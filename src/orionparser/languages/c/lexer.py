"""C17 tokens for a preprocessed translation unit."""
import re

from orionparser.languages.c_family import CParseError, valid_identifier_scalar


_NEWLINE = re.compile(r"\r\n|[\r\n]")


_UCN = re.compile(r"\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}")
_ESCAPE = re.compile(r"""\\(?:['"?\\abfnrtv]|[0-7]{1,3}|x[0-9a-fA-F]+|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})""")
_INTEGER = re.compile(r"(?:0[xX][a-fA-F0-9]+|0[0-7]*|[1-9][0-9]*)(?:[uU](?:ll|LL|[lL])?|(?:ll|LL|[lL])[uU]?)?")
_FLOAT = re.compile(
    r"(?:0[xX](?:[0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?|\.[0-9a-fA-F]+)[pP][+-]?[0-9]+"
    r"|(?:(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[0-9]+[eE][+-]?[0-9]+))[fFlL]?"
)
class LexicalRules:
    keywords = {
        **dict.fromkeys("void char short int long float double signed unsigned _Bool _Complex _Imaginary".split(), "TYPE"),
        **dict.fromkeys("const volatile restrict".split(), "QUALIFIER"),
        **dict.fromkeys("typedef extern auto register _Thread_local".split(), "STORAGE"),
        **dict.fromkeys("inline _Noreturn".split(), "FUNCTION_SPEC"),
        **{word: word.upper() for word in "if else while for return break continue do switch case default goto _Generic static sizeof _Alignof _Alignas _Atomic struct union enum _Static_assert".split()},
    }
    tokens = tuple(sorted(set(keywords.values()) | {
        "BUILTIN_VA_ARG", "BUILTIN_OFFSETOF", "GNU_BLOCK_OPEN", "GNU_TYPEOF", "NAME", "DECL_NAME", "MEMBER_NAME", "LABEL_NAME", "TAG_NAME", "ENUM_NAME", "TYPEDEF_NAME", "BLOCK_OPEN", "FUNCTION_OPEN", "PARAM_OPEN", "NUMBER", "CHARACTER", "STRING", "INC", "DEC", "ARROW", "SHIFT", "COMPARE",
        "EQUAL", "AND", "OR", "ASSIGN_OP", "ELLIPSIS",
    }))
    literals = "{}[]();,:?~!%^&*+-=/<>|."
    t_ignore = " \t\v\f"
    precedence = (("nonassoc", "IF"), ("nonassoc", "ELSE"))

    def t_newline(self, token):
        r"\r\n|[\r\n]"
        token.lexer.lineno += 1

    def t_line_marker(self, token):
        r'\#[ \t]*[0-9]+[ \t]+"(?:[^"\\\r\n]|\\[^\r\n])*"(?:[ \t]+[0-9]+)*[ \t]*(?=[\r\n]|$)'
        start = max(self.source.rfind(c, 0, token.lexpos) for c in "\r\n") + 1
        if self.source[start:token.lexpos].strip():
            raise self.error(token.lexpos, "line marker inside a source line")
        self.in_system_header = "3" in token.value.rsplit('"', 1)[1].split()

    def t_pragma(self, token):
        r'\#[ \t]*pragma\b[^\r\n]*'
        start = max(self.source.rfind(c, 0, token.lexpos) for c in "\r\n") + 1
        if self.source[start:token.lexpos].strip():
            raise self.error(token.lexpos, "pragma inside a source line")

    def t_comment(self, token):
        r"//[^\r\n]*|/\*"
        if token.value == "/*":
            end = self.source.find("*/", token.lexer.lexpos)
            if end < 0:
                raise self.error(token.lexpos, "unterminated block comment")
            token.lexer.lineno += sum(1 for _ in _NEWLINE.finditer(self.source, token.lexpos, end + 2))
            token.lexer.lexpos = end + 2

    def universal_character(self, spelling, pos):
        value = int(spelling[2:], 16)
        if (value < 0xA0 and value not in {0x24, 0x40, 0x60}) or 0xD800 <= value <= 0xDFFF or value > 0x10FFFF:
            raise self.error(pos, "invalid universal character name")
        return chr(value)

    def check_literal(self, token):
        spelling = token.value
        pos = spelling.find("\\")
        while pos >= 0:
            escape = _ESCAPE.match(spelling, pos)
            if escape is None:
                raise self.error(token.lexpos + pos, "invalid literal escape")
            if spelling[pos + 1] in "uU":
                self.universal_character(escape[0], token.lexpos + pos)
            pos = spelling.find("\\", escape.end())
        return token

    def t_STRING(self, token):
        r'(?:u8|[LuU])?"(?:[^"\\\r\n]|\\[^\r\n])*"'
        return self.check_literal(token)

    def t_CHARACTER(self, token):
        r"(?:[LuU])?'(?:[^'\\\r\n]|\\[^\r\n])+'"
        return self.check_literal(token)

    def t_NAME(self, token):
        r"(?:[A-Za-z_]|\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}|[^\x00-\x7f])(?:[A-Za-z_0-9]|\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}|[^\x00-\x7f])*"
        if "\\" in token.value or not token.value.isascii():
            chars = []
            pos = 0
            while pos < len(token.value):
                start = pos
                char = token.value[pos]
                if char == "\\":
                    match = _UCN.match(token.value, pos)
                    char = self.universal_character(match[0], token.lexpos + pos)
                    pos = match.end()
                else:
                    pos += 1
                cp = ord(char)
                if cp >= 128 or token.value[start] == "\\":
                    if not valid_identifier_scalar(cp, initial=not chars):
                        raise self.error(token.lexpos + start, "character not allowed in C identifier")
                chars.append(char)
            token.spelling = token.value
            token.value = "".join(chars)
        token.type = self.keywords.get(token.value, "NAME")
        return token

    def t_NUMBER(self, token):
        r"(?:[0-9]|\.[0-9])(?:[eEpP][+-]|[a-zA-Z0-9_.]|\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}|[^\x00-\x7f])*"
        if not (_INTEGER.fullmatch(token.value) or _FLOAT.fullmatch(token.value)):
            if self.in_system_header and re.fullmatch(r".*[ijIJ][fFlL]?", token.value):
                real = re.sub(r"[ijIJ]([fFlL]?)$", r"\1", token.value)
                if _FLOAT.fullmatch(real) or _INTEGER.fullmatch(real):
                    token.gnu_imaginary = True
                    return token
            raise self.error(token.lexpos, "invalid numeric constant " + repr(token.value))
        return token

    def t_digraph(self, token):
        r"<:|:>|<%|%>"
        token.spelling = token.value
        token.type = token.value = {"<:": "[", ":>": "]", "<%": "{", "%>": "}"}[token.value]
        return token

    def t_ASSIGN_OP(self, token):
        r"<<=|>>=|[+*/%&^|\-]="
        return token

    t_ELLIPSIS = r"\.\.\."
    t_INC = r"\+\+"
    t_DEC = r"--"
    t_ARROW = r"->"
    t_SHIFT = r"<<|>>"
    t_COMPARE = r"<=|>="
    t_EQUAL = r"==|!="
    t_AND = r"&&"
    t_OR = r"\|\|"

    def error(self, pos, message):
        return CParseError(self.source, pos, message)

    def t_error(self, token):
        raise self.error(token.lexpos, f"unexpected character {token.value[0]!r}")
