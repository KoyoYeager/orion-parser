"""DFD real code test — verify symbols.py variable flows are correct."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from orionparser.analysis.dfd import extract_dfd


SRC = Path("src/orionparser/analysis/symbols.py")


@pytest.fixture(scope="module")
def dfd():
    from orionparser.registry import get_pipeline
    result = get_pipeline(SRC).analyze_file(SRC)
    return extract_dfd(result.ast)


class TestFunctionsFound:
    def test_extract_symbols(self, dfd):
        assert "extract_symbols" in dfd["functions"]

    def test_walk(self, dfd):
        assert "_walk" in dfd["functions"]

    def test_sym_dict(self, dfd):
        assert "_sym_dict" in dfd["functions"]

    def test_extract_target_name(self, dfd):
        assert "_extract_target_name" in dfd["functions"]

    def test_class_methods(self, dfd):
        funcs = dfd["functions"]
        assert any("SymbolTable" in f for f in funcs)


class TestExtractSymbolsVars:
    """extract_symbols(ast) → table = SymbolTable(), _walk(...), return table"""

    def test_param_ast(self, dfd):
        params = dfd["functions"]["extract_symbols"]["params"]
        assert "ast" in params

    def test_var_table(self, dfd):
        vars = dfd["functions"]["extract_symbols"]["variables"]
        assert "table" in vars

    def test_table_defined_by_symbolttable(self, dfd):
        table = dfd["functions"]["extract_symbols"]["variables"]["table"]
        assert any("SymbolTable" in d["expr"] for d in table["defined_at"])

    def test_returns_table(self, dfd):
        assert "table" in dfd["functions"]["extract_symbols"]["returns"]

    def test_calls_walk(self, dfd):
        calls = dfd["functions"]["extract_symbols"]["calls"]
        assert any("_walk" in c["func"] for c in calls)

    def test_table_passed_to_walk(self, dfd):
        table = dfd["functions"]["extract_symbols"]["variables"]["table"]
        assert any("_walk" in p["func"] for p in table["passed_to"])


class TestWalkVars:
    """_walk has body, table, scope params + node, node_type, line, name, var_name, etc."""

    def test_params(self, dfd):
        params = dfd["functions"]["_walk"]["params"]
        assert "body" in params
        assert "table" in params
        assert "scope" in params

    def test_has_node_type_var(self, dfd):
        vars = dfd["functions"]["_walk"]["variables"]
        assert "node_type" in vars

    def test_has_name_var(self, dfd):
        vars = dfd["functions"]["_walk"]["variables"]
        assert "name" in vars

    def test_has_var_name_var(self, dfd):
        vars = dfd["functions"]["_walk"]["variables"]
        assert "var_name" in vars

    def test_calls_extract_target_name(self, dfd):
        calls = dfd["functions"]["_walk"]["calls"]
        assert any("_extract_target_name" in c["func"] for c in calls)

    def test_calls_walk_recursively(self, dfd):
        calls = dfd["functions"]["_walk"]["calls"]
        assert any("_walk" in c["func"] for c in calls)


class TestSymDictVars:
    """_sym_dict(s) → d = {...}, if s.docstring: d["docstring"] = ..., return d"""

    def test_param_s(self, dfd):
        assert "s" in dfd["functions"]["_sym_dict"]["params"]

    def test_var_d(self, dfd):
        assert "d" in dfd["functions"]["_sym_dict"]["variables"]

    def test_returns_d(self, dfd):
        assert "d" in dfd["functions"]["_sym_dict"]["returns"]


class TestExtractTargetNameVars:
    def test_param_target(self, dfd):
        assert "target" in dfd["functions"]["_extract_target_name"]["params"]

    def test_has_obj_var(self, dfd):
        vars = dfd["functions"]["_extract_target_name"]["variables"]
        assert "obj" in vars

    def test_has_attr_var(self, dfd):
        vars = dfd["functions"]["_extract_target_name"]["variables"]
        assert "attr" in vars


class TestCrossFlows:
    def test_has_cross_flows(self, dfd):
        assert len(dfd["cross_function_flows"]) > 0

    def test_extract_symbols_to_walk(self, dfd):
        flows = dfd["cross_function_flows"]
        assert any(
            f["from_func"] == "extract_symbols" and f["to_func"] == "_walk"
            for f in flows
        )


class TestGUIRendering:
    def test_all_functions_render(self, qtbot):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.dfd_panel import DFDPanel
        from orionparser.registry import get_pipeline

        result = get_pipeline(SRC).analyze_file(SRC)
        panel = DFDPanel()
        panel.build_graph(result)

        for fname in panel.get_function_names():
            graph = panel.build_for_function(fname)
            if graph is None:
                continue
            colors = panel.get_node_colors(graph)
            canvas = GraphCanvas()
            qtbot.addWidget(canvas)
            canvas.set_graph(graph, layout="dfd", node_colors=colors)
            # Some simple methods may have 0 DFD nodes (single return with no variables)
            # That's OK — just verify no crash

    def test_export_works(self, qtbot, tmp_path):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.dfd_panel import DFDPanel
        from orionparser.registry import get_pipeline

        result = get_pipeline(SRC).analyze_file(SRC)
        panel = DFDPanel()
        panel.build_graph(result)
        graph = panel.build_for_function("extract_symbols")
        colors = panel.get_node_colors(graph)
        canvas = GraphCanvas()
        qtbot.addWidget(canvas)
        canvas.set_graph(graph, layout="dfd", node_colors=colors)

        out = tmp_path / "dfd_export.png"
        ok = canvas.export_png_from_scene(str(out))
        assert ok
        assert out.stat().st_size > 100
