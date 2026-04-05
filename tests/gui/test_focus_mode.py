"""Tests for function-focused call tree — searchable dropdown."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest


COMPLEX_SOURCE = (
    "def validate_config(): pass\n"
    "def load_config():\n    validate_config()\n"
    "def init():\n    load_config()\n"
    "def validate_input(): pass\n"
    "def transform():\n    validate_input()\n"
    "def write_file(): pass\n"
    "def save():\n    write_file()\n"
    "def process():\n    transform()\n    save()\n"
    "def close_db(): pass\n"
    "def log_result(): pass\n"
    "def cleanup():\n    close_db()\n    log_result()\n"
    "def main():\n    init()\n    process()\n    cleanup()\n"
    "main()\n"
)


@pytest.fixture
def graph_view(qtbot):
    from orionparser.gui.views.graph_analysis import GraphAnalysisView
    from orionparser.registry import get_pipeline

    p = Path("_test_focus_view.py")
    p.write_text(COMPLEX_SOURCE, encoding="utf-8")
    try:
        pipeline = get_pipeline(p)
        result = pipeline.analyze_file(p)
    finally:
        p.unlink(missing_ok=True)

    view = GraphAnalysisView()
    qtbot.addWidget(view)
    view.set_data(result, COMPLEX_SOURCE)
    return view


def _select_func(view, func_name: str) -> None:
    """Select a function from the combo dropdown."""
    combo = view._focus_combo
    for i in range(combo.count()):
        if combo.itemData(i) == func_name:
            combo.setCurrentIndex(i)
            view._on_focus_selected(i)
            return
    raise ValueError(f"'{func_name}' not in combo")


def _set_mode(view, mode_data: str) -> None:
    for i in range(view._focus_mode.count()):
        if view._focus_mode.itemData(i) == mode_data:
            view._focus_mode.setCurrentIndex(i)
            return


def _focused_funcs(view) -> set[str]:
    sub = view._current_graph
    if sub is None:
        return set()
    return {sub.nodes[n].get("func_name") for n in sub.nodes}


class TestFocusUI:
    def test_combo_has_functions(self, graph_view):
        combo = graph_view._focus_combo
        items = [combo.itemText(i) for i in range(combo.count())]
        assert "(全体を表示)" in items
        assert "main" in items
        assert "process" in items

    def test_combo_is_editable(self, graph_view):
        assert graph_view._focus_combo.isEditable()

    def test_combo_has_completer(self, graph_view):
        completer = graph_view._focus_combo.completer()
        assert completer is not None

    def test_file_dropdown_exists(self, graph_view):
        """File dropdown should exist with '(すべてのファイル)' default."""
        combo = graph_view._focus_file
        assert combo.count() >= 1
        assert "すべて" in combo.itemText(0)


class TestDescendantsMode:
    def test_process_descendants(self, graph_view):
        _set_mode(graph_view, "descendants")
        _select_func(graph_view, "process")
        funcs = _focused_funcs(graph_view)
        assert "process" in funcs
        assert "transform" in funcs
        assert "save" in funcs
        assert "init" not in funcs

    def test_leaf_shows_only_itself(self, graph_view):
        _set_mode(graph_view, "descendants")
        _select_func(graph_view, "write_file")
        funcs = _focused_funcs(graph_view)
        assert funcs == {"write_file"}


class TestAncestorsDescendantsMode:
    def test_transform_path(self, graph_view):
        _set_mode(graph_view, "ancestors_descendants")
        _select_func(graph_view, "transform")
        funcs = _focused_funcs(graph_view)
        assert "<module>" in funcs
        assert "main" in funcs
        assert "process" in funcs
        assert "transform" in funcs
        assert "cleanup" not in funcs


class TestAutoApply:
    def test_selecting_function_reduces_nodes(self, graph_view):
        full_count = len(graph_view.canvas._node_items)
        _set_mode(graph_view, "descendants")
        _select_func(graph_view, "write_file")
        assert len(graph_view.canvas._node_items) < full_count

    def test_selecting_all_resets(self, graph_view):
        full_count = len(graph_view.canvas._node_items)
        _set_mode(graph_view, "descendants")
        _select_func(graph_view, "write_file")
        # Reset
        graph_view._focus_combo.setCurrentIndex(0)
        graph_view._on_focus_selected(0)
        assert len(graph_view.canvas._node_items) == full_count

    def test_changing_mode_reapplies(self, graph_view):
        _set_mode(graph_view, "descendants")
        _select_func(graph_view, "process")
        count_desc = len(graph_view.canvas._node_items)
        _set_mode(graph_view, "ancestors_descendants")
        count_anc = len(graph_view.canvas._node_items)
        assert count_anc > count_desc


class TestFocusDepth:
    def test_focused_depths_start_at_zero(self, graph_view):
        _set_mode(graph_view, "descendants")
        _select_func(graph_view, "process")
        sub = graph_view._current_graph
        min_depth = min(sub.nodes[n].get("depth", 99) for n in sub.nodes)
        assert min_depth == 0

    def test_focused_depth_invariant(self, graph_view):
        _set_mode(graph_view, "ancestors_descendants")
        _select_func(graph_view, "main")
        sub = graph_view._current_graph
        for u, v in sub.edges:
            ud = sub.nodes[u].get("depth", -1)
            vd = sub.nodes[v].get("depth", -1)
            assert vd == ud + 1
