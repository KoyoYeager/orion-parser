import pytest

from orionparser.languages.javascript.pipeline import JavaScriptModulePipeline, JavaScriptPipeline


def test_linkage():
    src = """import 'init';
    import primary, * as ns from 'lib';
    import {'foreign-name' as local, other,} from 'pkg';
    export {local, primary as default,};
    export * as 'public-name' from 'extra';
    export {missing as present} from 'upstream';
    export const result = await import('./data.mjs');
    import.meta;
    """
    side, namespace, named, local, star, indirect, decl, meta = JavaScriptModulePipeline().parse(src)["body"]
    assert side["specifiers"] == [] and namespace["specifiers"][1]["type"] == "ImportNamespaceSpecifier"
    assert named["specifiers"][0]["imported"]["value"] == "foreign-name"
    assert local["specifiers"][1]["exported"]["name"] == "default"
    assert star["exported"]["value"] == "public-name" and indirect["source"]["value"] == "upstream"
    assert decl["declaration"]["declarations"][0]["init"]["argument"]["type"] == "ImportExpression"
    assert meta["expression"]["meta"]["name"] == "import"


@pytest.mark.parametrize("src", ["export default function(){}", "export default function* named(){}",
                                 "export default class {}", "export default (function(){});"])
def test_default(src):
    decl = JavaScriptModulePipeline().parse(src)["body"][0]
    assert decl["type"] == "ExportDefaultDeclaration"
    assert decl["declaration"]["type"] in {"FunctionDeclaration", "ClassDeclaration", "FunctionExpression"}


@pytest.mark.parametrize("src", ["export {missing}", "export default 1;export default 2",
                                 "import a,{b as a} from 'lib'", "import * as eval from 'x'",
                                 "if (x) {export const v=1}", "import {3 as a} from 'x'",
                                 "function f(){ await value; }", "import a from 'x';{var a}"])
def test_invalid_module(src):
    with pytest.raises(ValueError):
        JavaScriptModulePipeline().parse(src)


@pytest.mark.parametrize("src", ["export default 1", "import 'lib'", "import.meta"])
def test_script_restrictions(src):
    with pytest.raises(ValueError):
        JavaScriptPipeline().parse(src)


def test_module_for_await():
    loop, = JavaScriptModulePipeline().parse("for await (const x of await xs) ;")["body"]
    assert loop["await"] and loop["right"]["type"] == "AwaitExpression"
    with pytest.raises(ValueError):
        JavaScriptPipeline().parse("for await (x of xs) ;")
