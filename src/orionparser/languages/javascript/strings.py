"""Decode an ECMAScript StringLiteral starting at a quote."""
import re

_HEX = frozenset("0123456789abcdefABCDEF")
_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r"}


def read_string(source, start, strict, error, template=False):
    quote = source[start]
    value = []
    index = start + 1
    while index < len(source):
        char = source[index]
        index += 1
        if char == quote:
            cooked = "".join(value)
            if any(0xd800 <= ord(unit) <= 0xdfff for unit in cooked):
                cooked = cooked.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")
            return index, cooked
        if char in "\n\r" and not template:
            raise error(index - 1, "line break in string")
        if template and char == "\r":
            if source[index:index + 1] == "\n":
                index += 1
            value.append("\n")
            continue
        if char != "\\":
            value.append(char)
            continue
        escape = index - 1
        if index == len(source):
            break
        char = source[index]
        index += 1
        if char in "\n\r\u2028\u2029":
            if char == "\r" and source[index:index + 1] == "\n":
                index += 1
        elif char in "xu":
            if char == "u" and source[index:index + 1] == "{":
                end = source.find("}", index + 1)
                digits = source[index + 1:end]
                if end < 0 or not digits or not _HEX.issuperset(digits):
                    raise error(escape, "invalid Unicode escape")
                index = end + 1
            else:
                length = 4 if char == "u" else 2
                digits = source[index:index + length]
                if len(digits) != length or not _HEX.issuperset(digits):
                    raise error(escape, "invalid hexadecimal escape")
                index += length
            significant = digits.lstrip("0") or "0"
            if len(significant) > 6 or int(significant, 16) > 0x10ffff:
                raise error(escape, "Unicode escape outside code point range")
            value.append(chr(int(significant, 16)))
        elif char in "0123456789":
            if strict and (char != "0" or source[index:index + 1] in tuple("0123456789")):
                raise error(escape, "legacy decimal escape")
            if char in "89":
                value.append(char)
            else:
                remaining = 2 if char in "0123" else 1
                suffix = re.match(r"[0-7]*", source[index:index + remaining])[0]
                index += len(suffix)
                value.append(chr(int(char + suffix, 8)))
        else:
            value.append(_ESCAPES.get(char, char))
    raise error(start, "unterminated string")
