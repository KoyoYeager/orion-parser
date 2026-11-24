"""Run the lexical, phrase and directive witnesses and audit their union against Annex A."""
import csv

from check_c17 import ROOT
from check_c17_examples import main as check_ast
from check_c17_lexical import main as check_tokens
from check_c17_preprocessing import main as check_directives


def main():
    seen = check_ast() | check_tokens() | check_directives()
    with (ROOT / "docs/conformance/c17.tsv").open() as stream:
        inventory = {(r["rule"], r["alternative"]) for r in csv.DictReader(stream, delimiter="\t")}
    if seen != inventory:
        raise ValueError(f"missing or unindexed grammar alternatives: {sorted(seen ^ inventory)}")
    print(f"{len(seen)}/{len(inventory)} Annex A.1–A.3 alternatives exercised")


if __name__ == "__main__":
    main()
