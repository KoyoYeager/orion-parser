"""Data flow graph panel."""

from __future__ import annotations

from typing import Any

from orionparser.gui.panels.graph_panels.base_graph import BaseGraphPanel

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


class DataFlowPanel(BaseGraphPanel):
    """Builds a data flow graph from analysis result."""

    graph_id = "data_flow"
    graph_name = "データフロー"

    def build_graph(self, result: Any) -> Any:
        ast = getattr(result, "ast", None)
        if ast is None:
            return None

        from orionparser.analysis.data_flow import extract_data_flow

        df = extract_data_flow(ast)
        return df.get("graph")

    def get_node_colors(self, graph: Any) -> dict[str, str]:
        if not HAS_NETWORKX or graph is None:
            return {}
        colors: dict[str, str] = {}
        for node in graph.nodes:
            data = graph.nodes[node]
            defs = data.get("definitions", [])
            uses = data.get("usages", [])
            if defs and uses:
                colors[node] = "#A9DFBF"
            elif defs and not uses:
                colors[node] = "#F5B7B1"
            elif uses and not defs:
                colors[node] = "#F9E79F"
            else:
                colors[node] = "#85C1E9"
        return colors

    def get_detail_text(self, node_id: str, graph: Any) -> str:
        if not HAS_NETWORKX or graph is None:
            return node_id
        data = graph.nodes.get(node_id, {})
        lines = [node_id]
        scope = data.get("scope", "")
        if scope:
            lines = lines + [f"  スコープ: {scope}"]
        defs = data.get("definitions", [])
        lines = lines + [f"  定義: {len(defs)} 回"]
        uses = data.get("usages", [])
        lines = lines + [f"  使用: {len(uses)} 回"]
        successors = list(graph.successors(node_id))
        if successors:
            lines = lines + [f"  フロー先: {', '.join(str(s) for s in successors)}"]
        return "\n".join(lines)
