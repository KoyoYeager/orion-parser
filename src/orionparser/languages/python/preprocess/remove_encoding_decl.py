"""Stage 3: Remove encoding declaration comment."""

import re

# PEP 263: coding declaration in first 2 lines
_ENCODING_RE = re.compile(
    r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)", re.ASCII
)


def remove_encoding_declaration(source: str) -> tuple[str, list[str]]:
    """Remove `# -*- coding: xxx -*-` from first two lines."""
    lines = source.split("\n", 2)
    logs: list[str] = []
    changed = False

    for i in range(min(2, len(lines))):
        if _ENCODING_RE.match(lines[i]):
            logs = logs + [
                f"[Preprocessing: RemoveEncodingDecl] "
                f"Line {i + 1}: Removed encoding declaration"
            ]
            lines[i] = ""
            changed = True

    if changed:
        return "\n".join(lines), logs
    return source, logs
