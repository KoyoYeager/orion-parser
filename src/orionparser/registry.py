"""Language registry — maps file extensions to analysis pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orionparser.core.pipeline import BasePipeline

_CPP = ("orionparser.languages.cpp.pipeline", "CppPipeline")
_CPP_SUFFIXES = (".C", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".ii", ".cppm", ".ixx")

# extension → (module_path, class_name)
_REGISTRY: dict[str, tuple[str, str]] = {
    **dict.fromkeys(_CPP_SUFFIXES, _CPP),
    ".java": ("orionparser.languages.java.pipeline", "JavaPipeline"),
    ".c": ("orionparser.languages.c.pipeline", "CPipeline"),
    ".i": ("orionparser.languages.c.pipeline", "CPipeline"),
    ".js": ("orionparser.languages.javascript.pipeline", "JavaScriptPipeline"),
    ".cjs": ("orionparser.languages.javascript.pipeline", "JavaScriptPipeline"),
    ".mjs": ("orionparser.languages.javascript.pipeline", "JavaScriptModulePipeline"),
    ".ts": ("orionparser.languages.typescript.pipeline", "TypeScriptPipeline"),
    ".tsx": ("orionparser.languages.typescript.pipeline", "TypeScriptPipeline"),
    ".mts": ("orionparser.languages.typescript.pipeline", "TypeScriptPipeline"),
    ".cts": ("orionparser.languages.typescript.pipeline", "TypeScriptPipeline"),
    ".py": ("orionparser.languages.python.pipeline", "PythonPipeline"),
}


def get_language(path: Path) -> str | None:
    """Detect language from file extension."""
    ext = path.suffix.lower()
    if path.suffix == ".C":  # Conventional C++ source extension.
        return ".C"
    if ext in _REGISTRY:
        return ext
    return None


def get_pipeline(path: Path, *, typescript_options=None, c_includes=(), c_defines=()) -> BasePipeline:
    """Return the appropriate pipeline for a file."""
    import importlib

    ext = get_language(path)
    if ext is None:
        supported = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(f"Unsupported extension: {path.suffix} (supported: {supported})")

    module_path, class_name = _REGISTRY[ext]
    module = importlib.import_module(module_path)
    pipeline_class = getattr(module, class_name)
    pipeline = pipeline_class.from_path(path)
    if typescript_options is not None and hasattr(pipeline, "syntax_options"):
        pipeline.syntax_options = typescript_options
    if ext == ".c" or ext in _CPP_SUFFIXES:
        pipeline.include_dirs = tuple(c_includes)
        pipeline.defines = tuple(c_defines)
    return pipeline


def supported_extensions() -> list[str]:
    """Return list of supported file extensions."""
    return sorted(_REGISTRY.keys())
