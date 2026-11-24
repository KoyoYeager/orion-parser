"""Exercise indexed C17 alternatives through PLY and compare positive inputs with Clang."""
import argparse
import csv
import json
from pathlib import Path
import subprocess

from ply_trace import capture_reductions
from check_c17 import FLAGS, ROOT, check_version
from orionparser.languages.c.pipeline import CPipeline


def trace(source):
    return capture_reductions(lambda: CPipeline().parse(source), "orionparser.languages.c.")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--clang", default="clang-18")
    args = cli.parse_args()
    check_version(args.clang)
    docs = ROOT / "docs/conformance"
    with (docs / "c17.tsv").open() as stream:
        inventory = {(r["rule"], r["alternative"]) for r in csv.DictReader(stream, delimiter="\t")}
    seen, inputs = set(), {}
    with (docs / "c17-examples.tsv").open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    for row in rows:
        key = row["rule"], row["alternative"]
        if key not in inventory:
            raise ValueError(f"unknown alternative {key}")
        source = row["source"]
        if source.startswith("fixture:"):
            source = (ROOT / "tests/languages/c" / source.removeprefix("fixture:")).read_text()
        if source not in inputs:
            subprocess.run([args.clang, *FLAGS, "-Wno-deprecated-non-prototype", "-x", "cpp-output", "-fsyntax-only", "-"],
                           input=source.rstrip("\n") + "\n", text=True, check=True)
            inputs[source] = trace(source)
        tree, actions = inputs[source]
        if row["production"] not in actions:
            raise ValueError(f"{key} did not reduce {row['production']} in {source!r}")
        value = tree
        for part in row["path"].split("."):
            value = value[int(part)] if isinstance(value, list) else value[part]
        if value != json.loads(row["expected_json"]):
            raise ValueError(f"{key} {row['path']}: got {value!r}, expected {row['expected_json']}")
        seen.add(key)
    print(f"{len(rows)} AST witnesses in {len(inputs)} translation units; {len(seen)}/{len(inventory)} alternatives verified")
    return seen


if __name__ == "__main__":
    main()
