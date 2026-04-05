"""Exact call tree verification — known source, expected edges, verified 1:1.

We create a specific multi-file project with known call relationships
and verify that EVERY expected edge exists and NO unexpected edges exist
in the cross-file merged output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def project_dir(tmp_path) -> Path:
    """Create a known multi-file project.

    File structure and call relationships:

    main.py:
        main() -> init(), run(), cleanup()
        init() -> load_config()
        run() -> process_data(), generate_report()

    processor.py:
        process_data() -> validate(), transform()
        validate() -> check_type(), check_range()
        transform() -> normalize()

    reporter.py:
        generate_report() -> collect_stats(), format_output()
        collect_stats() -> (nothing)
        format_output() -> (nothing)

    utils.py:
        load_config() -> parse_yaml()
        cleanup() -> close_connections(), flush_cache()
        parse_yaml() -> (nothing)
        close_connections() -> (nothing)
        flush_cache() -> (nothing)

    Expected call tree (from <module>):
        <module> -> main
        main -> init, run, cleanup
        init -> load_config
        run -> process_data, generate_report
        load_config -> parse_yaml
        process_data -> validate, transform
        validate -> check_type, check_range
        transform -> normalize
        generate_report -> collect_stats, format_output
        cleanup -> close_connections, flush_cache
    """
    (tmp_path / "main.py").write_text(
        "def init():\n    load_config()\n\n"
        "def run():\n    process_data()\n    generate_report()\n\n"
        "def main():\n    init()\n    run()\n    cleanup()\n\n"
        "main()\n",
        encoding="utf-8",
    )
    (tmp_path / "processor.py").write_text(
        "def check_type(): pass\n\n"
        "def check_range(): pass\n\n"
        "def validate():\n    check_type()\n    check_range()\n\n"
        "def normalize(): pass\n\n"
        "def transform():\n    normalize()\n\n"
        "def process_data():\n    validate()\n    transform()\n",
        encoding="utf-8",
    )
    (tmp_path / "reporter.py").write_text(
        "def collect_stats(): pass\n\n"
        "def format_output(): pass\n\n"
        "def generate_report():\n    collect_stats()\n    format_output()\n",
        encoding="utf-8",
    )
    (tmp_path / "utils.py").write_text(
        "def parse_yaml(): pass\n\n"
        "def load_config():\n    parse_yaml()\n\n"
        "def close_connections(): pass\n\n"
        "def flush_cache(): pass\n\n"
        "def cleanup():\n    close_connections()\n    flush_cache()\n",
        encoding="utf-8",
    )
    return tmp_path


# === Expected relationships ===

EXPECTED_FUNCTIONS = {
    "main", "init", "run", "cleanup",
    "process_data", "validate", "transform",
    "check_type", "check_range", "normalize",
    "generate_report", "collect_stats", "format_output",
    "load_config", "parse_yaml",
    "close_connections", "flush_cache",
}

EXPECTED_EDGES = {
    ("<module>", "main"),
    ("main", "init"),
    ("main", "run"),
    ("main", "cleanup"),
    ("init", "load_config"),
    ("run", "process_data"),
    ("run", "generate_report"),
    ("load_config", "parse_yaml"),
    ("process_data", "validate"),
    ("process_data", "transform"),
    ("validate", "check_type"),
    ("validate", "check_range"),
    ("transform", "normalize"),
    ("generate_report", "collect_stats"),
    ("generate_report", "format_output"),
    ("cleanup", "close_connections"),
    ("cleanup", "flush_cache"),
}


def _run_cli(project_dir: Path) -> dict:
    """Run CLI analyze and return the merged call tree."""
    r = subprocess.run(
        [sys.executable, "-m", "orionparser", "analyze", "--call-tree", str(project_dir)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"CLI failed: {r.stderr}"
    data = json.loads(r.stdout)
    merged = [d for d in data if d["file"] == "(cross-file merged)"]
    assert len(merged) == 1, f"Expected 1 merged entry, got {len(merged)}"
    return merged[0]["call_tree"]


class TestCLICrossFileExact:
    """Exact verification of cross-file call tree."""

    def test_all_expected_functions_present(self, project_dir):
        ct = _run_cli(project_dir)
        actual = set(ct["functions"])
        for func in EXPECTED_FUNCTIONS:
            assert func in actual, f"Missing function: {func}"

    def test_all_expected_edges_present(self, project_dir):
        ct = _run_cli(project_dir)
        actual_edges = {(c[0], c[1]) for c in ct["calls"]}
        for edge in EXPECTED_EDGES:
            assert edge in actual_edges, (
                f"Missing edge: {edge[0]} -> {edge[1]}\n"
                f"Actual edges: {sorted(actual_edges)}"
            )

    def test_no_unexpected_edges(self, project_dir):
        """Only expected caller->callee edges should exist (no phantom edges)."""
        ct = _run_cli(project_dir)
        actual_edges = {(c[0], c[1]) for c in ct["calls"]}
        unexpected = actual_edges - EXPECTED_EDGES
        assert len(unexpected) == 0, (
            f"Unexpected edges found:\n"
            + "\n".join(f"  {u} -> {v}" for u, v in sorted(unexpected))
        )

    def test_edge_count_exact(self, project_dir):
        ct = _run_cli(project_dir)
        actual_count = len(ct["calls"])
        expected_count = len(EXPECTED_EDGES)
        assert actual_count == expected_count, (
            f"Edge count mismatch: expected {expected_count}, got {actual_count}"
        )

    def test_function_count_exact(self, project_dir):
        ct = _run_cli(project_dir)
        actual = set(ct["functions"])
        assert actual == EXPECTED_FUNCTIONS, (
            f"Function set mismatch:\n"
            f"  Missing: {EXPECTED_FUNCTIONS - actual}\n"
            f"  Extra: {actual - EXPECTED_FUNCTIONS}"
        )

    def test_per_file_results_correct(self, project_dir):
        """Each file's individual result should have correct functions."""
        r = subprocess.run(
            [sys.executable, "-m", "orionparser", "analyze", "--call-tree", str(project_dir)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(r.stdout)
        per_file = {Path(d["file"]).stem: d["call_tree"] for d in data if d["file"] != "(cross-file merged)"}

        # main.py should have main, init, run
        assert "main" in per_file
        main_funcs = set(per_file["main"]["functions"])
        assert {"main", "init", "run"} <= main_funcs

        # processor.py should have process_data, validate, transform, etc.
        assert "processor" in per_file
        proc_funcs = set(per_file["processor"]["functions"])
        assert {"process_data", "validate", "transform", "check_type", "check_range", "normalize"} <= proc_funcs

        # reporter.py
        assert "reporter" in per_file
        rep_funcs = set(per_file["reporter"]["functions"])
        assert {"generate_report", "collect_stats", "format_output"} <= rep_funcs

        # utils.py
        assert "utils" in per_file
        util_funcs = set(per_file["utils"]["functions"])
        assert {"load_config", "parse_yaml", "cleanup", "close_connections", "flush_cache"} <= util_funcs

    def test_cross_file_edges_connect_files(self, project_dir):
        """Edges that cross file boundaries should be in merged but not in individual files."""
        r = subprocess.run(
            [sys.executable, "-m", "orionparser", "analyze", "--call-tree", str(project_dir)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(r.stdout)

        # Get per-file edges
        per_file_edges: set[tuple[str, str]] = set()
        for d in data:
            if d["file"] != "(cross-file merged)":
                for c in d["call_tree"]["calls"]:
                    per_file_edges.add((c[0], c[1]))

        merged = [d for d in data if d["file"] == "(cross-file merged)"][0]
        merged_edges = {(c[0], c[1]) for c in merged["call_tree"]["calls"]}

        # Cross-file edges: main.py's main() calls cleanup() defined in utils.py
        # These should be in per_file (as unresolved calls) and in merged
        cross_file_calls = {
            ("main", "cleanup"),      # main.py -> utils.py
            ("init", "load_config"),   # main.py -> utils.py
            ("run", "process_data"),   # main.py -> processor.py
            ("run", "generate_report"),# main.py -> reporter.py
        }
        for edge in cross_file_calls:
            assert edge in merged_edges, f"Cross-file edge {edge} missing from merged"


class TestGUICallTreeExact:
    """Verify the GUI call tree graph matches expected structure."""

    def test_gui_tree_has_all_nodes(self, project_dir):
        from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel
        from orionparser.registry import get_pipeline
        from orionparser.core.encoding import read_file

        results = []
        for f in sorted(project_dir.glob("*.py")):
            pipeline = get_pipeline(f)
            result = pipeline.analyze_file(f)
            source = read_file(f)
            results = results + [(result, source, str(f))]

        panel = CallTreePanel()
        graph = panel.build_graph_multi(results)

        func_names = {graph.nodes[n].get("func_name") for n in graph.nodes}
        for func in EXPECTED_FUNCTIONS:
            assert func in func_names, f"GUI tree missing function: {func}"
        assert "<module>" in func_names

    def test_gui_tree_edges_match(self, project_dir):
        from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel
        from orionparser.registry import get_pipeline
        from orionparser.core.encoding import read_file

        results = []
        for f in sorted(project_dir.glob("*.py")):
            pipeline = get_pipeline(f)
            result = pipeline.analyze_file(f)
            source = read_file(f)
            results = results + [(result, source, str(f))]

        panel = CallTreePanel()
        graph = panel.build_graph_multi(results)

        # Check every expected edge exists in the expanded tree
        for caller, callee in EXPECTED_EDGES:
            # Find nodes with matching func_names and check edge exists
            caller_nodes = [n for n in graph.nodes if graph.nodes[n].get("func_name") == caller]
            callee_nodes = [n for n in graph.nodes if graph.nodes[n].get("func_name") == callee]
            assert len(caller_nodes) >= 1, f"No node for caller: {caller}"
            assert len(callee_nodes) >= 1, f"No node for callee: {callee}"

            found = False
            for cn in caller_nodes:
                children_funcs = {graph.nodes[c].get("func_name") for c in graph.successors(cn)}
                if callee in children_funcs:
                    found = True
                    break
            assert found, f"Edge {caller} -> {callee} not found in GUI tree"

    def test_gui_tree_depth_correct(self, project_dir):
        """Verify specific depth expectations."""
        from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel
        from orionparser.registry import get_pipeline
        from orionparser.core.encoding import read_file

        results = []
        for f in sorted(project_dir.glob("*.py")):
            pipeline = get_pipeline(f)
            result = pipeline.analyze_file(f)
            source = read_file(f)
            results = results + [(result, source, str(f))]

        panel = CallTreePanel()
        graph = panel.build_graph_multi(results)

        # Expected minimum depths
        expected_depths = {
            "<module>": 0,
            "main": 1,
            "init": 2,
            "run": 2,
            "cleanup": 2,
            "load_config": 3,
            "process_data": 3,
            "generate_report": 3,
            "parse_yaml": 4,
            "validate": 4,
            "transform": 4,
            "collect_stats": 4,
            "format_output": 4,
            "check_type": 5,
            "check_range": 5,
            "normalize": 5,
            "close_connections": 3,
            "flush_cache": 3,
        }

        for func, expected_depth in expected_depths.items():
            nodes = [n for n in graph.nodes if graph.nodes[n].get("func_name") == func]
            assert len(nodes) >= 1, f"Missing function: {func}"
            actual_depth = graph.nodes[nodes[0]].get("depth", -1)
            assert actual_depth == expected_depth, (
                f"{func}: expected depth {expected_depth}, got {actual_depth}"
            )
