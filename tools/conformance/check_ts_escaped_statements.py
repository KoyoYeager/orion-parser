"""Compare escaped let, await and yield in statement and expression positions with TypeScript 5.9.3."""
import argparse
from pathlib import Path

from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler
from check_ts_alias_shapes import project_trees
from orionparser.languages.javascript.pipeline import SourceSyntaxError


def cases():
    for name in ("let", r"\u006cet", r"l\u{65}t"):
        for head in ("@", "/*𐐀*/ @"):
            word = head.replace("@", name)
            for suffix in (" x=0;", "\nx;", " /*c*/ [x]=a;", " {x}=a;", " yield;", " await;",
                           "();", ";", "=x;", ".x;", ":x();"):
                yield word + suffix
            for tail in (" of xs", " in xs", "=0;;", ";;", "[x] of xs", ".x of xs"):
                yield "for (" + word + tail + ") {}"
        for form in ("let @=1;", "fn(@);", "obj.@;", "({@:1});", "(@)=>@;", "if (ok) @ x;",
                     "export @ x=1;", "declare @ x:T;", "for (let @ of xs){}",
                     "for (x; @ [p]; @()) {}", "for await (@ of xs){}", "function f(@=x){}"):
            yield form.replace("@", name)
        yield "class C{" + name + "\n[x]() {}}"

    for name in (r"\u0061wait", r"\u0079ield"):
        for stmt in ("@;", "@(x);", "@+1;", "@*v;", "@ of;", "@ v;", "@\nv;", "@.field;",
                     "obj.@;", "let @=v;", "for (@ of xs){}", "for (@\nof xs){}"):
            for context in ("@", "function f(){@}", "async function f(){@}", "function* f(){@}",
                            "async function* f(){@}", "export {}; @"):
                yield context.replace("@", stmt.replace("@", name))
    for source in (r"for \u0061wait (x of xs){}", r"async function f(){for \u0061wait(x of xs){}}",
                   r"async function f(){(\u0061wait)=>0;}", r"function* f(){(\u0079ield)=>0;}"):
        yield source

    for await_word, using in (("await", "using"), (r"\u0061wait", "using"), ("await", r"\u0075sing"),
                              (r"\u0061wait", r"\u0075sing")):
        for gap in (" ", "\n", "/*𐐀\n*/"):
            for binding in (" x", " let", " {k}", "\nx"):
                head = await_word + gap + using + binding
                yield head + "=res;"
                yield "for (" + head + " of xs){}"
    for name in ("using", r"u\u0073ing"):
        for tail in (" x=res;", " let=res;", " of=res;", ";", "(x);", "[key]=v;"):
            yield name + tail
    for op in (r"\u006ff", r"\u0069n"):
        for target in ("x", "const x", "let x", "using x"):
            yield "for (" + target + " " + op + " xs){}"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    inputs = []
    for source in cases():
        projection = "branch statement"
        if source.startswith("export ") and not source.startswith("export {};"):
            projection = "declaration list"
        elif source.startswith("class "):
            projection = "class members"
        inputs.append(dict(name="let.ts", source=source, projection=projection, diagnosticSpans=True))
    for name in ("main.ts", "main.tsx", "main.mts", "main.cts", "main.d.ts", "main.d.mts", "main.d.cts"):
        for source in ("await\nusing x=open();", r"for (\u006cet of xs){}", r"obj.\u006cet;",
                       r"export {}; await \u0075sing item = open();"):
            inputs.append(dict(name=name, source=source, projection="file context", diagnosticSpans=True,
                               compilerModuleDetection=True))
    for declaration in ("var", "let", "const", "using", "await using"):
        for name in ("let", "yield", "await", "static", "interface", "of", "async", "enum", "get", "as",
                     "in", "default", "arguments", "𐐀"):
            loop = f"for ({declaration} of {name}) {{}}"
            for wrapper in ("@", "export {}; @", "function* f(){@}", "async function f(){@}", "class C{static {@}}"):
                inputs.append(dict(name="of.ts", source=wrapper.replace("@", loop), projection="iteration",
                                   diagnosticSpans=True))
    for filename in ("loop.ts", "loop.tsx", "loop.mts", "loop.cts", "loop.d.ts", "loop.d.mts", "loop.d.cts"):
        for prefix in ("", "export {}; "):
            for name in ("yield", "await", "static", "interface"):
                inputs.append(dict(name=filename, source=f"{prefix}for(let of {name}){{}}", projection="iteration",
                                   compilerModuleDetection=True, diagnosticSpans=True))
    for prefix in ("", "declare ", "public ", "abstract ", "async ", "export ", "@d ", "export @d ",
                   "@d export ", "@d public ", "@d declare ", "@d in ", "@d out "):
        for head in ("using x", "using\nx", "using [x]", "using {x}", "await using x", "await\nusing x"):
            inputs.append(dict(name="resource.ts", source=prefix + head + "=v;", projection="resource statements",
                               diagnosticSpans=True))
    for source in ("@d using;", "@d using\nif(x)y();", "@d using x:T;", "@d export using x, y=v;"):
        inputs.append(dict(name="resource.ts", source=source, projection="resource statements", diagnosticSpans=True))
    for prefix in ("public using ", "async using ", "public await using ", "@d using "):
        for name in ("await", "yield", "let", "of"):
            inputs.append(dict(name="resource.ts", source="export {}; " + prefix + name + "=v;",
                               projection="resource statements", diagnosticSpans=True))
    for filename in ("decl.ts", "decl.tsx", "decl.mts", "decl.cts", "decl.d.ts", "decl.d.mts", "decl.d.cts"):
        for source in ("export @d using\n[x]:T=open();", "@d using;", "@a out await using x=v;",
                       "export {}; public using await=v;", "@d using x=v; using\ny=v;"):
            inputs.append(dict(name=filename, source=source, projection="resource statements",
                               compilerModuleDetection=True, diagnosticSpans=True))
    refs = run_compiler(archive, _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text(), inputs)
    accepted = exact = other = failures = 0
    pipelines = {name: TypeScriptPipeline(name) for name in {case["name"] for case in inputs}}
    for c, ref in zip(inputs, refs, strict=True):
        try:
            root = pipelines[c["name"]].parse(c["source"])
        except SourceSyntaxError as error:
            actual = [error.code, error.offset, error.length]
            if ref.get("diagnostics", [])[:1] == [actual]:
                exact += 1
                continue
            if ref.get("invalid") and ref["diagnostics"][0][0] != 1260 and error.code is None:
                other += 1
                continue
        else:
            actual = project_trees(root, c["projection"])
            if actual and actual == ref.get("trees"):
                accepted += 1
                continue
        print(repr(c["source"]), actual, ref)
        failures += 1
    print(f"{accepted} matching trees, {exact} exact first diagnostics, {other} other joint rejections, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
