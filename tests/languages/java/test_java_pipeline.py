import json
from pathlib import Path
import subprocess
import sys

import pytest


def cli(path, command="parse"):
    return subprocess.run([sys.executable, "-m", "orionparser", command, str(path), "--json"],
                          capture_output=True, text=True)


def test_module_cli(tmp_path):
    path = tmp_path / "module-info.java"
    path.write_text(
        "import static a.B.*; @Marker open module module.example {\n"
        "requires transitive.name; requires transitive static dep;\n"
        "exports open.to to a, b; opens p; uses api.Service; provides api.Service with impl.One, impl.Two; }"
    )
    result = cli(path)
    assert result.returncode == 0, result.stderr
    unit = json.loads(result.stdout)
    assert unit["imports"] == [{"type": "ImportDeclaration", "static": True, "name": "a.B", "onDemand": True}]
    module = unit["module"]
    assert module["name"] == "module.example" and module["open"]
    assert module["annotations"][0]["name"] == "Marker"
    first, second, export, opened, uses, provides = module["directives"]
    assert first["name"] == "transitive.name" and first["modifiers"] == []
    assert second["modifiers"] == ["transitive", "static"]
    assert export["name"] == "open.to" and export["targets"] == ["a", "b"]
    assert opened["targets"] == [] and uses["name"] == "api.Service"
    assert provides["implementations"] == ["impl.One", "impl.Two"]


def test_unicode_source_translation(tmp_path):
    path = tmp_path / "Example.java"
    path.write_bytes(br"// comment\u000a pack\uuuu0061ge p; public class \uD801\uDC00 {}" + b"\r\n")
    result = cli(path)
    assert result.returncode == 0, result.stderr
    unit = json.loads(result.stdout)
    assert unit["package"]["name"] == "p"
    assert unit["declarations"][0]["name"] == "\U00010400"
    tokens = json.loads(cli(path, "tokens").stdout)
    assert tokens[0]["offset"] == path.read_bytes().index(b"pack")


@pytest.mark.parametrize(("source", "position"), [
    ("module m { exports a to ; }", "line 1, column 25"),
    ("module m { requires static static a; }", "line 1, column 28"),
    ("package p; module m {}", "line 1, column 12"),
    ("public class record {}", "line 1, column 14"),
    (r"module m { /* \uZZZZ */ }", "line 1, column 17"),
])
def test_rejects_invalid_unit(tmp_path, source, position):
    path = tmp_path / "Bad.java"
    path.write_text(source)
    result = cli(path)
    assert result.returncode and json.loads(result.stdout) is None
    assert position in result.stderr

def test_class_members_and_expression_tree():
    result = cli(Path(__file__).parent / "fixtures/Totals.java")
    assert result.returncode == 0, result.stderr
    decl, = json.loads(result.stdout)["declarations"]
    field, constructor, sum_method, run = decl["members"]
    assert field["modifiers"] == ["private", "final"]
    assignment = constructor["body"]["statements"][0]["expression"]
    assert assignment["left"] == {"type": "MemberAccess", "receiver": {"type": "ThisExpression"}, "name": "bias"}
    assert sum_method["parameters"][0]["parameterType"]["dimensions"] == 1
    local, loop, returned = sum_method["body"]["statements"]
    assert local["variables"][0]["initializer"]["raw"] == "0"
    assert loop["type"] == "EnhancedForStatement" and loop["iterable"]["name"] == "values"
    branch, = loop["body"]["statements"]
    addition = branch["then"]["expression"]
    assert branch["condition"]["operator"] == ">" and addition["operator"] == "+="
    assert addition["right"]["operator"] == "+" and addition["right"]["left"]["operator"] == "*"
    assert returned["expression"]["name"] == "sum"
    invocation = run["body"]["statements"][0]["expression"]
    assert invocation["receiver"] == {"type": "NewClass", "name": "Totals", "arguments": [{"type": "Literal", "raw": "1"}]}
    assert invocation["name"] == "sumPositive" and invocation["arguments"][0]["name"] == "data"


def test_type_arguments_and_shift_operators():
    result = cli(Path(__file__).parent / "fixtures/GenericBox.java")
    assert result.returncode == 0, result.stderr
    cls = json.loads(result.stdout)["declarations"][0]
    parameter, = cls["typeParameters"]
    assert parameter["name"] == "T" and parameter["bounds"][0] == "Number"
    field = cls["members"][1]["fieldType"]
    map_type, = field["segments"][0]["arguments"]
    inner_list = map_type["segments"][0]["arguments"][1]
    wildcard, = inner_list["segments"][0]["arguments"]
    assert wildcard["boundKind"] == "super" and wildcard["bound"]["name"] == "T"
    copy = cls["members"][5]["body"]["statements"][0]["expression"]
    assert copy["diamond"] and copy["name"] == "GenericBox"
    conditional = cls["members"][-1]["body"]["statements"][0]["expression"]
    assert conditional["condition"]["operator"] == "<"
    assert conditional["condition"]["right"]["operator"] == ">>" and conditional["then"]["operator"] == ">>>"


def test_lambdas_method_references_and_intersection_cast():
    result = cli(Path(__file__).parent / "fixtures/Functional.java")
    assert result.returncode == 0, result.stderr
    members = json.loads(result.stdout)["declarations"][0]["members"]
    fields = {var["name"]: var["initializer"] for m in members if m["type"] == "FieldDeclaration"
              for var in m["variables"]}
    assert [p["name"] for p in fields["choose"]["parameters"]] == ["a", "b"]
    annotated = fields["withVar"]["parameters"][0]
    assert annotated["parameterType"]["name"] == "var" and annotated["modifiers"][0]["name"] == "Deprecated"
    assert fields["varargs"]["parameters"][0]["variadic"]
    assert fields["print"]["body"]["statements"][0]["expression"]["arguments"][0]["name"] == "s"
    assert fields["array"]["qualifier"] == {"type": "Type", "name": "String", "dimensions": 1}
    assert fields["explicit"]["typeArguments"][0]["name"] == "T"
    assert fields["viaSuper"]["qualifier"]["type"] == "SuperExpression"
    cast = fields["cast"]
    assert cast["target"]["type"] == "IntersectionType" and cast["target"]["bounds"][1] == "java.io.Serializable"
    assert cast["operand"]["type"] == "LambdaExpression"
    assert fields["branch"]["else"]["body"]["name"] == "copy"


def test_relations_and_shifts_in_lambda_body(tmp_path):
    path = tmp_path / "Angles.java"
    path.write_text("class A { F f = x -> x < n >> 1 ? x+1 : x; boolean g(){return a < b > c;} }")
    result = cli(path)
    assert result.returncode == 0, result.stderr
    field, method = json.loads(result.stdout)["declarations"][0]["members"]
    body = field["variables"][0]["initializer"]["body"]
    assert body["condition"]["operator"] == "<"
    assert body["condition"]["right"]["operator"] == ">>" and body["then"]["operator"] == "+"
    assert method["body"]["statements"][0]["expression"]["left"]["operator"] == "<"


def test_sealed_records_and_recursive_patterns():
    result = cli(Path(__file__).parent / "fixtures/Shapes.java")
    assert result.returncode == 0, result.stderr
    shape, shapes, more, point, _, queries = json.loads(result.stdout)["declarations"]
    assert shape["permits"] == ["Shapes", "Point"] and shapes["permits"] == ["MoreShapes"]
    assert more["modifiers"] == ["non-sealed"]
    value, samples = point["components"]
    assert value["modifiers"][0]["name"] == "Deprecated" and samples["variadic"]
    compact, count, nested, init = point["members"]
    assert compact["type"] == "CompactConstructorDeclaration" and compact["body"]["statements"][0]["type"] == "IfStatement"
    assert count["name"] == "count" and nested["components"] == [] and init["static"]
    pattern = queries["members"][0]["body"]["statements"][0]["expression"]["left"]["test"]
    nested, count = pattern["components"]
    assert nested["recordType"]["name"] == "Point" and nested["components"][1]["variable"]["parameterType"]["dimensions"] == 1
    assert count["variable"]["name"] == "n"
    local, returned = queries["members"][2]["body"]["statements"]
    assert local["type"] == "RecordDeclaration" and local["modifiers"][0]["name"] == "Deprecated"
    assert returned["expression"]["receiver"]["arguments"][0]["name"] == "record"


def test_guarded_rules_yield_and_colon_groups():
    result = cli(Path(__file__).parent / "fixtures/Dispatch.java")
    assert result.returncode == 0, result.stderr
    _, score, legacy = json.loads(result.stdout)["declarations"][0]["members"]
    switch = score["body"]["statements"][0]["expression"]
    assert switch["type"] == "SwitchExpression"
    first, second, third, last = switch["body"]["entries"]
    assert first["label"]["guard"]["operator"] == "&&"
    assert first["label"]["pattern"]["components"][1]["variable"]["name"] == "y"
    assert second["body"]["statements"][0] == {"type": "YieldStatement", "expression": {"type": "NameExpression", "name": "y"}}
    assert third["label"]["guard"]["expression"]["name"] == "enabled" and last["label"]["includesDefault"]
    assert last["body"]["type"] == "ThrowStatement"
    stmt, returned = legacy["body"]["statements"]
    group, _ = stmt["body"]["entries"]
    assert [l["values"][0]["raw"] for l in group["labels"]] == ["1", "2"]
    assert group["statements"][-1]["type"] == "BreakStatement"
    assert len(returned["expression"]["body"]["entries"][0]["label"]["values"]) == 2


def test_switch_context_of_arrows_calls_and_yield(tmp_path):
    path = tmp_path / "Cases.java"
    path.write_text(
        "class Cases { int f(Object o, boolean ok, int yield) {"
        " yield++; switch(o){default -> { yield=0; }} "
        " return switch(o){case P(x) -> 1; case P(Q()) when (ok) -> 2;"
        " case R r when check(k -> k.test()) -> 3; default -> {yield yield;} }; } }"
    )
    result = cli(path)
    assert result.returncode == 0, result.stderr
    update, statement, returned = json.loads(result.stdout)["declarations"][0]["members"][0]["body"]["statements"]
    assert update["expression"]["operand"]["name"] == "yield"
    assert statement["body"]["entries"][0]["body"]["statements"][0]["expression"]["left"]["name"] == "yield"
    call, nested, guarded, fallback = returned["expression"]["body"]["entries"]
    assert call["label"]["values"][0]["type"] == "MethodInvocation"
    assert nested["label"]["pattern"]["components"][0]["recordType"]["name"] == "Q"
    assert nested["label"]["guard"]["expression"]["name"] == "ok"
    assert guarded["label"]["guard"]["arguments"][0]["type"] == "LambdaExpression"
    assert fallback["body"]["statements"][0]["expression"]["name"] == "yield"


def test_enum_bodies_and_annotation_defaults():
    result = cli(Path(__file__).parent / "fixtures/Palette.java")
    assert result.returncode == 0, result.stderr
    options, palette = json.loads(result.stdout)["declarations"]
    assert options["type"] == "AnnotationInterfaceDeclaration"
    assert options["members"][1]["default"]["values"][0]["raw"] == '"a"'
    assert options["members"][3]["dimensions"] == 1
    red, blue = palette["constants"]
    assert red["annotations"][0]["name"] == "Deprecated" and red["body"][0]["name"] == "code"
    assert blue["arguments"][0]["raw"] == "2" and blue["body"] is None
    literal = palette["members"][-1]["body"]["statements"][0]["expression"]
    assert literal["raw"].startswith('"""\t\n') and literal["value"] == "one \n  twothree A\n"


def test_text_block_line_endings_escapes_and_closing_delimiters(tmp_path):
    path = tmp_path / "TextValues.java"
    source = (Path(__file__).parent / "fixtures/TextValues.java").read_bytes()
    path.write_bytes(source.replace(b"\n", b"\r\n"))
    result = cli(path)
    assert result.returncode == 0, result.stderr
    fields = json.loads(result.stdout)["declarations"][0]["members"]
    values = [f["variables"][0]["initializer"]["value"] for f in fields]
    assert values == ["\b\t\n\f\r\"'\\\xff\n", 'raw "" and """ keep going', "", " \n  indented \n"]


def test_try_resources_and_union_catches():
    result = cli(Path(__file__).parent / "fixtures/Resources.java")
    assert result.returncode == 0, result.stderr
    members = json.loads(result.stdout)["declarations"][0]["members"]
    attempt, = members[2]["body"]["statements"]
    declared, field, name = attempt["resources"]
    assert declared["final"] and declared["variables"][0]["initializer"]["name"] == "src"
    assert field["receiver"]["type"] == "ThisExpression" and name["name"] == "src"
    assert attempt["catches"][0]["parameter"]["types"] == ["IOException", "IllegalStateException"]
    assert attempt["catches"][1]["parameter"]["types"] == ["RuntimeException"]
    assert attempt["finally"]["statements"][0]["expression"]["name"] == "cleanup"


def test_arrays_and_qualified_anonymous_creation():
    result = cli(Path(__file__).parent / "fixtures/Arrays.java")
    assert result.returncode == 0, result.stderr
    members = json.loads(result.stdout)["declarations"][0]["members"]
    rows = members[0]["variables"][0]["initializer"]["values"]
    assert [len(row["values"]) for row in rows] == [1, 0, 2]
    new_array = members[1]["body"]["statements"][0]["expression"]
    assert new_array["dimensions"][0]["size"]["operator"] == "+" and new_array["dimensions"][1]["size"] is None
    local, returned = members[4]["body"]["statements"]
    inner = local["variables"][0]["initializer"]
    assert inner["qualifier"]["name"] == "outer" and inner["constructorTypeArguments"][0]["name"] == "String"
    assert returned["expression"]["members"][0]["name"] == "count"
    assert members[5]["body"]["statements"][0]["expression"]["dimensions"][0]["annotations"][0]["name"] == "Dim"


def test_type_annotations_preserve_positions_and_dimension_order():
    result = cli(Path(__file__).parent / "fixtures/Annotated.java")
    assert result.returncode == 0, result.stderr
    decl = json.loads(result.stdout)["declarations"][2]
    assert decl["typeParameters"][0]["annotations"][0]["name"] == "A"
    field, wildcard, method, variadic = decl["members"][:4]
    segment = field["fieldType"]["segments"][-1]
    assert segment["annotations"][0]["value"]["raw"] == '"segment"'
    assert field["fieldType"]["dimensionAnnotations"][0][0]["value"]["raw"] == '"type"'
    assert field["variables"][0]["dimensionAnnotations"][0][0]["value"]["raw"] == '"variable"'
    argument = wildcard["fieldType"]["segments"][0]["arguments"][0]
    assert argument["annotations"][0]["name"] == "A" and argument["bound"]["annotations"][0]["name"] == "B"
    assert method["dimensions"] == 1 and method["throws"][0]["annotations"][0]["name"] == "B"
    assert variadic["parameters"][0]["varargAnnotations"][0]["name"] == "B"


def test_local_class_interface_enum_and_record():
    result = cli(Path(__file__).parent / "fixtures/LocalTypes.java")
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)["declarations"][0]["members"][0]["body"]["statements"]
    assert [d["type"] for d in body[1:6]] == [
        "ClassDeclaration", "ClassDeclaration", "InterfaceDeclaration", "EnumDeclaration", "RecordDeclaration"
    ]
    assert body[1]["modifiers"][0]["name"] == "Deprecated"
    assert body[2]["extends"] == ["Base"] and body[4]["constants"][1]["name"] == "NO"


def test_java21_identifier_version_and_malformed_numeric_tokens(tmp_path):
    path = tmp_path / "Keys.java"
    path.write_text("class \U00031350 {}")
    assert cli(path).returncode == 0
    path.write_text("class \U0002ebf0 {}")
    assert cli(path).returncode != 0
    path.write_text("class A { double n = 1e+_3; }")
    result = cli(path, "tokens")
    assert result.returncode != 0 and "line 1, column 25" in result.stderr


def test_receivers_and_qualified_invocations():
    result = cli(Path(__file__).parent / "fixtures/Invocation.java")
    assert result.returncode == 0, result.stderr
    members = json.loads(result.stdout)["declarations"][0]["members"]
    child = members[5]["members"]
    constructor, method, nested, own_flag = child
    assert own_flag["body"]["statements"][0]["expression"]["receiver"]["type"] == "SuperExpression"
    assert constructor["receiverParameter"]["qualifier"] == "Invocation"
    assert method["receiverParameter"]["receiverType"]["name"] == "Child"
    call = constructor["body"]["statements"][0]
    assert call["target"] == "super" and call["qualifier"]["name"] == "owner"
    assert call["typeArguments"][0]["name"] == "String"
    assert method["body"]["statements"][-1]["expression"]["receiver"] == {"type": "SuperExpression"}
    qualified = nested["members"][2]["body"]["statements"][0]["expression"]
    assert qualified["receiver"] == {"type": "SuperExpression", "qualifier": "Child"}
    assert members[6]["members"][0]["body"]["statements"][0]["qualifier"]["type"] == "ParenthesizedExpression"


def test_cast_before_switch_and_primary_selection(tmp_path):
    path = tmp_path / "SwitchCast.java"
    path.write_text("class C { byte f(int x){return (byte) switch(x){default->2;};} "
                    "int g(int x){return (switch(x){default->\"ab\";}).length();} }")
    result = cli(path)
    assert result.returncode == 0, result.stderr
    f, g = json.loads(result.stdout)["declarations"][0]["members"]
    assert f["body"]["statements"][0]["expression"]["operand"]["type"] == "SwitchExpression"
    assert g["body"]["statements"][0]["expression"]["receiver"]["expression"]["type"] == "SwitchExpression"


def test_jls_qualified_annotated_method_reference(tmp_path):
    path = tmp_path / "References.java"
    path.write_text("class R { F factory = java.lang.@A String::new; F trim = java.lang.@A String::trim; }")
    result = cli(path)
    assert result.returncode == 0, result.stderr
    fields = json.loads(result.stdout)["declarations"][0]["members"]
    for field, name in zip(fields, ["new", "trim"], strict=True):
        ref = field["variables"][0]["initializer"]
        assert ref["name"] == name and ref["qualifier"]["name"] == "java.lang.String"
        assert ref["qualifier"]["segments"][-1]["annotations"][0]["name"] == "A"


def test_java_numeric_limits(tmp_path):
    path = tmp_path / "Bounds.java"
    path.write_text("class Bounds { long a=-9223372036854775808L; int b=0xffffffff; float c=0x1p-149f; }")
    result = cli(path)
    assert result.returncode == 0, result.stderr
    field = json.loads(result.stdout)["declarations"][0]["members"][0]
    unary = field["variables"][0]["initializer"]
    assert unary["operator"] == "-" and unary["operand"]["raw"] == "9223372036854775808L"
    for bad in ["9223372036854775808L", "-(2147483648)", "0x1p-150f", "0x1.ffffffp127f"]:
        path.write_text("class Bounds { Object x=" + bad + "; }")
        result = cli(path)
        assert result.returncode and json.loads(result.stdout) is None
