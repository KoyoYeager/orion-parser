"""Test every export format -generate files and verify contents."""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest


@pytest.fixture
def canvas_with_graph(qtbot):
    from orionparser.gui.widgets.graph_canvas import GraphCanvas

    canvas = GraphCanvas()
    qtbot.addWidget(canvas)

    g = nx.DiGraph()
    g.add_edge("<module>", "main")
    g.add_edge("main", "parse_file")
    g.add_edge("main", "validate")
    g.add_edge("parse_file", "read_tokens")
    g.add_edge("<module>", "Config.__init__")

    colors = {
        "<module>": "#B3D9FF",
        "main": "#85C1E9",
        "parse_file": "#85C1E9",
        "validate": "#85C1E9",
        "read_tokens": "#85C1E9",
        "Config.__init__": "#D7BDE2",
    }
    canvas.set_graph(g, layout="dot", node_colors=colors)
    return canvas


# ── Graphviz formats ──

class TestGraphvizExports:
    @pytest.fixture(autouse=True)
    def _check_graphviz(self):
        from orionparser.gui.widgets.graph_canvas import HAS_GRAPHVIZ
        if not HAS_GRAPHVIZ:
            pytest.skip("Graphviz not installed")

    def test_svg(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.svg"
        assert canvas_with_graph.export_file(str(out), "svg")
        text = out.read_text(encoding="utf-8")
        assert "<svg" in text
        assert "main" in text
        print(f"  SVG: {out.stat().st_size} bytes")

    def test_png(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.png"
        assert canvas_with_graph.export_file(str(out), "png")
        data = out.read_bytes()
        assert data[:4] == b"\x89PNG"
        print(f"  PNG: {out.stat().st_size} bytes")

    def test_pdf(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.pdf"
        assert canvas_with_graph.export_file(str(out), "pdf")
        data = out.read_bytes()
        assert data[:5] == b"%PDF-"
        print(f"  PDF: {out.stat().st_size} bytes")

    def test_jpg(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.jpg"
        assert canvas_with_graph.export_file(str(out), "jpg")
        data = out.read_bytes()
        assert data[:2] == b"\xff\xd8"  # JPEG magic
        print(f"  JPG: {out.stat().st_size} bytes")

    def test_bmp(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.bmp"
        assert canvas_with_graph.export_file(str(out), "bmp")
        data = out.read_bytes()
        assert data[:2] == b"BM"
        print(f"  BMP: {out.stat().st_size} bytes")

    def test_gif(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.gif"
        assert canvas_with_graph.export_file(str(out), "gif")
        data = out.read_bytes()
        assert data[:3] == b"GIF"
        print(f"  GIF: {out.stat().st_size} bytes")

    def test_eps(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.eps"
        assert canvas_with_graph.export_file(str(out), "eps")
        text = out.read_text(encoding="latin-1")
        assert "%!PS" in text
        print(f"  EPS: {out.stat().st_size} bytes")

    def test_webp(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.webp"
        assert canvas_with_graph.export_file(str(out), "webp")
        data = out.read_bytes()
        assert data[8:12] == b"WEBP"
        print(f"  WEBP: {out.stat().st_size} bytes")

    def test_tiff(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.tif"
        assert canvas_with_graph.export_file(str(out), "tif")
        data = out.read_bytes()
        assert data[:2] in (b"II", b"MM")  # TIFF little/big endian
        print(f"  TIFF: {out.stat().st_size} bytes")


# ── Text-based formats ──

class TestTextExports:
    def test_dot(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.dot"
        assert canvas_with_graph.export_file(str(out), "dot")
        text = out.read_text(encoding="utf-8")
        assert "digraph" in text
        assert '"main"' in text
        assert '"<module>" -> "main"' in text
        assert "fillcolor" in text
        print(f"  DOT: {out.stat().st_size} bytes, {len(text.splitlines())} lines")

    def test_json(self, canvas_with_graph, tmp_path):
        import json
        out = tmp_path / "tree.json"
        assert canvas_with_graph.export_file(str(out), "json")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["nodes"]) == 6
        assert len(data["edges"]) == 5
        assert any(n["id"] == "main" for n in data["nodes"])
        print(f"  JSON: {out.stat().st_size} bytes, {len(data['nodes'])} nodes")

    def test_mermaid(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.md"
        assert canvas_with_graph.export_file(str(out), "mermaid")
        text = out.read_text(encoding="utf-8")
        assert "graph" in text  # LR or TD
        assert "main" in text
        assert "-->" in text
        print(f"  Mermaid: {out.stat().st_size} bytes")

    def test_plantuml(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.puml"
        assert canvas_with_graph.export_file(str(out), "plantuml")
        text = out.read_text(encoding="utf-8")
        assert "@startuml" in text
        assert "@enduml" in text
        assert '"main"' in text
        assert "-->" in text
        print(f"  PlantUML: {out.stat().st_size} bytes")

    def test_drawio(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.drawio"
        assert canvas_with_graph.export_file(str(out), "drawio")
        text = out.read_text(encoding="utf-8")
        assert "<mxfile>" in text
        assert "main" in text
        assert 'edge="1"' in text
        print(f"  Draw.io: {out.stat().st_size} bytes")

    def test_xml(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.xml"
        assert canvas_with_graph.export_file(str(out), "xml")
        text = out.read_text(encoding="utf-8")
        assert "<graph>" in text
        assert "<node " in text
        assert "<edge " in text
        assert 'id="main"' in text
        print(f"  XML: {out.stat().st_size} bytes")

    def test_yaml(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.yaml"
        assert canvas_with_graph.export_file(str(out), "yaml")
        text = out.read_text(encoding="utf-8")
        assert "nodes:" in text
        assert "edges:" in text
        assert '"main"' in text
        print(f"  YAML: {out.stat().st_size} bytes")

    def test_html(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.html"
        assert canvas_with_graph.export_file(str(out), "html")
        text = out.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in text
        assert "main" in text
        assert "OrionParser" in text
        assert "class=\"node\"" in text
        print(f"  HTML: {out.stat().st_size} bytes")


# ── Office format ──

class TestOfficeExports:
    def test_excel(self, canvas_with_graph, tmp_path):
        out = tmp_path / "tree.xlsx"
        assert canvas_with_graph.export_file(str(out), "xlsx")
        assert out.stat().st_size > 1000

        from openpyxl import load_workbook
        wb = load_workbook(str(out))
        assert "CallTree" in wb.sheetnames
        assert "Edges" in wb.sheetnames
        assert "Statistics" in wb.sheetnames

        ws = wb["CallTree"]
        # Header: #, 関数名, 呼び出し回数, 階層1, 階層2, ...
        assert ws.cell(1, 1).value == "#"
        # Data rows should have nodes
        assert ws.max_row >= 2
        node_names = [ws.cell(r, 2).value for r in range(2, ws.max_row + 1)]
        assert "main" in node_names
        # Hierarchy columns exist
        headers = [ws.cell(1, col).value for col in range(1, ws.max_column + 1)]
        hierarchy_cols = [h for h in headers if h and str(h).startswith("階層")]
        assert len(hierarchy_cols) >= 1

        ws2 = wb["Edges"]
        assert ws2.max_row == 6  # header + 5 edges

        ws3 = wb["Statistics"]
        # Statistics section
        assert ws3.cell(1, 1).value == "統計情報"

        print(f"  Excel: {out.stat().st_size} bytes, "
              f"Nodes={ws.max_row-1}, Edges={ws2.max_row-1}, "
              f"Columns={ws.max_column} (with hierarchy)")

    def test_visio_missing_raises_importerror(self, canvas_with_graph, tmp_path):
        """Visio export raises ImportError if pywin32 not available or Visio not installed."""
        import importlib
        has_win32 = importlib.util.find_spec("win32com") is not None

        out = tmp_path / "tree.vsdx"
        if not has_win32:
            # pywin32 not installed -> ImportError
            with pytest.raises(ImportError, match="pywin32"):
                canvas_with_graph.export_file(str(out), "vsdx")
            print("  Visio: ImportError raised (pywin32 not installed) -OK")
        else:
            # pywin32 installed but Visio may not be -> RuntimeError or success
            try:
                result = canvas_with_graph.export_file(str(out), "vsdx")
                if result:
                    assert out.stat().st_size > 100
                    print(f"  Visio: {out.stat().st_size} bytes -exported successfully")
                else:
                    print("  Visio: export returned False (Visio not available)")
            except RuntimeError as exc:
                print(f"  Visio: RuntimeError -{exc}")
                # Expected when Visio is not installed
