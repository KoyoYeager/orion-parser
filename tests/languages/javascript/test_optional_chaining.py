import pytest

from orionparser.languages.javascript.pipeline import JavaScriptPipeline


def expression(source):
    return JavaScriptPipeline().parse(source)["body"][0]["expression"]


def test_optional_segments():
    node = expression("root?.read(...args)?.[key].value")
    assert node["type"] == "ChainExpression"
    field = node["expression"]
    assert not field["optional"] and field["property"]["name"] == "value"
    computed = field["object"]
    assert computed["optional"] and computed["computed"] and computed["property"]["name"] == "key"
    call = computed["object"]
    assert not call["optional"] and call["arguments"][0]["type"] == "SpreadElement"
    assert call["callee"]["optional"] and call["callee"]["property"]["name"] == "read"


def test_group_and_numeric_lookahead():
    assert expression("(root?.a).b = v")["left"]["object"]["type"] == "ChainExpression"
    assert expression("a?.3:0")["consequent"]["raw"] == ".3"
    assert expression("a?.()")["expression"]["optional"]


@pytest.mark.parametrize("source", ["a?.b = c", "a?.[k]++", "new a?.b()", "a?.b\n`x`",
                                    "a?.`x`", "super?.x", "class C{#x;m(o){delete o?.#x}}"])
def test_invalid(source):
    with pytest.raises(ValueError):
        JavaScriptPipeline().parse(source)
