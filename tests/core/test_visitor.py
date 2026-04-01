"""Tests for AST visitor pattern."""

from orionparser.core.nodes import Node
from orionparser.core.visitor import NodeVisitor


class TestVisitor:
    def test_dispatch_to_specific_method(self):
        visited = []

        class MyVisitor(NodeVisitor):
            def visit_FunctionDef(self, node):
                visited.append(node.attrs.get("name"))

        node = Node(node_type="FunctionDef", attrs={"name": "hello"})
        MyVisitor().visit(node)
        assert visited == ["hello"]

    def test_generic_visit_traverses_children(self):
        visited = []

        class MyVisitor(NodeVisitor):
            def visit_Name(self, node):
                visited.append(node.attrs.get("id"))

        root = Node(
            node_type="Module",
            children=[
                Node(node_type="Name", attrs={"id": "a"}),
                Node(node_type="Name", attrs={"id": "b"}),
            ],
        )
        MyVisitor().visit(root)
        assert visited == ["a", "b"]
