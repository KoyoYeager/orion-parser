"""Shared test fixtures."""

import pytest

from orionparser.languages.python.lexer import PythonLexer
from orionparser.languages.python.pipeline import PythonPipeline


@pytest.fixture
def python_lexer():
    return PythonLexer()


@pytest.fixture
def python_pipeline():
    return PythonPipeline()
