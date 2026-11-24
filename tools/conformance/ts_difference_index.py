"""Print a compact index of the remaining cases in a TypeScript --checker --report run."""
import argparse
import csv
import json
from pathlib import Path
import sys


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("report", type=Path)
    cli.add_argument("--configured", action="store_true", help="Index a fixture-option matrix report")
    args = cli.parse_args()
    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    if args.configured:
        writer.writerow(["fixture", "virtual_file", "options_json", "category", "reference_codes", "detail"])
        for line in args.report.read_text().splitlines():
            row = json.loads(line)
            codes = row.get("codes", [d["code"] for d in row.get("referenceDiagnostics", [])])
            writer.writerow([row["file"], row["name"], json.dumps(row["options"], sort_keys=True), row["category"],
                             ",".join(map(str, codes)), row.get("detail", "")])
        return
    writer.writerow(["fixture", "virtual_file", "difference", "parse_codes", "checker_codes_on_line", "orion"])
    for line in args.report.read_text().splitlines():
        row = json.loads(line)
        diagnostics = row.get("referenceDiagnostics", [])
        codes = sorted({d[0] for d in row.get("checkerDiagnosticsOnLine", [])})
        writer.writerow([row["fixture"], row["name"], row["category"],
                         ",".join(str(d["code"]) for d in diagnostics), ",".join(map(str, codes)),
                         row.get("detail", "top-level kind/name difference")])


if __name__ == "__main__":
    main()
