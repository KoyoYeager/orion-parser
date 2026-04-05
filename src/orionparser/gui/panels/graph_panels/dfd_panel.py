"""DFD panel — Data Flow Diagram with variable-centric view."""

from __future__ import annotations

from typing import Any

from orionparser.gui.panels.graph_panels.base_graph import BaseGraphPanel

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

# Node colors by type
_COLORS = {
    "external": "#B3D9FF",   # light blue - external entity (param/return)
    "datastore": "#A9DFBF",  # green - data store (variable)
    "process": "#85C1E9",    # blue - process (function call)
    "io": "#F5CBA7",         # orange - I/O
}


class DFDPanel(BaseGraphPanel):
    """Data Flow Diagram — shows how variables flow through functions."""

    graph_id = "dfd"
    graph_name = "DFD"
    default_layout = "dfd"

    def __init__(self) -> None:
        self._all_dfd: dict[str, Any] = {}
        self._selected_func: str = ""

    def build_graph(self, result: Any) -> Any:
        ast = getattr(result, "ast", None)
        if ast is None:
            return None

        from orionparser.analysis.dfd import extract_dfd
        self._all_dfd = extract_dfd(ast)

        funcs = self._all_dfd.get("functions", {})
        if not funcs:
            return None

        if self._selected_func not in funcs:
            self._selected_func = next(iter(funcs))

        return self._build_func_dfd(self._selected_func)

    def build_graph_multi(self, results: list[tuple[Any, str, str]]) -> Any:
        """Build cross-function DFD from multiple files."""
        if not HAS_NETWORKX:
            return None

        from pathlib import Path
        from orionparser.analysis.dfd import extract_dfd

        merged: dict[str, Any] = {"functions": {}, "cross_function_flows": []}
        for parse_result, source, file_path in results:
            ast = getattr(parse_result, "ast", None)
            if ast is None:
                continue
            dfd = extract_dfd(ast)
            merged["functions"].update(dfd.get("functions", {}))
            merged["cross_function_flows"].extend(dfd.get("cross_function_flows", []))

        self._all_dfd = merged
        return self._build_overview_dfd()

    def build_for_function(self, func_name: str) -> Any:
        if func_name in self._all_dfd.get("functions", {}):
            self._selected_func = func_name
            return self._build_func_dfd(func_name)
        return None

    def get_function_names(self) -> list[str]:
        return list(self._all_dfd.get("functions", {}).keys())

    def _build_func_dfd(self, func_name: str) -> Any:
        """Build DFD for a single function — shows all variables and their flows."""
        if not HAS_NETWORKX:
            return None
        funcs = self._all_dfd.get("functions", {})
        finfo = funcs.get(func_name)
        if not finfo:
            return None

        g = nx.DiGraph()
        order: list[str] = []

        params = finfo["params"]
        variables = finfo["variables"]
        calls = finfo["calls"]
        returns = finfo["returns"]

        # Add parameter nodes (external entities)
        for p in params:
            nid = f"param:{p}"
            g.add_node(nid, label=f"[入力] {p}", type="external", var_name=p)
            order.append(nid)

        # Add variable nodes (data stores)
        for vname, vinfo in variables.items():
            if vname in params:
                continue  # already added as param
            nid = f"var:{vname}"
            defs = vinfo["defined_at"]
            if defs:
                expr = defs[0]["expr"]
                label = f"{vname}\n= {expr}" if len(expr) <= 30 else f"{vname}\n= {expr[:27]}..."
            else:
                label = vname
            g.add_node(nid, label=label, type="datastore", var_name=vname,
                       definitions=defs, usages=vinfo["used_at"])
            order.append(nid)

        # Add process nodes (function calls)
        for i, call in enumerate(calls):
            nid = f"call:{i}"
            label = f"{call['func']}({', '.join(call['args'][:3])})"
            g.add_node(nid, label=label, type="process", call_info=call)
            order.append(nid)

            # Edges: args → process
            for arg in call["args"]:
                src = f"param:{arg}" if f"param:{arg}" in g else f"var:{arg}"
                if src in g:
                    g.add_edge(src, nid, label=arg)

            # Edge: process → result variable
            if call["result_var"]:
                dst = f"var:{call['result_var']}"
                if dst in g:
                    g.add_edge(nid, dst, label=call["result_var"])

        # Add return nodes
        for ret in returns:
            nid = f"return:{ret}"
            g.add_node(nid, label=f"[戻り値] {ret}", type="external", var_name=ret)
            order.append(nid)
            src = f"param:{ret}" if f"param:{ret}" in g else f"var:{ret}"
            if src in g:
                g.add_edge(src, nid, label=ret)

        # DFD rule: data flows through processes, not directly variable→variable
        # Only add variable→variable edges when there's no process in between
        # (e.g. y = x + 1 where x is used to compute y without a function call)
        for vname, vinfo in variables.items():
            for usage in vinfo["used_at"]:
                target_expr = usage["expr"]
                if target_expr.startswith("→ ") and "()" not in target_expr:
                    target_var = target_expr[2:]
                    src = f"param:{vname}" if f"param:{vname}" in g else f"var:{vname}"
                    dst = f"var:{target_var}"
                    if src in g and dst in g and not g.has_edge(src, dst):
                        g.add_edge(src, dst, label=vname)

        g.graph["node_order"] = order
        g.graph["dfd_func"] = func_name
        return g

    def _build_overview_dfd(self) -> Any:
        """Build overview DFD showing cross-function data flows."""
        if not HAS_NETWORKX:
            return None

        g = nx.DiGraph()
        order: list[str] = []
        funcs = self._all_dfd.get("functions", {})
        flows = self._all_dfd.get("cross_function_flows", [])

        # Each function as a process node
        for fname, finfo in funcs.items():
            params = ", ".join(finfo["params"][:3])
            returns = ", ".join(finfo["returns"][:3])
            label = f"{fname}\n({params})"
            if returns:
                label = f"{label}\n→ {returns}"
            g.add_node(fname, label=label, type="process", func_name=fname)
            order.append(fname)

        # Cross-function flows as edges
        for flow in flows:
            src = flow["from_func"]
            dst = flow["to_func"]
            var = flow["from_var"]
            if src in g and dst in g:
                g.add_edge(src, dst, label=var)

        g.graph["node_order"] = order
        return g

    def get_node_colors(self, graph: Any) -> dict[str, str]:
        if not HAS_NETWORKX or graph is None:
            return {}
        return {n: _COLORS.get(graph.nodes[n].get("type", "process"), "#85C1E9")
                for n in graph.nodes}

    def get_detail_text(self, node_id: str, graph: Any) -> str:
        if not HAS_NETWORKX or graph is None:
            return node_id
        data = graph.nodes.get(node_id, {})
        ntype = data.get("type", "")
        label = data.get("label", node_id)

        lines = [label]
        if ntype == "datastore":
            defs = data.get("definitions", [])
            usages = data.get("usages", [])
            if defs:
                lines.append(f"  定義 ({len(defs)}):")
                for d in defs[:5]:
                    lines.append(f"    {d['expr']}")
            if usages:
                lines.append(f"  使用 ({len(usages)}):")
                for u in usages[:5]:
                    lines.append(f"    {u['expr']}")
            # Show impact
            succs = list(graph.successors(node_id))
            if succs:
                lines.append(f"  影響先 ({len(succs)}):")
                for s in succs:
                    lines.append(f"    → {graph.nodes[s].get('label', s)}")
        elif ntype == "process":
            call = data.get("call_info", {})
            if call:
                lines.append(f"  引数: {', '.join(call.get('args', []))}")
                if call.get("result_var"):
                    lines.append(f"  結果: {call['result_var']}")

        return "\n".join(lines)
