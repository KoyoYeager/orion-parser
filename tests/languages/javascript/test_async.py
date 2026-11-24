import json
import subprocess
import sys

import pytest

from orionparser.languages.javascript.pipeline import JavaScriptModulePipeline, JavaScriptPipeline


def test_async_cli(tmp_path):
    path = tmp_path / "stream.mjs"
    path.write_text("export default async function* stream(xs){for await(const x of xs) yield await x}")
    output = subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"])
    fn = json.loads(output)["body"][0]["declaration"]
    assert fn["type"] == "FunctionDeclaration" and fn["async"] and fn["generator"]
    loop, = fn["body"]["body"]
    assert loop["await"] and loop["right"]["name"] == "xs"
    value = loop["body"]["expression"]
    assert value["type"] == "YieldExpression" and value["argument"]["type"] == "AwaitExpression"


def test_async_methods():
    cls, obj = JavaScriptPipeline().parse("class C{static async *m(){yield await 1}};".rstrip(";") +
                                         " ({async function(){return await f()}})")["body"]
    method, = cls["body"]["body"]
    assert method["static"] and method["value"]["async"] and method["value"]["generator"]
    prop, = obj["expression"]["properties"]
    assert prop["key"]["name"] == "function" and prop["value"]["async"]


def test_async_arrows_and_ordinary_scope():
    src = "const f=async({a}, ...rest)=>await a, g=async x=>{return function(){return await}}"
    first, second = JavaScriptPipeline().parse(src)["body"][0]["declarations"]
    f, g = first["init"], second["init"]
    assert f["async"] and f["expression"] and f["body"]["type"] == "AwaitExpression"
    assert [p["type"] for p in f["params"]] == ["ObjectPattern", "RestElement"]
    nested = g["body"]["body"][0]["argument"]
    assert nested["body"]["body"][0]["argument"]["name"] == "await" and not nested["async"]


def test_async_line_restrictions():
    program = JavaScriptPipeline().parse("async/*\n*/function f(){}; async(1);")
    identifier, ordinary, _, call = program["body"]
    assert identifier["expression"]["name"] == "async" and not ordinary["async"]
    assert call["expression"]["type"] == "CallExpression"
    loop = JavaScriptModulePipeline().parse("for await (async of xs);")["body"][0]
    assert loop["left"]["name"] == "async"


@pytest.mark.parametrize("source", [
    "async function f(a=await x){}", "async function f(){let\nawait 0}",
    "(async function await(){})", "async function* f(yield){}",
    "(async function* yield(){})", "async x=>{let x}", "async(x,x)=>0",
    "async (...x,)=>0", "(async)(x)=>0", "async\n(x)=>0", "f(x)=>0",
    "async(a=(await)=>{})=>{}", "async(x=await)=>x", "class C{async constructor(){}}",
])
def test_invalid_async(source):
    with pytest.raises(ValueError, match="line "):
        JavaScriptPipeline().parse(source)
