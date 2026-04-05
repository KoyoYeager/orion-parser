"""Class diagram extraction from AST."""

from __future__ import annotations

from typing import Any


def extract_classes(ast: dict[str, Any]) -> dict[str, Any]:
    """Extract class information for class diagram.

    Returns:
        {
            "classes": {
                "ClassName": {
                    "bases": ["BaseClass", ...],
                    "docstring": "...",
                    "attributes": [{"name": str, "type": str, "default": str}, ...],
                    "methods": [{"name": str, "params": str, "returns": str, "docstring": str}, ...],
                    "line": int,
                }
            }
        }
    """
    result: dict[str, Any] = {"classes": {}}
    if ast is None:
        return result

    for node in ast.get("body", []):
        if not isinstance(node, dict):
            continue
        if node.get("type") == "ClassDef":
            cls_info = _extract_class(node)
            result["classes"][cls_info["name"]] = cls_info

    return result


def _extract_class(node: dict) -> dict[str, Any]:
    """Extract a single class definition."""
    name = node.get("name", "")
    bases = _extract_bases(node.get("bases", []))
    docstring = node.get("docstring", "")
    line = node.get("_line", 0)

    attributes: list[dict[str, str]] = []
    methods: list[dict[str, str]] = []

    for stmt in node.get("body", []):
        if not isinstance(stmt, dict):
            continue
        stype = stmt.get("type", "")

        if stype in ("FunctionDef", "AsyncFunctionDef"):
            method = _extract_method(stmt)
            # Check __init__ for instance attributes
            if method["name"] == "__init__":
                attrs = _extract_init_attrs(stmt)
                attributes = attributes + attrs
            methods = methods + [method]

        elif stype == "Assign":
            attr = _extract_class_attr(stmt)
            if attr:
                attributes = attributes + [attr]

        elif stype == "AnnAssign":
            attr = _extract_annotated_attr(stmt)
            if attr:
                attributes = attributes + [attr]

    return {
        "name": name,
        "bases": bases,
        "docstring": docstring,
        "attributes": attributes,
        "methods": methods,
        "line": line,
    }


def _extract_bases(bases: list) -> list[str]:
    result: list[str] = []
    if not isinstance(bases, list):
        return result
    for b in bases:
        if isinstance(b, dict):
            if b.get("type") == "Name":
                result = result + [b.get("id", "?")]
            elif b.get("type") == "Attribute":
                result = result + [_expr(b)]
        elif isinstance(b, str):
            result = result + [b]
    return result


def _extract_method(node: dict) -> dict[str, str]:
    name = node.get("name", "")
    params = node.get("params", [])
    param_strs: list[str] = []
    for p in (params if isinstance(params, list) else []):
        if isinstance(p, dict):
            pname = p.get("name", "")
            if pname == "self":
                continue
            ann = p.get("annotation")
            default = p.get("default")
            s = pname
            if ann:
                s = f"{s}: {_expr(ann)}"
            if default:
                s = f"{s}={_expr(default)}"
            param_strs = param_strs + [s]
        elif isinstance(p, str) and p != "self":
            param_strs = param_strs + [p]

    returns = ""
    ret_ann = node.get("returns")
    if ret_ann:
        returns = _expr(ret_ann)

    docstring = node.get("docstring", "")
    decorators = node.get("decorators", [])
    prefix = ""
    if isinstance(decorators, list):
        for d in decorators:
            if isinstance(d, dict) and d.get("type") == "Name":
                dname = d.get("id", "")
                if dname == "property":
                    prefix = "@property "
                elif dname in ("staticmethod", "classmethod"):
                    prefix = f"@{dname} "

    return {
        "name": f"{prefix}{name}",
        "params": ", ".join(param_strs),
        "returns": returns,
        "docstring": docstring,
    }


def _extract_init_attrs(init_node: dict) -> list[dict[str, str]]:
    """Extract self.xxx = ... assignments from __init__."""
    attrs: list[dict[str, str]] = []
    for stmt in init_node.get("body", []):
        if not isinstance(stmt, dict):
            continue
        if stmt.get("type") == "Assign":
            target = stmt.get("target", {})
            if isinstance(target, dict) and target.get("type") == "Attribute":
                obj = target.get("value", {})
                if isinstance(obj, dict) and obj.get("id") == "self":
                    attr_name = target.get("attr", "")
                    value = _expr(stmt.get("value"))
                    attrs = attrs + [{"name": attr_name, "type": "", "default": value}]
        elif stmt.get("type") == "AnnAssign":
            target = stmt.get("target", {})
            if isinstance(target, dict) and target.get("type") == "Attribute":
                obj = target.get("value", {})
                if isinstance(obj, dict) and obj.get("id") == "self":
                    attr_name = target.get("attr", "")
                    ann = _expr(stmt.get("annotation"))
                    value = _expr(stmt.get("value"))
                    attrs = attrs + [{"name": attr_name, "type": ann, "default": value}]
    return attrs


def _extract_class_attr(stmt: dict) -> dict[str, str] | None:
    target = stmt.get("target", {})
    if isinstance(target, dict) and target.get("type") == "Name":
        name = target.get("id", "")
        value = _expr(stmt.get("value"))
        return {"name": name, "type": "", "default": value}
    return None


def _extract_annotated_attr(stmt: dict) -> dict[str, str] | None:
    target = stmt.get("target", {})
    if isinstance(target, dict) and target.get("type") == "Name":
        name = target.get("id", "")
        ann = _expr(stmt.get("annotation"))
        value = _expr(stmt.get("value"))
        return {"name": name, "type": ann, "default": value}
    return None


def _expr(node: Any) -> str:
    if node is None:
        return ""
    if not isinstance(node, dict):
        return str(node)
    t = node.get("type", "")
    if t == "Name":
        return node.get("id", "?")
    if t == "Attribute":
        return f"{_expr(node.get('value'))}.{node.get('attr', '?')}"
    if t == "Subscript":
        return f"{_expr(node.get('value'))}[{_expr(node.get('slice'))}]"
    if t == "Constant" or t == "NameConstant":
        v = node.get("value")
        return str(v) if v is not None else "None"
    if t == "Num":
        return str(node.get("value", ""))
    if t == "Str":
        v = node.get("value", "")
        return f'"{v}"' if len(v) <= 20 else f'"{v[:17]}..."'
    if t == "Tuple":
        elts = node.get("elts", [])
        return f"({', '.join(_expr(e) for e in elts)})"
    if t == "List":
        elts = node.get("elts", [])
        return f"[{', '.join(_expr(e) for e in elts)}]"
    if t == "Call":
        func = _expr(node.get("func"))
        return f"{func}(...)"
    name = node.get("name") or node.get("id") or node.get("value")
    if name is not None:
        return str(name)
    return t
