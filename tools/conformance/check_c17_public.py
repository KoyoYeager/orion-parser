"""Compare file acceptance and function definitions on a pinned c-testsuite snapshot."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

from check_c17 import FLAGS, ROOT, check_version, name
from orionparser.languages.c.pipeline import CPipeline
from orionparser.registry import get_pipeline


COMMIT = "5c7275656d751de0e68b2d340a95b5681858ed07"
DIGEST = "010008bf4b5671f947ae7e8d693a1c959a4a4d795fa7227c0abb1f95de45f7e7"


def orion_signatures(unit):
    signatures = []
    for declaration in unit["declarations"]:
        if declaration["type"] == "FunctionDefinition":
            function = declaration["declarator"]
            while function["declarator"]["type"] != "Identifier":
                function = function["declarator"]
            params = function["parameters"]
            args = [name(p if p["type"] == "Identifier" else p.get("declarator")) for p in params]
            signatures.append((name(function), [arg for arg in args if arg is not None],
                               any(p["type"] == "Ellipsis" for p in params)))
    return signatures


def check(path, compiler, exceptions):
    flags = [compiler, *FLAGS, "-Wno-strict-prototypes", "-Wno-deprecated-non-prototype"]
    reference = subprocess.run([*flags, "-fsyntax-only", "-Xclang", "-ast-dump=json", str(path)],
                               capture_output=True, text=True)
    actual = get_pipeline(path).analyze_file(path)
    if path.name in exceptions:
        row = exceptions[path.name]
        errors = [line for line in reference.stderr.splitlines() if ": error:" in line]
        if not reference.returncode or not any(row["clang_reason"] in line for line in errors):
            raise ValueError(f"{path.name}: expected {row['clang_reason']!r}, got {errors}")
        if actual.success != (row["orion_accepts"] == "yes"):
            raise ValueError(f"{path.name}: unexpected Orion acceptance: {actual.errors}")
        return 0
    if reference.returncode or not actual.success:
        raise ValueError(f"{path.name}: unexpected rejection: {reference.stderr} {actual.errors}")
    source = subprocess.check_output([*flags, "-E", str(path)])
    expected = []
    for decl in json.loads(reference.stdout)["inner"]:
        inner = decl.get("inner", [])
        if decl["kind"] == "FunctionDecl" and any(n["kind"] == "CompoundStmt" for n in inner):
            expected.append((decl["name"], [n["name"] for n in inner if n["kind"] == "ParmVarDecl"],
                             decl.get("variadic", False)))
    if not any(fn == "main" for fn, _, _ in expected):
        raise ValueError(f"{path.name}: missing reference main definition")
    for tree in (actual.ast, CPipeline().parse(source.decode())):
        if (found := orion_signatures(tree)) != expected:
            raise ValueError(f"{path.name}: Orion {found} vs Clang {expected}")
    return len(expected)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("archive", type=Path)
    cli.add_argument("--clang", default="clang-18")
    args = cli.parse_args()
    check_version(args.clang)
    if hashlib.sha256(args.archive.read_bytes()).hexdigest() != DIGEST:
        cli.error("unexpected c-testsuite archive digest")
    with (ROOT / "docs/conformance/c17-public-differences.tsv").open() as stream:
        exceptions = {row["fixture"]: row for row in csv.DictReader(stream, delimiter="\t")}
    with tempfile.TemporaryDirectory() as directory, tarfile.open(args.archive) as archive:
        archive.extractall(directory, filter="data")
        cases = sorted((Path(directory) / ("c-testsuite-" + COMMIT) / "tests/single-exec").glob("*.c"))
        if len(cases) != 220 or exceptions.keys() - {path.name for path in cases}:
            raise ValueError("unexpected c-testsuite inventory")
        functions = sum(check(path, args.clang, exceptions) for path in cases)
    print(f"{len(cases)-len(exceptions)} accepted files, {functions} matching function signatures "
          f"via .c and .i, {len(exceptions)} classified reference rejections")


if __name__ == "__main__":
    main()
