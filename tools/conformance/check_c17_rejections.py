"""Check positioned rejection of delimiter deletions and balanced invalid C17 inputs."""
import argparse
import csv
import re
import subprocess

from check_c17 import FLAGS, ROOT, check_version
from orionparser.languages.c.lexer import CParseError
from orionparser.languages.c.pipeline import CPipeline


def malformed_inputs(pipeline):
    seen = set()
    with (ROOT / "docs/conformance/c17-examples.tsv").open() as stream:
        inputs = dict.fromkeys(row["source"] for row in csv.DictReader(stream, delimiter="\t"))
    for source in inputs:
        if source.startswith("fixture:"):
            source = (ROOT / "tests/languages/c" / source.removeprefix("fixture:")).read_text()
        for token in pipeline.tokenize(source):
            if token["type"] not in {"(", ")", "[", "]", "{", "}"}:
                continue
            offset = token["offset"]
            # Preserve neighboring token boundaries and all physical line positions.
            length = len(token["value"])
            bad = source[:offset] + " " * length + source[offset + length:]
            if bad not in seen:
                seen.add(bad)
                yield bad


def check_rejection(pipeline, compiler, source, *, reference_accepts=False):
    try:
        pipeline.parse(source)
    except CParseError as error:
        if not (0 <= error.offset <= len(source) and error.line > 0 and error.column > 0):
            raise ValueError(f"invalid diagnostic position in {source!r}") from error
    else:
        raise ValueError(f"Orion accepted invalid input: {source!r}")
    result = subprocess.run([compiler, *FLAGS, "-Wno-deprecated-non-prototype", "-ferror-limit=1",
                             "-x", "cpp-output", "-fsyntax-only", "-"], input=source.rstrip("\n") + "\n",
                            capture_output=True, text=True)
    if reference_accepts:
        if result.returncode:
            raise ValueError(f"reference behavior changed for {source!r}: {result.stderr}")
    elif not result.returncode or not re.search(r"<stdin>:\d+:\d+: error:", result.stderr):
        raise ValueError(f"expected a Clang diagnostic for {source!r}: {result.stderr}")


def check_semantic_diagnostics(pipeline, compiler):
    with (ROOT / "docs/conformance/c17-semantic-diagnostics.tsv").open() as stream:
        cases = list(csv.DictReader(stream, delimiter="\t"))
    for case in cases:
        source = case["source"]
        unit = pipeline.parse(source)
        value = unit["declarations"][0]["body"]["items"]
        for part in case["ast_path"].split("."):
            value = value[int(part)] if isinstance(value, list) else value[part]
        if value != case["expected"]:
            raise ValueError(f"unexpected syntax tree for {source!r}: {value!r}")
        result = subprocess.run([compiler, *FLAGS, "-x", "cpp-output", "-fsyntax-only", "-"],
                                input=source + "\n", capture_output=True, text=True)
        errors = [line for line in result.stderr.splitlines() if ": error:" in line]
        if not result.returncode or len(errors) != 1 or case["clang_diagnostic"] not in errors[0]:
            raise ValueError(f"unexpected semantic diagnostic for {source!r}: {result.stderr}")
    print(f"{len(cases)} type-dependent diagnostics distinguished from syntax rejection")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--clang", default="clang-18")
    compiler = cli.parse_args().clang
    check_version(compiler)
    pipeline = CPipeline()
    count = 0
    for source in malformed_inputs(pipeline):
        check_rejection(pipeline, compiler, source)
        count += 1
    print(f"{count} distinct delimiter deletions rejected with positions by Clang and Orion")
    with (ROOT / "docs/conformance/c17-balanced-rejections.tsv").open() as stream:
        cases = list(csv.DictReader(stream, delimiter="\t"))
    for case in cases:
        check_rejection(pipeline, compiler, case["source"])
    print(f"{len(cases)} balanced invalid translation units rejected with positions by Clang and Orion")
    for source in ("int * _Atomic (p);", "int f(int [const *]);"):
        check_rejection(pipeline, compiler, source, reference_accepts=True)
    print("2 C17 declarator differences reproduced against Clang")
    check_semantic_diagnostics(pipeline, compiler)



if __name__ == "__main__":
    main()
