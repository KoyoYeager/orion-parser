"""Integration tests — full flow through MainWindow."""

from __future__ import annotations

import pytest


class TestFullFlow:
    def test_code_analysis_shows_symbols(self, qtbot, sample_file):
        """Open file -> code analysis mode -> symbols panel has functions."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        # Code analysis mode is default (index 0)
        assert win._stack.currentIndex() == 0

        panel = win._code_view.symbols_panel
        assert "function" in panel._sections
        func_section = panel._sections["function"]
        assert func_section.childCount() >= 1  # at least "main"

    def test_graph_analysis_shows_call_tree(self, qtbot, sample_file):
        """Open file -> graph analysis mode -> call tree nodes visible."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        win._switch_mode(1)
        assert win._stack.currentIndex() == 1

        canvas = win._graph_view.canvas
        assert len(canvas._node_items) > 0

    def test_mode_switch_preserves_data(self, qtbot, sample_file):
        """Switch between modes — data is preserved."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        # Switch to graph
        win._switch_mode(1)
        assert len(win._graph_view.canvas._node_items) > 0

        # Switch back to code
        win._switch_mode(0)
        assert "def main" in win._code_view.source_viewer.toPlainText()

    def test_bidirectional_linking_end_to_end(self, qtbot, sample_file):
        """Symbol click -> source highlight in full window context."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        # Find and click a function symbol
        panel = win._code_view.symbols_panel
        func_section = panel._sections.get("function")
        if func_section and func_section.childCount() > 0:
            child = func_section.child(0)
            panel._tree.itemClicked.emit(child, 0)

            # Source should now have a highlighted line
            viewer = win._code_view.source_viewer
            assert viewer._highlighted_line is not None
            assert viewer._highlighted_line > 0

    def test_token_click_highlights_span(self, qtbot, sample_file):
        """Token click -> source highlights the exact characters."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        # Switch to tokens tab
        win._code_view._tabs.setCurrentWidget(win._code_view.tokens_panel)

        panel = win._code_view.tokens_panel
        viewer = win._code_view.source_viewer

        # Find a token with lexpos (skip structural tokens)
        for i, tok in enumerate(panel._tokens):
            if tok.get("lexpos") is not None and len(tok.get("value", "")) > 0:
                panel._table.cellClicked.emit(i, 0)

                # Should have 2 extra selections (line bg + token span)
                assert len(viewer.extraSelections()) == 2
                assert viewer._highlighted_line is not None
                break

    def test_status_bar_updates(self, qtbot, sample_file):
        """Status bar shows file info after loading."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        status = win._status_label.text()
        assert "sample.py" in status
        assert "関数:" in status
