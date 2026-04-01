"""Stage 5: Extract comments and strip them from source.

Produces a comment map (line → comment text) while removing
comments from the source code. String literals are protected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Comment:
    """A single extracted comment."""

    line: int
    col: int
    text: str
    is_inline: bool  # True if code exists before the comment on the same line


def extract_comments(source: str) -> tuple[str, list[Comment]]:
    """Extract all comments from Python source.

    Returns (cleaned_source, comments).
    Comments inside string literals are NOT extracted.
    """
    lines = source.split("\n")
    cleaned: list[str] = []
    comments: list[Comment] = []
    logs: list[str] = []

    in_triple_quote: str | None = None  # None, '\"\"\"', or "'''"

    for line_no_0, line in enumerate(lines):
        line_no = line_no_0 + 1

        # Inside triple-quoted string — check for closing
        if in_triple_quote is not None:
            close_idx = line.find(in_triple_quote)
            if close_idx >= 0:
                in_triple_quote = None
            cleaned = cleaned + [line]
            continue

        # Scan character by character to find comment outside strings
        result_chars: list[str] = []
        i = 0
        in_string: str | None = None  # quote character

        while i < len(line):
            c = line[i]

            # Check for triple-quote start
            if in_string is None and i + 2 < len(line):
                triple = line[i:i + 3]
                if triple in ('"""', "'''"):
                    # Check if it closes on the same line
                    close_idx = line.find(triple, i + 3)
                    if close_idx >= 0:
                        # Entire triple-quoted string on one line
                        result_chars = result_chars + list(line[i:close_idx + 3])
                        i = close_idx + 3
                        continue
                    else:
                        # Opens a multi-line triple-quoted string
                        in_triple_quote = triple
                        result_chars = result_chars + list(line[i:])
                        i = len(line)
                        continue

            # String literal handling
            if in_string is None and c in ('"', "'"):
                in_string = c
                result_chars = result_chars + [c]
                i += 1
                continue

            if in_string is not None:
                result_chars = result_chars + [c]
                if c == "\\" and i + 1 < len(line):
                    # Escape sequence — consume next char too
                    result_chars = result_chars + [line[i + 1]]
                    i += 2
                    continue
                if c == in_string:
                    in_string = None
                i += 1
                continue

            # Comment found
            if c == "#":
                comment_text = line[i:]
                code_before = line[:i].rstrip()
                is_inline = len(code_before) > 0

                comments = comments + [
                    Comment(
                        line=line_no,
                        col=i,
                        text=comment_text,
                        is_inline=is_inline,
                    )
                ]

                # Strip the comment from the line
                stripped = line[:i].rstrip()
                result_chars = list(stripped)
                break

            result_chars = result_chars + [c]
            i += 1

        cleaned = cleaned + ["".join(result_chars)]

    return "\n".join(cleaned), comments
