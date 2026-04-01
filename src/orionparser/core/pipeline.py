"""Base pipeline interface for language-specific implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParseResult:
    """Single file parse result."""

    file_path: str
    success: bool
    ast: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    tokens: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


class BasePipeline(ABC):
    """Abstract base for language analysis pipelines.

    Each language implements this interface:
      - preprocess: source normalization
      - tokenize: lexical analysis
      - parse: syntax analysis → AST
      - analyze_file: full pipeline for a single file
    """

    @abstractmethod
    def preprocess(self, source: str) -> str:
        """Normalize source code before lexing."""

    @abstractmethod
    def tokenize(self, source: str) -> list[dict[str, Any]]:
        """Produce token list from source."""

    @abstractmethod
    def parse(self, source: str) -> dict[str, Any] | None:
        """Parse source into AST dict."""

    def analyze_file(self, path: Path) -> ParseResult:
        """Run the full pipeline on a single file."""
        source = path.read_text(encoding="utf-8")
        errors: list[str] = []

        preprocessed = self.preprocess(source)

        tokens = []
        try:
            tokens = self.tokenize(preprocessed)
        except Exception as e:
            errors = errors + [f"Lexer error: {e}"]

        ast = None
        try:
            ast = self.parse(preprocessed)
        except Exception as e:
            errors = errors + [f"Parser error: {e}"]

        return ParseResult(
            file_path=str(path),
            success=ast is not None and len(errors) == 0,
            ast=ast,
            errors=errors,
            tokens=tokens,
        )
