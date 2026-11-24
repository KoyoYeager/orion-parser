"""Compare TypeScript function-type ASTs and acceptance across line-leading asterisk positions."""
import argparse
from pathlib import Path
import re

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler
from orionparser.languages.javascript.pipeline import SourceSyntaxError


PARAMETER_TYPES = (
    "?T", "T?", "T!", "T![]", "F<T?, U!>", "T extends infer U extends Q ? X : Y",
    "(() => T)", "[x: T, y?: U]", "A.B<C.D>", "T[K]", "T extends (infer U)[] ? X : Y",
    "{ [K in keyof T]: T[K] }", "...T=", "function(this:T):U", "function(new:T=):U",
    "*", "module:foo", 'import("m").T', "T", "T=", "this:T", "new:T=", "...T", "T | U",
    "[A,B]", "{a:A;b:B}", "A<B>", "(T)", "T[]", "function(T):U", "function(T,U)",
    "function(T=,U=)", "function([A,B]):U", "T extends U ? X : Y", "{m(a:T):U}",
)


def examples():
    for arg in PARAMETER_TYPES:
        for source in (f"type A=function({arg});", f"type A=function(A,{arg},B):Q;"):
            yield source
            for token in re.finditer(r'"[^"]*"|[A-Za-z]+|\.\.\.|=>|[^\s]', source):
                pos = token.start()
                if pos >= len("type A="):
                    yield source[:pos] + "\n* " + source[pos:]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    args = cli.parse_args()
    check_pin(args.compiler, COMPILER_SHA)
    cases = [{"source": s, "name": "margin.ts", "projection": "alias"} for s in dict.fromkeys(examples())]
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    results = run_compiler(args.compiler, oracle, cases)
    pipeline = TypeScriptPipeline("margin.ts")
    accepted = rejected = failures = 0
    for case, ref in zip(cases, results, strict=True):
        try:
            ast = pipeline.parse(case["source"])
        except SourceSyntaxError:
            if ref.get("invalid"):
                rejected += 1
                continue
        else:
            if project_trees(ast, "alias") == ref.get("trees"):
                accepted += 1
                continue
        failures += 1
        print(repr(case["source"]), ref)
    print(f"{accepted} matching alias ASTs, {rejected} jointly rejected, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
