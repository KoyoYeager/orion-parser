"""Python lexer — PLY-based tokenizer with INDENT/DEDENT generation.

INDENT/DEDENT tokens are generated as a post-processing step over
PLY's raw token stream, following Python's indentation rules:
  - After a NEWLINE, measure leading whitespace
  - If indent increases → emit INDENT
  - If indent decreases → emit one or more DEDENT
  - Brackets suppress NEWLINE (implicit line continuation)
"""

from __future__ import annotations

from typing import Any

import ply.lex as lex

from orionparser.languages.python.tokens import RESERVED, TOKENS


class PythonLexer:
    """Lexical analyzer for Python source code."""

    tokens = TOKENS

    # --- Multi-char operators (longest match first) ---
    t_DOUBLESTAREQUAL = r"\*\*="
    t_DOUBLESLASHEQUAL = r"//="
    t_LSHIFTEQUAL = r"<<="
    t_RSHIFTEQUAL = r">>="
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
    t_PERCENTEQUAL = r"%="
    t_AMPEREQUAL = r"&="
    t_VBAREQUAL = r"\|="
    t_CIRCUMFLEXEQUAL = r"\^="
    t_ATEQUAL = r"@="

    # --- Single-char operators ---
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

    # Ignore spaces/tabs within a line (indent handled in post-processing)
    t_ignore = " \t"

    def __init__(self) -> None:
        self.lexer: lex.Lexer = lex.lex(module=self)

    def t_COMMENT(self, t: lex.LexToken) -> lex.LexToken:
        r"\#[^\n]*"
        return t

    def t_STRING(self, t: lex.LexToken) -> lex.LexToken:
        r'(?:f|r|b|u|rf|rb|fr|br|F|R|B|U|RF|RB|FR|BR)?"""[\s\S]*?"""|' \
        r"(?:f|r|b|u|rf|rb|fr|br|F|R|B|U|RF|RB|FR|BR)?'''[\s\S]*?'''|" \
        r'(?:f|r|b|u|rf|rb|fr|br|F|R|B|U|RF|RB|FR|BR)?"(?:[^"\\]|\\.)*"|' \
        r"(?:f|r|b|u|rf|rb|fr|br|F|R|B|U|RF|RB|FR|BR)?'(?:[^'\\]|\\.)*'"
        # Count newlines inside triple-quoted strings
        t.lexer.lineno += t.value.count("\n")
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

    def t_NEWLINE(self, t: lex.LexToken) -> lex.LexToken:
        r"\n"
        t.lexer.lineno += 1
        t.type = "NEWLINE"
        return t

    def t_error(self, t: lex.LexToken) -> None:
        t.lexer.skip(1)

    def tokenize(self, source: str) -> list[dict[str, Any]]:
        """Tokenize source and return token list with INDENT/DEDENT."""
        raw = self._collect_raw_tokens(source)
        tokens = self._inject_indent_dedent(raw, source)
        return self._collapse_newlines(tokens)

    @staticmethod
    def _collapse_newlines(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse consecutive NEWLINE tokens into one.

        Blank lines produce extra NEWLINEs that break `block: NEWLINE INDENT`.
        """
        result: list[dict[str, Any]] = []
        for tok in tokens:
            if tok["type"] == "NEWLINE" and result and result[-1]["type"] == "NEWLINE":
                continue
            result = result + [tok]
        return result

    def _collect_raw_tokens(self, source: str) -> list[dict[str, Any]]:
        """Collect raw tokens from PLY lexer."""
        self.lexer.input(source)
        tokens: list[dict[str, Any]] = []
        for tok in self.lexer:
            tokens = tokens + [
                {"type": tok.type, "value": tok.value, "line": tok.lineno}
            ]
        return tokens

    def _inject_indent_dedent(
        self, raw: list[dict[str, Any]], source: str
    ) -> list[dict[str, Any]]:
        """Post-process raw tokens to insert INDENT/DEDENT.

        Algorithm:
        1. Split source into lines to get indent levels
        2. Walk tokens; after each NEWLINE, check indent of next line
        3. Emit INDENT/DEDENT based on indent stack
        4. Skip NEWLINE inside brackets (implicit continuation)
        """
        # Pre-compute indent level for each line (1-indexed)
        lines = source.split("\n")
        line_indent: dict[int, int] = {}
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped and not stripped.startswith("#"):
                line_indent[i + 1] = len(line) - len(stripped)
            else:
                line_indent[i + 1] = -1  # blank or comment-only

        indent_stack: list[int] = [0]
        paren_depth = 0
        result: list[dict[str, Any]] = []

        i = 0
        while i < len(raw):
            tok = raw[i]

            # Track bracket depth
            if tok["type"] in ("LPAREN", "LSQB", "LBRACE"):
                paren_depth += 1
            elif tok["type"] in ("RPAREN", "RSQB", "RBRACE"):
                paren_depth = max(0, paren_depth - 1)

            # Inside brackets: suppress NEWLINE
            if tok["type"] == "NEWLINE" and paren_depth > 0:
                i += 1
                continue

            # On NEWLINE: look ahead for indent changes
            if tok["type"] == "NEWLINE":
                result = result + [tok]

                # Find the next non-blank, non-comment line's indent
                next_line = tok["line"] + 1
                next_indent = -1
                while next_line in line_indent:
                    if line_indent[next_line] >= 0:
                        next_indent = line_indent[next_line]
                        break
                    next_line += 1

                if next_indent < 0:
                    # No more code lines
                    i += 1
                    continue

                # Skip consecutive NEWLINEs (blank lines)
                j = i + 1
                while j < len(raw) and raw[j]["type"] in ("NEWLINE", "COMMENT"):
                    if raw[j]["type"] == "NEWLINE":
                        result = result + [raw[j]]
                    else:
                        result = result + [raw[j]]
                    j += 1
                i = j

                current_indent = indent_stack[-1]
                if next_indent > current_indent:
                    indent_stack = indent_stack + [next_indent]
                    result = result + [
                        {"type": "INDENT", "value": "", "line": next_line}
                    ]
                elif next_indent < current_indent:
                    while indent_stack and indent_stack[-1] > next_indent:
                        indent_stack = indent_stack[:-1]
                        result = result + [
                            {"type": "DEDENT", "value": "", "line": next_line}
                        ]
                continue

            result = result + [tok]
            i += 1

        # Emit remaining DEDENT at EOF
        while len(indent_stack) > 1:
            indent_stack = indent_stack[:-1]
            line = raw[-1]["line"] if raw else 1
            result = result + [{"type": "DEDENT", "value": "", "line": line}]

        # Add ENDMARKER
        line = raw[-1]["line"] if raw else 1
        result = result + [{"type": "ENDMARKER", "value": "", "line": line}]

        return result
