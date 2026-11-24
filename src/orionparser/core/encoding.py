"""Encoding detection using chardet."""

from __future__ import annotations

from pathlib import Path


def read_file(path: Path, *, prefer_utf8: bool = False) -> str:
    """Read a file with automatic encoding detection.

    Compiler output can request strict UTF-8 first. Other encodings use chardet.
    """
    raw = path.read_bytes()
    if not raw:
        return ""

    if prefer_utf8:
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass

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
