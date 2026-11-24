# /// script
# requires-python = ">=3.12"
# dependencies = ["beautifulsoup4==4.13.4"]
# ///
"""Index the alternatives of the Java SE 21 lexical and syntactic grammars."""
import argparse
import csv
import hashlib
from pathlib import Path
import sys
from urllib.request import urlopen

from bs4 import BeautifulSoup

BASE = "https://docs.oracle.com/javase/specs/jls/se21/html/"
PAGES = {
    "jls-3.html": "c3b6363bbb9407c9b950e15861ae6ebc4df55bee82ca9b5f7437fbcf28c34623",
    "jls-4.html": "0f243d22fbecd7b2eb36305e7e95d30de8acf8183c9742657be9472128d8f1ad",
    "jls-5.html": "a04756c50c03e52939388c42ba7518aeeb440fc8d0a72f85fd1acf1c4932a80f",
    "jls-6.html": "e33a342b27d265bec9fac354212e1d7192765de7f50a453cdf498fc31cc7ed36",
    "jls-7.html": "8cab9f48115ff54489071c03a41b449de2599316921a013085b053941faccfc6",
    "jls-8.html": "64d7f2d97da784e2642b1617ee23e007dc6d1c311f8d2acd0b62196b4c6be0c0",
    "jls-9.html": "3c87670664402810a30ae26c854459240e8164f748e4a1649bcb0d62099ab4ca",
    "jls-10.html": "aa064c1a6b1ee6b74a3f540bea54b64ae54ea4f43cd70b8bf02dd07ff673c33d",
    "jls-11.html": "2ba41a367dede387582fe42d5c5c9836f9e0502b4bb23f8fe2118dbd00d7ea9f",
    "jls-12.html": "97f1f09b8479cd4262a365d73199d6b968b14226335e1c72f088c7e4dbac3c7d",
    "jls-13.html": "1e98ea71e1dc282c130dbb2e96079714f3902d731c5df6cc91a58a859995f1d0",
    "jls-14.html": "598a37c64d81db549463ad6ac810ddf3aff67427c8d36e08e8ea5f28c6ab8f19",
    "jls-15.html": "575d903286081248bbd765fc736802c8480fe63e00b4a6b6de141402b4fcaae1",
    "jls-16.html": "e8c4121c35a5931fe7a0eb9ca4bd063eceab1472b4a5209fed5bafe9e75f3eee",
    "jls-17.html": "5352da1f94167b6db4c194a51e11e3d1d511f0292f62a44c56f7a92280bae9f1",
    "jls-18.html": "8d9e4589bd7ae7847d5f38cd2d21b729a4b286bf50318273b6ebf57fe96ea633",
    "jls-19.html": "4c83b242a4120d32331450892e19b115e8b3027fc8ef59982c36d42f6cbcf0f2",
}


def alternatives(production, lhs):
    rhs = production.select_one(".rhs")
    if lhs == "ReservedKeyword":
        # The prose gloss "(underscore)" follows the last keyword in the table.
        return [word for code in rhs.select("code.literal") for word in code.get_text().split()]
    for br in rhs.select("br"):
        br.replace_with("\0")
    text = rhs.get_text(" ", strip=True)
    if text.startswith("(one of)"):
        return text.removeprefix("(one of)").replace("\0", " ").split()
    return [" ".join(line.split()) for line in text.split("\0") if line.strip()]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--input-dir", type=Path, help="directory containing the pinned jls-N.html pages")
    args = cli.parse_args()
    rules = {}
    order = []
    for page, digest in PAGES.items():
        if args.input_dir:
            data = (args.input_dir / page).read_bytes()
        else:
            with urlopen(BASE + page) as response:
                data = response.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("unexpected Java SE 21 source digest: " + page)
        soup = BeautifulSoup(data, "html.parser")
        for production in soup.select(".production"):
            lhs = production.select_one(".lhs").get_text(strip=True).removesuffix(":")
            if page == "jls-19.html":
                # Chapter 19 restates syntactic productions. Preserve its order
                # and verify every RHS against the defining chapter.
                if alternatives(production, lhs) != rules[lhs][1]:
                    raise ValueError("summary disagrees with the defining chapter: " + lhs)
                if lhs not in order:
                    order.append(lhs)
            elif production.find("a", attrs={"name": "jls-" + lhs}):
                values = alternatives(production, lhs)
                if lhs in rules or not values:
                    raise ValueError("duplicate or empty definition: " + lhs)
                rules[lhs] = (page, values)
                if page == "jls-3.html":
                    order.append(lhs)
    missing = rules.keys() - set(order)
    if missing != {"VariableAccess"}:
        raise ValueError(f"unexpected omissions from the summary: {sorted(missing)}")
    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow(["rule", "alternative", "source", "rhs_sha256"])
    for lhs in [*order, *sorted(missing)]:
        page, values = rules[lhs]
        for i, value in enumerate(values, 1):
            writer.writerow([lhs, i, f"{page}#jls-{lhs}", hashlib.sha256(value.encode()).hexdigest()])


if __name__ == "__main__":
    main()
