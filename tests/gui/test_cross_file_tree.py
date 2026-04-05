"""Tests for cross-file (directory) call tree integration."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest


@pytest.fixture
def multi_file_dir(tmp_path) -> Path:
    """Directory with 3 files that call each other."""
    # main.py calls functions from utils.py and db.py
    (tmp_path / "main.py").write_text(
        "from utils import helper\n"
        "from db import connect\n"
        "\n"
        "def main():\n"
        "    helper()\n"
        "    connect()\n"
        "    process()\n"
        "\n"
        "def process():\n"
        "    helper()\n"
        "\n"
        "main()\n",
        encoding="utf-8",
    )
    (tmp_path / "utils.py").write_text(
        "def helper():\n"
        "    validate()\n"
        "\n"
        "def validate():\n"
        "    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "db.py").write_text(
        "def connect():\n"
        "    setup()\n"
        "\n"
        "def setup():\n"
        "    pass\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def parse_dir(multi_file_dir):
    """Parse all files and return results list."""
    from orionparser.registry import get_pipeline
    from orionparser.core.encoding import read_file

    results = []
    for f in sorted(multi_file_dir.glob("*.py")):
        pipeline = get_pipeline(f)
        result = pipeline.analyze_file(f)
        source = read_file(f)
        results = results + [(result, source, str(f))]
    return results


class TestCrossFileCallTree:
    """Call tree should connect functions across files."""

    def test_multi_file_graph_has_all_functions(self, parse_dir):
        from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel

        panel = CallTreePanel()
        graph = panel.build_graph_multi(parse_dir)

        assert graph is not None
        func_names = {graph.nodes[n].get("func_name") for n in graph.nodes}
        assert "main" in func_names
        assert "helper" in func_names
        assert "connect" in func_names
        assert "validate" in func_names
        assert "setup" in func_names
        assert "process" in func_names

    def test_cross_file_edges_exist(self, parse_dir):
        """main() calls helper() (from utils.py) - edge should exist."""
        from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel

        panel = CallTreePanel()
        graph = panel.build_graph_multi(parse_dir)

        # Find main node and check its children include helper
        main_nodes = [n for n in graph.nodes if graph.nodes[n].get("func_name") == "main"]
        assert len(main_nodes) >= 1

        main_children_funcs = set()
        for main_n in main_nodes:
            for child in graph.successors(main_n):
                main_children_funcs.add(graph.nodes[child].get("func_name"))

        assert "helper" in main_children_funcs, f"main should call helper, got {main_children_funcs}"
        assert "connect" in main_children_funcs, f"main should call connect, got {main_children_funcs}"
        assert "process" in main_children_funcs, f"main should call process, got {main_children_funcs}"

    def test_deep_cross_file_chain(self, parse_dir):
        """main -> helper -> validate should form a chain across files."""
        from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel

        panel = CallTreePanel()
        graph = panel.build_graph_multi(parse_dir)

        # Find validate nodes and check they're at depth >= 3
        val_nodes = [n for n in graph.nodes if graph.nodes[n].get("func_name") == "validate"]
        assert len(val_nodes) >= 1
        for vn in val_nodes:
            depth = graph.nodes[vn].get("depth", 0)
            assert depth >= 2, f"validate should be depth >= 2, got {depth}"

    def test_helper_appears_twice(self, parse_dir):
        """helper is called by main and process -> should appear twice."""
        from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel

        panel = CallTreePanel()
        graph = panel.build_graph_multi(parse_dir)

        helper_nodes = [n for n in graph.nodes if graph.nodes[n].get("func_name") == "helper"]
        assert len(helper_nodes) >= 2, f"helper called from 2 places -> 2 nodes, got {len(helper_nodes)}"

    def test_nodes_have_file_attribute(self, parse_dir):
        """In multi-file mode, nodes should have file attribute."""
        from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel

        panel = CallTreePanel()
        graph = panel.build_graph_multi(parse_dir)

        files = {graph.nodes[n].get("file", "") for n in graph.nodes}
        files.discard("")
        assert len(files) >= 2, f"Expected nodes from multiple files, got {files}"

    def test_node_colors_are_set(self, parse_dir):
        from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel

        panel = CallTreePanel()
        graph = panel.build_graph_multi(parse_dir)
        colors = panel.get_node_colors(graph)

        # All nodes should have colors
        for n in graph.nodes:
            assert n in colors or str(n) in colors


class TestDirectoryGraphInMainWindow:
    """Integration: MainWindow directory load -> graph view shows cross-file tree."""

    def test_directory_graph_has_nodes(self, qtbot, multi_file_dir):
        from PySide6.QtTest import QTest
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        with qtbot.waitSignal(win._viewmodel.file_selected, timeout=15000):
            win.open_path(str(multi_file_dir))

        if win._viewmodel._dir_worker:
            win._viewmodel._dir_worker.wait()
        QTest.qWait(200)

        # Switch to graph mode
        win._switch_mode(1)
        QTest.qWait(100)

        canvas = win._graph_view.canvas
        assert len(canvas._node_items) > 3, (
            f"Cross-file tree should have >3 nodes, got {len(canvas._node_items)}"
        )

    def test_directory_graph_has_cross_file_edges(self, qtbot, multi_file_dir):
        from PySide6.QtTest import QTest
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        with qtbot.waitSignal(win._viewmodel.file_selected, timeout=15000):
            win.open_path(str(multi_file_dir))

        if win._viewmodel._dir_worker:
            win._viewmodel._dir_worker.wait()
        QTest.qWait(200)

        win._switch_mode(1)
        QTest.qWait(100)

        graph = win._graph_view._current_graph
        assert graph is not None

        # Should have edges spanning files
        func_names = {graph.nodes[n].get("func_name") for n in graph.nodes}
        assert "main" in func_names
        assert "helper" in func_names
        assert "validate" in func_names

    def test_screenshot(self, qtbot, multi_file_dir):
        from PySide6.QtTest import QTest
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        with qtbot.waitSignal(win._viewmodel.file_selected, timeout=15000):
            win.open_path(str(multi_file_dir))

        if win._viewmodel._dir_worker:
            win._viewmodel._dir_worker.wait()
        QTest.qWait(200)

        win._switch_mode(1)
        QTest.qWait(200)

        ss_dir = Path(__file__).parent / "screenshots" / "cross_file"
        ss_dir.mkdir(parents=True, exist_ok=True)
        win.grab().save(str(ss_dir / "cross_file_call_tree.png"))
        print(f"  Cross-file nodes: {len(win._graph_view.canvas._node_items)}")
