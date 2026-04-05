"""Python analysis pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orionparser.core.pipeline import BasePipeline, ParseResult


class PythonPipeline(BasePipeline):
    """Pipeline for Python source code analysis."""

    def preprocess(self, source: str) -> str:
        from orionparser.languages.python.preprocess import run_pipeline

        processed, _logs, _comments = run_pipeline(source)
        return processed

    def tokenize(self, source: str) -> list[dict[str, Any]]:
        from orionparser.languages.python.lexer import PythonLexer

        lexer = PythonLexer()
        return lexer.tokenize(source)

    def parse(self, source: str) -> dict[str, Any] | None:
        from orionparser.languages.python.parser import parse_source

        return parse_source(source)

    def analyze_file(self, path: Path) -> ParseResult:
        """Full pipeline with comment attachment."""
        from orionparser.languages.python.preprocess import run_pipeline
        from orionparser.languages.python.comment_attacher import attach_comments

        from orionparser.core.encoding import read_file

        source = read_file(path)
        errors: list[str] = []

        # Preprocess: normalize + extract comments
        preprocessed, _logs, comments = run_pipeline(source)

        # Tokenize
        tokens: list[dict[str, Any]] = []
        try:
            tokens = self.tokenize(preprocessed)
        except Exception as e:
            errors = errors + [f"Lexer error: {e}"]

        # Parse
        ast = None
        try:
            ast = self.parse(preprocessed)
        except Exception as e:
            errors = errors + [f"Parser error: {e}"]

        # Post-process: attach comments and docstrings to AST nodes
        if ast and comments:
            attach_comments(ast, comments)
        if ast:
            from orionparser.languages.python.docstring_attacher import attach_docstrings
            attach_docstrings(ast)

        return ParseResult(
            file_path=str(path),
            success=ast is not None and len(errors) == 0,
            ast=ast,
            errors=errors,
            tokens=tokens,
        )
