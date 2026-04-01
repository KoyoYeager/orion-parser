"""Post-processing: attach comments to AST nodes.

Strategy: walk the AST's body lists (Module.body, FunctionDef.body, etc.)
and match comments to statements by line number. This avoids attaching
comments to sub-expression nodes.

Comment positions:
  - leading:  comment on line(s) before the statement
  - inline:   comment on the same line as the statement
"""

from __future__ import annotations

from typing import Any

from orionparser.languages.python.preprocess.extract_comments import Comment


def attach_comments(ast: dict[str, Any], comments: list[Comment]) -> None:
    """Attach comments to AST nodes in-place."""
    if not comments:
        return

    remaining = list(comments)
    _attach_to_body(ast.get("body", []), remaining)

    # Any leftover comments attach to Module itself
    if remaining:
        entries = [
            {"text": c.text, "line": c.line, "position": "trailing"}
            for c in remaining
        ]
        ast["comments"] = ast.get("comments", []) + entries


def _attach_to_body(
    body: list[dict[str, Any]], remaining: list[Comment]
) -> None:
    """Walk a body list and attach comments to statements."""
    for stmt in body:
        if not isinstance(stmt, dict) or "type" not in stmt:
            continue

        stmt_line = stmt.get("_line", 0)
        if stmt_line == 0:
            continue

        # Collect comments that belong to this statement
        matched: list[Comment] = []
        still_remaining: list[Comment] = []

        for c in remaining:
            if c.is_inline and c.line == stmt_line:
                matched = matched + [c]
            elif not c.is_inline and c.line < stmt_line:
                # Check if there's a closer statement after this comment
                # but before our statement — if so, skip
                matched = matched + [c]
            else:
                still_remaining = still_remaining + [c]

        # Filter: only keep leading comments that are closer to THIS stmt
        # than to a previous stmt
        final_matched: list[Comment] = []
        for c in matched:
            if c.is_inline:
                final_matched = final_matched + [c]
            else:
                # Leading: only attach if no other body stmt is between
                # the comment and this stmt
                has_closer = False
                for other in body:
                    if other is stmt:
                        continue
                    other_line = other.get("_line", 0) if isinstance(other, dict) else 0
                    if c.line < other_line < stmt_line:
                        has_closer = True
                        break
                if not has_closer:
                    final_matched = final_matched + [c]
                else:
                    still_remaining = still_remaining + [c]

        if final_matched:
            entries = []
            for c in final_matched:
                position = "inline" if c.is_inline else "leading"
                entries = entries + [
                    {"text": c.text, "line": c.line, "position": position}
                ]
            stmt["comments"] = stmt.get("comments", []) + entries

        remaining.clear()
        remaining.extend(still_remaining)

        # Recurse into nested bodies
        for field in ("body", "orelse", "finalbody"):
            nested = stmt.get(field, [])
            if isinstance(nested, list):
                _attach_to_body(nested, remaining)

        if "handlers" in stmt:
            for handler in stmt.get("handlers", []):
                if isinstance(handler, dict):
                    _attach_to_body(handler.get("body", []), remaining)
