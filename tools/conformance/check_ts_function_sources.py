"""Compare named and anonymous functions, signatures, and bodies against TypeScript 5.9.3."""
import argparse
from pathlib import Path

from orionparser.languages.javascript.pipeline import SourceSyntaxError
from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler


def examples():
    for prefix in ("", "export ", "export default ", "declare ", "const f="):
        for head, body in (("function", "{return x}"), ("function*", "{yield x}"),
                           ("async function", "{return await x}"), ("async function*", "{yield await x}")):
            for name in ("", "f", "await", "yield", "eval", "let"):
                for ending in (";", body):
                    yield f"{prefix}{head} {name}<T>(x:T):T{ending}"
    yield "function f():T\nfunction f(){return x}"
    yield "declare function f(x=await v){}"
    yield "declare async function f(x=await v){return await x}"
    yield "declare async function* f(x=yield v){yield await x}"
    yield "declare async function f(){return function(){return await}}"
    yield "function f():T next;"
    yield "const f=function<T>(x:T):T"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases = [dict(source=s, name="functions.ts", projection="function source") for s in examples()]
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    accepted = rejected = failures = 0
    for c, ref in zip(cases, run_compiler(archive, oracle, cases), strict=True):
        try:
            tree = TypeScriptPipeline(c["name"]).parse(c["source"])
        except SourceSyntaxError as exc:
            if ref.get("invalid") and 0 <= exc.offset <= len(c["source"]):
                rejected += 1
                continue
            actual = str(exc)
        else:
            actual = project_trees(tree, c["projection"])
            if actual == ref.get("trees"):
                accepted += 1
                continue
        print(repr(c["source"]), actual, ref)
        failures += 1
    print(f"{accepted} matching function files, {rejected} joint rejections, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
