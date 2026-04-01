"""Call tree extraction from AST.

Walks the AST to find function/method definitions and
the calls they make, building a directed graph.
"""

from __future__ import annotations

from typing import Any

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


def extract_call_tree(ast: dict[str, Any]) -> dict[str, Any]:
    """Extract call tree from a Module AST.

    Returns a dict with:
      - functions: list of function names
      - calls: list of (caller, callee) edges
      - graph: networkx DiGraph (if networkx available)
    """
    functions: list[str] = []
    calls: list[tuple[str, str]] = []

    _walk_module(ast, functions, calls, scope="<module>")

    result: dict[str, Any] = {
        "functions": functions,
        "calls": calls,
    }

    if HAS_NETWORKX:
        g = nx.DiGraph()
        for func in functions:
            g.add_node(func, node_type="function")
        g.add_node("<module>", node_type="module")
        for caller, callee in calls:
            g.add_edge(caller, callee)
        result["graph"] = g

    return result


def _walk_module(
    node: dict[str, Any],
    functions: list[str],
    calls: list[tuple[str, str]],
    scope: str,
) -> None:
    """Recursively walk AST nodes to extract functions and calls."""
    if not isinstance(node, dict):
        return

    node_type = node.get("type", "")

    if node_type in ("FunctionDef", "AsyncFunctionDef"):
        name = node.get("name", "<anonymous>")
        functions = functions  # accumulator — we append via caller
        functions.append(name)
        # Walk function body with this function as scope
        for stmt in node.get("body", []):
            _walk_module(stmt, functions, calls, scope=name)
        return

    if node_type == "ClassDef":
        class_name = node.get("name", "")
        for stmt in node.get("body", []):
            if isinstance(stmt, dict) and stmt.get("type") in ("FunctionDef", "AsyncFunctionDef"):
                method_name = f"{class_name}.{stmt.get('name', '')}"
                functions.append(method_name)
                for s in stmt.get("body", []):
                    _walk_module(s, functions, calls, scope=method_name)
            else:
                _walk_module(stmt, functions, calls, scope=scope)
        return

    if node_type == "Call":
        callee = _resolve_callee(node.get("func", {}))
        if callee:
            calls.append((scope, callee))
        # Also walk arguments
        for arg in node.get("args", []):
            _walk_module(arg, functions, calls, scope=scope)
        return

    if node_type == "Expr":
        _walk_module(node.get("value", {}), functions, calls, scope=scope)
        return

    # Walk known container fields
    for field in ("body", "orelse", "finalbody", "handlers"):
        items = node.get(field, [])
        if isinstance(items, list):
            for item in items:
                _walk_module(item, functions, calls, scope=scope)

    # Walk expression fields
    for field in ("value", "target", "test", "left", "right", "operand",
                  "func", "iter", "exc"):
        child = node.get(field)
        if isinstance(child, dict):
            _walk_module(child, functions, calls, scope=scope)


def _resolve_callee(func_node: dict[str, Any]) -> str | None:
    """Resolve a Call's func to a string name."""
    if not isinstance(func_node, dict):
        return None
    if func_node.get("type") == "Name":
        return func_node.get("id")
    if func_node.get("type") == "Attribute":
        obj = _resolve_callee(func_node.get("value", {}))
        attr = func_node.get("attr", "")
        if obj:
            return f"{obj}.{attr}"
        return attr
    return None
