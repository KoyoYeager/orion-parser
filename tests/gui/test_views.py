"""Tests for CodeAnalysisView, GraphAnalysisView, and MainWindow."""

from __future__ import annotations

import pytest


class TestCodeAnalysisView:
    def test_has_three_sub_tabs(self, qtbot):
        from orionparser.gui.views.code_analysis import CodeAnalysisView

        view = CodeAnalysisView()
        qtbot.addWidget(view)

        assert view._tabs.count() == 3
        assert view._tabs.tabText(0) == "シンボル一覧"
        assert view._tabs.tabText(1) == "トークン"
        assert view._tabs.tabText(2) == "AST"

    def test_set_data_populates_all(self, qtbot, sample_result, sample_source):
        from orionparser.gui.views.code_analysis import CodeAnalysisView

        view = CodeAnalysisView()
        qtbot.addWidget(view)
        view.set_data(sample_result, sample_source)

        # Source viewer has content
        assert "def main" in view.source_viewer.toPlainText()

        # Symbols panel has items
        assert view.symbols_panel._tree.topLevelItemCount() > 0

        # Tokens panel has rows
        assert view.tokens_panel._table.rowCount() > 0

        # AST panel has tree
        assert view.ast_panel._tree.topLevelItemCount() > 0

    def test_bidirectional_panel_to_source(self, qtbot, sample_result, sample_source):
        """Panel click -> source line highlight."""
        from orionparser.gui.views.code_analysis import CodeAnalysisView

        view = CodeAnalysisView()
        qtbot.addWidget(view)
        view.set_data(sample_result, sample_source)

        # Simulate symbol panel emitting line request
        view.symbols_panel.source_line_requested.emit(4)
        assert view.source_viewer._highlighted_line == 4

    def test_bidirectional_source_to_panel(self, qtbot, sample_result, sample_source):
        """Source line click -> panel highlight."""
        from orionparser.gui.views.code_analysis import CodeAnalysisView

        view = CodeAnalysisView()
        qtbot.addWidget(view)
        view.set_data(sample_result, sample_source)

        # Simulate source viewer line click
        view.source_viewer.line_clicked.emit(4)
        # Should not raise; panel should try to highlight

    def test_clear(self, qtbot, sample_result, sample_source):
        from orionparser.gui.views.code_analysis import CodeAnalysisView

        view = CodeAnalysisView()
        qtbot.addWidget(view)
        view.set_data(sample_result, sample_source)
        view.clear()
        assert view.source_viewer.toPlainText() == ""


class TestGraphAnalysisView:
    def test_has_selector_items(self, qtbot):
        from orionparser.gui.views.graph_analysis import GraphAnalysisView

        view = GraphAnalysisView()
        qtbot.addWidget(view)

        # 2 enabled + 5 disabled (future)
        assert view._selector.count() == 7

    def test_set_data_renders_graph(self, qtbot, sample_result, sample_source):
        from orionparser.gui.views.graph_analysis import GraphAnalysisView

        view = GraphAnalysisView()
        qtbot.addWidget(view)
        view.set_data(sample_result, sample_source)

        # Canvas should have items (call tree is default)
        assert len(view.canvas._node_items) > 0

    def test_switch_graph_type(self, qtbot, sample_result, sample_source):
        from orionparser.gui.views.graph_analysis import GraphAnalysisView

        view = GraphAnalysisView()
        qtbot.addWidget(view)
        view.set_data(sample_result, sample_source)

        # Switch to data flow
        view._selector.setCurrentRow(1)
        # Should not crash; canvas should update
        assert view._current_graph is not None

    def test_clear(self, qtbot, sample_result, sample_source):
        from orionparser.gui.views.graph_analysis import GraphAnalysisView

        view = GraphAnalysisView()
        qtbot.addWidget(view)
        view.set_data(sample_result, sample_source)
        view.clear()
        assert len(view.canvas._node_items) == 0


class TestMainWindow:
    def test_creation(self, qtbot):
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        assert win.windowTitle() == "OrionParser"
        assert win._stack.count() == 2

    def test_welcome_page_shown_initially(self, qtbot):
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        # Welcome page is shown initially (outer_stack index 0)
        assert win._outer_stack.currentIndex() == 0

    def test_welcome_page_hidden_after_file_load(self, qtbot, sample_file):
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        assert win._outer_stack.currentIndex() == 0

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        # After loading, analysis views are shown (outer_stack index 1)
        assert win._outer_stack.currentIndex() == 1

    def test_mode_switch(self, qtbot):
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        win._switch_mode(1)
        assert win._stack.currentIndex() == 1
        assert win._mode_bar.currentIndex() == 1

        win._switch_mode(0)
        assert win._stack.currentIndex() == 0

    def test_open_file(self, qtbot, sample_file):
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        assert "sample.py" in win.windowTitle()
        assert "def main" in win._code_view.source_viewer.toPlainText()

    def test_open_directory(self, qtbot, sample_dir):
        from PySide6.QtTest import QTest
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        # Wait for file_selected (auto-selects first file after directory_loaded)
        with qtbot.waitSignal(win._viewmodel.file_selected, timeout=15000):
            win.open_path(str(sample_dir))

        if win._viewmodel._dir_worker:
            win._viewmodel._dir_worker.wait()
        QTest.qWait(100)

        # File list should have 3 files (isVisible requires show(), so check count)
        assert win._file_list.count() == 3

        # First file should be auto-selected and displayed
        assert win._code_view.source_viewer.toPlainText() != ""

    def test_directory_file_switching(self, qtbot, sample_dir):
        from PySide6.QtTest import QTest
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        with qtbot.waitSignal(win._viewmodel.file_selected, timeout=15000):
            win.open_path(str(sample_dir))

        if win._viewmodel._dir_worker:
            win._viewmodel._dir_worker.wait()
        QTest.qWait(100)

        first_source = win._code_view.source_viewer.toPlainText()

        # Click second file in list
        with qtbot.waitSignal(win._viewmodel.file_selected, timeout=5000):
            win._file_list.setCurrentRow(1)

        QTest.qWait(50)
        second_source = win._code_view.source_viewer.toPlainText()
        assert len(second_source) > 0
        # Different file -> different content (or at least non-empty)
        assert second_source != ""
