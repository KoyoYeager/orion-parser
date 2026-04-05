"""Tokens panel — lexer output with color coding."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

from orionparser.gui.panels.base_panel import BasePanel

_CATEGORY_COLORS = {
    "keyword": "#E8F0FE",
    "name": "#FFFFFF",
    "number": "#E6F4EA",
    "string": "#FCE8E6",
    "operator": "#FEF7E0",
    "delimiter": "#F5F5F5",
    "structure": "#ECECEC",
}

_CATEGORY_TEXT_COLORS = {
    "keyword": "#1A44A0",
    "name": "#1E1E1E",
    "number": "#0D652D",
    "string": "#9B1C1C",
    "operator": "#7A5D00",
    "delimiter": "#444444",
    "structure": "#888888",
}

_KEYWORDS = {
    "DEF", "CLASS", "IF", "ELIF", "ELSE", "FOR", "WHILE", "RETURN", "IMPORT",
    "FROM", "AS", "WITH", "TRY", "EXCEPT", "FINALLY", "RAISE", "PASS", "BREAK",
    "CONTINUE", "AND", "OR", "NOT", "IN", "IS", "LAMBDA", "YIELD", "ASYNC",
    "AWAIT", "GLOBAL", "NONLOCAL", "DEL", "ASSERT", "TRUE", "FALSE", "NONE",
}

_STRUCTURE = {"NEWLINE", "INDENT", "DEDENT", "ENDMARKER"}

_DELIMITERS = {
    "LPAREN", "RPAREN", "LSQB", "RSQB", "LBRACE", "RBRACE",
    "COMMA", "COLON", "DOT", "ELLIPSIS", "ARROW",
}

_DISPLAY_MAP = {"NEWLINE": "↵", "INDENT": "→", "DEDENT": "←", "ENDMARKER": "⏎"}


def _classify(token_type: str) -> str:
    if token_type in _KEYWORDS:
        return "keyword"
    if token_type == "NAME":
        return "name"
    if token_type == "NUMBER":
        return "number"
    if token_type == "STRING":
        return "string"
    if token_type in _STRUCTURE:
        return "structure"
    if token_type in _DELIMITERS:
        return "delimiter"
    return "operator"


class TokensPanel(BasePanel):
    """Token list with color-coded categories."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["#", "種別", "値", "行"])
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 45)
        self._table.setColumnWidth(1, 100)
        self._table.setColumnWidth(3, 40)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._table)

        self._tokens: list[dict] = []
        self._source: str = ""

    def set_data(self, result: object, source: str) -> None:
        tokens = getattr(result, "tokens", None) or []
        self._tokens = tokens
        self._source = source
        self._table.setRowCount(len(tokens))

        for i, tok in enumerate(tokens):
            tok_type = tok.get("type", "?")
            tok_value = tok.get("value", "")
            tok_line = tok.get("line", tok.get("lineno", 0))
            category = _classify(tok_type)
            bg = QBrush(QColor(_CATEGORY_COLORS.get(category, "#FFFFFF")))
            fg = QBrush(QColor(_CATEGORY_TEXT_COLORS.get(category, "#1E1E1E")))

            display_value = _DISPLAY_MAP.get(tok_type, tok_value)

            items = [
                QTableWidgetItem(str(i + 1)),
                QTableWidgetItem(tok_type),
                QTableWidgetItem(display_value),
                QTableWidgetItem(str(tok_line) if tok_line else ""),
            ]
            for item in items:
                item.setBackground(bg)
                item.setForeground(fg)
            items[0].setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            items[3].setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            for col, item in enumerate(items):
                self._table.setItem(i, col, item)

    def highlight_for_line(self, line: int) -> None:
        for i, tok in enumerate(self._tokens):
            tok_line = tok.get("line", tok.get("lineno", 0))
            if tok_line >= line:
                self._table.selectRow(i)
                self._table.scrollToItem(self._table.item(i, 0))
                return

    def clear(self) -> None:
        self._table.setRowCount(0)
        self._tokens = []
        self._source = ""

    def _find_token_position(self, tok: dict) -> tuple[int, int] | None:
        """Find (offset, length) of a token in the source text."""
        value = tok.get("value", "")
        if not value or not self._source:
            return None

        line_num = tok.get("line", tok.get("lineno", 0))
        if line_num <= 0:
            return None

        lines = self._source.split("\n")
        if line_num > len(lines):
            return None

        line_offset = sum(len(lines[i]) + 1 for i in range(line_num - 1))
        line_text = lines[line_num - 1]

        # Try single-line match first
        col = line_text.find(value)
        if col >= 0:
            return (line_offset + col, len(value))

        # Multi-line token (e.g. docstring): search from line_offset in full source
        pos = self._source.find(value, line_offset)
        if pos >= 0:
            return (pos, len(value))

        # Fallback: search from beginning
        pos = self._source.find(value)
        if pos >= 0:
            return (pos, len(value))

        return None

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if 0 <= row < len(self._tokens):
            tok = self._tokens[row]
            span = self._find_token_position(tok)
            if span is not None:
                self.source_span_requested.emit(span[0], span[1])
            else:
                line_num = tok.get("line", tok.get("lineno", 0))
                if line_num > 0:
                    self.source_line_requested.emit(line_num)
