"""Reduce pinned TypeScript parse-acceptance differences to reproducible witnesses."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

from check_typescript import COMPILER_SHA, SOURCE_SHA, _CHECKER, check_pin, run_compiler, source_cases
from orionparser.languages.typescript.pipeline import TypeScriptPipeline

_ORACLE = """
const ts = require(process.argv[1]);
require('node:readline').createInterface({input: process.stdin}).on('line', line => {
    const {name, source, tokens, position} = JSON.parse(line);
    const file = ts.createSourceFile(name, source, ts.ScriptTarget.ESNext, true);
    let result = !file.parseDiagnostics.length;
    if (position !== null && result) {
        const fragments = new Set();
        for (let n = ts.getTokenAtPosition(file, position); n && n !== file; n = n.parent) {
            const text = n.getText(file);
            fragments.add(text);
            if (ts.isCatchClause(n)) fragments.add('try{}' + text);
            if (ts.isClassElement(n)) fragments.add('class C{' + text + '}');
            if (ts.isTypeElement(n)) fragments.add('interface T{' + text + '}');
            if (ts.isTypeNode(n)) fragments.add('type T=' + text);
        }
        result = [...fragments].filter(text => text.length < source.length)
                              .sort((a,b) => a.length - b.length);
    }
    if (tokens && result) {
        const leaves = [];
        const stack = [file];
        while (stack.length) {
            const n = stack.pop(), children = n.getChildren(file);
            if (children.length) {
                for (let i=children.length-1; i>=0; --i) stack.push(children[i]);
            } else if (n.end > n.pos) leaves.push(source.slice(n.pos, n.end));
        }
        result = leaves;
    }
    process.stdout.write(JSON.stringify(result) + '\\n');
});
"""


def reason(error):
    return re.sub(r"^line \d+, column \d+: (?:unexpected )?", "", str(error))


# Compiler diagnostic codes with a direct counterpart in Orion's rejection.
# A coincident diagnostic on the same source line is otherwise left unclassified.
_CHECKER_COUNTERPARTS = {
    "optional binding pattern in implementation": {2463},
    "invalid jump target": {1107, 1104, 1105, 1115, 1116},
    "duplicate export default": {2528},
    "duplicate constructor": {2392},
    "static element named prototype": {2699},
    "with statement in strict code": {1101},
    "strict directive with non-simple parameters": {1346, 1347},
    "invalid update target": {2357},
    "invalid assignment target": {2364},
    "multiple iteration bindings": {1091, 1188},
    "delete of an unqualified identifier": {1102},
    "setter requires one non-rest parameter": {1049, 1053},
    "getter with parameters": {1054},
    "using declaration with a binding pattern": {1492},
    "using declaration in for-in": {1493},
    "invalid strict binding": {1100},
    "invalid strict assignment target": {1100},
    "binding pattern without initializer": {1182},
    "const without initializer": {1155},
    "invalid async function expression name": {1359},
    "invalid new.target": {17013},
    "invalid super call": {2337},
    "undeclared private name": {18013, 18016},
    "rest parameter must be last": {1013, 1014},
}


def counterpart_codes(reason_text, original, reduced, filename):
    shared = {tuple(d) for d in original}.intersection(tuple(d) for d in reduced)
    allowed = _CHECKER_COUNTERPARTS.get(reason_text, set())
    matches = {code for code, _ in shared if code in allowed}
    if reason_text == "'<'" and filename.lower().endswith((".mts", ".cts")):
        matches.update(code for code, _ in shared if code in {7059, 7060})
    identifier = re.fullmatch(r"'([a-z]+)'|reserved identifier ([a-z]+)", reason_text)
    if identifier:
        name = identifier[1] or identifier[2]
        for code, message in shared:
            if code in {1212, 1213, 1214, 1262, 1359} and f"'{name}' is a reserved word" in message:
                matches.add(code)
    private = re.fullmatch(r"duplicate private name (#[^ ]+)", reason_text)
    if private and (2300, f"Duplicate identifier '{private[1]}'.") in shared:
        matches.add(2300)
    return sorted(matches)


def shrink(parts, matches):
    """Delta-debug a sequence, then confirm that no single part can be dropped."""
    granularity = 2
    while len(parts) > 1:
        step = (len(parts) + granularity - 1) // granularity
        for first in range(0, len(parts), step):
            candidate = parts[:first] + parts[first+step:]
            if candidate and matches("".join(candidate)):
                parts = candidate
                granularity = max(2, granularity - 1)
                break
        else:
            if granularity >= len(parts):
                break
            granularity = min(len(parts), granularity * 2)
    return "".join(parts)


def reduce_candidates(source, name, detail, oracle, keep_context):
    pipeline = TypeScriptPipeline(name)
    goal = reason(detail)

    def matches(text):
        try:
            pipeline.parse(text)
        except ValueError as exc:
            return reason(exc) == goal and oracle(name, text, False)
        except Exception:
            return False
        return False

    if not matches(source):
        raise ValueError(f"Stale report for {name}: {detail}")
    starts = [source] if keep_context else []
    # A complete enclosing declaration often removes unrelated balanced blocks
    # that cannot be deleted a single line or token at a time.
    try:
        pipeline.parse(source)
    except ValueError as error:
        offset = getattr(error, "offset", None)
        if offset is not None:
            position = len(source[:offset].encode("utf-16-le", "surrogatepass")) // 2
            for fragment in oracle(name, source, False, position):
                if matches(fragment):
                    source = fragment
                    break
    starts.append(source)
    results = set()
    for start in dict.fromkeys(starts):
        smaller = shrink(start.splitlines(keepends=True), matches)
        pieces = oracle(name, smaller, True)
        if isinstance(pieces, list) and "".join(pieces) == smaller:
            smaller = shrink(pieces, matches)
        trimmed = smaller.strip()
        if trimmed != smaller and matches(trimmed):
            smaller = trimmed
        results.add(smaller)
    return sorted(results, key=lambda text: (len(text), text))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    cli.add_argument("corpus", type=Path)
    cli.add_argument("report", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("--checker", action="store_true", help="Record checker codes on the reduced diagnostic line")
    cli.add_argument("--selection", default=".", help="Use the same fixture selection as the reported comparison")
    args = cli.parse_args()
    check_pin(args.compiler, COMPILER_SHA)
    check_pin(args.corpus, SOURCE_SHA)
    rows = [json.loads(line) for line in args.report.read_text().splitlines()]
    selected = {(r["fixture"], r["name"]) for r in rows}
    originals = {(c["file"], c["name"]): c["source"] for c in source_cases(args.corpus, args.selection)
                 if (c["file"], c["name"]) in selected}
    if len(originals) != len(selected):
        raise ValueError("Corpus/report file lists differ")
    counts = Counter()
    entries, checker_cases, original_checks = [], [], []
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(args.compiler) as tar:
        compiler = Path(tmp) / "typescript.cjs"
        compiler.write_bytes(tar.extractfile("package/lib/typescript.js").read())
        with subprocess.Popen(["node", "-e", _ORACLE, str(compiler)], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True) as proc:
            def oracle(name, text, tokens, position=None):
                proc.stdin.write(json.dumps({"name": name, "source": text, "tokens": tokens, "position": position}) + "\n")
                proc.stdin.flush()
                return json.loads(proc.stdout.readline())
            try:
                for row in rows:
                    if row["category"] != "acceptance" or row["orion"] is not False or row["referenceDiagnostics"]:
                        counts["other outcomes"] += 1
                        continue
                    key = row["fixture"], row["name"]
                    text = originals[key]
                    detail = reason(row["detail"])
                    original = row.get("checkerDiagnosticsOnLine", [])
                    keep_context = args.checker and bool(counterpart_codes(detail, original, original, key[1]))
                    for reduced in reduce_candidates(text, key[1], row["detail"], oracle, keep_context):
                        entries.append([*key, len(text), len(reduced), detail, json.dumps(reduced)])
                        if args.checker:
                            original_checks.append(original)
                            try:
                                TypeScriptPipeline(key[1]).parse(reduced)
                            except ValueError as exc:
                                position = re.match(r"line (\d+), column ", str(exc))
                                if not position:
                                    raise ValueError(f"Unpositioned diagnostic for {key}") from exc
                                checker_cases.append({"name": key[1], "source": reduced, "line": int(position[1])})
                            else:
                                raise ValueError(f"Reduced source unexpectedly accepted: {key}")
            finally:
                proc.stdin.close()
    columns = ["fixture", "virtual_file", "original_chars", "reduced_chars", "diagnostic", "source_json"]
    if args.checker:
        columns.extend(["reduced_checker_codes_on_line", "matched_checker_counterparts"])
        reduced_checks = run_compiler(args.compiler, _CHECKER, checker_cases)
        for entry, original, reduced in zip(entries, original_checks, reduced_checks, strict=True):
            entry.append(",".join(map(str, sorted({d[0] for d in reduced}))))
            matched = counterpart_codes(entry[4], original, reduced, entry[1])
            entry.append(",".join(map(str, matched)))
        # Prefer preserving a corroborated diagnostic over deleting its context.
        best = {}
        for entry in entries:
            key = tuple(entry[:2])
            score = (not bool(entry[-1]), entry[3])
            if key not in best or score < best[key][0]:
                best[key] = score, entry
        entries = [entry for _, entry in best.values()]
        counts["matched checker counterparts"] = sum(bool(entry[-1]) for entry in entries)
    counts["witnesses"] = len(entries)
    counts["original characters"] = sum(entry[2] for entry in entries)
    counts["reduced characters"] = sum(entry[3] for entry in entries)
    with args.output.open("w", encoding="utf-8") as out:
        writer = csv.writer(out, delimiter="\t", lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(entries)
    print(dict(counts))


if __name__ == "__main__":
    main()
