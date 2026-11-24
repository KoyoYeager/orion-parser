"""Compare class field boundaries, ASTs and first syntax diagnostics with TypeScript 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler
from orionparser.languages.javascript.pipeline import SourceSyntaxError


def examples():
    for field in ("x:T", "static x!:T", "readonly [key]?:T", "#x:T", "x:T=1", "x = call()", "x"):
        for gap in (" ", " /*𐐀*/ ", "\r\n"):
            for tail in ("y:T", "@d y:T", "()", ";", "}"):
                body = field + gap + tail
                yield "class C{" + body + ("" if tail == "}" else "}")
    for key in ("x", "𐐀", r"\u0061", "fuction", "#x", "[x]", '"x"', "0", "let", "type", "if", "public var", "public const"):
        for gap in (" ", " /*comment*/ "):
            for tail in ("y", "+x"):
                yield f"class C{{{key}{gap}{tail}}}"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases = [dict(name="fields.ts", source=source, projection="computed await", diagnosticSpans=True)
             for source in examples()]
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    accepted = positioned = other = failures = 0
    pipeline = TypeScriptPipeline("fields.ts")
    for c, ref in zip(cases, run_compiler(archive, oracle, cases), strict=True):
        try:
            root = pipeline.parse(c["source"])
        except SourceSyntaxError as error:
            actual = [error.code, error.offset, error.length]
            diagnostics = ref.get("diagnostics", [])
            if diagnostics and diagnostics[0][0] in (1436, 1441, 1442, 1005, 1434, 1435, 1440, 1068):
                if diagnostics[0] == actual:
                    positioned += 1
                    continue
            elif diagnostics and error.code is None:
                other += 1
                continue
        else:
            actual = project_trees(root, c["projection"])
            if actual and actual == ref.get("trees"):
                accepted += 1
                continue
        print(repr(c["source"]), actual, ref)
        failures += 1
    print(f"{accepted} matching class trees, {positioned} matching field diagnostics, {other} other joint rejections, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
