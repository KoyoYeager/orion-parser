"""Shared fixtures for GUI tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Force offscreen rendering for CI / headless environments
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def sample_source() -> str:
    """Minimal Python source for testing."""
    return (
        "import os\n"
        "import sys\n"
        "\n"
        "def main():\n"
        '    """Entry point."""\n'
        "    x = 1\n"
        "    print(x)\n"
        "\n"
        "class Config:\n"
        '    """Configuration."""\n'
        "    name = 'app'\n"
        "\n"
        "main()\n"
    )


@pytest.fixture(scope="session")
def sample_file(tmp_path_factory, sample_source) -> Path:
    """Write sample source to a temp file."""
    p = tmp_path_factory.mktemp("src") / "sample.py"
    p.write_text(sample_source, encoding="utf-8")
    return p


@pytest.fixture(scope="session")
def sample_result(sample_file):
    """ParseResult from analyzing sample_file."""
    from orionparser.registry import get_pipeline

    pipeline = get_pipeline(sample_file)
    return pipeline.analyze_file(sample_file)


@pytest.fixture(scope="session")
def sample_dir(tmp_path_factory) -> Path:
    """Directory with multiple Python files for testing."""
    d = tmp_path_factory.mktemp("project")
    (d / "main.py").write_text("def main():\n    greet()\n\ndef greet():\n    print('hi')\n", encoding="utf-8")
    (d / "utils.py").write_text("def helper():\n    return 42\n", encoding="utf-8")
    sub = d / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    return d
