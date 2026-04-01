"""Python parser — PLY-based syntax analyzer.

Produces AST dicts from Python source code.
This is a scaffold; grammar rules will be added incrementally.
"""

from __future__ import annotations

from typing import Any

from orionparser.languages.python.lexer import PythonLexer


class PythonParser:
    """Syntax analyzer for Python source code."""

    def __init__(self) -> None:
        self._lexer = PythonLexer()

    def parse(self, source: str) -> dict[str, Any] | None:
        """Parse Python source into AST dict.

        Currently returns a minimal module node with token info.
        Full grammar rules will be added in subsequent development.
        """
        tokens = self._lexer.tokenize(source)
        # Scaffold: return module node wrapping raw tokens
        return {
            "type": "Module",
            "body": [],
            "token_count": len(tokens),
        }
