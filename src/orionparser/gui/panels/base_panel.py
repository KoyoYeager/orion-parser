"""Base class for code analysis sub-tab panels."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class BasePanel(QWidget):
    """Common interface for all code-analysis sub-tabs."""

    source_line_requested = Signal(int)  # 1-based line to jump to in source
    source_span_requested = Signal(int, int)  # (position, length) — character-level highlight

    def set_data(self, result: object, source: str) -> None:
        """Populate panel with analysis result."""

    def highlight_for_line(self, line: int) -> None:
        """Highlight the item corresponding to the given source line."""

    def clear(self) -> None:
        """Clear all displayed data."""
