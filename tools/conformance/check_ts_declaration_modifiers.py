"""Check declaration-prefix disambiguation, modifier order, and decorators against TS 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, _STATEMENT_SHAPE, TypeScriptPipeline, check_pin, run_compiler


def cases():
    prefixes = ("", "public ", "async ", "static\n", "abstract ", "accessor ", "declare ", "declare declare ",
                "export ", "export export ", "export declare ", "declare export ", "export default @d ", "export default @a @b ", "@d ", "@a export @b ")
    forms = ("class C {}", "interface I {}", "type T = X", "namespace N {}", 'module "m" {}',
             "enum E {A}", "var v;", "const x = 1", "function f() {}", "import x = N.X;",
             "export { x };", "export = x;")
    for prefix in prefixes:
        for form in forms:
            yield {"name": "prefixes.ts", "source": prefix + form, "projection": "declaration modifiers"}
    for source in ("async\nclass C {}", "public\nvar x", "public;", "static static class C {}",
                   "async public function f(){return await;}", "@d foo()", "public import('pkg')",
                   "public abstract class C{}", "async public function f(){return await work()}",
                   "export default @d class {}", "@a export @b class C{}", "declare async function f<T>(): T;",
                   "export @d default class C{}", "@d default class C{}", "export @a default @b class C{}",
                   "@d default @q class C{}", "public @d class C{}", "export abstract @d class C{}",
                   "@new factory() class C{}", "@f().x class C{}", "@f?.[name] interface I{}",
                   "@f?.() type T = X", "@f`x` class C{}", "@(f[key]) class C{}", "@f[key] class C{}",
                   "async public function* f<T>(v:T){yield await v}", "declare let;", "export let;"):
        yield {"name": "prefixes.ts", "source": source, "projection": "declaration modifiers"}

    for prefix in ("const", "static const", "const static", "async", "async override", "public async",
                   "async readonly static", "static async", "async abstract"):
        for tail in ("x=4;", "x?:T;", "[key]!:T = v;", "#secret:T;", "m<T>(v:T):T;", "*m<T>(v:T){yield v;}"):
            yield {"name": "members.ts", "source": "class C{" + prefix + " " + tail + "}", "projection": "class member modifiers"}
    for member in ("async static {}", "const static {}", "async\nx=1;", "const\nenum;", "async=1;", "const(){}",
                   "static async {}", "const *", r"c\u006fnst x;", "async get x(){return value;}"):
        yield {"name": "members.ts", "source": "class C{" + member + "}", "projection": "class member modifiers"}

    for source in ("async function outer(){ function f(@#await p:T){} }",
                   "namespace N{export class C{async m(@await p){}}}",
                   "export class C{async m(@d(await) p){}}",
                   "export {}; namespace N{class C{m(@await p){}}}",
                   "export {}; interface I{m(@await p):T}"):
        yield {"name": "parameters.ts", "source": source, "projection": "decorated parameter"}
    for prefix, end in [("", ""), ("export {}; ", ""), ("async function outer(){", "}"),
                        ("function* outer(){", "}"), ("class Outer {static {", "}}")]:
        for form in ["function inner(PARAM){}", "async function inner(PARAM){}",
                     "const inner=function(PARAM){};", "class C{m(PARAM){}}", "class C{async m(PARAM){}}"]:
            for param in ["@await x:T", "@await() x:T", "@d(await) x:T", "@d(await value) x:T",
                          "@d(await value) x=await init", "@d this:T", "...this:T"]:
                yield {"name": "parameters.ts", "source": prefix + form.replace("PARAM", param) + end,
                       "projection": "decorated parameter"}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    inputs = list(cases())
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    matched = rejected = failures = 0
    for case, ref in zip(inputs, run_compiler(archive, oracle, inputs), strict=True):
        try:
            root = TypeScriptPipeline(case["name"]).parse(case["source"])
        except ValueError as exc:
            if ref.get("invalid"):
                rejected += 1
                continue
            actual = str(exc)
        else:
            actual = project_trees(root, case["projection"])
            if actual == ref.get("trees"):
                matched += 1
                continue
        print(case["source"], "Orion", actual, "TypeScript", ref)
        failures += 1
    print(f"{matched} matching declaration cases, {rejected} jointly rejected inputs, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
