"""Tests for core AST nodes."""

from orionparser.core.nodes import Node


class TestNode:
    def test_to_dict_simple(self):
        node = Node(node_type="Name", line=1, col=0, attrs={"id": "x"})
        d = node.to_dict()
        assert d["type"] == "Name"
        assert d["line"] == 1
        assert d["id"] == "x"

    def test_to_dict_with_children(self):
        child = Node(node_type="Name", line=1, col=4, attrs={"id": "y"})
        parent = Node(node_type="Assign", line=1, col=0, children=[child])
        d = parent.to_dict()
        assert len(d["children"]) == 1
        assert d["children"][0]["type"] == "Name"

    def test_to_dict_no_children(self):
        node = Node(node_type="Pass", line=5, col=0)
        d = node.to_dict()
        assert "children" not in d
