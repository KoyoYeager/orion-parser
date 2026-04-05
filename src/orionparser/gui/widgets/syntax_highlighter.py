"""Python syntax highlighter for the source viewer."""

from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


_KEYWORDS = (
    "False None True and as assert async await break class continue "
    "def del elif else except finally for from global if import in is "
    "lambda nonlocal not or pass raise return try while with yield"
).split()


class PythonHighlighter(QSyntaxHighlighter):
    """Regex-based Python syntax highlighter."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)

        kw_pattern = r"\b(?:" + "|".join(_KEYWORDS) + r")\b"

        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = [
            (re.compile(kw_pattern), _fmt("#0000CC", bold=True)),      # keywords
            (re.compile(r"\bself\b"), _fmt("#D4376E", italic=True)),    # self
            (re.compile(r"@\w+"), _fmt("#9B59B6")),                     # decorators
            (re.compile(r"\b\d+\.?\d*(?:[eE][+-]?\d+)?\b"), _fmt("#098658")),  # numbers
            (re.compile(r'""".*?"""', re.DOTALL), _fmt("#6A9955", italic=True)),  # triple double
            (re.compile(r"'''.*?'''", re.DOTALL), _fmt("#6A9955", italic=True)),  # triple single
            (re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"'), _fmt("#A31515")),  # strings
            (re.compile(r"'[^'\\]*(?:\\.[^'\\]*)*'"), _fmt("#A31515")),  # strings
            (re.compile(r"#[^\n]*"), _fmt("#6A9955", italic=True)),      # comments
            (re.compile(r"\b[A-Z_][A-Z0-9_]{2,}\b"), _fmt("#267F99")),  # CONSTANTS
            (re.compile(r"(?<=\bdef\s)\w+"), _fmt("#795E26")),           # function names
            (re.compile(r"(?<=\bclass\s)\w+"), _fmt("#267F99", bold=True)),  # class names
        ]

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)
