"""AST Visitor pattern.

Subclass NodeVisitor and define visit_<node_type> methods.
Unhandled node types fall through to generic_visit.
"""

from __future__ import annotations

from typing import Any

from orionparser.core.nodes import Node


class NodeVisitor:
    """Base visitor that dispatches to visit_<node_type> methods."""

    def visit(self, node: Node) -> Any:
        method_name = f"visit_{node.node_type}"
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node: Node) -> None:
        """Default: visit all children."""
        for child in node.children:
            self.visit(child)
