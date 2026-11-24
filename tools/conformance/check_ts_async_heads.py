"""Differential check for async call/arrow lookahead in parameter and expression contexts."""
import argparse
from pathlib import Path

from check_typescript import COMPILER_SHA, TypeScriptPipeline, check_pin, run_compiler

_ORACLE = """
const ts = require(process.argv[1]);
const cases = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
function shape(n) {
    if (ts.isParenthesizedExpression(n)) return shape(n.expression);
    if (ts.isConditionalExpression(n)) return ["conditional", shape(n.whenTrue), shape(n.whenFalse)];
    if (ts.isArrowFunction(n)) return ["arrow", (n.modifiers || []).some(m => m.kind === ts.SyntaxKind.AsyncKeyword),
        n.parameters.map(p => [p.name.getText(), !!p.type, p.initializer ? shape(p.initializer) : null]),
        !!n.type, shape(n.body)];
    if (ts.isCallExpression(n)) return ["call", shape(n.expression), n.arguments.map(shape)];
    if (ts.isYieldExpression(n)) return ["yield", !!n.asteriskToken, n.expression ? shape(n.expression) : null];
    if (ts.isAwaitExpression(n)) return ["await", shape(n.expression)];
    if (ts.isJsxSelfClosingElement(n)) return ["jsx", n.tagName.getText()];
    if (ts.isIdentifier(n)) return ["name", n.text];
    if (ts.isNumericLiteral(n)) return ["number", n.getText()];
    throw new Error("unmapped expression " + ts.SyntaxKind[n.kind]);
}
process.stdout.write(JSON.stringify(cases.map(c => {
    const f = ts.createSourceFile(c.name, c.source, ts.ScriptTarget.ESNext, true);
    if (f.parseDiagnostics.length) return null;
    const stmt = f.statements[f.statements.length - 1];
    const list = ts.isClassDeclaration(stmt) ? stmt.members[0].body.statements[0] :
        ts.isFunctionDeclaration(stmt) ? stmt.body.statements[0] : stmt;
    return shape(list.declarationList.declarations[0].initializer);
})));
"""


def shape(n):
    kind = n["type"]
    if kind == "ConditionalExpression":
        return ["conditional", shape(n["consequent"]), shape(n["alternate"])]
    if kind == "ArrowFunctionExpression":
        params = []
        for p in n["params"]:
            init = None
            if p["type"] == "AssignmentPattern":
                init = shape(p["right"])
                p = p["left"]
            params.append([p["name"], bool(p.get("typeAnnotation")), init])
        return ["arrow", n["async"], params, bool(n.get("returnType")), shape(n["body"])]
    if kind == "CallExpression":
        return ["call", shape(n["callee"]), [shape(a) for a in n["arguments"]]]
    if kind == "YieldExpression":
        return ["yield", n["delegate"], shape(n["argument"]) if n["argument"] else None]
    if kind == "AwaitExpression":
        return ["await", shape(n["argument"])]
    if kind == "JSXElement":
        return ["jsx", n["openingElement"]["name"]["name"]]
    if kind == "Identifier":
        return ["name", n["name"]]
    if kind == "NumericLiteral":
        return ["number", n["raw"]]
    raise ValueError("unmapped expression " + kind)


def cases():
    heads = [
        "async(value)", "async(value) => value", "async(await): R => 0", "async(yield) => 0",
        "async(x, await) => 0", "async(x = await source()) => x", "async(x = await) => x",
        "async(x = fn<T>()) => x", "async(x = async(y) => await y) => x",
        "async(await, x = async(await) => 1) => x", "async(public readonly x: T) => x",
        "async(private ...x: T[]) => 0", "async(private as: T) => 0",
        "flag ? async(x) : y => y", "flag ? async(x): T => x : other",
        "flag ? (async(x): T => x) : other", "async(x)\n=> x", "async\n(x) => x",
        "async x\n=> x", "(async)(x) => x",
        "async await=>0", "async yield=>0", "(await)=>0", "(yield)=>0", "(x=await)=>x", "(x=yield)=>x",
        "(x=await work)=>x", "(x=yield work)=>x", "(x=async q=>await q)=>x",
        "(x, await)=>0", "(x, yield)=>0", "async (x=yield work)=>x",
    ]
    for suffix in ("ts", "tsx"):
        expressions = heads + (["async(await, x = async(v = <C/>) => v) => x"] if suffix == "tsx" else [])
        for prefix, end in [("", ""), ("export {}; ", ""), ("class C { static {", "}}"),
                            ("function outer(){", "}"), ("async function outer(){", "}"),
                            ("function* outer(){", "}"), ("async function* outer(){", "}")]:
            for expression in expressions:
                yield {"name": "heads." + suffix, "source": prefix + "const result = " + expression + ";" + end}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    inputs = list(cases())
    matches = invalid = errors = 0
    for case, expected in zip(inputs, run_compiler(archive, _ORACLE, inputs), strict=True):
        try:
            root = TypeScriptPipeline(case["name"]).parse(case["source"])
        except ValueError as exc:
            if expected is None:
                invalid += 1
                continue
            actual = str(exc)
        else:
            stmt = root["body"][-1]
            if stmt["type"] == "ClassDeclaration":
                stmt = stmt["body"]["body"][0]["body"][0]
            elif stmt["type"] == "FunctionDeclaration":
                stmt = stmt["body"]["body"][0]
            actual = shape(stmt["declarations"][0]["init"])
            if actual == expected:
                matches += 1
                continue
        errors += 1
        print(case["source"], "Orion", actual, "TypeScript", expected)
    print(f"{matches} matching expression trees, {invalid} jointly rejected cases, {errors} differences")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
