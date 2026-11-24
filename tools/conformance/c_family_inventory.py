# /// script
# requires-python = ">=3.12"
# dependencies = ["beautifulsoup4==4.13.4"]
# ///
"""Index grammar alternatives by source location; print TSV for c17 or cpp20."""
import argparse
import csv
import hashlib
import re
import subprocess
from pathlib import Path
import sys
from urllib.request import urlopen


SOURCES = {
    "c17": ("https://bolha.dev/blau_araujo/cblc/raw/commit/"
            "2bbee7c9ff6fcc10018015f100f5f27e24c0508b/c17/iso-iec-9899-2017.pdf",
            "092e6b30d661892b6d7a9f264f74b839e75e028976c81b28202fbbe62708da56"),
    "cpp20": ("https://timsong-cpp.github.io/cppwp/n4861/gram",
              "40d672251c51f776c571822a3d0ea7bdafaf49f9d6ffea073cea3ff1656f964f"),
}


def c17_rules(data, document="N2176"):
    text = subprocess.run(["pdftotext", "-layout", "-", "-"], input=data, capture_output=True,
                          check=True).stdout.decode()
    # Annex A.4 is a library input-string grammar, outside C translation units.
    annex = text.split("A.1.1 Lexical elements", 1)[1].split("A.4 Floating-point subject sequence", 1)[0]
    for line in annex.splitlines():
        item = line.strip()
        if not item or item.startswith("A.") or "Language syntax summary" in line or "C17 ballot" in line:
            continue
        if document == "N2310" and (item == "(E)" or set(item) == {":"}
                                    or any(marker in item for marker in ("ISO/IEC", "N2310", "diff marks"))):
            continue
        heading = re.fullmatch(r"\(([0-9.]+)\)\s+([A-Za-z_-]+):\s*(one of)?", item)
        if heading:
            section, rule, one_of = heading.groups()
            alternatives = []
            yield rule, document + " " + section, alternatives
        elif one_of:
            alternatives.extend(item.split())
        elif len(line) - len(line.lstrip()) >= 35:
            # Wrapped continuations in the fixed layout of the pinned ballot.
            alternatives[-1] += " " + item
        else:
            alternatives.append(item)


def cpp20_rules(data):
    from bs4 import BeautifulSoup

    doc = BeautifulSoup(data, "html.parser")
    for block in doc.select("pre.bnf"):
        for line in block.get_text().splitlines():
            if not line.strip():
                continue
            heading = re.fullmatch(r"([a-z0-9_-]+):(?: (one of))?", line)
            if heading:
                rule, one_of = heading.groups()
                alternatives = []
                yield rule, "gram#nt:" + rule, alternatives
            elif one_of:
                # Thin spaces inside the () and [] operator names are typographic.
                alternatives.extend(line.replace("\u2009", "").split())
            elif line.startswith("\t\t"):
                alternatives[-1] += " " + line.strip()
            else:
                alternatives.append(line.strip())


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("language", choices=SOURCES)
    cli.add_argument("--input", type=Path, help="Use a local copy of the pinned source")
    args = cli.parse_args()
    language = args.language
    url, digest = SOURCES[language]
    if args.input:
        data = args.input.read_bytes()
    else:
        with urlopen(url) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Unexpected source digest")
    rules = list(c17_rules(data) if language == "c17" else cpp20_rules(data))
    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow(["rule", "alternative", "source", "rhs_sha256"])
    seen = set()
    for name, source, alternatives in rules:
        if name in seen or not alternatives:
            raise ValueError("Empty or duplicate rule: " + name)
        seen.add(name)
        for index, alternative in enumerate(alternatives, 1):
            normalized = " ".join(alternative.split())
            writer.writerow([name, index, source, hashlib.sha256(normalized.encode()).hexdigest()])


if __name__ == "__main__":
    main()
