"""Check ordered operator pairs with independent, nested javac AST projections."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from check_java_modules import ROOT, root_kind, type_name
from orionparser.registry import get_pipeline


def shape(node):
    t = node["type"]
    kind = root_kind(node)
    if t in {"BinaryExpression", "AssignmentExpression"}:
        return [kind, shape(node["left"]), shape(node["right"])]
    if t == "UnaryExpression":
        return [kind, shape(node["operand"])]
    if t == "ConditionalExpression":
        return [kind, *[shape(node[key]) for key in ("condition", "then", "else")]]
    if t == "NameExpression":
        parts = node["name"].split(".")
        result = ["IDENTIFIER", parts[0]]
        for part in parts[1:]:
            result = ["MEMBER_SELECT", result, part]
        return result
    if t == "ArrayAccess":
        return [kind, shape(node["array"]), shape(node["index"])]
    if t == "MemberAccess":
        return [kind, shape(node["receiver"]), node["name"]]
    if t == "ParenthesizedExpression":
        return [kind, shape(node["expression"])]
    if t == "Literal":
        return [kind, node["raw"]]
    if t == "CastExpression":
        return [kind, type_name(node["target"]), shape(node["operand"])]
    if t == "InstanceOfExpression":
        return [kind, shape(node["operand"]), type_name(node["test"])]
    if t == "LambdaExpression":
        return [kind, [p["name"] for p in node["parameters"]], shape(node["body"])]
    raise ValueError(f"unmapped expression {t}")


def run(jdk):
    # The reference checks syntax; these independent combinations do not require attribution.
    binary = "* / % + - << >> >>> < > <= >= == != & ^ | && ||".split()
    assign = "= *= /= %= += -= <<= >>= >>>= &= ^= |=".split()
    cases = {}

    def witness(source, *keys):
        cases.setdefault(source, set()).update(tuple(k.rsplit(".", 1)) for k in keys)

    for operators in (binary, assign):
        for left in operators:
            for right in operators:
                witness(f"a {left} b {right} c")
    for op in binary:
        for source in (f"a ? b {op} c : d", f"a ? b : c {op} d", f"a {op} b ? c : d", f"a = b {op} c"):
            witness(source)

    levels = [
        ("ConditionalOrExpression", ["||"]), ("ConditionalAndExpression", ["&&"]),
        ("InclusiveOrExpression", ["|"]), ("ExclusiveOrExpression", ["^"]), ("AndExpression", ["&"]),
        ("EqualityExpression", ["==", "!="]), ("RelationalExpression", ["<", ">", "<=", ">="]),
        ("ShiftExpression", ["<<", ">>", ">>>"]), ("AdditiveExpression", ["+", "-"]),
        ("MultiplicativeExpression", ["*", "/", "%"]),
    ]
    for rule, ops in levels:
        witness("a", rule + ".1")
        for i, op in enumerate(ops, 2):
            witness(f"a {op} b", rule + "." + str(i))
    for i, op in enumerate(assign, 1):
        witness(f"a {op} b", f"AssignmentOperator.{i}", "Assignment.1", "LeftHandSide.1",
                "Expression.2", "AssignmentExpression.2")
    witness("a", "AssignmentExpression.1", "ConditionalExpression.1", "PostfixExpression.2")
    witness("true", "Primary.1", "PrimaryNoNewArray.1", "UnaryExpression.5", "UnaryExpressionNotPlusMinus.1", "PostfixExpression.1")
    for i, op in enumerate(["++", "--", "+", "-"], 1):
        witness(op + "a", f"UnaryExpression.{i}")
    for expr, keys in [
        ("++a", ["PreIncrementExpression.1"]), ("--a", ["PreDecrementExpression.1"]),
        ("~a", ["UnaryExpressionNotPlusMinus.2"]), ("!a", ["UnaryExpressionNotPlusMinus.3"]),
        ("(int)b", ["UnaryExpressionNotPlusMinus.4"]), ("a++", ["PostfixExpression.3", "PostIncrementExpression.1"]),
        ("a--", ["PostfixExpression.4", "PostDecrementExpression.1"]), ("a instanceof String", ["RelationalExpression.6"]),
        ("a ? b : c ? d : a", ["ConditionalExpression.2"]), ("a ? b : x -> x + c", ["ConditionalExpression.3", "Expression.1"]),
        ("xs[a] = b", ["LeftHandSide.3", "ArrayAccess.1", "PrimaryNoNewArray.8"]),
        ("(a).field = b", ["LeftHandSide.2", "FieldAccess.1", "PrimaryNoNewArray.5", "PrimaryNoNewArray.7"]),
        ("(xs)[a]", ["ArrayAccess.2"]), ("a ? b = c : d", []), ("a = b ? c : d", []),
    ]:
        witness(expr, *keys)
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        path = stage / "Matrix.java"
        path.write_text("class Matrix {\n" + "".join(f"Object e{i}() {{ return {expr}; }}\n" for i, expr in enumerate(cases)) + "}\n")
        result = get_pipeline(path).analyze_file(path)
        if not result.success:
            raise ValueError(result.errors)
        subprocess.run([jdk/"bin/javac", "-d", stage, ROOT/"tools/conformance/JavaParseOracle.java"], check=True)
        ref = json.loads(subprocess.check_output([jdk/"bin/java", "-cp", stage, "JavaParseOracle", "--expressions", path], text=True))
        if not ref["accepted"]:
            raise ValueError(ref["errors"])
        for expr, method, expected in zip(cases, result.ast["declarations"][0]["members"], ref["expressions"], strict=True):
            found = [method["name"], shape(method["body"]["statements"][0]["expression"])]
            if expected != found:
                raise ValueError(f"{expr}: javac {expected}, Orion {found}")
    seen = set().union(*cases.values())
    print(f"{len(cases)} complete operator trees matched javac, exercising {len(seen)} indexed alternatives")
    return seen


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--jdk", type=Path, default=ROOT / ".venv/toolchains/jdk-21.0.2")
    run(cli.parse_args().jdk)
