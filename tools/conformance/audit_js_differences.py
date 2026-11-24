"""Match a complete Test262 language mismatch report to reviewed case-level fingerprints."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[2] / "docs/conformance/ecmascript-2024-deviations.tsv"
PROPOSALS = {"decorators", "source-phase-imports", "import-assertions", "import-attributes"}
CALL_TESTS = {"direct-callexpression-arguments", "parenthesized-callexpression-arguments"}


def classify(row):
    if row["orion"] is not False:
        return "unreviewed"
    proposals = PROPOSALS.intersection(row["features"])
    if len(proposals) == 1:
        return proposals.pop()
    source = row["file"].removeprefix("language/expressions/assignmenttargettype/").removesuffix(".js")
    if source in CALL_TESTS and row["expected"] is False and row["node"] is True:
        return "node-call-assignment"
    return "unreviewed"


def fingerprints(report):
    groups = {}
    with report.open() as stream:
        for line in stream:
            row = json.loads(line)
            # Include diagnostics, mode and all three outcomes in each pin.
            record = json.dumps(row, sort_keys=True, separators=(",", ":"))
            groups.setdefault(classify(row), []).append(record)
    return {key: (len(records), hashlib.sha256("\n".join(sorted(records)).encode()).hexdigest())
            for key, records in groups.items()}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("report", type=Path)
    args = cli.parse_args()
    with LEDGER.open() as stream:
        known = {r["classification"]: (int(r["cases"]), r["sha256"]) for r in csv.DictReader(stream, delimiter="\t")}
    actual = fingerprints(args.report)
    for key in sorted(actual.keys() | known.keys()):
        print(key, actual.get(key, (0, None))[0], "matched" if actual.get(key) == known.get(key) else "requires review")
    return int(actual != known)


if __name__ == "__main__":
    raise SystemExit(main())
