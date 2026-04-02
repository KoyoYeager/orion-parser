"""Tests for Python lexer."""

from orionparser.languages.python.lexer import PythonLexer


class TestKeywords:
    def test_reserved_words(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("if else while for def class return\n")
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
        tokens = lexer.tokenize("my_var\n")
        assert tokens[0]["type"] == "NAME"
        assert tokens[0]["value"] == "my_var"


class TestOperators:
    def test_comparison_operators(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("== != <= >= < >\n")
        types = [t["type"] for t in tokens if t["type"] not in ("NEWLINE", "ENDMARKER")]
        assert types == ["EQEQUAL", "NOTEQUAL", "LESSEQUAL", "GREATEREQUAL", "LESS", "GREATER"]

    def test_assignment_operators(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("+= -= *= /=\n")
        types = [t["type"] for t in tokens if t["type"] not in ("NEWLINE", "ENDMARKER")]
        assert types == ["PLUSEQUAL", "MINEQUAL", "STAREQUAL", "SLASHEQUAL"]

    def test_walrus_operator(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize(":=\n")
        assert tokens[0]["type"] == "COLONEQUAL"


class TestLiterals:
    def test_integer(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("42\n")
        assert tokens[0]["type"] == "NUMBER"
        assert tokens[0]["value"] == "42"

    def test_hex_literal(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("0xFF\n")
        assert tokens[0]["type"] == "NUMBER"

    def test_string_single_quote(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("'hello'\n")
        assert tokens[0]["type"] == "STRING"

    def test_string_double_quote(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize('"hello"\n')
        assert tokens[0]["type"] == "STRING"

    def test_fstring(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize('f"value={x}"\n')
        assert tokens[0]["type"] == "STRING"

    def test_triple_quote(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize('"""docstring"""\n')
        assert tokens[0]["type"] == "STRING"


class TestStructure:
    def test_newline_token(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("a\nb\n")
        types = [t["type"] for t in tokens]
        assert "NEWLINE" in types

    def test_implicit_line_continuation(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("(\n1\n)\n")
        # NEWLINE should not appear inside parens
        types = [t["type"] for t in tokens if t["type"] != "ENDMARKER"]
        newline_count = types.count("NEWLINE")
        # Only the final NEWLINE after ) should remain
        assert newline_count <= 1

    def test_comment_skipped_by_lexer(self):
        """Comments are extracted in preprocessing, not by lexer."""
        lexer = PythonLexer()
        tokens = lexer.tokenize("x = 1  # comment\n")
        types = [t["type"] for t in tokens]
        assert "COMMENT" not in types

    def test_endmarker(self):
        lexer = PythonLexer()
        tokens = lexer.tokenize("x\n")
        assert tokens[-1]["type"] == "ENDMARKER"


class TestIndentDedent:
    def test_simple_indent(self):
        source = "if True:\n    x = 1\n"
        lexer = PythonLexer()
        tokens = lexer.tokenize(source)
        types = [t["type"] for t in tokens]
        assert "INDENT" in types

    def test_simple_dedent(self):
        source = "if True:\n    x = 1\ny = 2\n"
        lexer = PythonLexer()
        tokens = lexer.tokenize(source)
        types = [t["type"] for t in tokens]
        assert "INDENT" in types
        assert "DEDENT" in types

    def test_nested_indent(self):
        source = "if True:\n    if False:\n        x = 1\n"
        lexer = PythonLexer()
        tokens = lexer.tokenize(source)
        types = [t["type"] for t in tokens]
        indent_count = types.count("INDENT")
        assert indent_count == 2

    def test_multiple_dedent(self):
        source = "if True:\n    if False:\n        x = 1\ny = 2\n"
        lexer = PythonLexer()
        tokens = lexer.tokenize(source)
        types = [t["type"] for t in tokens]
        dedent_count = types.count("DEDENT")
        assert dedent_count == 2

    def test_function_def(self):
        source = "def hello():\n    print('hi')\n    return 1\n"
        lexer = PythonLexer()
        tokens = lexer.tokenize(source)
        types = [t["type"] for t in tokens]
        assert types.count("INDENT") == 1
        assert types.count("DEDENT") == 1

    def test_class_with_method(self):
        source = (
            "class Foo:\n"
            "    def bar(self):\n"
            "        return 1\n"
        )
        lexer = PythonLexer()
        tokens = lexer.tokenize(source)
        types = [t["type"] for t in tokens]
        assert types.count("INDENT") == 2
        # DEDENT at EOF for both levels
        assert types.count("DEDENT") == 2

    def test_eof_dedents(self):
        """Remaining indents should produce DEDENT at EOF."""
        source = "if True:\n    x = 1\n"
        lexer = PythonLexer()
        tokens = lexer.tokenize(source)
        types = [t["type"] for t in tokens]
        # Should have DEDENT before ENDMARKER
        endmarker_idx = types.index("ENDMARKER")
        assert "DEDENT" in types[:endmarker_idx]

    def test_no_indent_flat_code(self):
        source = "x = 1\ny = 2\nz = 3\n"
        lexer = PythonLexer()
        tokens = lexer.tokenize(source)
        types = [t["type"] for t in tokens]
        assert "INDENT" not in types
        assert "DEDENT" not in types
