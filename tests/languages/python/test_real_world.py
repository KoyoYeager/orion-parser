"""Real-world Python code tests.

Tests OrionParser against actual Python files from GitHub repositories.
Files with unsupported syntax (list comprehensions etc.) are expected
to fail — we track the pass rate as a benchmark.

Test corpus: C:/workspace/OrionParser/parser_sample/python/
  - algorithms/ (TheAlgorithms/Python) — 1375 files
  - flask/ (pallets/flask) — 83 files
"""

import logging
import os
import sys
from pathlib import Path

import pytest

from orionparser.languages.python.parser import parse_source
from orionparser.languages.python.preprocess import run_pipeline

logging.disable(logging.WARNING)

SAMPLE_ROOT = Path("C:/workspace/OrionParser/parser_sample/python")
STDLIB_ROOT = Path(sys.prefix) / "Lib"


def _collect_files(subdir: str) -> list[Path]:
    d = SAMPLE_ROOT / subdir
    if not d.exists():
        return []
    return sorted(d.rglob("*.py"))


def _parse_file(file_path: Path) -> bool:
    source = file_path.read_text(encoding="utf-8", errors="replace")
    preprocessed, _, _ = run_pipeline(source)
    result = parse_source(preprocessed)
    return result is not None


@pytest.mark.skipif(
    not (SAMPLE_ROOT / "algorithms").exists(),
    reason="Sample files not available",
)
class TestAlgorithmsBenchmark:
    """Benchmark: parse rate against TheAlgorithms/Python.

    Target: 70%+ (list comprehensions, match/case, walrus in
    complex contexts are known unsupported).
    """

    def test_pass_rate(self):
        files = _collect_files("algorithms")
        assert len(files) > 0

        ok = sum(1 for f in files if _parse_file(f))
        total = len(files)
        rate = ok * 100 // total

        print(f"\n  algorithms: {ok}/{total} ({rate}%)")
        assert rate >= 70, f"Pass rate {rate}% below 70% threshold"


@pytest.mark.skipif(
    not (SAMPLE_ROOT / "flask").exists(),
    reason="Sample files not available",
)
class TestFlaskBenchmark:
    """Benchmark: parse rate against pallets/flask.

    Target: 60%+ (Flask uses advanced syntax: match/case,
    type aliases, complex decorators).
    """

    def test_pass_rate(self):
        files = _collect_files("flask")
        assert len(files) > 0

        ok = sum(1 for f in files if _parse_file(f))
        total = len(files)
        rate = ok * 100 // total

        print(f"\n  flask: {ok}/{total} ({rate}%)")
        assert rate >= 60, f"Pass rate {rate}% below 60% threshold"


@pytest.mark.skipif(
    not STDLIB_ROOT.exists(),
    reason="Python stdlib not found",
)
class TestStdlibBenchmark:
    """Benchmark: parse rate against Python standard library.

    Target: 65%+ (stdlib uses advanced patterns: match/case,
    type params, walrus operator in complex contexts).
    """

    def test_pass_rate(self):
        files = sorted(STDLIB_ROOT.glob("*.py"))
        assert len(files) > 0

        ok = sum(1 for f in files if _parse_file(f))
        total = len(files)
        rate = ok * 100 // total

        print(f"\n  stdlib: {ok}/{total} ({rate}%)")
        assert rate >= 65, f"Pass rate {rate}% below 65% threshold"
