"""Compare computed class member names across await contexts with TypeScript 5.9.3."""
import argparse
from pathlib import Path

from orionparser.languages.javascript.pipeline import SourceSyntaxError
from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler


def examples():
    for file in ("x.ts", "x.d.ts", "x.mts", "x.d.cts"):
        for prefix, suffix in (("", ""), ("export ", ""), ("export declare ", ""), ("export {}; ", ""),
                               ("export {}; declare ", ""), ("async function f(){", "}"),
                               ("namespace N {export ", "}")):
            for member in ("[await]():T", "static [await.x]:T", "[await x]?:T", "get [await + v](){}",
                           "[o.await]:T", "[f(await)]:T", "[x=>await]:T", "[async()=>await x]:T", "[()=>({await})]:T", "[async()=>({await})]:T",
                           "[{await}]:T", "[{await:1}]:T", "field=[await]", "m(){return await}", "m(){return {await}}", "*g(){yield {await}}",
                           "async m(){return {await}}"):
                yield dict(name=file, source=prefix + "class C{" + member + "}" + suffix,
                           projection="computed await", compilerModuleDetection=True)
        for members in ("[await]():T; other(){return await}", "[await]():T; field=o.await",
                        "[await]():T; field=await", "[await]():T; [await]=1",
                        "[{await}]:T; [await]=1", "get [await]():T;", "set [await](v);",
                        "static [f(await)]<T>(v:T):T;", "[await + v](){}", "[await + v]():T",
                        "[await]():T; [k](await:T){}", "[await]():T; [k](p=await){}",
                        "[await]():T; x={await:1}", "[await]():T; x={await=1}",
                        "[await]():T; x=class { [await]():T }", "[await]():T; static { doWork() }"):
            for prefix in ("export {}; ", "export "):
                yield dict(name=file, source=prefix + "class C{" + members + "}",
                           projection="computed await", compilerModuleDetection=True)
        for prefix in ("export @d ", "@d export ", "export default @d ", "export declare abstract "):
            for member in ("@m [await]():T", "async *[await x](){}", "public static [await]?:T",
                           "get [o.await](){return x}"):
                yield dict(name=file, source=prefix + "class C{" + member + "}",
                           projection="computed await", compilerModuleDetection=True)
        for source in ("export {}; const C=class{[await]():T};",
                       "export {}; const C=class{[await]():T}, k=await;",
                       "export {}; let obj={cls:class{[{await}]:T}};",
                       "export const C=class{[await]():T};", "export default (class{[await]():T});",
                       "export {}; class X{[class{[await]():T}](){}}"):
            yield dict(name=file, source=source, projection="computed await", compilerModuleDetection=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases = list(examples())
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
            actual = project_trees(tree, "computed await")
            if actual and actual == ref.get("trees"):
                accepted += 1
                continue
        print(c["name"], repr(c["source"]), actual, ref)
        failures += 1
    print(f"{accepted} matching class trees, {rejected} joint rejections, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
