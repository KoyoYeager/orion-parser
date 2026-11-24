"""Compare leading reference fields and diagnostics with TypeScript 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler
from orionparser.languages.javascript.pipeline import SourceSyntaxError


def sources():
    valid = '/// <reference path="lib" />'
    invalid = '/// <reference unknown="𐐀" /> trailing'
    amd = '/// <amd-module name="main" />'
    bad_mode = '/// <reference types="𐐀pkg" resolution-mode="esm" />'
    for trivia in ("", "\t", "\v", "\f", " ", "\r", "\n", "\r\n", "\u2028", "\u2029", "\u0085",
                   "\u200b", "\ufeff", "/*𐐀*/", "/** doc */\n", "// prior\r", "#!bin\n"):
        for directive in (valid, invalid, bad_mode, amd + "\n" + amd):
            yield trivia + directive + "\nconst x=1;"
    for lines in ((valid, amd, amd, invalid), (amd, valid, invalid, amd),
                  (bad_mode, invalid), (invalid, bad_mode), (amd, bad_mode, amd),
                  ('/// <amd-module />', invalid, amd, amd), (valid, "x;", invalid),
                  (valid, amd, '/// <amd-dependency path="x"/>'), (invalid, "throw;"),
                  (invalid, 'const x = "\\xZ";'), (bad_mode, 'type T = `h${F(x)}`;')):
        yield "\n".join(lines)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases = [{"name": "reference.ts", "source": s, "projection": "source references", "diagnosticSpans": True}
             for s in sources()]
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    refs = run_compiler(archive, oracle, cases)
    pipeline = TypeScriptPipeline("reference.ts")
    trees = diagnostics = failures = 0
    for case, ref in zip(cases, refs, strict=True):
        try:
            root = pipeline.parse(case["source"])
        except SourceSyntaxError as error:
            actual = [error.code, error.offset, error.length]
            if ref.get("diagnostics", [])[:1] == [actual]:
                diagnostics += 1
                continue
        else:
            actual = project_trees(root, case["projection"])
            if actual == ref.get("trees"):
                trees += 1
                continue
        print(repr(case["source"]), actual, ref)
        failures += 1
    print(f"{trees} matching reference trees, {diagnostics} exact first diagnostics, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
