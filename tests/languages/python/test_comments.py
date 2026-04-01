"""Tests for comment extraction and attachment."""

import logging

from orionparser.languages.python.preprocess.extract_comments import extract_comments
from orionparser.languages.python.parser import PythonParser
from orionparser.languages.python.comment_attacher import attach_comments
from orionparser.languages.python.preprocess import run_pipeline

logging.disable(logging.WARNING)


class TestExtractComments:
    def test_inline_comment(self):
        source = "x = 1  # assign x\n"
        cleaned, comments = extract_comments(source)
        assert len(comments) == 1
        assert comments[0].text == "# assign x"
        assert comments[0].is_inline is True
        assert comments[0].line == 1
        assert "# assign x" not in cleaned

    def test_standalone_comment(self):
        source = "# this is a comment\nx = 1\n"
        cleaned, comments = extract_comments(source)
        assert len(comments) == 1
        assert comments[0].is_inline is False
        assert comments[0].line == 1

    def test_comment_in_string_not_extracted(self):
        source = 'x = "# not a comment"\n'
        cleaned, comments = extract_comments(source)
        assert len(comments) == 0
        assert "# not a comment" in cleaned

    def test_comment_in_triple_string(self):
        source = '"""# not a comment"""\n'
        cleaned, comments = extract_comments(source)
        assert len(comments) == 0

    def test_multiple_comments(self):
        source = "# first\nx = 1  # second\n# third\ny = 2\n"
        cleaned, comments = extract_comments(source)
        assert len(comments) == 3
        assert comments[0].text == "# first"
        assert comments[1].text == "# second"
        assert comments[2].text == "# third"

    def test_no_comments(self):
        source = "x = 1\ny = 2\n"
        cleaned, comments = extract_comments(source)
        assert len(comments) == 0
        assert cleaned == source


class TestAttachComments:
    def _parse_with_comments(self, source: str) -> dict:
        preprocessed, _logs, comments = run_pipeline(source)
        parser = PythonParser()
        ast = parser.parse(preprocessed)
        assert ast is not None
        if comments:
            attach_comments(ast, comments)
        return ast

    def test_leading_comment(self):
        source = "# greet the user\ndef hello():\n    pass\n"
        ast = self._parse_with_comments(source)
        func = ast["body"][0]
        assert func["type"] == "FunctionDef"
        assert "comments" in func
        assert func["comments"][0]["position"] == "leading"
        assert "greet the user" in func["comments"][0]["text"]

    def test_inline_comment(self):
        source = "x = 1  # initialize\n"
        ast = self._parse_with_comments(source)
        stmt = ast["body"][0]
        assert "comments" in stmt
        assert stmt["comments"][0]["position"] == "inline"
        assert "initialize" in stmt["comments"][0]["text"]

    def test_no_comment_no_key(self):
        source = "x = 1\n"
        ast = self._parse_with_comments(source)
        stmt = ast["body"][0]
        assert "comments" not in stmt

    def test_multiple_leading_comments(self):
        source = "# first line\n# second line\nx = 1\n"
        ast = self._parse_with_comments(source)
        stmt = ast["body"][0]
        assert "comments" in stmt
        assert len(stmt["comments"]) == 2

    def test_class_with_docstring_comment(self):
        source = "# Foo class\nclass Foo:\n    # bar method\n    def bar(self):\n        pass\n"
        ast = self._parse_with_comments(source)
        cls = ast["body"][0]
        assert cls["type"] == "ClassDef"
        assert "comments" in cls
        assert "Foo class" in cls["comments"][0]["text"]
