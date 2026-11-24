import json
import subprocess
import sys

import pytest

from orionparser.languages.typescript.options import SyntaxOptions
from orionparser.registry import get_pipeline


def parse_cli(path, config):
    return subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json",
                           "--tsconfig", str(config)], capture_output=True, text=True)


@pytest.mark.parametrize(("filename", "options", "source", "expected"), [
    ("call.ts", {"module": "esnext"}, 'import<T>("p");', [(1326, 0, 14)]),
    ("call.ts", {"module": "es2015"}, 'import<T>("p");', [(1323, 0, 14)]),
    ("call.cts", {"module": "commonjs", "verbatimModuleSyntax": True}, 'import("p");', [(1286, 0, 11)]),
    ("call.ts", {"module": "commonjs"}, 'import("p", /*𐐀*/ o,);', [(1009, 19, 1), (1324, 18, 1)]),
    ("call.ts", {"module": "preserve"}, 'import.defer(...xs);', [(1325, 13, 5)]),
])
def test_import_grammar_tsconfig_cli(tmp_path, filename, options, source, expected):
    path, config = tmp_path / filename, tmp_path / "tsconfig.json"
    path.write_text(source)
    config.write_text(json.dumps({"compilerOptions": options}))
    result = parse_cli(path, config)
    assert result.returncode == 0, result.stderr
    call = json.loads(result.stdout)["body"][0]["expression"]
    assert call["type"] == "ImportExpression"
    assert [(d["code"], d["offset"], d["length"]) for d in call["diagnostics"]] == expected


def test_jsonc_inheritance_and_strict_override(tmp_path):
    base = tmp_path / "base.json"
    base.write_text('{"compilerOptions": {"strict": true, "baseUrl": "https://host/a,b",},}')
    config = tmp_path / "tsconfig.json"
    config.write_text('{"extends": "./base", /* strict inherited */ "compilerOptions":{"moduleDetection":"legacy"}}')
    src = tmp_path / "script.ts"
    src.write_text("let eval = 1;")
    diagnosed = parse_cli(src, config)
    assert diagnosed.returncode == 0, diagnosed.stderr
    declaration = json.loads(diagnosed.stdout)["body"][0]["declarations"][0]
    diagnostic, = declaration["diagnostics"]
    assert declaration["id"]["name"] == "eval" and (diagnostic["code"], diagnostic["offset"]) == (1100, 4)
    config.write_text('{"extends":["./base"],"compilerOptions":{"alwaysStrict":false}}')
    accepted = parse_cli(src, tmp_path)
    assert accepted.returncode == 0
    program = json.loads(accepted.stdout)
    assert program["sourceType"] == "script" and "diagnostics" not in program["body"][0]["declarations"][0]


@pytest.mark.parametrize(("mode", "jsx", "expected"), [
    ("auto", "preserve", "script"), ("auto", "react-jsx", "module"),
    ("auto", "react-jsxdev", "module"), ("legacy", "react-jsx", "script"),
    ("force", "preserve", "module"),
])
def test_jsx_module_detection(tmp_path, mode, jsx, expected):
    path = tmp_path / "view.tsx"
    path.write_text("<button/>")
    options = SyntaxOptions(module_detection=mode, jsx=jsx)
    result = get_pipeline(path, typescript_options=options).analyze_file(path)
    assert result.success and result.ast["sourceType"] == expected


def test_node_package_boundary(tmp_path):
    path = tmp_path / "src" / "x.ts"
    path.parent.mkdir()
    path.write_text("const x = 1")
    (tmp_path / "package.json").write_text('{"type":"module"}')
    config = tmp_path / "tsconfig.json"
    config.write_text('{"compilerOptions":{"module":"nodenext", "moduleDetection":"auto"}}')
    assert json.loads(parse_cli(path, config).stdout)["sourceType"] == "module"
    (path.parent / "package.json").write_text('{"type":"commonjs"}')
    assert json.loads(parse_cli(path, config).stdout)["sourceType"] == "script"


def test_declarations_and_module_file_restrictions(tmp_path):
    opts = SyntaxOptions(module_detection="force")
    result = get_pipeline(tmp_path / "pkg.d.mts", typescript_options=opts).parse("declare const v:T;")
    assert result["sourceType"] == "script" and result["declarationFile"]
    for ext in (".cts", ".mts"):
        parser = get_pipeline(tmp_path / ("pkg" + ext))
        arrow = parser.parse("<T>(x:T)=>x")["body"][0]["expression"]
        assert arrow["type"] == "ArrowFunctionExpression" and arrow["diagnostics"][0]["code"] == 7060
        assert arrow["diagnostics"][0]["offset"] == 1
        assert "diagnostics" not in parser.parse("<T,>(x:T)=>x")["body"][0]["expression"]
        assertion = parser.parse("<T>x")["body"][0]["expression"]
        assert assertion["type"] == "TSTypeAssertion" and assertion["diagnostics"][0]["code"] == 7059
        assert assertion["diagnostics"][0]["offset"] == 0


def test_cycle_identifies_project(tmp_path):
    cfg = tmp_path / "tsconfig.json"
    cfg.write_text('{"extends":"./tsconfig"}')
    with pytest.raises(ValueError, match="Cycle"):
        SyntaxOptions.from_project(cfg)


@pytest.mark.parametrize(("source", "goal"), [
    ("namespace N { export type T=number } import A=N;", "script"),
    ("import A=require('pkg');", "module"),
    ("export as namespace API;", "script"),
    ("function f(){return import.meta}", "module"),
    ("await x; for await(const item of xs){}", "script"),
    ("class C { f(value: public){} }", "script"),
])
def test_external_module_indicators(tmp_path, source, goal):
    tree = get_pipeline(tmp_path / "file.ts").parse(source)
    assert tree["sourceType"] == goal


@pytest.mark.parametrize(("target", "diagnose"), [("es5", False), ("es2015", False), ("es2016", True), ("esnext", True)])
def test_strict_directive_parameter_target(tmp_path, target, diagnose):
    cfg = tmp_path / "tsconfig.json"
    cfg.write_text(json.dumps({"compilerOptions": {"target": target}}))
    src = tmp_path / "args.ts"
    src.write_text('function f(x=1){"use strict";return x}')
    outcome = parse_cli(src, cfg)
    assert outcome.returncode == 0, outcome.stderr
    function = json.loads(outcome.stdout)["body"][0]
    parameter = function["params"][0]
    directive = function["body"]["body"][0]
    assert parameter["type"] == "AssignmentPattern" and parameter["left"]["name"] == "x"
    assert directive["expression"]["value"] == "use strict"
    for node, expected in [(parameter, (1346, 11)), (directive, (1347, 16))]:
        assert [(d["code"], d["offset"]) for d in node.get("diagnostics", [])] == ([expected] if diagnose else [])
    if diagnose:
        param_link, = parameter["diagnostics"][0]["relatedInformation"]
        directive_link, = directive["diagnostics"][0]["relatedInformation"]
        assert (param_link["code"], param_link["offset"]) == (1349, 16)
        assert (directive_link["code"], directive_link["offset"]) == (1348, 11)


def test_parameter_list_trailing_comma_cli(tmp_path):
    path = tmp_path / "params.ts"
    source = "function f(x, ...xs:T[], /*𐐀*/ ){} declare function g(...xs:T[],):void; interface I{[k:string,]:T}"
    path.write_text(source)
    cfg = tmp_path / "tsconfig.json"
    cfg.write_text("{}")
    result = parse_cli(path, cfg)
    assert result.returncode == 0, result.stderr
    fn, ambient, interface = json.loads(result.stdout)["body"]
    index, = interface["body"]["body"]
    assert all(node["parameterListTrailingComma"] for node in (fn, ambient, index))
    assert "diagnostics" not in ambient
    for owner, code, offset in ((fn, 1013, source.index("[],") + 2), (index, 1025, source.rindex(","))):
        diagnostic, = owner["diagnostics"]
        assert (diagnostic["code"], diagnostic["offset"], diagnostic["length"]) == (code, offset, 1)

    for source, expected in (
        (r"function f(@d ...xs:T[],x:T){}", [(1014, "...")]),
        (r"function f(a?:T,\u0062:T){}", [(1016, r"\u0062")]),
        ("function f(a?:T=1){}", [(1015, "a")]),
        ("function f(... /*gap*/ {x,y}:T=v,){}", [(1048, "{x,y}"), (1013, ",)")]),
        ("declare function f(...x?:T[],):void;", [(1047, "?")]),
    ):
        function = get_pipeline(path).parse(source)["body"][0]
        nodes = [function, *function["params"]]
        spans = sorted((d["code"], d["offset"], d["length"]) for n in nodes for d in n.get("diagnostics", []))
        assert spans == sorted((code, source.index(text), 1 if text == ",)" else len(text)) for code, text in expected)


def test_index_signature_grammar_spans(tmp_path):
    parser = get_pipeline(tmp_path / "index.ts")
    for source, expected in (
        ("interface I{[firstKey:string,b:number]:T}", [(1096, "firstKey")]),
        ("declare interface I{readonly []:Box<T> /*gap*/ ;}", [(1096, "readonly []:Box<T> /*gap*/ ;")]),
        ("class C{static readonly []:T\n f(){}}", [(1096, "static readonly []:T")]),
        ("interface I{[...xs:string[],]:T}", [(1017, "..."), (1025, ",")]),
        ("type I={[public name:string]:T}", [(1018, "name")]),
        ("type I={[key?:string]:T}", [(1019, "?")]),
        ("type I={[key:string=1]:T}", [(1020, "key")]),
        ("interface I{[𐐀,]:T}", [(1022, "𐐀"), (1025, ",")]),
        ("class C{static [k:(string|number)] /*gap*/ ;}", [(1021, "static [k:(string|number)] /*gap*/ ;")]),
    ):
        root = parser.parse(source)
        pending, spans = [root], []
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                spans.extend((d["code"], d["offset"], d["length"]) for d in item.get("diagnostics", []))
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        assert sorted(spans) == sorted((code, source.index(text), len(text))
                                       for code, text in expected)


def test_strict_directive_arrow_parameter_nodes(tmp_path):
    path = tmp_path / "parameters.ts"
    source = 'const fn=(/*𐐀*/[x]:T, y=1, ...z:R[])=>{"first"; "use strict"; "use strict"}'
    path.write_text(source)
    arrow = get_pipeline(path).parse(source)["body"][0]["declarations"][0]["init"]
    assert arrow["type"] == "ArrowFunctionExpression"
    assert [p["type"] for p in arrow["params"]] == ["ArrayPattern", "AssignmentPattern", "RestElement"]
    for param, spelling in zip(arrow["params"], ["[x]", "y=1", "...z"], strict=True):
        diagnostic, = param["diagnostics"]
        assert (diagnostic["code"], diagnostic["offset"]) == (1346, source.index(spelling))
        link, = diagnostic["relatedInformation"]
        assert (link["code"], link["offset"]) == (1349, source.index('"use strict"'))
    before, directive, after = arrow["body"]["body"]
    assert "diagnostics" not in before and "diagnostics" not in after
    diagnostic, = directive["diagnostics"]
    assert (diagnostic["code"], diagnostic["offset"]) == (1347, source.index('"use strict"'))
    assert [(d["code"], d["offset"]) for d in diagnostic["relatedInformation"]] == [
        (1348, source.index("[x]")), (6204, source.index("y=1")), (6204, source.index("...z"))]


def test_strict_name_diagnostic_owners(tmp_path):
    path = tmp_path / "scopes.ts"
    source = 'export {}; class C{ f({p:eval}) {arguments++;} } function eval(arguments){}'
    path.write_text(source)
    tree = get_pipeline(path).parse(source)
    assert "_strict" not in json.dumps(tree)
    _, cls, function = tree["body"]
    method = cls["body"]["body"][0]["value"]
    prop = method["params"][0]["properties"][0]
    update = method["body"]["body"][0]["expression"]
    assert prop["value"]["name"] == "eval"
    assert update["argument"]["name"] == "arguments" and update["operator"] == "++"
    for owner, code, offset in [(prop, 1210, source.index("eval")), (update, 1210, source.index("arguments")),
                                (function, 1215, source.rindex("eval")),
                                (function["params"][0], 1215, source.rindex("arguments"))]:
        diagnostic, = owner["diagnostics"]
        assert (diagnostic["code"], diagnostic["offset"]) == (code, offset)


def test_class_initializer_arguments_tree(tmp_path):
    path = tmp_path / "field.ts"
    function, = get_pipeline(path).parse(
        "function f(){class C{x=arguments; static {const n=()=>arguments;}}}")["body"]
    cls, = function["body"]["body"]
    field, block = cls["body"]["body"]
    assert field["value"] == {"type": "Identifier", "name": "arguments"}
    arrow = block["body"][0]["declarations"][0]["init"]
    assert arrow["type"] == "ArrowFunctionExpression" and arrow["body"] == field["value"]


def test_optional_pattern_and_catch_initializer_cli(tmp_path):
    source = 'function f({x}?:T){"use strict"; try{} catch ([e] = make()) {} }'
    path = tmp_path / "parameters.ts"
    path.write_text(source)
    config = tmp_path / "tsconfig.json"
    config.write_text('{"compilerOptions":{"target":"es2016"}}')
    outcome = parse_cli(path, config)
    assert outcome.returncode == 0, outcome.stderr
    fn, = json.loads(outcome.stdout)["body"]
    parameter, = fn["params"]
    assert parameter["type"] == "ObjectPattern" and parameter["optional"]
    assert {(d["code"], d["offset"]) for d in parameter["diagnostics"]} == {
        (2463, source.index("{x}")), (1346, source.index("{x}"))}
    directive, stmt = fn["body"]["body"]
    assert directive["diagnostics"][0]["code"] == 1347
    handler = stmt["handler"]
    assert handler["param"]["elements"][0]["name"] == "e"
    assert handler["initializer"]["callee"]["name"] == "make"
    diagnostic, = handler["diagnostics"]
    assert (diagnostic["code"], diagnostic["offset"]) == (1197, source.index("make"))


@pytest.mark.parametrize(("name", "source"), [
    ("native.ts", "const 𐐀 = 1;"),
    ("escaped.ts", r"const \u{10400} = 1;"),
    ("generic.ts", "f<𐐀>(x);"),
    ("private.ts", "class C { #𐐀; }"),
    ("component.tsx", "<𐐀 />;"),
    ("continuation.ts", "const a𐐀 = 0;"),
])
def test_identifier_target_ranges(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    for target, accepted in [("es2015", True), ("es5", False), ("esnext", True)]:
        result = get_pipeline(path, typescript_options=SyntaxOptions(target=target)).analyze_file(path)
        assert result.success is accepted, (target, result.errors)


def test_es5_identifier_cli(tmp_path):
    path = tmp_path / "names.ts"
    config = tmp_path / "tsconfig.json"
    config.write_text('{"compilerOptions":{"target":"es5"}}')
    path.write_text("const café = 1;", encoding="utf-8")
    result = parse_cli(path, config)
    assert json.loads(result.stdout)["body"][0]["declarations"][0]["id"]["name"] == "café"
    path.write_text(r"const a\u{10400} = 1;", encoding="utf-8")
    rejected = parse_cli(path, config)
    assert rejected.returncode and "column 8:" in rejected.stderr


def test_invalid_identifier_module_replay_cli(tmp_path):
    path = tmp_path / "unicode.ts"
    config = tmp_path / "tsconfig.json"
    config.write_text('{"compilerOptions":{"target":"es5"}}')
    for source, code, column in [("await; ~𐐀 ** b; export {};", 1109, 6),
                                 ("await; ~𐐀 ** b;", 1127, 9), ("await; � export {};", 1490, 1)]:
        path.write_text(source, encoding="utf-8")
        result = parse_cli(path, config)
        assert result.returncode and f"TS{code}" in result.stderr and f"column {column}:" in result.stderr
    path.write_text('await; "𐐀";', encoding="utf-8")
    tree = json.loads(parse_cli(path, config).stdout)
    assert tree["sourceType"] == "script" and tree["body"][1]["expression"]["value"] == "𐐀"


def test_regexp_target_diagnostic_spans_cli(tmp_path):
    path = tmp_path / "patterns.ts"
    path.write_text("/*𐐀*/ /(?<n>a)(?s:b)/dy;", encoding="utf-8")
    config = tmp_path / "tsconfig.json"
    for target, expected in [
        ("es5", [(1501, 21, 1), (1501, 22, 1), (1503, 9, 3), (1501, 16, 1)]),
        ("es2018", [(1501, 21, 1)]), ("es2022", []),
    ]:
        config.write_text(json.dumps({"compilerOptions": {"target": target}}))
        regex = json.loads(parse_cli(path, config).stdout)["body"][0]["expression"]
        assert regex["alternatives"][0][0]["name"] == "n"
        assert regex["alternatives"][0][1]["modifiers"]["enable"] == "s"
        assert [(d["code"], d["offset"], d["length"]) for d in regex.get("diagnostics", [])] == expected


def test_project_unicode_trivia_and_target_cli(tmp_path):
    base = tmp_path / "base.json"
    base.write_text('{// preceding target\u2028\u200b"compilerOptions": {"target":"\\x65s5",},}', encoding="utf-8")
    config = tmp_path / "tsconfig.json"
    config.write_text('{"extends":"./base", /* gap */\u2029}', encoding="utf-8")
    path = tmp_path / "names.ts"
    path.write_text("const 𐐀 = 1;", encoding="utf-8")
    assert SyntaxOptions.from_project(config).target == "es5"
    assert parse_cli(path, config).returncode != 0
    base.write_text('{// preceding target\u2029"compilerOptions": {"target":"es2015"}}', encoding="utf-8")
    accepted = parse_cli(path, config)
    assert json.loads(accepted.stdout)["body"][0]["declarations"][0]["id"]["name"] == "𐐀"


def test_null_project_option_clears_inherited_setting(tmp_path):
    parent = tmp_path / "base.json"
    parent.write_text('{"compilerOptions":{"target":"es2015","alwaysStrict":false}}')
    config = tmp_path / "tsconfig.json"
    config.write_text('{"extends":"./base","compilerOptions":{"target":null,"alwaysStrict":null,"strict":true}}')
    options = SyntaxOptions.from_project(config)
    assert options.target == "es5" and options.always_strict
    for local in ("null", '["ignored"]'):
        config.write_text('{"extends":"./base","compilerOptions":' + local + "}")
        options = SyntaxOptions.from_project(config)
        assert options.target == "es2015" and not options.always_strict


def test_relative_extends_resolves_file_and_normalizes_slashes(tmp_path):
    settings = tmp_path / "settings"
    settings.mkdir()
    (settings / "tsconfig.json").write_text('{"compilerOptions":{"target":"es2022"}}')
    project = tmp_path / "tsconfig.json"
    project.write_text('{"extends":"./settings"}')
    with pytest.raises(ValueError, match="resolve inherited configuration"):
        SyntaxOptions.from_project(project)
    (settings / "parent.json").write_text('{"compilerOptions":{"target":"es2018"}}')
    project.write_text(json.dumps({"extends": r".\settings\parent"}))
    assert SyntaxOptions.from_project(project).target == "es2018"


def test_exported_project_selects_cli_identifier_target(tmp_path):
    package = tmp_path / "node_modules/pkg"
    (package / "mapped").mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"exports": {"./*": {
        "types@>=6": "./base.json", "types@>=5.9 <6": "./mapped/*.json", "default": "./base.json",
    }}}))
    (package / "mapped/base.json").write_text('{"compilerOptions":{"target":"es2015"}}')
    (package / "base.json").write_text('{"compilerOptions":{"target":"es5"}}')
    project = tmp_path / "tsconfig.json"
    project.write_text('{"extends":"pkg/base"}')
    source = tmp_path / "names.ts"
    source.write_text("const 𐐀 = 1;", encoding="utf-8")
    result = parse_cli(source, project)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["body"][0]["declarations"][0]["id"]["name"] == "𐐀"


def test_project_self_reference_precedes_installed_config(tmp_path):
    dep = tmp_path / "node_modules/p"
    dep.mkdir(parents=True)
    (dep / "base.json").write_text('{"compilerOptions":{"target":"es5"}}')
    (tmp_path / "package.json").write_text('{// local scope\n"name":"p","exports":{"./base":"./modern.json"},"imports":{"#modern":"p/base"},}')
    (tmp_path / "modern.json").write_text('{"compilerOptions":{"target":"es2015"}}')
    project = tmp_path / "src"
    project.mkdir()
    config = project / "tsconfig.json"
    config.write_text('{"extends":"#modern"}')
    src = project / "names.ts"
    src.write_text("const 𐐀 = 1;", encoding="utf-8")
    result = parse_cli(src, config)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["body"][0]["declarations"][0]["id"]["name"] == "𐐀"
    (project / "package.json").write_text('{"name":"inner"}')
    with pytest.raises(ValueError, match="Cannot resolve"):
        SyntaxOptions.from_project(config)
    config.write_text('{"extends":"p/base"}')
    assert SyntaxOptions.from_project(config).target == "es5"


def test_types_versions_config_controls_identifier_syntax(tmp_path):
    package = tmp_path / "node_modules/pkg"
    (package / "v5").mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"typesVersions": {
        ">=6": {"*": ["legacy"]}, "5.9": {"*": ["missing/*", "v5/*"]},
    }}))
    (package / "v5/strict.json").write_text('{"compilerOptions":{"target":"es2015"}}')
    (package / "strict.json").write_text('{"compilerOptions":{"target":"es5"}}')
    project = tmp_path / "tsconfig.json"
    project.write_text('{"extends":"pkg/strict"}')
    source = tmp_path / "names.ts"
    source.write_text("const 𐐀 = 1;", encoding="utf-8")
    parsed = parse_cli(source, project)
    assert parsed.returncode == 0, parsed.stderr
    assert json.loads(parsed.stdout)["body"][0]["declarations"][0]["id"]["name"] == "𐐀"
    (package / "v5/strict.json").unlink()
    with pytest.raises(ValueError, match="Cannot resolve"):
        SyntaxOptions.from_project(project)


def test_declaration_suffix_case_and_module_resolution(tmp_path):
    (tmp_path / "package.json").write_text('{"type":"module"}')
    options = SyntaxOptions.from_compiler_options({"module": "nodenext", "moduleDetection": "auto"})
    for filename, declaration, mode in [
        ("x.d.ts", True, "script"), ("x.D.ts", False, "module"), ("x.d.TS", False, "script"),
        ("x.d.css.ts", True, "script"), ("x.D.css.ts", False, "module"),
        ("x.mts", False, "module"), ("x.MTS", False, "script"),
    ]:
        path = tmp_path / filename
        path.write_text("await(x);")
        tree = get_pipeline(path, typescript_options=options).parse(path.read_text())
        assert (tree["declarationFile"], tree["sourceType"]) == (declaration, mode)
        assert tree["body"][0]["expression"]["type"] == ("AwaitExpression" if mode == "module" else "CallExpression")
    nested = get_pipeline(tmp_path / r"pkg.d.types\ordinary.ts", typescript_options=options)
    assert not nested.parse("type T=number;")["declarationFile"]
    config = tmp_path / "tsconfig.json"
    config.write_text("{}")
    for filename, accepted in (("x.d.ts", True), ("x.D.ts", False)):
        path = tmp_path / filename
        path.write_text("export {}; await;")
        result = parse_cli(path, config)
        if accepted:
            tree = json.loads(result.stdout)
            assert tree["declarationFile"] and tree["body"][-1]["expression"]["name"] == "await"
        else:
            assert result.returncode and "TS1109" in result.stderr and "column 17:" in result.stderr
    path = tmp_path / "node_modules" / "pkg" / "file.ts"
    path.parent.mkdir(parents=True)
    path.write_text("await(x);")
    config.write_text('{"compilerOptions":{"module":"nodenext","moduleResolution":"nodenext","moduleDetection":"auto"}}')
    result = parse_cli(path, config)
    assert result.returncode == 0 and json.loads(result.stdout)["sourceType"] == "module"
    (path.parent / "package.json").write_text('{"type":"commonjs"}')
    result = parse_cli(path, config)
    assert result.returncode == 0 and json.loads(result.stdout)["sourceType"] == "script"
