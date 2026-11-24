# /// script
# requires-python = ">=3.12"
# dependencies = ["beautifulsoup4==4.13.4"]
# ///
"""Print a TSV index of the pinned ECMA-262 Annex A grammar."""
import csv
import hashlib
import sys
from urllib.request import urlopen

from bs4 import BeautifulSoup

URL = "https://tc39.es/ecma262/2024/multipage/grammar-summary.html"
DIGEST = "bf518fed5efd944a9edebcde65031505b39e34dcd98d2cf088a4f4585b20c29d"


def main():
    with urlopen(URL) as response:
        page = response.read()
    if hashlib.sha256(page).hexdigest() != DIGEST:
        raise SystemExit("Source changed. Review the edition and diff before updating the pin.")
    document = BeautifulSoup(page, "html.parser")
    output = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    output.writerow(["rule", "parameters", "alternative", "source", "rhs", "section"])
    for production in document.select("emu-production:not(.inline)"):
        anchor = production.select_one("emu-nt > a")["href"]
        alternatives = production.select(":scope > emu-rhs")
        if production.has_attr("oneof"):
            alternatives = production.select(":scope > emu-rhs > emu-t")
        if not alternatives:
            raise ValueError(production["name"])
        for index, rhs in enumerate(alternatives, 1):
            output.writerow([
                production["name"], production.get("params", ""), index, anchor,
                " ".join(rhs.stripped_strings), production.find_parent("emu-annex")["id"],
            ])


if __name__ == "__main__":
    main()
