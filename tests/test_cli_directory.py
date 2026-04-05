"""Tests for CLI directory analysis with cross-file merging."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def multi_dir(tmp_path) -> Path:
    """Directory with files that call each other."""
    (tmp_path / "main.py").write_text(
        "def main():\n    helper()\n    connect()\n\nmain()\n",
        encoding="utf-8",
    )
    (tmp_path / "utils.py").write_text(
        "def helper():\n    validate()\n\ndef validate():\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "db.py").write_text(
        "def connect():\n    setup()\n\ndef setup():\n    pass\n",
        encoding="utf-8",
    )
    return tmp_path


def _run_cli(*args: str) -> str:
    """Run orion-parser CLI and return stdout."""
    result = subprocess.run(
        [sys.executable, "-m", "orionparser"] + list(args),
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout


class TestCLIParseDirectory:
    def test_parse_counts_files(self, multi_dir):
        out = _run_cli("parse", str(multi_dir))
        assert "3/3 files parsed successfully" in out

    def test_parse_shows_ok_for_each(self, multi_dir):
        out = _run_cli("parse", str(multi_dir))
        assert out.count("[OK]") == 3


class TestCLIAnalyzeDirectory:
    def test_call_tree_has_cross_file_merged(self, multi_dir):
        out = _run_cli("analyze", "--call-tree", str(multi_dir))
        data = json.loads(out)
        assert len(data) == 4  # 3 files + 1 merged
        merged = data[-1]
        assert merged["file"] == "(cross-file merged)"

    def test_merged_has_all_functions(self, multi_dir):
        out = _run_cli("analyze", "--call-tree", str(multi_dir))
        data = json.loads(out)
        merged = data[-1]["call_tree"]
        funcs = set(merged["functions"])
        assert "main" in funcs
        assert "helper" in funcs
        assert "validate" in funcs
        assert "connect" in funcs
        assert "setup" in funcs

    def test_merged_has_cross_file_edges(self, multi_dir):
        out = _run_cli("analyze", "--call-tree", str(multi_dir))
        data = json.loads(out)
        merged = data[-1]["call_tree"]
        calls = {(c[0], c[1]) for c in merged["calls"]}
        # main (main.py) -> helper (utils.py)
        assert ("main", "helper") in calls
        # main (main.py) -> connect (db.py)
        assert ("main", "connect") in calls
        # helper (utils.py) -> validate (utils.py)
        assert ("helper", "validate") in calls
        # connect (db.py) -> setup (db.py)
        assert ("connect", "setup") in calls

    def test_merged_deduplicates_edges(self, multi_dir):
        out = _run_cli("analyze", "--call-tree", str(multi_dir))
        data = json.loads(out)
        merged = data[-1]["call_tree"]
        calls = merged["calls"]
        call_tuples = [(c[0], c[1]) for c in calls]
        # No duplicates
        assert len(call_tuples) == len(set(call_tuples))

    def test_data_flow_has_merged(self, multi_dir):
        out = _run_cli("analyze", "--data-flow", str(multi_dir))
        data = json.loads(out)
        merged = data[-1]
        assert merged["file"] == "(cross-file merged)"
        assert "variables" in merged["data_flow"]

    def test_symbols_no_merge(self, multi_dir):
        """Symbols don't need cross-file merge — each file is independent."""
        out = _run_cli("analyze", "--symbols", str(multi_dir))
        data = json.loads(out)
        # Merged entry still exists but only has symbol data if --all
        assert len(data) >= 3

    def test_all_analysis(self, multi_dir):
        out = _run_cli("analyze", "--all", str(multi_dir))
        data = json.loads(out)
        merged = data[-1]
        assert merged["file"] == "(cross-file merged)"
        assert "call_tree" in merged
        assert "data_flow" in merged
        # symbols are per-file, not merged
        per_file = data[0]
        assert "symbols" in per_file

    def test_output_to_file(self, multi_dir, tmp_path):
        out_file = tmp_path / "result.json"
        _run_cli("analyze", "--call-tree", str(multi_dir), "-o", str(out_file))
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data[-1]["file"] == "(cross-file merged)"


class TestCLISingleFile:
    """Single file should NOT have a merged entry."""

    def test_single_file_no_merge(self, multi_dir):
        out = _run_cli("analyze", "--call-tree", str(multi_dir / "main.py"))
        data = json.loads(out)
        # Single file returns a dict, not a list
        assert isinstance(data, dict)
        assert "call_tree" in data
        assert data.get("file") != "(cross-file merged)"
