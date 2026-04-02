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
    t_DOT = r"\."

    # Ignore spaces/tabs within a line (indent handled in post-processing)
    t_ignore = " \t"

    def __init__(self) -> None:
        self.lexer: lex.Lexer = lex.lex(module=self)

    def t_COMMENT(self, t: lex.LexToken) -> None:
        r"\#[^\n]*"
        # Comments are extracted in preprocessing; skip in lexer

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
        tokens = self._collapse_newlines(tokens)
        tokens = self._merge_adjacent_strings(tokens)
        tokens = self._strip_type_params(tokens)
        tokens = self._convert_pos_only_slash(tokens)
        tokens = self._convert_lambda_colon(tokens)
        return self._mark_comp_tokens(tokens)

    @staticmethod
    def _merge_adjacent_strings(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge adjacent STRING tokens (implicit string concatenation).

        `"a" "b"` → single STRING token `"a" "b"`.
        """
        result: list[dict[str, Any]] = []
        for tok in tokens:
            if tok["type"] == "STRING" and result and result[-1]["type"] == "STRING":
                # Merge into previous
                prev = result[-1]
                result[-1] = {
                    "type": "STRING",
                    "value": prev["value"] + " " + tok["value"],
                    "line": prev["line"],
                }
            else:
                result = result + [tok]
        return result

    @staticmethod
    def _strip_type_params(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Strip PEP 695 type parameter brackets from def/class.

        `def f[T](x)` → `def f(x)` (removes [T])
        `class C[T: Bound]` → `class C` (removes [T: Bound])
        This avoids LALR(1) conflicts with subscript expressions.
        """
        result: list[dict[str, Any]] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            # Check for DEF/CLASS NAME LSQB pattern
            if (tok["type"] in ("DEF", "CLASS")
                    and i + 2 < len(tokens)
                    and tokens[i + 1]["type"] == "NAME"
                    and tokens[i + 2]["type"] == "LSQB"):
                # Emit DEF/CLASS and NAME
                result = result + [tok, tokens[i + 1]]
                # Skip everything from LSQB to matching RSQB
                j = i + 2
                depth = 0
                while j < len(tokens):
                    if tokens[j]["type"] == "LSQB":
                        depth += 1
                    elif tokens[j]["type"] == "RSQB":
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                    j += 1
                i = j
                continue
            result = result + [tok]
            i += 1
        return result

    @staticmethod
    def _convert_pos_only_slash(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert positional-only parameter `/` to a skippable token.

        `def f(a, /, b)` — the `/` inside param list is not division.
        Strategy: inside `DEF NAME LPAREN ... RPAREN`, replace bare SLASH
        between COMMA tokens with nothing (skip it).
        """
        result: list[dict[str, Any]] = []
        in_def_params = False
        paren_depth = 0

        for i, tok in enumerate(tokens):
            if tok["type"] == "DEF":
                in_def_params = True
                result = result + [tok]
                continue

            if in_def_params:
                if tok["type"] == "LPAREN":
                    paren_depth += 1
                elif tok["type"] == "RPAREN":
                    paren_depth -= 1
                    if paren_depth == 0:
                        in_def_params = False

                # Skip bare SLASH in parameter list (positional-only marker)
                if paren_depth > 0 and tok["type"] == "SLASH":
                    # Check context: should be between COMMA tokens
                    prev = result[-1]["type"] if result else None
                    if prev in ("COMMA", "LPAREN"):
                        continue  # Skip the /

            result = result + [tok]

        return result

    @staticmethod
    def _convert_lambda_colon(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert lambda's COLON to LAMBDA_COLON everywhere.

        Avoids LALR(1) conflicts between lambda body `:` and
        dict kv_pair `:`, annotation `:`, etc.
        """
        result: list[dict[str, Any]] = []
        after_lambda = False

        for tok in tokens:
            t = tok["type"]

            if t == "LAMBDA":
                after_lambda = True
                result = result + [tok]
                continue

            if after_lambda and t == "COLON":
                after_lambda = False
                result = result + [
                    {"type": "LAMBDA_COLON", "value": tok["value"], "line": tok["line"]}
                ]
                continue

            # Reset after_lambda on tokens that can't be in lambda params
            if after_lambda and t not in ("NAME", "COMMA", "EQUAL", "STAR",
                                           "DOUBLESTAR", "NUMBER", "STRING",
                                           "LPAREN", "RPAREN", "LSQB", "RSQB"):
                after_lambda = False

            result = result + [tok]

        return result

    @staticmethod
    def _mark_comp_tokens(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert FOR/IN/IF inside brackets to COMP_FOR/COMP_IN/COMP_IF.

        This resolves the LALR(1) conflict between:
          - `expression IN expression` (comparison operator)
          - `comp_for : COMP_FOR ... COMP_IN expression` (comprehension)

        Detection: track bracket depth. When FOR appears inside
        [ ], ( ), or { } after an expression (not at statement level),
        convert it and subsequent IN/IF to COMP_* tokens.
        """
        result: list[dict[str, Any]] = []
        bracket_depth = 0
        # Track: are we inside a comprehension context?
        # comp_depth[i] = True means bracket level i has seen a COMP_FOR
        comp_depth: dict[int, bool] = {}

        after_for = False
        at_line_start = True  # For detecting match/case/type at statement start

        for i, tok in enumerate(tokens):
            t = tok["type"]

            if t in ("LSQB", "LBRACE", "LPAREN"):
                bracket_depth += 1
                comp_depth[bracket_depth] = False
                result = result + [tok]
                continue

            if t in ("RSQB", "RBRACE", "RPAREN"):
                comp_depth.pop(bracket_depth, None)
                bracket_depth = max(0, bracket_depth - 1)
                result = result + [tok]
                continue

            # Inside brackets: FOR → COMP_FOR
            if bracket_depth > 0 and t == "FOR":
                comp_depth[bracket_depth] = True
                result = result + [
                    {"type": "COMP_FOR", "value": tok["value"], "line": tok["line"]}
                ]
                after_for = True
                continue

            # Inside brackets: IF in comprehension context → COMP_IF
            if bracket_depth > 0 and comp_depth.get(bracket_depth, False) and t == "IF":
                result = result + [
                    {"type": "COMP_IF", "value": tok["value"], "line": tok["line"]}
                ]
                continue

            # Statement-level FOR: mark next IN as COMP_IN
            if bracket_depth == 0 and t == "FOR":
                after_for = True
                at_line_start = False
                result = result + [tok]
                continue

            # WITH LPAREN: remove outer parens (parenthesized with, PEP 617)
            # `with (ctx1, ctx2 as f):` → `with ctx1, ctx2 as f:`
            if t == "WITH" and i + 1 < len(tokens) and tokens[i + 1]["type"] == "LPAREN":
                depth = 0
                rparen_idx = -1
                for j in range(i + 1, len(tokens)):
                    if tokens[j]["type"] == "LPAREN":
                        depth += 1
                    elif tokens[j]["type"] == "RPAREN":
                        depth -= 1
                        if depth == 0:
                            rparen_idx = j
                            break
                if rparen_idx > 0:
                    # Remove the LPAREN and RPAREN, and trailing comma before RPAREN
                    tokens[i + 1] = {"type": "_SKIP", "value": "", "line": tokens[i + 1]["line"]}
                    if tokens[rparen_idx - 1]["type"] == "COMMA":
                        tokens[rparen_idx - 1] = {"type": "_SKIP", "value": "", "line": tokens[rparen_idx - 1]["line"]}
                    tokens[rparen_idx] = {"type": "_SKIP", "value": "", "line": tokens[rparen_idx]["line"]}

            # First IN after any FOR → COMP_IN (avoids `v IN items` comparison)
            if after_for and t == "IN":
                after_for = False
                result = result + [
                    {"type": "COMP_IN", "value": tok["value"], "line": tok["line"]}
                ]
                continue

            # Soft keywords: match/case/type at line start
            if at_line_start and t == "NAME":
                next_tok = tokens[i + 1] if i + 1 < len(tokens) else None
                next_type = next_tok["type"] if next_tok else None
                if tok["value"] == "match" and next_type not in ("EQUAL", "DOT", "COMMA", "NEWLINE", None):
                    # Disambiguate match() call vs match statement
                    is_match_stmt = True
                    if next_type == "LPAREN":
                        # Check if RPAREN is followed by COLON
                        depth2 = 0
                        is_match_stmt = False
                        for k in range(i + 2, len(tokens)):
                            if tokens[k]["type"] == "LPAREN": depth2 += 1
                            elif tokens[k]["type"] == "RPAREN":
                                if depth2 == 0:
                                    # Check what follows the closing paren
                                    if k + 1 < len(tokens) and tokens[k + 1]["type"] == "COLON":
                                        is_match_stmt = True
                                    break
                                depth2 -= 1
                    if is_match_stmt:
                        result = result + [{"type": "MATCH_KW", "value": tok["value"], "line": tok["line"]}]
                        continue
                if tok["value"] == "case" and next_type not in ("EQUAL", "DOT", "COMMA", "NEWLINE", None):
                    result = result + [{"type": "CASE_KW", "value": tok["value"], "line": tok["line"]}]
                    # Convert IF → COMP_IF and AS → MATCH_AS in this case clause
                    for j in range(i + 1, len(tokens)):
                        jt = tokens[j]["type"]
                        if jt == "IF":
                            tokens[j] = {"type": "COMP_IF", "value": tokens[j]["value"], "line": tokens[j]["line"]}
                        elif jt == "AS":
                            tokens[j] = {"type": "MATCH_AS", "value": tokens[j]["value"], "line": tokens[j]["line"]}
                        elif jt in ("COLON", "NEWLINE"):
                            break
                    continue
                if tok["value"] == "type" and next_type == "NAME":
                    result = result + [{"type": "TYPE_KW", "value": tok["value"], "line": tok["line"]}]
                    continue

            # Track line start
            if t in ("NEWLINE", "INDENT", "DEDENT"):
                at_line_start = True
            elif t not in ("NEWLINE", "INDENT", "DEDENT", "ENDMARKER"):
                at_line_start = False

            if t != "_SKIP":
                result = result + [tok]

        return result

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
        self.lexer.lineno = 1  # Reset line counter for reuse
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
