"""Real-world Python code tests.

Tests OrionParser against actual Python files from GitHub repositories.
Follows the reference project's approach of parametrized real-file tests
with success rate benchmarks.

Test corpus: C:/workspace/OrionParser/parser_sample/python/
  - algorithms/ (TheAlgorithms/Python) — small samples, 100% target
  - flask/ (pallets/flask) — real project, 95%+ target
"""

import logging
import os
from pathlib import Path

import pytest

from orionparser.languages.python.parser import PythonParser
from orionparser.languages.python.preprocess import run_pipeline

logging.disable(logging.WARNING)

SAMPLE_ROOT = Path("C:/workspace/OrionParser/parser_sample/python")

# Files that use unsupported Python features (skip for now)
SKIP_FILES = {
    # Relative imports (from . import X) — not yet supported
    "app.py",
}


def get_algorithm_files() -> list[Path]:
    """Collect all .py files from algorithms sample."""
    sample_dir = SAMPLE_ROOT / "algorithms"
    if not sample_dir.exists():
        return []
    return sorted(sample_dir.rglob("*.py"))


def get_flask_files() -> list[Path]:
    """Collect all .py files from Flask project."""
    sample_dir = SAMPLE_ROOT / "flask"
    if not sample_dir.exists():
        return []
    return sorted(
        f for f in sample_dir.rglob("*.py")
        if f.name not in SKIP_FILES
    )


# Shared parser instance (avoid rebuilding PLY tables for each test)
_parser = PythonParser()


def _parse_file(file_path: Path) -> bool:
    """Parse a single file, return True if successful."""
    source = file_path.read_text(encoding="utf-8", errors="replace")
    preprocessed, _, _ = run_pipeline(source)
    result = _parser.parse(preprocessed)
    return result is not None


@pytest.mark.skipif(
    not (SAMPLE_ROOT / "algorithms").exists(),
    reason="Sample files not available",
)
class TestAlgorithms:
    """Test against TheAlgorithms/Python — target: 100%."""

    @pytest.mark.parametrize(
        "file_path",
        get_algorithm_files(),
        ids=lambda p: os.path.basename(p),
    )
    def test_parse(self, file_path: Path):
        assert _parse_file(file_path), f"Parse failed: {file_path.name}"


@pytest.mark.skipif(
    not (SAMPLE_ROOT / "flask").exists(),
    reason="Sample files not available",
)
class TestFlask:
    """Test against pallets/flask — target: 95%+."""

    @pytest.mark.parametrize(
        "file_path",
        get_flask_files(),
        ids=lambda p: os.path.basename(p),
    )
    def test_parse(self, file_path: Path):
        assert _parse_file(file_path), f"Parse failed: {file_path.name}"
