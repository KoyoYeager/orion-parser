"""Compare C17 directive examples through the CLI, Clang preprocessing and a literal expansion."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from check_c17 import FLAGS, ROOT, check_version


def parse(path, *options):
    run = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json", *options],
                         capture_output=True, text=True)
    return run.returncode, json.loads(run.stdout), run.stderr


def check_case(case, folder, compiler):
    for name, text in case.get("headers", {}).items():
        (folder / name).write_text(text)
    source = folder / "example.c"
    source.write_text(case["source"])
    status, tree, error = parse(source, "-I", str(folder))
    reference = subprocess.run([compiler, *FLAGS, "-E", "-P", "-I", str(folder), str(source)], capture_output=True, text=True)
    if "diagnostic" in case:
        return (status != 0 and tree is None and reference.returncode != 0
                and case["diagnostic"] in error and case["diagnostic"] in reference.stderr)
    if status or reference.returncode:
        raise ValueError(error + reference.stderr)
    for name, expanded in [("expected.i", case["expanded"]), ("reference.i", reference.stdout)]:
        path = folder / name
        path.write_text(expanded)
        expected_status, expected, error = parse(path)
        if expected_status or expected != tree:
            raise ValueError(f"{name}: {error or 'different AST'}")
    return True


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--clang", default="clang-18")
    compiler = cli.parse_args().clang
    check_version(compiler)
    docs = ROOT / "docs/conformance"
    with (docs / "c17.tsv").open() as stream:
        inventory, directives = set(), set()
        for row in csv.DictReader(stream, delimiter="\t"):
            key = row["rule"] + "." + row["alternative"]
            inventory.add(key)
            if row["source"].startswith("N2176 6.10"):
                directives.add(key)
    seen = set()
    for case in json.loads((docs / "c17-preprocessing.json").read_text()):
        with tempfile.TemporaryDirectory() as directory:
            if not check_case(case, Path(directory), compiler):
                raise ValueError(case["case"])
        seen.update(case["rules"])
    if (missing := directives - seen) or (missing := seen - inventory):
        raise ValueError(f"directive inventory mismatch: {sorted(missing)}")
    print(f"{len(seen)} preprocessing alternatives checked via the .c CLI and Clang")
    return {tuple(key.rsplit(".", 1)) for key in seen}


if __name__ == "__main__":
    main()
