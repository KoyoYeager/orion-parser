"""DFD tests — variable tracking, cross-function flows, impact analysis."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from orionparser.analysis.dfd import extract_dfd


def _dfd(source: str) -> dict:
    p = Path(f"_dfd_{abs(hash(source)) % 99999}.py")
    p.write_text(source, encoding="utf-8")
    try:
        from orionparser.registry import get_pipeline
        result = get_pipeline(p).analyze_file(p)
    finally:
        p.unlink(missing_ok=True)
    return extract_dfd(result.ast)


# ============================================================
# Variable tracking within a function
# ============================================================

class TestVariableTracking:
    def test_parameter_is_defined(self):
        dfd = _dfd("def f(x):\n    return x\n")
        assert "x" in dfd["functions"]["f"]["variables"]
        vx = dfd["functions"]["f"]["variables"]["x"]
        assert any(d["expr"] == "parameter" for d in vx["defined_at"])

    def test_assignment_tracked(self):
        dfd = _dfd("def f():\n    x = 1\n    return x\n")
        assert "x" in dfd["functions"]["f"]["variables"]
        vx = dfd["functions"]["f"]["variables"]["x"]
        assert len(vx["defined_at"]) >= 1

    def test_usage_tracked(self):
        dfd = _dfd("def f():\n    x = 1\n    y = x + 2\n    return y\n")
        vx = dfd["functions"]["f"]["variables"]["x"]
        assert len(vx["used_at"]) >= 1  # used in y = x + 2

    def test_return_tracked(self):
        dfd = _dfd("def f():\n    x = 1\n    return x\n")
        assert "x" in dfd["functions"]["f"]["returns"]

    def test_augassign_tracked(self):
        dfd = _dfd("def f():\n    x = 0\n    x += 1\n    return x\n")
        vx = dfd["functions"]["f"]["variables"]["x"]
        assert len(vx["defined_at"]) >= 2  # initial + augassign


# ============================================================
# Function call tracking
# ============================================================

class TestCallTracking:
    def test_call_recorded(self):
        dfd = _dfd("def g(): pass\ndef f():\n    x = g()\n    return x\n")
        calls = dfd["functions"]["f"]["calls"]
        assert any(c["func"] == "g" for c in calls)

    def test_call_result_var(self):
        dfd = _dfd("def g(): pass\ndef f():\n    result = g()\n    return result\n")
        calls = dfd["functions"]["f"]["calls"]
        g_call = next(c for c in calls if c["func"] == "g")
        assert g_call["result_var"] == "result"

    def test_call_args_tracked(self):
        dfd = _dfd("def g(a): pass\ndef f():\n    x = 1\n    g(x)\n")
        calls = dfd["functions"]["f"]["calls"]
        g_call = next(c for c in calls if c["func"] == "g")
        assert "x" in g_call["args"]

    def test_passed_to_tracked(self):
        dfd = _dfd("def g(a): pass\ndef f():\n    x = 1\n    g(x)\n")
        vx = dfd["functions"]["f"]["variables"]["x"]
        assert any(p["func"] == "g" for p in vx["passed_to"])


# ============================================================
# Cross-function flows
# ============================================================

class TestCrossFunctionFlows:
    def test_arg_flow(self):
        source = "def process(data): return data\ndef main():\n    x = [1,2]\n    result = process(x)\n"
        dfd = _dfd(source)
        flows = dfd["cross_function_flows"]
        assert any(
            f["from_func"] == "main" and f["from_var"] == "x" and
            f["to_func"] == "process" and f["to_param"] == "data"
            for f in flows
        ), f"Missing flow main.x -> process.data. Flows: {flows}"

    def test_return_flow(self):
        source = "def process(data): return data\ndef main():\n    x = [1,2]\n    result = process(x)\n"
        dfd = _dfd(source)
        flows = dfd["cross_function_flows"]
        assert any(
            f["from_func"] == "process" and f["to_func"] == "main" and
            f["to_param"] == "result"
            for f in flows
        ), f"Missing return flow process -> main.result. Flows: {flows}"


# ============================================================
# Real test project
# ============================================================

class TestDFDTestProject:
    @pytest.fixture(scope="class")
    def dfd(self):
        p = Path("C:/tmp/dfd_test/app.py")
        if not p.exists():
            pytest.skip("DFD test project not found")
        from orionparser.registry import get_pipeline
        result = get_pipeline(p).analyze_file(p)
        return extract_dfd(result.ast)

    def test_all_functions_found(self, dfd):
        funcs = set(dfd["functions"].keys())
        expected = {"read_input", "validate", "calculate", "format_output", "process"}
        assert expected <= funcs, f"Missing: {expected - funcs}"

    # --- read_input ---
    def test_read_input_params(self, dfd):
        assert dfd["functions"]["read_input"]["params"] == ["path"]

    def test_read_input_returns_data(self, dfd):
        assert "data" in dfd["functions"]["read_input"]["returns"]

    def test_read_input_variables(self, dfd):
        vars = dfd["functions"]["read_input"]["variables"]
        assert "raw" in vars or "lines" in vars or "data" in vars

    # --- validate ---
    def test_validate_params(self, dfd):
        assert dfd["functions"]["validate"]["params"] == ["data"]

    def test_validate_returns_cleaned(self, dfd):
        assert "cleaned" in dfd["functions"]["validate"]["returns"]

    def test_validate_has_cleaned_var(self, dfd):
        assert "cleaned" in dfd["functions"]["validate"]["variables"]

    # --- calculate ---
    def test_calculate_params(self, dfd):
        assert dfd["functions"]["calculate"]["params"] == ["data"]

    def test_calculate_returns_result(self, dfd):
        assert "result" in dfd["functions"]["calculate"]["returns"]

    def test_calculate_has_total(self, dfd):
        assert "total" in dfd["functions"]["calculate"]["variables"]

    def test_calculate_has_count(self, dfd):
        assert "count" in dfd["functions"]["calculate"]["variables"]

    def test_calculate_has_average(self, dfd):
        assert "average" in dfd["functions"]["calculate"]["variables"]

    # --- format_output ---
    def test_format_output_params(self, dfd):
        assert dfd["functions"]["format_output"]["params"] == ["stats"]

    def test_format_output_returns_output(self, dfd):
        assert "output" in dfd["functions"]["format_output"]["returns"]

    # --- process (pipeline function) ---
    def test_process_params(self, dfd):
        params = dfd["functions"]["process"]["params"]
        assert "input_path" in params
        assert "output_path" in params

    def test_process_calls_read_input(self, dfd):
        calls = dfd["functions"]["process"]["calls"]
        assert any(c["func"] == "read_input" for c in calls)

    def test_process_calls_validate(self, dfd):
        calls = dfd["functions"]["process"]["calls"]
        assert any(c["func"] == "validate" for c in calls)

    def test_process_calls_calculate(self, dfd):
        calls = dfd["functions"]["process"]["calls"]
        assert any(c["func"] == "calculate" for c in calls)

    def test_process_calls_format_output(self, dfd):
        calls = dfd["functions"]["process"]["calls"]
        assert any(c["func"] == "format_output" for c in calls)

    def test_process_data_flows_through(self, dfd):
        """data → clean_data → stats → report: variable chain."""
        vars = dfd["functions"]["process"]["variables"]
        assert "data" in vars
        assert "clean_data" in vars
        assert "stats" in vars
        assert "report" in vars

    # --- cross-function flows ---
    def test_cross_flow_data_to_validate(self, dfd):
        flows = dfd["cross_function_flows"]
        assert any(
            f["from_func"] == "process" and f["from_var"] == "data" and
            f["to_func"] == "validate"
            for f in flows
        )

    def test_cross_flow_clean_data_to_calculate(self, dfd):
        flows = dfd["cross_function_flows"]
        assert any(
            f["from_func"] == "process" and f["from_var"] == "clean_data" and
            f["to_func"] == "calculate"
            for f in flows
        )

    def test_cross_flow_stats_to_format(self, dfd):
        flows = dfd["cross_function_flows"]
        assert any(
            f["from_func"] == "process" and f["from_var"] == "stats" and
            f["to_func"] == "format_output"
            for f in flows
        )


# ============================================================
# GUI rendering
# ============================================================

class TestDFDGUI:
    def test_panel_renders(self, qtbot):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.dfd_panel import DFDPanel

        p = Path("C:/tmp/dfd_test/app.py")
        if not p.exists():
            pytest.skip("DFD test project not found")
        from orionparser.registry import get_pipeline
        result = get_pipeline(p).analyze_file(p)

        panel = DFDPanel()
        graph = panel.build_graph(result)
        assert graph is not None

        colors = panel.get_node_colors(graph)
        canvas = GraphCanvas()
        qtbot.addWidget(canvas)
        canvas.set_graph(graph, layout="dfd", node_colors=colors)
        assert len(canvas._node_items) > 0

    def test_function_switch(self, qtbot):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.dfd_panel import DFDPanel

        p = Path("C:/tmp/dfd_test/app.py")
        if not p.exists():
            pytest.skip("DFD test project not found")
        from orionparser.registry import get_pipeline
        result = get_pipeline(p).analyze_file(p)

        panel = DFDPanel()
        panel.build_graph(result)

        names = panel.get_function_names()
        assert "process" in names
        assert "calculate" in names

        # Switch to calculate
        graph = panel.build_for_function("calculate")
        assert graph is not None
        colors = panel.get_node_colors(graph)
        canvas = GraphCanvas()
        qtbot.addWidget(canvas)
        canvas.set_graph(graph, layout="dfd", node_colors=colors)
        assert len(canvas._node_items) > 0

    def test_export(self, qtbot):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.dfd_panel import DFDPanel

        p = Path("C:/tmp/dfd_test/app.py")
        if not p.exists():
            pytest.skip("DFD test project not found")
        from orionparser.registry import get_pipeline
        result = get_pipeline(p).analyze_file(p)

        panel = DFDPanel()
        panel.build_graph(result)
        graph = panel.build_for_function("process")
        colors = panel.get_node_colors(graph)
        canvas = GraphCanvas()
        qtbot.addWidget(canvas)
        canvas.set_graph(graph, layout="dfd", node_colors=colors)

        ss = Path(__file__).parent / "screenshots" / "dfd"
        ss.mkdir(parents=True, exist_ok=True)
        ok = canvas.export_png_from_scene(str(ss / "process_dfd.png"))
        assert ok
