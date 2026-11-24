"""Compare template spelling, cooked fragments, tail flags and substitution ASTs."""
import argparse
from pathlib import Path

from orionparser.languages.javascript.pipeline import SourceSyntaxError

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler


def examples():
    for fragment in ("", "text", "line\rbreak", "line\r\nbreak", "line\nbreak", "line\u2028break",
                     "\\\r\n", r"\n", r"\x41", r"\u{1F600}", r"\`", r"\${x}", r"\0", r"\01",
                     r"\8", r"\xZ", r"\u{}", r"\u{110000}", r"\u123G", r"\u{fffG}", r"\u{000000110000G}", r"\1234", r"\428", "𐐀\r\n" + r"\8", "two\rbreaks\r\n" + r"\xZ"):
        for template in ("`@s`", "`@s${x}z`", "`h${x}@s`", "`h${x}@s${y}t`"):
            for context in ("const v=@t;", "tag@t;", "type T=@t;"):
                yield {"source": context.replace("@t", template.replace("@s", fragment)), "name": "literal.ts",
                       "projection": "template spelling", "diagnosticSpans": True}

    for source in (r"`bad\xZ${`inner\u{}`}tail`", r"tag`bad\xZ${`inner\u{}`}tail`",
                   r"`ok${x}bad\u{110000}${`inner\8`}`", r"type T=`bad\xZ${`inner\u{}`}tail`",
                   r"tag`bad\xZ${tag`inner\8`}tail`", r"`ok${tag`inner\8`}bad\x1`"):
        yield {"source": source, "name": "nested.ts", "projection": "template spelling", "diagnosticSpans": True}

    for prefix in ("const s=", "tag", "type T=", "f(", "f(tag", "type T = Box<"):
        for start in ("`", "`h${X}", "`h${X}m${Y}"):
            for end in ("", "𐐀\r\n", "\\", "\\\\", r"\8", r"\x1", r"\u{", r"\u{1", r"\u{1f0000}"):
                yield {"source": prefix + start + end, "name": "unfinished.ts",
                       "projection": "template spelling", "diagnosticSpans": True}

    for prefix in ("const s=", "tag", "type T="):
        for start in ("`h${", "`h${X}m${"):
            for end in ("", " ", "X", "X /*c*/", "(X", "(", "X|", "X|  "):
                yield {"source": prefix + start + end, "name": "substitution.ts",
                       "projection": "template spelling", "diagnosticSpans": True}

    for suffix in ("f(", "f(x,", "a?.(", "new Foo(", "[", "[x,", "({x: y", "function f(){",
                   "x[", "x.", "x?.", "x ? a", "(x,", "class C {"):
        yield {"source": "`h${" + suffix, "name": "expression.ts", "projection": "template spelling",
               "diagnosticSpans": True}
    for suffix in ("[", "[X,", "{", "{x: T", "X[", "X[K", "typeof ", "T<", "T.", "(T"):
        yield {"source": "type T = `h${" + suffix, "name": "type.ts", "projection": "template spelling",
               "diagnosticSpans": True}

    for source in (r"`bad\xZ${)", r"`bad\u{}${", r"type S=`bad\xQ${:}",
                   r"`ok${x}bad\u{123Z}${)", r"tag`bad\xZ${)", r"tag`bad\u{}${"):
        yield {"source": source, "name": "bad-substitution.ts", "projection": "template spelling",
               "diagnosticSpans": True}

    for prefix in ("const s=", "tag", "type T="):
        for text in ("`h${ )", "`h${ }", "`h${}rest`", "`h${Y}m${;"):
            yield {"source": prefix + text, "name": "missing.ts", "projection": "template spelling",
                   "diagnosticSpans": True}
    for term in ("F(x)", "F?.(x)", "F + x", "F === x", "F, x", "F instanceof X",
                 "F && G", "F || G", "F = G", "(F)", "F[X]"):
        for start in ("`h${", "`h${Y}m${"):
            for prefix in ("type T = ", "const t = ", "tag"):
                yield {"source": prefix + start + term + "}tail`;", "name": "boundary.ts",
                       "projection": "template spelling", "diagnosticSpans": True}
    for term in ("(X + Y)", "Promise<X + Y>", "[X + Y]", "{a: X + Y}", "X[K + Y]",
                 "F(X Y)", "[X Y]", "{x:1 y:2}", "X >= Y", "X >>> Y", "(a, b + )"):
        yield {"source": "type T = `h${" + term + "}t`;", "name": "inner-type.ts",
               "projection": "template spelling", "diagnosticSpans": True}
    for term in ("F(x y)", "[x y]", "{x:1 y:2}", 'x /*𐐀*/ return', "x #name", r"x \u0061bc"):
        for prefix in ("tag", ""):
            yield {"source": prefix + "`h${" + term + "}t`;", "name": "inner-expression.ts",
                   "projection": "template spelling", "diagnosticSpans": True}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases = list(examples())
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    accepted = rejected = differences = 0
    for case, ref in zip(cases, run_compiler(archive, oracle, cases), strict=True):
        try:
            tree = TypeScriptPipeline(case["name"]).parse(case["source"])
        except SourceSyntaxError as error:
            if ref.get("invalid") and ref["diagnostics"][0] == [error.code, error.offset, error.length]:
                rejected += 1
                continue
            actual = str(error)
        else:
            actual = project_trees(tree, case["projection"])
            if actual and actual == ref.get("trees"):
                accepted += 1
                continue
        print(repr(case["source"]), "Orion", actual, "TypeScript", ref)
        differences += 1
    print(f"{accepted} matching template cases, {rejected} exact diagnostic spans, {differences} differences")
    return int(bool(differences))


if __name__ == "__main__":
    raise SystemExit(main())
