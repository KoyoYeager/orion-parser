"""Validate that the call tree hierarchy is correct at every level.

Tests verify:
- Each node is at the expected depth
- Parent-child edges respect depth (parent.depth + 1 == child.depth)
- Cross-file calls maintain correct hierarchy
- Specific known call chains have correct depth sequence
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest


# ============================================================
# Helper
# ============================================================

def _build_tree(source: str):
    """Parse source, build call tree, return (graph, panel)."""
    from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel
    from orionparser.registry import get_pipeline

    p = Path(f"_test_hierarchy_{id(source)}.py")
    p.write_text(source, encoding="utf-8")
    try:
        pipeline = get_pipeline(p)
        result = pipeline.analyze_file(p)
    finally:
        p.unlink(missing_ok=True)

    panel = CallTreePanel()
    graph = panel.build_graph(result)
    return graph, panel


def _build_multi_tree(file_dict: dict[str, str]):
    """Parse multiple files, build cross-file call tree."""
    from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel
    from orionparser.registry import get_pipeline
    from orionparser.core.encoding import read_file

    results = []
    paths = []
    for name, source in file_dict.items():
        p = Path(f"_test_multi_{name}")
        p.write_text(source, encoding="utf-8")
        paths = paths + [p]
        pipeline = get_pipeline(p)
        result = pipeline.analyze_file(p)
        results = results + [(result, source, str(p))]

    panel = CallTreePanel()
    graph = panel.build_graph_multi(results)

    for p in paths:
        p.unlink(missing_ok=True)

    return graph, panel


def _get_depths(graph) -> dict[str, int]:
    """Return {func_name: depth} from graph."""
    depths = {}
    for n in graph.nodes:
        func = graph.nodes[n].get("func_name", str(n))
        depth = graph.nodes[n].get("depth", -1)
        if func not in depths:
            depths[func] = depth
    return depths


def _get_nodes_by_func(graph, func_name: str) -> list[str]:
    """Return all node IDs for a given func_name."""
    return [n for n in graph.nodes if graph.nodes[n].get("func_name") == func_name]


# ============================================================
# Single file hierarchy
# ============================================================

class TestSingleFileHierarchy:
    """Verify depth assignments for single-file call trees."""

    def test_linear_chain_depths(self):
        """<module> -> a -> b -> c: depths 0,1,2,3"""
        graph, _ = _build_tree(
            "def c(): pass\ndef b(): c()\ndef a(): b()\na()\n"
        )
        depths = _get_depths(graph)
        assert depths["<module>"] == 0
        assert depths["a"] == 1
        assert depths["b"] == 2
        assert depths["c"] == 3

    def test_flat_calls_same_depth(self):
        """<module> calls a, b, c directly: all at depth 1"""
        graph, _ = _build_tree(
            "def a(): pass\ndef b(): pass\ndef c(): pass\na()\nb()\nc()\n"
        )
        depths = _get_depths(graph)
        assert depths["<module>"] == 0
        assert depths["a"] == 1
        assert depths["b"] == 1
        assert depths["c"] == 1

    def test_mixed_depth(self):
        """<module> -> main -> (helper, process); process -> helper"""
        graph, _ = _build_tree(
            "def helper(): pass\n"
            "def process():\n    helper()\n"
            "def main():\n    helper()\n    process()\n"
            "main()\n"
        )
        depths = _get_depths(graph)
        assert depths["<module>"] == 0
        assert depths["main"] == 1
        # helper is called from main (depth 2) AND from process (depth 3)
        helper_nodes = _get_nodes_by_func(graph, "helper")
        helper_depths = {graph.nodes[n]["depth"] for n in helper_nodes}
        assert 2 in helper_depths  # called by main
        assert 3 in helper_depths  # called by process

    def test_parent_child_depth_diff_is_one(self):
        """Every edge: parent.depth + 1 == child.depth"""
        graph, _ = _build_tree(
            "def d(): pass\n"
            "def c(): d()\n"
            "def b(): c()\n"
            "def a(): b()\n"
            "a()\n"
        )
        for u, v in graph.edges:
            u_depth = graph.nodes[u]["depth"]
            v_depth = graph.nodes[v]["depth"]
            assert v_depth == u_depth + 1, (
                f"Edge {u}->{v}: parent depth {u_depth}, child depth {v_depth}, "
                f"expected child = {u_depth + 1}"
            )

    def test_5_level_deep(self):
        graph, _ = _build_tree(
            "def e(): pass\n"
            "def d(): e()\n"
            "def c(): d()\n"
            "def b(): c()\n"
            "def a(): b()\n"
            "a()\n"
        )
        depths = _get_depths(graph)
        assert depths["<module>"] == 0
        assert depths["a"] == 1
        assert depths["b"] == 2
        assert depths["c"] == 3
        assert depths["d"] == 4
        assert depths["e"] == 5

    def test_diamond_both_paths_correct(self):
        """a -> b, a -> c, b -> d, c -> d: d appears at depth 3 twice"""
        graph, _ = _build_tree(
            "def d(): pass\n"
            "def b(): d()\n"
            "def c(): d()\n"
            "def a():\n    b()\n    c()\n"
            "a()\n"
        )
        d_nodes = _get_nodes_by_func(graph, "d")
        assert len(d_nodes) == 2
        for dn in d_nodes:
            assert graph.nodes[dn]["depth"] == 3

    def test_recursive_stops_at_ancestor(self):
        """Recursive call should not create infinite depth."""
        graph, _ = _build_tree("def rec(): rec()\nrec()\n")
        depths = _get_depths(graph)
        assert depths["rec"] == 1
        # rec calls rec -> rec#2 is created but NOT further expanded
        rec_nodes = _get_nodes_by_func(graph, "rec")
        assert len(rec_nodes) <= 2  # at most 2 (parent + one child, no infinite)
        max_depth = max(graph.nodes[n]["depth"] for n in rec_nodes)
        assert max_depth <= 2  # doesn't go deeper than 2

    def test_mutual_recursion(self):
        """a -> b -> a: should stop expanding."""
        graph, _ = _build_tree(
            "def b(): a()\ndef a(): b()\na()\n"
        )
        assert len(graph.nodes) < 10  # should not explode

    def test_node_order_matches_depth(self):
        """Node order should have parent before child."""
        graph, _ = _build_tree(
            "def c(): pass\ndef b(): c()\ndef a(): b()\na()\n"
        )
        order = graph.graph.get("node_order", [])
        for u, v in graph.edges:
            u_idx = order.index(u) if u in order else -1
            v_idx = order.index(v) if v in order else -1
            assert u_idx < v_idx, f"Parent {u} (idx {u_idx}) should come before child {v} (idx {v_idx})"


# ============================================================
# Cross-file hierarchy
# ============================================================

class TestCrossFileHierarchy:
    """Verify depth assignments for cross-file call trees."""

    def test_cross_file_linear(self):
        """main.py: main() -> helper(); utils.py: helper() -> validate()"""
        graph, _ = _build_multi_tree({
            "main.py": "def main():\n    helper()\nmain()\n",
            "utils.py": "def helper():\n    validate()\ndef validate():\n    pass\n",
        })
        depths = _get_depths(graph)
        assert depths["<module>"] == 0
        assert depths["main"] == 1
        assert depths["helper"] == 2
        assert depths["validate"] == 3

    def test_cross_file_3_files(self):
        """main -> helper (utils) -> db_query (db)"""
        graph, _ = _build_multi_tree({
            "main.py": "def main():\n    helper()\nmain()\n",
            "utils.py": "def helper():\n    db_query()\n",
            "db.py": "def db_query():\n    pass\n",
        })
        depths = _get_depths(graph)
        assert depths["<module>"] == 0
        assert depths["main"] == 1
        assert depths["helper"] == 2
        assert depths["db_query"] == 3

    def test_cross_file_parent_child_depth_invariant(self):
        """Every edge across files: parent.depth + 1 == child.depth"""
        graph, _ = _build_multi_tree({
            "main.py": "def main():\n    a()\n    b()\nmain()\n",
            "a.py": "def a():\n    c()\n",
            "b.py": "def b():\n    c()\n",
            "c.py": "def c():\n    pass\n",
        })
        for u, v in graph.edges:
            u_depth = graph.nodes[u]["depth"]
            v_depth = graph.nodes[v]["depth"]
            assert v_depth == u_depth + 1, (
                f"Edge {graph.nodes[u].get('label')}->{graph.nodes[v].get('label')}: "
                f"depth {u_depth}->{v_depth}, expected {u_depth + 1}"
            )

    def test_shared_util_across_files_duplicated(self):
        """util() called from file_a and file_b -> appears twice at correct depths"""
        graph, _ = _build_multi_tree({
            "main.py": "def run():\n    fa()\n    fb()\nrun()\n",
            "file_a.py": "def fa():\n    util()\n",
            "file_b.py": "def fb():\n    util()\n",
            "shared.py": "def util():\n    pass\n",
        })
        util_nodes = _get_nodes_by_func(graph, "util")
        assert len(util_nodes) == 2
        # Both should be at depth 3 (module->run->fa/fb->util)
        for un in util_nodes:
            assert graph.nodes[un]["depth"] == 3

    def test_labels_contain_file_prefix(self):
        """Multi-file labels include [filename] prefix."""
        graph, _ = _build_multi_tree({
            "app.py": "def start():\n    pass\nstart()\n",
            "lib.py": "def util():\n    pass\n",
        })
        labels = [graph.nodes[n].get("label", "") for n in graph.nodes]
        file_labels = [l for l in labels if "[" in l]
        assert len(file_labels) >= 1, f"Expected [file] prefix in labels, got {labels}"


# ============================================================
# CLI output hierarchy validation
# ============================================================

class TestCLIHierarchyOutput:
    """Validate that CLI --call-tree output has correct merged edges."""

    def test_cli_merged_edges_form_valid_tree(self, tmp_path):
        import json
        import subprocess
        import sys

        (tmp_path / "a.py").write_text(
            "def top():\n    mid()\ntop()\n", encoding="utf-8"
        )
        (tmp_path / "b.py").write_text(
            "def mid():\n    bottom()\n", encoding="utf-8"
        )
        (tmp_path / "c.py").write_text(
            "def bottom():\n    pass\n", encoding="utf-8"
        )

        result = subprocess.run(
            [sys.executable, "-m", "orionparser", "analyze", "--call-tree", str(tmp_path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        merged = data[-1]
        assert merged["file"] == "(cross-file merged)"

        calls = {(c[0], c[1]) for c in merged["call_tree"]["calls"]}
        assert ("top", "mid") in calls, f"top->mid missing, got {calls}"
        assert ("mid", "bottom") in calls, f"mid->bottom missing, got {calls}"

    def test_cli_single_file_depth_via_graph(self, tmp_path):
        """Single file: verify graph depth matches expected."""
        (tmp_path / "chain.py").write_text(
            "def d(): pass\n"
            "def c(): d()\n"
            "def b(): c()\n"
            "def a(): b()\n"
            "a()\n",
            encoding="utf-8",
        )
        import json
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "orionparser", "analyze", "--call-tree", str(tmp_path / "chain.py")],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        calls = {(c[0], c[1]) for c in data["call_tree"]["calls"]}
        assert ("<module>", "a") in calls
        assert ("a", "b") in calls
        assert ("b", "c") in calls
        assert ("c", "d") in calls
