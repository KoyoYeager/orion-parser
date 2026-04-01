"""Tests for data flow analysis."""

import logging

from orionparser.languages.python.parser import PythonParser
from orionparser.analysis.data_flow import extract_data_flow

logging.disable(logging.WARNING)


def _data_flow(source: str) -> dict:
    parser = PythonParser()
    ast = parser.parse(source)
    assert ast is not None
    return extract_data_flow(ast)


class TestDataFlow:
    def test_simple_assignment(self):
        df = _data_flow("x = 1\n")
        assert "<module>.x" in df["variables"]
        var = df["variables"]["<module>.x"]
        assert len(var["definitions"]) == 1

    def test_variable_usage(self):
        df = _data_flow("x = 1\ny = x\n")
        assert "<module>.x" in df["variables"]
        assert "<module>.y" in df["variables"]
        # x is used in the assignment to y
        assert len(df["variables"]["<module>.x"]["usages"]) > 0

    def test_data_flow_edge(self):
        df = _data_flow("x = 1\ny = x\n")
        # Should have flow from x to y
        assert ("<module>.x", "<module>.y", "<module>") in df["flows"]

    def test_function_params(self):
        source = "def f(a, b):\n    return a\n"
        df = _data_flow(source)
        assert "f.a" in df["variables"]
        assert "f.b" in df["variables"]
        assert len(df["variables"]["f.a"]["definitions"]) == 1

    def test_no_variables(self):
        df = _data_flow("pass\n")
        assert df["variables"] == {}
        assert df["flows"] == []

    def test_class_scope(self):
        source = (
            "class Foo:\n"
            "    def bar(self):\n"
            "        x = 1\n"
        )
        df = _data_flow(source)
        assert "<module>.Foo.bar.x" in df["variables"]
