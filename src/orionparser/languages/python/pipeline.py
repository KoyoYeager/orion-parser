"""Python analysis pipeline."""

from __future__ import annotations

from typing import Any

from orionparser.core.pipeline import BasePipeline


class PythonPipeline(BasePipeline):
    """Pipeline for Python source code analysis."""

    def preprocess(self, source: str) -> str:
        from orionparser.languages.python.preprocess import run_pipeline

        processed, _logs = run_pipeline(source)
        return processed

    def tokenize(self, source: str) -> list[dict[str, Any]]:
        from orionparser.languages.python.lexer import PythonLexer

        lexer = PythonLexer()
        return lexer.tokenize(source)

    def parse(self, source: str) -> dict[str, Any] | None:
        from orionparser.languages.python.parser import PythonParser

        parser = PythonParser()
        return parser.parse(source)
