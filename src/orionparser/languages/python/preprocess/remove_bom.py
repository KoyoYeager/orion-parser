"""Stage 1: Remove UTF-8 BOM if present."""


def remove_bom(source: str) -> tuple[str, list[str]]:
    """Strip UTF-8 BOM (U+FEFF) from the start of source."""
    if source.startswith("\ufeff"):
        return source[1:], ["[Preprocessing: RemoveBOM] Removed UTF-8 BOM"]
    return source, []
