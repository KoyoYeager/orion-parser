"""Check each linked Annex A example against the production index and Acorn's AST."""
import argparse
import csv
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

from orionparser.languages.javascript import pipeline
from orionparser.languages.javascript.pipeline import Grammar, JavaScriptModulePipeline, JavaScriptPipeline
from orionparser.languages.javascript.regexp import PatternGrammar
from orionparser.languages.javascript.regexp_sets import SetGrammar

from check_js_acorn import DIGEST

ROOT = Path(__file__).resolve().parents[2] / "docs/conformance"
_ORACLE = """
const acorn = require(process.argv[1]);
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const result = cases.map(({src, goal}) => {
    try {
        return acorn.parse(src, {ecmaVersion: 2024, sourceType: goal});
    } catch (err) {
        if (!(err instanceof SyntaxError)) throw err;
        return null;
    }
});
process.stdout.write(JSON.stringify(result, (key, value) =>
    typeof value === 'bigint' ? value.toString() : value));
"""


def canonical(node):
    if isinstance(node, list):
        return [canonical(child) for child in node]
    if not isinstance(node, dict):
        return node
    kind = node.get("type")
    if kind in {"NumericLiteral", "BigIntLiteral"} or (kind == "Literal" and
            ("bigint" in node or type(node.get("value")) in {float, int})):
        return {"type": "Number", "raw": node["raw"]}
    if kind == "RegExpLiteral" or kind == "Literal" and "regex" in node:
        regex = node.get("regex", node)
        return {"type": "RegExpLiteral", "pattern": regex["pattern"], "flags": regex["flags"]}
    result = {key: canonical(value) for key, value in node.items()
              if key not in {"start", "end", "loc", "range", "directive"}}
    if kind == "Literal":
        # Both representations retain the cooked value; Acorn also includes raw
        # spelling on null and Boolean literals.
        if type(result.get("value")) in {bool, type(None)}:
            result.pop("raw", None)
    if kind in {"FunctionExpression", "FunctionDeclaration"}:
        result.setdefault("expression", False)
    if kind in {"CallExpression", "MemberExpression"}:
        result.setdefault("optional", False)
    return result


def acorn_asts(archive_path, cases):
    with archive_path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != DIGEST:
            raise ValueError("Acorn archive checksum mismatch")
    with tempfile.TemporaryDirectory() as directory, tarfile.open(archive_path) as archive:
        library = Path(directory) / "acorn.cjs"
        library.write_bytes(archive.extractfile("package/dist/acorn.js").read())
        oracle = subprocess.check_output(["node", "-e", _ORACLE, str(library)], text=True, input=json.dumps(cases))
    return json.loads(oracle)


def handler_for(symbol):
    if "." in symbol:
        owner, method = symbol.split(".", 1)
        return getattr({"PatternGrammar": PatternGrammar, "SetGrammar": SetGrammar, "pipeline": pipeline}[owner], method)
    return getattr(Grammar, symbol)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("acorn_archive", type=Path)
    cli.add_argument("--supplement", action="store_true", help="Check Annex B productions and ASI obligations")
    args = cli.parse_args()
    if args.supplement:
        with (ROOT / "ecmascript-2024-constraints.tsv").open() as stream:
            inventory = {(r["section_anchor"], r["item"]) for r in csv.DictReader(stream, delimiter="\t")
                         if r["category"] in {"AnnexB-production", "ASI"}}
        examples = "ecmascript-2024-supplement-examples.tsv"
    else:
        with (ROOT / "ecmascript-2024.tsv").open() as stream:
            inventory = {(r["rule"], r["alternative"]) for r in csv.DictReader(stream, delimiter="\t")
                         if r["section"] not in {"sec-number-conversions", "sec-time-zone-offset-string-format"}}
        examples = "ecmascript-2024-examples.tsv"
    cases = []
    targets = set()
    with (ROOT / examples).open() as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            target = row["rule"], row["alternative"]
            handler = handler_for(row["action"])
            if target not in inventory or not (inspect.isfunction(handler) or row["action"] == "t_ignore"):
                raise ValueError(f"Invalid evidence link: {row}")
            targets.add(target)
            for goal in (["script", "module"] if row["goal"] == "both" else [row["goal"]]):
                cases.append({"src": json.loads(row["source_json"]), "goal": goal,
                              "target": target, "probe": json.loads(row["probe"]) if row.get("probe") else None, "action": row["action"], "valid": row["outcome"] == "accept"})
    reference_asts = acorn_asts(args.acorn_archive, cases)
    failures = 0
    script, module = JavaScriptPipeline(), JavaScriptModulePipeline()
    for case, reference in zip(cases, reference_asts, strict=True):
        called = False
        handler = handler_for(case["action"])

        def trace(frame, event, arg):
            nonlocal called
            if event == "call" and frame.f_code is handler.__code__:
                called = True

        if inspect.isfunction(handler):
            sys.setprofile(trace)
        else:
            called = any(char in handler for char in case["src"])
        try:
            actual = (module if case["goal"] == "module" else script).parse(case["src"])
        except ValueError:
            actual = None
        finally:
            sys.setprofile(None)
        probe_ok = True
        if case["probe"] and actual is not None:
            path, expected = case["probe"]
            part = actual
            for step in path:
                part = part[step]
            probe_ok = part == expected
        if not probe_ok or not called or case["valid"] != (reference is not None) or canonical(actual) != canonical(reference):
            failures += 1
            print(case, "handler reached", called, "Orion", canonical(actual), "Acorn", canonical(reference))
    print(f"{len(targets)}/{len(inventory)} indexed alternatives have linked examples; "
          f"{len(cases)} goal-specific comparisons; {failures} discrepancies")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
