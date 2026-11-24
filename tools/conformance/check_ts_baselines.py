"""Locate the compiler's checked-in error baselines for each Orion rejection."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import posixpath
import re
import tarfile

from check_typescript import SOURCE_SHA, check_pin, source_cases

_HEADER = re.compile(r"^(.+?)\((\d+),(\d+)\): error TS(\d+): (.*)$")
_SECTION = re.compile(r"^==== (.*?) \(\d+ errors?\) ====$")
_PREFIX = "TypeScript-5.9.3/tests/baselines/reference/"


def norm(name):
    return posixpath.normpath("/" + name.replace("\\", "/")).lstrip("/")


def baseline_details(text):
    """Extract diagnostic summary locations and rendered source by virtual file."""
    diagnostics, text_by_file = defaultdict(list), defaultdict(list)
    section = None
    for line in text.splitlines():
        title = _SECTION.fullmatch(line)
        if title:
            section = norm(title[1])
        elif section is None:
            record = _HEADER.match(line)
            if record:
                diagnostics[norm(record[1])].append((int(record[2]), int(record[4]), record[5]))
        elif line.startswith("    "):
            text_by_file[section].append(line[4:].rstrip())
    return diagnostics, text_by_file


def source_matches(lines, rendered):
    """Verify all non-empty input lines in order, allowing inserted squiggles."""
    remaining = iter(rendered)
    return all(any(candidate == line for candidate in remaining) for line in lines)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("corpus", type=Path)
    cli.add_argument("report", type=Path)
    cli.add_argument("ledger", type=Path, help="Reduced witnesses with checker counterparts")
    cli.add_argument("output", type=Path)
    cli.add_argument("--selection", default=".", help="Use the same fixture selection as the reported comparison")
    args = cli.parse_args()
    check_pin(args.corpus, SOURCE_SHA)
    rows = [json.loads(line) for line in args.report.read_text().splitlines()]
    with args.ledger.open() as stream:
        confirmed = {(r["fixture"], r["virtual_file"]): set(filter(None, r["matched_checker_counterparts"].split(",")))
                     for r in csv.DictReader(stream, delimiter="\t")}
    keys = {(r["fixture"], r["name"]) for r in rows if r["category"] == "acceptance"
            and r["orion"] is False and not r["referenceDiagnostics"]}
    if keys != set(confirmed):
        raise ValueError("Reduced ledger and mismatch report refer to different cases")
    wanted = defaultdict(list)
    sources = {(r["file"], r["name"]): r["source"] for r in source_cases(args.corpus, args.selection)
               if (r["file"], r["name"]) in confirmed}
    results = {}
    for row in rows:
        key = row["fixture"], row["name"]
        position = re.match(r"line (\d+), column ", row.get("detail", ""))
        if key not in sources or not position:
            continue
        number = int(position[1])
        lines = re.split(r"\r\n|[\r\n\u2028\u2029]", sources[key])
        wanted[Path(key[0]).stem].append((key, number, lines[number-1].rstrip(),
                                          [line.rstrip() for line in lines if line.strip()]))
        results[key] = {"seen": [], "file": [], "line": [], "codes": set(), "confirmed": set()}
    with tarfile.open(args.corpus) as tar:
        for member in tar:
            if not member.isfile() or not member.name.startswith(_PREFIX):
                continue
            short = member.name.removeprefix(_PREFIX)
            if "/" in short or not short.endswith(".errors.txt"):
                continue
            tag = short.removesuffix(".errors.txt").split("(", 1)[0]
            if tag not in wanted:
                continue
            diagnostics, rendered = baseline_details(tar.extractfile(member).read().decode("utf-8-sig"))
            for key, line, source_line, input_lines in wanted[tag]:
                result = results[key]
                result["seen"].append(short)
                name = norm(key[1])
                matches = [name] if name in rendered else [f for f in rendered if f.endswith("/" + name)]
                if len(matches) != 1:
                    continue
                f = matches[0]
                result["file"].append(short)
                if not source_line.strip() or not source_matches(input_lines, rendered[f]):
                    continue
                codes = {str(code) for n, code, _ in diagnostics[f] if n == line}
                if codes:
                    result["line"].append(short)
                    result["codes"].update(codes)
                    result["confirmed"].update(codes & confirmed[key])
    with args.output.open("w", encoding="utf-8") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["fixture", "virtual_file", "baseline_variants", "matched_virtual_file_variants",
                         "same_line_variants", "same_line_codes", "corroborated_checker_codes"])
        for key, result in results.items():
            writer.writerow([*key, len(result["seen"]), len(result["file"]), ";".join(sorted(result["line"])),
                             ",".join(sorted(result["codes"])), ",".join(sorted(result["confirmed"]))])
    print(f"{len(results)} cases; {sum(bool(r['file']) for r in results.values())} with a matching baseline file, "
          f"{sum(bool(r['codes']) for r in results.values())} with same-line baseline diagnostics, "
          f"{sum(bool(r['confirmed']) for r in results.values())} corroborating a reviewed checker counterpart")


if __name__ == "__main__":
    main()
