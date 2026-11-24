"""Verify await expressions and identifier uses in TypeScript module blocks."""
import argparse
from pathlib import Path

from orionparser.languages.javascript.pipeline import SourceSyntaxError
from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler


def examples():
    for name in ("n.ts", "n.d.ts", "n.mts", "n.d.cts"):
        for wrapper in ("namespace N.M{@}", "export namespace N{@}", "export {}; namespace N{@}",
                        'declare module "m"{@}', "export {}; declare global{@}",
                        "async function f(){ namespace N{@} }", "export {}; {await(k); namespace N{@}}",
                        "export {}; {await k; namespace N{@}}", "export namespace N{namespace M{@}}",
                        "export {}; namespace N{export namespace M{@}}"):
            for stmt in ("const x=await;", "export const x={await};", "let x=await(y);", "await load();",
                         "const fn=async()=>await item;", "export default await;", "export = await load();"):
                yield dict(name=name, source=wrapper.replace("@", stmt), projection="namespace statements",
                           compilerModuleDetection=True)
        for prefix in ("", "export {}; "):
            for expr in ("await /x/;", "await /=x/;", "await /x/g;", "await /ab+c/;", "await /x/.test(v);",
                         "await /x/; await /y/;", "await \n/x/;", "await /ab*/;", "await /a(b)/;",
                         "await /a|b/;", "await /(?<n>x)/;", "await /(?:abc)/;", "await /(?=x)y/;", r"await /a\/b/;", "await /[a-z]/;", "await /a{2}/;",
                         "await /a/ / 2;", "await /a/ + /b/;", "await /x/?.test(v);", "await /x/.exec(v)\n", "await /[/]/;", "await {x:1};", "x/;"):
                yield dict(name=name, source=prefix + expr + " namespace N{const n=await;}",
                           projection="namespace replay", compilerModuleDetection=True)
        for source in ("await /x/; namespace N{const x=await;} export {};",
                       "await /x/.test(v); namespace N{await(v)} import type {T} from 'p';",
                       "await / left / right; namespace N{const x=await;}",
                       "export {}; await / left / right; namespace N{const x=await;}",
                       "export {}; {await /x/; namespace N{const x=await;}}",
                       "export {}; before(); await /x/; after(); namespace N{const x=await;}"):
            yield dict(name=name, source=source, projection="namespace replay", compilerModuleDetection=True)


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
            root = TypeScriptPipeline(c["name"]).parse(c["source"])
        except SourceSyntaxError as exc:
            if ref.get("invalid") and 0 <= exc.offset <= len(c["source"]):
                rejected += 1
                continue
            actual = str(exc)
        else:
            actual = project_trees(root, c["projection"])
            if actual == ref.get("trees"):
                accepted += 1
                continue
        print(c["name"], repr(c["source"]), actual, ref)
        failures += 1
    print(f"{accepted} matching namespace files, {rejected} jointly rejected, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
