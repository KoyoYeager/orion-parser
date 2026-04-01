"""Stage 2: Normalize line endings."""


def normalize_lines(source: str) -> tuple[str, list[str]]:
    """Convert all line endings to LF and ensure trailing newline."""
    logs: list[str] = []

    if "\r\n" in source:
        source = source.replace("\r\n", "\n")
        logs = logs + ["[Preprocessing: NormalizeLines] Converted CRLF to LF"]

    if "\r" in source:
        source = source.replace("\r", "\n")
        logs = logs + ["[Preprocessing: NormalizeLines] Converted CR to LF"]

    if source and not source.endswith("\n"):
        source = source + "\n"
        logs = logs + ["[Preprocessing: NormalizeLines] Added trailing newline"]

    return source, logs
