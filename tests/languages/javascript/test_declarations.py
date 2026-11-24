import json
import subprocess
import sys

import pytest

from orionparser.languages.javascript.pipeline import JavaScriptPipeline, JavaScriptModulePipeline


@pytest.fixture
def parse():
    return JavaScriptPipeline().parse


@pytest.mark.parametrize("operator", "= += -= *= **= /= %= <<= >>= >>>= &= ^= |= &&= ||= ??=".split())
def test_assignment(parse, operator):
    decl, = parse(f"let first = object.key {operator} x = 1, second;")["body"]
    first, second = decl["declarations"]
    assert decl["kind"] == "let" and second["init"] is None
    assert first["id"]["name"] == "first"
    expr = first["init"]
    assert expr["operator"] == operator and expr["left"]["property"]["name"] == "key"
    assert expr["right"]["operator"] == "=" and expr["right"]["right"]["raw"] == "1"


@pytest.mark.parametrize(("source", "value"), [
    (r"'abc\x20\u0061\u{1F600}'", "abc a😀"), (r'"\t\""', '\t"'),
    ("'abc\\\r\ndef'", "abcdef"), ("'a\u2028b'", "a\u2028b"), (r"'\141\8'", "a8"),
    (r"'\0'", "\0"),
])
def test_string(parse, source, value):
    assert parse(source)["body"][0]["expression"] == {"type": "Literal", "raw": source, "value": value}


@pytest.mark.parametrize("source", [
    "const x;", "let let=2", "const x += 2", "call() = 1", "var a=,b", "var a,",
    r"'\u{110000}'", r"'\xZZ'", r"'\u{}'", "'bare\nline'", "'unfinished",
    "for(x\ny;z);", "for(;;)", "if(x) const y=0;", "throw /*\n*/ 1",
])
def test_errors(parse, source):
    with pytest.raises(ValueError, match=r"line \d+, column \d+"):
        parse(source)


def test_strict_string():
    with pytest.raises(ValueError, match="legacy decimal escape"):
        JavaScriptModulePipeline().parse(r"'\1'")


def test_array_holes(parse):
    expr = parse("[,a,,...b,]")["body"][0]["expression"]
    assert expr["elements"] == [None, {"type": "Identifier", "name": "a"}, None,
                                {"type": "SpreadElement", "argument": {"type": "Identifier", "name": "b"}}]


def test_nested_control_flow_cli(tmp_path):
    path = tmp_path / "example.mjs"
    path.write_text("for (var i=0; i<2; i++) if (i) if (i !== 1) ; else throw new Error('bad')",
                    encoding="utf-8")
    output = subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"])
    loop, = json.loads(output)["body"]
    assert loop["type"] == "ForStatement"
    assert loop["init"]["kind"] == "var" and loop["test"]["operator"] == "<"
    assert loop["update"]["operator"] == "++"
    outer = loop["body"]
    assert outer["alternate"] is None
    inner = outer["consequent"]
    assert inner["test"]["operator"] == "!==" and inner["consequent"]["type"] == "EmptyStatement"
    error = inner["alternate"]["argument"]
    assert error["type"] == "NewExpression" and error["arguments"][0]["value"] == "bad"


def test_new_member_call(parse):
    expr = parse("new C.member(1).next()")["body"][0]["expression"]
    constructor = expr["callee"]["object"]
    assert expr["type"] == "CallExpression" and constructor["type"] == "NewExpression"
    assert constructor["callee"]["property"]["name"] == "member"
    assert constructor["arguments"][0]["raw"] == "1"


@pytest.mark.parametrize("source", ["var eval", "const arguments=0", "++eval", "arguments=1"])
def test_module_restricted_targets(source):
    with pytest.raises(ValueError):
        JavaScriptModulePipeline().parse(source)


@pytest.mark.parametrize("operator", ["==", "!=", "===", "!=="])
def test_equality_precedence(parse, operator):
    expr = parse(f"x = a {operator} b < c")["body"][0]["expression"]
    assert expr["operator"] == "=" and expr["right"]["operator"] == operator
    assert expr["right"]["right"]["operator"] == "<"
