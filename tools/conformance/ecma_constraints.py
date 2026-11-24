# /// script
# requires-python = ">=3.12"
# dependencies = ["beautifulsoup4==4.13.4"]
# ///
"""Index early-error bullets, ASI rules and supplemental Annex B grammar in ECMA-262."""
import csv
import hashlib
import sys
from urllib.request import urlopen

from bs4 import BeautifulSoup

URL = "https://tc39.es/ecma262/2024/"
DIGEST = "e3ad72f7d7b8785d6cb6f5d496221e7a0cc01c4809a1478c538e38df0f033f9a"


def normalized(node):
    return " ".join(node.stripped_strings)


def main():
    with urlopen(URL) as response:
        page = response.read()
    if hashlib.sha256(page).hexdigest() != DIGEST:
        raise ValueError("Unexpected ECMA-262 edition digest")
    document = BeautifulSoup(page, "html.parser")
    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow(["category", "section_anchor", "item", "productions", "text_sha256"])

    def emit(category, clause, nodes):
        for index, (node, productions) in enumerate(nodes, 1):
            digest = hashlib.sha256(normalized(node).encode()).hexdigest()
            writer.writerow([category, clause["id"], index, ",".join(productions), digest])

    for clause in document.find_all(["emu-clause", "emu-annex"]):
        title = clause.find("h1", recursive=False)
        if title is None:
            continue
        if normalized(title).endswith("Static Semantics: Early Errors"):
            entries = []
            productions = []
            for child in clause.find_all(recursive=False):
                if child.name == "emu-grammar":
                    productions = [p["name"] for p in child.find_all("emu-production")]
                elif child.name == "ul":
                    entries.extend((item, productions) for item in child.find_all("li", recursive=False))
            emit("early-error", clause, entries)
        if clause["id"] == "sec-rules-of-automatic-semicolon-insertion":
            entries = [(item, []) for item in clause.select(":scope > ol > li, :scope > ul > li")]
            entries.extend((p, []) for p in clause.find_all("p", recursive=False)
                           if "overriding condition" in normalized(p))
            emit("ASI", clause, entries)

    annex = document.select_one('emu-annex[namespace="annexB"]')
    for clause in annex.find_all(["emu-annex", "emu-clause"]):
        entries = []
        for production in clause.select(":scope > emu-grammar[type=definition] > emu-production"):
            for rhs in production.select(":scope > emu-rhs"):
                alternatives = rhs.find_all("emu-t", recursive=False) if production.has_attr("oneof") else [rhs]
                entries.extend((alt, [production["name"]]) for alt in alternatives)
        emit("AnnexB-production", clause, entries)


if __name__ == "__main__":
    main()
