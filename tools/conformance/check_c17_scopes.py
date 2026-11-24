"""Check type/value binding at C declaration boundaries through CLI and Clang ASTs."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from check_c17 import FLAGS, ROOT, check_version


def objects(tree):
    if isinstance(tree, list):
        for item in tree:
            yield from objects(item)
    elif isinstance(tree, dict):
        yield tree
        for item in tree.values():
            yield from objects(item)


def check_case(case, path, compiler):
    path.write_text(case["source"] + "\n")
    result = subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"])
    (operand,) = (n["operand"] for n in objects(json.loads(result))
                  if n.get("type") == "UnaryExpression" and n["operator"] == "sizeof")
    clang = subprocess.run([compiler, *FLAGS, "-fsyntax-only", "-Xclang", "-ast-dump=json", str(path)],
                           capture_output=True)
    if clang.returncode:
        raise ValueError(clang.stderr.decode())
    traits = [n for n in objects(json.loads(clang.stdout))
              if n.get("kind") == "UnaryExprOrTypeTraitExpr" and n["name"] == "sizeof"]
    is_type = case["role"] == "type"
    if is_type:
        expected = {"type": "TypeName", "specifiers": [{"type": "TypedefName", "name": "T"}], "declarator": None}
    else:
        expected = {"type": "Identifier", "name": "T"}
    if operand != expected:
        return False
    if traits:
        trait, = traits
        if is_type:
            return trait.get("argType", {}).get("qualType") == "T"
        refs = [n["referencedDecl"]["name"] for n in objects(trait.get("inner")) if n.get("kind") == "DeclRefExpr"]
        return refs == ["T"]

    # Clang can fold an array bound or omit it after parameter adjustment.
    # At the same source position only one of these spellings is grammatical.
    for replacement, accepted in [("sizeof(T *)", is_type), ("sizeof T", not is_type)]:
        probe = case["source"].replace("sizeof(T)", replacement)
        result = subprocess.run([compiler, *FLAGS, "-x", "cpp-output", "-fsyntax-only", "-"],
                                input=probe + "\n", text=True, capture_output=True)
        if (result.returncode == 0) != accepted:
            raise ValueError(f"{case['case']}: unexpected reference result for {probe}: {result.stderr}")
    return True


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--clang", default="clang-18")
    compiler = cli.parse_args().clang
    check_version(compiler)
    with (ROOT / "docs/conformance/c17-typedef-scopes.tsv").open() as stream:
        cases = list(csv.DictReader(stream, delimiter="\t"))
    with tempfile.TemporaryDirectory() as folder:
        for case in cases:
            if not check_case(case, Path(folder) / "scope.i", compiler):
                raise ValueError(f"{case['case']}: unexpected binding in {case['source']}")
    print(f"{len(cases)} type/value bindings matched the expected scope and Clang")


if __name__ == "__main__":
    main()
