"""Trace both sides of inventoried TypeScript predicates and compare their example ASTs."""
import argparse
import csv
import json
from pathlib import Path
import re
import sys
import tarfile

from orionparser.languages.javascript.pipeline import SourceSyntaxError
from orionparser.languages.typescript.config import parse_config
from orionparser.languages.typescript.options import SyntaxOptions

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, SOURCE_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler


DOCS = Path(__file__).resolve().parents[2] / "docs/conformance"


def rows(filename):
    with (DOCS / filename).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    cli.add_argument("source_archive", type=Path)
    args = cli.parse_args()
    check_pin(args.compiler, COMPILER_SHA)
    check_pin(args.source_archive, SOURCE_SHA)
    inventory = {(r["source"], r["function"], r["line:column"]): r["branch locations"].split("; ")
                 for r in rows("typescript-5.9.tsv")}
    examples = rows("typescript-5.9-branch-examples.tsv")
    sites, site_ids, cases, required = [], {}, [], {}
    for row in examples:
        options = json.loads(row.pop("compiler_options_json", None) or "{}")
        if None in row or None in row.values() or not row["filename"]:
            raise ValueError(f"Incomplete witness at {row.get('branch_location')}")
        owner = row["file"], row["function"], row["function_location"]
        location = row["branch_location"]
        boolean = location + "=true/false" in inventory[owner]
        choice = None if boolean else row["outcome"]
        if not boolean and ((choice != "default" and not choice.startswith(("SyntaxKind.", "ScriptKind.", "ParsingContext.", "ClassSetExpressionType.", "CharacterCodes.", '"'))) or location + "=" + choice not in inventory[owner]):
            raise ValueError(f"Unknown branch outcome {owner} {location} {row['outcome']}")
        key = (*owner, location)
        if key not in site_ids:
            site_ids[key] = len(sites)
            sites.append({"file": owner[0], "owner": owner[1], "ownerLocation": owner[2], "location": location, "choice": choice})
        idx = site_ids[key]
        if boolean:
            required.setdefault(idx, set()).add(row["outcome"])
        if row["target"] not in {"ESNext", "ES5", "ES2015"}:
            raise ValueError(f"Unknown target {row['target']}")
        cases.append({"options": {**options, "target": row["target"].lower()}, "target": row["target"], "name": row["filename"], "source": json.loads(row["source_json"]), "projection": row["projection"],
                      "diagnosticSpans": bool(row["reference_diagnostics_json"])})
    if any(outcomes != {"true", "false"} for outcomes in required.values()):
        raise ValueError("Each listed predicate requires a witness for both outcomes")
    with tarfile.open(args.source_archive) as archive:
        sources = {name: archive.extractfile("TypeScript-5.9.3/src/compiler/" + name).read().decode()
                   for name in {s["file"] for s in sites}}
    grammar_oracle = Path(__file__).with_name("ts_grammar_diagnostics.cjs").read_text()
    traces = run_compiler(args.compiler, grammar_oracle + Path(__file__).with_name("ts_branch_oracle.cjs").read_text(),
                          {"cases": cases, "sites": sites, "sources": sources})
    oracle = grammar_oracle + _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    trees = run_compiler(args.compiler, oracle, cases)
    failures = 0
    for row, case, trace, ref in zip(examples, cases, traces, trees, strict=True):
        symbol = row["implementation"]
        called = False

        def record(frame, event, arg):
            nonlocal called
            if event == "call" and frame.f_code.co_name == symbol and frame.f_globals.get("__name__", "").startswith("orionparser.languages."):
                called = True

        tree, offset, diagnostic, location = None, None, None, None
        collect_tokens = case["projection"] == "tokens and expression"
        tokens = []
        sys.setprofile(record)
        try:
            pipeline = TypeScriptPipeline(case["name"])
            pipeline.syntax_options = SyntaxOptions.from_compiler_options(case["options"])
            if case["projection"] in {"project config", "project source"}:
                tree = parse_config(case["source"])
            else:
                tree = pipeline._parse(case["source"], tokens) if collect_tokens else pipeline.parse(case["source"])
        except SourceSyntaxError as error:
            offset = error.offset
            if case["projection"] == "diagnostic location":
                position = re.match(r"line (\d+), column (\d+):", str(error))
                if position:
                    location = [int(value) for value in position.groups()]
            if error.code is not None:
                diagnostic = [error.code, error.offset, error.length]
        finally:
            sys.setprofile(None)
        expected_diagnostics = json.loads(row["reference_diagnostics_json"] or "[]")
        if bool(expected_diagnostics) != bool(row["orion_error_offset"]):
            raise ValueError("Rejected witnesses require both compiler diagnostics and an Orion error offset")
        if expected_diagnostics:
            actual = offset
            agrees = tree is None and offset == int(row["orion_error_offset"]) and ref.get("invalid") is True
            if case["projection"] == "diagnostic location":
                actual = [diagnostic, location]
                agrees = (agrees and diagnostic == expected_diagnostics[0] and location == ref["cliLocation"]
                          and trace["location"] == ref["location"])
            elif case["projection"] in {"file context", "implied file context"}:
                agrees = agrees and diagnostic == expected_diagnostics[0]
            elif diagnostic is not None:
                agrees = agrees and diagnostic in expected_diagnostics
        else:
            label = "target expression" if collect_tokens else case["projection"]
            actual = ([tree] if label in {"project config", "project source"} else project_trees(tree, label)) if tree is not None else None
            agrees = bool(actual) and actual == ref.get("trees")
            if label in {"function grammar", "import grammar"}:
                agrees = agrees and trace["grammar"] == ref["grammar"]
            if collect_tokens:
                agrees = agrees and [[t["value"], t["offset"], t["line"]] for t in tokens] == ref.get("tokens")
        diagnostics_match = trace["parse"] == ref.get("diagnostics", []) == expected_diagnostics
        site = site_ids[row["file"], row["function"], row["function_location"], row["branch_location"]]
        if not diagnostics_match or f"{site}:{row['outcome']}" not in trace["hits"] or not called or not agrees:
            failures += 1
            print(case, row["branch_location"], trace, "action executed", called, actual, ref)
    print(f"{len(required)} predicates, {len(sites) - len(required)} switch cases, {len(cases)} branch witnesses, {failures} failed checks")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
