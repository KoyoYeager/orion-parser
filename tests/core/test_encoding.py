"""Tests for automatic encoding detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from orionparser.core.encoding import read_file


class TestReadFile:
    def test_utf8(self, tmp_path):
        p = tmp_path / "utf8.py"
        p.write_text("# UTF-8\nx = 'hello'\n", encoding="utf-8")
        result = read_file(p)
        assert "hello" in result

    def test_utf8_bom(self, tmp_path):
        p = tmp_path / "bom.py"
        p.write_bytes(b"\xef\xbb\xbf# BOM\nx = 1\n")
        result = read_file(p)
        assert "x = 1" in result

    def test_shift_jis(self, tmp_path):
        p = tmp_path / "sjis.py"
        content = "# Shift_JIS テスト\nx = 'こんにちは'\n"
        p.write_bytes(content.encode("shift_jis"))
        result = read_file(p)
        assert "こんにちは" in result

    def test_euc_jp(self, tmp_path):
        p = tmp_path / "eucjp.py"
        content = "# EUC-JP テスト\nx = 'テスト'\n"
        p.write_bytes(content.encode("euc-jp"))
        result = read_file(p)
        assert "テスト" in result

    def test_latin1(self, tmp_path):
        p = tmp_path / "latin1.py"
        content = "# café\nx = 1\n"
        p.write_bytes(content.encode("latin-1"))
        result = read_file(p)
        assert "x = 1" in result

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.py"
        p.write_bytes(b"")
        result = read_file(p)
        assert result == ""

    def test_ascii(self, tmp_path):
        p = tmp_path / "ascii.py"
        p.write_bytes(b"x = 1\n")
        result = read_file(p)
        assert "x = 1" in result
