"""Encoding detection using chardet."""

from __future__ import annotations

from pathlib import Path


def read_file(path: Path) -> str:
    """Read a file with automatic encoding detection.

    Uses chardet to detect encoding, falling back to utf-8.
    """
    raw = path.read_bytes()
    if not raw:
        return ""

    try:
        import chardet

        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"
    except ImportError:
        encoding = "utf-8"

    try:
        return raw.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return raw.decode("utf-8", errors="replace")
