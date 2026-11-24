import json
import subprocess
import sys

import pytest

from orionparser.languages.javascript.pipeline import JavaScriptPipeline


def parse(source):
    return JavaScriptPipeline().parse(source)["body"]


def test_generator_cli(tmp_path):
    path = tmp_path / "gen.mjs"
    path.write_text("function* walk(xs){yield* xs; yield\n+1; return yield 2}")
    command = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    decl, = json.loads(subprocess.check_output(command))["body"]
    assert decl["generator"] and decl["id"]["name"] == "walk"
    delegate, bare, plus, returned = decl["body"]["body"]
    assert delegate["expression"] == {"type": "YieldExpression", "argument": {"type": "Identifier", "name": "xs"}, "delegate": True}
    assert bare["expression"]["argument"] is None and plus["expression"]["operator"] == "+"
    assert returned["argument"]["argument"]["raw"] == "2"


def test_generator_scope():
    decl, = parse("function* f(){ (function yield(yield){return yield}); yield { *[yield k](){yield 1} } }")
    nested, outer = decl["body"]["body"]
    assert nested["expression"]["id"]["name"] == "yield"
    assert nested["expression"]["params"] == [{"type": "Identifier", "name": "yield"}]
    method, = outer["expression"]["argument"]["properties"]
    assert method["computed"] and method["key"]["type"] == "YieldExpression"
    assert method["value"]["generator"]


@pytest.mark.parametrize("source", ["function* f(yield){}", "function* f(x=yield 1){}",
                                    "function* f(){let yield}", "function* f(){yield*;}",
                                    "(function* yield(){})", "function* f(){({yield})}"])
def test_invalid_generator(source):
    with pytest.raises(ValueError):
        parse(source)


def test_arrow_parameters_and_body():
    expr = parse("({x=1}, [a], ...rest) => v => ({x, v, rest})")[0]["expression"]
    assert expr["type"] == "ArrowFunctionExpression" and expr["expression"]
    assert [p["type"] for p in expr["params"]] == ["ObjectPattern", "ArrayPattern", "RestElement"]
    assert expr["body"]["params"][0]["name"] == "v" and expr["body"]["body"]["type"] == "ObjectExpression"
    block = parse("(x,) => { return x }")[0]["expression"]
    assert not block["expression"] and block["body"]["body"][0]["type"] == "ReturnStatement"


@pytest.mark.parametrize("source", ["(x,x)=>0", "((x))=>0", "(x.y)=>0", "(...x,)=>0",
                                    "(x + y)=>0", "x\n=>0", "(x=0)=>{'use strict'}"])
def test_invalid_arrow(source):
    with pytest.raises(ValueError):
        parse(source)


def test_unicode_identifier_names():
    declaration, reference, loop = parse(r"let 𐐀́ = 1; obj.\u0069f; for (\u0061sync of xs);")
    assert declaration["declarations"][0]["id"]["name"] == "𐐀́"
    assert reference["expression"]["property"]["name"] == "if"
    assert loop["left"]["name"] == "async"
    assert parse(r"var \u{10400}=0")[0]["declarations"][0]["id"]["name"] == "𐐀"


@pytest.mark.parametrize("source", [r"var \u0030", r"x\u{110000}", r"var \u{200C}", "var 💫",
                                    r"var \u0069f", r"for (x \u006ff xs);"])
def test_invalid_identifier(source):
    with pytest.raises(ValueError):
        parse(source)
