"""Base AST node definitions.

All language-specific nodes inherit from Node.
Nodes are simple dataclasses with a `node_type` field and
child/attribute accessors for the Visitor pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    """Base AST node."""

    node_type: str
    line: int = 0
    col: int = 0
    children: list[Node] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to plain dict (for JSON output)."""
        result: dict[str, Any] = {
            "type": self.node_type,
            "line": self.line,
            "col": self.col,
        }
        if self.attrs:
            result.update(self.attrs)
        if self.children:
            result["children"] = [c.to_dict() for c in self.children]
        return result
