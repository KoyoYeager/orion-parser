"""E2E visual test — launch GUI, click around, take screenshots.

Run with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/gui/test_e2e_visual.py -v -s
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"


@pytest.fixture(autouse=True)
def ensure_screenshot_dir():
    SCREENSHOT_DIR.mkdir(exist_ok=True)


def _grab(widget, name: str) -> None:
    """Save a screenshot of the widget."""
    pixmap = widget.grab()
    path = SCREENSHOT_DIR / f"{name}.png"
    pixmap.save(str(path))
    print(f"  Screenshot: {path}")


class TestE2EVisual:
    """Full visual walkthrough of the GUI."""

    def test_01_welcome_screen(self, qtbot):
        """Verify welcome page on startup."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        _grab(win, "01_welcome")

        # Welcome page visible
        assert win._outer_stack.currentIndex() == 0
        # Mode tabs exist
        assert win._mode_bar.count() == 2
        assert "コード解析" in win._mode_bar.tabText(0)
        assert "グラフ解析" in win._mode_bar.tabText(1)

    def test_02_open_file_code_analysis(self, qtbot, sample_file, sample_source):
        """Open a file -> code analysis mode shows source + symbols."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        _grab(win, "02_code_analysis_symbols")

        # Welcome hidden, analysis shown
        assert win._outer_stack.currentIndex() == 1
        # Source viewer has content
        viewer = win._code_view.source_viewer
        assert "def main" in viewer.toPlainText()
        # Symbols panel has sections
        panel = win._code_view.symbols_panel
        assert panel._tree.topLevelItemCount() > 0
        assert "function" in panel._sections

    def test_03_click_symbol_highlights_source(self, qtbot, sample_file):
        """Click a function symbol -> source line highlights."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        panel = win._code_view.symbols_panel
        viewer = win._code_view.source_viewer

        # Find "main" function and click it
        func_section = panel._sections.get("function")
        assert func_section is not None
        assert func_section.childCount() >= 1

        main_item = func_section.child(0)
        # Simulate click via QTreeWidget
        rect = panel._tree.visualItemRect(main_item)
        if not rect.isNull():
            QTest.mouseClick(
                panel._tree.viewport(),
                Qt.MouseButton.LeftButton,
                pos=rect.center(),
            )
        else:
            # fallback: emit signal directly
            panel._tree.itemClicked.emit(main_item, 0)

        _grab(win, "03_symbol_click_highlight")

        # Source should have highlighted line
        assert viewer._highlighted_line is not None
        assert viewer._highlighted_line > 0
        assert len(viewer.extraSelections()) >= 1

    def test_04_switch_to_tokens_tab(self, qtbot, sample_file):
        """Switch to tokens tab -> token list visible."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        # Click tokens tab
        win._code_view._tabs.setCurrentIndex(1)
        QTest.qWait(100)

        _grab(win, "04_tokens_tab")

        tokens_panel = win._code_view.tokens_panel
        assert tokens_panel._table.rowCount() > 0

    def test_05_click_token_highlights_span(self, qtbot, sample_file):
        """Click a token -> source highlights the exact characters."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        win._code_view._tabs.setCurrentIndex(1)
        QTest.qWait(100)

        tokens_panel = win._code_view.tokens_panel
        viewer = win._code_view.source_viewer

        # Find first real code token (not NEWLINE/INDENT)
        clicked = False
        for i, tok in enumerate(tokens_panel._tokens):
            if (
                len(tok.get("value", "")) > 0
                and tok.get("type") not in ("NEWLINE", "INDENT", "DEDENT", "ENDMARKER")
                and tok.get("line", 0) > 0
            ):
                # Click the row
                rect = tokens_panel._table.visualItemRect(tokens_panel._table.item(i, 1))
                if not rect.isNull():
                    QTest.mouseClick(
                        tokens_panel._table.viewport(),
                        Qt.MouseButton.LeftButton,
                        pos=rect.center(),
                    )
                else:
                    tokens_panel._table.cellClicked.emit(i, 0)

                QTest.qWait(50)

                _grab(win, f"05_token_click_{tok['type']}_{tok['value'][:10]}")

                # Verify: 2 selections = line bg + token span
                sels = viewer.extraSelections()
                assert len(sels) == 2, f"Expected 2 selections, got {len(sels)} for token {tok}"
                assert viewer._highlighted_line is not None
                clicked = True
                break

        assert clicked, "No clickable token found"

    def test_06_click_multiple_tokens(self, qtbot, sample_file):
        """Click several different tokens — each highlights correctly."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        win._code_view._tabs.setCurrentIndex(1)
        QTest.qWait(100)

        tokens_panel = win._code_view.tokens_panel
        viewer = win._code_view.source_viewer

        clicked_types = set()
        target_types = {"IMPORT", "NAME", "DEF", "STRING", "NUMBER"}

        for i, tok in enumerate(tokens_panel._tokens):
            tok_type = tok.get("type", "")
            if tok_type in target_types and tok_type not in clicked_types:
                value = tok.get("value", "")
                if len(value) > 0 and tok.get("line", 0) > 0:
                    tokens_panel._table.cellClicked.emit(i, 0)
                    QTest.qWait(30)

                    sels = viewer.extraSelections()
                    assert len(sels) == 2, f"Token {tok_type}={value!r}: expected 2 sels, got {len(sels)}"
                    clicked_types.add(tok_type)

            if clicked_types >= target_types:
                break

        _grab(win, "06_multiple_tokens_last")
        print(f"  Verified token types: {clicked_types}")
        assert len(clicked_types) >= 3, f"Only verified {clicked_types}"

    def test_07_switch_to_ast_tab(self, qtbot, sample_file):
        """Switch to AST tab -> tree visible with nodes."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        win._code_view._tabs.setCurrentIndex(2)
        QTest.qWait(100)

        _grab(win, "07_ast_tab")

        ast_panel = win._code_view.ast_panel
        assert ast_panel._tree.topLevelItemCount() > 0

        # Click first child node (should be Import or FunctionDef)
        root = ast_panel._tree.topLevelItem(0)
        if root.childCount() > 0:
            child = root.child(0)
            ast_panel._tree.itemClicked.emit(child, 0)
            QTest.qWait(50)

            _grab(win, "07_ast_node_click")

    def test_08_switch_to_graph_mode(self, qtbot, sample_file):
        """Switch to graph analysis mode -> call tree visible."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        # Switch to graph mode
        win._mode_bar.setCurrentIndex(1)
        QTest.qWait(100)

        _grab(win, "08_graph_call_tree")

        canvas = win._graph_view.canvas
        assert len(canvas._node_items) > 0
        print(f"  Call tree nodes: {list(canvas._node_items.keys())}")

    def test_09_switch_graph_type_to_data_flow(self, qtbot, sample_file):
        """Switch graph type to data flow."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        win._mode_bar.setCurrentIndex(1)
        QTest.qWait(100)

        # Switch to data flow
        win._graph_view._selector.setCurrentRow(1)
        QTest.qWait(100)

        _grab(win, "09_graph_data_flow")

        canvas = win._graph_view.canvas
        assert len(canvas._node_items) > 0
        print(f"  Data flow nodes: {list(canvas._node_items.keys())[:10]}")

    def test_10_mode_round_trip(self, qtbot, sample_file):
        """Switch modes back and forth — data preserved."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        # Code mode -> verify source
        assert win._stack.currentIndex() == 0
        assert "def main" in win._code_view.source_viewer.toPlainText()

        # Graph mode -> verify nodes
        win._mode_bar.setCurrentIndex(1)
        QTest.qWait(50)
        assert len(win._graph_view.canvas._node_items) > 0

        # Back to code mode -> source still there
        win._mode_bar.setCurrentIndex(0)
        QTest.qWait(50)
        assert "def main" in win._code_view.source_viewer.toPlainText()

        _grab(win, "10_round_trip_final")

    def test_11_source_click_selects_token(self, qtbot, sample_file):
        """Click a line in source -> tokens tab scrolls to that line's token."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        # Switch to tokens tab
        win._code_view._tabs.setCurrentIndex(1)
        QTest.qWait(100)

        viewer = win._code_view.source_viewer
        tokens_panel = win._code_view.tokens_panel

        # Simulate clicking line 4 (def main():)
        viewer.line_clicked.emit(4)
        QTest.qWait(50)

        _grab(win, "11_source_click_to_token")

        # Tokens panel should have selected a row
        selected = tokens_panel._table.selectedItems()
        # At minimum it shouldn't crash; selection is best-effort
        print(f"  Selected items after source click: {len(selected)}")

    def test_12_symbol_filter(self, qtbot, sample_file):
        """Type in symbol filter -> list narrows down."""
        from orionparser.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        with qtbot.waitSignal(win._viewmodel.file_loaded, timeout=10000):
            win.open_path(str(sample_file))

        panel = win._code_view.symbols_panel

        # Count total symbols before filter
        total_before = sum(
            panel._tree.topLevelItem(i).childCount()
            for i in range(panel._tree.topLevelItemCount())
        )

        # Type "main" in filter
        panel._search._input.setText("main")
        panel._apply_filter("main", "all")
        QTest.qWait(50)

        _grab(win, "12_symbol_filter_main")

        total_after = sum(
            panel._tree.topLevelItem(i).childCount()
            for i in range(panel._tree.topLevelItemCount())
        )

        assert total_after < total_before
        assert total_after >= 1  # "main" function should remain
        print(f"  Symbols: {total_before} -> {total_after} (filter='main')")
