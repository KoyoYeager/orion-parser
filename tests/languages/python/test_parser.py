"""Tests for Python parser."""

import logging

from orionparser.languages.python.parser import parse_source

logging.disable(logging.WARNING)


def _parse(source: str) -> dict:
    result = parse_source(source)
    assert result is not None, f"Parse returned None for: {source!r}"
    return result


class TestModuleStructure:
    def test_empty_module(self):
        result = _parse("\n")
        assert result["type"] == "Module"
        assert result["body"] == []

    def test_single_expression(self):
        result = _parse("42\n")
        assert result["type"] == "Module"
        assert len(result["body"]) == 1
        assert result["body"][0]["type"] == "Expr"

    def test_multiple_statements(self):
        result = _parse("x = 1\ny = 2\n")
        assert len(result["body"]) == 2


class TestAssignment:
    def test_simple_assign(self):
        result = _parse("x = 1\n")
        stmt = result["body"][0]
        assert stmt["type"] == "Assign"
        assert stmt["target"]["id"] == "x"

    def test_augmented_assign(self):
        result = _parse("x += 1\n")
        stmt = result["body"][0]
        assert stmt["type"] == "AugAssign"
        assert stmt["op"] == "+="

    def test_annotated_assign(self):
        result = _parse("x: int = 1\n")
        stmt = result["body"][0]
        assert stmt["type"] == "AnnAssign"
        assert stmt["annotation"]["id"] == "int"


class TestImports:
    def test_import(self):
        result = _parse("import os\n")
        stmt = result["body"][0]
        assert stmt["type"] == "Import"
        assert stmt["names"][0]["name"] == "os"

    def test_import_as(self):
        result = _parse("import numpy as np\n")
        stmt = result["body"][0]
        assert stmt["names"][0]["alias"] == "np"

    def test_from_import(self):
        result = _parse("from os import path\n")
        stmt = result["body"][0]
        assert stmt["type"] == "ImportFrom"
        assert stmt["module"] == "os"
        assert stmt["names"][0]["name"] == "path"

    def test_from_import_dotted(self):
        result = _parse("from os.path import join\n")
        stmt = result["body"][0]
        assert stmt["module"] == "os.path"

    def test_relative_import_dot(self):
        result = _parse("from . import cli\n")
        stmt = result["body"][0]
        assert stmt["type"] == "ImportFrom"
        assert stmt["module"] == "."

    def test_relative_import_dot_module(self):
        result = _parse("from .ctx import AppContext\n")
        stmt = result["body"][0]
        assert stmt["module"] == ".ctx"

    def test_relative_import_double_dot(self):
        result = _parse("from .. import base\n")
        stmt = result["body"][0]
        assert stmt["module"] == ".."

    def test_relative_import_triple_dot(self):
        result = _parse("from ...pkg import mod\n")
        stmt = result["body"][0]
        assert stmt["module"] == "...pkg"


class TestFunctionDef:
    def test_simple_function(self):
        result = _parse("def hello():\n    pass\n")
        func = result["body"][0]
        assert func["type"] == "FunctionDef"
        assert func["name"] == "hello"
        assert func["params"] == []

    def test_function_with_params(self):
        result = _parse("def add(a, b):\n    return a\n")
        func = result["body"][0]
        assert len(func["params"]) == 2
        assert func["params"][0]["name"] == "a"

    def test_function_with_return_type(self):
        result = _parse("def f() -> int:\n    pass\n")
        func = result["body"][0]
        assert func["returns"]["id"] == "int"

    def test_function_with_default(self):
        result = _parse("def f(x, y=10):\n    pass\n")
        func = result["body"][0]
        assert func["params"][1]["default"]["value"] == "10"


class TestClassDef:
    def test_simple_class(self):
        result = _parse("class Foo:\n    pass\n")
        cls = result["body"][0]
        assert cls["type"] == "ClassDef"
        assert cls["name"] == "Foo"

    def test_class_with_base(self):
        result = _parse("class Bar(Foo):\n    pass\n")
        cls = result["body"][0]
        assert len(cls["bases"]) == 1


class TestControlFlow:
    def test_if(self):
        result = _parse("if True:\n    pass\n")
        stmt = result["body"][0]
        assert stmt["type"] == "If"
        assert stmt["body"][0]["type"] == "Pass"

    def test_if_else(self):
        result = _parse("if True:\n    x = 1\nelse:\n    x = 2\n")
        stmt = result["body"][0]
        assert stmt["type"] == "If"
        assert len(stmt["orelse"]) > 0

    def test_while(self):
        result = _parse("while True:\n    break\n")
        stmt = result["body"][0]
        assert stmt["type"] == "While"

    def test_for(self):
        result = _parse("for x in items:\n    pass\n")
        stmt = result["body"][0]
        assert stmt["type"] == "For"
        assert stmt["target"]["id"] == "x"


class TestExpressions:
    def test_binary_op(self):
        result = _parse("x + y\n")
        expr = result["body"][0]["value"]
        assert expr["type"] == "BinOp"
        assert expr["op"] == "+"

    def test_comparison(self):
        result = _parse("x == y\n")
        expr = result["body"][0]["value"]
        assert expr["type"] == "Compare"

    def test_function_call(self):
        result = _parse("print(x)\n")
        expr = result["body"][0]["value"]
        assert expr["type"] == "Call"
        assert expr["func"]["id"] == "print"

    def test_attribute_access(self):
        result = _parse("obj.attr\n")
        expr = result["body"][0]["value"]
        assert expr["type"] == "Attribute"
        assert expr["attr"] == "attr"

    def test_subscript(self):
        result = _parse("x[0]\n")
        expr = result["body"][0]["value"]
        assert expr["type"] == "Subscript"

    def test_list_literal(self):
        result = _parse("[1, 2, 3]\n")
        expr = result["body"][0]["value"]
        assert expr["type"] == "List"

    def test_dict_literal(self):
        result = _parse('{"a": 1}\n')
        expr = result["body"][0]["value"]
        assert expr["type"] == "Dict"

    def test_unary_op(self):
        result = _parse("-x\n")
        expr = result["body"][0]["value"]
        assert expr["type"] == "UnaryOp"
        assert expr["op"] == "-"

    def test_boolean_op(self):
        result = _parse("x and y\n")
        expr = result["body"][0]["value"]
        assert expr["type"] == "BoolOp"


class TestKeywordStatements:
    def test_return(self):
        result = _parse("def f():\n    return 1\n")
        ret = result["body"][0]["body"][0]
        assert ret["type"] == "Return"

    def test_pass(self):
        result = _parse("pass\n")
        assert result["body"][0]["type"] == "Pass"

    def test_break(self):
        result = _parse("while True:\n    break\n")
        brk = result["body"][0]["body"][0]
        assert brk["type"] == "Break"

    def test_raise(self):
        result = _parse("raise ValueError\n")
        stmt = result["body"][0]
        assert stmt["type"] == "Raise"

    def test_assert(self):
        result = _parse("assert x\n")
        stmt = result["body"][0]
        assert stmt["type"] == "Assert"
