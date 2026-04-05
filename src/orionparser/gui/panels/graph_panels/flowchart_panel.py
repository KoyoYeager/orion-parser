"""Flowchart panel — JIS-style control flow diagram per function."""

from __future__ import annotations

from typing import Any

from orionparser.gui.panels.graph_panels.base_graph import BaseGraphPanel

try:
    import networkx as nx

    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

# Node type colors
_TYPE_COLORS = {
    "start": "#A9DFBF",      # green
    "end": "#F5B7B1",         # red
    "process": "#85C1E9",     # blue
    "decision": "#F9E79F",    # yellow
    "loop_start": "#D7BDE2",  # purple
    "loop_end": "#D7BDE2",    # purple
    "io": "#F5CBA7",          # orange
    "return": "#F5B7B1",      # red
}


class FlowchartPanel(BaseGraphPanel):
    """Generates a per-function flowchart from AST control flow."""

    graph_id = "flowchart"
    graph_name = "フローチャート"
    default_layout = "flowchart"

    def __init__(self) -> None:
        self._all_cfgs: dict[str, dict] = {}
        self._selected_func: str = ""

    def build_graph(self, result: Any) -> Any:
        ast = getattr(result, "ast", None)
        if ast is None:
            return None

        from orionparser.analysis.control_flow import extract_control_flow

        cf = extract_control_flow(ast)
        self._all_cfgs = cf.get("functions", {})

        if not self._all_cfgs:
            return None

        # Default to first function
        if self._selected_func not in self._all_cfgs:
            self._selected_func = next(iter(self._all_cfgs))

        return self._cfg_to_graph(self._selected_func)

    def build_for_function(self, func_name: str) -> Any:
        """Build flowchart for a specific function."""
        if func_name in self._all_cfgs:
            self._selected_func = func_name
            return self._cfg_to_graph(func_name)
        return None

    def get_function_names(self) -> list[str]:
        """Return available function names."""
        return list(self._all_cfgs.keys())

    def _cfg_to_graph(self, func_name: str) -> Any:
        if not HAS_NETWORKX or func_name not in self._all_cfgs:
            return None

        cfg = self._all_cfgs[func_name]
        g = nx.DiGraph()

        node_order: list[str] = []
        for node in cfg["nodes"]:
            nid = node["id"]
            g.add_node(nid, **node)
            node_order = node_order + [nid]

        for edge in cfg["edges"]:
            g.add_edge(edge["from"], edge["to"], label=edge.get("label", ""))

        g.graph["node_order"] = node_order
        g.graph["flowchart_func"] = func_name
        return g

    def get_node_colors(self, graph: Any) -> dict[str, str]:
        if not HAS_NETWORKX or graph is None:
            return {}
        return {
            n: _TYPE_COLORS.get(graph.nodes[n].get("type", "process"), "#85C1E9")
            for n in graph.nodes
        }

    def get_detail_text(self, node_id: str, graph: Any) -> str:
        if not HAS_NETWORKX or graph is None:
            return node_id
        data = graph.nodes.get(node_id, {})
        ntype = data.get("type", "")
        label = data.get("label", "")
        line = data.get("line", 0)

        _TYPE_NAMES = {
            "start": "開始", "end": "終了", "process": "処理",
            "decision": "判断", "loop_start": "ループ開始", "loop_end": "ループ終了",
            "io": "入出力", "return": "復帰",
        }

        lines = [_TYPE_NAMES.get(ntype, ntype)]
        if label:
            lines = lines + [f"  内容: {label}"]
        if line:
            lines = lines + [f"  行: {line}"]

        succs = list(graph.successors(node_id))
        if succs:
            for s in succs:
                edge_data = graph.edges[node_id, s]
                elabel = edge_data.get("label", "")
                slabel = graph.nodes[s].get("label", s)
                arrow = f" ({elabel})" if elabel else ""
                lines = lines + [f"  → {slabel}{arrow}"]

        return "\n".join(lines)
