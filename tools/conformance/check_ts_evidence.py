"""Validate the links from pinned TypeScript reference functions to implementation and tests."""
import ast
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFORMANCE = ROOT / "docs" / "conformance"


def read_rows(name):
    with (CONFORMANCE / name).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source, delimiter="\t"))


def main():
    inventory = {(r["source"], r["function"], r["line:column"]) for r in read_rows("typescript-5.9.tsv")}
    evidence = read_rows("typescript-5.9-evidence.tsv")
    symbols = set()
    for lang in ("javascript", "typescript"):
        for path in (ROOT / "src/orionparser/languages" / lang).glob("*.py"):
            symbols.update(node.name for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
    tests, covered, seen, errors = {}, set(), set(), []
    for row in evidence:
        anchor = row["source"], row["reference_function"], row["reference_location"]
        impl, test = row["implementation"], row["pytest_node"]
        link = (*anchor, impl, test)
        if link in seen:
            errors.append(f"duplicate evidence link: {link}")
        seen.add(link)
        if anchor not in inventory:
            errors.append(f"unknown reference function: {anchor}")
        if impl not in symbols:
            errors.append(f"missing implementation: {impl}")
        filename, _, test_name = test.partition("::")
        if filename not in tests:
            path = ROOT / filename
            tests[filename] = {node.name for node in ast.parse(path.read_text(encoding="utf-8")).body
                               if isinstance(node, ast.FunctionDef)} if path.is_file() else set()
        if test_name not in tests[filename]:
            errors.append(f"missing test: {test}")
        covered.add(anchor)
    for message in errors:
        print(message)
    print(f"{len(seen)} evidence links, {len(covered)} of {len(inventory)} reference functions linked, "
          f"{len(inventory - covered)} without links, {len(errors)} link errors")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
