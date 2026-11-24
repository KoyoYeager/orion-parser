import pytest

from orionparser.languages.javascript.pipeline import JavaScriptModulePipeline, JavaScriptPipeline


def expressions(source):
    return [statement["expression"] for statement in JavaScriptPipeline().parse(source)["body"]]


@pytest.mark.parametrize("raw", ["0", "1_234", "0xff", "0O77", "0b10", "0n", "0xCA_FEn",
                                  ".5", "1.", "0.12_34", "1e+20", "2.1E-3"])
def test_numeric(raw):
    assert expressions(raw) == [{"type": "BigIntLiteral" if raw.endswith("n") else "NumericLiteral",
                                 "raw": raw}]


@pytest.mark.parametrize("operator", ["!", "~", "+", "-", "typeof", "void", "delete"])
def test_unary(operator):
    expression, = expressions(f"{operator} obj.field")
    assert expression["operator"] == operator
    assert expression["argument"]["object"] == {"type": "Identifier", "name": "obj"}


@pytest.mark.parametrize("source", ["0x", "1_n", "0b2", "1foo", "2e", "-2**3", "x y",
                                     "1++", "++(x+y)", "x +", "f(,x)", "(x,)"])
def test_invalid_expression(source):
    with pytest.raises(ValueError, match=r"line 1, column"):
        expressions(source)


def test_precedence_and_associativity():
    expression, = expressions("1-2-3+4*5%6/7**8**-9")
    assert expression["operator"] == "+"
    assert expression["left"]["left"]["operator"] == "-"
    product = expression["right"]
    assert [product["operator"], product["left"]["operator"], product["left"]["left"]["operator"]] == ["/", "%", "*"]
    power = product["right"]
    assert power["operator"] == power["right"]["operator"] == "**"
    assert power["right"]["right"]["operator"] == "-"


def test_call_and_member_continuations():
    expression, = expressions("this\n.default\n[key]\n(null, true, false,)")
    assert expression["type"] == "CallExpression"
    assert expression["arguments"] == [{"type": "Literal", "value": value} for value in [None, True, False]]
    computed = expression["callee"]
    assert computed["computed"] and computed["property"]["name"] == "key"
    assert computed["object"] == {"type": "MemberExpression", "object": {"type": "ThisExpression"},
                                  "property": {"type": "Identifier", "name": "default"}, "computed": False}


def test_update_line_restriction():
    first, second, third = expressions("x++\ny/*\u2028*/--z")
    assert first["type"] == "UpdateExpression" and first["prefix"] is False
    assert second == {"type": "Identifier", "name": "y"}
    assert third["prefix"] is True and third["operator"] == "--"


def test_parenthesized_sequence():
    call, = expressions("f((x,y,z),w)")
    sequence, last = call["arguments"]
    assert sequence["type"] == "SequenceExpression"
    assert [item["name"] for item in sequence["expressions"]] == ["x", "y", "z"]
    assert last["name"] == "w"


def test_module_context():
    with pytest.raises(ValueError):
        JavaScriptModulePipeline().parse("delete (name)")
    with pytest.raises(ValueError):
        JavaScriptModulePipeline().parse("yield")
    assert expressions("yield")[0]["name"] == "yield"


def test_conditional_and_bitwise_precedence():
    expr, = expressions("x = a || b && c | d ^ e & f == g < h >>> i + j ? k = l : m ? n : o")
    conditional = expr["right"]
    assert conditional["consequent"]["operator"] == "="
    assert conditional["alternate"]["type"] == "ConditionalExpression"
    node = conditional["test"]
    for operator in ["||", "&&", "|", "^", "&", "==", "<", ">>>", "+"]:
        assert node["operator"] == operator
        node = node["right"]
    assert node["name"] == "j"


@pytest.mark.parametrize("source", ["a ?? b || c", "a && b ?? c", "a || b ?? c", "a ?? b && c"])
def test_coalesce_restriction(source):
    with pytest.raises(ValueError):
        expressions(source)


def test_coalesce_parentheses():
    expr, = expressions("(a && b) ?? c ?? (d || e)")
    assert expr["operator"] == expr["left"]["operator"] == "??"
    assert expr["left"]["left"]["operator"] == "&&" and expr["right"]["operator"] == "||"
