"""Tests for analysis panels."""

from __future__ import annotations

import pytest


class TestSymbolsPanel:
    def test_set_data_populates_tree(self, qtbot, sample_result, sample_source):
        from orionparser.gui.panels.symbols_panel import SymbolsPanel

        panel = SymbolsPanel()
        qtbot.addWidget(panel)
        panel.set_data(sample_result, sample_source)

        # Should have sections (functions, classes, variables, imports)
        assert panel._tree.topLevelItemCount() > 0

    def test_has_function_section(self, qtbot, sample_result, sample_source):
        from orionparser.gui.panels.symbols_panel import SymbolsPanel

        panel = SymbolsPanel()
        qtbot.addWidget(panel)
        panel.set_data(sample_result, sample_source)

        assert "function" in panel._sections

    def test_has_class_section(self, qtbot, sample_result, sample_source):
        from orionparser.gui.panels.symbols_panel import SymbolsPanel

        panel = SymbolsPanel()
        qtbot.addWidget(panel)
        panel.set_data(sample_result, sample_source)

        assert "class" in panel._sections

    def test_source_line_requested_on_click(self, qtbot, sample_result, sample_source):
        from orionparser.gui.panels.symbols_panel import SymbolsPanel

        panel = SymbolsPanel()
        qtbot.addWidget(panel)
        panel.set_data(sample_result, sample_source)

        # Find a function item and click it
        func_section = panel._sections.get("function")
        if func_section and func_section.childCount() > 0:
            child = func_section.child(0)
            with qtbot.waitSignal(panel.source_line_requested, timeout=1000):
                panel._tree.itemClicked.emit(child, 0)

    def test_clear(self, qtbot, sample_result, sample_source):
        from orionparser.gui.panels.symbols_panel import SymbolsPanel

        panel = SymbolsPanel()
        qtbot.addWidget(panel)
        panel.set_data(sample_result, sample_source)
        panel.clear()
        assert panel._tree.topLevelItemCount() == 0

    def test_filter(self, qtbot, sample_result, sample_source):
        from orionparser.gui.panels.symbols_panel import SymbolsPanel

        panel = SymbolsPanel()
        qtbot.addWidget(panel)
        panel.set_data(sample_result, sample_source)

        # Filter by "main"
        panel._search._input.setText("main")
        panel._apply_filter("main", "all")

        # Should have fewer items
        total = 0
        for i in range(panel._tree.topLevelItemCount()):
            total += panel._tree.topLevelItem(i).childCount()
        assert total >= 1  # at least "main" function


class TestTokensPanel:
    def test_set_data_populates_table(self, qtbot, sample_result, sample_source):
        from orionparser.gui.panels.tokens_panel import TokensPanel

        panel = TokensPanel()
        qtbot.addWidget(panel)
        panel.set_data(sample_result, sample_source)

        assert panel._table.rowCount() > 0

    def test_source_line_requested(self, qtbot, sample_result, sample_source):
        from orionparser.gui.panels.tokens_panel import TokensPanel

        panel = TokensPanel()
        qtbot.addWidget(panel)
        panel.set_data(sample_result, sample_source)

        # Click first row with lineno > 0
        for i, tok in enumerate(panel._tokens):
            if tok.get("lineno", 0) > 0:
                with qtbot.waitSignal(panel.source_line_requested, timeout=1000):
                    panel._table.cellClicked.emit(i, 0)
                break

    def test_clear(self, qtbot, sample_result, sample_source):
        from orionparser.gui.panels.tokens_panel import TokensPanel

        panel = TokensPanel()
        qtbot.addWidget(panel)
        panel.set_data(sample_result, sample_source)
        panel.clear()
        assert panel._table.rowCount() == 0


class TestASTPanel:
    def test_set_data_populates_tree(self, qtbot, sample_result, sample_source):
        from orionparser.gui.panels.ast_panel import ASTPanel

        panel = ASTPanel()
        qtbot.addWidget(panel)
        panel.set_data(sample_result, sample_source)

        assert panel._tree.topLevelItemCount() > 0

    def test_source_line_requested_on_click(self, qtbot, sample_result, sample_source):
        from orionparser.gui.panels.ast_panel import ASTPanel

        panel = ASTPanel()
        qtbot.addWidget(panel)
        panel.set_data(sample_result, sample_source)

        # Find a node with a line number
        root = panel._tree.topLevelItem(0)
        if root and root.childCount() > 0:
            for i in range(root.childCount()):
                child = root.child(i)
                line = child.data(0, 0x0100)  # UserRole
                if isinstance(line, int) and line > 0:
                    with qtbot.waitSignal(panel.source_line_requested, timeout=1000):
                        panel._tree.itemClicked.emit(child, 0)
                    break

    def test_clear(self, qtbot, sample_result, sample_source):
        from orionparser.gui.panels.ast_panel import ASTPanel

        panel = ASTPanel()
        qtbot.addWidget(panel)
        panel.set_data(sample_result, sample_source)
        panel.clear()
        assert panel._tree.topLevelItemCount() == 0


class TestCallTreePanel:
    def test_build_graph(self, sample_result):
        from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel

        panel = CallTreePanel()
        graph = panel.build_graph(sample_result)
        assert graph is not None
        assert len(graph.nodes) > 0

    def test_get_detail_text(self, sample_result):
        from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel

        panel = CallTreePanel()
        graph = panel.build_graph(sample_result)
        text = panel.get_detail_text("<module>", graph)
        assert "<module>" in text


class TestDataFlowPanel:
    def test_build_graph(self, sample_result):
        from orionparser.gui.panels.graph_panels.data_flow_panel import DataFlowPanel

        panel = DataFlowPanel()
        graph = panel.build_graph(sample_result)
        assert graph is not None
        assert len(graph.nodes) > 0

    def test_get_detail_text(self, sample_result):
        from orionparser.gui.panels.graph_panels.data_flow_panel import DataFlowPanel

        panel = DataFlowPanel()
        graph = panel.build_graph(sample_result)
        # Pick first node
        node = list(graph.nodes)[0]
        text = panel.get_detail_text(node, graph)
        assert len(text) > 0
