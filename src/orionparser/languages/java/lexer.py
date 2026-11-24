"""Java source translation and tokens used by the compilation-unit grammar."""
from bisect import bisect_right
import re
from pathlib import Path

from ply.lex import LexToken


RESERVED = frozenset("""
abstract assert boolean break byte case catch char class const continue default do double else enum
extends final finally float for goto if implements import instanceof int interface long native new
package private protected public return short static strictfp super switch synchronized this throw
throws transient try void volatile while _ true false null
""".split())
CONTEXTUAL = frozenset("open module requires transitive exports opens to uses provides with record sealed permits when yield".split())
_HEX = re.compile(r"[0-9a-fA-F]{4}")
_NEWLINE = re.compile(r"\r\n|[\r\n]")


_DECIMAL = "0123456789"
_HEXADECIMAL = _DECIMAL + "abcdefABCDEF"
_ESCAPE = re.compile(r"""\\(?:[btnfrs"'\\]|[0-3][0-7]{0,2}|[4-7][0-7]?)""")
# Character.isWhitespace characters relevant to String.stripIndent.
_JAVA_SPACE = " \t\f\v\r\n\x1c\x1d\x1e\x1f\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2008\u2009\u200a\u2028\u2029\u205f\u3000"
_BLOCK_ESCAPE = re.compile(_ESCAPE.pattern + r"|\\\n")
_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", "s": " ", "\n": "",
            "'": "'", '"': '"', "\\": "\\"}


def decode_escape(match):
    spelling = match[0][1:]
    if spelling in _ESCAPES:
        return _ESCAPES[spelling]
    return chr(int(spelling, 8))


_PRIMITIVES = frozenset("boolean byte char double float int long short".split())
_OPERATORS = {
    "...": "ELLIPSIS", "->": "ARROW", "::": "COLONS",
    ">>>=": "ASSIGN_OP", "<<=": "ASSIGN_OP", ">>=": "ASSIGN_OP", ">>>": "SHIFT",
    ">>": "SHIFT", "<<": "SHIFT", "++": "INC", "--": "DEC", "==": "EQ", "!=": "EQ",
    "<=": "REL", ">=": "REL", "&&": "AND", "||": "OR",
    **{s + "=": "ASSIGN_OP" for s in "+-*/%&^|"},
}
_OPERATOR = re.compile("|".join(map(re.escape, sorted(_OPERATORS, key=len, reverse=True))))


# Run boundaries from JavaLexOracle.characters, fixed to JDK 21's Unicode version.
_runs = [row.split() for row in Path(__file__).with_name("identifier-classes.txt").read_text("ascii").splitlines()]
_BOUNDARIES = tuple(int(start, 16) for start, _ in _runs)
_CLASSES = bytes(int(kind) for _, kind in _runs)
del _runs
_ASCII = bytes(_CLASSES[bisect_right(_BOUNDARIES, cp) - 1] for cp in range(128))


def identifier_class(c):
    cp = ord(c)
    return _ASCII[cp] if cp < 128 else _CLASSES[bisect_right(_BOUNDARIES, cp) - 1]


def identifier_start(c):
    return identifier_class(c) == 3


def ignorable(c):
    return identifier_class(c) == 2


def identifier_part(c):
    return identifier_class(c) != 0


class JavaSource:
    def __init__(self, source):
        self.raw = source
        self.line_starts = [0, *(m.end() for m in _NEWLINE.finditer(source))]
        self.text, self.offsets = self.translate()

    def error(self, offset, message):
        line = bisect_right(self.line_starts, offset)
        prefix = self.raw[self.line_starts[line-1]:offset]
        column = 0
        for c in prefix:
            column += 8 - column % 8 if c == "\t" else 1 + (ord(c) > 0xffff)
        return ValueError(f"line {line}, column {column+1}: {message}")

    def translate(self):
        chars, offsets = [], []
        i = slashes = 0
        escaped = False
        while i < len(self.raw):
            start = i
            c = self.raw[i]
            i += 1
            eligible = escaped or slashes % 2 == 0
            escaped = c == "\\" and eligible and self.raw.startswith("u", i)
            if escaped:
                while self.raw.startswith("u", i):
                    i += 1
                digits = _HEX.match(self.raw, i)
                if digits is None:
                    raise self.error(i, "malformed Unicode escape")
                c = chr(int(digits[0], 16))
                i = digits.end()
            slashes = slashes + 1 if c == "\\" else 0
            if 0xDC00 <= ord(c) <= 0xDFFF and chars and 0xD800 <= ord(chars[-1]) <= 0xDBFF:
                chars[-1] = chr(0x10000 + ((ord(chars[-1]) - 0xD800) << 10) + ord(c) - 0xDC00)
            else:
                chars.append(c)
                offsets.append(start)
        offsets.append(len(self.raw))
        return "".join(chars), offsets

    def number_end(self, start):
        text = self.text

        def at(i, chars):
            return i < len(text) and text[i] in chars

        def digits(i, alphabet):
            if at(i, "_"):
                raise self.error(self.offsets[i], "unexpected underscore before digits")
            while at(i, alphabet + "_"):
                i += 1
            if text[i-1:i] == "_":
                raise self.error(self.offsets[i-1], "unexpected trailing underscore in number")
            return i

        def exponent(i):
            if at(i, "+-"):
                i += 1
            if at(i, "_"):
                raise self.error(self.offsets[i], "unexpected underscore in exponent")
            if not at(i, _DECIMAL):
                raise self.error(self.offsets[start], "missing exponent digits")
            return digits(i, _DECIMAL)

        prefix = text[start:start+2].lower()
        if prefix == "0b":
            i = digits(start+2, "01")
            if i == start+2:
                raise self.error(self.offsets[start], "missing binary digits")
            return i + at(i, "lL")

        if prefix == "0x":
            first = start+2
            i = digits(first, _HEXADECIMAL)
            has_digits = i > first
            fraction = at(i, ".")
            if fraction:
                point = i
                i = digits(i+1, _HEXADECIMAL)
                has_digits |= i > point+1
            if not has_digits:
                raise self.error(self.offsets[start], "missing hexadecimal digits")
            if at(i, "pP"):
                i = exponent(i+1)
                return i + at(i, "fFdD")
            if fraction:
                raise self.error(self.offsets[start], "hexadecimal float requires a binary exponent")
            return i + at(i, "lL")

        # Scan radix-10 digits before deciding whether a leading zero
        # introduces an octal integer or a decimal floating-point literal.
        if text[start] == "0" and at(start+1, "_"):
            i = start+1
            while at(i, "_"):
                i += 1
            if not at(i, _DECIMAL):
                raise self.error(self.offsets[start+1], "expected digits after underscore")
        i = start if text[start] == "." else digits(start, _DECIMAL)
        fraction = at(i, ".")
        if fraction:
            i = digits(i+1, _DECIMAL)
        if at(i, "eE"):
            i = exponent(i+1)
            fraction = True
        if fraction or at(i, "fFdD"):
            return i + at(i, "fFdD")
        if text[start] == "0":
            i = digits(start, "01234567")
        return i + at(i, "lL")

    def quoted_end(self, start):
        quote = self.text[start]
        i, units = start + 1, 0
        while i < len(self.text) and self.text[i] not in "\r\n":
            c = self.text[i]
            if c == quote:
                if quote == "'" and units != 1:
                    raise self.error(self.offsets[start], "character literal requires one UTF-16 code unit")
                return i + 1
            if c == "\\":
                escape = _ESCAPE.match(self.text, i)
                if escape is None:
                    raise self.error(self.offsets[i], "invalid literal escape")
                i = escape.end()
                units += 1
            else:
                i += 1
                units += 1 + (ord(c) > 0xFFFF)
        raise self.error(self.offsets[start], "unterminated literal")

    def text_block(self, start):
        s = self.text
        content = start + 3
        while content < len(s) and s[content] in " \t\f":
            content += 1
        opening = _NEWLINE.match(s, content)
        if opening is None:
            raise self.error(self.offsets[content], "expected line terminator after text block opening delimiter")
        i = opening.end()
        while i < len(s):
            if s.startswith('"""', i):
                body = _NEWLINE.sub("\n", s[opening.end():i])
                lines = body.split("\n")
                indents = [len(line) - len(line.lstrip(_JAVA_SPACE)) for line in lines if line.strip(_JAVA_SPACE)]
                indents.append(len(lines[-1]) - len(lines[-1].lstrip(_JAVA_SPACE)))
                indent = min(indents)
                stripped = "\n".join(line[indent:].rstrip(_JAVA_SPACE) for line in lines)
                return i + 3, _BLOCK_ESCAPE.sub(decode_escape, stripped)
            if s[i] == "\\":
                escaped = _NEWLINE.match(s, i + 1) or _ESCAPE.match(s, i)
                if escaped is None:
                    raise self.error(self.offsets[i], "invalid text block escape")
                i = escaped.end()
            else:
                i += 1
        raise self.error(self.offsets[start], "unterminated text block")

    def tokens(self):
        s = self.text
        i = 0
        while i < len(s):
            start = i
            c = s[i]
            if c == "\x1a" and i == len(s) - 1:
                break
            if c in " \f\t\r\n":
                i += 1
                continue
            if s.startswith("//", i):
                end = _NEWLINE.search(s, i + 2)
                i = end.end() if end else len(s)
                continue
            if s.startswith("/*", i):
                end = s.find("*/", i + 2)
                if end < 0:
                    raise self.error(self.offsets[i], "unclosed comment")
                i = end + 2
                continue
            if identifier_start(c):
                i += 1
                while i < len(s) and identifier_part(s[i]):
                    i += 1
                value = "".join(c for c in s[start:i] if not ignorable(c))
                kind = value.upper() if value in RESERVED else "IDENT"
                if value in _PRIMITIVES:
                    kind = "PRIMITIVE"
            elif (c.isascii() and c.isdigit()) or (c == "." and i + 1 < len(s) and s[i+1] in "0123456789"):
                i = self.number_end(start)
                value = s[start:i]
                kind = "NUMBER"
            elif s.startswith('"""', i):
                i, decoded = self.text_block(start)
                kind, value = "TEXT_BLOCK", s[start:i]
            elif c in {"'", '"'}:
                i = self.quoted_end(start)
                kind, value = ("CHARACTER" if c == "'" else "STRING"), s[start:i]
            elif s.startswith("..", i) and not s.startswith("...", i):
                raise self.error(self.offsets[i+1], "expected a third dot in ellipsis")
            elif match := _OPERATOR.match(s, i):
                value, i = match[0], match.end()
                kind = _OPERATORS[value]
            elif c in ".,;{}*@()[]+-/%=<>!~^&|?:":
                kind = value = c
                i += 1
            else:
                raise self.error(self.offsets[i], f"unexpected character {c!r}")
            token = LexToken()
            token.type, token.value = kind, value
            if kind == "TEXT_BLOCK":
                token.decoded = decoded
            token.logical_pos = start
            token.lexpos = self.offsets[start]
            token.endlexpos = self.offsets[i]
            token.lineno = bisect_right(self.line_starts, token.lexpos)
            yield token
