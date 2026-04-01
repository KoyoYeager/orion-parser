"""Python lexer — PLY-based tokenizer with INDENT/DEDENT generation."""

from __future__ import annotations

from typing import Any

import ply.lex as lex

from orionparser.languages.python.tokens import RESERVED, TOKENS


class PythonLexer:
    """Lexical analyzer for Python source code."""

    tokens = TOKENS

    # --- Simple tokens (longest match first) ---
    t_DOUBLESTAR = r"\*\*"
    t_DOUBLESLASH = r"//"
    t_LSHIFT = r"<<"
    t_RSHIFT = r">>"
    t_LESSEQUAL = r"<="
    t_GREATEREQUAL = r">="
    t_EQEQUAL = r"=="
    t_NOTEQUAL = r"!="
    t_COLONEQUAL = r":="
    t_ARROW = r"->"
    t_ELLIPSIS = r"\.\.\."
    t_PLUSEQUAL = r"\+="
    t_MINEQUAL = r"-="
    t_STAREQUAL = r"\*="
    t_SLASHEQUAL = r"/="
    t_DOUBLESLASHEQUAL = r"//="
    t_PERCENTEQUAL = r"%="
    t_DOUBLESTAREQUAL = r"\*\*="
    t_AMPEREQUAL = r"&="
    t_VBAREQUAL = r"\|="
    t_CIRCUMFLEXEQUAL = r"\^="
    t_LSHIFTEQUAL = r"<<="
    t_RSHIFTEQUAL = r">>="
    t_ATEQUAL = r"@="
    t_PLUS = r"\+"
    t_MINUS = r"-"
    t_STAR = r"\*"
    t_SLASH = r"/"
    t_PERCENT = r"%"
    t_AT = r"@"
    t_AMPER = r"&"
    t_VBAR = r"\|"
    t_CIRCUMFLEX = r"\^"
    t_TILDE = r"~"
    t_LESS = r"<"
    t_GREATER = r">"
    t_EQUAL = r"="
    t_LPAREN = r"\("
    t_RPAREN = r"\)"
    t_LSQB = r"\["
    t_RSQB = r"\]"
    t_LBRACE = r"\{"
    t_RBRACE = r"\}"
    t_COMMA = r","
    t_COLON = r":"
    t_SEMI = r";"
    t_DOT = r"\."

    t_ignore = " \t"

    def __init__(self) -> None:
        self._indent_stack: list[int] = [0]
        self._paren_depth: int = 0
        self._pending_tokens: list[Any] = []
        self.lexer: lex.Lexer = lex.lex(module=self)

    def t_COMMENT(self, t: lex.LexToken) -> None:
        r"\#[^\n]*"
        # Keep comments as tokens (for trivia preservation)
        return t

    def t_STRING(self, t: lex.LexToken) -> lex.LexToken:
        r'(f|r|b|u|rf|rb|fr|br|F|R|B|U|RF|RB|FR|BR)?"""[\s\S]*?"""|' \
        r"(f|r|b|u|rf|rb|fr|br|F|R|B|U|RF|RB|FR|BR)?'''[\s\S]*?'''|" \
        r'(f|r|b|u|rf|rb|fr|br|F|R|B|U|RF|RB|FR|BR)?"(?:[^"\\]|\\.)*"|' \
        r"(f|r|b|u|rf|rb|fr|br|F|R|B|U|RF|RB|FR|BR)?'(?:[^'\\]|\\.)*'"
        return t

    def t_NUMBER(self, t: lex.LexToken) -> lex.LexToken:
        r"0[xX][0-9a-fA-F](?:_?[0-9a-fA-F])*|" \
        r"0[oO][0-7](?:_?[0-7])*|" \
        r"0[bB][01](?:_?[01])*|" \
        r"[0-9](?:_?[0-9])*\.(?:[0-9](?:_?[0-9])*)?(?:[eE][+-]?[0-9](?:_?[0-9])*)?[jJ]?|" \
        r"\.[0-9](?:_?[0-9])*(?:[eE][+-]?[0-9](?:_?[0-9])*)?[jJ]?|" \
        r"[0-9](?:_?[0-9])*[eE][+-]?[0-9](?:_?[0-9])*[jJ]?|" \
        r"[0-9](?:_?[0-9])*[jJ]|" \
        r"[0-9](?:_?[0-9])*"
        return t

    def t_NAME(self, t: lex.LexToken) -> lex.LexToken:
        r"[a-zA-Z_][a-zA-Z0-9_]*"
        t.type = RESERVED.get(t.value, "NAME")
        return t

    def t_NEWLINE(self, t: lex.LexToken) -> lex.LexToken | None:
        r"\n+"
        t.lexer.lineno += len(t.value)
        if self._paren_depth > 0:
            # Inside brackets — implicit line continuation
            return None
        t.type = "NEWLINE"
        return t

    def t_error(self, t: lex.LexToken) -> None:
        t.lexer.skip(1)

    def tokenize(self, source: str) -> list[dict[str, Any]]:
        """Tokenize source and return list of token dicts."""
        self.lexer.input(source)
        self._indent_stack = [0]
        self._paren_depth = 0

        raw_tokens: list[dict[str, Any]] = []
        for tok in self.lexer:
            # Track bracket depth for implicit line continuation
            if tok.type in ("LPAREN", "LSQB", "LBRACE"):
                self._paren_depth += 1
            elif tok.type in ("RPAREN", "RSQB", "RBRACE"):
                self._paren_depth = max(0, self._paren_depth - 1)

            raw_tokens = raw_tokens + [
                {"type": tok.type, "value": tok.value, "line": tok.lineno}
            ]

        return raw_tokens
