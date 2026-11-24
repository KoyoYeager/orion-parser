import pytest

from orionparser.languages.javascript.pipeline import JavaScriptModulePipeline, JavaScriptPipeline


@pytest.mark.parametrize("source", [
    "{ let x; { var x } }", "{ function* f(){} function f(){} }",
    "switch(n){case 1: let x; default: var x}",
    "async function f(x){const x=0}", "try {} catch({x}) {if(ok){var x}}",
    "try {} catch(x) {function x(){}}", 'label:function f(){}; let f;',
    "while(ok) label:function f(){}", "if(x) async function f(){}",
    "class C {v=()=>arguments}", "class C {static {class D{[arguments](){}}}}",
])
def test_early_error(source):
    with pytest.raises(ValueError, match=r"line \d+, column \d+"):
        JavaScriptPipeline().parse(source)


@pytest.mark.parametrize("source", [
    "{let x; function f(){var x}}", "try{} catch(x) {var x}",
    "class C { f=function(){return arguments}; x={arguments: 1}; }",
    "class C { f=()=>obj.arguments; }", "{function f(){} function f(){}}",
    "if(x) function f(){} else function g(){}",
])
def test_separate_scopes(source):
    assert JavaScriptPipeline().parse(source)["body"]


def test_html_comments():
    script = "x <!-- trailing\n /* preceding */ --> ignored\ny"
    body = JavaScriptPipeline().parse(script)["body"]
    assert [n["expression"]["name"] for n in body] == ["x", "y"]
    with pytest.raises(ValueError):
        JavaScriptModulePipeline().parse("<!-- x\ny")


def test_module_duplicate_location():
    with pytest.raises(ValueError, match=r"line 3, column 1:"):
        JavaScriptModulePipeline().parse("import x from 'm';\n\nconst x=1;")
