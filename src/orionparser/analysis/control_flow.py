"""Control flow extraction from AST — builds per-function flowchart data."""

from __future__ import annotations

from typing import Any


def extract_control_flow(ast: dict[str, Any]) -> dict[str, Any]:
    """Extract control flow graphs for each function in the module."""
    result: dict[str, Any] = {"functions": {}}
    if ast is None:
        return result
    _walk_for_functions(ast.get("body", []), result, prefix="")
    return result


def _walk_for_functions(body: list, result: dict, prefix: str) -> None:
    """Recursively find all function definitions including class methods."""
    for node in body:
        if not isinstance(node, dict):
            continue
        ntype = node.get("type", "")
        if ntype in ("FunctionDef", "AsyncFunctionDef"):
            name = node.get("name", "")
            full_name = f"{prefix}.{name}" if prefix else name
            cfg = _build_cfg(full_name, node.get("body", []), node.get("docstring", ""), func_node=node)
            result["functions"][full_name] = cfg
        elif ntype == "ClassDef":
            cls_name = node.get("name", "")
            cls_prefix = f"{prefix}.{cls_name}" if prefix else cls_name
            _walk_for_functions(node.get("body", []), result, prefix=cls_prefix)


class _CfgBuilder:
    def __init__(self, func_name: str) -> None:
        self.func_name = func_name
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, str]] = []
        self._counter = 0

    def _nid(self) -> str:
        self._counter += 1
        return f"n{self._counter}"

    def add_node(self, ntype: str, label: str, line: int = 0, tooltip: str = "") -> str:
        nid = self._nid()
        display = label
        self.nodes = self.nodes + [{
            "id": nid, "type": ntype, "label": display,
            "line": line, "tooltip": tooltip or label,
        }]
        return nid

    def add_edge(self, src: str, dst: str, label: str = "") -> None:
        self.edges = self.edges + [{"from": src, "to": dst, "label": label}]

    def process_body(self, body: list[Any], entry_id: str) -> str:
        prev = entry_id
        for stmt in body:
            if not isinstance(stmt, dict):
                continue
            stype = stmt.get("type", "")
            line = stmt.get("_line", 0)

            # Skip docstrings (first Expr with string value)
            if stype == "Expr":
                inner = stmt.get("value", {})
                if isinstance(inner, dict) and inner.get("type") == "Str":
                    continue  # docstring — skip

            if stype == "If":
                prev = self._process_if(stmt, prev, line)
            elif stype == "For":
                prev = self._process_for(stmt, prev, line)
            elif stype == "While":
                prev = self._process_while(stmt, prev, line)
            elif stype == "Return":
                val = _expr(stmt.get("value"))
                label = f"return {val}" if val else "return"
                nid = self.add_node("return", label, line)
                self.add_edge(prev, nid)
                prev = nid
            elif stype == "Try":
                prev = self._process_try(stmt, prev, line)
            elif stype == "Expr":
                inner = stmt.get("value", {})
                if isinstance(inner, dict) and inner.get("type") == "Call":
                    fn = _call_name(inner)
                    args = _call_args(inner)
                    label = f"{fn}({args})"
                    nt = "io" if fn in ("print", "input") else "process"
                    nid = self.add_node(nt, label, line)
                else:
                    nid = self.add_node("process", _expr(inner), line)
                self.add_edge(prev, nid)
                prev = nid
            elif stype == "Assign":
                tgt = _expr(stmt.get("target"))
                val = _expr(stmt.get("value"))
                nid = self.add_node("process", f"{tgt} = {val}", line)
                self.add_edge(prev, nid)
                prev = nid
            elif stype == "AugAssign":
                tgt = _expr(stmt.get("target"))
                op = stmt.get("op", "+=")
                val = _expr(stmt.get("value"))
                nid = self.add_node("process", f"{tgt} {op} {val}", line)
                self.add_edge(prev, nid)
                prev = nid
            elif stype == "AnnAssign":
                tgt = _expr(stmt.get("target"))
                val = _expr(stmt.get("value"))
                label = f"{tgt} = {val}" if val else tgt
                nid = self.add_node("process", label, line)
                self.add_edge(prev, nid)
                prev = nid
            elif stype in ("Break", "Continue"):
                nid = self.add_node("process", stype.lower(), line)
                self.add_edge(prev, nid)
                prev = nid
            elif stype == "Raise":
                exc = _expr(stmt.get("exc"))
                label = f"raise {exc}" if exc else "raise"
                nid = self.add_node("process", label, line)
                self.add_edge(prev, nid)
                prev = nid
            elif stype in ("Pass", "Assert", "Delete", "Global", "Nonlocal"):
                nid = self.add_node("process", stype.lower(), line)
                self.add_edge(prev, nid)
                prev = nid
            elif stype == "With":
                prev = self._process_with(stmt, prev, line)
            elif stype in ("FunctionDef", "AsyncFunctionDef", "ClassDef"):
                # Nested definition — skip in flowchart
                continue
            else:
                nid = self.add_node("process", stype.lower() if stype else "...", line)
                self.add_edge(prev, nid)
                prev = nid
        return prev

    def _process_if(self, node: dict, prev: str, line: int) -> str:
        cond = _expr(node.get("test"))
        dec_id = self.add_node("decision", cond, line, tooltip=f"if {cond}")
        self.add_edge(prev, dec_id)

        merge_id = self._nid()
        self.nodes = self.nodes + [{"id": merge_id, "type": "merge", "label": "", "line": 0, "tooltip": ""}]

        # True branch
        true_entry = self._nid()
        self.nodes = self.nodes + [{"id": true_entry, "type": "merge", "label": "", "line": 0, "tooltip": ""}]
        self.add_edge(dec_id, true_entry, "True")
        true_body = node.get("body", [])
        true_last = self.process_body(true_body, true_entry) if true_body else true_entry
        self.add_edge(true_last, merge_id)

        # False branch
        false_entry = self._nid()
        self.nodes = self.nodes + [{"id": false_entry, "type": "merge", "label": "", "line": 0, "tooltip": ""}]
        self.add_edge(dec_id, false_entry, "False")
        false_body = node.get("orelse", [])
        false_last = self.process_body(false_body, false_entry) if false_body else false_entry
        self.add_edge(false_last, merge_id)

        return merge_id

    def _process_for(self, node: dict, prev: str, line: int) -> str:
        tgt = _expr(node.get("target"))
        iter_e = _expr(node.get("iter"))
        label = f"for {tgt} in {iter_e}"
        ls = self.add_node("loop_start", label, line, tooltip=label)
        self.add_edge(prev, ls)
        body = node.get("body", [])
        last = self.process_body(body, ls) if body else ls
        le = self.add_node("loop_end", label, line)
        self.add_edge(last, le)
        return le

    def _process_while(self, node: dict, prev: str, line: int) -> str:
        cond = _expr(node.get("test"))
        label = f"while {cond}"
        ls = self.add_node("loop_start", label, line, tooltip=label)
        self.add_edge(prev, ls)
        body = node.get("body", [])
        last = self.process_body(body, ls) if body else ls
        le = self.add_node("loop_end", label, line)
        self.add_edge(last, le)
        return le

    def _process_try(self, node: dict, prev: str, line: int) -> str:
        ts = self.add_node("process", "try", line)
        self.add_edge(prev, ts)
        body = node.get("body", [])
        last = self.process_body(body, ts) if body else ts
        merge = self._nid()
        self.nodes = self.nodes + [{"id": merge, "type": "merge", "label": "", "line": 0, "tooltip": ""}]
        self.add_edge(last, merge)
        for handler in node.get("handlers", []):
            if isinstance(handler, dict):
                h_type = _expr(handler.get("type"))
                h_name = handler.get("name", "")
                label = f"except {h_type}" if h_type else "except"
                if h_name:
                    label = f"{label} as {h_name}"
                eid = self.add_node("process", label, handler.get("_line", 0))
                self.add_edge(ts, eid)
                h_body = handler.get("body", [])
                h_last = self.process_body(h_body, eid) if h_body else eid
                self.add_edge(h_last, merge)
        fin = node.get("finalbody", [])
        if fin:
            fid = self.add_node("process", "finally", 0)
            self.add_edge(merge, fid)
            merge2 = self._nid()
            self.nodes = self.nodes + [{"id": merge2, "type": "merge", "label": "", "line": 0, "tooltip": ""}]
            last2 = self.process_body(fin, fid)
            self.add_edge(last2, merge2)
            return merge2
        return merge

    def _process_with(self, node: dict, prev: str, line: int) -> str:
        nid = self.add_node("process", "with ...", line)
        self.add_edge(prev, nid)
        body = node.get("body", [])
        return self.process_body(body, nid) if body else nid


def _build_cfg(func_name: str, body: list[Any], docstring: str = "",
               func_node: dict | None = None) -> dict[str, Any]:
    builder = _CfgBuilder(func_name)
    sig = _func_signature(func_node) if func_node else func_name
    start_label = f"開始: {sig}"
    tip = f"{sig}\n{docstring[:100]}" if docstring else sig
    start = builder.add_node("start", start_label, tooltip=tip)
    last = builder.process_body(body, start)
    end = builder.add_node("end", "終了")
    builder.add_edge(last, end)
    nodes, edges = _collapse_merges(builder.nodes, builder.edges)
    return {"nodes": nodes, "edges": edges}


def _collapse_merges(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict]]:
    merge_ids = {n["id"] for n in nodes if n["type"] == "merge"}
    if not merge_ids:
        return nodes, edges
    out_map: dict[str, str] = {}
    for e in edges:
        if e["from"] in merge_ids:
            out_map[e["from"]] = e["to"]
    new_edges: list[dict] = []
    for e in edges:
        if e["from"] in merge_ids:
            continue
        target = e["to"]
        while target in merge_ids and target in out_map:
            target = out_map[target]
        new_edges = new_edges + [{**e, "to": target}]
    new_nodes = [n for n in nodes if n["type"] != "merge"]
    return new_nodes, new_edges


def _expr(node: Any) -> str:
    """Generate a readable label from an AST expression node."""
    if node is None:
        return ""
    if not isinstance(node, dict):
        return str(node)
    t = node.get("type", "")
    if t == "Name":
        return node.get("id", "?")
    if t == "Num":
        return str(node.get("value", ""))
    if t == "Str":
        v = node.get("value", "")
        return f'"{v}"' if len(v) <= 20 else f'"{v[:17]}..."'
    if t == "Constant" or t == "NameConstant":
        v = node.get("value")
        return str(v) if v is not None else "None"
    if t == "BinOp":
        return f"{_expr(node.get('left'))} {node.get('op', '?')} {_expr(node.get('right'))}"
    if t == "Compare":
        return f"{_expr(node.get('left'))} {node.get('op', '?')} {_expr(node.get('right') or node.get('comparator'))}"
    if t == "BoolOp":
        return f"{_expr(node.get('left'))} {node.get('op', '?')} {_expr(node.get('right'))}"
    if t == "UnaryOp":
        op = node.get("op", "")
        operand = _expr(node.get("operand"))
        if op == "not":
            return f"not {operand}"
        return f"{op}{operand}"
    if t == "Call":
        return f"{_call_name(node)}({_call_args(node)})"
    if t == "Attribute":
        return f"{_expr(node.get('value'))}.{node.get('attr', '?')}"
    if t == "Subscript":
        return f"{_expr(node.get('value'))}[{_expr(node.get('slice'))}]"
    if t == "List":
        elts = node.get("elts", [])
        if not elts:
            return "[]"
        return f"[{', '.join(_expr(e) for e in elts[:3])}{'...' if len(elts) > 3 else ''}]"
    if t == "Tuple":
        elts = node.get("elts", [])
        return f"({', '.join(_expr(e) for e in elts[:3])})"
    if t == "Dict":
        keys = node.get("keys", [])
        values = node.get("values", [])
        if keys and isinstance(keys, list) and len(keys) <= 4:
            pairs = []
            for k, v in zip(keys, values):
                pairs = pairs + [f"{_expr(k)}: {_expr(v)}"]
            return "{" + ", ".join(pairs) + "}"
        return "{...}"
    if t == "FString" or t == "JoinedStr":
        return 'f"..."'
    if t == "IfExp":
        return f"{_expr(node.get('body'))} if {_expr(node.get('test'))} else {_expr(node.get('orelse'))}"
    if t == "Lambda":
        return "lambda ..."
    # Fallback
    name = node.get("name") or node.get("id") or node.get("value")
    if name is not None:
        return str(name)[:30]
    return t.lower() if t else "..."


def _call_name(node: dict) -> str:
    func = node.get("func", {})
    return _expr(func) if isinstance(func, dict) else str(func)


def _call_args(node: dict) -> str:
    parts: list[str] = []
    args = node.get("args", [])
    if isinstance(args, list):
        for a in args[:6]:
            if isinstance(a, dict) and a.get("type") == "keyword":
                # keyword argument inside args list
                key = a.get("arg", "")
                val = _expr(a.get("value"))
                parts = parts + [f"{key}={val}" if key else f"**{val}"]
            else:
                parts = parts + [_expr(a)]
        if len(args) > 6:
            parts = parts + ["..."]
    # Also check separate keywords field
    kwargs = node.get("keywords", [])
    if isinstance(kwargs, list):
        for kw in kwargs[:3]:
            if isinstance(kw, dict):
                key = kw.get("arg", "")
                val = _expr(kw.get("value"))
                parts = parts + [f"{key}={val}" if key else f"**{val}"]
    return ", ".join(parts)


def _func_signature(node: dict) -> str:
    """Build function signature string from AST FunctionDef node."""
    name = node.get("name", "?")
    params = node.get("params", [])
    if not isinstance(params, list):
        return f"{name}()"
    parts: list[str] = []
    for p in params:
        if isinstance(p, dict):
            pname = p.get("name", "?")
            default = p.get("default")
            ann = p.get("annotation")
            s = pname
            if ann:
                s = f"{s}: {_expr(ann)}"
            if default:
                s = f"{s}={_expr(default)}"
            parts = parts + [s]
        elif isinstance(p, str):
            parts = parts + [p]
    return f"{name}({', '.join(parts)})"
