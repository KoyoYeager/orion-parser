"""Interactive graph canvas — column-based hierarchy with L-shaped connectors."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QWidget,
)

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

HAS_GRAPHVIZ = shutil.which("dot") is not None

# Layout constants
COL_WIDTH = 180.0   # horizontal spacing per hierarchy level
ROW_HEIGHT = 50.0   # vertical spacing per node
NODE_W = 140.0
NODE_H = 32.0
HEADER_H = 28.0     # hierarchy header height
ARROW_SIZE = 7.0


def _mermaid_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


class _NodeItem(QGraphicsRectItem):
    """Non-draggable rounded-rect node with tooltip."""

    def __init__(self, node_id: str, label: str, x: float, y: float,
                 color: str, call_count: int = 0, tooltip: str = "") -> None:
        self.node_id = node_id
        font = QFont("Consolas", 9)
        fm_width = max(len(label) * 8 + 16, NODE_W)
        self._width = fm_width
        super().__init__(-fm_width / 2, -NODE_H / 2, fm_width, NODE_H)
        self.setPos(x, y)
        self.setBrush(QBrush(QColor(color)))

        if call_count >= 3:
            self.setPen(QPen(QColor("#C0392B"), 2.5))
        elif call_count >= 2:
            self.setPen(QPen(QColor("#E67E22"), 2.0))
        else:
            self.setPen(QPen(QColor("#3C3C3C"), 1.5))

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)

        if tooltip:
            self.setToolTip(tooltip)

        self._text_item = QGraphicsSimpleTextItem(label, self)
        self._text_item.setFont(font)
        self._text_item.setBrush(QBrush(QColor("#1E1E1E")))
        tr = self._text_item.boundingRect()
        self._text_item.setPos(-tr.width() / 2, -tr.height() / 2)

    def set_label(self, label: str) -> None:
        """Update display text."""
        self._text_item.setText(label)
        tr = self._text_item.boundingRect()
        self._text_item.setPos(-tr.width() / 2, -tr.height() / 2)


class GraphCanvas(QGraphicsView):
    """Graph visualization with column-based hierarchy layout."""

    node_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        self._scene = QGraphicsScene()
        super().__init__(self._scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._node_items: dict[str, _NodeItem] = {}
        self._graph: Any = None
        self._node_colors: dict[str, str] = {}

    # --- Public API ---

    def set_graph(
        self,
        graph: Any,
        layout: str = "tree",
        node_colors: dict[str, str] | None = None,
    ) -> None:
        if not HAS_NETWORKX or graph is None:
            return
        self._scene.clear()
        self._node_items.clear()
        self._graph = graph
        self._node_colors = node_colors or {}

        if len(graph.nodes) == 0:
            return

        if layout == "tree" or layout == "dot":
            self._render_tree_layout(graph)
        else:
            pos = self._compute_layout(graph, layout)
            for node_id in graph.nodes:
                label = self._get_label(graph, node_id)
                x, y = pos.get(node_id, (0, 0))
                color = self._node_colors.get(node_id, "#85C1E9")
                nd = graph.nodes[node_id]
                cc = nd.get("call_count", 0) if hasattr(nd, "get") else 0
                tip = nd.get("docstring", "") if hasattr(nd, "get") else ""
                item = _NodeItem(node_id, label, x, y, color, call_count=cc, tooltip=tip)
                self._scene.addItem(item)
                self._node_items[node_id] = item
            for u, v in graph.edges:
                self._add_straight_edge(u, v)

        self._scene.selectionChanged.connect(self._on_selection_changed)

    def fit_to_view(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if not rect.isEmpty():
            rect.adjust(-40, -40, 40, 40)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def clear_graph(self) -> None:
        self._scene.clear()
        self._node_items.clear()
        self._graph = None

    # --- Tree layout (column = hierarchy) ---

    def _render_tree_layout(self, graph: Any) -> None:
        """Render with columns = hierarchy levels, rows = source order."""
        # Get node order (source appearance order)
        node_order = graph.graph.get("node_order", list(graph.nodes))

        # Get depth for each node
        depths: dict[str, int] = {}
        for n in node_order:
            depths[n] = graph.nodes[n].get("depth", 0)

        max_depth = max(depths.values()) if depths else 0

        # Draw hierarchy column headers
        for d in range(max_depth + 1):
            x = d * COL_WIDTH + COL_WIDTH / 2
            y = 0
            header = self._scene.addSimpleText(f"階層 {d + 1}", QFont("Yu Gothic UI", 10, QFont.Weight.Bold))
            header.setBrush(QBrush(QColor("#0078D4")))
            hr = header.boundingRect()
            header.setPos(x - hr.width() / 2, y - hr.height() / 2)

            # Column separator line
            line_x = (d + 1) * COL_WIDTH
            if d < max_depth:
                sep = self._scene.addLine(
                    line_x, -HEADER_H, line_x, len(node_order) * ROW_HEIGHT + HEADER_H,
                    QPen(QColor("#E0E0E0"), 1, Qt.PenStyle.DashLine),
                )

        # Place nodes: x = depth * COL_WIDTH, y = order index * ROW_HEIGHT
        for row_idx, node_id in enumerate(node_order):
            depth = depths.get(node_id, 0)
            x = depth * COL_WIDTH + COL_WIDTH / 2
            y = (row_idx + 1) * ROW_HEIGHT + HEADER_H / 2

            label = self._get_label(graph, node_id)
            color = self._node_colors.get(node_id, "#85C1E9")
            nd = graph.nodes[node_id]
            cc = nd.get("call_count", 0)
            doc = nd.get("docstring", "")
            tip = f"{nd.get('func_name', node_id)}\n{doc}" if doc else ""
            item = _NodeItem(node_id, label, x, y, color, call_count=cc, tooltip=tip)
            self._scene.addItem(item)
            self._node_items[node_id] = item

        # Draw L-shaped connectors
        for u, v in graph.edges:
            self._add_l_shaped_edge(u, v)

    def _get_label(self, graph: Any, node_id: str) -> str:
        data = graph.nodes.get(node_id, {})
        return data.get("label", str(node_id))

    # --- L-shaped edge (parent right → down → child left) ---

    def _add_l_shaped_edge(self, u: str, v: str) -> None:
        src = self._node_items.get(u)
        dst = self._node_items.get(v)
        if src is None or dst is None:
            return

        # Start from right edge of parent
        sx = src.pos().x() + src._width / 2
        sy = src.pos().y()

        # End at left edge of child
        ex = dst.pos().x() - dst._width / 2
        ey = dst.pos().y()

        # L-shape: go right a bit, then down/up, then right to child
        mid_x = sx + 15  # small horizontal offset from parent

        path = QPainterPath(QPointF(sx, sy))
        path.lineTo(QPointF(mid_x, sy))     # horizontal from parent
        path.lineTo(QPointF(mid_x, ey))     # vertical
        path.lineTo(QPointF(ex, ey))         # horizontal to child

        edge_item = QGraphicsPathItem(path)
        edge_item.setPen(QPen(QColor("#666666"), 1.2))
        self._scene.addItem(edge_item)

        # Arrow at child end
        polygon = QPolygonF([
            QPointF(ex, ey),
            QPointF(ex - ARROW_SIZE, ey - ARROW_SIZE * 0.4),
            QPointF(ex - ARROW_SIZE, ey + ARROW_SIZE * 0.4),
        ])
        self._scene.addPolygon(polygon, QPen(Qt.PenStyle.NoPen), QBrush(QColor("#666666")))

    # --- Straight edge (for non-tree layouts) ---

    def _add_straight_edge(self, u: str, v: str) -> None:
        src = self._node_items.get(u)
        dst = self._node_items.get(v)
        if src is None or dst is None:
            return
        start = src.pos()
        end = dst.pos()
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1:
            return
        ux, uy = dx / length, dy / length
        s = QPointF(start.x() + ux * NODE_H / 2, start.y() + uy * NODE_H / 2)
        e = QPointF(end.x() - ux * NODE_H / 2, end.y() - uy * NODE_H / 2)
        path = QPainterPath(s)
        path.lineTo(e)
        edge_item = QGraphicsPathItem(path)
        edge_item.setPen(QPen(QColor("#666666"), 1.2))
        self._scene.addItem(edge_item)
        polygon = QPolygonF([e, QPointF(e.x() - ARROW_SIZE * ux + ARROW_SIZE * 0.4 * uy,
                                         e.y() - ARROW_SIZE * uy - ARROW_SIZE * 0.4 * ux),
                              QPointF(e.x() - ARROW_SIZE * ux - ARROW_SIZE * 0.4 * uy,
                                       e.y() - ARROW_SIZE * uy + ARROW_SIZE * 0.4 * ux)])
        self._scene.addPolygon(polygon, QPen(Qt.PenStyle.NoPen), QBrush(QColor("#666666")))

    # --- Fallback layouts ---

    @staticmethod
    def _compute_layout(graph: Any, layout: str) -> dict:
        if layout == "circular":
            return {k: (v[0] * 200, v[1] * 200) for k, v in nx.circular_layout(graph).items()}
        if layout == "kamada_kawai" and len(graph.nodes) > 1:
            return {k: (v[0] * 200, v[1] * 200) for k, v in nx.kamada_kawai_layout(graph).items()}
        return {k: (v[0] * 250, v[1] * 250) for k, v in nx.spring_layout(graph, seed=42).items()}

    # --- Export methods ---

    def _nodes_and_edges(self) -> tuple[list[str], list[tuple[str, str]]]:
        if not HAS_NETWORKX or self._graph is None:
            return [], []
        nodes = [str(n) for n in self._graph.nodes]
        edges = [(str(u), str(v)) for u, v in self._graph.edges]
        return nodes, edges

    def to_dot(self) -> str:
        if not HAS_NETWORKX or self._graph is None:
            return ""
        lines = ['digraph CallTree {']
        lines = lines + ['    rankdir=LR;']  # left-to-right for column hierarchy
        lines = lines + ['    node [shape=box, style="rounded,filled", fontname="Consolas", fontsize=10];']
        lines = lines + ['    edge [color="#555555", arrowsize=0.8];']
        for node_id in self._graph.nodes:
            label = self._get_label(self._graph, node_id).replace('"', '\\"')
            color = self._node_colors.get(node_id, "#85C1E9")
            lines = lines + [f'    "{label}" [label="{label}", fillcolor="{color}"];']
        for u, v in self._graph.edges:
            ul = self._get_label(self._graph, u).replace('"', '\\"')
            vl = self._get_label(self._graph, v).replace('"', '\\"')
            lines = lines + [f'    "{ul}" -> "{vl}";']
        lines = lines + ['}']
        return "\n".join(lines)

    def to_json(self) -> str:
        import json
        nodes, edges = self._nodes_and_edges()
        if not nodes:
            return "{}"
        node_data = []
        for n in self._graph.nodes:
            d = self._graph.nodes[n]
            node_data = node_data + [{"id": str(n), "label": d.get("label", str(n)),
                                       "depth": d.get("depth", 0), "call_count": d.get("call_count", 0),
                                       "color": self._node_colors.get(str(n), "")}]
        return json.dumps({"nodes": node_data, "edges": [{"source": u, "target": v} for u, v in edges]},
                          indent=2, ensure_ascii=False)

    def to_mermaid(self) -> str:
        nodes, edges = self._nodes_and_edges()
        if not nodes:
            return ""
        lines = ["graph LR"]
        for n in self._graph.nodes:
            label = self._get_label(self._graph, n).replace('"', "'")
            lines = lines + [f'    {_mermaid_id(str(n))}["{label}"]']
        for u, v in edges:
            lines = lines + [f"    {_mermaid_id(u)} --> {_mermaid_id(v)}"]
        return "\n".join(lines)

    def to_plantuml(self) -> str:
        nodes, edges = self._nodes_and_edges()
        if not nodes:
            return ""
        lines = ["@startuml"]
        for u, v in self._graph.edges:
            ul = self._get_label(self._graph, u)
            vl = self._get_label(self._graph, v)
            lines = lines + [f'"{ul}" --> "{vl}"']
        lines = lines + ["@enduml"]
        return "\n".join(lines)

    def to_drawio(self) -> str:
        if not HAS_NETWORKX or self._graph is None:
            return ""
        from xml.sax.saxutils import escape
        cells = []
        cell_id = 2
        node_ids_map: dict[str, int] = {}
        node_order = self._graph.graph.get("node_order", list(self._graph.nodes))
        for i, n in enumerate(node_order):
            node_ids_map[str(n)] = cell_id
            d = self._graph.nodes[n]
            depth = d.get("depth", 0)
            label = d.get("label", str(n))
            color = self._node_colors.get(str(n), "#85C1E9")
            x = depth * 200 + 20
            y = i * 60 + 40
            cells = cells + [
                f'      <mxCell id="{cell_id}" value="{escape(label)}" '
                f'style="rounded=1;fillColor={color};strokeColor=#3C3C3C;fontFamily=Consolas;" '
                f'vertex="1" parent="1">'
                f'<mxGeometry x="{x}" y="{y}" width="160" height="36" as="geometry"/>'
                f'</mxCell>'
            ]
            cell_id += 1
        for u, v in self._graph.edges:
            src = node_ids_map.get(str(u), 0)
            tgt = node_ids_map.get(str(v), 0)
            if src and tgt:
                cells = cells + [
                    f'      <mxCell id="{cell_id}" edge="1" source="{src}" target="{tgt}" parent="1">'
                    f'<mxGeometry relative="1" as="geometry"/></mxCell>'
                ]
                cell_id += 1
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<mxfile><diagram name="CallTree"><mxGraphModel>\n'
            '  <root>\n    <mxCell id="0"/>\n    <mxCell id="1" parent="0"/>\n'
            + "\n".join(cells) + "\n"
            '  </root>\n</mxGraphModel></diagram></mxfile>'
        )

    def to_xml(self) -> str:
        nodes, edges = self._nodes_and_edges()
        if not nodes:
            return ""
        from xml.sax.saxutils import escape
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<graph>", "  <nodes>"]
        for n in self._graph.nodes:
            d = self._graph.nodes[n]
            lines = lines + [f'    <node id="{escape(str(n))}" label="{escape(d.get("label", str(n)))}" '
                              f'depth="{d.get("depth", 0)}" call_count="{d.get("call_count", 0)}" '
                              f'color="{self._node_colors.get(str(n), "")}"/>']
        lines = lines + ["  </nodes>", "  <edges>"]
        for u, v in self._graph.edges:
            lines = lines + [f'    <edge source="{escape(str(u))}" target="{escape(str(v))}"/>']
        lines = lines + ["  </edges>", "</graph>"]
        return "\n".join(lines)

    def to_yaml(self) -> str:
        nodes, edges = self._nodes_and_edges()
        if not nodes:
            return ""
        lines = ["nodes:"]
        for n in self._graph.nodes:
            d = self._graph.nodes[n]
            lines = lines + [f'  - id: "{n}"', f'    label: "{d.get("label", str(n))}"',
                              f'    depth: {d.get("depth", 0)}', f'    call_count: {d.get("call_count", 0)}',
                              f'    color: "{self._node_colors.get(str(n), "")}"']
        lines = lines + ["edges:"]
        for u, v in self._graph.edges:
            lines = lines + [f'  - source: "{u}"', f'    target: "{v}"']
        return "\n".join(lines)

    def to_html(self) -> str:
        if not HAS_NETWORKX or self._graph is None:
            return ""
        from xml.sax.saxutils import escape
        node_order = self._graph.graph.get("node_order", list(self._graph.nodes))
        max_depth = max((self._graph.nodes[n].get("depth", 0) for n in node_order), default=0)

        # Header
        header_html = ""
        for d in range(max_depth + 1):
            header_html += f'<div class="col-header" style="left:{d*200+20}px;">&#x968E;&#x5C64; {d+1}</div>\n'

        node_html = ""
        for i, n in enumerate(node_order):
            d = self._graph.nodes[n]
            depth = d.get("depth", 0)
            label = d.get("label", str(n))
            color = self._node_colors.get(str(n), "#85C1E9")
            cc = d.get("call_count", 0)
            badge = f' <span class="badge">x{cc}</span>' if cc > 1 else ""
            node_html += (
                f'<div class="node" style="background:{color};top:{i*50+60}px;left:{depth*200+20}px;">'
                f'{escape(label)}{badge}</div>\n'
            )

        return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<title>OrionParser - Call Tree</title>
<style>
body {{ font-family: Consolas, monospace; margin: 20px; background: #FAFAFA; }}
h1 {{ color: #0078D4; font-size: 18px; }}
.canvas {{ position: relative; min-height: {len(node_order)*50+120}px; border: 1px solid #DDD; background: #FFF; padding: 10px; }}
.col-header {{ position: absolute; top: 10px; font-weight: bold; color: #0078D4; font-size: 13px; }}
.node {{ position: absolute; padding: 6px 14px; border: 1.5px solid #3C3C3C;
         border-radius: 5px; font-size: 12px; color: #1E1E1E; white-space: nowrap; }}
.node:hover {{ box-shadow: 0 2px 8px rgba(0,0,0,0.15); }}
.badge {{ background: #E74C3C; color: #FFF; border-radius: 8px; padding: 1px 6px; font-size: 10px; margin-left: 4px; }}
.legend {{ margin-top: 12px; font-size: 11px; color: #666; }}
.legend span {{ display: inline-block; width: 14px; height: 14px; border-radius: 3px; vertical-align: middle; margin-right: 4px; border: 1px solid #999; }}
</style></head><body>
<h1>OrionParser - Call Tree</h1>
<p class="legend">
<span style="background:#B3D9FF;"></span>階層0
<span style="background:#85C1E9;"></span>階層1
<span style="background:#82E0AA;"></span>階層2
<span style="background:#F9E79F;"></span>階層3
<span style="background:#F5CBA7;"></span>階層4
<span style="background:#F1948A;"></span>階層5
<span style="background:#D7BDE2;"></span>階層6
<span style="background:#76D7C4;"></span>階層7
<span style="background:#F7DC6F;"></span>階層8
<span style="background:#E59866;"></span>階層9
<span style="background:#7FB3D8;"></span>階層10+
| <b style="border:2px solid #E67E22;padding:0 4px;">太枠</b> = 複数箇所から呼出
</p>
<div class="canvas">{header_html}{node_html}</div>
</body></html>"""

    def export_excel(self, output_path: str) -> bool:
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
            from openpyxl.utils import get_column_letter
        except ImportError:
            return False
        if not HAS_NETWORKX or self._graph is None:
            return False
        graph = self._graph
        node_order = graph.graph.get("node_order", list(graph.nodes))
        if not node_order:
            return False
        max_depth = max((graph.nodes[n].get("depth", 0) for n in node_order), default=0)

        wb = Workbook()
        hdr_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        hdr_font = Font(name="Consolas", bold=True, color="FFFFFF", size=11)
        thin = Border(*(Side(style="thin") for _ in range(4)))
        center = Alignment(horizontal="center", vertical="center")

        def _hdr(ws, row, col, text):
            c = ws.cell(row=row, column=col, value=text)
            c.fill, c.font, c.alignment, c.border = hdr_fill, hdr_font, center, thin

        # --- Sheet 1: CallTree ---
        ws = wb.active
        ws.title = "CallTree"
        headers = ["#", "関数名", "呼び出し回数"]
        for d in range(max_depth + 1):
            headers = headers + [f"階層{d+1}"]
        for col, h in enumerate(headers, 1):
            _hdr(ws, 1, col, h)

        for i, n in enumerate(node_order):
            d = graph.nodes[n]
            row = i + 2
            depth = d.get("depth", 0)
            label = d.get("label", str(n))
            func_name = d.get("func_name", str(n))
            cc = d.get("call_count", 0)
            color_hex = self._node_colors.get(str(n), "").lstrip("#")

            ws.cell(row=row, column=1, value=i+1).border = thin
            nc = ws.cell(row=row, column=2, value=func_name)
            nc.border = thin
            nc.font = Font(name="Consolas", size=10, bold=True)
            if color_hex:
                nc.fill = PatternFill(start_color=color_hex, end_color=color_hex, fill_type="solid")

            cc_cell = ws.cell(row=row, column=3, value=cc)
            cc_cell.border = thin
            if cc >= 3:
                cc_cell.fill = PatternFill(start_color="F5B7B1", end_color="F5B7B1", fill_type="solid")
            elif cc >= 2:
                cc_cell.fill = PatternFill(start_color="F9E79F", end_color="F9E79F", fill_type="solid")

            for dd in range(max_depth + 1):
                col = 4 + dd
                cell = ws.cell(row=row, column=col, value=func_name if dd == depth else "")
                cell.border = thin
                if dd == depth:
                    cell.font = Font(name="Consolas", size=10, bold=True)
                    if color_hex:
                        cell.fill = PatternFill(start_color=color_hex, end_color=color_hex, fill_type="solid")

        ws.column_dimensions["A"].width = 5
        ws.column_dimensions["B"].width = 25
        ws.column_dimensions["C"].width = 12
        for dd in range(max_depth + 1):
            ws.column_dimensions[get_column_letter(4 + dd)].width = 22

        # --- Sheet 2: Edges ---
        edges = list(self._graph.edges)
        ws2 = wb.create_sheet("Edges")
        for col, h in enumerate(["#", "呼び出し元", "呼び出し先"], 1):
            _hdr(ws2, 1, col, h)
        for i, (u, v) in enumerate(edges):
            for col, val in enumerate([i+1, graph.nodes[u].get("label", str(u)), graph.nodes[v].get("label", str(v))], 1):
                c = ws2.cell(row=i+2, column=col, value=val)
                c.border = thin
                c.font = Font(name="Consolas", size=10)
        ws2.column_dimensions["A"].width = 5
        ws2.column_dimensions["B"].width = 30
        ws2.column_dimensions["C"].width = 30

        # --- Sheet 3: Statistics ---
        ws3 = wb.create_sheet("Statistics")
        ws3.cell(row=1, column=1, value="統計情報").font = Font(bold=True, size=14, color="2E75B6")
        stats = [("総ノード数", len(node_order)), ("総エッジ数", len(edges)), ("最大階層", max_depth + 1)]
        for i, (label, val) in enumerate(stats):
            ws3.cell(row=i+3, column=1, value=label).font = Font(bold=True)
            ws3.cell(row=i+3, column=2, value=val)

        # Color legend
        r = len(stats) + 5
        ws3.cell(row=r, column=1, value="色分けの意味").font = Font(bold=True, size=12, color="2E75B6")
        legend = [
            ("水色 #B3D9FF", "階層0 (ルート)"),
            ("青 #85C1E9", "階層1"),
            ("緑 #82E0AA", "階層2"),
            ("黄 #F9E79F", "階層3"),
            ("橙 #F5CBA7", "階層4"),
            ("桃 #F1948A", "階層5"),
            ("紫 #D7BDE2", "階層6"),
            ("翡翠 #76D7C4", "階層7"),
            ("金 #F7DC6F", "階層8"),
            ("茶 #E59866", "階層9"),
            ("鋼 #7FB3D8", "階層10+"),
            ("太枠(橙)", "2箇所から呼出"),
            ("太枠(赤)", "3箇所以上から呼出"),
        ]
        for i, (color, desc) in enumerate(legend):
            ws3.cell(row=r+1+i, column=1, value=color)
            ws3.cell(row=r+1+i, column=2, value=desc)
        ws3.column_dimensions["A"].width = 20
        ws3.column_dimensions["B"].width = 25

        try:
            wb.save(output_path)
            return True
        except Exception:
            return False

    def export_visio(self, output_path: str) -> bool:
        """Export to Visio (.vsdx) via win32com. Requires Visio + pywin32."""
        if not HAS_NETWORKX or self._graph is None:
            return False
        try:
            import win32com.client
        except ImportError:
            raise ImportError("Visioエクスポートには pywin32 が必要です。\npip install pywin32 でインストールしてください。")

        graph = self._graph
        node_order = graph.graph.get("node_order", list(graph.nodes))
        if not node_order:
            return False

        try:
            visio = win32com.client.Dispatch("Visio.Application")
            visio.Visible = False
            doc = visio.Documents.Add("")
            page = doc.Pages(1)

            shape_w = 77.5 / 25.4
            shape_h = 10.0 / 25.4
            h_indent = 10.0 / 25.4
            start_x, start_y = 1.0, 10.0
            shapes_map: dict[str, object] = {}

            for i, n in enumerate(node_order):
                d = graph.nodes[n]
                depth = d.get("depth", 0)
                label = d.get("label", str(n))
                x = start_x + depth * h_indent
                y = start_y - i * shape_h

                shape = page.DrawRectangle(x - shape_w/2, y - shape_h/2, x + shape_w/2, y + shape_h/2)
                shape.Text = label
                shape.CellsU("Char.Size").FormulaU = "10 pt"
                shape.CellsU("Para.HorzAlign").FormulaU = "1"
                shape.CellsU("VerticalAlign").FormulaU = "1"
                shape.CellsU("LineColor").FormulaU = "RGB(0,0,0)"
                shape.CellsU("LineWeight").FormulaU = "0.25 pt"

                color = self._node_colors.get(str(n), "#FFFFFF")
                rv, gv, bv = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
                shape.CellsU("FillForegnd").FormulaU = f"RGB({rv},{gv},{bv})"
                shapes_map[str(n)] = shape

            import os
            output_path = os.path.abspath(output_path)
            if not output_path.lower().endswith((".vsdx", ".vsd")):
                output_path = output_path + ".vsdx"
            doc.SaveAs(output_path)
            doc.Close()
            visio.Quit()
            return True
        except Exception as exc:
            try:
                visio.Quit()
            except Exception:
                pass
            raise RuntimeError(f"Visioエクスポートに失敗しました: {exc}") from exc

    def export_file(self, output_path: str, fmt: str = "svg") -> bool:
        """Export graph. Supported: svg,png,pdf,jpg,bmp,webp,tif,gif,eps,dot,json,mermaid,plantuml,drawio,xml,yaml,html,xlsx,vsdx"""
        _TEXT = {"dot": self.to_dot, "json": self.to_json, "mermaid": self.to_mermaid,
                 "plantuml": self.to_plantuml, "drawio": self.to_drawio,
                 "xml": self.to_xml, "yaml": self.to_yaml, "html": self.to_html}
        if fmt in _TEXT:
            text = _TEXT[fmt]()
            if not text:
                return False
            Path(output_path).write_text(text, encoding="utf-8")
            return True
        if fmt == "xlsx":
            return self.export_excel(output_path)
        if fmt == "vsdx":
            return self.export_visio(output_path)
        # Graphviz
        dot_source = self.to_dot()
        if not dot_source or not HAS_GRAPHVIZ:
            return False
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".dot", delete=False, encoding="utf-8") as f:
                f.write(dot_source)
                dot_path = f.name
            subprocess.run(["dot", f"-T{fmt}", dot_path, "-o", output_path], check=True, capture_output=True, timeout=30)
            Path(dot_path).unlink(missing_ok=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def export_png_from_scene(self, output_path: str) -> bool:
        from PySide6.QtGui import QImage
        rect = self._scene.itemsBoundingRect()
        if rect.isEmpty():
            return False
        rect.adjust(-40, -40, 40, 40)
        w, h = max(1, int(rect.width())), max(1, int(rect.height()))
        image = QImage(w, h, QImage.Format.Format_ARGB32)
        image.fill(QColor("#FFFFFF"))
        painter = QPainter()
        if not painter.begin(image):
            return False
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._scene.render(painter, source=rect)
        painter.end()
        return image.save(output_path)

    # --- Events ---

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def _on_selection_changed(self) -> None:
        for item in self._scene.selectedItems():
            if isinstance(item, _NodeItem):
                self.node_selected.emit(item.node_id)
                return
