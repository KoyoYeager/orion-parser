"""Tests for Python preprocessing pipeline."""

from orionparser.languages.python.preprocess import run_pipeline
from orionparser.languages.python.preprocess.remove_bom import remove_bom
from orionparser.languages.python.preprocess.normalize_lines import normalize_lines
from orionparser.languages.python.preprocess.remove_encoding_decl import remove_encoding_declaration
from orionparser.languages.python.preprocess.merge_backslash_lines import merge_backslash_lines


class TestRemoveBOM:
    def test_removes_utf8_bom(self):
        source = "\ufeffprint('hello')"
        result, logs = remove_bom(source)
        assert result == "print('hello')"
        assert len(logs) == 1

    def test_no_bom_unchanged(self):
        source = "print('hello')"
        result, logs = remove_bom(source)
        assert result == source
        assert len(logs) == 0


class TestNormalizeLines:
    def test_crlf_to_lf(self):
        result, logs = normalize_lines("a\r\nb\r\n")
        assert "\r" not in result
        assert "a\nb\n" == result

    def test_cr_to_lf(self):
        result, logs = normalize_lines("a\rb\r")
        assert "\r" not in result

    def test_adds_trailing_newline(self):
        result, logs = normalize_lines("a\nb")
        assert result.endswith("\n")


class TestRemoveEncodingDecl:
    def test_removes_coding_line(self):
        source = "# -*- coding: utf-8 -*-\nprint('hello')\n"
        result, logs = remove_encoding_declaration(source)
        assert "coding" not in result
        assert "print" in result
        assert len(logs) == 1

    def test_removes_coding_on_line2(self):
        source = "#!/usr/bin/env python\n# coding: utf-8\nprint('hello')\n"
        result, logs = remove_encoding_declaration(source)
        assert "coding" not in result
        assert "#!/usr/bin/env python" in result

    def test_no_coding_unchanged(self):
        source = "print('hello')\n"
        result, logs = remove_encoding_declaration(source)
        assert result == source
        assert len(logs) == 0


class TestMergeBackslashLines:
    def test_merges_continuation(self):
        source = "x = 1 + \\\n    2\n"
        result, logs = merge_backslash_lines(source)
        assert "x = 1 +     2" in result
        assert len(logs) == 1

    def test_multiple_continuations(self):
        source = "x = 1 + \\\n    2 + \\\n    3\n"
        result, logs = merge_backslash_lines(source)
        assert "x = 1 +     2 +     3" in result

    def test_no_continuation_unchanged(self):
        source = "x = 1\ny = 2\n"
        result, logs = merge_backslash_lines(source)
        assert "x = 1" in result
        assert "y = 2" in result
        assert len(logs) == 0


class TestFullPipeline:
    def test_combined(self):
        source = "\ufeff# -*- coding: utf-8 -*-\r\nx = 1 + \\\r\n    2\r\n"
        result, logs = run_pipeline(source)
        assert "\ufeff" not in result
        assert "coding" not in result
        assert "\r" not in result
        assert "x = 1 +     2" in result
        assert len(logs) >= 3
