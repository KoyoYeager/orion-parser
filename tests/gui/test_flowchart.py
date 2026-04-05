"""Tests for flowchart generation — control flow extraction + JIS shapes."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest


def _parse(source: str):
    """Parse source and return ParseResult."""
    p = Path(f"_fc_test_{id(source)}.py")
    p.write_text(source, encoding="utf-8")
    try:
        from orionparser.registry import get_pipeline
        pipeline = get_pipeline(p)
        return pipeline.analyze_file(p)
    finally:
        p.unlink(missing_ok=True)


def _cfg(source: str, func_name: str = None):
    """Extract control flow for a function."""
    from orionparser.analysis.control_flow import extract_control_flow
    result = _parse(source)
    cf = extract_control_flow(result.ast)
    funcs = cf["functions"]
    if func_name:
        return funcs.get(func_name)
    return funcs.get(next(iter(funcs))) if funcs else None


# ============================================================
# Control flow extraction
# ============================================================

class TestControlFlowBasic:
    def test_simple_function(self):
        cfg = _cfg("def f():\n    x = 1\n    return x\n")
        assert cfg is not None
        types = [n["type"] for n in cfg["nodes"]]
        assert "start" in types
        assert "end" in types
        assert "process" in types  # x = 1
        assert "return" in types

    def test_if_statement(self):
        cfg = _cfg("def f(x):\n    if x > 0:\n        print('pos')\n    else:\n        print('neg')\n")
        types = [n["type"] for n in cfg["nodes"]]
        assert "decision" in types
        assert "io" in types  # print
        # Should have True/False labels on edges
        labels = [e["label"] for e in cfg["edges"]]
        assert "True" in labels
        assert "False" in labels

    def test_for_loop(self):
        cfg = _cfg("def f():\n    for i in range(10):\n        print(i)\n")
        types = [n["type"] for n in cfg["nodes"]]
        assert "loop_start" in types
        assert "loop_end" in types
        # Loop start should contain the iteration info
        loop_nodes = [n for n in cfg["nodes"] if n["type"] == "loop_start"]
        assert any("i" in n["label"] and "range" in n["label"] for n in loop_nodes)

    def test_while_loop(self):
        cfg = _cfg("def f(x):\n    while x > 0:\n        x -= 1\n")
        types = [n["type"] for n in cfg["nodes"]]
        assert "loop_start" in types
        assert "loop_end" in types

    def test_nested_if_for(self):
        source = (
            "def f(items):\n"
            "    for item in items:\n"
            "        if item > 0:\n"
            "            print(item)\n"
        )
        cfg = _cfg(source)
        types = [n["type"] for n in cfg["nodes"]]
        assert "loop_start" in types
        assert "decision" in types
        assert "io" in types

    def test_multiple_returns(self):
        source = (
            "def f(x):\n"
            "    if x > 0:\n"
            "        return 1\n"
            "    return 0\n"
        )
        cfg = _cfg(source)
        return_nodes = [n for n in cfg["nodes"] if n["type"] == "return"]
        assert len(return_nodes) == 2

    def test_try_except(self):
        source = (
            "def f():\n"
            "    try:\n"
            "        x = 1\n"
            "    except:\n"
            "        x = 0\n"
        )
        cfg = _cfg(source)
        labels = [n["label"] for n in cfg["nodes"]]
        assert any("try" in l for l in labels)
        assert any("except" in l for l in labels)

    def test_empty_function(self):
        cfg = _cfg("def f():\n    pass\n")
        assert cfg is not None
        types = [n["type"] for n in cfg["nodes"]]
        assert "start" in types
        assert "end" in types

    def test_multiple_functions(self):
        source = "def a():\n    pass\ndef b():\n    pass\n"
        from orionparser.analysis.control_flow import extract_control_flow
        result = _parse(source)
        cf = extract_control_flow(result.ast)
        assert "a" in cf["functions"]
        assert "b" in cf["functions"]


# ============================================================
# Flowchart panel
# ============================================================

class TestFlowchartPanel:
    def test_build_graph(self):
        from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel
        result = _parse("def f():\n    x = 1\n    print(x)\n    return x\n")
        panel = FlowchartPanel()
        graph = panel.build_graph(result)
        assert graph is not None
        assert len(graph.nodes) > 0

    def test_function_names(self):
        from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel
        result = _parse("def a(): pass\ndef b(): pass\ndef c(): pass\n")
        panel = FlowchartPanel()
        panel.build_graph(result)
        names = panel.get_function_names()
        assert "a" in names
        assert "b" in names
        assert "c" in names

    def test_build_for_function(self):
        from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel
        result = _parse("def a():\n    return 1\ndef b():\n    return 2\n")
        panel = FlowchartPanel()
        panel.build_graph(result)
        g = panel.build_for_function("b")
        assert g is not None
        # Should have a node with "return 2"
        labels = [g.nodes[n].get("label", "") for n in g.nodes]
        assert any("return" in l for l in labels)

    def test_node_colors(self):
        from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel
        result = _parse("def f(x):\n    if x:\n        print(x)\n    return x\n")
        panel = FlowchartPanel()
        graph = panel.build_graph(result)
        colors = panel.get_node_colors(graph)
        # All nodes should have colors
        for n in graph.nodes:
            assert n in colors


# ============================================================
# GUI rendering
# ============================================================

class TestFlowchartRendering:
    def test_canvas_renders(self, qtbot):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel

        result = _parse("def f(x):\n    if x > 0:\n        print(x)\n    return x\n")
        panel = FlowchartPanel()
        graph = panel.build_graph(result)
        colors = panel.get_node_colors(graph)

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)
        canvas.set_graph(graph, layout="flowchart", node_colors=colors)

        assert len(canvas._node_items) > 0
        canvas.fit_to_view()

    def test_different_shapes(self, qtbot):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas, _FlowchartNodeItem
        from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel

        source = (
            "def f(x):\n"
            "    for i in range(x):\n"
            "        if i > 0:\n"
            "            print(i)\n"
            "    return x\n"
        )
        result = _parse(source)
        panel = FlowchartPanel()
        graph = panel.build_graph(result)
        colors = panel.get_node_colors(graph)

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)
        canvas.set_graph(graph, layout="flowchart", node_colors=colors)

        # Check that different shape types are used
        shape_types = set()
        for item in canvas._node_items.values():
            if isinstance(item, _FlowchartNodeItem):
                shape_types.add(item._shape_type)

        assert "rounded" in shape_types    # start/end/return
        assert "diamond" in shape_types    # if decision
        assert "trap_top" in shape_types   # loop start
        assert "trap_bottom" in shape_types  # loop end

    def test_screenshot(self, qtbot):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel

        source = (
            "def process(data):\n"
            "    result = []\n"
            "    for item in data:\n"
            "        if item > 0:\n"
            "            print(item)\n"
            "            result.append(item)\n"
            "        else:\n"
            "            print('skip')\n"
            "    return result\n"
        )
        result = _parse(source)
        panel = FlowchartPanel()
        graph = panel.build_graph(result)
        colors = panel.get_node_colors(graph)

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)
        canvas.set_graph(graph, layout="flowchart", node_colors=colors)
        canvas.fit_to_view()

        ss_dir = Path(__file__).parent / "screenshots" / "flowchart"
        ss_dir.mkdir(parents=True, exist_ok=True)
        canvas.grab().save(str(ss_dir / "process_flowchart.png"))


# ============================================================
# Edge cases
# ============================================================

class TestFlowchartEdgeCases:
    def test_function_with_only_pass(self):
        cfg = _cfg("def f():\n    pass\n")
        assert len(cfg["nodes"]) >= 2  # at least start + end

    def test_deeply_nested(self):
        source = (
            "def f(x):\n"
            "    if x > 0:\n"
            "        if x > 10:\n"
            "            if x > 100:\n"
            "                print(x)\n"
        )
        cfg = _cfg(source)
        decisions = [n for n in cfg["nodes"] if n["type"] == "decision"]
        assert len(decisions) == 3

    def test_while_with_break(self):
        source = (
            "def f():\n"
            "    while True:\n"
            "        x = input()\n"
            "        if x == 'q':\n"
            "            break\n"
        )
        cfg = _cfg(source)
        types = [n["type"] for n in cfg["nodes"]]
        assert "loop_start" in types
        assert "decision" in types  # if x == 'q'
        # x = input() is an Assign, so it's a process node
        assert "process" in types

    def test_real_code(self):
        """Test with orion-parser's own extract_symbols function."""
        from orionparser.registry import get_pipeline
        p = Path("src/orionparser/analysis/symbols.py")
        if not p.exists():
            pytest.skip("symbols.py not found")
        pipeline = get_pipeline(p)
        result = pipeline.analyze_file(p)

        from orionparser.analysis.control_flow import extract_control_flow
        cf = extract_control_flow(result.ast)
        assert len(cf["functions"]) > 0
        # extract_symbols should be one of the functions
        assert "extract_symbols" in cf["functions"]
        cfg = cf["functions"]["extract_symbols"]
        assert len(cfg["nodes"]) > 2  # more than just start/end
