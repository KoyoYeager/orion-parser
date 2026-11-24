"""Compare TS type-list lookahead and expression fallback with TypeScript 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler
from orionparser.languages.javascript.pipeline import SourceSyntaxError


def cases():
    words = ("super", "class", "const", "return", "default", "in", "export", "enum", "case", "for",
             "switch", "with", "var", "let", "public", "await", "yield", "string", "T")
    for word in words:
        term = word + ".x"
        for pattern in ("@", "(@)", "Box<@>", "Box<T,@>", "Box<(@)>", "Box<((@))>", "[@]", "[T,@]",
                        "T[@]", "@ | Q", "Box<@ | T>", "Box<Q | @>", "`x${Box<@>}`"):
            yield "type.ts", "type R = " + pattern.replace("@", term) + ";", "alias"
        for pattern in ("f<@>(a)", "f<Q,@>(a)", "f<(@)>(a)"):
            yield "expr.ts", pattern.replace("@", term) + ";", "target expression"
    for word in ("super", "const", "import", "let", "class"):
        yield "call.ts", "f<" + word + ">(x);", "target expression"
        yield "tuple.ts", "type R = [" + word + ": T];", "alias"
        yield "jsx.tsx", "<C<" + word + ".x>/>;", "JSX"
    for expr in ("g<await>(a)", "g<T,await>(a)", "g<Box<await>>(a)", "g<(await)>(a)", "new G<await>(a)",
                 "g<yield>(a)", "g<T,yield>(a)", "g<Box<yield>>(a)", "g<(yield)>(a)", "g?.<yield>(a)",
                 "g?.<await>(a)", "x + yield", "g<super.x>(a)", "g<Options.super>(a)"):
        for kind in ("function", "async function", "function*", "async function*"):
            yield "scope.ts", kind + " f(){" + expr + ";}", "branch statement"
        yield "scope.ts", "class C{static {" + expr + ";}}", "computed await"
        yield "scope.ts", "export {}; " + expr + ";", "branch statement"
    for word in ("await", "yield"):
        for kind in ("async function", "function*"):
            yield "scope.ts", kind + " f(){let x:Box<" + word + ">;}", "declaration list"
            yield "scope.tsx", kind + " f(){return <C<" + word + ">/>;}", "JSX"
    # The same identifier spellings can instead be parameters of a function
    # type. Verify that the modifier and the binding name remain separate.
    for word in ("super", "const", "return", "class", "in", "default", "enum", "function", "new", "this",
                 "let", "yield", "await", "get", "set", "readonly", "public", "static", "override", "abstract",
                 "async", "using", "out", "infer", "void", "true", "null", "import", "export", "debugger",
                 "extends", "protected", "arguments", "eval"):
        for pattern in ("@", "@:T", "@?:T", "...@:T[]", "@=v", "readonly @:T"):
            parameter = pattern.replace("@", word)
            yield "parameter.ts", "function f(" + parameter + "){}", "function source"
            yield "parameter.ts", "const f=(" + parameter + ")=>0;", "arrow signature"
            yield "parameter.ts", "type F=(" + parameter + ")=>R;", "alias"
            yield "parameter.ts", "type F={(" + parameter + "):R};", "alias"
            yield "parameter.ts", "class C{m(" + parameter + ") {}}", "class method signature"
    for prefix in ("export @d", "default @d", "export default @d", "@a export @b", "export @a @b readonly",
                   "export @a export @b", "@a export @b export @c", "readonly @d", "export\n@d"):
        for binding in ("x:T", "let:T", "...xs:T[]", "{x}:T"):
            param = prefix + " " + binding
            yield "decorated.ts", "function f(" + param + "){}", "function source"
            yield "decorated.ts", "class C{m(" + param + ") {}}", "class method signature"
            yield "decorated.ts", "type F=(" + param + ")=>R;", "alias"
            yield "decorated.ts", "const f=(" + param + ")=>x;", "arrow signature"
    for word in ("true", "false", "null", "this", "void", "function", "typeof", "return", "super", "import",
                 "number", "boolean", "any", "unknown", "symbol", "readonly", "keyof", "infer", "unique",
                 "never", "string", "undefined", "intrinsic", "object", "bigint", "new", "asserts", "abstract"):
        for spelling in (r"\u%04x" % ord(word[0]) + word[1:], word[:-1] + r"\u{%x}" % ord(word[-1])):
            for form in ("@", "@.member", "NS.@", "Box<@>", "typeof @", "{@:T}", "[@:T]",
                         "(@:T)=>R", "(@)=>R", "@()", "@<T>", "(@ extends T ? X : Y)"):
                yield "escape.ts", "type X=" + form.replace("@", spelling) + ";", "alias"
            for expression in ("f<@>(x)", "f<@>+x", "f<@.X>(x)", "f<NS.@>(x)", "f<@>"):
                yield "escape.ts", expression.replace("@", spelling) + ";", "target expression"
    for filename in ("kind.ts", "kind.tsx", "kind.mts", "kind.cts", "kind.d.ts", "kind.d.mts", "kind.d.cts"):
        for term in (r"\u0074rue", r"NS.\u0074rue", r"{\u0074rue:T}", r"Box<n\u0075mber>",
                     r"n\u0075mber.X", r"\u0066unction", r"\u0066unction()", r"\u0066unction.X"):
            yield filename, "export type X = " + term + ";", "alias"
    terms = ("typeof F<T>", 'typeof import("m").F<string>', 'import("m", {with:{type:"json"}}).X',
             "infer X extends T", "keyof T", "readonly [head:X,...tail:Y[]]",
             "{[K in keyof T as `x${K & string}`]?: T[K]}", "{get x(): T; set x(v:T);}",
             "(x:unknown)=>x is T", "abstract new<X extends T>(v:X)=>X", "X extends Y ? A : B",
             "T[K][]", "T & (A|B)", "(T|B)[K]", "function(this:T,...U=):V",
             "(s:T)=>asserts s is U", "unique symbol", "this is X", "[name?:T]", "`x${T}`",
             "typeof this.#x", "null|undefined", "-42n", 'import("m").default', "super.x")
    for term in terms:
        for pattern in ("@", "Box<@>", "(@)[]", "@ | never", "`inner${@}`", "X extends @ ? true : false"):
            yield "nested.ts", "type R<T,K> = `outer${" + pattern.replace("@", term) + "}end`;", "template spelling"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    inputs = [dict(name=n, source=s, projection=p, diagnosticSpans=True) for n, s, p in cases()]
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    asts = exact = rejections = failures = 0
    for case, ref in zip(inputs, run_compiler(archive, oracle, inputs), strict=True):
        try:
            root = TypeScriptPipeline(case["name"]).parse(case["source"])
        except SourceSyntaxError as error:
            actual = [error.code, error.offset, error.length]
            if ref.get("diagnostics", [])[:1] == [actual]:
                exact += 1
                continue
            if error.code is None and ref.get("invalid"):
                rejections += 1
                continue
        else:
            actual = project_trees(root, case["projection"])
            if actual and actual == ref.get("trees"):
                asts += 1
                continue
        print(case["source"], actual, ref)
        failures += 1
    print(f"{asts} matching trees, {exact} exact first diagnostics, {rejections} other joint rejections, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
