"""Tests for Python lexer."""

from orionparser.languages.python.lexer import PythonLexer


class TestKeywords:
    def test_reserved_words(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("if else while for def class return")
        types = [t["type"] for t in tokens]
        assert "IF" in types
        assert "ELSE" in types
        assert "WHILE" in types
        assert "FOR" in types
        assert "DEF" in types
        assert "CLASS" in types
        assert "RETURN" in types

    def test_identifier_not_keyword(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("my_var")
        assert tokens[0]["type"] == "NAME"
        assert tokens[0]["value"] == "my_var"


class TestOperators:
    def test_comparison_operators(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("== != <= >= < >")
        types = [t["type"] for t in tokens]
        assert types == ["EQEQUAL", "NOTEQUAL", "LESSEQUAL", "GREATEREQUAL", "LESS", "GREATER"]

    def test_assignment_operators(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("+= -= *= /=")
        types = [t["type"] for t in tokens]
        assert types == ["PLUSEQUAL", "MINEQUAL", "STAREQUAL", "SLASHEQUAL"]

    def test_walrus_operator(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize(":=")
        assert tokens[0]["type"] == "COLONEQUAL"


class TestLiterals:
    def test_integer(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("42")
        assert tokens[0]["type"] == "NUMBER"
        assert tokens[0]["value"] == "42"

    def test_hex_literal(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("0xFF")
        assert tokens[0]["type"] == "NUMBER"

    def test_string_single_quote(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("'hello'")
        assert tokens[0]["type"] == "STRING"

    def test_string_double_quote(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize('"hello"')
        assert tokens[0]["type"] == "STRING"

    def test_fstring(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize('f"value={x}"')
        assert tokens[0]["type"] == "STRING"

    def test_triple_quote(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize('"""docstring"""')
        assert tokens[0]["type"] == "STRING"


class TestStructure:
    def test_newline_token(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("a\nb")
        types = [t["type"] for t in tokens]
        assert "NEWLINE" in types

    def test_implicit_line_continuation(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("(\n1\n)")
        # NEWLINE should not appear inside parens
        types = [t["type"] for t in tokens]
        assert "NEWLINE" not in types

    def test_comment_preserved(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("x = 1  # comment")
        types = [t["type"] for t in tokens]
        assert "COMMENT" in types
