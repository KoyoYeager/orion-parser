import json
from pathlib import Path
import subprocess
import sys

import pytest


FIXTURES = Path(__file__).with_name("fixtures")


def cli(path, *args):
    return subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json", *args],
                          capture_output=True, text=True)


def parsed(path, *options):
    result = cli(path, *options)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_module_cli():
    unit = parsed(FIXTURES / "Scale.cppm", "-DSCALE_FACTOR=5")
    assert unit["globalModuleFragment"] == {"type": "GlobalModuleFragment", "declarations": []}
    assert unit["module"]["exported"] and unit["module"]["name"] == "sample.scale"
    namespace, = unit["declarations"][0]["declarations"]
    assert [p["name"] for p in namespace["path"]] == ["sample", "math"]
    enum, alias, function = namespace["declarations"]
    assert enum["scoped"] and enum["enumerators"][1]["name"] == "add"
    assert alias["target"]["specifiers"] == ["unsigned", "long"]
    assert function["noexcept"] and function["parameters"][1]["parameterType"]["specifiers"][0]["name"] == "Mode"
    expr = function["body"]["statements"][0]["expression"]
    assert expr["test"]["right"]["name"] == "Mode::add" and expr["then"]["operator"] == "+"
    assert expr["then"]["left"]["operator"] == "*" and expr["then"]["left"]["right"]["raw"] == "5"
    assert unit["privateModuleFragment"]["declarations"][0]["initializer"]["raw"] == "0b10'01"


def test_template_arguments_and_function_body(tmp_path):
    path = FIXTURES / "Fold.cpp"
    unit = parsed(path)
    preprocessed = tmp_path / "Fold.ii"
    preprocessed.write_bytes(subprocess.check_output(["g++", "-E", "-P", "-std=c++20", str(path)]))
    assert parsed(preprocessed) == unit
    template, twice, _, total, run = unit["declarations"][0]["declarations"]
    assert [p["type"] for p in template["parameters"]] == ["TypeTemplateParameter", "NonTypeTemplateParameter"]
    items, first = template["declaration"]["members"]
    assert items["dimensions"][0]["name"] == "N" and first["qualifiers"] == ["const"]
    assert twice["declaration"]["returnType"]["specifiers"][-1]["name"] == "T"
    loop = total["body"]["statements"][1]
    increment = loop["body"]["statements"][0]["then"]["expression"]
    assert increment["operator"] == "+=" and increment["right"]["callee"]["arguments"][0]["specifiers"] == ["int"]
    local = run["body"]["statements"][0]
    assert local["variableType"]["specifiers"][0]["arguments"][1]["raw"] == "3"
    assert local["initializer"]["elements"][0]["elements"][1]["operator"] == "-"
    assert unit["declarations"][1]["test"]["operator"] == "=="


def test_partition_header_import_and_contextual_identifiers(tmp_path):
    path = tmp_path / "part.ii"
    path.write_text("export module app:core;\nexport import :support;\nimport <vector>;\n"
                    "int module = 1; int import = module;\n")
    unit = parsed(path)
    assert unit["module"]["partition"] == "core"
    first, header, module, var = unit["declarations"]
    assert first["declarations"][0] == {"type": "ImportDeclaration", "kind": "partition", "target": "support"}
    assert header["kind"] == "header" and header["target"] == "<vector>"
    assert module["name"] == "module" and var["initializer"]["name"] == "module"


def test_cpp_header_search_and_source_location(tmp_path):
    include = tmp_path / "include"
    include.mkdir()
    header = include / "factor.hpp"
    header.write_text("#define SCALE(x) (VALUE * (x))\n")
    path = tmp_path / "Example.C"
    path.write_text("#include <factor.hpp>\nconstexpr int value = SCALE(3);\n")
    assert parsed(path, "-I", str(include), "-DVALUE=7")["declarations"][0]["initializer"]["expression"]["left"]["raw"] == "7"
    header.write_text("int ok;\nint bad = ;\n")
    result = cli(path, "-I", str(include))
    assert result.returncode and json.loads(result.stdout) is None and f"{header}:2:11" in result.stderr


@pytest.mark.parametrize("source,line", [
    ("module;\nint a;", 2),
    ("int x;\nexport module m;", 2),
    ("export module m:part;\nmodule :private;", 2),
    ("using T=int;\nT f(T n){return n + ;}", 2),
    ("int f(){\n/* missing", 2),
])
def test_positioned_cpp_rejection(tmp_path, source, line):
    path = tmp_path / "bad.ii"
    path.write_text(source)
    result = cli(path)
    assert result.returncode and json.loads(result.stdout) is None and f"line {line}, column " in result.stderr


def test_cpp_type_name_scopes(tmp_path):
    path = tmp_path / "scope.ii"
    path.write_text(
        "namespace n::inline v {using T=int;} using T=n::T;\n"
        "int f(int x){for(int T=0;T<x;++T) T*x; T *after;\n"
        " {int T=2; T*x;} return x;}\n"
        "int g(int T,int n){ T*n;return T;}"
    )
    tree = parsed(path)
    f, g = tree["declarations"][-2:]
    loop, after, inner, _ = f["body"]["statements"]
    assert loop["body"]["expression"]["operator"] == "*"
    assert after["variableType"]["specifiers"] == [{"type": "TypeName", "name": "T"}]
    assert inner["statements"][-1]["expression"]["operator"] == "*"
    assert g["body"]["statements"][0]["expression"]["operator"] == "*"
    path.write_text("using T=int; int f(int T,T x);")
    assert cli(path).returncode != 0


def test_binding_order_and_declaration_ambiguity():
    declarations = {d["name"]: d for d in parsed(FIXTURES / "Declarators.cpp")["declarations"]}
    callback = declarations["Callback"]["target"]["declarator"]
    assert [op["type"] for op in callback] == ["PointerOperator", "FunctionOperator"]
    table = declarations["Table"]["target"]["declarator"]
    assert [op["type"] for op in table] == ["ArrayOperator", "PointerOperator", "FunctionOperator"]
    assert table[0]["size"]["raw"] == "2"
    factory = declarations["factory"]
    assert factory["parameters"][0]["name"] == "enabled" and factory["returnType"]["declarator"] == callback
    assert declarations["callbacks"]["variableType"]["declarator"][0]["qualifiers"] == ["const"]
    assert declarations["view"]["variableType"]["declarator"][0]["operator"] == "&"
    param, = declarations["declares_function"]["parameters"]
    assert param["name"] is None and param["parameterType"]["declarator"][0]["type"] == "FunctionOperator"
    obj, fn, _ = declarations["choose"]["body"]["statements"]
    assert obj["initializer"]["arguments"][0]["type"] == "TypeConstruction" and fn["type"] == "FunctionDeclaration"
    loop = declarations["folded"]["body"]["statements"][2]
    assert loop["type"] == "RangeForStatement" and loop["body"]["expression"]["operator"] == "+="


def test_class_hierarchy_and_constructor_initializers():
    unit = parsed(FIXTURES / "Hierarchy.cpp")
    base, _, counter, ctor, method, dtor, leaf, shared, pair = unit["declarations"]
    assert base["members"][2]["functionSpecifier"] == "pure"
    assert counter["final"] and [b["access"] for b in counter["bases"]] == ["public", "private"]
    assert counter["members"][2]["initializers"][0]["target"]["name"] == "Counter"
    assert counter["members"][3]["functionSpecifier"] == "delete"
    assert ctor["name"] == "Counter::Counter" and ctor["parameters"][0]["parameterType"]["specifiers"][0]["name"] == "Value"
    assert ctor["initializers"][0]["initializer"]["elements"][0]["name"] == "n"
    assert method["name"] == "Counter::score" and dtor["functionSpecifier"] == "default"
    assert leaf["bases"][0]["access"] is None and shared["bases"][0]["virtual"]
    assert [i["target"] for i in pair["members"][2]["initializers"]] == ["x", "y"]


def test_template_packs_defaults_and_trailing_return_type():
    unit = parsed(FIXTURES / "Packs.cpp")
    pack, buffer, alias, count, variadic, only, _, assertion, apply, joined, empty, default, default_list = unit["declarations"]
    assert pack["parameters"][0]["pack"]
    assert buffer["parameters"][0]["default"]["specifiers"] == ["int"]
    assert buffer["parameters"][1]["default"]["raw"] == "3"
    expansion, = alias["declaration"]["target"]["specifiers"][0]["arguments"]
    assert expansion["type"] == "PackExpansion"
    function = count["declaration"]
    assert function["parameters"][0]["pack"] and function["trailingReturnType"]["specifiers"] == ["unsigned"]
    assert function["body"]["statements"][0]["expression"] == {"type": "SizeofPack", "name": "values"}
    assert variadic["parameters"][-1]["type"] == only["parameters"][0]["type"] == "Ellipsis"
    assert assertion["test"]["right"]["raw"] == "3"
    assert apply["parameters"][0]["parameters"][0]["pack"]
    assert default["parameters"][0]["default"] == "List"
    assert default_list["target"]["specifiers"][0]["arguments"] == []
    assert joined["declaration"]["bases"][0]["pack"]
    assert empty["target"]["specifiers"][0]["arguments"][0] == {"type": "TemplateName", "name": "List"}


def test_member_pointers_and_common_decl_specifiers():
    nodes = parsed(FIXTURES / "MemberPointers.cpp")["declarations"]
    _, data, getter, field, method, read, variables, functions, grouped = nodes
    assert data["target"]["indirections"][0]["class"] == "demo::Cell"
    assert getter["target"]["declarator"][1]["qualifiers"] == ["const"]
    assert field["variableType"]["indirections"][0]["qualifiers"] == ["const"]
    tree = read["body"]["statements"][0]["expression"]
    assert tree["left"]["operator"] == ".*" and tree["right"]["operator"] == "*"
    assert tree["right"]["right"]["callee"]["expression"]["operator"] == "->*"
    first, ptr, numbers = variables["declarations"]
    assert first["initializer"]["arguments"][0]["raw"] == "1"
    assert ptr["variableType"]["indirections"] == ["*"] and numbers["variableType"]["indirections"] == []
    fn, pointer = functions["declarations"]
    assert fn["type"] == "FunctionDeclaration" and pointer["variableType"]["declarator"][0]["operator"] == "*"
    assert grouped["body"]["statements"][1]["init"]["declarations"][1]["name"] == "j"


def test_operator_names_and_dependent_types():
    number, out_bool, _, call, twice, plus, _ = parsed(FIXTURES / "Operators.cpp")["declarations"]
    assert number["members"][1]["specifiers"] == ["explicit"] and out_bool["qualifier"] == "Number"
    assert number["members"][-1]["target"]["indirections"] == ["*"]
    assert twice["name"] == 'operator""_twice' and plus["name"] == 'operator""_plus'
    expression = call["body"]["statements"][0]["expression"]
    assert expression["left"]["callee"]["member"] == "operator()" and expression["right"]["callee"]["member"] == "operator+"
    alias, read, indirect, static_call, _ = parsed(FIXTURES / "Dependent.cpp")["declarations"]
    segments = alias["declaration"]["target"]["specifiers"][0]["segments"]
    assert [s["name"] for s in segments] == ["T", "rebind", "type"] and segments[1]["template"]
    for fn, access in [(read, "."), (indirect, "->")]:
        member = fn["declaration"]["body"]["statements"][0]["expression"]["callee"]
        assert member["operator"] == access and member["template"]
        assert member["arguments"][0]["specifiers"][0]["segments"][-1]["name"] == "value_type"
    assert static_call["declaration"]["body"]["statements"][0]["expression"]["callee"]["qualifier"] == "T"


def test_fold_direction_and_seed():
    ds = parsed(FIXTURES / "FoldExpressions.cpp")["declarations"]
    folds = {d["declaration"]["name"]: d["declaration"]["body"]["statements"][0]["expression"]
             for d in ds if d["type"] == "TemplateDeclaration"}
    assert folds["left"]["direction"] == "left" and folds["left"]["left"] is None
    assert folds["right"]["direction"] == "right" and folds["right"]["right"] is None
    for name, side in [("subtract_left", "left"), ("subtract_right", "right")]:
        fold = folds[name]
        assert fold["direction"] == side and fold["operator"] == "-"
        assert fold[side]["raw"] == "20"


def test_types_and_expressions_inside_parentheses():
    ds = parsed(FIXTURES / "Operands.cpp")["declarations"]
    expr = ds[1]["body"]["statements"][0]["expression"]
    assert expr["left"]["left"]["cast"] == "c-style"
    assert expr["left"]["right"]["operand"]["indirections"] == ["*"]
    assert expr["right"]["operand"]["declarator"][0]["size"]["raw"] == "3"
    assert ds[2]["body"]["statements"][0]["expression"]["type"] == "NoexceptExpression"
    hidden = ds[3]["body"]["statements"][0]["expression"]
    assert hidden["operand"]["type"] == "ParenthesizedExpression" and hidden["operand"]["expression"]["name"] == "Value"
    comparison = parsed(FIXTURES / "TypeQueries.cpp")["declarations"][-1]["body"]["statements"][0]["expression"]
    assert [comparison[s]["operand"]["type"] for s in ("left", "right")] == ["NameExpression", "Type"]


def test_concepts_requirements_and_constraint_scopes():
    ds = parsed(FIXTURES / "Constraints.cpp")["declarations"]
    req = ds[2]["declaration"]["constraint"]
    simple, typ, compound, nested = req["requirements"]
    assert simple["expression"]["left"]["name"] == "x" and req["parameters"][0]["name"] == "x"
    assert typ["target"]["segments"][-1]["name"] == "value_type"
    assert compound["noexcept"] and compound["constraint"]["arguments"][0]["specifiers"] == ["long"]
    assert nested["constraint"]["type"] == "ConceptId"
    head = ds[3]
    assert head["requires"]["operator"] == "&&" and head["parameters"][0]["constraint"]["name"] == "Small"
    assert head["declaration"]["requires"]["expression"]["operator"] == ">"
    assert ds[8]["abbreviated"] and ds[8]["parameters"][0]["parameterType"]["specifiers"][0]["placeholder"] == "auto"
    shadow = ds[10]["declaration"]["requires"]["expression"]
    assert shadow["left"]["operand"]["expression"]["name"] == "Outer" and shadow["right"]["operand"]["type"] == "Type"
    cast = ds[-1]["declaration"]["body"]["statements"][0]["expression"]
    assert cast["cast"] == "c-style" and cast["operand"]["type"] == "RequiresExpression"


def test_allocation_types_placement_and_initialization():
    statements = parsed(FIXTURES / "Allocation.cpp")["declarations"][1]["body"]["statements"]
    nodes = [s["expression"] for s in statements]
    assert nodes[0]["initializer"] is None and nodes[1]["global"]
    assert [d.get("name", d.get("raw")) for d in nodes[2]["dimensions"]] == ["n", "2"]
    assert nodes[3]["dimensions"] == [None]
    assert [e["raw"] for e in nodes[3]["initializer"]["elements"]] == ["1", "2"]
    assert nodes[4]["parenthesizedType"] and nodes[4]["initializer"]["arguments"] == []
    assert nodes[5]["placement"][0]["name"] == "address" and nodes[5]["parenthesizedType"]
    assert nodes[7]["allocatedType"]["indirections"] == ["*"]
    assert nodes[8]["allocatedType"]["declarator"][0]["size"]["raw"] == "3"


def test_lambda_capture_initializers_template_and_parameter_scopes():
    expressions = parsed(FIXTURES / "Lambdas.cpp")["declarations"]
    generic = expressions[0]["body"]["statements"][0]["initializer"]
    assert generic["captures"][1]["initializer"]["type"] == "CopyInitializer"
    assert generic["specifiers"] == ["mutable"] and generic["noexcept"]
    assert generic["returnType"]["specifiers"] == ["int"]
    assert expressions[2]["body"]["statements"][0]["expression"]["callee"]["specifiers"] == ["consteval"]
    declarations = parsed(FIXTURES / "LambdaScopes.cpp")["declarations"]
    scoped, parameter, after = declarations[1]["body"]["statements"]
    captured = scoped["initializer"]["body"]["statements"][0]["expression"]["left"]["operand"]
    shadow = parameter["initializer"]["body"]["statements"][0]["expression"]["operand"]
    assert captured["expression"]["name"] == shadow["expression"]["name"] == "Outer"
    assert after["expression"]["left"]["left"]["operand"]["type"] == "Type"
    constrained = declarations[-1]["body"]["statements"][0]["initializer"]
    assert constrained["templateRequires"]["name"] == constrained["requires"]["name"] == "Small"


def test_function_try_blocks_and_handler_scope():
    _, dispatch, nested, sample, ctor = parsed(FIXTURES / "Exceptions.cpp")["declarations"]
    named, unnamed, fallback = dispatch["body"]["handlers"]
    assert named["parameter"]["name"] == "Outer" and named["parameter"]["exceptionType"]["indirections"] == ["&"]
    assert named["body"]["statements"][0]["expression"]["operand"]["expression"]["name"] == "Outer"
    assert unnamed["body"]["statements"][0]["expression"]["operand"]["type"] == "Type"
    assert fallback["parameter"] is None
    assert fallback["body"]["statements"][0]["expression"] == {"type": "ThrowExpression", "operand": None}
    outer = nested["body"]["statements"][0]
    throwing = outer["body"]["statements"][0]["body"]["statements"][0]["expression"]
    assert throwing["operand"]["type"] == "AssignmentExpression"
    assert sample["members"][-1]["body"]["type"] == ctor["body"]["type"] == "TryBlock"
    assert ctor["initializers"][0]["target"] == "value"


def test_switch_labels_loops_and_goto():
    select, _, skip = parsed(FIXTURES / "Control.cpp")["declarations"]
    loop, label = select["body"]["statements"]
    switch = loop["body"]["statements"][0]
    case, default, stop = switch["body"]["statements"]
    assert loop["type"] == "DoWhileStatement" and switch["type"] == "SwitchStatement"
    assert case["value"]["raw"] == "1" and case["statement"]["label"] == label["label"] == "done"
    assert default["value"] is None and stop["type"] == "BreakStatement"
    alias_label = skip["body"]["statements"][1]
    assert alias_label["label"] == "Finish"
    assert alias_label["statement"]["expression"]["left"]["operand"]["specifiers"][0]["name"] == "Finish"


def test_selection_initializer_and_loop_condition_scopes():
    statements = parsed(FIXTURES / "Conditions.cpp")["declarations"][1]["body"]["statements"]
    selection = statements[0]
    assert selection["init"]["name"] == selection["test"]["left"]["name"] == "Entry"
    for arm in ("then", "else"):
        assert selection[arm]["expression"]["right"]["operand"]["expression"]["name"] == "Entry"
    assert statements[1]["constexpr"] and statements[1]["test"]["name"] == "enabled"
    assert "init" in statements[2] and statements[2]["init"] is None
    assert statements[4]["test"]["initializer"]["name"] == statements[4]["init"]["name"]
    assert statements[6]["test"]["initializer"]["name"] == statements[6]["init"]["name"]
    assert statements[8]["body"]["statements"][0]["expression"]["right"]["left"]["operand"]["expression"]["name"] == "Entry"
    assert statements[-1]["expression"]["right"]["operand"]["specifiers"][0]["name"] == "Entry"


def test_structured_bindings_in_initializers_and_ranges():
    statements = parsed(FIXTURES / "Bindings.cpp")["declarations"][2]["body"]["statements"]
    assert statements[0]["names"] == ["Name", "extra"]
    assert statements[1]["initializer"]["operand"]["expression"]["name"] == "Name"
    assert statements[2]["init"]["variableType"]["specifiers"] == ["const", "auto"]
    assert statements[3]["binding"]["names"] == ["x", "y"]
    assert statements[3]["init"]["initializer"]["name"] == "extra"


def test_attribute_tokens_owners_and_spans(tmp_path):
    # A .ii input gives offsets in the exact text supplied to the parser.
    path = tmp_path / "attributes.ii"
    source = (FIXTURES / "Attributes.cpp").read_text()
    path.write_text(source)
    nodes = parsed(path)["declarations"]
    spec = nodes[0]["attributes"][0]
    item = spec["items"][0]
    assert source[spec["startOffset"]:spec["endOffset"]] == '[[nodiscard("use result")]]'
    assert source[item["startOffset"]:item["endOffset"]] == 'nodiscard("use result")'
    using, scoped = nodes[4]["attributes"]
    trace, hole, flag, last = using["items"]
    assert using["usingNamespace"] == "vendor" and hole is None and last is None
    assert trace["arguments"][0] == {"delimiter": "()", "tokens": ["a", "+", "b"]}
    assert trace["arguments"][2]["delimiter"] == "[]" and trace["arguments"][4]["delimiter"] == "{}"
    assert flag["arguments"] is None and scoped["items"][0]["name"] == "using"
    body = nodes[5]["body"]["statements"]
    assert body[2]["handlers"][0]["parameter"]["attributes"][0]["items"][0]["name"] == "maybe_unused"
    assert body[3]["initializer"]["attributes"][0]["items"] == [None]
    assert body[4]["initializer"]["dimensionAttributes"][0][0]["items"] == [None]
    assert [nodes[i]["declaration"]["attributes"][0]["operand"]["type"] for i in (6, 7)] == ["Type", "NameExpression"]
    assert all(nodes[i]["declaration"]["attributes"][0]["pack"] for i in (6, 7))
    extension = nodes[10]["declarations"][0]["gnuAttributes"][0]
    assert extension["type"] == "GnuAttributeSpecifier" and extension["items"][0]["arguments"] == ['"v1"']


def test_attribute_pack_expansion_syntax(tmp_path):
    path = tmp_path / "packs.ii"
    path.write_text("template<class... T> struct [[vendor::a(T)..., vendor::b(T)...]] Group {};")
    items = parsed(path)["declarations"][0]["declaration"]["attributes"][0]["items"]
    assert [(item["name"], item["pack"]) for item in items] == [("a", True), ("b", True)]


def test_template_qualified_definitions_and_member_pointers():
    ds = parsed(FIXTURES / "QualifiedOwners.cpp")["declarations"]
    member = ds[1]["declaration"]
    owner = member["owner"]
    assert member["name"] == "Constant::value" and owner["name"] == "Constant"
    assert owner["arguments"][0]["specifiers"][0]["name"] == "T"
    assert owner["arguments"][1] == {"type": "NameExpression", "name": "N"}
    method = ds[3]["declaration"]
    assert method["owner"]["spelling"] == "lib::Box<U>"
    assert method["parameters"][0]["parameterType"]["specifiers"][0]["name"] == "Element"
    pointer, signature = ds[5]["variableType"]["declarator"]
    assert pointer["owner"]["name"] == "lib::Box" and signature["qualifiers"] == ["const"]
    assert ds[4]["initializer"]["operand"]["name"] == "field"
    assert ds[7]["target"]["indirections"][0]["owner"]["arguments"][0]["specifiers"][0]["name"] == "Cell"
    assert ds[10]["target"]["indirections"][0]["owner"]["arguments"][0]["expression"]["operator"] == "<"


def test_language_linkage_blocks_single_declarations_and_gnu_spellings():
    ds = parsed(FIXTURES / "Linkage.cpp")["declarations"]
    assert ds[0]["language"] == ['"C"'] and not ds[0]["block"]
    alias, inner = ds[1]["declarations"]
    assert alias["name"] == "Count" and inner["declarations"][0]["name"] == "inside"
    assert ds[2]["block"] and ds[2]["declarations"] == []
    assert ds[3]["returnType"]["specifiers"][0]["name"] == "Count"
    attrs = ds[5]["declarations"][0]["gnuAttributes"][0]
    assert [item["name"] for item in attrs["items"]] == ["__noreturn__", "__cold__"]
    assert ds[6]["language"] == ['"C"', '"++"']
    assert ds[7]["declarations"][0]["type"] == "EmptyDeclaration"
    assert ds[8]["target"]["specifiers"][0]["gnuSpelling"] == "__decltype"


def test_class_specialization_scopes_and_renamed_parameters():
    ds = parsed(FIXTURES / "Specializations.cpp")["declarations"]
    assert ds[1]["type"] == "ExplicitSpecialization" and ds[1]["declaration"]["specialization"]["arguments"] == []
    partial = ds[2]["declaration"]
    assert partial["specialization"]["arguments"][0]["specifiers"][0]["name"] == "T"
    assert ds[3]["parameters"][0]["parameterType"]["specifiers"][0]["name"] == "Selected"
    short_alias, field = [d["body"]["statements"][0]["expression"]["operand"] for d in ds[7:9]]
    assert short_alias["type"] == "Type" and field["expression"]["name"] == "Label"
    renamed = ds[-1]["declaration"]
    assert renamed["owner"]["arguments"][0]["specifiers"][0]["name"] == "V"
    assert renamed["parameters"][0]["parameterType"]["specifiers"][0]["name"] == "Entry"


def test_dependent_base_types_and_unscoped_enum_names():
    ds = parsed(FIXTURES / "DependentBases.cpp")["declarations"]
    base = ds[1]["declaration"]["bases"][0]["target"]
    assert base["name"] == "type" and base["qualifier"]["arguments"][0]["name"] == "B::value"
    rebound = ds[3]["declaration"]["bases"][0]["target"]
    assert rebound["template"] and rebound["arguments"][0]["specifiers"] == ["int"]
    enum = ds[5]["members"][0]
    assert enum["name"] is None and enum["enumerators"][1]["value"]["left"]["name"] == "off"
    block, after = ds[6]["body"]["statements"]
    assert block["statements"][1]["test"]["left"]["operand"]["expression"]["name"] == "Entry"
    assert after["expression"]["operand"]["type"] == "Type"
    assert ds[-1]["bases"][0]["target"]["operand"]["name"] == "existing"


def test_non_type_parameter_declarators_and_dependent_construction():
    ds = parsed(FIXTURES / "NonTypeParameters.cpp")["declarations"]
    unnamed = ds[0]["parameters"][1]
    assert unnamed["name"] is None and unnamed["default"]["operand"]["type"] == "Type"
    assert ds[1]["parameters"][0]["pack"] and ds[1]["parameters"][0]["name"] is None
    pointer, fn = ds[2]["parameters"][0]["parameterType"]["declarator"]
    assert pointer["operator"] == "*" and fn["type"] == "FunctionOperator"
    assert ds[4]["parameters"][1]["default"]["operand"]["expression"]["name"] == "Value"
    fold = ds[6]["declaration"]["body"]["statements"][0]["expression"]
    assert fold["left"]["target"]["type"] == "DependentType" and fold["operator"] == "+"
    expr_arg = ds[-3]["declaration"]["bases"][0]["target"]["arguments"][0]["left"]
    type_arg = ds[-2]["declaration"]["target"]["specifiers"][0]["arguments"][0]
    assert expr_arg["type"] == "TypeConstruction" and type_arg["declarator"][0]["type"] == "FunctionOperator"
    destroy = ds[-1]["declaration"]["body"]["statements"][0]["expression"]["callee"]
    assert destroy["destructorType"]["type"] == "Decltype"


def test_type_traits_imported_members_and_extension_declaration():
    enum = parsed(FIXTURES / "BuiltinTraits.cpp")["declarations"][0]["declaration"]["members"][0]
    traits = {n["name"]: n["value"] for n in enum["enumerators"]}
    assert traits["trivially_copyable"]["type"] == "BuiltinTypeTraitExpression"
    assert traits["same"]["name"] == "__is_same" and len(traits["same"]["operands"]) == 2
    assert traits["construct"]["operands"][1]["type"] == "PackExpansion"
    ds = parsed(FIXTURES / "UsingMembers.cpp")["declarations"]
    assert [node["target"] for node in ds[1]["declarations"]] == ["names::A", "names::B"]
    typ, value, method = ds[3]["declaration"]["members"]
    assert typ["typename"] and typ["owner"]["name"] == value["owner"]["name"] == "Base"
    assert method["parameters"][0]["parameterType"]["specifiers"][0]["name"] == "Type"
    assert ds[4]["declaration"]["members"][0]["pack"]
    assert ds[6]["type"] == "GnuExtensionDeclaration"
    assert ds[6]["declaration"]["declaration"]["specialization"]["arguments"][0]["specifiers"] == ["unsigned", "__int128"]


def test_unnamed_classes_union_injection_and_variable_templates():
    ds = parsed(FIXTURES / "AnonymousAndVariableTemplates.cpp")["declarations"]
    record, inner, union = ds[0]["members"]
    assert record["name"] is None and record["gnuAttributes"][0]["items"][0]["name"] == "aligned"
    assert [d["name"] for d in record["declarators"]] == ["slot", "extra"]
    assert record["declarators"][1]["dimensions"][0]["raw"] == "2"
    assert inner["key"] == "class" and union["key"] == "union"
    arg = ds[3]["declaration"]["bases"][0]["target"]["arguments"][0]
    assert arg["type"] == "TemplateId" and arg["name"] == "options::enabled"
    assert arg["arguments"][0]["specifiers"][0]["name"] == "T"
    block, after = ds[-1]["body"]["statements"]
    assert block["statements"][1]["test"]["left"]["operand"]["expression"]["name"] == "Entry"
    assert after["expression"]["operand"]["type"] == "Type"


def test_dependent_template_names_and_gcc14_type_builtins():
    ds = parsed(FIXTURES / "TemplateNameArguments.cpp")["declarations"]
    arg = ds[2]["declaration"]["target"]["specifiers"][0]["segments"][0]["arguments"][0]
    assert arg["type"] == "DependentTemplateName" and arg["name"] == "Rebind"
    assert arg["owner"]["arguments"][0]["specifiers"][0]["name"] == "T"
    requirement = ds[4]["declaration"]["constraint"]["requirements"][0]["target"]
    assert requirement["name"] == "Op" and requirement["arguments"][0]["type"] == "PackExpansion"
    gcc = parsed(FIXTURES / "Gcc14TypeBuiltins.cpp")["declarations"]
    for node in gcc[:2]:
        trait = node["declaration"]["initializer"]
        assert trait["type"] == "BuiltinTypeTraitExpression" and len(trait["operands"]) == 2
    assert gcc[2]["declaration"]["target"]["specifiers"][0]["name"] == "__remove_reference"


def test_variable_specializations_and_conditional_noexcept():
    ds = parsed(FIXTURES / "VariableSpecializations.cpp")["declarations"]
    partial, explicit = ds[1:3]
    assert partial["declaration"]["specialization"]["arguments"][0]["indirections"] == ["&"]
    assert explicit["type"] == "ExplicitSpecialization"
    assert explicit["declaration"]["specialization"]["arguments"][0]["specifiers"] == ["void"]
    method = ds[4]["members"][1]["declaration"]
    assert method["body"]["type"] == "CompoundStatement"
    assert method["noexcept"]["callee"]["name"] == "safe"
    assert method["noexcept"]["callee"]["arguments"][0]["specifiers"][0]["name"] == "T"
    self_reference = ds[5]["declaration"]["initializer"]
    assert self_reference["type"] == "TemplateId" and self_reference["arguments"][0]["operator"] == "-"


def test_friend_types_and_postfix_casts():
    ds = parsed(FIXTURES / "FriendTypes.cpp")["declarations"]
    friends = ds[1]["declaration"]["members"]
    assert friends[0]["key"] == "class" and friends[0]["target"]["name"] == "Hidden"
    assert friends[1]["target"]["arguments"][0]["specifiers"] == ["int"]
    assert friends[2]["target"]["name"] == "T::Nested"
    assert friends[3]["target"]["specifiers"][0]["name"] == "T"
    assert friends[-1]["declaration"]["target"]["name"] == "Peer"
    result = ds[7]["body"]["statements"][0]["expression"]
    assert result["left"]["left"]["left"]["base"]["cast"] == "static_cast"
    ptr_array = result["right"]["base"]["base"]["target"]["declarator"]
    assert [op["type"] for op in ptr_array] == ["PointerOperator", "ArrayOperator"]
    assert ds[8]["declarationSpecifiers"] == ["inline", "constexpr"] and ds[8]["declarators"][0]["name"] == "maker"
    assert ds[9]["declaration"]["target"]["specifiers"][0]["type"] == "BuiltinPackElement"
    call = ds[-1]["members"][0]
    assert call["declaratorAttributes"][0]["items"][0]["name"] == "nodiscard"
    assert call["parameters"][0]["declaratorAttributes"][0]["items"][0]["name"] == "maybe_unused"


def test_deduction_guides_and_conditional_explicit(tmp_path):
    ds = parsed(FIXTURES / "DeductionGuides.cpp")["declarations"]
    _, generic, direct, conditional = ds[0]["declarations"]
    guide = generic["declaration"]
    assert guide["type"] == "DeductionGuide" and guide["explicit"] is False
    assert [p["name"] for p in guide["parameters"]] == ["a", "b"]
    assert [t["specifiers"][0]["name"] for t in guide["target"]["arguments"]] == ["A", "B"]
    assert direct["explicit"] is True and conditional["declaration"]["explicit"]["operator"] == ">"
    assert ds[4]["postClassSpecifiers"] == ["inline", "constexpr"]
    ctor = ds[6]["declaration"]["members"][1]
    assert ctor["specifiers"][1]["condition"]["operator"] == ">" and ctor["requires"]["name"] == "Sized"
    assert ds[8]["noexcept"]["type"] == "EmptyThrowSpecification"
    assert ds[10]["target"]["arguments"][0]["specifiers"] == ["int"]

    # In this argument position Self is the injected class type, followed by a reference declarator.
    path = tmp_path / "injected.ii"
    path.write_text("template<class> struct TypeArg {}; template<class T> struct Self { using Wrapped = TypeArg<Self &&>; };")
    alias = parsed(path)["declarations"][1]["declaration"]["members"][0]
    assert alias["target"]["specifiers"][0]["arguments"][0]["indirections"] == ["&&"]


def test_record_typedefs_special_members_and_field_widths():
    ds = parsed(FIXTURES / "RecordAliases.cpp")["declarations"]
    div, ptr, pair = ds[0]["typedefs"]
    assert div["name"] == "Div" and not div["declarator"]
    assert ptr["declarator"][0]["operator"] == "*" and pair["declarator"][0]["size"]["raw"] == "2"
    ctor, dtor = [d["declaration"] for d in ds[4:6]]
    assert ctor["owner"]["spelling"] == dtor["owner"]["spelling"] == "Box<U>"
    assert ctor["parameters"][1]["parameterType"]["specifiers"][0]["name"] == "Size"
    assert ctor["initializers"][0]["target"] == "value"
    bits = ds[8]["members"][0]["declarations"]
    assert [b["name"] for b in bits] == ["ready", None, "mode"]
    assert bits[2]["bitWidth"]["raw"] == "3" and bits[2]["initializer"]["elements"][0]["raw"] == "2"
    first, second = ds[10]["members"]
    assert first["bitWidth"]["else"]["type"] == "AssignmentExpression" and first["initializer"] is None
    assert second["initializer"]["raw"] == "2"
    assert ds[11]["declarations"][0]["asmLabel"]["parts"] == ['"external_entry"']


def test_class_alias_scope_and_decltype_construction():
    ds = parsed(FIXTURES / "ClassAliasLookup.cpp")["declarations"]
    assert ds[1]["typedefs"][0]["gnuAttributes"][0]["items"][0]["name"] == "aligned"
    first, nested, final = ds[3]["members"][-1]["body"]["statements"]
    assert first["initializer"]["target"]["specifiers"][0]["name"] == "Chain::Value"
    assert nested["statements"][1]["variableType"]["specifiers"][0]["name"] == "S::Value"
    assert final["expression"]["right"]["operand"]["type"] == "Type"
    copied = ds[4]["declaration"]["body"]["statements"][0]["expression"]
    assert copied["target"]["type"] == "Decltype" and copied["initializer"]["elements"][0]["name"] == "input"
    assert ds[5]["declaration"]["members"][1]["requires"]["type"] == "RequiresExpression"
    assert ds[-1]["target"]["specifiers"][0]["name"] == "Parent::Member::Value"


def test_instantiation_declarations_and_specializations():
    ds = parsed(FIXTURES / "ExplicitInstantiation.cpp")["declarations"]
    assert ds[1]["extern"] and ds[1]["target"]["arguments"][0]["specifiers"] == ["int"]
    assert not ds[2]["extern"] and ds[2]["key"] == "struct"
    assert ds[4]["declaration"]["body"]["statements"][0]["expression"]["operator"] == "+"
    assert ds[5]["declaration"]["specialization"]["arguments"][0]["specifiers"] == ["long"]
    assert ds[9]["declaration"]["owner"]["spelling"] == "Host<int>"
    assert ds[10]["members"][0]["specialization"]["arguments"] == []
    funcs = parsed(FIXTURES / "InstantiatedDeclarators.cpp")["declarations"]
    assert funcs[1]["extern"] and funcs[1]["declaration"]["name"] == "identity"
    assert funcs[2]["declaration"]["specialization"]["arguments"][0]["specifiers"] == ["long"]
    assert not funcs[4]["extern"] and funcs[4]["declaration"]["specialization"]["name"] == "size"


def test_complete_class_body_lookup_and_positions(tmp_path):
    from orionparser.registry import get_pipeline

    path = tmp_path / "complete.ii"
    source = (FIXTURES / "CompleteClass.cpp").read_text()
    path.write_text(source)
    pipeline = get_pipeline(path)
    result = pipeline.analyze_file(path)
    assert result.success and result.tokens == pipeline.tokenize(source)
    ds = result.ast["declarations"]
    members = ds[0]["declarations"][0]["declaration"]["members"]
    decl, conditional, _ = members[0]["declaration"]["body"]["statements"]
    assert decl["variableType"]["specifiers"][0]["name"] == "Later"
    assert conditional["test"]["type"] == "TemplateId" and conditional["test"]["name"] == "enabled"
    assert members[1]["body"]["statements"][1]["expression"]["operator"] == "<"
    assert members[2]["members"][0]["body"]["statements"][0]["expression"]["arguments"][0]["specifiers"][0]["name"] == "T"
    assert ds[2]["name"] == "Outer::Inner" and ds[3]["body"]["statements"][0]["declarators"][0]["initializer"]["arguments"][0]["name"] == "n"
    path.write_text("struct S {\n    int f() { return 1 + ; }\n    using Next = int;\n};\n")
    invalid = pipeline.analyze_file(path)
    assert not invalid.success and "line 2, column 26" in invalid.errors[0]


def test_gnu_attribute_spellings_and_float_types():
    ds = parsed(FIXTURES / "MemberAttributes.cpp")["declarations"]
    assert ds[0]["target"]["declarator"][0]["gnuAttributes"][0]["items"][0]["name"] == "__deprecated__"
    assert ds[1]["gnuAttributes"][0]["spelling"] == "__attribute"
    assert ds[2]["members"][0]["gnuAttributes"][0]["items"][0]["name"] == "nonnull"
    types = parsed(FIXTURES / "Gcc14TypeBuiltins.cpp")["declarations"]
    assert [d["target"]["specifiers"][0]["name"] for d in types[-5:]] == ["_Float32", "_Float64", "_Float128", "_Float32x", "_Float64x"]


def test_member_template_lookup_and_nested_owners():
    ds = parsed(FIXTURES / "KnownMembers.cpp")["declarations"]
    expr = ds[4]["declaration"]["body"]["statements"][0]["expression"]
    callees = [expr["left"]["left"]["callee"], expr["left"]["right"]["callee"], expr["right"]["callee"]]
    assert [c["operator"] for c in callees] == [".", "->", "."]
    for callee in callees:
        assert callee["template"] is False and callee["arguments"][0]["specifiers"][0]["name"] == "T"
    comparison = ds[5]["body"]["statements"][0]["expression"]
    assert comparison["operator"] == ">" and comparison["left"]["operator"] == "<"
    alias = ds[8]["target"]["specifiers"][0]
    assert alias["type"] == "QualifiedType" and alias["qualifier"]["name"] == "Select"
    ctor = ds[11]["declaration"]
    assert ctor["owner"]["spelling"] == "Enclosing<T>::Inner" and ctor["initializers"][0]["target"] == "value"


def test_qualified_operator_call_and_comma_return(tmp_path):
    ds = parsed(FIXTURES / "QualifiedCalls.cpp")["declarations"]
    call = ds[1]["declaration"]["members"][0]["body"]["statements"][0]["expression"]
    assert call["callee"]["base"]["type"] == "ThisExpression"
    assert call["callee"]["qualifier"]["arguments"][0]["specifiers"][0]["name"] == "T"
    assert call["callee"]["member"] == "operator=" and call["arguments"][0]["name"] == "other"
    returned = ds[2]["body"]["statements"][0]["expression"]
    assert returned["type"] == "CommaExpression" and returned["left"]["operator"] == "="
    assert ds[4]["body"]["statements"][0]["expression"]["type"] == "InitializerList"

    path = tmp_path / "member-inst.ii"
    path.write_text("template<class T> struct Stream { template<class V> int insert(V); };\n"
                    "template<class T> template<class U> int Stream<T>::insert(U x) { return int(x); }\n"
                    "using Concrete = Stream<char>;\nextern template int Concrete::insert(long);\n")
    inst = parsed(path)["declarations"][-1]
    assert inst["extern"] and inst["declaration"]["name"] == "Concrete::insert"


def test_elaborated_declarations_and_scoped_namespace_aliases():
    ds = parsed(FIXTURES / "SystemDeclarations.cpp")["declarations"]
    assert ds[2]["members"][0]["variableType"]["specifiers"][0] == {"type": "ElaboratedType", "key": "enum", "name": "Kind"}
    stamp = ds[3]["parameters"][1]["parameterType"]
    assert stamp["specifiers"][1]["name"] == "tags::Stamp" and stamp["declarator"][0]["size"]["raw"] == "2"
    count, ptr, array = ds[5]["declarations"]
    assert count["target"]["indirections"] == [] and ptr["target"]["indirections"] == ["*"]
    assert array["target"]["declarator"][0]["size"]["raw"] == "2"
    alias, value, nested, ret = ds[13]["body"]["statements"]
    assert alias["target"] == "outer::detail" and nested["statements"][0]["target"] == "other"
    assert value["variableType"]["specifiers"][0]["name"] == "select::Item"
    assert ret["expression"]["name"] == "value"


def test_constructor_initializer_arguments_see_complete_class(tmp_path):
    ds = parsed(FIXTURES / "SystemDeclarations.cpp")["declarations"]
    ctor = ds[10]["declaration"]["members"][0]
    paren, braces = ctor["initializers"]
    assert paren["initializer"]["values"][0]["target"]["specifiers"][0]["name"] == "Index"
    assert braces["initializer"]["elements"][0]["operand"]["type"] == "Type"
    assert ds[8]["parameters"][0]["parameterType"]["specifiers"][0]["name"] == "Text"
    assert ds[9]["parameters"][0]["parameterType"]["indirections"] == ["&&"]
    assert ds[15]["members"][0]["conversionType"]["specifiers"] == ["int"]
    assert ds[17]["declaration"]["target"]["specifiers"][0]["segments"][0]["decltype"]["type"] == "Decltype"
    call = ds[21]["members"][0]["body"]["statements"][0]["expression"]
    assert call["callee"]["name"] == "operator()" and call["callee"]["arguments"][0]["specifiers"] == ["int"]
    path = tmp_path / "shadow.ii"
    path.write_text("struct C { C(int Index) : n(sizeof(Index)) {} using Index = int; int n; };")
    width = parsed(path)["declarations"][0]["members"][0]["initializers"][0]["initializer"]["values"][0]
    assert width["operand"]["expression"]["name"] == "Index"


def test_coroutine_operands_and_precedence():
    ds = parsed(FIXTURES / "Coroutines.cpp")["declarations"]
    cases = {d.get("name"): d for d in ds}
    statements = cases["coro_case_sequence"]["body"]["statements"]
    rhs = statements[0]["expression"]["right"]
    assert rhs["operator"] == "+" and rhs["left"] == {"type": "AwaitExpression", "operand": {"type": "NameExpression", "name": "a"}}
    assert statements[1]["expression"]["operand"]["type"] == "AssignmentExpression"
    assert statements[2]["expression"]["operand"]["elements"][1]["operator"] == "+"
    assert statements[-1] == {"type": "CoroutineReturnStatement", "operand": None}
    result = cases["coro_case_result"]["body"]["statements"][0]["operand"]
    assert result["elements"][0]["type"] == "AwaitExpression" and result["elements"][1]["raw"] == "4"
    member = cases["Worker"]["members"][0]["body"]["statements"]
    assert member[0]["variableType"]["specifiers"][0]["name"] == "Later"


def test_mixed_returns_and_integer_sequence_template(tmp_path):
    source = (FIXTURES / "Coroutines.cpp").read_text()
    for body in ("return Sequence{}; co_return;", "co_return; return Sequence{};"):
        path = tmp_path / "mixed.cpp"
        path.write_text(source + "\nSequence mixed() { " + body + " }\n")
        result = cli(path)
        assert result.returncode and "ordinary return in a coroutine" in result.stderr
    ds = parsed(FIXTURES / "IntegerSequences.cpp")["declarations"]
    seq = ds[1]["target"]["specifiers"][0]
    assert seq["type"] == "BuiltinIntegerSequence" and seq["template"]["name"] == "Sequence"
    assert seq["elementType"]["specifiers"] == ["int"] and seq["length"]["raw"] == "4"


def test_designated_members_preserve_order_nesting_and_initialization_form():
    ds = parsed(FIXTURES / "Designated.cpp")["declarations"]
    result = ds[2]["body"]["statements"][0]["expression"]
    corner, size = result["elements"]
    assert result["trailingComma"] and corner["member"] == "corner" and corner["form"] == "="
    assert corner["value"]["elements"][0]["member"] == "y"
    assert size["member"] == "size" and size["form"] == "{}"
    assert size["value"]["elements"][0]["operator"] == "+"
    dependent = ds[3]["declaration"]["body"]["statements"][0]["expression"]["initializer"]
    assert not dependent["trailingComma"] and [d["member"] for d in dependent["elements"]] == ["x", "y"]


def test_array_attribute_owners_and_pack_names(tmp_path):
    grid, row, named, unnamed, grouped, callback, record = parsed(FIXTURES / "ArrayAttributes.cpp")["declarations"]

    def names(specifiers):
        return [(item["namespace"], item["name"]) for spec in specifiers for item in spec["items"]]

    assert names(grid["declaratorAttributes"]) == [(None, "maybe_unused")]
    assert [names(attrs) for attrs in grid["dimensionAttributes"]] == [
        [("example", "outer")], [], [("example", "inner")]
    ]
    assert [d["raw"] for d in grid["dimensions"]] == ["2", "3", "4"]
    assert names(row["target"]["declarator"][0]["attributes"]) == [("example", "row")]
    for template, field, name in [(named, "dim", "values"), (unnamed, "anonymous", None), (grouped, "ref", "values")]:
        param, = template["declaration"]["parameters"]
        assert param["name"] == name and param["pack"]
        assert names(param.get("declaratorAttributes", [])) == ([(None, "maybe_unused")] if name else [])
        assert names(param["parameterType"]["declarator"][-1]["attributes"]) == [("example", field)]
    assert names(callback["parameters"][0]["declaratorAttributes"]) == [("example", "callback")]
    entries, = record["declarators"]
    assert names(entries["declaratorAttributes"]) == [("example", "object")]
    assert names(entries["dimensionAttributes"][0]) == [("example", "records")]
    bounds = tmp_path / "bounds.ii"
    bounds.write_text("int conditional_bound[true ? 2 : 3]; int parenthesized_bound[(1, 2)];")
    conditional, comma = parsed(bounds)["declarations"]
    assert conditional["dimensions"][0]["type"] == "ConditionalExpression"
    assert comma["dimensions"][0]["expression"]["type"] == "CommaExpression"


def test_pointer_and_function_attribute_owners():
    unit = parsed(FIXTURES / "PointerAttributes.cpp")
    decls = {d.get("name"): d for d in unit["declarations"]}

    def attr(node, field="attributes"):
        spec, = node[field]
        item, = spec["items"]
        assert item["namespace"] == "example"
        return item["name"]

    inner, outer = decls["Pointer"]["target"]["indirections"]
    assert (attr(inner), inner["qualifiers"], attr(outer)) == ("inner", ["const"], "outer")
    for alias, operator, label in [("Member", "*", "member"), ("Ref", "&", "reference"), ("Move", "&&", "move")]:
        part, = decls[alias]["target"]["indirections"]
        assert (part["operator"], attr(part)) == (operator, label)
    assert decls["Member"]["target"]["indirections"][0]["class"] == "Cell"
    templated, = decls["Templated"]["target"]["indirections"]
    assert (templated["class"], attr(templated)) == ("Box<int>", "element")
    callback, function = decls["Callback"]["target"]["declarator"]
    assert attr(callback) == "callback" and function["type"] == "FunctionOperator"
    assert [attr(p["parameterType"]["declarator"][0]) for p in decls["visit"]["parameters"]] == ["handler", "array"]
    assert [attr(m, "functionTypeAttributes") for m in decls["Qualified"]["members"]] == [
        "method", "ctor", "dtor", "method", "convert"
    ]
    pointer, function = decls["Method"]["target"]["declarator"]
    assert (attr(pointer), attr(function), function["qualifiers"]) == ("ptr", "signature", ["const", "&&"])


def test_enum_redeclarations_and_attribute_owners(tmp_path):
    decls = parsed(FIXTURES / "EnumDeclarations.cpp")["declarations"]
    ns, mode, flags, phase, choose, use = decls[:6]
    word, mode_decl, flags_decl, owner = ns["declarations"]
    assert word["name"] == "Word"
    assert mode_decl["attributes"][0]["items"][0]["name"] == "nodiscard"
    assert mode_decl["enumerators"] is None and flags_decl["enumerators"] is None
    assert mode["name"] == "api::Mode" and mode["trailingComma"]
    assert mode["underlying"]["specifiers"][0]["name"] == "api::Word"
    idle, old = mode["enumerators"]
    assert idle["name"] == "idle" and old["value"]["raw"] == "9"
    assert old["attributes"][0]["items"][0]["arguments"] == ['"use idle"']
    assert flags["enumerators"][1]["value"]["left"]["name"] == "read"
    assert owner["members"][0]["key"] == phase["key"] == "struct"
    assert phase["name"] == "api::Owner::Phase"
    assert choose["body"]["statements"][0]["expression"]["name"] == "api::Mode::idle"
    assert use["body"]["statements"][0]["expression"]["left"]["name"] == "api::read"

    for decl in decls[8:]:
        operand = decl["body"]["statements"][-1]["expression"]["operand"]
        if decl["name"] == "outside":
            assert operand["type"] == "Type" and operand["specifiers"][0]["name"] == "idle"
        else:
            assert operand["expression"] == {"type": "NameExpression", "name": "idle"}

    scope = tmp_path / "scope.ii"
    scope.write_text("namespace N{inline namespace I{enum class E;}} enum class N::E{a}; "
                     "void f(){enum E : int; enum E : int {b};} void g(){enum E : int {c};}")
    assert parsed(scope)["declarations"][1]["enumerators"][0]["name"] == "a"


def test_enum_definitions_in_object_and_alias_declarators(tmp_path):
    objects, aliases, modern, bits, take, values, holder, local = parsed(FIXTURES / "EnumObjects.cpp")["declarations"]
    selected, pointer = objects["declarations"]
    assert selected["variableType"]["specifiers"][0]["enumerators"][1]["name"] == "second"
    assert selected["initializer"]["name"] == "Kind::first"
    assert pointer["variableType"]["indirections"] == ["*"] and pointer["initializer"]["operator"] == "&"
    legacy, legacy_ptr = aliases["declarations"]
    assert legacy["target"]["specifiers"][0]["name"] == legacy["name"] == "Legacy"
    assert legacy_ptr["target"]["indirections"] == ["*"]
    assert take["returnType"]["specifiers"][0]["name"] == "LegacyPtr"
    assert modern["target"]["specifiers"][0]["name"] == "Named"
    assert bits["dimensions"][0]["raw"] == "1" and values["target"]["declarator"][0]["size"]["raw"] == "2"
    assert [field["name"] for field in holder["members"]] == ["flag", None]
    assert local["body"]["statements"][0]["declarations"][1]["name"] == "p"

    path = tmp_path / "anonymous.ii"
    path.write_text("typedef enum { off, on } Switch, *Handle; Handle get(Switch *p){return p;}")
    group, get = parsed(path)["declarations"]
    switch, handle = group["declarations"]
    assert switch["target"]["specifiers"][0]["name"] is None
    assert handle["name"] == "Handle" and handle["target"]["indirections"] == ["*"]
    assert get["parameters"][0]["parameterType"]["specifiers"][0]["name"] == "Switch"


def test_record_object_declarators_and_inline_aliases(tmp_path):
    row, array, node, read, item, packet, tag = parsed(FIXTURES / "RecordObjects.cpp")["declarations"]
    obj, pointer, ref = row["declarators"]
    assert obj["initializer"]["elements"][0]["raw"] == "3"
    assert [d["declarator"][0]["operator"] for d in (pointer, ref)] == ["*", "&"]
    assert pointer["initializer"]["operand"]["name"] == "row" and ref["initializer"]["name"] == "row"
    assert array["target"]["specifiers"][0]["name"] == "Element"
    assert array["target"]["declarator"][0]["size"]["raw"] == "2"
    assert node["target"]["specifiers"][0]["members"][0]["name"] == "Size"
    assert read["returnType"]["specifiers"][0]["name"] == "Node::Size"
    items, ptr = item["declarators"]
    assert items["dimensions"][0]["raw"] == "2"
    assert [op["type"] for op in ptr["declarator"]] == ["PointerOperator", "ArrayOperator"]

    assert packet["declarationSpecifiers"] == ["const"] and tag["declarationSpecifiers"] == ["volatile"]
    assert packet["typedefs"][1]["declarator"][0]["operator"] == "*"

    path = tmp_path / "anonymous.ii"
    path.write_text("using A = struct { using Size = long; }; A::Size n;")
    alias, n = parsed(path)["declarations"]
    assert alias["target"]["specifiers"][0]["name"] is None and n["name"] == "n"


def test_asm_declaration_scopes_and_strings(tmp_path):
    empty, ns, assertion = parsed(FIXTURES / "Asm.cpp")["declarations"]
    assert assertion["message"] == ['"ordinary "', 'R"msg(raw message)msg"']
    assert empty == {"type": "AsmDeclaration", "parts": ['""']}
    declaration, marker = ns["declarations"]
    assert declaration["parts"] == ['"# "', '"namespace"']
    statement, conditional, returned = marker["body"]["statements"]
    assert statement["parts"] == ['R"note(# block)note"', '"\\n"']
    assert statement["attributes"][0]["items"] == [None]
    assert conditional["then"]["parts"] == ['"# conditional"'] and returned["type"] == "ReturnStatement"
    path = tmp_path / "asm.ii"
    path.write_text('[[vendor::file]] asm(L""); void f(){ [[vendor::block]] asm(u8""); }')
    file_asm, function = parsed(path)["declarations"]
    block_asm, = function["body"]["statements"]
    for node, name, operand in ((file_asm, "file", 'L""'), (block_asm, "block", 'u8""')):
        assert node["parts"] == [operand]
        assert node["attributes"][0]["items"][0]["name"] == name


def test_qualified_destructor_calls():
    declarations = parsed(FIXTURES / "DestructorCalls.cpp")["declarations"]
    calls = {}
    for node in declarations:
        function = node.get("declaration", node)
        if function.get("body"):
            call = function["body"]["statements"][0]["expression"]
            assert call["type"] == "CallExpression" and call["arguments"] == []
            callee = call["callee"]
            calls[function["name"]] = callee["expression"] if callee["type"] == "ParenthesizedExpression" else callee
    for fn, base, op, qualifier, destroyed in [
        ("retire", "p", "->", "T", "T"), ("end_count", "value", ".", "Count", "Count"),
        ("end_cell", "p", "->", "library::Cell", "Cell"), ("end_box", "box", ".", "Box", "Box"),
        ("nested", "p", "->", "T::Inner", "Inner"), ("absolute", "c", ".", "::library::Cell", "Cell"),
        ("release", "h", "->", "library::Handle", "Handle")
    ]:
        member = calls[fn]
        assert (member["base"]["name"], member["operator"]) == (base, op)
        assert (member["qualifier"]["name"], member["destructorType"]["name"]) == (qualifier, destroyed)
    for fn in ("end_box", "release"):
        assert calls[fn]["qualifier"]["arguments"] == calls[fn]["destructorType"]["arguments"]
        assert calls[fn]["destructorType"]["arguments"][0]["specifiers"] == ["int"]


def test_conversion_function_calls_and_address():
    nodes = parsed(FIXTURES / "ConversionCalls.cpp")["declarations"]
    expressions = {}
    for decl in nodes:
        function = decl.get("declaration", decl)
        if function.get("body"):
            expressions[function["name"]] = function["body"]["statements"][0]["expression"]
    for name, obj, op, target in (("value", "n", ".", "int"), ("pointer_value", "p", "->", "int"),
                                  ("address", "a", ".", "int"), ("unwrap", "v", ".", "int")):
        call = expressions[name]
        member = call["callee"]
        assert call["arguments"] == [] and member["member"] == "operator"
        assert (member["base"]["name"], member["operator"]) == (obj, op)
        assert target in member["conversionType"]["specifiers"]
    assert expressions["pointer_value"]["callee"]["qualifier"]["name"] == "Number"
    assert expressions["unwrap"]["callee"]["qualifier"]["arguments"][0]["specifiers"] == ["int"]
    ptr = expressions["first"]["base"]["callee"]["conversionType"]
    assert ptr["specifiers"] == ["const", "int"] and ptr["indirections"] == ["*"]
    assert expressions["dependent"]["callee"]["conversionType"]["specifiers"][0]["name"] == "T"
    getter = nodes[7]["members"][-1]["body"]["statements"][0]["expression"]["callee"]
    assert getter["type"] == "ConversionFunctionId" and getter["target"]["specifiers"][0]["name"] == "Scalar"
    pointer = nodes[9]["initializer"]
    assert pointer["operator"] == "&" and pointer["operand"]["qualifier"] == "Index"
    pick = nodes[-1]["initializer"]["operand"]
    assert pick["target"]["specifiers"][0]["arguments"] == [{"type": "NameExpression", "name": "Choice"}]



def test_qualified_member_template_arguments_and_relations():
    declarations = parsed(FIXTURES / "QualifiedMemberTemplates.cpp")["declarations"]
    expressions = {}
    for node in declarations:
        fn = node.get("declaration", node)
        if fn.get("body"):
            expressions[fn["name"]] = fn["body"]["statements"][0]["expression"]
    for fn, op, obj, owner, member, keyword in [
        ("read", ".", "v", "Base", "get", True), ("indirect", "->", "p", "T", "get", True),
        ("total", "->", "p", "lib::Holder", "sum", True), ("known", ".", "v", "Base", "get", False),
        ("known_specialization", "->", "p", "lib::Holder", "sum", False),
        ("shadow", ".", "obj", "T", "get", True)
    ]:
        callee = expressions[fn]["callee"]
        assert (callee["operator"], callee["base"]["name"], callee["qualifier"]["name"]) == (op, obj, owner)
        assert callee["member"] == member and callee["template"] is keyword
    total = expressions["total"]["callee"]
    assert total["qualifier"]["arguments"][0]["specifiers"] == ["char"]
    assert total["arguments"][0]["specifiers"] == ["long"] and total["arguments"][1]["raw"] == "3"
    nested = expressions["nested_args"]["callee"]["arguments"][0]["specifiers"][0]
    assert nested["name"] == "lib::Holder" and nested["arguments"][0]["specifiers"] == ["unsigned"]
    for fn, operator in [("less", "<"), ("greater", ">"), ("at_least", ">="), ("at_most", "<=")]:
        assert expressions[fn]["operator"] == operator and expressions[fn]["left"]["member"] == "Data::field"


def test_member_operator_template_calls():
    calls = {}
    for node in parsed(FIXTURES / "MemberOperatorTemplates.cpp")["declarations"]:
        fn = node.get("declaration", node)
        if fn.get("body"):
            calls[fn["name"]] = fn["body"]["statements"][0]["expression"]
    for fn, op, name, keyword in [
        ("invoke", ".", "operator()", True), ("via_ptr", "->", "operator()", True),
        ("qualified", ".", "operator()", True), ("index", "->", "operator[]", True),
        ("known", ".", "operator()", False), ("known_base", "->", "operator()", False),
        ("specialized", ".", "operator+", False), ("smaller", ".", "operator<", False),
        ("shift", ".", "operator>>", True), ("pending", ".", "operator()", True)
    ]:
        member = calls[fn]["callee"]
        assert (member["operator"], member["member"], member["template"]) == (op, name, keyword)
    assert calls["invoke"]["callee"]["arguments"][0]["specifiers"] == ["int"]
    assert calls["invoke"]["arguments"][0]["raw"] == "7"
    owner = calls["specialized"]["callee"]["qualifier"]
    assert owner["name"] == "lib::Fun" and owner["arguments"][0]["specifiers"] == ["int"]
    assert calls["pair"]["callee"]["arguments"] == []
    assert [arg["raw"] for arg in calls["pair"]["arguments"]] == ["10", "11"]


def test_generic_lambda_operator_template_lookup():
    declarations = parsed(FIXTURES / "LambdaOperatorCalls.cpp")["declarations"]
    functions = {n["name"]: n["body"]["statements"] for n in declarations if n["type"] == "FunctionDeclaration"}
    explicit, result = functions["invoke"]
    assert explicit["initializer"]["templateParameters"][0]["name"] == "T"
    assert result["expression"]["callee"]["arguments"][0]["specifiers"] == ["int"]
    lhs = functions["aliases"][-1]["expression"]["left"]["callee"]
    rhs = functions["aliases"][-1]["expression"]["right"]["callee"]
    assert (lhs["base"]["name"], lhs["operator"], rhs["base"]["name"], rhs["operator"]) == ("alias", ".", "pointer", "->")
    assert lhs["member"] == rhs["member"] == "operator()" and lhs["template"] is rhs["template"] is False
    capture_body = functions["captured"][1]["initializer"]["body"]["statements"][0]["expression"]
    assert [capture_body[side]["callee"]["base"]["name"] for side in ("left", "right")] == ["id", "duplicate"]
    assert functions["immediate"][0]["expression"]["callee"]["base"]["expression"]["type"] == "LambdaExpression"
    inner = functions["shadow"][1]["statements"][-1]["expression"]["callee"]
    assert "arguments" not in inner and functions["shadow"][-1]["expression"]["callee"]["arguments"]
    alias = functions["retained"][1]
    assert alias["variableType"]["specifiers"] == [{"type": "Decltype", "operand": "auto"}]
    assert functions["retained"][-1]["expression"]["callee"]["base"]["name"] == "ref"
    original, copy, direct = functions["direct_copy"]
    assert original["initializer"]["type"] == "InitializerList"
    assert copy["initializer"]["type"] == "DirectInitializer"
    assert direct["expression"]["callee"]["base"]["name"] == "copy"
    assert functions["from_class"][0]["expression"]["callee"]["base"]["name"] == "Registry::id"


def test_closure_aliases_and_parameter_lookup(tmp_path):
    declarations = parsed(FIXTURES / "ClosureAliases.cpp")["declarations"]
    nodes = {node.get("name"): node for node in declarations}
    assert nodes["Callable"]["target"]["specifiers"][0]["operand"]["name"] == "id"
    for fn, name, access in [("apply", "copy", "."), ("pointer", "p", "->"), ("reference", "f", "."),
                             ("local", "v", "."), ("specialized", "f", ".")]:
        callee = nodes[fn]["body"]["statements"][-1]["expression"]["callee"]
        assert (callee["base"]["name"], callee["operator"], callee["member"]) == (name, access, "operator()")
        assert callee["template"] is False and len(callee["arguments"]) == 1
    deep = nodes["deep"]["body"]["statements"][0]["expression"]["callee"]
    assert deep["base"]["expression"]["operator"] == "*" and deep["operator"] == "->"
    field = nodes["field"]["body"]["statements"][0]["expression"]["callee"]
    assert field["base"]["member"] == "value"
    ordinary = nodes["ordinary_scope"]["body"]["statements"][-1]["expression"]["callee"]
    assert ordinary["member"] == "operator()" and "arguments" not in ordinary

    direct = tmp_path / "direct.ii"
    direct.write_text("using Fn = decltype([](auto x){return x;}); int f(Fn v){return v.operator()<int>(1);}")
    alias, function = parsed(direct)["declarations"]
    assert alias["target"]["specifiers"][0]["operand"]["type"] == "LambdaExpression"
    call = function["body"]["statements"][0]["expression"]
    assert call["callee"]["arguments"][0]["specifiers"] == ["int"]


def test_call_operator_lookup_from_declared_result():
    declarations = parsed(FIXTURES / "ClosureResults.cpp")["declarations"]
    exprs = {}
    for node in declarations:
        fn = node.get("declaration", node)
        if fn.get("body"):
            exprs[fn["name"]] = fn["body"]["statements"][0]["expression"]
    factory = exprs["invoke"]["callee"]["base"]
    assert factory["type"] == "CallExpression" and factory["callee"]["name"] == "make"
    indirect = exprs["indirect"]
    assert indirect["left"]["callee"]["operator"] == "." and indirect["right"]["callee"]["operator"] == "->"
    members = exprs["member"]["callee"]["base"]["callee"]
    assert members["member"] == "get" and members["base"]["name"] == "f"
    overload = exprs["overload"]
    assert overload["left"]["callee"]["arguments"][0]["specifiers"] == ["int"]
    assert "arguments" not in overload["right"]["callee"]
    assert exprs["same_result"]["callee"]["base"]["callee"]["name"] == "choose"
    assert exprs["extra"]["left"]["left"]["callee"]["base"]["arguments"] == []
    for name in ("explicit_args", "reversed"):
        call = exprs[name]["left"] if name == "explicit_args" else exprs[name]
        assert call["callee"]["base"]["callee"]["arguments"][0]["specifiers"] == ["int"]
    assert exprs["qualified"]["callee"]["base"]["callee"]["member"] == "Factory::get"
    assert exprs["expanded"]["callee"]["base"]["arguments"][1]["type"] == "PackExpansion"


def test_closure_operator_on_constructed_and_cast_receivers(tmp_path):
    calls = {n["name"]: n["body"]["statements"][0]["expression"] for n in
             parsed(FIXTURES / "ClosureTemporaries.cpp")["declarations"] if n["type"] == "FunctionDeclaration"}
    for call in calls.values():
        assert call["callee"]["member"] == "operator()"
        assert call["callee"]["arguments"][0]["specifiers"] == ["int"]
    assert calls["braced"]["callee"]["base"]["initializer"]["type"] == "InitializerList"
    assert calls["parens"]["callee"]["base"]["initializer"]["values"] == []
    assert calls["copied"]["callee"]["base"]["initializer"]["values"][0]["name"] == "f"
    for name, cast, pointer in [("ref", "static_cast", "&"), ("ptr", "const_cast", "*"), ("cstyle", "c-style", "&")]:
        base = calls[name]["callee"]["base"]
        if name == "cstyle":
            base = base["expression"]
        assert base["cast"] == cast and base["target"]["indirections"] == [pointer]

    direct = tmp_path / "temporary.ii"
    direct.write_text("using Fn = decltype([](auto x){return x;}); int f(){return Fn{}.operator()<int>(12);}")
    alias, fn = parsed(direct)["declarations"]
    assert alias["target"]["specifiers"][0]["operand"]["type"] == "LambdaExpression"
    assert fn["body"]["statements"][0]["expression"]["callee"]["base"]["target"]["name"] == "Fn"


def test_template_member_lookup_after_subscript():
    expressions = {n["name"]: n["body"]["statements"][-1]["expression"]
                   for n in parsed(FIXTURES / "SubscriptReceivers.cpp")["declarations"]
                   if n["type"] == "FunctionDeclaration"}
    for name, expression in expressions.items():
        member = expression["callee"]
        assert member["template"] is False and member["base"]["type"] == "SubscriptExpression"
        assert member["member"] == ("read" if name in {"cells", "named_array", "entry", "inline_record", "from_typedef"} else "operator()")
    assert expressions["swapped"]["callee"]["base"]["index"]["name"] == "p"
    for name in ("matrix", "cells", "chained"):
        assert expressions[name]["callee"]["base"]["base"]["type"] == "SubscriptExpression"


def test_allocated_template_receivers():
    decls = parsed(FIXTURES / "AllocatedReceivers.cpp")["declarations"]
    expressions = {n["name"]: n["body"]["statements"][-1]["expression"] for n in decls if n["type"] == "FunctionDeclaration"}
    for call in expressions.values():
        assert call["callee"]["template"] is False and len(call["callee"]["arguments"]) == 1
    scalar = expressions["scalar"]["callee"]
    assert scalar["operator"] == "->" and scalar["base"]["expression"]["dimensions"] == []
    matrix = expressions["matrix"]["callee"]["base"]["base"]["base"]["expression"]
    assert [dim["raw"] for dim in matrix["dimensions"]] == ["2", "3"]
    row = expressions["named_row"]["callee"]["base"]["base"]["expression"]
    assert row["dimensions"] == [] and row["allocatedType"]["specifiers"][0]["name"] == "Row"
    parenthesized = expressions["parenthesized"]["callee"]["base"]["base"]["expression"]
    assert parenthesized["parenthesizedType"] and parenthesized["allocatedType"]["declarator"][0]["size"]["raw"] == "2"
    assert expressions["record"]["callee"]["member"] == "read"


def test_conditional_template_receivers():
    decls = parsed(FIXTURES / "ConditionalReceivers.cpp")["declarations"]
    calls = {}
    for decl in decls:
        fn = decl.get("declaration", decl)
        if fn.get("body"):
            calls[fn["name"]] = fn["body"]["statements"][0]["expression"]["callee"]
    for name, call in calls.items():
        conditional = call["base"]["expression"]
        assert conditional["type"] == "ConditionalExpression"
        assert call["operator"] == ("->" if name in {"null_left", "zero_right", "decay", "nested", "inherited_ptr"} else ".")
        assert call["template"] is (name == "dependent")
    assert calls["null_left"]["base"]["expression"]["then"]["raw"] == "nullptr"
    assert calls["zero_right"]["base"]["expression"]["else"]["raw"] == "0x0'0ULL"
    assert calls["throws"]["base"]["expression"]["then"]["expression"]["type"] == "ThrowExpression"
    assert calls["inherited"]["member"] == "get" and calls["inherited"]["arguments"][0]["specifiers"] == ["long"]


def test_comma_template_receivers():
    declarations = parsed(FIXTURES / "CommaReceivers.cpp")["declarations"]
    functions = [n for n in declarations if n["type"] == "FunctionDeclaration" and n["name"] != "discard"]
    for namespace in (n for n in declarations if n["type"] == "NamespaceDefinition"):
        functions.extend(n for n in namespace["declarations"] if n.get("name") in {"fallback", "run"})
    for n in functions:
        member = n["body"]["statements"][0]["expression"]["callee"]
        comma = member["base"]["expression"]
        assert comma["type"] == "CommaExpression" and member["member"] == "operator()"
        assert member["operator"] == ("->" if n["name"] in {"pointer", "nonmember", "run"} else ".")
        if n["name"] == "hidden":
            assert comma["right"]["name"] == "value"
        if n["name"] == "nested":
            assert comma["right"]["expression"]["type"] == "CommaExpression"


def test_assignment_template_receivers():
    decls = parsed(FIXTURES / "AssignmentReceivers.cpp")["declarations"]
    expressions = {n["name"]: n["body"]["statements"][0]["expression"] for n in decls if n["type"] == "FunctionDeclaration"}
    for name, op in [("assign", "="), ("advance", "+="), ("retreat", "-="), ("divide", "/="),
                     ("modulo", "%="), ("right", ">>="), ("left", "<<="), ("mask", "&="), ("toggle", "^="), ("adl", "|=")]:
        callee = expressions[name]["callee"]
        assert callee["base"]["expression"]["operator"] == op and callee["member"] == "operator()"
    member = expressions["member"]
    assert member["left"]["callee"]["operator"] == "." and member["right"]["callee"]["operator"] == "->"
    nested = expressions["chained"]["callee"]["base"]["expression"]
    assert nested["left"]["name"] == "a" and nested["right"]["left"]["name"] == "b"
    assert expressions["implicit_copy"]["callee"]["member"] == "read"
    assert expressions["explicit_copy"]["callee"]["member"] == "operator()"


def test_increment_receiver_fixity_and_return_type():
    decls = parsed(FIXTURES / "IncrementReceivers.cpp")["declarations"]
    functions = {n["name"]: n for n in decls if n["type"] == "FunctionDeclaration"}
    for name, operator, prefix, access in [
        ("advance", "++", True, "->"), ("retreat", "--", False, "->"),
        ("old_pointer", "++", False, "->"), ("new_pointer", "--", True, "->"),
        ("pre", "++", True, "."), ("post", "++", False, "->"),
        ("pre_free", "--", True, "."), ("post_free", "--", False, "->"), ("inherited", "++", False, "->")
    ]:
        callee = functions[name]["body"]["statements"][0]["expression"]["callee"]
        unary = callee["base"]["expression"]
        assert (unary["operator"], unary["prefix"], callee["operator"]) == (operator, prefix, access)
        assert callee["member"] == "operator()" and len(callee["arguments"]) == 1


def test_overloaded_unary_template_receivers():
    declarations = parsed(FIXTURES / "UnaryReceivers.cpp")["declarations"]
    for decl in declarations:
        if decl["type"] != "FunctionDeclaration":
            continue
        callee = decl["body"]["statements"][0]["expression"]["callee"]
        unary = callee["base"]["expression"]
        expected = {"deref": ("*", "."), "address": ("&", "->"), "positive": ("+", "."),
                    "negate": ("!", "->"), "invert": ("~", "."), "negative": ("-", "->"), "builtin": ("+", "->")}
        assert (unary["operator"], callee["operator"]) == expected[decl["name"]]
        assert unary["prefix"] and callee["arguments"][0]["specifiers"] == ["int"]


def test_additive_template_receivers():
    declarations = parsed(FIXTURES / "AdditiveReceivers.cpp")["declarations"]
    callees = {d["name"]: d["body"]["statements"][0]["expression"]["callee"]
               for d in declarations if d["type"] == "FunctionDeclaration"}
    for name, operator, access in [("item", "+", "->"), ("swapped", "+", "->"), ("minus", "-", "->"),
                                   ("member", "+", "."), ("other", "-", "->")]:
        member = callees[name]
        assert member["base"]["expression"]["operator"] == operator and member["operator"] == access
        assert member["member"] == "operator()" and member["template"] is False
    assert callees["swapped"]["base"]["expression"]["left"]["raw"] == "1"
    assert callees["distance"]["base"]["expression"]["right"]["expression"]["operator"] == "-"
    assert callees["matrix"]["base"]["type"] == "SubscriptExpression"


def test_binary_operator_result_template_calls():
    decls = parsed(FIXTURES / "BinaryOperatorReceivers.cpp")["declarations"]
    operators = set()
    for decl in decls:
        if decl["type"] != "FunctionDeclaration" or decl["name"] == "operator+":
            continue
        callee = decl["body"]["statements"][0]["expression"]["callee"]
        binary = callee["base"]["expression"]
        assert binary["type"] == "BinaryExpression" and callee["member"] == "operator()"
        operators.add(binary["operator"])
        if decl["name"] == "chained":
            assert callee["operator"] == "->" and binary["right"]["operator"] == "*"
    assert operators == set("* / % << >> & ^ | == != < > <= >= <=> && || +".split())


def test_member_pointer_template_receivers():
    declarations = parsed(FIXTURES / "MemberPointerReceivers.cpp")["declarations"]
    calls = {node["name"]: node["body"]["statements"][-1]["expression"] for node in declarations
             if node["type"] == "FunctionDeclaration"}
    for name, operator in [("read", ".*"), ("inherited", ".*"), ("pointer", "->*"), ("copied", ".*"),
                           ("indexed", ".*"), ("direct", ".*"), ("inherited_address", ".*"), ("overloaded", "->*")]:
        callee = calls[name]["callee"]
        assert callee["member"] == "operator()" and callee["template"] is False
        assert callee["base"]["expression"]["operator"] == operator
    assert calls["indexed"]["callee"]["base"]["expression"]["right"]["type"] == "SubscriptExpression"
    assert calls["direct"]["callee"]["base"]["expression"]["right"]["operator"] == "&"
    for name in ("result", "via_method", "slot"):
        method_call = calls[name]["callee"]["base"]
        assert method_call["type"] == "CallExpression" and len(method_call["arguments"]) == 1
        assert method_call["callee"]["expression"]["operator"] == "->*"
    assert calls["array"]["callee"]["base"]["type"] == "SubscriptExpression"
    assert calls["from_static"]["callee"]["operator"] == "->"
    assert calls["from_alias"]["callee"]["base"]["callee"]["expression"]["operator"] == ".*"
    assert calls["specialized_address"]["callee"]["base"]["expression"]["right"]["name"] == "pm"


def test_numeric_user_defined_suffix_boundaries(tmp_path):
    from orionparser.languages.cpp.lexer import CppSource

    by_name = {n["name"]: n["initializer"] for n in parsed(FIXTURES / "NumericSuffixes.cpp")["declarations"]
               if n["type"] == "VariableDeclaration"}
    integers = {"decimal": "12'345", "octal": "07'1", "hex": "0xA'Be", "binary": "0B10'01"}
    floating = {"fraction": ".1'25", "decimal_exp": "4'2e1", "hex_fraction": "0x1.8p1", "hex_exp": "0Xf'FP1",
                "positive": "0x1.8p+1", "negative": "0X.FP-2", "dec_fraction_exp": "3.75E-1"}
    for examples, kind, suffix in [(integers, "integer", "_num"), (floating, "floating", "_unit")]:
        for name, number in examples.items():
            assert by_name[name]["raw"] == number + suffix
            assert by_name[name]["userDefined"] == {"kind": kind, "number": number, "suffix": suffix}
    assert "userDefined" not in by_name["ordinary"] and "userDefined" not in by_name["suffix_collision"]

    path = tmp_path / "unicode.ii"
    source = r'constexpr long double operator""_\u03B1(long double x){return x;} auto β=0x1.8p1_α; auto γ=.5_\u03B1; auto after=β;'
    path.write_text(source)
    op, beta, gamma, after = parsed(path)["declarations"]
    assert op["name"] == 'operator""_α' and beta["name"] == "β" and gamma["name"] == "γ"
    assert beta["initializer"]["userDefined"]["suffix"] == gamma["initializer"]["userDefined"]["suffix"] == "_α"
    assert gamma["initializer"]["raw"] == r".5_\u03B1" and after["initializer"]["name"] == "β"
    tokens = list(CppSource(source).tokens())
    assert all(t.lexpos < t.endlexpos and source[t.lexpos:t.endlexpos] == t.spelling for t in tokens)
    assert all(a.endlexpos <= b.lexpos for a, b in zip(tokens, tokens[1:]))


def test_concatenated_user_defined_strings(tmp_path):
    nodes = parsed(FIXTURES / "QuotedSuffixes.cpp")["declarations"]
    literals = {n["name"]: n["initializer"] for n in nodes if n["type"] == "VariableDeclaration"}
    for name, parts in [("first", ['"a"_len', '"bc"']), ("last", ['"a"', 'R"tag(b c)tag"_len']),
                        ("both", ['R"(a)"_len', '""', '"b"_len'])]:
        assert literals[name] == {"type": "StringLiteral", "parts": parts, "userDefined": {"kind": "string", "suffix": "_len"}}
    assert literals["ordinary"] == {"type": "StringLiteral", "parts": ['"a"', '"b"']}
    assert literals["character"]["userDefined"] == {"kind": "character", "suffix": "_code"}

    path = tmp_path / "unicode.ii"
    path.write_text(r'constexpr int operator""_α(const char*, unsigned long){return 1;} auto n="a"_\u03B1 "b"_α;')
    _, variable = parsed(path)["declarations"]
    assert variable["initializer"]["userDefined"]["suffix"] == "_α"
    assert variable["initializer"]["parts"] == [r'"a"_\u03B1', '"b"_α']
    assert literals["wide"]["encodingPrefix"] == "L" and literals["wide"]["userDefined"]["suffix"] == "_len"
    assert [literals[n]["encodingPrefix"] for n in ("utf8", "utf16", "utf32")] == ["u8", "u", "U"]
    assert literals["scalar"]["raw"] == r"U'\U0001F642'"
    assert literals["raw_escape"]["parts"] == [r'UR"(\uD800)"']
    assert literals["controls"]["parts"] == [r'u"\u0000"', r'"\u0041"']


def test_prefixed_character_code_units(tmp_path):
    nodes = parsed(FIXTURES / "CharacterWidths.cpp")["declarations"]
    by_name = {n["name"]: n["initializer"] for n in nodes}
    assert by_name["multiple"] == {"type": "Literal", "raw": "'ab'"}
    for name, prefix, value in [("byte", "u8", 255), ("byte_hex", "u8", 255), ("surrogate_unit", "u", 0xD800),
                                ("bmp", "u", 65535), ("plane", "U", 0x1F642), ("word", "U", 0xFFFFFFFF),
                                ("wide", "L", 0x1F642), ("newline", "u", 10), ("escaped_quote", "U", 39)]:
        assert (by_name[name]["encodingPrefix"], by_name[name]["codeUnit"]) == (prefix, value)
    path = tmp_path / "physical.ii"
    path.write_text("constexpr int operator\"\"_c(char16_t c){return c;} auto n=u'界'_c;")
    _, decl = parsed(path)["declarations"]
    assert decl["initializer"]["codeUnit"] == ord("界") and decl["initializer"]["userDefined"]["suffix"] == "_c"


def test_numeric_string_escape_width_after_concatenation():
    values = {n["name"]: n["initializer"] for n in parsed(FIXTURES / "StringEscapeWidths.cpp")["declarations"]}
    assert values["last"]["parts"] == [r'"\x100"', 'u""'] and values["last"]["encodingPrefix"] == "u"
    assert values["first"]["parts"] == ['U""', r'"\x10000"'] and values["first"]["encodingPrefix"] == "U"
    assert values["middle"]["parts"] == [r'"\400"', 'u""', r'"\xFFFF"']
    assert values["untouched"]["parts"] == [r'R"tag(\x100000000\400)tag"']
    assert values["separate"]["parts"] == [r'"\x1"', '"FF"']
    # Group termination at EOF also matters for the tokenization entry point.
    from orionparser.languages.cpp.lexer import CppSource
    from orionparser.languages.c_family import CParseError
    with pytest.raises(CParseError, match="line 1, column 2"):
        list(CppSource(r'"\x100"').tokens())


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_physical_line_splices(tmp_path, newline):
    from orionparser.languages.cpp.lexer import CppSource

    splice = "\\" + newline
    path = tmp_path / "spliced.ii"
    source = (f"con{splice}stexpr int va{splice}lue = 1{splice}2;" + newline
              + f"/{splice}/ hidden {splice}still hidden" + newline
              + f'auto raw = R{splice}"tag(a{splice}b)ta{splice}g"c)tag";' + newline
              + f'auto text = "a{splice}b";' + newline)
    path.write_bytes(source.encode())
    value, raw, text = parsed(path)["declarations"]
    assert value["name"] == "value" and value["initializer"]["raw"] == "12"
    assert raw["initializer"]["parts"] == [f'R"tag(a{splice}b)ta{splice}g"c)tag"']
    assert text["initializer"]["parts"] == ['"ab"']
    tokens = list(CppSource(source).tokens())
    number, = [token for token in tokens if token.type == "NUMBER"]
    assert (number.lexpos, number.endlexpos) == (source.index("1"), source.index("2;") + 1)
    assert number.lineno == 3
    path.write_bytes((source + f"int bad = 1{splice} + ;" + newline).encode())
    result = cli(path)
    assert result.returncode and f"line {source.count(newline) + 2}, column 4:" in result.stderr


def test_inline_and_reopened_unnamed_namespaces():
    decls = parsed(FIXTURES / "UnnamedNamespaces.cpp")["declarations"]
    definition, reopening, read = decls[0]["declarations"]
    assert definition["path"] == reopening["path"] == []
    assert definition["inline"] and not reopening.get("inline")
    assert reopening["declarations"][0]["returnType"]["specifiers"][0]["name"] == "Word"
    assert read["body"]["statements"][0]["expression"]["callee"]["name"] == "next"
    lookup = next(n for n in decls if n.get("name") == "lookup")
    expr = lookup["body"]["statements"][0]["expression"]
    assert expr["left"]["operand"]["type"] == "Type"
    assert expr["right"]["operand"]["expression"]["name"] == "values::Choice"
    attributed = next(n for n in decls if n.get("path") == [{"name": "attributed", "inline": False}])["declarations"][0]
    assert attributed["path"] == [] and attributed["inline"] and attributed["attributes"][0]["items"][0]["name"] == "local"


def test_namespace_alias_targets_through_directives():
    decls = parsed(FIXTURES / "NamespaceDirectives.cpp")["declarations"]
    client = decls[1]["declarations"]
    assert [node["type"] for node in client] == ["UsingDirective", "NamespaceAlias", "VariableDeclaration"]
    assert client[1]["target"] == "detail" and client[2]["variableType"]["specifiers"][0]["name"] == "impl::Word"
    functions = {n["name"]: n for n in decls if n["type"] == "FunctionDeclaration"}
    assert functions["nearest"]["returnType"]["specifiers"][0]["name"] == "direct_first::selected::Unique"
    assert functions["by_cycle"]["returnType"]["specifiers"][0]["name"] == "through_inline::Value"
    assert functions["shadow"]["body"]["statements"][1]["target"] == "lib"


def test_qualified_types_follow_using_directives():
    decls = parsed(FIXTURES / "ImportedTypes.cpp")["declarations"]
    names = {d.get("name"): d for d in decls}
    assert names["read"]["returnType"]["specifiers"][0]["name"] == "client::detail::Word"
    assert names["via_diamond"]["returnType"]["specifiers"][0]["name"] == "diamond::Box::Item"
    assert names["common"]["parameters"][0]["parameterType"]["specifiers"][0]["name"] == "together::Count"
    assert names["selected"]["body"]["statements"][0]["expression"]["operand"]["type"] == "ParenthesizedExpression"
    assert names["direct_shadow"]["body"]["statements"][0]["expression"]["operand"]["expression"]["name"] == "local_only::Entry"
    nearer, = decls[-1]["declarations"][1]["declarations"][1:2]
    assert nearer["body"]["statements"][0]["expression"]["operand"]["type"] == "Type"


def test_builtin_alias_chain_identity():
    left, right, merged, plain, readonly = parsed(FIXTURES / "AliasChains.cpp")["declarations"]
    targets = {n["name"]: n["target"] for n in left["declarations"]}
    assert targets["Handle"]["specifiers"] == ["const", {"type": "TypeName", "name": "P"}]
    assert targets["Read"]["indirections"] == ["*"]
    assert right["declarations"][1]["target"]["indirections"][0]["qualifiers"] == ["const"]
    assert [n["target"] for n in merged["declarations"]] == ["left", "right"]
    assert plain["returnType"]["specifiers"][0]["name"] == "merged::Plain"
    assert readonly["parameters"][0]["parameterType"]["specifiers"][0]["name"] == "merged::Reference"


def test_array_alias_identity():
    left, right, _, cell, borrow, read = parsed(FIXTURES / "ArrayAliasIdentity.cpp")["declarations"]
    aliases = {d["name"]: d["target"] for d in right["declarations"]}
    assert [op["size"]["raw"] for op in aliases["Matrix"]["declarator"]] == ["2", "4"]
    assert [op["type"] for op in aliases["RowPtr"]["declarator"]] == ["PointerOperator", "ArrayOperator"]
    assert aliases["Slots"]["declarator"][1]["qualifiers"] == ["const"]
    pointers = next(d["target"] for d in left["declarations"] if d["name"] == "Pointers")
    assert [op["type"] for op in pointers["declarator"]] == ["ArrayOperator", "PointerOperator"]
    for function, alias in ((cell, "Matrix"), (borrow, "Row"), (read, "Slots")):
        param = function["parameters"][0]["parameterType"]
        assert param["specifiers"] == [{"type": "TypeName", "name": "view::" + alias}]
        assert param["indirections"] == ["&"]


def test_constant_array_bounds_preserve_declaration_scope():
    _, local, written, _, consume = parsed(FIXTURES / "ConstantArrayBounds.cpp")["declarations"]
    for declared, literal, name, extent in zip(local["declarations"][2:], written["declarations"],
                                                ("width", "cells"), ("2", "8"), strict=True):
        assert declared["target"]["declarator"][0]["size"] == {"type": "NameExpression", "name": name}
        assert literal["target"]["declarator"][0]["size"] == {"type": "Literal", "raw": extent}
    assert [p["parameterType"]["specifiers"][0]["name"] for p in consume["parameters"]] == ["view::Row", "view::Block"]


def test_initializer_inferred_array_bounds():
    sizes, _, _, _, accept = parsed(FIXTURES / "InferredArrayBounds.cpp")["declarations"]
    arrays = {n["name"]: n for n in sizes["declarations"] if n["type"] == "VariableDeclaration"}
    assert arrays["cube"]["dimensions"] == [None, {"type": "Literal", "raw": "2"}, {"type": "Literal", "raw": "3"}]
    assert arrays["direct"]["initializer"]["type"] == "DirectInitializer"
    assert arrays["wide"]["initializer"]["encodingPrefix"] == "u"
    read = next(n for n in sizes["declarations"] if n.get("name") == "read")
    callee = read["body"]["statements"][0]["expression"]["callee"]
    assert callee["base"]["type"] == "SubscriptExpression"
    assert (callee["operator"], callee["member"]) == ("->", "get")
    assert callee["arguments"][0]["specifiers"] == ["int"]
    assert len(accept["parameters"]) == len(arrays) == 16


def test_integral_template_arguments_keep_written_defaults():
    model, inferred, written, _, consume = parsed(FIXTURES / "IntegralTemplateArguments.cpp")["declarations"]
    forward, definition = [n for n in model["declarations"] if n.get("declaration", {}).get("name") == "Next"]
    expression = forward["parameters"][1]["default"]
    assert expression["operator"] == "+" and expression["left"]["name"] == "N"
    assert definition["parameters"][0]["default"]["raw"] == "3"
    assert "default" not in definition["parameters"][1]
    for namespace, spellings in ((inferred, []), (written, ["3", "4"])):
        alias = next(n for n in namespace["declarations"] if n["name"] == "Next")
        assert [arg["raw"] for arg in alias["target"]["specifiers"][0]["arguments"]] == spellings
    assert consume["parameters"][-1]["parameterType"]["specifiers"][0]["name"] == "both::Next"


def test_address_template_arguments_keep_declaration_spellings():
    *_, inferred, explicit_args, _, consume = parsed(FIXTURES / "AddressTemplateArguments.cpp")["declarations"]
    omitted = inferred["declarations"][0]["target"]["specifiers"][0]
    supplied = explicit_args["declarations"][0]["target"]["specifiers"][0]["arguments"]
    assert omitted["arguments"] == []
    assert supplied[0] == {"type": "NameExpression", "name": "data::pointer"}
    assert supplied[1]["operator"] == "&" and supplied[1]["operand"]["name"] == "data::item"
    assert [p["parameterType"]["specifiers"][0]["name"] for p in consume["parameters"]] == [
        "shared::T", "shared::R", "shared::Element", "shared::E", "shared::F"]


def test_function_address_defaults_and_overloads():
    *_, inferred, written, _, consume = parsed(FIXTURES / "FunctionAddressArguments.cpp")["declarations"]
    assert inferred["declarations"][0]["target"]["specifiers"][0]["arguments"] == []
    args = written["declarations"][0]["target"]["specifiers"][0]["arguments"]
    assert args[0]["operator"] == "&" and args[0]["operand"]["name"] == "ops::apply"
    assert args[1] == {"type": "NameExpression", "name": "ops::apply"}
    selected = written["declarations"][-1]["target"]["specifiers"][0]["arguments"]
    assert selected[0]["specifiers"] == ["long"] and selected[1]["operand"]["name"] == "ops::apply"
    assert [p["parameterType"]["specifiers"][0]["name"] for p in consume["parameters"]] == [
        "both::Primary", "both::Checked", "both::Getter", "both::Auto", "both::Long"]


def test_ordered_function_template_addresses():
    ds = parsed(FIXTURES / "OrderedFunctionTemplates.cpp")["declarations"]
    consume, deep = (n for n in ds if n.get("name") in ("consume", "consume_deep"))
    assert consume["parameters"][0]["parameterType"]["specifiers"][0]["name"] == "C::T"
    assert deep["parameters"][0]["parameterType"]["specifiers"][0]["name"] == "merged::U"


def test_nested_template_owner_and_partial_specialization_lookup():
    ds = parsed(FIXTURES / "ContextAudit.cpp")["declarations"]
    nested = [n["declaration"]["declaration"] for n in ds if n.get("declaration", {}).get("type") == "TemplateDeclaration"]
    assert [n["name"] for n in nested] == ["Outer::Inner::Inner", "Outer::Inner::~Inner", "Outer::Inner::get"]
    for n in nested:
        assert n["owner"]["name"] == "Inner" and n["owner"]["qualifier"]["name"] == "Outer"
    packed = next(n for n in ds if n.get("name") == "packed")["body"]["statements"][0]["expression"]
    assert packed["left"]["left"]["operand"]["type"] == "ParenthesizedExpression"
    assert packed["left"]["right"]["operand"]["type"] == "Type"
    assert packed["right"]["operand"]["type"] == "Type"
