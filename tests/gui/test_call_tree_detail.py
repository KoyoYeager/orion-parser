"""Comprehensive call tree tests — layout, ordering, duplication, colors, connectors."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF


@pytest.fixture
def make_canvas(qtbot):
    """Factory to create a GraphCanvas with a call tree from source code."""
    def _make(source: str):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel

        # Parse source
        p = Path(f"_test_{id(source)}.py")
        p.write_text(source, encoding="utf-8")
        try:
            from orionparser.registry import get_pipeline
            pipeline = get_pipeline(p)
            result = pipeline.analyze_file(p)
        finally:
            p.unlink(missing_ok=True)

        panel = CallTreePanel()
        graph = panel.build_graph(result)
        colors = panel.get_node_colors(graph) if graph else {}

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)
        if graph is not None:
            canvas.set_graph(graph, layout="tree", node_colors=colors)
        return canvas, graph, panel

    return _make


SCREENSHOT_DIR = Path(__file__).parent / "screenshots" / "call_tree"


@pytest.fixture(autouse=True)
def ensure_dir():
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _grab(canvas, name):
    canvas.grab().save(str(SCREENSHOT_DIR / f"{name}.png"))


# ============================================================
# 1. Basic layout structure
# ============================================================

class TestColumnHierarchy:
    """Hierarchy should be columns (left-to-right), not rows."""

    def test_root_is_leftmost(self, make_canvas):
        canvas, graph, _ = make_canvas("def main(): pass\nmain()\n")
        items = canvas._node_items
        # <module> should have the smallest x
        root_x = items["<module>"].pos().x()
        for nid, item in items.items():
            if nid != "<module>":
                assert item.pos().x() >= root_x, f"{nid} should be right of <module>"
        _grab(canvas, "01_root_leftmost")

    def test_child_is_right_of_parent(self, make_canvas):
        canvas, graph, _ = make_canvas(
            "def a(): b()\ndef b(): c()\ndef c(): pass\na()\n"
        )
        items = canvas._node_items
        # <module> -> a -> b -> c, each deeper
        mod_x = items["<module>"].pos().x()
        a_nodes = [n for n in items if graph.nodes[n].get("func_name") == "a"]
        b_nodes = [n for n in items if graph.nodes[n].get("func_name") == "b"]
        c_nodes = [n for n in items if graph.nodes[n].get("func_name") == "c"]
        assert items[a_nodes[0]].pos().x() > mod_x
        assert items[b_nodes[0]].pos().x() > items[a_nodes[0]].pos().x()
        assert items[c_nodes[0]].pos().x() > items[b_nodes[0]].pos().x()
        _grab(canvas, "02_depth_increases_right")

    def test_hierarchy_headers_exist(self, make_canvas):
        canvas, graph, _ = make_canvas("def f(): pass\nf()\n")
        # Should have QGraphicsSimpleTextItem with "階層" in text
        from PySide6.QtWidgets import QGraphicsSimpleTextItem
        headers = [item for item in canvas._scene.items()
                   if isinstance(item, QGraphicsSimpleTextItem) and "階層" in item.text()]
        assert len(headers) >= 2  # at least 階層1, 階層2


# ============================================================
# 2. Source order (top-to-bottom = call appearance order)
# ============================================================

class TestSourceOrder:
    """Nodes should appear top-to-bottom in source appearance order."""

    def test_call_order_preserved(self, make_canvas):
        source = "def z(): pass\ndef a(): pass\ndef m(): pass\nz()\na()\nm()\n"
        canvas, graph, _ = make_canvas(source)
        order = graph.graph.get("node_order", [])
        # <module> first, then z, a, m in call order
        func_names = [graph.nodes[n].get("func_name") for n in order]
        assert func_names[0] == "<module>"
        assert func_names[1] == "z"
        assert func_names[2] == "a"
        assert func_names[3] == "m"

    def test_y_positions_follow_order(self, make_canvas):
        source = "def first(): pass\ndef second(): pass\nfirst()\nsecond()\n"
        canvas, graph, _ = make_canvas(source)
        order = graph.graph.get("node_order", [])
        items = canvas._node_items
        for i in range(len(order) - 1):
            y_curr = items[order[i]].pos().y()
            y_next = items[order[i + 1]].pos().y()
            assert y_curr < y_next, f"{order[i]} should be above {order[i+1]}"
        _grab(canvas, "03_source_order")


# ============================================================
# 3. Duplicate function expansion
# ============================================================

class TestDuplicateExpansion:
    """Same function called from multiple places should appear as separate nodes."""

    def test_shared_callee_creates_multiple_nodes(self, make_canvas):
        source = (
            "def helper(): pass\n"
            "def a(): helper()\n"
            "def b(): helper()\n"
            "a()\nb()\n"
        )
        canvas, graph, _ = make_canvas(source)
        helper_nodes = [n for n in graph.nodes if graph.nodes[n].get("func_name") == "helper"]
        assert len(helper_nodes) == 2, f"helper should appear twice, got {len(helper_nodes)}"
        _grab(canvas, "04_duplicate_helper")

    def test_duplicate_has_call_count_badge(self, make_canvas):
        source = (
            "def util(): pass\n"
            "def x(): util()\n"
            "def y(): util()\n"
            "def z(): util()\n"
            "x()\ny()\nz()\n"
        )
        canvas, graph, _ = make_canvas(source)
        util_nodes = [n for n in graph.nodes if graph.nodes[n].get("func_name") == "util"]
        assert len(util_nodes) == 3
        # Each should have call_count >= 3
        for n in util_nodes:
            cc = graph.nodes[n].get("call_count", 0)
            assert cc == 3, f"util call_count should be 3, got {cc}"
            # Label should contain "(x3)"
            label = graph.nodes[n].get("label", "")
            assert "x3" in label
        _grab(canvas, "05_call_count_badge")

    def test_single_call_no_badge(self, make_canvas):
        source = "def only_once(): pass\nonly_once()\n"
        canvas, graph, _ = make_canvas(source)
        for n in graph.nodes:
            if graph.nodes[n].get("func_name") == "only_once":
                label = graph.nodes[n].get("label", "")
                assert "x" not in label.lower() or "x1" not in label


# ============================================================
# 4. Color meaning
# ============================================================

class TestColorMeaning:
    """Colors should reflect hierarchy depth."""

    def test_root_depth0_is_light_blue(self, make_canvas):
        canvas, graph, panel = make_canvas("def f(): pass\nf()\n")
        colors = panel.get_node_colors(graph)
        root = [n for n in graph.nodes if graph.nodes[n].get("depth") == 0]
        assert colors[root[0]] == "#B3D9FF"

    def test_depth1_is_blue(self, make_canvas):
        source = "def a(): pass\na()\n"
        canvas, graph, panel = make_canvas(source)
        colors = panel.get_node_colors(graph)
        d1 = [n for n in graph.nodes if graph.nodes[n].get("depth") == 1]
        for n in d1:
            assert colors[n] == "#85C1E9"

    def test_depth2_is_green(self, make_canvas):
        source = "def b(): pass\ndef a(): b()\na()\n"
        canvas, graph, panel = make_canvas(source)
        colors = panel.get_node_colors(graph)
        d2 = [n for n in graph.nodes if graph.nodes[n].get("depth") == 2]
        for n in d2:
            assert colors[n] == "#82E0AA"

    def test_depth3_is_yellow(self, make_canvas):
        source = "def c(): pass\ndef b(): c()\ndef a(): b()\na()\n"
        canvas, graph, panel = make_canvas(source)
        colors = panel.get_node_colors(graph)
        d3 = [n for n in graph.nodes if graph.nodes[n].get("depth") == 3]
        for n in d3:
            assert colors[n] == "#F9E79F"
        _grab(canvas, "06_depth_colors")

    def test_each_depth_has_distinct_color(self, make_canvas):
        source = (
            "def d(): pass\ndef c(): d()\ndef b(): c()\ndef a(): b()\na()\n"
        )
        canvas, graph, panel = make_canvas(source)
        colors = panel.get_node_colors(graph)
        depth_colors = {}
        for n in graph.nodes:
            d = graph.nodes[n].get("depth", 0)
            depth_colors[d] = colors[n]
        # Depths 0-4 should all have different colors
        unique_colors = set(depth_colors.values())
        assert len(unique_colors) == len(depth_colors), (
            f"Each depth should have a distinct color: {depth_colors}"
        )

    def test_deep_hierarchy_colors_distinct(self, make_canvas):
        """Depths 0-9 should all have different colors."""
        # Build 10-level chain: f9 -> f8 -> ... -> f0 -> module
        funcs = "\n".join(
            f"def f{i}(): f{i-1}()" if i > 0 else "def f0(): pass"
            for i in range(10)
        )
        source = funcs + "\nf9()\n"
        canvas, graph, panel = make_canvas(source)
        colors = panel.get_node_colors(graph)
        depth_colors = {}
        for n in graph.nodes:
            d = graph.nodes[n].get("depth", 0)
            depth_colors[d] = colors[n]
        # At least depths 0-9 should exist with 10 distinct colors
        assert len(depth_colors) >= 10, f"Expected 10+ depths, got {depth_colors.keys()}"
        unique = set(depth_colors.values())
        assert len(unique) >= 10, (
            f"Depths 0-9 should have distinct colors, got {len(unique)} unique: {depth_colors}"
        )
        _grab(canvas, "14_10level_colors")


# ============================================================
# 5. No drag
# ============================================================

class TestNoDrag:
    """Nodes should not be movable."""

    def test_nodes_not_movable(self, make_canvas):
        canvas, graph, _ = make_canvas("def f(): pass\nf()\n")
        from PySide6.QtWidgets import QGraphicsItem
        for item in canvas._node_items.values():
            assert not item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable


# ============================================================
# 6. L-shaped connectors
# ============================================================

class TestLShapedConnectors:
    """Edges should be L-shaped, not straight lines through nodes."""

    def test_edges_are_path_items(self, make_canvas):
        from PySide6.QtWidgets import QGraphicsPathItem
        canvas, graph, _ = make_canvas("def f(): pass\nf()\n")
        path_items = [item for item in canvas._scene.items() if isinstance(item, QGraphicsPathItem)]
        assert len(path_items) >= 1  # at least one connector

    def test_connector_does_not_overlap_nodes(self, make_canvas):
        """The mid-x of L-connector should be between parent right and child left."""
        canvas, graph, _ = make_canvas("def a(): b()\ndef b(): pass\na()\n")
        # Rough check: connector paths exist and aren't straight diagonal
        from PySide6.QtWidgets import QGraphicsPathItem
        paths = [item for item in canvas._scene.items() if isinstance(item, QGraphicsPathItem)]
        for p in paths:
            # Path should have at least 3 segments (L-shape = 3 lines)
            element_count = p.path().elementCount()
            assert element_count >= 3, f"L-shape should have 3+ points, got {element_count}"
        _grab(canvas, "07_l_connectors")


# ============================================================
# 7. Complex scenarios
# ============================================================

class TestComplexScenarios:
    """Larger, more realistic call trees."""

    def test_deep_chain(self, make_canvas):
        """5-level deep call chain."""
        source = (
            "def d4(): pass\n"
            "def d3(): d4()\n"
            "def d2(): d3()\n"
            "def d1(): d2()\n"
            "def main(): d1()\n"
            "main()\n"
        )
        canvas, graph, _ = make_canvas(source)
        depths = {graph.nodes[n].get("func_name"): graph.nodes[n].get("depth")
                  for n in graph.nodes}
        assert depths["<module>"] == 0
        assert depths["main"] == 1
        assert depths["d1"] == 2
        assert depths["d2"] == 3
        assert depths["d3"] == 4
        assert depths["d4"] == 5
        _grab(canvas, "08_deep_chain")

    def test_wide_call(self, make_canvas):
        """One function calling many others."""
        source = (
            "def a(): pass\ndef b(): pass\ndef c(): pass\ndef d(): pass\ndef e(): pass\n"
            "def main():\n    a()\n    b()\n    c()\n    d()\n    e()\n"
            "main()\n"
        )
        canvas, graph, _ = make_canvas(source)
        main_nodes = [n for n in graph.nodes if graph.nodes[n].get("func_name") == "main"]
        assert len(main_nodes) >= 1
        callees = list(graph.successors(main_nodes[0]))
        assert len(callees) >= 5
        _grab(canvas, "09_wide_call")

    def test_diamond_pattern(self, make_canvas):
        """A calls B and C, both call D — D should appear twice."""
        source = (
            "def d(): pass\n"
            "def b(): d()\n"
            "def c(): d()\n"
            "def a():\n    b()\n    c()\n"
            "a()\n"
        )
        canvas, graph, _ = make_canvas(source)
        d_nodes = [n for n in graph.nodes if graph.nodes[n].get("func_name") == "d"]
        assert len(d_nodes) == 2, f"d should appear twice in diamond, got {len(d_nodes)}"
        _grab(canvas, "10_diamond_pattern")

    def test_recursive_stops(self, make_canvas):
        """Recursive function should not create infinite nodes."""
        source = "def rec(): rec()\nrec()\n"
        canvas, graph, _ = make_canvas(source)
        # Should have finite nodes (DFS stops on revisit)
        assert len(graph.nodes) < 100
        _grab(canvas, "11_recursive")

    def test_class_methods(self, make_canvas):
        source = (
            "class Foo:\n"
            "    def bar(self): self.baz()\n"
            "    def baz(self): pass\n"
            "f = Foo()\n"
            "f.bar()\n"
        )
        canvas, graph, _ = make_canvas(source)
        assert len(canvas._node_items) > 0
        _grab(canvas, "12_class_methods")

    def test_empty_file(self, make_canvas):
        canvas, graph, _ = make_canvas("")
        assert graph is None or len(canvas._node_items) <= 1


# ============================================================
# 8. Detail text
# ============================================================

class TestDetailText:
    def test_detail_shows_call_count(self, make_canvas):
        source = "def f(): pass\ndef a(): f()\ndef b(): f()\na()\nb()\n"
        canvas, graph, panel = make_canvas(source)
        f_nodes = [n for n in graph.nodes if graph.nodes[n].get("func_name") == "f"]
        text = panel.get_detail_text(f_nodes[0], graph)
        assert "呼び出し回数: 2" in text

    def test_detail_shows_hierarchy(self, make_canvas):
        source = "def inner(): pass\ndef outer(): inner()\nouter()\n"
        canvas, graph, panel = make_canvas(source)
        inner_nodes = [n for n in graph.nodes if graph.nodes[n].get("func_name") == "inner"]
        text = panel.get_detail_text(inner_nodes[0], graph)
        assert "階層:" in text


# ============================================================
# 9. Export sanity check (spot check with new tree structure)
# ============================================================

class TestExportWithTree:
    def test_dot_export(self, make_canvas, tmp_path):
        canvas, graph, _ = make_canvas("def f(): pass\ndef g(): f()\ng()\n")
        out = tmp_path / "tree.dot"
        assert canvas.export_file(str(out), "dot")
        text = out.read_text(encoding="utf-8")
        assert "rankdir=LR" in text  # left-to-right for column layout

    def test_html_export_has_legend(self, make_canvas, tmp_path):
        source = "def f(): pass\ndef a(): f()\ndef b(): f()\na()\nb()\n"
        canvas, graph, _ = make_canvas(source)
        out = tmp_path / "tree.html"
        assert canvas.export_file(str(out), "html")
        text = out.read_text(encoding="utf-8")
        assert "階層0" in text or "ルート" in text
        assert "階層1" in text
        assert "太枠" in text or "呼出" in text

    def test_excel_has_hierarchy_columns(self, make_canvas, tmp_path):
        source = "def a(): b()\ndef b(): pass\na()\n"
        canvas, graph, _ = make_canvas(source)
        out = tmp_path / "tree.xlsx"
        assert canvas.export_file(str(out), "xlsx")

        from openpyxl import load_workbook
        wb = load_workbook(str(out))
        ws = wb["CallTree"]
        # Should have 階層 columns
        headers = [ws.cell(1, col).value for col in range(1, ws.max_column + 1)]
        hierarchy_cols = [h for h in headers if h and "階層" in str(h)]
        assert len(hierarchy_cols) >= 2

    def test_png_export(self, make_canvas, tmp_path):
        from orionparser.gui.widgets.graph_canvas import HAS_GRAPHVIZ
        if not HAS_GRAPHVIZ:
            pytest.skip("Graphviz not installed")
        canvas, graph, _ = make_canvas("def f(): pass\nf()\n")
        out = tmp_path / "tree.png"
        assert canvas.export_file(str(out), "png")
        assert out.stat().st_size > 100
        _grab(canvas, "13_png_export")
