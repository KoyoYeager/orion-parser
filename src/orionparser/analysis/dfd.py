"""Data Flow Diagram extraction — tracks variable definitions, usages, and flows.

Produces a graph where:
- Data stores (variables) are the central nodes
- Processes (functions/expressions that transform data) connect them
- External entities (parameters, return values, I/O) are entry/exit points
- Arrows show data flow direction
"""

from __future__ import annotations

from typing import Any


def extract_dfd(ast: dict[str, Any]) -> dict[str, Any]:
    """Extract DFD information from module AST.

    Returns:
        {
            "functions": {
                "func_name": {
                    "params": [str],
                    "returns": [str],
                    "variables": {
                        "var_name": {
                            "defined_at": [{"expr": str, "line": int}],
                            "used_at": [{"expr": str, "line": int}],
                            "passed_to": [{"func": str, "arg_pos": int}],
                        }
                    },
                    "calls": [{"func": str, "args": [str], "result_var": str, "line": int}],
                }
            },
            "cross_function_flows": [
                {"from_func": str, "from_var": str, "to_func": str, "to_param": str}
            ]
        }
    """
    result: dict[str, Any] = {"functions": {}, "cross_function_flows": []}
    if ast is None:
        return result

    _walk_module(ast.get("body", []), result)
    _compute_cross_flows(result)
    return result


def _walk_module(body: list, result: dict) -> None:
    for node in body:
        if not isinstance(node, dict):
            continue
        ntype = node.get("type", "")
        if ntype in ("FunctionDef", "AsyncFunctionDef"):
            name = node.get("name", "")
            func_info = _analyze_function(node)
            result["functions"][name] = func_info
        elif ntype == "ClassDef":
            for stmt in node.get("body", []):
                if isinstance(stmt, dict) and stmt.get("type") in ("FunctionDef", "AsyncFunctionDef"):
                    mname = f"{node.get('name', '')}.{stmt.get('name', '')}"
                    result["functions"][mname] = _analyze_function(stmt)


def _analyze_function(func_node: dict) -> dict[str, Any]:
    """Analyze a single function for data flows."""
    params = []
    for p in func_node.get("params", []):
        if isinstance(p, dict):
            pname = p.get("name", "")
            if pname and pname != "self":
                params.append(pname)
        elif isinstance(p, str) and p != "self":
            params.append(p)

    variables: dict[str, dict] = {}
    calls: list[dict] = []

    # Initialize params as defined variables
    for p in params:
        variables[p] = {"defined_at": [{"expr": "parameter", "line": 0}],
                        "used_at": [], "passed_to": []}

    _walk_body(func_node.get("body", []), variables, calls)

    # Find return variables
    returns = []
    for stmt in _flatten_body(func_node.get("body", [])):
        if isinstance(stmt, dict) and stmt.get("type") == "Return":
            ret_names = _collect_names(stmt.get("value"))
            returns = returns + ret_names

    return {"params": params, "returns": list(set(returns)),
            "variables": variables, "calls": calls}


def _walk_body(body: list, variables: dict, calls: list) -> None:
    for stmt in body:
        if not isinstance(stmt, dict):
            continue
        stype = stmt.get("type", "")
        line = stmt.get("_line", 0)

        if stype == "Assign":
            tgt = _target_name(stmt.get("target"))
            val = stmt.get("value", {})
            if tgt:
                expr = _expr_str(val)
                if tgt not in variables:
                    variables[tgt] = {"defined_at": [], "used_at": [], "passed_to": []}
                variables[tgt]["defined_at"].append({"expr": expr, "line": line})

                if isinstance(val, dict) and val.get("type") == "Call":
                    # RHS is a function call: track args only (not func name)
                    func_name = _expr_str(val.get("func"))
                    args = [_expr_str(a) for a in val.get("args", [])
                            if not (isinstance(a, dict) and a.get("type") == "keyword")]
                    calls.append({"func": func_name, "args": args, "result_var": tgt, "line": line})
                    for i, arg in enumerate(args):
                        if arg in variables:
                            variables[arg]["passed_to"].append({"func": func_name, "arg_pos": i})
                            variables[arg]["used_at"].append({"expr": f"→ {func_name}()", "line": line})
                else:
                    # RHS is an expression: track all referenced variables
                    for used in _collect_names(val):
                        if used in variables:
                            variables[used]["used_at"].append({"expr": f"→ {tgt}", "line": line})

        elif stype == "AugAssign":
            tgt = _target_name(stmt.get("target"))
            if tgt:
                val = stmt.get("value", {})
                expr = f"{tgt} {stmt.get('op', '?')} {_expr_str(val)}"
                if tgt not in variables:
                    variables[tgt] = {"defined_at": [], "used_at": [], "passed_to": []}
                variables[tgt]["defined_at"].append({"expr": expr, "line": line})

        elif stype == "Expr":
            inner = stmt.get("value", {})
            if isinstance(inner, dict) and inner.get("type") == "Call":
                func_name = _expr_str(inner.get("func"))
                args = [_expr_str(a) for a in inner.get("args", []) if not (isinstance(a, dict) and a.get("type") == "keyword")]
                calls.append({"func": func_name, "args": args, "result_var": "", "line": line})
                for i, arg in enumerate(args):
                    if arg in variables:
                        variables[arg]["passed_to"].append({"func": func_name, "arg_pos": i})

        elif stype == "Return":
            for name in _collect_names(stmt.get("value")):
                if name in variables:
                    variables[name]["used_at"].append({"expr": "return", "line": line})

        # Recurse into compound statements
        for field in ("body", "orelse", "finalbody"):
            sub = stmt.get(field, [])
            if isinstance(sub, list):
                _walk_body(sub, variables, calls)
        for handler in stmt.get("handlers", []):
            if isinstance(handler, dict):
                _walk_body(handler.get("body", []), variables, calls)


def _compute_cross_flows(result: dict) -> None:
    """Compute data flows between functions via call arguments."""
    flows = []
    funcs = result["functions"]
    for fname, finfo in funcs.items():
        for call in finfo["calls"]:
            called = call["func"]
            # Find the called function in our known functions
            if called in funcs:
                target_params = funcs[called]["params"]
                for i, arg in enumerate(call["args"]):
                    if i < len(target_params):
                        flows.append({
                            "from_func": fname, "from_var": arg,
                            "to_func": called, "to_param": target_params[i],
                        })
                # Return flow
                if call["result_var"] and funcs[called]["returns"]:
                    for ret_var in funcs[called]["returns"]:
                        flows.append({
                            "from_func": called, "from_var": ret_var,
                            "to_func": fname, "to_param": call["result_var"],
                        })
    result["cross_function_flows"] = flows


def _flatten_body(body: list) -> list:
    """Flatten nested body for return scanning."""
    result = []
    for stmt in body:
        if isinstance(stmt, dict):
            result.append(stmt)
            for field in ("body", "orelse", "finalbody"):
                sub = stmt.get(field, [])
                if isinstance(sub, list):
                    result.extend(_flatten_body(sub))
    return result


def _target_name(node: Any) -> str:
    if isinstance(node, dict):
        if node.get("type") == "Name":
            return node.get("id", "")
        if node.get("type") == "Attribute":
            obj = _target_name(node.get("value"))
            attr = node.get("attr", "")
            return f"{obj}.{attr}" if obj else attr
    return ""


def _collect_names(node: Any) -> list[str]:
    """Collect all Name references in an expression."""
    if not isinstance(node, dict):
        return []
    if node.get("type") == "Name":
        name = node.get("id", "")
        return [name] if name else []
    names: list[str] = []
    for field in ("left", "right", "operand", "value", "func", "test", "body", "orelse"):
        child = node.get(field)
        if isinstance(child, dict):
            names.extend(_collect_names(child))
    for arg in node.get("args", []):
        if isinstance(arg, dict):
            names.extend(_collect_names(arg))
    for elt in node.get("elts", []):
        if isinstance(elt, dict):
            names.extend(_collect_names(elt))
    return names


def _expr_str(node: Any) -> str:
    if node is None:
        return ""
    if not isinstance(node, dict):
        return str(node)
    t = node.get("type", "")
    if t == "Name":
        return node.get("id", "?")
    if t == "Attribute":
        return f"{_expr_str(node.get('value'))}.{node.get('attr', '?')}"
    if t == "Call":
        func = _expr_str(node.get("func"))
        args = [_expr_str(a) for a in node.get("args", [])[:3] if not (isinstance(a, dict) and a.get("type") == "keyword")]
        return f"{func}({', '.join(args)})"
    if t == "Subscript":
        return f"{_expr_str(node.get('value'))}[...]"
    if t == "Num":
        return str(node.get("value", ""))
    if t == "Str":
        v = node.get("value", "")
        return f'"{v}"' if len(v) <= 15 else f'"{v[:12]}..."'
    if t == "Constant" or t == "NameConstant":
        return str(node.get("value", ""))
    if t == "BinOp":
        return f"{_expr_str(node.get('left'))} {node.get('op', '?')} {_expr_str(node.get('right'))}"
    if t == "Compare":
        return f"{_expr_str(node.get('left'))} {node.get('op', '?')} {_expr_str(node.get('right') or node.get('comparator'))}"
    if t == "List":
        return "[...]"
    if t == "Dict":
        return "{...}"
    if t == "ListComp":
        return "[... for ...]"
    name = node.get("id") or node.get("name") or node.get("value")
    return str(name)[:20] if name else t
