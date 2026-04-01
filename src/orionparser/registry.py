"""Language registry — maps file extensions to analysis pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orionparser.core.pipeline import BasePipeline

# extension → (module_path, class_name)
_REGISTRY: dict[str, tuple[str, str]] = {
    ".py": ("orionparser.languages.python.pipeline", "PythonPipeline"),
}


def get_language(path: Path) -> str | None:
    """Detect language from file extension."""
    ext = path.suffix.lower()
    if ext in _REGISTRY:
        return ext
    return None


def get_pipeline(path: Path) -> BasePipeline:
    """Return the appropriate pipeline for a file."""
    import importlib

    ext = path.suffix.lower()
    if ext not in _REGISTRY:
        supported = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(f"Unsupported extension: {ext} (supported: {supported})")

    module_path, class_name = _REGISTRY[ext]
    module = importlib.import_module(module_path)
    pipeline_class = getattr(module, class_name)
    return pipeline_class()


def supported_extensions() -> list[str]:
    """Return list of supported file extensions."""
    return sorted(_REGISTRY.keys())
