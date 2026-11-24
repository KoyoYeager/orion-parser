"""Validate indexed Java syntax examples with PLY reductions, CLI ASTs and pinned javac."""
import argparse
import csv
import json
from pathlib import Path
import tempfile

from ply_trace import capture_reductions
from check_java_operators import run as check_operators
from check_java_lexical import run as check_lexical
from check_java_modules import ROOT, functional_shapes, instance_tests, invocation_shapes, member_shape, reference_results, resource_and_array_shapes, switch_shapes, text_block_values
from orionparser.registry import get_pipeline


def trace(path):
    result, reductions = capture_reductions(lambda: get_pipeline(path).analyze_file(path), "orionparser.languages.java.")
    if not result.success:
        raise ValueError(f"{path}: {result.errors}")
    return result.ast, reductions


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--jdk", type=Path, default=ROOT / ".venv/toolchains/jdk-21.0.2")
    args = cli.parse_args()
    docs = ROOT / "docs/conformance"
    with (docs / "java-se21.tsv").open() as stream:
        inventory = {(r["rule"], r["alternative"]) for r in csv.DictReader(stream, delimiter="\t")}
    with (docs / "java-se21-examples.tsv").open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    inputs = {}
    seen = set()
    for row in rows:
        key = row["rule"], row["alternative"]
        if key not in inventory:
            raise ValueError(f"unknown Java rule {key}")
        path = ROOT / "tests/languages/java/fixtures" / row["fixture"]
        if path not in inputs:
            inputs[path] = trace(path)
        value, actions = inputs[path]
        if row["production"] not in actions:
            raise ValueError(f"{key}: missing reduction {row['production']}")
        for part in row["path"].split("."):
            value = value[int(part)] if isinstance(value, list) else value[part]
        if value != json.loads(row["expected_json"]):
            raise ValueError(f"{key}: unexpected AST value {value!r}")
        seen.add(key)
    with (docs / "java-se21-rejections.tsv").open() as stream:
        cases = list(csv.DictReader(stream, delimiter="\t"))
    with tempfile.TemporaryDirectory() as folder:
        invalid = {}
        for i, case in enumerate(cases):
            filename = "module-info.java" if "module m" in case["source"] else "Example.java"
            path = Path(folder) / str(i) / filename
            path.parent.mkdir()
            path.write_text(case["source"])
            actual = get_pipeline(path).analyze_file(path)
            if case["orion_column"] == "parse-accept":
                if not actual.success:
                    raise ValueError(f"{case['case']}: unexpected Orion rejection {actual.errors}")
            else:
                position = f"line {case.get('orion_line') or 1}, column {case['orion_column']}:"
                if actual.success or actual.ast is not None or not any(e.startswith(position) for e in actual.errors):
                    raise ValueError(f"{case['case']}: expected rejection at {position}, got {actual.errors}")
            invalid[path] = case
        for ref in reference_results(args.jdk, Path(folder), [*inputs, *invalid]):
            if (case := invalid.get(Path(ref["file"]))) is not None:
                if case["javac_code"] == "parse-accept":
                    if not ref["accepted"]:
                        raise ValueError(f"{case['case']}: unexpected javac parse rejection")
                else:
                    expected = {"code": case["javac_code"], "line": int(case.get("javac_line") or 1), "column": int(case["javac_column"])}
                    if not ref["errors"] or ref["errors"][0] != expected:
                        raise ValueError(f"{case['case']}: expected {expected}, got {ref['errors']}")
                continue
            if not ref["accepted"]:
                raise ValueError(f"{ref['file']}: {ref['errors']}")
            tree, _ = inputs[Path(ref["file"])]
            if resource_and_array_shapes(tree) != (ref["tries"], ref["arrays"]):
                raise ValueError(f"{ref['file']}: try or array structure differs from javac")
            if text_block_values(tree) != ref["textBlocks"]:
                raise ValueError(f"{ref['file']}: text block values differ from javac")
            if switch_shapes(tree) != ref["switches"]:
                raise ValueError(f"{ref['file']}: switch cases differ from javac: {switch_shapes(tree)} vs {ref['switches']}")
            if instance_tests(tree) != ref["instances"]:
                raise ValueError(f"{ref['file']}: instanceof targets differ from javac: {ref['instances']}")
            if invocation_shapes(tree) != ref["invocations"]:
                raise ValueError(f"{ref['file']}: invocation receivers or type arguments differ from javac")
            if functional_shapes(tree) != ref["functional"]:
                raise ValueError(f"{ref['file']}: lambda and method-reference structure differs from javac")
            classes = [member_shape(decl) for decl in tree["declarations"] if decl["type"] != "EmptyDeclaration"]
            if classes != ref["shapes"]:
                raise ValueError(f"{ref['file']}: member structure differs from javac: {classes} vs {ref['shapes']}")
    accepted = sum(case["orion_column"] == "parse-accept" for case in cases)
    print(f"{len(cases)-accepted} positioned Orion rejections and {accepted} Orion-only acceptances checked against javac")
    lexical = check_lexical(args.jdk)
    operators = check_operators(args.jdk)
    coverage = seen | lexical | operators
    if coverage != inventory:
        raise ValueError(f"missing or unindexed Java alternatives: {sorted(coverage ^ inventory)}")
    print(f"{len(coverage)}/{len(inventory)} Java alternatives exercised "
          f"({len(seen)} with PLY reductions and AST assertions, {len(lexical)} with scanner comparisons, {len(operators)} in the operator matrix)")


if __name__ == "__main__":
    main()
