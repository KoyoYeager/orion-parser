"""Tokens for preprocessed C++20, with physical offsets in the translation unit."""
from bisect import bisect_left, bisect_right
import re

from ply.lex import LexToken

from orionparser.languages.c_family import CParseError, valid_identifier_scalar


BUILTINS = set("void bool char signed unsigned __signed __signed__ short int long float double wchar_t char8_t char16_t char32_t auto __builtin_va_list __int128 __float80 __float128 _Complex __complex__".split())
_SPECIFIERS = set("const volatile constexpr consteval constinit static extern thread_local mutable".split())
TYPE_TRANSFORMS = {"__underlying_type", "__remove_cv", "__remove_cvref", "__remove_pointer", "__remove_reference"}
TYPE_TRAITS = {
    **dict.fromkeys("""__has_trivial_destructor __has_unique_object_representations __has_virtual_destructor
                       __is_abstract __is_aggregate __is_class __is_empty __is_enum __is_final __is_literal_type
                       __is_array __is_bounded_array __is_function __is_member_function_pointer __is_member_object_pointer
                       __is_member_pointer __is_object __is_reference __has_trivial_constructor
                       __is_pod __is_polymorphic __is_standard_layout __is_trivial __is_trivially_copyable __is_union""".split(), "UNARY_TRAIT"),
    **dict.fromkeys("""__is_pointer_interconvertible_base_of __is_layout_compatible __reference_converts_from_temporary __reference_constructs_from_temporary __is_assignable __is_base_of __is_convertible __is_nothrow_convertible __is_nothrow_assignable __is_same
                       __is_trivially_assignable""".split(), "BINARY_TRAIT"),
    **dict.fromkeys("""__is_constructible __is_nothrow_constructible __is_trivially_constructible""".split(), "VARIADIC_TRAIT"),
}
_KEYWORDS = set("""
alignas alignof asm break case catch class concept const_cast continue co_await co_return co_yield decltype
default delete do dynamic_cast else enum explicit export false for friend goto if inline namespace new noexcept nullptr
operator private protected public register reinterpret_cast requires return sizeof static_assert static_cast struct switch
template this throw true try typedef typeid typename union using virtual while
""".split())
_ALTERNATIVES = dict(zip("and and_eq bitand bitor compl not not_eq or or_eq xor xor_eq".split(),
                         "&& &= & | ~ ! != || |= ^ ^=".split(), strict=True))
_OPERATORS = {
    "::": "SCOPE", "<=>": "SPACESHIP", "++": "INC", "--": "DEC", "->": "ARROW", "->*": "ARROW_STAR",
    ".*": "DOT_STAR", "...": "ELLIPSIS", "==": "EQ", "!=": "EQ", "<=": "REL", ">=": "REL",
    "<<": "SHIFT", ">>": "SHIFT", "&&": "AND", "||": "OR",
    **{op + "=": "ASSIGN_OP" for op in "+ - * / % & | ^ << >>".split()},
}
_DIGRAPHS = {"<:": "[", ":>": "]", "<%": "{", "%>": "}", "%:": "#", "%:%:": "##"}
_PUNCT = re.compile("|".join(map(re.escape, sorted([*_OPERATORS, *_DIGRAPHS], key=len, reverse=True))))
_ID_NONDIGIT = r"(?:[a-zA-Z_]|[^\x00-\x7f]|\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8})"
_IDENT = re.compile(rf"{_ID_NONDIGIT}(?:{_ID_NONDIGIT}|[0-9])*")
_UCN = re.compile(r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})")
_LITERAL = re.compile(r'''(?:u8|u|U|L)?(?:R"|["'])''')
_PP_NUMBER = re.compile(rf"(?:[0-9]|\.[0-9])(?:[eEpP][+-]|[0-9.]|{_ID_NONDIGIT}|'[0-9A-Za-z_])*")
_DEC = r"[0-9](?:'?[0-9])*"
_HEX = r"[0-9a-fA-F](?:'?[0-9a-fA-F])*"
_FLOAT_BODY = (rf"(?:0[xX](?:{_HEX}(?:\.(?:{_HEX})?)?|\.{_HEX})[pP][+-]?{_DEC}"
               rf"|(?:{_DEC}\.(?:{_DEC})?|\.{_DEC})(?:[eE][+-]?{_DEC})?|{_DEC}[eE][+-]?{_DEC})")
_INT_BODY = rf"(?:0[xX]{_HEX}|0[bB][01](?:'?[01])*|0(?:'?[0-7])*|[1-9](?:'?[0-9])*)"
_FLOAT_LITERAL = re.compile(rf"{_FLOAT_BODY}([fFlL]?)")


def floating_literal_type(raw):
    match = _FLOAT_LITERAL.fullmatch(raw)
    if match:
        return {"": ("double",), "l": ("double", "long"), "f": ("float",)}[match[1].lower()]
    return None


_NUMBER = re.compile(rf"{_FLOAT_BODY}[fFlL]?|{_INT_BODY}(?:[uU](?:ll|LL|[lL])?|(?:ll|LL|[lL])[uU]?)?")
_UNSUFFIXED_NUMBER = re.compile(rf"(?P<floating>{_FLOAT_BODY})|(?P<integer>{_INT_BODY})")
_NEWLINE = re.compile(r"\r\n|[\r\n]")
_SPLICE = re.compile(r"\\(?:\r\n|\r|\n)")
_MARKER = re.compile(r'#[ \t]*[0-9]+[ \t]+"(?:[^"\\\r\n]|\\[^\r\n])*"(?:[ \t]+[0-9]+)*[ \t]*(?=[\r\n]|$)')
_PRAGMA = re.compile(r'#[ \t]*pragma\b[^\r\n]*')
_ESCAPE = re.compile(r"""\\(?:['"?\\abfnrtv]|[0-7]{1,3}|x[0-9a-fA-F]+|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})""")
_SIMPLE_ESCAPES = {"'": 39, '"': 34, "?": 63, "\\": 92, "a": 7, "b": 8,
                   "f": 12, "n": 10, "r": 13, "t": 9, "v": 11}


def is_integer_zero_literal(spelling):
    """The token has already passed ordinary literal validation."""
    digits = spelling.lower().rstrip("ul").replace("'", "")
    if digits.startswith(("0x", "0b")):
        digits = digits[2:]
    return bool(digits) and not digits.strip("0")


# UTF-8 execution characters and 32-bit wchar_t on the reference target.
_CODE_UNIT_WIDTH = {"": 8, "u8": 8, "u": 16, "U": 32, "L": 32}


def character_argument(literal):
    prefix = literal.get("encodingPrefix", "")
    unit = literal.get("codeUnit")
    if unit is None:
        body = literal["raw"][1:-1]
        if len(body) == 1:
            unit = ord(body)
        elif _ESCAPE.fullmatch(body):
            tag = body[1]
            if tag in _SIMPLE_ESCAPES:
                unit = _SIMPLE_ESCAPES[tag]
            else:
                digits, base = (body[2:], 16) if tag in "xuU" else (body[1:], 8)
                unit = int(digits, base)
        else:
            return None
    width = _CODE_UNIT_WIDTH[prefix]
    if unit >= 1 << width:
        return None
    if prefix in ("", "L") and unit >= 1 << (width - 1):
        unit -= 1 << width
    return {"": "char", "L": "wchar_t", "u8": "char8_t", "u": "char16_t", "U": "char32_t"}[prefix], unit


def string_array_extent(literal):
    """Count code units in already validated, concatenated string tokens, including the terminator."""
    width = _CODE_UNIT_WIDTH[literal.get("encodingPrefix", "")]
    encoding = {8: "utf-8", 16: "utf-16-le", 32: "utf-32-le"}[width]

    def units(text):
        return len(text.encode(encoding)) // (width // 8)

    count = 1
    for part in literal["parts"]:
        prefix, _, body = part.partition('"')
        if prefix.endswith("R"):
            count += units(body[body.index("(") + 1:body.rindex(")")])
            continue
        body = body[:-1]
        end = 0
        for match in _ESCAPE.finditer(body):
            count += units(body[end:match.start()])
            escape = match[0]
            count += units(chr(int(escape[2:], 16))) if escape[1] in "uU" else 1
            end = match.end()
        count += units(body[end:])
    return count


class CppSource:
    def __init__(self, source):
        self.source = source
        self.lines = [0, *(m.end() for m in _NEWLINE.finditer(source))]

        # Mapping is sparse even for large preprocessed translation units.
        self.splice_starts = []
        self.splice_ends = []
        self.logical_breaks = []
        self.removed = [0]
        self.raw_splices = set()
        for match in _SPLICE.finditer(source):
            self.splice_starts.append(match.start())
            self.splice_ends.append(match.end())
            self.logical_breaks.append(match.start() - self.removed[-1])
            self.removed.append(self.removed[-1] + len(match[0]))
        self.logical = _SPLICE.sub("", source) if self.splice_starts else source

    def physical_pos(self, logical):
        return logical + self.removed[bisect_right(self.logical_breaks, logical)]

    def logical_pos(self, physical):
        return physical - self.removed[bisect_right(self.splice_ends, physical)]

    def spelling(self, start, end):
        if not self.splice_starts:
            return self.source[start:end]
        parts = []
        for i in range(bisect_left(self.splice_starts, start), bisect_left(self.splice_starts, end)):
            if i not in self.raw_splices:
                parts.append(self.source[start:self.splice_starts[i]])
                start = self.splice_ends[i]
        return "".join(parts) + self.source[start:end]

    def lex_error(self, logical, message):
        return self.error(self.physical_pos(logical), message)

    @staticmethod
    def attribute_identifier(token):
        return _IDENT.fullmatch(token.spelling) is not None

    def error(self, offset, message):
        return CParseError(self.source, offset, message)

    def identifier_value(self, spelling, start):
        if spelling.isascii() and "\\" not in spelling:
            return spelling
        normalized = []
        offset = 0
        while offset < len(spelling):
            char = spelling[offset]
            index = offset
            if char == "\\":
                match = _UCN.match(spelling, offset)
                cp = int(match[1] or match[2], 16)
                offset = match.end()
            else:
                cp = ord(char)
                offset += 1
            if (cp >= 128 or char == "\\") and not valid_identifier_scalar(cp, initial=not normalized):
                raise self.lex_error(start + index, "character not allowed in C++ identifier")
            normalized.append(chr(cp))
        return "".join(normalized)

    def quoted_literal(self, start, head):
        s = self.logical
        pos = head.end()
        quote = s[pos-1]
        code_unit = None
        wide_escapes = []
        if head[0].endswith('R"'):
            # Phase 2 is reversed between the raw literal's quotes, including its delimiters.
            physical = self.source
            opening = self.physical_pos(pos - 1) + 1
            bracket = opening
            while bracket < len(physical) and physical[bracket] != "(":
                char = physical[bracket]
                if bracket - opening == 16 or not ("!" <= char <= "~") or char in ")\\@$`":
                    raise self.error(bracket, "invalid raw string delimiter")
                bracket += 1
            if bracket == len(physical):
                raise self.lex_error(start, "unterminated raw string delimiter")
            closing = ")" + physical[opening:bracket] + '"'
            end = physical.find(closing, bracket+1)
            if end == -1:
                raise self.lex_error(start, "unterminated raw string literal")
            end += len(closing)
            self.raw_splices.update(range(bisect_left(self.splice_starts, opening), bisect_left(self.splice_starts, end)))
            pos = self.logical_pos(end)
        else:
            prefix = head[0][:-1]
            width = _CODE_UNIT_WIDTH[prefix]
            while pos < len(s) and s[pos] != quote:
                if s[pos] in "\r\n":
                    raise self.lex_error(start, "unterminated literal")
                if quote == "'" and prefix and pos != head.end():
                    raise self.lex_error(start, "prefixed character literal contains multiple characters")
                if s[pos] != "\\":
                    scalar = ord(s[pos])
                    pos += 1
                else:
                    escape = _ESCAPE.match(s, pos)
                    if escape is None:
                        raise self.lex_error(pos, "invalid literal escape")
                    tag = escape[0][1]
                    scalar = None
                    if tag in "uU":
                        scalar = int(escape[0][2:], 16)
                        if scalar > 0x10FFFF or 0xD800 <= scalar <= 0xDFFF:
                            raise self.lex_error(pos, "invalid universal character in literal")
                    elif tag in _SIMPLE_ESCAPES:
                        code_unit = _SIMPLE_ESCAPES[tag]
                    else:
                        if tag == "x":
                            digits = escape[0][2:].lstrip("0")
                            # Saturate above the largest supported code unit, even for very long escapes.
                            value = int(digits or "0", 16) if len(digits) <= 8 else 1 << 32
                        else:
                            value = int(escape[0][1:], 8)
                        if quote == "'":
                            if value.bit_length() > width:
                                raise self.lex_error(pos, "numeric escape exceeds character code unit")
                            code_unit = value
                        elif value.bit_length() > 8:
                            wide_escapes.append((self.physical_pos(pos), value.bit_length()))
                    pos = escape.end()
                if quote == "'" and scalar is not None:
                    if (width == 8 and scalar > 0x7F) or (width == 16 and scalar > 0xFFFF):
                        raise self.lex_error(start, "character requires more than one code unit")
                    code_unit = scalar
            if pos == len(s) or (quote == "'" and pos == head.end()):
                raise self.lex_error(start, "invalid or unterminated literal")
            pos += 1
        suffix = _IDENT.match(s, pos)
        if suffix:
            return suffix.end(), self.identifier_value(suffix[0], pos), code_unit, wide_escapes
        return pos, None, code_unit, wide_escapes

    def tokens(self):
        prefix = ""
        pending = []
        for token in self.raw_tokens():
            if token.type == "STRING":
                prefix = prefix or token.encoding_prefix
                pending.extend(token.wide_escapes)
            elif prefix or pending:
                self.check_string_escapes(pending, prefix)
                prefix = ""
                pending.clear()
            yield token
        self.check_string_escapes(pending, prefix)

    def check_string_escapes(self, pending, prefix):
        for offset, bits in pending:
            if bits > _CODE_UNIT_WIDTH[prefix]:
                raise self.error(offset, "numeric escape exceeds concatenated string code unit")

    def raw_tokens(self):
        s = self.logical
        pos = 0
        beginning = True
        after_export = header = False
        while pos < len(s):
            start = pos
            user_defined = None
            c = s[pos]
            if c in " \t\v\f":
                pos += 1
                continue
            if c in "\r\n":
                pos = _NEWLINE.match(s, pos).end()
                beginning, after_export, header = True, False, False
                continue
            if s.startswith("//", pos):
                newline = _NEWLINE.search(s, pos+2)
                pos = newline.start() if newline else len(s)
                continue
            if s.startswith("/*", pos):
                end = s.find("*/", pos+2)
                if end < 0:
                    raise self.lex_error(pos, "unterminated block comment")
                pos = end+2
                if _NEWLINE.search(s, start, pos):
                    beginning, after_export, header = True, False, False
                continue
            if beginning and c == "#" and (line := _MARKER.match(s, pos) or _PRAGMA.match(s, pos)):
                pos = line.end()
                continue
            if header and c in '<"':
                end = s.find(">" if c == "<" else '"', pos+1)
                if end < pos+2 or _NEWLINE.search(s, pos, end):
                    raise self.lex_error(pos, "invalid header name")
                pos, kind = end+1, "HEADER"
            elif literal := _LITERAL.match(s, pos):
                pos, suffix, code_unit, wide_escapes = self.quoted_literal(start, literal)
                kind = "STRING" if literal[0].endswith('"') else "CHARACTER"
                if suffix:
                    suffix_start = s.rindex(literal[0][-1], start, pos) + 1
                    suffix_offset = self.physical_pos(suffix_start)
                    user_defined = {"kind": kind.lower(), "suffix": suffix}
            elif ident := _IDENT.match(s, pos):
                spelling = ident[0]
                pos = ident.end()
                kind = "IDENT"
                if spelling in BUILTINS:
                    kind = "BUILTIN"
                elif spelling in _SPECIFIERS:
                    kind = "SPECIFIER"
                elif spelling in {"__alignof", "__alignof__"}:
                    kind = "GNU_ALIGNOF"
                elif spelling == "__make_integer_seq":
                    kind = "MAKE_INTEGER_SEQ"
                elif spelling == "__type_pack_element":
                    kind = "PACK_ELEMENT"
                elif spelling in {"__typeof", "__typeof__"}:
                    kind = "GNU_TYPEOF"
                elif spelling == "__builtin_bit_cast":
                    kind = "BUILTIN_BIT_CAST"
                elif spelling in {"__restrict", "__restrict__"}:
                    kind = "GNU_RESTRICT"
                elif spelling in {"__asm", "__asm__"}:
                    kind = "GNU_ASM"
                elif spelling in {"__inline", "__inline__"}:
                    kind = "INLINE"
                elif spelling == "__extension__":
                    kind = "GNU_EXTENSION"
                elif spelling == "__decltype":
                    kind = "DECLTYPE"
                elif spelling in _KEYWORDS:
                    kind = spelling.upper()
                elif spelling in _ALTERNATIVES:
                    op = _ALTERNATIVES[spelling]
                    kind = _OPERATORS.get(op, op)
                elif spelling in {"module", "import"} and (beginning or after_export):
                    kind = "MODULE_CANDIDATE" if spelling == "module" else "IMPORT_CANDIDATE"
            elif number := _PP_NUMBER.match(s, pos):
                spelling = number[0]
                if not _NUMBER.fullmatch(spelling):
                    # Match the literal before inspecting the suffix: e and p can introduce exponents.
                    body = _UNSUFFIXED_NUMBER.match(spelling)
                    if body is None or not _IDENT.fullmatch(spelling, body.end()):
                        raise self.lex_error(pos, "invalid numeric literal")
                    suffix = self.identifier_value(spelling[body.end():], pos + body.end())
                    user_defined = {"kind": body.lastgroup, "number": body[0], "suffix": suffix}
                pos, kind = number.end(), "NUMBER"
            elif s.startswith("<::", pos) and s[pos+3:pos+4] not in (":", ">"):
                pos, kind = pos+1, "<"
            elif punct := _PUNCT.match(s, pos):
                pos = punct.end()
                kind = _OPERATORS.get(punct[0]) or _DIGRAPHS[punct[0]]
            elif c in "{}[]();,:?~!%^&*+-=/<>|.":
                pos, kind = pos+1, c
            else:
                raise self.lex_error(pos, f"unexpected character {c!r}")
            token = LexToken()
            if self.splice_starts:
                token.lexpos = self.physical_pos(start)
                token.endlexpos = self.physical_pos(pos-1) + 1
            else:
                token.lexpos, token.endlexpos = start, pos
            token.spelling = s[start:pos]
            if self.splice_starts and kind == "STRING" and literal[0].endswith('R"'):
                token.spelling = self.spelling(token.lexpos, token.endlexpos)
            token.value = _ALTERNATIVES.get(token.spelling, _DIGRAPHS.get(token.spelling, token.spelling))
            if kind == "IDENT":
                token.value = self.identifier_value(token.value, start)
            if kind in {"STRING", "CHARACTER"}:
                token.encoding_prefix = literal[0][:-1].removesuffix("R")
                if kind == "STRING":
                    token.wide_escapes = wide_escapes
                if kind == "CHARACTER" and token.encoding_prefix:
                    token.code_unit = code_unit
            if user_defined is not None:
                token.user_defined = user_defined
                if kind in {"STRING", "CHARACTER"}:
                    token.suffix_offset = suffix_offset
            token.type = kind
            token.lineno = bisect_right(self.lines, token.lexpos)
            after_export = beginning and kind == "EXPORT"
            header = kind == "IMPORT_CANDIDATE"
            beginning = False
            yield token
