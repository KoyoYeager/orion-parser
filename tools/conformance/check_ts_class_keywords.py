"""Compare class keyword names, modifiers and line boundaries with TypeScript 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler
from orionparser.languages.javascript.pipeline import SourceSyntaxError


def cases():
    for keyword in ("static", "get", "set", "export", "readonly", "async", "public", "default"):
        escaped = r"\u%04x" % ord(keyword[0]) + keyword[1:]
        for word in (keyword, escaped):
            for gap in (" ", "\n", "/*𐐀\r\n*/"):
                for member in ("x:T;", "x(){}", "*x(){}", "#x:T;", "[x](){}", "{}", "@d x:T;"):
                    yield "class C{" + word + gap + member + "}"
            for suffix in ("(){}", ":T;", "!:T;", "?:T;", "=0;", "<T>(){}", ";"):
                yield "class C{" + word + suffix + "}"
    for prefix in ("static ", "public static ", "static public "):
        for tail in ("static(){}", r"\u0073tatic(){}", "static\nx:T;", r"\u0073tatic" + "\nx:T;"):
            yield "class C{" + prefix + tail + "}"
    for prefix in ("@a export @b ", "public export @b ", "export default\n@b ", "export\n@a export @b ",
                   "@a export @b export @c ", "export @b ", "export\n@a @b readonly ", "@a static "):
        for body in ("x:T;", "m(){}", "get p(){return v;}", "set p(v){}"):
            yield "class C{" + prefix + body + "}"
    for prefix in ("@a", "async", "public", "static", "abstract", "export default", "declare", "accessor",
                   "const", "static async", "async public", "async static", "@a export", "public export",
                   "public @a", "readonly"):
        for suffix in (" default\n@b f(){}", " export @b f(){}", " static\nq:T;", " static(){}",
                       " get\n*x(){}", " @d x:T;", " @d\n@b y:T;"):
            yield "class C{" + prefix + suffix + "}"

    for prefix in ("", "public ", "static ", "static public ", "public static ", "async public ",
                   "@d ", "static async export @d ", "static static ", "async static "):
        for block in ("static {run(x);}", "static\n{if(x)run(x);}", r"\u0073tatic {run(x);}",
                      "static(){}", "static:T;"):
            yield "class C{" + prefix + block + "}"
    for prefix in ("", "static ", "public ", "async ", "async public ", "static async ", "export\n@d ",
                   "@d ", "static async export @d ", "public static ", "readonly ", "async static "):
        for name in ("[k:string]:T;", "[k:number]:X;", "[...k:string[]]:T;", "[k?x:y]:T;", "[k]!:T;",
                     "[k]:T=use(v);", "[k]():void;", "[k]<T>(v:T){}"):
            yield "class C{" + prefix + name + "}"
    for modifier in ("public", "private", "protected", "async", "abstract", "declare", "accessor", "static",
                     "override", "readonly", "in", "out", "export", "default", "const", "get", "set"):
        for entry in (" k:string", " let:number", ":T", "?x:y"):
            yield "class C{[" + modifier + entry + "]:T;}"
    for context in ("class C{@}", "async function f(){class C{@}}", "function* f(){class C{@}}",
                    "async function* f(){class C{@}}", "export {}; class C{@}"):
        for key in ("await:T", "yield:T", "public await:T", "async yield:T", "await ? x : y", "yield ? x : y"):
            yield context.replace("@", "[" + key + "]:R;")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases_to_parse = [dict(source=s, name="member.ts", projection="class keyword members", diagnosticSpans=True) for s in cases()]
    for name in ("member.tsx", "member.mts", "member.cts", "member.d.ts", "member.d.mts", "member.d.cts"):
        for body in ("static\nx:T;", r"\u0073tatic" + "\nx:T;", "export\n@d x:T;", "async!:T;",
                     "static async export @d static {run(x);}", "static static {run(x);}"):
            cases_to_parse.append(dict(source="export class C{" + body + "}", name=name,
                                       projection="class keyword members", diagnosticSpans=True))
    for function in ("async function", "function*", "async function*"):
        for decl in ("type R = {[k:T]:R};", "interface I{[k:T]:R}", "interface I{x:{[k:T]:R}}"):
            for name in ("await", "yield", "public await", "static yield"):
                source = function + " f(){" + decl.replace("[k:", "[" + name + ":") + "}"
                cases_to_parse.append(dict(source=source, name="context.ts", projection="branch statement", diagnosticSpans=True))
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    refs = run_compiler(archive, oracle, cases_to_parse)
    pipelines = {name: TypeScriptPipeline(name) for name in {case["name"] for case in cases_to_parse}}
    accepted = exact = rejected = failures = 0
    for case, ref in zip(cases_to_parse, refs, strict=True):
        try:
            tree = pipelines[case["name"]].parse(case["source"])
        except SourceSyntaxError as error:
            actual = [error.code, error.offset, error.length]
            if ref.get("diagnostics", [])[:1] == [actual]:
                exact += 1
                continue
            if ref.get("invalid") and ref["diagnostics"][0][0] != 1260:
                rejected += 1
                continue
        else:
            actual = project_trees(tree, case["projection"])
            if actual and actual == ref.get("trees"):
                accepted += 1
                continue
        print(repr(case["source"]), actual, ref)
        failures += 1
    print(f"{accepted} matching class trees, {exact} exact first diagnostics, {rejected} other joint rejections, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
