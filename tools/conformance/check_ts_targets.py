"""Compare assignment/update acceptance, operands, precedence and grouping with TS 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import operand, project_trees
from check_typescript import COMPILER_SHA, _STATEMENT_SHAPE, TypeScriptPipeline, check_pin, run_compiler


def cases():
    operands = [
        "a", "1", "true", "this", "get()", "new C()", "obj.x", "obj[k]", "obj?.x",
        "obj?.[k]", "obj!.x", "(a as T)", "a+b", "(a+b)", "a?b:c", "(a?b:c)",
        "tag?.`x`", "(a?.b)<T>`p${k}q`", "a?.<T>`x`", "new.foo", "import.metal", "new.#x",
        "super.x", "super[k]", "super()", "a++", "(a++)", "void a", "(void a)", "[]", "([a])", "[a,,...tail]",
        "[...x = 1,y]", "({x:a})", "(a,b)", "import.meta", "(class {})",
    ]
    for left in operands:
        for form in ("++{}", "--{}", "{}++", "{}--", "{} = rhs", "{} += rhs", "{} ??= rhs"):
            yield form.format(left)
    yield from ("obj?.x = a = rhs", "[a = 0, {x: b}, ...tail] = rhs", "a\n++b",
                "++-x", "++x++", "[] = ", "a + = b", "++", "get() **= b", "a\n++")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    inputs = [{"name": "targets.ts", "source": src + ";", "projection": "target expression"} for src in cases()]
    for name in ("construct.ts", "construct.tsx"):
        for callee in ("C", "C<T>", "ns.C<T>", "(C<T>)", "C[k]", "(a?.Ctor)", "new C", "new C<T>()"):
            for arguments in ("", "()", "(x)", "(x,)", "(x,...ys,)"):
                inputs.append({"name": name, "source": "new " + callee + arguments + ";", "projection": "target expression"})
        for callee in ("f", "super", "async", "f<T,>", "a?.b", "a?.<T>", "f(x,)", "import", "import.defer", "import.defer?.", "import.defer?.<T>", "(import.defer)"):
            for arguments in ("()", "(x)", "(x,)", "(x,...ys,)"):
                inputs.append({"name": name, "source": callee + arguments + ";", "projection": "target expression"})
        for expr in ("a<b>=c", "a<b>>c", "a<b>>>c", "a<b>==c", "a<b>===c", "a<b>>=c",
                     "f<T> >=v", "f<T>\n>>v", "a<b<c>>=d", "a<b<c>>(x)", "a<b<c<d>>>(x)", "a<b> = c", "new C<T>=x"):
            inputs.append({"name": name, "source": expr + ";", "projection": "target expression"})
    for expr in ("new super()", "new super(arg).p", "new super", "new super<T>(arg)", "new super()(x)",
                 "new super.#x", "new (super)()", "new super?.x"):
        inputs.append({"name": "super.ts", "source": expr + ";", "projection": "target expression"})
    for base in ("a?.b!", "(a?.b)!", "a<T>", "a?.b<T>", "a?.b!!", "a?.b!`x`", "(a?.b<T>)"):
        for suffix in ("?.()", "?.<U>()", "()", ".p", "?.p", "[x]", "?.[x]", "`q`", "?.`q`", "<U>`q`", ".#p"):
            inputs.append({"name": "chain.ts", "source": base + suffix + ";", "projection": "target expression"})
    for base in ("<A/>", "<B>text</B>", "<>child</>", "(<A/>)", "typeof <A/>", "+<A/>"):
        for suffix in (" < name", " <= n", ".key", "[x]", "\n[x]", "()", "\n(x)", "?.x", " ** 2", " as T", "<B/>"):
            inputs.append({"name": "jsx.tsx", "source": base + suffix + ";", "projection": "target expression"})
    for left_op in ("??", "||", "&&"):
        for right_op in ("??", "||", "&&"):
            for expr in (f"a {left_op} b {right_op} c", f"(a {left_op} b) {right_op} c",
                         f"a {left_op} (b {right_op} c)", f"a {left_op} b {right_op} c ? d : e"):
                inputs.append({"name": "logical.ts", "source": expr + ";", "projection": "target expression"})
    for filename in ("assert.ts", "assert.mts", "assert.cts", "assert.tsx"):
        for expr in ("<const>x", "<const[]>x", "<const.X>x", "<const<T>>x", "<const | T>x",
                     "<const T>(x:T)=>x", "<const T,>(x:T)=>x"):
            inputs.append({"name": filename, "source": expr + ";", "projection": "target expression"})
    for filename in ("assert.ts", "assert.tsx"):
        for head in ("x as number", "x + y as T", "x satisfies (T|U)", "x as const", "x as Box<T>"):
            for op in ("+", "-", "*", "/", "%", "**", "<<", ">>", ">>>"):
                for right in ("y + z * q", "y ** z ** q", "y as U * z"):
                    inputs.append({"name": filename, "source": f"{head} {op} {right};", "projection": "target expression"})
                inputs.append({"name": filename, "source": f"for ({head} {op} y in obj) {{}}", "projection": "iteration"})
        for expr in ("x as T / /r/.test(y)", "x as T / /r/.test(y) ** z", "x as T * y satisfies R + z",
                     "x as T + y as U / z", "(x as T) / /r/.source", "x as T++",
                     "x as typeof obj << y", "x satisfies typeof obj.m << n + 2", "x as typeof number<T> / z",
                     "x as typeof this.key << n", "x as N.number<T> / y", "x as const<T> * y",
                     "x as Box<Box<T>>>>n", "x satisfies number/**/<<n", "x as T\n<<n",
                     "x as typeof obj<<n", 'x as typeof import("p").T<<n',
                     "x as T<X>**-y", "x as const[]/ /r/.source"):
            inputs.append({"name": filename, "source": expr + ";", "projection": "target expression"})
    for head in ("v++", "++v", "a=1", "a,b", "a ? b in c : d", "a+b*c", "(a in b)", "async", "let.x",
                 "(let.x)", "obj[k]", "{x:v}", "[v]", "var v=1", "let", "let x:T", "const x,y", "using x"):
        for separator in ("in", "of"):
            for prefix in ("for", "for await"):
                inputs.append({"name": "iteration.ts", "source": f"{prefix} ({head} {separator} xs) {{}}",
                               "projection": "iteration"})
    for tail in ("x in b,c", "x of b,c", "x of (b,c)", "x of k in o", "async of => x;;", "let of of xs"):
        inputs.append({"name": "iteration.ts", "source": f"for ({tail}) {{}}", "projection": "iteration"})
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    matched = invalid = failures = 0
    for case, ref in zip(inputs, run_compiler(archive, oracle, inputs), strict=True):
        try:
            root = TypeScriptPipeline(case["name"]).parse(case["source"])
        except ValueError as exc:
            if ref.get("invalid"):
                invalid += 1
                continue
            actual = str(exc)
        else:
            try:
                actual = (project_trees(root, "iteration") if case["projection"] == "iteration" else
                          [operand(s["expression"]) for s in root["body"]])
            except ValueError as exc:
                actual = str(exc)
            if actual == ref.get("trees"):
                matched += 1
                continue
        print(case["source"], "Orion", actual, "TypeScript", ref)
        failures += 1
    print(f"{matched} matching expression cases, {invalid} jointly rejected cases, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
