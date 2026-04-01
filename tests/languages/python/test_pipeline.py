"""Tests for Python pipeline integration."""

from orionparser.languages.python.pipeline import PythonPipeline


class TestPipeline:
    def test_preprocess_normalizes_crlf(self):
        pipeline = PythonPipeline()
        result = pipeline.preprocess("a\r\nb")
        assert result == "a\nb"

    def test_tokenize_basic(self):
        pipeline = PythonPipeline()
        tokens = pipeline.tokenize("x = 1")
        assert len(tokens) == 3
        assert tokens[0]["type"] == "NAME"
        assert tokens[1]["type"] == "EQUAL"
        assert tokens[2]["type"] == "NUMBER"

    def test_parse_returns_module(self):
        pipeline = PythonPipeline()
        result = pipeline.parse("x = 1")
        assert result is not None
        assert result["type"] == "Module"
