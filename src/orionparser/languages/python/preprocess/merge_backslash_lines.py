"""Stage 4: Merge backslash-continued lines.

Follows the same pattern as the C reference preprocessor:
buffer lines ending with `\\`, then join with the next line.
"""


def merge_backslash_lines(source: str) -> tuple[str, list[str]]:
    """Merge lines ending with backslash into a single logical line."""
    lines = source.splitlines()
    merged: list[str] = []
    logs: list[str] = []

    buffer = ""
    merge_start: int | None = None

    for i, line in enumerate(lines):
        line_no = i + 1
        stripped = line.rstrip()

        if stripped.endswith("\\"):
            if merge_start is None:
                merge_start = line_no
            buffer = buffer + stripped[:-1]
        else:
            if merge_start is not None:
                buffer = buffer + line
                merged = merged + [buffer]
                logs = logs + [
                    f"[Preprocessing: MergeBackslashLines] "
                    f"Lines {merge_start}-{line_no}: Merged continuation"
                ]
                buffer = ""
                merge_start = None
            else:
                merged = merged + [line]

    # Unterminated continuation at EOF
    if merge_start is not None:
        merged = merged + [buffer]
        logs = logs + [
            f"[Preprocessing: MergeBackslashLines] "
            f"Line {merge_start}: Unterminated continuation at EOF"
        ]

    return "\n".join(merged) + "\n" if merged else "", logs
