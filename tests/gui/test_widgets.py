"""Tests for reusable widgets."""

from __future__ import annotations

import pytest


class TestSourceViewer:
    def test_set_source(self, qtbot):
        from orionparser.gui.widgets.source_viewer import SourceViewer

        viewer = SourceViewer()
        qtbot.addWidget(viewer)

        viewer.set_source("line 1\nline 2\nline 3\n")
        assert "line 1" in viewer.toPlainText()
        assert viewer.document().blockCount() >= 3

    def test_highlight_line(self, qtbot):
        from orionparser.gui.widgets.source_viewer import SourceViewer

        viewer = SourceViewer()
        qtbot.addWidget(viewer)

        viewer.set_source("a\nb\nc\nd\ne\n")
        viewer.highlight_line(3)
        assert viewer._highlighted_line == 3
        assert len(viewer.extraSelections()) == 1

    def test_clear_highlight(self, qtbot):
        from orionparser.gui.widgets.source_viewer import SourceViewer

        viewer = SourceViewer()
        qtbot.addWidget(viewer)

        viewer.set_source("a\nb\n")
        viewer.highlight_line(1)
        viewer.clear_highlight()
        assert viewer._highlighted_line is None
        assert len(viewer.extraSelections()) == 0

    def test_highlight_span(self, qtbot):
        from orionparser.gui.widgets.source_viewer import SourceViewer

        viewer = SourceViewer()
        qtbot.addWidget(viewer)

        # "hello\nworld\n" — "world" starts at position 6, length 5
        viewer.set_source("hello\nworld\n")
        viewer.highlight_span(6, 5)

        # Should have 2 extra selections: line bg + token highlight
        assert len(viewer.extraSelections()) == 2
        # Highlighted line should be 2 (where "world" is)
        assert viewer._highlighted_line == 2

    def test_highlight_span_scrolls_to_position(self, qtbot):
        from orionparser.gui.widgets.source_viewer import SourceViewer

        viewer = SourceViewer()
        qtbot.addWidget(viewer)

        # Many lines, highlight near the end
        source = "\n".join(f"line {i}" for i in range(100))
        viewer.set_source(source)
        viewer.highlight_span(len(source) - 10, 4)
        # Should not crash, should have selections
        assert len(viewer.extraSelections()) == 2

    def test_line_clicked_signal(self, qtbot):
        from orionparser.gui.widgets.source_viewer import SourceViewer

        viewer = SourceViewer()
        qtbot.addWidget(viewer)
        viewer.set_source("line1\nline2\n")

        with qtbot.waitSignal(viewer.line_clicked, timeout=1000):
            # Simulate click by direct signal emission for offscreen
            viewer.line_clicked.emit(1)


class TestSearchBar:
    def test_filter_changed_signal(self, qtbot):
        from orionparser.gui.widgets.search_bar import SearchBar

        bar = SearchBar(categories=["A", "B"])
        qtbot.addWidget(bar)

        with qtbot.waitSignal(bar.filter_changed, timeout=2000):
            bar._input.setText("test")
            bar._debounce.timeout.emit()

    def test_default_category(self, qtbot):
        from orionparser.gui.widgets.search_bar import SearchBar

        bar = SearchBar()
        qtbot.addWidget(bar)
        assert bar.category == "all"


class TestGraphCanvas:
    def test_set_graph(self, qtbot):
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")

        canvas.set_graph(g)
        # 3 nodes (rect+text each) + 2 edges + 2 arrows = many items
        assert len(canvas._scene.items()) > 0
        assert len(canvas._node_items) == 3

    def test_empty_graph(self, qtbot):
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        canvas.set_graph(g)
        assert len(canvas._node_items) == 0

    def test_fit_to_view(self, qtbot):
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        g.add_edge("X", "Y")
        canvas.set_graph(g)
        canvas.fit_to_view()  # should not raise

    def test_clear_graph(self, qtbot):
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        g.add_edge("A", "B")
        canvas.set_graph(g)
        canvas.clear_graph()
        assert len(canvas._node_items) == 0

    def test_dot_layout(self, qtbot):
        """Graphviz dot layout produces valid positions."""
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        g.add_edge("main", "helper")
        g.add_edge("main", "process")
        g.add_edge("helper", "util")

        canvas.set_graph(g, layout="dot")
        assert len(canvas._node_items) == 4
        # Nodes should have distinct positions
        positions = {nid: item.pos() for nid, item in canvas._node_items.items()}
        pos_set = {(round(p.x()), round(p.y())) for p in positions.values()}
        assert len(pos_set) == 4  # all unique

    def test_to_dot(self, qtbot):
        """DOT source generation."""
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        g.add_edge("A", "B")
        canvas.set_graph(g, node_colors={"A": "#FF0000", "B": "#00FF00"})

        dot = canvas.to_dot()
        assert "digraph" in dot
        assert '"A"' in dot
        assert '"B"' in dot
        assert '"A" -> "B"' in dot
        assert "#FF0000" in dot

    def test_export_dot_file(self, qtbot, tmp_path):
        """Export to DOT file."""
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        g.add_edge("X", "Y")
        canvas.set_graph(g)

        out = tmp_path / "test.dot"
        assert canvas.export_file(str(out), "dot") is True
        content = out.read_text(encoding="utf-8")
        assert "digraph" in content
        assert '"X" -> "Y"' in content

    def test_export_svg_file(self, qtbot, tmp_path):
        """Export to SVG via Graphviz."""
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas, HAS_GRAPHVIZ

        if not HAS_GRAPHVIZ:
            pytest.skip("Graphviz not installed")

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        g.add_edge("func_a", "func_b")
        canvas.set_graph(g)

        out = tmp_path / "test.svg"
        assert canvas.export_file(str(out), "svg") is True
        content = out.read_text(encoding="utf-8")
        assert "<svg" in content

    def test_export_png_file(self, qtbot, tmp_path):
        """Export to PNG via Graphviz."""
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas, HAS_GRAPHVIZ

        if not HAS_GRAPHVIZ:
            pytest.skip("Graphviz not installed")

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        g.add_edge("alpha", "beta")
        canvas.set_graph(g)

        out = tmp_path / "test.png"
        assert canvas.export_file(str(out), "png") is True
        assert out.stat().st_size > 100

    def test_export_pdf_file(self, qtbot, tmp_path):
        """Export to PDF via Graphviz."""
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas, HAS_GRAPHVIZ

        if not HAS_GRAPHVIZ:
            pytest.skip("Graphviz not installed")

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        g.add_edge("a", "b")
        canvas.set_graph(g)

        out = tmp_path / "test.pdf"
        assert canvas.export_file(str(out), "pdf") is True
        assert out.stat().st_size > 100

    def test_export_json_file(self, qtbot, tmp_path):
        """Export to JSON."""
        import json
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        g.add_edge("main", "helper")
        canvas.set_graph(g, node_colors={"main": "#FF0000"})

        out = tmp_path / "test.json"
        assert canvas.export_file(str(out), "json") is True

        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert data["edges"][0]["source"] == "main"
        assert data["edges"][0]["target"] == "helper"

    def test_export_jpg_file(self, qtbot, tmp_path):
        """Export to JPEG via Graphviz."""
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas, HAS_GRAPHVIZ

        if not HAS_GRAPHVIZ:
            pytest.skip("Graphviz not installed")

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        g.add_edge("x", "y")
        canvas.set_graph(g)

        out = tmp_path / "test.jpg"
        assert canvas.export_file(str(out), "jpg") is True
        assert out.stat().st_size > 100

    def test_export_eps_file(self, qtbot, tmp_path):
        """Export to EPS via Graphviz."""
        import networkx as nx
        from orionparser.gui.widgets.graph_canvas import GraphCanvas, HAS_GRAPHVIZ

        if not HAS_GRAPHVIZ:
            pytest.skip("Graphviz not installed")

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)

        g = nx.DiGraph()
        g.add_edge("p", "q")
        canvas.set_graph(g)

        out = tmp_path / "test.eps"
        assert canvas.export_file(str(out), "eps") is True
        assert out.stat().st_size > 100
