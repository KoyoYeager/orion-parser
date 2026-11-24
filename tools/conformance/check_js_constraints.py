"""Check paired valid/invalid sources against pinned ECMA-262 early-error clauses."""
import argparse
import csv
import json
from pathlib import Path
import re

from check_js_examples import ROOT, acorn_asts, canonical
from orionparser.languages.javascript.pipeline import JavaScriptModulePipeline, JavaScriptPipeline


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("acorn_archive", type=Path)
    args = cli.parse_args()
    with (ROOT / "ecmascript-2024-constraints.tsv").open() as stream:
        inventory = {(r["section_anchor"], r["item"]) for r in csv.DictReader(stream, delimiter="\t")
                     if r["category"] == "early-error"}
    tested = set()
    cases = []
    with (ROOT / "ecmascript-2024-early-error-examples.tsv").open() as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            key = row["section_anchor"], row["item"]
            if key not in inventory:
                raise ValueError(key)
            tested.add(key)
            for field in ("valid", "invalid"):
                cases.append({"src": json.loads(row[field]), "goal": row["goal"], "obligation": key,
                              "valid": field == "valid"})
    oracle = acorn_asts(args.acorn_archive, cases)
    failures = 0
    for case, expected in zip(cases, oracle, strict=True):
        src = case["src"]
        try:
            parser = JavaScriptModulePipeline() if case["goal"] == "module" else JavaScriptPipeline()
            actual, diagnostic = parser.parse(src), ""
        except ValueError as exc:
            actual, diagnostic = None, str(exc)
        if ((expected is not None) != case["valid"] or canonical(actual) != canonical(expected)
                or (actual is None and not re.match(r"line [1-9]\d*, column [1-9]\d*:", diagnostic))):
            print(case["obligation"], case["goal"], ascii(src), "Acorn", expected is not None,
                  "Orion", diagnostic or "accepted")
            failures += 1
    print(f"{len(tested)}/{len(inventory)} early-error items have paired source checks; "
          f"{len(cases)} comparisons; {failures} discrepancies")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
