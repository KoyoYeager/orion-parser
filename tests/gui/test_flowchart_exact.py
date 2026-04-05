"""Exact flowchart verification — predict expected nodes/edges, then compare.

Each test defines:
1. Source code
2. Expected node sequence (type + label pattern)
3. Expected edge connections (with True/False labels)
Then verifies the actual CFG matches exactly.
"""

from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from orionparser.analysis.control_flow import extract_control_flow


def _cfg(source: str, func_name: str | None = None) -> dict:
    p = Path(f"_exact_{id(source)}.py")
    p.write_text(source, encoding="utf-8")
    try:
        from orionparser.registry import get_pipeline
        result = get_pipeline(p).analyze_file(p)
    finally:
        p.unlink(missing_ok=True)
    cf = extract_control_flow(result.ast)
    funcs = cf["functions"]
    if func_name:
        return funcs[func_name]
    return funcs[next(iter(funcs))]


def _types(cfg: dict) -> list[str]:
    """Return ordered list of node types."""
    return [n["type"] for n in cfg["nodes"]]


def _edge_pairs(cfg: dict) -> set[tuple[str, str, str]]:
    """Return set of (from_type, to_type, label) using node types."""
    id_to_type = {n["id"]: n["type"] for n in cfg["nodes"]}
    result = set()
    for e in cfg["edges"]:
        ft = id_to_type.get(e["from"], "?")
        tt = id_to_type.get(e["to"], "?")
        result.add((ft, tt, e["label"]))
    return result


def _has_label(cfg: dict, pattern: str) -> bool:
    """Check if any node label matches the pattern."""
    return any(re.search(pattern, n["label"]) for n in cfg["nodes"])


# ============================================================
# 1. Sequential processing (no branching)
# ============================================================

class TestSequential:
    """
    def f():
        x = 1
        y = 2
        return x + y

    Expected flow:
        start → process(x=1) → process(y=2) → return → end
    """
    SOURCE = "def f():\n    x = 1\n    y = 2\n    return x + y\n"

    def test_node_count(self):
        cfg = _cfg(self.SOURCE)
        assert len(cfg["nodes"]) == 5  # start, x=1, y=2, return, end

    def test_node_types(self):
        types = _types(_cfg(self.SOURCE))
        assert types == ["start", "process", "process", "return", "end"]

    def test_labels(self):
        cfg = _cfg(self.SOURCE)
        assert _has_label(cfg, r"x = 1")
        assert _has_label(cfg, r"y = 2")
        assert _has_label(cfg, r"return")

    def test_linear_edges(self):
        """Every node connects to the next in sequence."""
        cfg = _cfg(self.SOURCE)
        for i in range(len(cfg["nodes"]) - 1):
            src = cfg["nodes"][i]["id"]
            dst = cfg["nodes"][i + 1]["id"]
            matching = [e for e in cfg["edges"] if e["from"] == src and e["to"] == dst]
            assert len(matching) == 1, f"Missing edge {src} -> {dst}"

    def test_no_labels_on_edges(self):
        cfg = _cfg(self.SOURCE)
        for e in cfg["edges"]:
            assert e["label"] == "", f"Unexpected label: {e}"


# ============================================================
# 2. If-else branching
# ============================================================

class TestIfElse:
    """
    def f(x):
        if x > 0:
            y = 1
        else:
            y = -1
        return y

    Expected flow:
        start → decision(x > 0) → True: process(y=1) → return(y) → end
                                 → False: process(y=-1) → ↑ (merge to return)
    """
    SOURCE = "def f(x):\n    if x > 0:\n        y = 1\n    else:\n        y = -1\n    return y\n"

    def test_has_decision(self):
        types = _types(_cfg(self.SOURCE))
        assert "decision" in types

    def test_decision_label(self):
        cfg = _cfg(self.SOURCE)
        decisions = [n for n in cfg["nodes"] if n["type"] == "decision"]
        assert len(decisions) == 1
        assert "x" in decisions[0]["label"] and "0" in decisions[0]["label"]

    def test_true_false_edges(self):
        cfg = _cfg(self.SOURCE)
        labels = {e["label"] for e in cfg["edges"]}
        assert "True" in labels, f"Missing True edge. Labels: {labels}"
        assert "False" in labels, f"Missing False edge. Labels: {labels}"

    def test_both_branches_have_process(self):
        cfg = _cfg(self.SOURCE)
        processes = [n for n in cfg["nodes"] if n["type"] == "process"]
        assert len(processes) >= 2  # y=1 and y=-1

    def test_both_branches_reach_return(self):
        """Both branches should eventually reach return."""
        cfg = _cfg(self.SOURCE)
        ret_nodes = [n["id"] for n in cfg["nodes"] if n["type"] == "return"]
        assert len(ret_nodes) >= 1
        # Check edges: there should be paths from both process nodes to return
        process_ids = [n["id"] for n in cfg["nodes"] if n["type"] == "process"]
        edge_targets = {e["from"]: e["to"] for e in cfg["edges"]}
        for pid in process_ids:
            # Walk forward from process to see if we reach return
            current = pid
            visited = set()
            found = False
            while current and current not in visited:
                visited.add(current)
                if current in ret_nodes:
                    found = True
                    break
                current = edge_targets.get(current)
            assert found, f"Process {pid} doesn't reach return"


# ============================================================
# 3. For loop
# ============================================================

class TestForLoop:
    """
    def f():
        for i in range(10):
            print(i)

    Expected flow:
        start → loop_start(i in range(10)) → io(print(i)) → loop_end → end
    """
    SOURCE = "def f():\n    for i in range(10):\n        print(i)\n"

    def test_loop_nodes(self):
        types = _types(_cfg(self.SOURCE))
        assert "loop_start" in types
        assert "loop_end" in types

    def test_loop_label(self):
        cfg = _cfg(self.SOURCE)
        starts = [n for n in cfg["nodes"] if n["type"] == "loop_start"]
        assert len(starts) == 1
        assert "i" in starts[0]["label"]
        assert "range" in starts[0]["label"]

    def test_io_inside_loop(self):
        cfg = _cfg(self.SOURCE)
        io_nodes = [n for n in cfg["nodes"] if n["type"] == "io"]
        assert len(io_nodes) == 1
        assert "print" in io_nodes[0]["label"]

    def test_loop_start_before_end(self):
        cfg = _cfg(self.SOURCE)
        types = _types(cfg)
        start_idx = types.index("loop_start")
        end_idx = types.index("loop_end")
        assert start_idx < end_idx

    def test_node_sequence(self):
        types = _types(_cfg(self.SOURCE))
        assert types == ["start", "loop_start", "io", "loop_end", "end"]


# ============================================================
# 4. While loop
# ============================================================

class TestWhileLoop:
    """
    def f(x):
        while x > 0:
            x = x - 1

    Expected flow:
        start → loop_start(x > 0) → process(x = x - 1) → loop_end → end
    """
    SOURCE = "def f(x):\n    while x > 0:\n        x = x - 1\n"

    def test_loop_nodes(self):
        types = _types(_cfg(self.SOURCE))
        assert "loop_start" in types
        assert "loop_end" in types

    def test_condition_in_label(self):
        cfg = _cfg(self.SOURCE)
        starts = [n for n in cfg["nodes"] if n["type"] == "loop_start"]
        assert any("x" in s["label"] and "0" in s["label"] for s in starts)

    def test_node_sequence(self):
        types = _types(_cfg(self.SOURCE))
        assert types == ["start", "loop_start", "process", "loop_end", "end"]


# ============================================================
# 5. Nested if in for
# ============================================================

class TestNestedIfInFor:
    """
    def f(items):
        for item in items:
            if item > 0:
                print(item)
            else:
                print("skip")

    Expected:
        start → loop_start → decision → True: io(print(item))
                                       → False: io(print("skip"))
                → loop_end → end
    """
    SOURCE = (
        "def f(items):\n"
        "    for item in items:\n"
        "        if item > 0:\n"
        "            print(item)\n"
        "        else:\n"
        '            print("skip")\n'
    )

    def test_contains_all_types(self):
        types = set(_types(_cfg(self.SOURCE)))
        assert "loop_start" in types
        assert "loop_end" in types
        assert "decision" in types
        assert "io" in types

    def test_two_io_nodes(self):
        cfg = _cfg(self.SOURCE)
        io_nodes = [n for n in cfg["nodes"] if n["type"] == "io"]
        assert len(io_nodes) == 2

    def test_decision_has_true_false(self):
        cfg = _cfg(self.SOURCE)
        labels = {e["label"] for e in cfg["edges"]}
        assert "True" in labels
        assert "False" in labels

    def test_loop_wraps_decision(self):
        types = _types(_cfg(self.SOURCE))
        ls_idx = types.index("loop_start")
        le_idx = types.index("loop_end")
        dec_idx = types.index("decision")
        assert ls_idx < dec_idx < le_idx


# ============================================================
# 6. Multiple returns
# ============================================================

class TestMultipleReturns:
    """
    def f(x):
        if x > 0:
            return "positive"
        if x < 0:
            return "negative"
        return "zero"

    Expected: 3 return nodes, 2 decision nodes
    """
    SOURCE = (
        "def f(x):\n"
        '    if x > 0:\n        return "positive"\n'
        '    if x < 0:\n        return "negative"\n'
        '    return "zero"\n'
    )

    def test_return_count(self):
        cfg = _cfg(self.SOURCE)
        returns = [n for n in cfg["nodes"] if n["type"] == "return"]
        assert len(returns) == 3

    def test_decision_count(self):
        cfg = _cfg(self.SOURCE)
        decisions = [n for n in cfg["nodes"] if n["type"] == "decision"]
        assert len(decisions) == 2

    def test_return_labels(self):
        cfg = _cfg(self.SOURCE)
        returns = [n["label"] for n in cfg["nodes"] if n["type"] == "return"]
        assert any("positive" in r for r in returns)
        assert any("negative" in r for r in returns)
        assert any("zero" in r for r in returns)


# ============================================================
# 7. Complex real-world function
# ============================================================

class TestRealWorldExtractSymbols:
    """Test with orion-parser's own extract_symbols function."""

    def test_has_expected_structure(self):
        p = Path("src/orionparser/analysis/symbols.py")
        if not p.exists():
            pytest.skip("symbols.py not found")
        from orionparser.registry import get_pipeline
        result = get_pipeline(p).analyze_file(p)
        cf = extract_control_flow(result.ast)

        # extract_symbols is simple: no branches, no loops
        es = cf["functions"]["extract_symbols"]
        types = _types(es)
        assert types[0] == "start"
        assert types[-1] == "end"
        assert "return" in types
        # Should have process nodes for table=SymbolTable() and _walk(...)
        assert _has_label(es, r"table")
        assert _has_label(es, r"_walk")

    def test_walk_has_loop_and_decisions(self):
        p = Path("src/orionparser/analysis/symbols.py")
        if not p.exists():
            pytest.skip("symbols.py not found")
        from orionparser.registry import get_pipeline
        result = get_pipeline(p).analyze_file(p)
        cf = extract_control_flow(result.ast)

        walk = cf["functions"]["_walk"]
        types = set(_types(walk))
        # _walk has: for loop (body iteration) + multiple if/elif checks
        assert "loop_start" in types
        assert "loop_end" in types
        assert "decision" in types
        # Should have many decisions (isinstance check, type checks)
        decisions = [n for n in walk["nodes"] if n["type"] == "decision"]
        assert len(decisions) >= 5, f"Expected 5+ decisions, got {len(decisions)}"

    def test_extract_target_name_has_returns(self):
        p = Path("src/orionparser/analysis/symbols.py")
        if not p.exists():
            pytest.skip("symbols.py not found")
        from orionparser.registry import get_pipeline
        result = get_pipeline(p).analyze_file(p)
        cf = extract_control_flow(result.ast)

        etn = cf["functions"]["_extract_target_name"]
        returns = [n for n in etn["nodes"] if n["type"] == "return"]
        # _extract_target_name has: return target.get("id"), return f"...", return attr, return None
        assert len(returns) >= 3, f"Expected 3+ returns, got {len(returns)}"


# ============================================================
# 8. Edge graph integrity
# ============================================================

class TestGraphIntegrity:
    """Every node should be reachable from start, and end should be reachable."""

    def _check_reachable(self, source: str):
        cfg = _cfg(source)
        # Build adjacency
        adj: dict[str, list[str]] = {}
        for e in cfg["edges"]:
            if e["from"] not in adj:
                adj[e["from"]] = []
            adj[e["from"]] = adj[e["from"]] + [e["to"]]

        # BFS from start
        start_id = cfg["nodes"][0]["id"]
        visited: set[str] = set()
        queue = [start_id]
        while queue:
            n = queue.pop(0)
            if n in visited:
                continue
            visited.add(n)
            for child in adj.get(n, []):
                queue = queue + [child]

        all_ids = {n["id"] for n in cfg["nodes"]}
        unreachable = all_ids - visited
        assert len(unreachable) == 0, f"Unreachable nodes: {unreachable}"

    def test_simple(self):
        self._check_reachable("def f():\n    return 1\n")

    def test_if_else(self):
        self._check_reachable("def f(x):\n    if x:\n        return 1\n    else:\n        return 0\n")

    def test_for_loop(self):
        self._check_reachable("def f():\n    for i in range(3):\n        print(i)\n")

    def test_nested(self):
        self._check_reachable(
            "def f(x):\n"
            "    for i in range(x):\n"
            "        if i > 0:\n"
            "            print(i)\n"
            "    return x\n"
        )

    def test_complex(self):
        self._check_reachable(
            "def f(x):\n"
            "    if x > 0:\n"
            "        for i in range(x):\n"
            "            if i % 2 == 0:\n"
            "                print(i)\n"
            "    else:\n"
            "        while x < 0:\n"
            "            x += 1\n"
            "    return x\n"
        )


# ============================================================
# 9. GUI flowchart rendering with exact node count
# ============================================================

class TestRenderedFlowchart:
    def test_simple_renders_5_nodes(self, qtbot):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel

        result = _parse("def f():\n    x = 1\n    return x\n")
        panel = FlowchartPanel()
        graph = panel.build_graph(result)
        colors = panel.get_node_colors(graph)

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)
        canvas.set_graph(graph, layout="flowchart", node_colors=colors)

        # start, x=1, return, end = 4 visible nodes (no invisible merges)
        assert len(canvas._node_items) == 4

    def test_if_renders_decision_shape(self, qtbot):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas, _FlowchartNodeItem
        from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel

        result = _parse("def f(x):\n    if x:\n        return 1\n    return 0\n")
        panel = FlowchartPanel()
        graph = panel.build_graph(result)
        colors = panel.get_node_colors(graph)

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)
        canvas.set_graph(graph, layout="flowchart", node_colors=colors)

        shapes = {item._shape_type for item in canvas._node_items.values()
                  if isinstance(item, _FlowchartNodeItem)}
        assert "diamond" in shapes  # decision node is diamond

    def test_no_node_at_negative_x(self, qtbot):
        """All nodes must be at x >= 0 (no spilling left of column 0)."""
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel

        source = (
            "def f(x):\n"
            "    if x > 0:\n"
            "        if x > 10:\n"
            "            print('big')\n"
            "        else:\n"
            "            print('small')\n"
            "    else:\n"
            "        print('neg')\n"
            "    return x\n"
        )
        result = _parse(source)
        panel = FlowchartPanel()
        graph = panel.build_graph(result)
        colors = panel.get_node_colors(graph)

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)
        canvas.set_graph(graph, layout="flowchart", node_colors=colors)

        for nid, item in canvas._node_items.items():
            x = item.pos().x() - item._width / 2
            assert x >= -5, f"Node {nid} at x={x}, should be >= 0"

    def test_all_nodes_in_single_column(self, qtbot):
        """All flowchart nodes should be in the same x column (single-column layout)."""
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel

        source = "def f(x):\n    if x > 0:\n        y = 1\n    else:\n        y = -1\n    return y\n"
        result = _parse(source)
        panel = FlowchartPanel()
        graph = panel.build_graph(result)
        colors = panel.get_node_colors(graph)

        canvas = GraphCanvas()
        qtbot.addWidget(canvas)
        canvas.set_graph(graph, layout="flowchart", node_colors=colors)

        x_positions = {round(item.pos().x()) for item in canvas._node_items.values()}
        assert len(x_positions) == 1, f"All nodes should be in 1 column, got x={x_positions}"


def _parse(source: str):
    p = Path(f"_exact_render_{id(source)}.py")
    p.write_text(source, encoding="utf-8")
    try:
        from orionparser.registry import get_pipeline
        return get_pipeline(p).analyze_file(p)
    finally:
        p.unlink(missing_ok=True)
