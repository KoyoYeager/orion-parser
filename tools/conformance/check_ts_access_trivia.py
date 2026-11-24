"""Check expression and JSX access across line terminators against TypeScript 5.9.3."""
import argparse
from pathlib import Path

from orionparser.languages.javascript.pipeline import SourceSyntaxError
from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler


def examples():
    for operator in (".", "?."):
        for gap in ("", " ", "\n", "/*\r\n*/", "\u2028"):
            for suffix in ("key in obj", "key\nin obj", "key as T", "default instanceof C", "#x in obj",
                           "key()", "key?.[idx]", "key /*two*/ satisfies T"):
                yield "x.ts", "obj" + operator + gap + suffix + ";", "target expression"
    for source in ("import.\nmeta in value;", "new.\ntarget as T;", "obj[ ];", "obj?.[ ];",
                   "obj?.[a,b].c;", "obj[1]?.value;", "obj.\n𐐀 /*gap*/ in value;"):
        yield "x.ts", source, "target expression"
    for source in ('type T=import("m").\nX extends U?A:B;', 'type T=import("m").X.\nY extends U?A:B;',
                   'type T=typeof this.\nx extends U?A:B;', 'type T=A.\nB extends U?A:B;', 'type T=T[];'):
        yield "x.ts", source, "alias"
    for name in ("a-b.C", "A.B-c", "A.B.C-x", "A.\nB", "ns:b-c", "a-b"):
        for attrs in ("", " data-x"):
            yield "x.tsx", "<" + name + attrs + "/>;", "JSX"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases = [dict(name=n, source=s, projection=p, diagnosticSpans=True) for n, s, p in examples()]
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    accepted = rejected = failures = 0
    for c, ref in zip(cases, run_compiler(archive, oracle, cases), strict=True):
        try:
            root = TypeScriptPipeline(c["name"]).parse(c["source"])
        except SourceSyntaxError as exc:
            actual = str(exc)
            code = exc.code or (1003 if "TS1003" in actual else 1011 if "TS1011" in actual else None)
            if ref.get("invalid") and (code is None or [code, exc.offset, exc.length or 0] in ref["diagnostics"]):
                rejected += 1
                continue
        else:
            actual = project_trees(root, c["projection"])
            if actual and actual == ref.get("trees"):
                accepted += 1
                continue
        print(repr(c["source"]), actual, ref)
        failures += 1
    print(f"{accepted} matching ASTs, {rejected} joint rejections, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
