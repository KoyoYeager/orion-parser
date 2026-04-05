"""Reusable filter / search bar widget."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QWidget


class SearchBar(QWidget):
    """Search bar with text input and optional category dropdown."""

    filter_changed = Signal(str, str)  # (text, category)

    def __init__(
        self,
        placeholder: str = "検索...",
        categories: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._input = QLineEdit()
        self._input.setPlaceholderText(placeholder)
        self._input.setClearButtonEnabled(True)
        layout.addWidget(self._input)

        self._combo: QComboBox | None = None
        if categories:
            self._combo = QComboBox()
            self._combo.addItem("すべて", "all")
            for cat in categories:
                self._combo.addItem(cat, cat)
            self._combo.currentIndexChanged.connect(self._emit_filter)
            layout.addWidget(self._combo)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._emit_filter)
        self._input.textChanged.connect(lambda _: self._debounce.start())

    @property
    def text(self) -> str:
        return self._input.text()

    @property
    def category(self) -> str:
        if self._combo is None:
            return "all"
        return self._combo.currentData() or "all"

    def _emit_filter(self) -> None:
        self.filter_changed.emit(self.text, self.category)
