"""Class diagram panel — UML-style class visualization."""

from __future__ import annotations

from typing import Any

from orionparser.gui.panels.graph_panels.base_graph import BaseGraphPanel

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


class ClassDiagramPanel(BaseGraphPanel):
    """Generates a class diagram from AST."""

    graph_id = "class_diagram"
    graph_name = "クラス図"
    default_layout = "class_diagram"

    def build_graph(self, result: Any) -> Any:
        ast = getattr(result, "ast", None)
        if ast is None:
            return None

        from orionparser.analysis.class_diagram import extract_classes
        cd = extract_classes(ast)
        classes = cd.get("classes", {})
        if not classes:
            return None

        if not HAS_NETWORKX:
            return None

        g = nx.DiGraph()
        node_order: list[str] = []

        for cls_name, info in classes.items():
            # Build UML-style label
            attrs_text = "\n".join(
                f"  {a['name']}: {a['type']}" if a['type'] else f"  {a['name']}"
                for a in info["attributes"]
            )
            methods_text = "\n".join(
                f"  {m['name']}({m['params']})" + (f" -> {m['returns']}" if m['returns'] else "")
                for m in info["methods"]
            )
            label = f"{cls_name}\n{'─' * max(len(cls_name), 10)}\n{attrs_text}\n{'─' * max(len(cls_name), 10)}\n{methods_text}"

            g.add_node(cls_name, label=label, type="class",
                       class_name=cls_name, bases=info["bases"],
                       attributes=info["attributes"], methods=info["methods"],
                       docstring=info.get("docstring", ""),
                       line=info.get("line", 0))
            node_order = node_order + [cls_name]

            # Add inheritance edges
            for base in info["bases"]:
                if base not in g:
                    g.add_node(base, label=base, type="base_class",
                               class_name=base, bases=[], attributes=[], methods=[],
                               docstring="", line=0)
                    node_order = node_order + [base]
                g.add_edge(cls_name, base, label="inherits")

        g.graph["node_order"] = node_order
        return g

    def get_node_colors(self, graph: Any) -> dict[str, str]:
        if not HAS_NETWORKX or graph is None:
            return {}
        return {
            n: "#B3D9FF" if graph.nodes[n].get("type") == "base_class" else "#85C1E9"
            for n in graph.nodes
        }

    def get_detail_text(self, node_id: str, graph: Any) -> str:
        if not HAS_NETWORKX or graph is None:
            return node_id
        data = graph.nodes.get(node_id, {})
        cls_name = data.get("class_name", node_id)
        bases = data.get("bases", [])
        attrs = data.get("attributes", [])
        methods = data.get("methods", [])
        doc = data.get("docstring", "")

        lines = [f"class {cls_name}"]
        if bases:
            lines = lines + [f"  継承: {', '.join(bases)}"]
        if doc:
            lines = lines + [f"  説明: {doc[:80]}"]
        if attrs:
            lines = lines + [f"  属性 ({len(attrs)}):"]
            for a in attrs:
                t = f": {a['type']}" if a['type'] else ""
                d = f" = {a['default']}" if a['default'] else ""
                lines = lines + [f"    {a['name']}{t}{d}"]
        if methods:
            lines = lines + [f"  メソッド ({len(methods)}):"]
            for m in methods:
                ret = f" -> {m['returns']}" if m['returns'] else ""
                lines = lines + [f"    {m['name']}({m['params']}){ret}"]
        return "\n".join(lines)
