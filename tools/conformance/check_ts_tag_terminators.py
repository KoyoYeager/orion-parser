"""Compare template expression boundaries and TS1443 diagnostic spans against TypeScript 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler
from orionparser.languages.javascript.pipeline import SourceSyntaxError


def examples():
    for tag in ("module", "foo", "obj.tag", "fn()", "foo<T>", "obj?.tag", "(foo)", "tag`inner`"):
        for literal in ("`x`", "`𐐀\r\n${x}mid${y}z`", "`outer${nested`in`}end`"):
            for sep, suffix in ((" ", "next;"), (" /*c*/ ", "{}"), ("\n", "next;"), (" + ", "next;")):
                yield tag + " /*𐐀*/ " + literal + sep + suffix
    for head in ("throw ", "if (ok) ", "a + ", "a = ", "const x = ", "f(", "("):
        yield head + "tag`bad` next;"
    for suffix in (")", "]", "#name", ":", "@dec class C{}"):
        yield "tag`x` " + suffix
    for source in ("function f(){return tag`x` y}", "export default tag`x` y;", "throw (tag`x`) y;",
                   "if(ok) tag`x` else y;", "tag`a` /* a */ `b` next;", "tag?.`a` y;"):
        yield source
    yield "(tag`x`) y;"
    yield "tag`x`.p y;"
    yield "`x` y;"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases = [dict(name="tag.ts", source=src, projection="branch statement", diagnosticSpans=True) for src in examples()]
    refs = run_compiler(archive, _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text(), cases)
    accepted = positioned = other = failures = 0
    pipeline = TypeScriptPipeline("tag.ts")
    for c, ref in zip(cases, refs, strict=True):
        try:
            root = pipeline.parse(c["source"])
        except SourceSyntaxError as exc:
            ds = ref.get("diagnostics", [])
            if ds and ds[0][0] == 1443 and ds[0] == [exc.code, exc.offset, exc.length]:
                positioned += 1
                continue
            if ds and ds[0][0] != 1443 and (exc.code is None or ds[0] == [exc.code, exc.offset, exc.length]):
                other += 1
                continue
            actual = str(exc)
        else:
            actual = project_trees(root, c["projection"])
            if actual and actual == ref.get("trees"):
                accepted += 1
                continue
        print(repr(c["source"]), actual, ref)
        failures += 1
    print(f"{accepted} matching trees, {positioned} matching TS1443 spans, {other} other joint rejections, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
