"""Scan IdentifierName, validating escaped code points in their lexical position."""
from bisect import bisect_right
import re

from .unicode_ranges import ID_START, ID_CONTINUE

IDENTIFIER_ESCAPE = re.compile(r"\\u(?:([0-9a-fA-F]{4})|\{([0-9a-fA-F]+)\})")


def identifier_char(char, first):
    if char in "$_":
        return True
    if char.isascii():
        return char.isalpha() or (not first and char.isdigit())
    if not first and char in "\u200c\u200d":
        return True
    bounds = ID_START if first else ID_CONTINUE
    return bisect_right(bounds, ord(char)) % 2 == 1


def scan_identifier(source, start, error, valid_char=identifier_char, *, jsx_name=False, recover_escape=None):
    index = start
    chars = []
    while index < len(source):
        char = source[index]
        if char == "\\":
            match = IDENTIFIER_ESCAPE.match(source, index)
            reason = None
            if not match:
                reason = "invalid identifier escape"
            else:
                digits = (match[1] or match[2]).lstrip("0") or "0"
                if len(digits) > 6 or int(digits, 16) > 0x10ffff:
                    reason = "invalid identifier code point"
                else:
                    char = chr(int(digits, 16))
                    if not valid_char(char, not chars):
                        reason = "invalid escaped identifier character"
            if reason is None:
                index = match.end()
            elif recover_escape is None:
                raise error(index, reason)
            else:
                recovered = recover_escape(index, not chars)
                if recovered is None:
                    break
                index, char = recovered
        elif valid_char(char, not chars) or (jsx_name and chars and char == "-"):
            index += 1
        else:
            break
        chars.append(char)
    if not chars and recover_escape is None:
        raise error(start, repr(source[start]))
    return index, "".join(chars)
