"""Compare ordered object-literal members and their expression trees against TypeScript 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler
from orionparser.languages.javascript.pipeline import SourceSyntaxError


def examples():
    for key in ("name", '"quoted"', "0x2", "[a,b]", "[fn(x)]", "__proto__", "#private"):
        for member in (key, key + "=initial", key + ": value", key + "<T>(x:T):T{return x}",
                       "*" + key + "(){}", "get " + key + "(){return x}", "set " + key + "(v){}"):
            yield "({...before," + member + ", ...after});"
    for modifiers in ("async", "async async", "async static", "public async", "async readonly public", "static async static"):
        for member in ("x", "x:1", "x=1", "x?!:2", "[k]<T>(v:T){return await v}", "*f(){yield await work()}",
                       "get [k](){return await work()}", "set x(v){v}", "async(){}"):
            yield "({" + modifiers + " " + member + "});"
    for prefix in ("export @first", "default @one @two(p)", "public async export @d", "async default @d public",
                   "export @a async default @b", "static @d", "@d async"):
        for member in ("x", "x=1", "...rest", "get [k](){return y}", "async *f(){yield await v}"):
            yield "({" + prefix + " " + member + "});"
    for member in ("__proto__:a, __proto__:b", '__proto__:a, "__proto__":b',
                   '["__proto__"]:a, __proto__:b', "get:x, set:y, async:z", "async *[k]<T>(v:T){}",
                   "async, get, set", "get x?(){}", "[k]", "static *[a](){}", "#async x:1", "#export @d x:1", "#default @d x:1", "#async(){}"):
        yield "({" + member + "});"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases = [{"name": "object.ts", "source": s, "projection": "object elements"} for s in examples()]
    refs = run_compiler(archive, _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text(), cases)
    pipeline = TypeScriptPipeline("object.ts")
    accepted = rejected = failures = 0
    for case, ref in zip(cases, refs, strict=True):
        try:
            tree = pipeline.parse(case["source"])
        except SourceSyntaxError as error:
            if ref.get("invalid") and 0 <= error.offset <= len(case["source"]):
                rejected += 1
                continue
            actual = str(error)
        else:
            actual = project_trees(tree, case["projection"])
            if actual and actual == ref.get("trees"):
                accepted += 1
                continue
        print(repr(case["source"]), actual, ref)
        failures += 1
    print(f"{accepted} matching object trees, {rejected} jointly rejected, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
