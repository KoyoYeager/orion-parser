"""Post-processing: attach docstrings to AST nodes.

A docstring is the first statement in a module/class/function body
that is a bare string expression (Expr with Str value containing
triple quotes).

After this pass, nodes gain a "docstring" key with the string content.
"""

from __future__ import annotations

from typing import Any


def attach_docstrings(ast: dict[str, Any]) -> None:
    """Attach docstrings to Module, FunctionDef, ClassDef nodes in-place."""
    # Module docstring
    _extract_docstring(ast)

    # Walk all bodies
    _walk_body(ast.get("body", []))


def _walk_body(body: list[Any]) -> None:
    """Recursively walk bodies and attach docstrings."""
    for node in body:
        if not isinstance(node, dict):
            continue

        node_type = node.get("type", "")

        if node_type in ("FunctionDef", "AsyncFunctionDef", "ClassDef"):
            _extract_docstring(node)
            _walk_body(node.get("body", []))

        # Recurse into compound statements
        for field in ("body", "orelse", "finalbody"):
            items = node.get(field, [])
            if isinstance(items, list):
                _walk_body(items)

        if node_type == "Try":
            for handler in node.get("handlers", []):
                if isinstance(handler, dict):
                    _walk_body(handler.get("body", []))


def _extract_docstring(node: dict[str, Any]) -> None:
    """Check if the first statement in body is a docstring and attach it."""
    body = node.get("body", [])
    if not body:
        return

    first = body[0]
    if not isinstance(first, dict):
        return

    if first.get("type") != "Expr":
        return

    value = first.get("value", {})
    if not isinstance(value, dict):
        return

    if value.get("type") != "Str":
        return

    raw = value.get("value", "")
    # Must be a triple-quoted string
    if not (raw.startswith('"""') or raw.startswith("'''")):
        return

    # Strip the quotes to get the content
    if raw.startswith('"""'):
        content = raw[3:-3]
    else:
        content = raw[3:-3]

    node["docstring"] = content.strip()
