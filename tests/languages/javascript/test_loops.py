from concurrent.futures import ThreadPoolExecutor

import pytest

from orionparser.languages.javascript.pipeline import JavaScriptModulePipeline, JavaScriptPipeline


def first(source):
    return JavaScriptPipeline().parse(source)["body"][0]


def test_in_parameter():
    loop = first("for (f ? a in b : (c in d); e in f; g in h) ;")
    assert loop["init"]["consequent"]["operator"] == loop["init"]["alternate"]["operator"] == "in"
    assert loop["test"]["operator"] == loop["update"]["operator"] == "in"
    loop = first("for (var a = [k in obj], b = f(k in obj);;) ;")
    assert loop["init"]["declarations"][0]["init"]["elements"][0]["operator"] == "in"


def test_iterators():
    loop = first("for (let of of options) for (obj.x in a,b) ;")
    assert loop["type"] == "ForOfStatement" and not loop["await"]
    assert loop["left"]["declarations"][0]["id"]["name"] == "of"
    inner = loop["body"]
    assert inner["type"] == "ForInStatement" and inner["right"]["type"] == "SequenceExpression"
    assert inner["left"]["property"]["name"] == "x"


def test_annex_b_for_initializer():
    source = "for(var x=1 in obj);"
    assert first(source)["left"]["declarations"][0]["init"]["raw"] == "1"
    with pytest.raises(ValueError):
        JavaScriptModulePipeline().parse(source)


def test_destructuring_bindings():
    loop = first("for (const {a:x=1,[k]:[,z],...rest} of arr) ;")
    a, computed, rest = loop["left"]["declarations"][0]["id"]["properties"]
    assert a["value"]["type"] == "AssignmentPattern" and a["value"]["left"]["name"] == "x"
    assert computed["computed"] and computed["value"]["elements"][0] is None
    assert rest["type"] == "RestElement"
    func = first("function f([a],{x=1}, ...[r]) {try{}catch({code}){}}")
    assert [p["type"] for p in func["params"]] == ["ArrayPattern", "ObjectPattern", "RestElement"]
    assert func["body"]["body"][0]["handler"]["param"]["type"] == "ObjectPattern"


def test_labels_switch_and_do_while():
    body = JavaScriptPipeline().parse("a:b:do {switch(n){case 1:continue a; default:break}} while(x) f()")["body"]
    loop = body[0]["body"]["body"]
    assert loop["type"] == "DoWhileStatement" and body[1]["expression"]["type"] == "CallExpression"
    case, default = loop["body"]["body"][0]["cases"]
    assert case["consequent"][0]["label"]["name"] == "a"
    assert default["test"] is None and default["consequent"][0]["label"] is None


@pytest.mark.parametrize("source", [
    "for(x ? a : b in c;;);", "for(x in y;;);", "for(var a,b in obj);",
    "for (let x=1 in obj);", "for(const x=1 of xs);", "for(x of a,b);",
    "for(let of xs);", "for(async of xs);", "for(const x;;);",
    "for(var x in obj) let\n[a]=0", "let [x,x]=[]", "var {x};",
    "var [...x,]=xs", "let {...x,y}=obj", "try{}catch([x,x]){}",
    "break", "x:{continue x}", "while(a){function f(){break}}", "a:a:;",
    "switch(x){default:;default:;}", "do{}while(a) else ;",
])
def test_invalid(source):
    with pytest.raises(ValueError, match=r"line \d+, column \d+"):
        first(source)


def test_reuse_after_failure():
    def run(_):
        with pytest.raises(ValueError):
            first("function f(){\n\n x +")
        with pytest.raises(ValueError, match="line 1, column 1"):
            first("return")
        return first("while(1){break}")["type"]

    with ThreadPoolExecutor(max_workers=3) as executor:
        assert list(executor.map(run, range(9))) == ["WhileStatement"] * 9


def test_assignment_patterns():
    loop = first("for ({x=2,key:[obj.y,,...rest],...target.rest} in source) ;")
    shorthand, nested, rest = loop["left"]["properties"]
    assert loop["left"]["type"] == "ObjectPattern"
    assert shorthand["value"]["type"] == "AssignmentPattern"
    member, hole, spread = nested["value"]["elements"]
    assert member["type"] == "MemberExpression" and hole is None
    assert spread["type"] == rest["type"] == "RestElement"
    assign = first("([x,...[y]] = arr)")["expression"]
    assert assign["left"]["elements"][1]["argument"]["type"] == "ArrayPattern"


@pytest.mark.parametrize("source", [
    "for (const x in obj) if (z) {var x}",
    "for (let {x} of xs) try {} finally {var x}",
    "for(let x=0;;) switch(n){case 1: var x}",
    "({x=2})", "([...x,]=z)", "({x(){}} = y)", "(([x]) = z)",
    "({ ...[x] } = z)", "({ ...x, } = z)", "for ([foo()] in obj);",
])
def test_invalid_pattern_or_scope(source):
    with pytest.raises(ValueError):
        first(source)


def test_independent_var_scope():
    loop = first("for(let x of xs){function f(){var x}}")
    assert loop["body"]["body"][0]["type"] == "FunctionDeclaration"


def test_cli_diagnostics(tmp_path):
    import json
    import subprocess
    import sys

    good = tmp_path / "good.js"
    bad = tmp_path / "bad.js"
    good.write_text("for (const x of xs) ;")
    bad.write_text("for (const x=1 of xs) ;")
    run = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(tmp_path), "--json"],
                         capture_output=True, text=True)
    assert run.returncode == 1 and "line 1, column" in run.stderr
    rejected, accepted = json.loads(run.stdout)
    assert not rejected["success"] and rejected["errors"] and rejected["ast"] is None
    assert accepted["success"] and accepted["ast"]["body"][0]["type"] == "ForOfStatement"
