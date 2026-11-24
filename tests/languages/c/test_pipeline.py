import json
from pathlib import Path
import subprocess
import sys

import pytest


def cli(path, *options):
    return subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json", *options],
                          capture_output=True, text=True)


def test_translation_unit_cli():
    result = cli(Path(__file__).with_name("sum.i"))
    assert result.returncode == 0, result.stderr
    unit = json.loads(result.stdout)
    assert unit["type"] == "TranslationUnit"
    total, main = unit["declarations"]
    assert total["type"] == main["type"] == "FunctionDefinition"
    assert total["declarator"]["declarator"]["name"] == "sum_positive"
    pointer, length = total["declarator"]["parameters"]
    assert pointer["specifiers"] == ["const", "int"]
    assert pointer["declarator"]["type"] == "PointerDeclarator"
    assert length["declarator"]["name"] == "length"
    init, loop, returned = total["body"]["items"]
    assert init["declarators"][0]["initializer"]["raw"] == "0"
    assert loop["type"] == "ForStatement" and loop["init"]["type"] == "Declaration"
    assert loop["test"]["operator"] == "<" and loop["update"]["operator"] == "++"
    branch, = loop["body"]["items"]
    assert branch["type"] == "IfStatement" and branch["test"]["left"]["type"] == "SubscriptExpression"
    addition = branch["consequent"]["expression"]
    assert addition["operator"] == "+=" and addition["right"]["operator"] == "+"
    assert addition["right"]["left"]["operator"] == "*"
    assert returned["type"] == "ReturnStatement" and returned["expression"]["name"] == "sum"
    array, _, countdown, end = main["body"]["items"]
    assert array["declarators"][0]["declarator"]["size"]["raw"] == "3"
    assert countdown["type"] == "WhileStatement" and countdown["body"]["expression"]["operator"] == "="
    call = end["expression"]
    assert call["type"] == "CallExpression" and call["callee"]["name"] == "sum_positive"
    assert [arg["name"] for arg in call["arguments"]] == ["values", "length"]


@pytest.mark.parametrize(("source", "location"), [
    ("int x;\nint y = ;", "line 2, column 9"),
    ("int f(void) {", "line 1, column 14"),
    ("int x;\n/*oops", "line 2, column 1"),
])
def test_positioned_rejection(tmp_path, source, location):
    path = tmp_path / "bad.i"
    path.write_text(source)
    result = cli(path)
    assert result.returncode and json.loads(result.stdout) is None and location in result.stderr


def test_declarator_binding(tmp_path):
    path = tmp_path / "types.i"
    path.write_text('# 1 "file.c"\nint *a[3]; int (*b)[3]; int (*callback)(int);')
    result = cli(path)
    assert result.returncode == 0, result.stderr
    a, b, callback = [n["declarators"][0]["declarator"] for n in json.loads(result.stdout)["declarations"]]
    assert (a["type"], a["declarator"]["type"]) == ("PointerDeclarator", "ArrayDeclarator")
    assert (b["type"], b["declarator"]["type"]) == ("ArrayDeclarator", "PointerDeclarator")
    assert callback["type"] == "FunctionDeclarator" and callback["declarator"]["type"] == "PointerDeclarator"


def test_typedef_shadowing_and_restoration(tmp_path):
    path = tmp_path / "scope.i"
    path.write_text(
        "typedef int T;\n"
        "int f(int n) {\n"
        "  T *outer;\n"
        "  { int T = 2; T * n; }\n"
        "  for (int T = 0; T < n; T++) if (T) continue;\n"
        "  T *after; return (T)n;\n"
        "}\n"
    )
    result = cli(path)
    assert result.returncode == 0, result.stderr
    _, function = json.loads(result.stdout)["declarations"]
    outer, block, loop, after, returned = function["body"]["items"]
    assert outer["specifiers"] == after["specifiers"] == [{"type": "TypedefName", "name": "T"}]
    multiplication = block["items"][1]["expression"]
    assert multiplication["operator"] == "*" and multiplication["left"]["name"] == "T"
    assert loop["test"]["left"]["name"] == "T"
    assert returned["expression"]["type"] == "CastExpression"


@pytest.mark.parametrize(("source", "location"), [
    ("typedef int T; int f(int T, T x);", "line 1, column 29"),
    ("int x;\r\nint y = 0x1.member;", "line 2, column 9"),
    ('int x;\rchar *s = "\\q";', "line 2, column 12"),
])
def test_scope_and_lexical_errors(tmp_path, source, location):
    path = tmp_path / "bad.i"
    path.write_bytes(source.encode())
    result = cli(path)
    assert result.returncode and json.loads(result.stdout) is None and location in result.stderr


def test_c_preprocessing_matches_translation_unit(tmp_path):
    headers = tmp_path / "include"
    headers.mkdir()
    (headers / "macros.h").write_text(
        "#ifndef MACROS_H\n#define MACROS_H\n"
        "#define JOIN(a,b) a ## b\n#define TEXT(a) #a\n"
        "#define ADD(x, ...) ((x) + (__VA_ARGS__))\n#endif\n"
    )
    source = tmp_path / "input.c"
    source.write_text(
        "#include <macros.h>\n#include <macros.h>\n"
        '#if defined(ENABLED) && FACTOR == 3\nchar *s = TEXT(two words);\n'
        "int JOIN(va,lue)(void) { return ADD(FACTOR, 2); }\n"
        "#else\n#error configuration missing\n#endif\n"
    )
    expected = tmp_path / "expanded.i"
    expected.write_text('char *s = "two words"; int value(void) { return ((3) + (2)); }')
    a = cli(source, "-I", str(headers), "-DENABLED", "-D", "FACTOR=3")
    b = cli(expected)
    assert a.returncode == b.returncode == 0, a.stderr
    assert json.loads(a.stdout) == json.loads(b.stdout)
    failure = cli(source, "-I", str(headers))
    assert failure.returncode and "configuration missing" in failure.stderr


def test_c_error_in_quoted_header(tmp_path):
    source = tmp_path / "main.c"
    source.write_text('#include "local.h"\n')
    header = tmp_path / "local.h"
    header.write_text("int valid;\nint invalid = ;\n")
    result = cli(source)
    assert result.returncode and json.loads(result.stdout) is None
    assert f"{header}:2:15:" in result.stderr


def test_function_parameter_enumerator_scope(tmp_path):
    path = tmp_path / "parameter.i"
    path.write_text(
        "typedef int T; typedef int U;\n"
        "int f(enum {T = 3} x, int (*cb)(enum {U})){ U local; return T; }\n"
        "T outside;\n"
    )
    result = cli(path)
    assert result.returncode == 0, result.stderr
    _, _, function, outside = json.loads(result.stdout)["declarations"]
    local, returned = function["body"]["items"]
    assert local["specifiers"][0]["name"] == "U"
    assert returned["expression"] == {"type": "Identifier", "name": "T"}
    assert outside["specifiers"][0]["name"] == "T"


def test_system_header_extensions_are_scoped(tmp_path):
    path = tmp_path / "markers.i"
    header = '# 1 "system.h" 1 3\nint f(int *__restrict p) __attribute__((pure));\n'
    path.write_text(header + '# 2 "main.c" 2\nint x;\n')
    result = cli(path)
    assert result.returncode == 0, result.stderr
    tree = json.loads(result.stdout)
    assert [item["spelling"] for item in tree["systemHeaderExtensions"]] == ["__restrict", "__attribute__((pure))"]
    assert [header[item["offset"]:][:len(item["spelling"])] for item in tree["systemHeaderExtensions"]] == [
        "__restrict", "__attribute__((pure))"
    ]
    path.write_text(header + '# 2 "main.c" 2\nint f(int *__restrict p);\n')
    assert cli(path).returncode != 0


def test_standard_macro_type_operands(tmp_path):
    path = tmp_path / "variadic.c"
    path.write_text(
        "#include <stdarg.h>\n#include <stddef.h>\n"
        "struct S { struct { int n; } a[2]; };\n"
        "int sum(int n, ...) { va_list ap; va_start(ap, n);\n"
        "int v = va_arg(ap, int); va_end(ap); return v + offsetof(struct S, a[1].n); }\n"
    )
    result = cli(path)
    assert result.returncode == 0, result.stderr
    function = json.loads(result.stdout)["declarations"][-1]
    read = function["body"]["items"][2]["declarators"][0]["initializer"]
    assert read["name"] == "__builtin_va_arg" and read["arguments"][1]["specifiers"] == ["int"]
    offset = function["body"]["items"][-1]["expression"]["right"]
    assert offset["name"] == "__builtin_offsetof"
    member = offset["arguments"][1]
    assert member["member"] == "n" and member["base"]["index"]["raw"] == "1"


def test_prototype_return_array_and_function_body_scopes(tmp_path):
    path = tmp_path / "scope.i"
    path.write_text(
        "typedef char T;\n"
        "int (*f(enum {T=1} p))[sizeof(T)];\n"
        "int g(enum {T=2} p){ return T; }\n"
        "T outside;\n"
    )
    result = cli(path)
    assert result.returncode == 0, result.stderr
    _, prototype, definition, outside = json.loads(result.stdout)["declarations"]
    size = prototype["declarators"][0]["declarator"]["size"]
    assert size["operand"]["specifiers"] == [{"type": "TypedefName", "name": "T"}]
    assert definition["body"]["items"][0]["expression"] == {"type": "Identifier", "name": "T"}
    assert outside["specifiers"] == [{"type": "TypedefName", "name": "T"}]


def test_identifier_list_belongs_to_its_definition(tmp_path):
    path = tmp_path / "old.i"
    path.write_text("int (*choose(n, p))(int) register int n; int (*p)(int); {return p;}")
    result = cli(path)
    assert result.returncode == 0, result.stderr
    definition, = json.loads(result.stdout)["declarations"]
    assert [decl["specifiers"] for decl in definition["parameterDeclarations"]] == [["register", "int"], ["int"]]
    path.write_text("int (*choose(n))(x) int n; {return 0;}")
    result = cli(path)
    assert result.returncode and json.loads(result.stdout) is None
    assert "line 1, column 17: identifier list outside its function definition" in result.stderr


def test_void_typedef_and_unnamed_prototypes(tmp_path):
    path = tmp_path / "void.i"
    path.write_text("typedef void V; typedef V W; int f(W){return 1;} int g(int, int (*)(int));")
    result = cli(path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["declarations"][2]["declarator"]["parameters"][0]["specifiers"][0]["name"] == "W"


def test_parameter_array_bounds_in_definitions_and_nested_prototypes(tmp_path):
    path = tmp_path / "arrays.i"
    path.write_text(
        "int f(int a[const static 2][3], int (*g)(int [*])) {return a[0][0];}\n"
        "int old(a) int a[static 3]; {return a[0];}\n"
    )
    result = cli(path)
    assert result.returncode == 0, result.stderr
    current, old = json.loads(result.stdout)["declarations"]
    array, callback = current["declarator"]["parameters"]
    outer = array["declarator"]["declarator"]
    assert outer["static"] and outer["qualifiers"] == ["const"]
    assert callback["declarator"]["parameters"][0]["declarator"]["star"]
    assert old["parameterDeclarations"][0]["declarators"][0]["declarator"]["static"]


def test_label_and_control_scopes(tmp_path):
    path = tmp_path / "jumps.i"
    path.write_text(
        "int f(int x){goto done; while(x){switch(x){default: if(x) continue; else break;}}"
        "done: return x;}\n"
        "int g(int x){switch(x){default:switch(x){default:goto done;}}done:return x;}\n"
    )
    result = cli(path)
    assert result.returncode == 0, result.stderr
    first, second = json.loads(result.stdout)["declarations"]
    assert first["body"]["items"][0]["label"] == first["body"]["items"][-1]["label"] == "done"
    switch = second["body"]["items"][0]["body"]["items"][0]["body"]
    assert switch["body"]["items"][0]["body"]["type"] == "GotoStatement"


@pytest.mark.parametrize(("invalid", "column", "valid"), [
    ("int f(int [const *]);", 18, "int f(int a[const *], int [*], int [const 3]);"),
    ("int * _Atomic (p);", 7, "int * _Atomic p; _Atomic(int *) q;"),
])
def test_c17_declarator_distinctions(tmp_path, invalid, column, valid):
    path = tmp_path / "declarations.i"
    path.write_text(invalid)
    result = cli(path)
    assert result.returncode and json.loads(result.stdout) is None
    assert f"line 1, column {column}" in result.stderr
    path.write_text(valid)
    result = cli(path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["declarations"]


def test_nested_generic_defaults_and_literal_concatenation(tmp_path):
    path = tmp_path / "generic.i"
    path.write_text(
        '_Thread_local static int x; extern _Thread_local int y;\n'
        'int f(void){return _Generic(x, default: _Generic(y, default: sizeof("a" u8"b" "c")));}'
    )
    result = cli(path)
    assert result.returncode == 0, result.stderr
    outer = json.loads(result.stdout)["declarations"][2]["body"]["items"][0]["expression"]
    inner = outer["associations"][0]["expression"]
    assert inner["associations"][0]["expression"]["operand"]["parts"] == ['"a"', 'u8"b"', '"c"']


def test_anonymous_members_and_unnamed_bitfield(tmp_path):
    path = tmp_path / "members.i"
    path.write_text("struct S { struct {int x;}; union {long y; int z;}; unsigned :2; };")
    result = cli(path)
    assert result.returncode == 0, result.stderr
    structure, union, bits = json.loads(result.stdout)["declarations"][0]["specifiers"][0]["members"]
    assert structure["specifiers"][0]["members"][0]["members"][0]["declarator"]["name"] == "x"
    assert union["specifiers"][0]["type"] == "UnionSpecifier"
    assert bits["members"][0]["declarator"] is None


def test_annex_g_imaginary_type_specifiers(tmp_path):
    source = tmp_path / "imaginary.i"
    source.write_text("float _Imaginary x; double _Imaginary y; long double _Imaginary z;\n")
    result = cli(source)
    assert result.returncode == 0, result.stderr
    declarations = json.loads(result.stdout)["declarations"]
    assert [d["specifiers"] for d in declarations] == [
        ["float", "_Imaginary"], ["double", "_Imaginary"], ["long", "double", "_Imaginary"]
    ]
