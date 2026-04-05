"""Source code viewer with line numbers, syntax highlight, and line highlighting."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget


class _LineNumberArea(QWidget):
    """Line number gutter for SourceViewer."""

    def __init__(self, editor: SourceViewer) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return self._editor._line_number_area_size()

    def paintEvent(self, event):
        if self.width() > 0 and self.height() > 0:
            try:
                self._editor._paint_line_numbers(event)
            except Exception:
                pass  # suppress any paint errors silently


class SourceViewer(QPlainTextEdit):
    """Read-only source code viewer with line numbers and highlighting."""

    line_clicked = Signal(int)  # 1-based line number

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 12))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(40)

        self._line_area = _LineNumberArea(self)
        self._highlighted_line: int | None = None
        self._highlighter = None  # set on first source load

        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self._update_line_area_width()

    # --- Public API ---

    def set_source(self, text: str) -> None:
        """Set the displayed source code."""
        self.setPlainText(text)
        self.clear_highlight()

        # Attach syntax highlighter on first use
        if self._highlighter is None:
            from orionparser.gui.widgets.syntax_highlighter import PythonHighlighter
            self._highlighter = PythonHighlighter(self.document())

    def highlight_line(self, line: int) -> None:
        """Highlight the given 1-based line number and scroll to it."""
        self._highlighted_line = line
        self._apply_highlight()
        block = self.document().findBlockByLineNumber(line - 1)
        if block.isValid():
            cursor = QTextCursor(block)
            self.setTextCursor(cursor)
            self.centerCursor()

    def highlight_span(self, position: int, length: int) -> None:
        """Highlight a character range and scroll to it.

        Args:
            position: 0-based character offset from file start.
            length: number of characters to highlight.
        """
        if length <= 0:
            return
        doc = self.document()

        cursor = QTextCursor(doc)
        cursor.setPosition(position)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, length)

        # Track the line for line-number gutter highlight
        self._highlighted_line = cursor.blockNumber() + 1

        # Scroll to the position
        self.setTextCursor(cursor)
        self.centerCursor()

        # Build extra selections: line bg + token fg
        from PySide6.QtGui import QTextCharFormat

        sels = []

        # 1) Full-line pale yellow background
        line_cursor = QTextCursor(doc.findBlockByNumber(self._highlighted_line - 1))
        line_cursor.clearSelection()
        line_fmt = QTextCharFormat()
        line_fmt.setBackground(QColor("#FFFDE7"))
        line_fmt.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
        line_sel = QTextEdit.ExtraSelection()
        line_sel.format = line_fmt
        line_sel.cursor = line_cursor
        sels = sels + [line_sel]

        # 2) Token-level bright orange highlight
        token_fmt = QTextCharFormat()
        token_fmt.setBackground(QColor("#FFD54F"))
        token_sel = QTextEdit.ExtraSelection()
        token_sel.format = token_fmt
        token_sel.cursor = cursor
        sels = sels + [token_sel]

        self.setExtraSelections(sels)
        self._line_area.update()

    def clear_highlight(self) -> None:
        """Remove line highlight."""
        self._highlighted_line = None
        self.setExtraSelections([])

    # --- Line number area ---

    def _line_number_area_size(self):
        from PySide6.QtCore import QSize
        digits = max(1, len(str(self.blockCount())))
        width = 14 + self.fontMetrics().horizontalAdvance("9") * digits
        return QSize(width, 0)

    def _update_line_area_width(self) -> None:
        self.setViewportMargins(self._line_number_area_size().width(), 0, 0, 0)

    def _update_line_area(self, rect, dy):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(cr.left(), cr.top(), self._line_number_area_size().width(), cr.height())

    def _paint_line_numbers(self, event) -> None:
        area = self._line_area
        if area.width() <= 0 or area.height() <= 0:
            return

        # Install temporary message handler to suppress QPainter C-level warnings
        from PySide6.QtCore import qInstallMessageHandler

        _orig = [None]

        def _quiet(mode, context, message):
            if "QPainter" in message or "Paint device" in message:
                return
            if _orig[0] is not None:
                _orig[0](mode, context, message)

        _orig[0] = qInstallMessageHandler(_quiet)
        try:
            painter = QPainter()
            if not painter.begin(area):
                return
            try:
                painter.fillRect(event.rect(), QColor("#E8E8E8"))
                block = self.firstVisibleBlock()
                block_number = block.blockNumber()
                top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
                bottom = top + round(self.blockBoundingRect(block).height())

                while block.isValid() and top <= event.rect().bottom():
                    if block.isVisible() and bottom >= event.rect().top():
                        number = str(block_number + 1)
                        if self._highlighted_line is not None and block_number + 1 == self._highlighted_line:
                            painter.setPen(QColor("#0078D4"))
                        else:
                            painter.setPen(QColor("#6E7681"))
                        painter.drawText(
                            0, top, area.width() - 6, self.fontMetrics().height(),
                            Qt.AlignmentFlag.AlignRight, number,
                        )
                    block = block.next()
                    top = bottom
                    bottom = top + round(self.blockBoundingRect(block).height())
                    block_number += 1
            finally:
                painter.end()
        finally:
            qInstallMessageHandler(_orig[0])

    # --- Highlight ---

    def _apply_highlight(self) -> None:
        # Repaint line numbers to update highlighted number
        self._line_area.update()

        if self._highlighted_line is None:
            self.setExtraSelections([])
            return

        block = self.document().findBlockByLineNumber(self._highlighted_line - 1)
        if not block.isValid():
            return

        cursor = QTextCursor(block)
        cursor.clearSelection()

        from PySide6.QtGui import QTextCharFormat
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#FFFDE7"))
        fmt.setProperty(QTextCharFormat.Property.FullWidthSelection, True)

        sel = QTextEdit.ExtraSelection()
        sel.format = fmt
        sel.cursor = cursor
        self.setExtraSelections([sel])

    # --- Mouse click → line number ---

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        cursor = self.cursorForPosition(event.pos())
        line = cursor.blockNumber() + 1
        self.line_clicked.emit(line)
