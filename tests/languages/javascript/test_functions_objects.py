import json
import subprocess
import sys

import pytest

from orionparser.languages.javascript.pipeline import JavaScriptPipeline, JavaScriptModulePipeline


def test_function_object_cli(tmp_path):
    path = tmp_path / "objects.mjs"
    path.write_text("""function factory(a = 0, ...rest) {
        return {a, [a]: function inner(x,) {return x}, m(){ return rest }, ...rest,}
    }""")
    result = subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"])
    declaration, = json.loads(result)["body"]
    assert declaration["type"] == "FunctionDeclaration" and declaration["id"]["name"] == "factory"
    default, rest = declaration["params"]
    assert default["type"] == "AssignmentPattern" and default["right"]["raw"] == "0"
    assert rest == {"type": "RestElement", "argument": {"type": "Identifier", "name": "rest"}}
    shorthand, computed, method, spread = declaration["body"]["body"][0]["argument"]["properties"]
    assert shorthand["shorthand"] and shorthand["key"]["name"] == "a"
    assert computed["computed"] and computed["value"]["id"]["name"] == "inner"
    assert method["method"] and method["value"]["body"]["body"][0]["type"] == "ReturnStatement"
    assert spread["type"] == "SpreadElement"


def test_return_restriction_and_property_name():
    ast = JavaScriptPipeline().parse("function f(){return /*\n*/ {}}; obj.return\n(1)")
    returned, block = ast["body"][0]["body"]["body"]
    assert returned == {"type": "ReturnStatement", "argument": None}
    assert block == {"type": "BlockStatement", "body": []}
    assert ast["body"][-1]["expression"]["callee"]["property"]["name"] == "return"


def test_accessors():
    ast = JavaScriptPipeline().parse("({get [key](){return 1},set 'a'(v){},0: null})")
    getter, setter, data = ast["body"][0]["expression"]["properties"]
    assert getter["kind"] == "get" and getter["computed"]
    assert setter["kind"] == "set" and setter["value"]["params"][0]["name"] == "v"
    assert data["key"] == {"type": "NumericLiteral", "raw": "0"}


@pytest.mark.parametrize("source", [
    "return 1", "function f(){} return", "function(){}", "if(x) function(){};",
    "function f(...x,){}", "function f(x=0,x){}", "function f(a,{){}",
    "({if})", "({0})", "({[x]})", "({__proto__:1,'__proto__':2})",
    "({m(x,x){}})", "({get a(x){}})", "({set a(){}})", "({set a(...x){}})",
    "({foo bar(){}})",
])
def test_bad_function_or_property(source):
    with pytest.raises(ValueError, match=r"line 1, column"):
        JavaScriptPipeline().parse(source)


def test_simple_parameters_script_and_module():
    assert len(JavaScriptPipeline().parse("function f(x,x){}")["body"][0]["params"]) == 2
    with pytest.raises(ValueError, match="duplicate parameter"):
        JavaScriptModulePipeline().parse("function f(x,x){}")


@pytest.mark.parametrize("base", ["~3", "delete o.p", "!1", "-3", "+1", "typeof 1", "void 1"])
def test_test262_unary_base_error(base):
    with pytest.raises(ValueError) as error:
        JavaScriptPipeline().parse(base + " ** 2;")
    assert str(error.value) == f"line 1, column {len(base) + 2}: unexpected '**'"
    expr = JavaScriptPipeline().parse(f"({base}) ** 2;")["body"][0]["expression"]
    assert expr["operator"] == "**" and expr["left"]["type"] == "UnaryExpression"
