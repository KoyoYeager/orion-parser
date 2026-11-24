"""Cross-check the C17 ballot inventory against WG14's first marked-up successor."""
import argparse
import csv
import hashlib
import re
import subprocess
from pathlib import Path

from c_family_inventory import c17_rules, SOURCES
from check_c17 import ROOT
from orionparser.languages.c.lexer import CParseError
from orionparser.languages.c.pipeline import CPipeline


def read_rules(path, digest, document):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"unexpected {document} digest")
    rules = {}
    for name, section, alternatives in list(c17_rules(data, document)):
        key = (name, section.split()[-1])
        if key in rules:
            raise ValueError(f"duplicate {key}")
        rules[key] = [" ".join(rhs.split()) for rhs in alternatives]
    return rules


def check_identifier_ranges(ballot):
    layout = subprocess.check_output(["pdftotext", "-layout", str(ballot), "-"], text=True)
    annex = layout.rsplit("D.1     Ranges of characters allowed", 1)[1]
    allowed, initial = annex.split("D.2     Ranges of characters disallowed initially", 1)
    initial = initial.split("§ D.2", 1)[0]

    def ranges(text):
        pattern = r"([0-9A-F]{4,6})(?:–\s*([0-9A-F]{4,6}))?"
        return [(int(a, 16), int(b or a, 16)) for a, b in re.findall(pattern, text)]

    valid, noninitial = ranges(allowed), ranges(initial)
    if len(valid) != 45 or len(noninitial) != 4:
        raise ValueError(f"unexpected Annex D extraction: {len(valid)}, {len(noninitial)}")
    boundaries = {point for lo, hi in valid + noninitial for point in (lo-1, lo, hi, hi+1)}
    pipeline = CPipeline()
    count = 0
    for cp in sorted(boundaries):
        allowed_here = any(lo <= cp <= hi for lo, hi in valid)
        for prefix in ("", "x"):
            accept = allowed_here and (bool(prefix) or not any(lo <= cp <= hi for lo, hi in noninitial))
            for spelling in (chr(cp), f"\\U{cp:08x}"):
                source = f"int {prefix}{spelling};"
                try:
                    tree = pipeline.parse(source)
                except CParseError:
                    if accept:
                        raise ValueError(f"rejected valid Annex D spelling {source!r}")
                else:
                    name = tree["declarations"][0]["declarators"][0]["declarator"]["name"]
                    if not accept or name != prefix + chr(cp):
                        raise ValueError(f"unexpected identifier {name!r} for {source!r}")
                count += 1
    print(f"{count} Annex D identifier boundary cases checked")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ballot", type=Path)
    parser.add_argument("successor", type=Path)
    args = parser.parse_args()
    ballot = read_rules(args.ballot, SOURCES["c17"][1], "N2176")
    successor = read_rules(args.successor, "6a01dfbfd271a2b6682e48a13a68cf4b599beb3b7e39512bc74989d0b5991029", "N2310")
    expected = [(name, str(i), "N2176 " + section, hashlib.sha256(rhs.encode()).hexdigest())
                for (name, section), rhss in ballot.items() for i, rhs in enumerate(rhss, 1)]
    with (ROOT / "docs/conformance/c17.tsv").open() as stream:
        actual = [tuple(row.values()) for row in csv.DictReader(stream, delimiter="\t")]
    if expected != actual or ballot.keys() != successor.keys():
        raise ValueError("ballot inventory or successor production set differs")
    assertion = "_Static_assert ( constant-expression , string-literal ) ;"
    changes = {key: (rhs, successor[key]) for key, rhs in ballot.items() if rhs != successor[key]}
    if changes != {
        ("hexadecimal-prefix", "6.4.4.1"): (["0X", "0X"], ["0x", "0X"]),
        ("lparen", "6.10"): (["a ( character not immediately preceded by white-space"],
                              ["a ( character not immediately preceded by white space"]),
        ("static_assert-declaration", "6.7.10"): ([assertion], [assertion, "_Static_assert ( constant-expression ) ;"]),
    }:
        raise ValueError(f"unexpected revision changes: {changes}")
    check_identifier_ranges(args.ballot)
    print(f"{len(ballot)} productions, {len(expected)} C17 alternatives, 3 classified revision differences")


if __name__ == "__main__":
    main()
