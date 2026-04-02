"""Python parser — PLY yacc with dynamic rule binding.

Grammar rules are defined in separate modules under rules/
and bound to PythonParser via _bind_rules(), following the
reference C parser's architecture.
"""

from __future__ import annotations

import logging
from typing import Any

import ply.yacc as yacc

from orionparser.languages.python.lexer import PythonLexer
from orionparser.languages.python.precedence import PYTHON_PRECEDENCE
from orionparser.languages.python.tokens import TOKENS

logger = logging.getLogger(__name__)

# Module-level singleton: build yacc tables once, reuse everywhere.
# PLY yacc has global state that breaks when yacc.yacc() is called
# multiple times. A single parser instance avoids this.
_singleton: PythonParser | None = None


class PythonParser:
    """LALR(1) parser for Python source code."""

    tokens = TOKENS
    precedence = PYTHON_PRECEDENCE

    def __init__(self) -> None:
        self._lexer = PythonLexer()
        self._errors: list[str] = []
        self._parser = yacc.yacc(
            module=self,
            start="file_input",
            debug=False,
            write_tables=False,
        )

    def parse(self, source: str) -> dict[str, Any] | None:
        """Parse Python source into AST dict."""
        self._errors = []
        tokens = self._lexer.tokenize(source)
        adapter = _TokenAdapter(tokens)
        result = self._parser.parse(lexer=adapter)
        return result

    @property
    def errors(self) -> list[str]:
        return list(self._errors)


def parse_source(source: str) -> dict[str, Any] | None:
    """Parse source with the shared parser singleton.

    If a parse fails (returns None), the singleton is rebuilt to
    prevent PLY's internal state from corrupting subsequent parses.
    """
    global _singleton
    if _singleton is None:
        _singleton = PythonParser()
    result = _singleton.parse(source)
    if result is None:
        # Rebuild singleton to clear any corrupted PLY state
        _singleton = PythonParser()
    return result


class _TokenAdapter:
    """Adapts a token list to PLY's lexer interface."""

    def __init__(self, tokens: list[dict[str, Any]]) -> None:
        self._tokens = tokens
        self._pos = 0

    def token(self) -> Any:
        if self._pos >= len(self._tokens):
            return None
        tok_dict = self._tokens[self._pos]
        self._pos += 1
        tok = yacc.YaccSymbol()
        tok.type = tok_dict["type"]
        tok.value = tok_dict["value"]
        tok.lineno = tok_dict.get("line", 0)
        tok.lexpos = 0
        return tok


def _bind_rules(parser_class: type) -> None:
    """Bind p_* functions from rule modules to PythonParser."""
    from orionparser.languages.python.rules import (
        r_module,
        r_statements,
        r_imports,
        r_compound,
        r_expressions,
        r_error,
    )

    modules = [
        r_module,
        r_statements,
        r_imports,
        r_compound,
        r_expressions,
        r_error,
    ]

    for mod in modules:
        for name in dir(mod):
            if name.startswith("p_"):
                setattr(parser_class, name, staticmethod(getattr(mod, name)))


_bind_rules(PythonParser)
