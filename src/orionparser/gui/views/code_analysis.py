"""Code Analysis mode — source viewer + sub-tabs (symbols, tokens, AST)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QTabWidget, QVBoxLayout, QWidget

from orionparser.gui.panels.ast_panel import ASTPanel
from orionparser.gui.panels.base_panel import BasePanel
from orionparser.gui.panels.symbols_panel import SymbolsPanel
from orionparser.gui.panels.tokens_panel import TokensPanel
from orionparser.gui.widgets.source_viewer import SourceViewer


class CodeAnalysisView(QWidget):
    """Two-pane view: source code (left) + analysis sub-tabs (right)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left: source viewer
        self.source_viewer = SourceViewer()
        splitter.addWidget(self.source_viewer)

        # Right: sub-tabs
        self._tabs = QTabWidget()
        self.symbols_panel = SymbolsPanel()
        self.tokens_panel = TokensPanel()
        self.ast_panel = ASTPanel()

        self._tabs.addTab(self.symbols_panel, "シンボル一覧")
        self._tabs.addTab(self.tokens_panel, "トークン")
        self._tabs.addTab(self.ast_panel, "AST")
        splitter.addWidget(self._tabs)

        splitter.setSizes([450, 550])

        # Bidirectional linking: panels -> source
        self._panels: list[BasePanel] = [self.symbols_panel, self.tokens_panel, self.ast_panel]
        for panel in self._panels:
            panel.source_line_requested.connect(self.source_viewer.highlight_line)
            panel.source_span_requested.connect(self.source_viewer.highlight_span)

        # Bidirectional linking: source -> active panel
        self.source_viewer.line_clicked.connect(self._on_source_line_clicked)

    def set_data(self, result: object, source: str) -> None:
        """Populate all sub-panels with analysis result."""
        self.source_viewer.set_source(source)
        for panel in self._panels:
            panel.set_data(result, source)

    def clear(self) -> None:
        self.source_viewer.clear()
        for panel in self._panels:
            panel.clear()

    def _on_source_line_clicked(self, line: int) -> None:
        active = self._tabs.currentWidget()
        if isinstance(active, BasePanel):
            active.highlight_for_line(line)
