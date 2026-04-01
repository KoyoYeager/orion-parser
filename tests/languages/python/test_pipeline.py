"""Tests for Python pipeline integration."""

from orionparser.languages.python.pipeline import PythonPipeline


class TestPipeline:
    def test_preprocess_normalizes_crlf(self):
        pipeline = PythonPipeline()
        result = pipeline.preprocess("a\r\nb")
        assert "\r" not in result
        assert result.endswith("\n")  # trailing newline added

    def test_tokenize_basic(self):
        pipeline = PythonPipeline()
        tokens = pipeline.tokenize("x = 1\n")
        # NAME EQUAL NUMBER NEWLINE ENDMARKER
        types = [t["type"] for t in tokens]
        assert "NAME" in types
        assert "EQUAL" in types
        assert "NUMBER" in types
        assert "ENDMARKER" in types

    def test_parse_returns_module(self):
        pipeline = PythonPipeline()
        result = pipeline.parse("x = 1\n")
        assert result is not None
        assert result["type"] == "Module"

    def test_analyze_file(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def hello():\n    print('hi')\n", encoding="utf-8")
        pipeline = PythonPipeline()
        result = pipeline.analyze_file(f)
        assert result.success
        assert result.ast["type"] == "Module"
