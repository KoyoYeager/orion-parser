"""Tests for call tree extraction."""

import logging

from orionparser.languages.python.parser import parse_source
from orionparser.analysis.call_tree import extract_call_tree

logging.disable(logging.WARNING)


def _call_tree(source: str) -> dict:
    ast = parse_source(source)
    assert ast is not None
    return extract_call_tree(ast)


class TestCallTree:
    def test_module_level_call(self):
        ct = _call_tree("print(x)\n")
        assert ("print" in [c[1] for c in ct["calls"]])
        assert ("<module>", "print") in ct["calls"]

    def test_function_definition(self):
        ct = _call_tree("def hello():\n    pass\n")
        assert "hello" in ct["functions"]

    def test_function_calls_function(self):
        source = (
            "def greet():\n"
            "    print(x)\n"
            "def main():\n"
            "    greet()\n"
        )
        ct = _call_tree(source)
        assert "greet" in ct["functions"]
        assert "main" in ct["functions"]
        assert ("greet", "print") in ct["calls"]
        assert ("main", "greet") in ct["calls"]

    def test_method_in_class(self):
        source = (
            "class Foo:\n"
            "    def bar(self):\n"
            "        print(x)\n"
        )
        ct = _call_tree(source)
        assert "Foo.bar" in ct["functions"]
        assert ("Foo.bar", "print") in ct["calls"]

    def test_attribute_call(self):
        ct = _call_tree("obj.method()\n")
        assert ("<module>", "obj.method") in ct["calls"]

    def test_no_functions(self):
        ct = _call_tree("x = 1\n")
        assert ct["functions"] == []
        assert ct["calls"] == []

    def test_nested_calls(self):
        ct = _call_tree("print(len(items))\n")
        calls = ct["calls"]
        assert ("<module>", "print") in calls
        assert ("<module>", "len") in calls
