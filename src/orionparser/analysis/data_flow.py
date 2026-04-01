"""Data flow analysis from AST.

Tracks variable definitions and usages to build a data flow graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


@dataclass
class VarInfo:
    """Information about a variable."""

    name: str
    scope: str
    definitions: list[int] = field(default_factory=list)  # line numbers
    usages: list[int] = field(default_factory=list)


def extract_data_flow(ast: dict[str, Any]) -> dict[str, Any]:
    """Extract data flow information from a Module AST.

    Returns:
      - variables: dict of var_name → VarInfo
      - flows: list of (source_var, target_var, scope) edges
      - graph: networkx DiGraph (if available)
    """
    variables: dict[str, VarInfo] = {}
    flows: list[tuple[str, str, str]] = []

    _walk(ast, variables, flows, scope="<module>")

    result: dict[str, Any] = {
        "variables": {k: {"name": v.name, "scope": v.scope,
                          "definitions": v.definitions, "usages": v.usages}
                      for k, v in variables.items()},
        "flows": flows,
    }

    if HAS_NETWORKX:
        g = nx.DiGraph()
        for key, var in variables.items():
            g.add_node(key, scope=var.scope,
                       definitions=var.definitions, usages=var.usages)
        for src, tgt, scope in flows:
            g.add_edge(src, tgt, scope=scope)
        result["graph"] = g

    return result


def _walk(
    node: dict[str, Any],
    variables: dict[str, VarInfo],
    flows: list[tuple[str, str, str]],
    scope: str,
) -> None:
    """Recursively walk AST to track variable definitions and usages."""
    if not isinstance(node, dict):
        return

    node_type = node.get("type", "")

    # --- Definitions ---
    if node_type == "Assign":
        target = node.get("target", {})
        value = node.get("value", {})
        tgt_name = _extract_name(target)
        if tgt_name:
            key = f"{scope}.{tgt_name}"
            if key not in variables:
                variables[key] = VarInfo(name=tgt_name, scope=scope)
            variables[key].definitions = variables[key].definitions + [0]

            # Track data flow from RHS names to target
            rhs_names = _collect_names(value)
            for rhs in rhs_names:
                rhs_key = f"{scope}.{rhs}"
                if rhs_key not in variables:
                    variables[rhs_key] = VarInfo(name=rhs, scope=scope)
                variables[rhs_key].usages = variables[rhs_key].usages + [0]
                flows.append((rhs_key, key, scope))
        _walk(value, variables, flows, scope=scope)
        return

    if node_type in ("FunctionDef", "AsyncFunctionDef"):
        func_name = node.get("name", "")
        func_scope = f"{scope}.{func_name}" if scope != "<module>" else func_name
        # Parameters are definitions
        for param in node.get("params", []):
            p_name = param.get("name", "")
            if p_name and not p_name.startswith("*"):
                key = f"{func_scope}.{p_name}"
                variables[key] = VarInfo(name=p_name, scope=func_scope)
                variables[key].definitions = [0]
        for stmt in node.get("body", []):
            _walk(stmt, variables, flows, scope=func_scope)
        return

    if node_type == "ClassDef":
        class_scope = f"{scope}.{node.get('name', '')}"
        for stmt in node.get("body", []):
            _walk(stmt, variables, flows, scope=class_scope)
        return

    # --- Usages ---
    if node_type == "Name":
        name = node.get("id", "")
        if name:
            key = f"{scope}.{name}"
            if key not in variables:
                variables[key] = VarInfo(name=name, scope=scope)
            variables[key].usages = variables[key].usages + [0]
        return

    # Walk children
    if node_type == "Expr":
        _walk(node.get("value", {}), variables, flows, scope=scope)
        return

    for field_name in ("body", "orelse", "finalbody", "handlers"):
        items = node.get(field_name, [])
        if isinstance(items, list):
            for item in items:
                _walk(item, variables, flows, scope=scope)

    for field_name in ("value", "target", "test", "left", "right",
                       "operand", "func", "iter", "exc"):
        child = node.get(field_name)
        if isinstance(child, dict):
            _walk(child, variables, flows, scope=scope)

    if node_type == "Call":
        for arg in node.get("args", []):
            _walk(arg, variables, flows, scope=scope)


def _extract_name(node: dict[str, Any]) -> str | None:
    """Extract simple name from a target node."""
    if isinstance(node, dict) and node.get("type") == "Name":
        return node.get("id")
    return None


def _collect_names(node: dict[str, Any]) -> list[str]:
    """Collect all Name references in an expression."""
    names: list[str] = []
    if not isinstance(node, dict):
        return names
    if node.get("type") == "Name":
        name = node.get("id")
        if name:
            names = names + [name]
    for field_name in ("left", "right", "operand", "value", "func"):
        child = node.get(field_name)
        if isinstance(child, dict):
            names = names + _collect_names(child)
    for arg in node.get("args", []):
        if isinstance(arg, dict):
            names = names + _collect_names(arg)
    return names
