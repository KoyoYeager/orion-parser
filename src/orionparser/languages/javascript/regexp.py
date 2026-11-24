"""PLY grammar for RegExp alternatives, assertions, groups, atoms and quantifiers."""
import copy
import re
import threading

from ply import lex, yacc

from ..typescript.spelling import spelling_suggestion
from .identifiers import identifier_char
from .regexp_sets import read_set
from .unicode_properties import BINARY, GENERAL_CATEGORY, SCRIPT, STRINGS


_FLAG_MINIMUM_YEAR = {"u": 2015, "y": 2015, "s": 2018, "d": 2022, "v": 2024}


def check_flag_target(flag, target_year, diagnostics, component, offset):
    minimum = _FLAG_MINIMUM_YEAR.get(flag, 0)
    if target_year < minimum:
        diagnostics.append({"code": 1501, "component": component, "offset": offset, "length": 1,
                            "message": f"RegExp flag {flag} requires ES{minimum} or later"})


_PROPERTY_WORD = re.compile(r"[A-Za-z0-9_]*")
_BRACED_IDENTIFIER_PREFIX = re.compile(r"\\u\{([0-9A-Fa-f]+)")
_PROPERTY_VALUES = {"General_Category": GENERAL_CATEGORY, "gc": GENERAL_CATEGORY, "Script": SCRIPT, "sc": SCRIPT,
                    "Script_Extensions": SCRIPT, "scx": SCRIPT}


def surrogate_units(char):
    scalar = ord(char) - 0x10000
    return chr(0xd800 + (scalar >> 10)), chr(0xdc00 + (scalar & 0x3ff))


class PatternGrammar:
    typescript = False
    tokens = ("ATOM", "OPEN", "CLOSE", "ASSERTION", "BAR", "QUANTIFIER", "QUESTION")
    start = "alternatives"
    # Attach a quantifier to the preceding atom and a lazy suffix to its quantifier.
    precedence = (("nonassoc", "TERM_END"), ("nonassoc", "QUANTIFIER", "QUESTION"))

    def t_OPEN(self, token):
        r"\(\?(?:[:=!]|<[=!]|<)|\("
        if self.typescript and token.value == "(" and self.pattern.startswith("?", token.lexer.lexpos):
            token.modifiers, end = self.scoped_modifiers(token.lexer.lexpos + 1)
            token.value = self.pattern[token.lexpos:end]
            token.lexer.lexpos = end
        if token.value in {"(", "(?<"}:
            self.capture_index += 1
            token.capture_index = self.capture_index
        if token.value == "(?<":
            start = token.lexer.lexpos
            name, scanner_name, name_end = self.group_name(start)
            if name:
                duplicate = any(scanner_name in scope for scope in self.capture_scopes) if self.typescript else name in self.group_names
                if duplicate:
                    self.pattern_diagnostic(1515, start, name_end, "duplicate capture group name")
                elif self.typescript:
                    if name in self.ecma_group_names:
                        self.compatibility.append({"offset": self.offset + token.lexpos,
                                                   "message": "duplicate capture group name in ECMAScript 2024"})
                    self.capture_scopes[-1].add(scanner_name)
                self.ecma_group_names.add(name)
                self.group_names[scanner_name] = None
            end = self.close_group_name(name_end)
            if self.target_year < 2018:
                opening = token.lexpos + 2
                self.pattern_diagnostic(1503, opening, end, "named capture requires ES2018 or later")
            token.group_name = name
            if scanner_name != name:
                token.scanner_name = scanner_name
            token.lexer.lexpos = end
        if self.typescript:
            self.capture_scopes.append(set())
        return token

    def scoped_modifiers(self, start):
        pos, seen = start, set()

        def read_flags():
            nonlocal pos
            first = pos
            while pos < len(self.pattern) and self.identifier_char(self.pattern[pos], first=False):
                flag = self.pattern[pos]
                if flag not in "dgimsuvy":
                    self.pattern_diagnostic(1499, pos, pos + 1, "unknown RegExp flag")
                elif flag in seen:
                    self.pattern_diagnostic(1500, pos, pos + 1, "duplicate inline RegExp modifier")
                elif flag not in "ims":
                    self.pattern_diagnostic(1509, pos, pos + 1, "flag cannot be toggled inside a subpattern")
                else:
                    seen.add(flag)
                    check_flag_target(flag, self.target_year, self.diagnostics, "pattern", self.offset + pos)
                pos += 1
            return self.pattern[first:pos]

        enabled, disabled = read_flags(), ""
        if self.pattern.startswith("-", pos):
            pos += 1
            disabled = read_flags()
            if not enabled and not disabled:
                self.pattern_diagnostic(1504, start, pos, "missing inline RegExp modifier")
        modifiers = {"enable": enabled, "disable": disabled}
        if self.pattern.startswith(":", pos):
            return modifiers, pos + 1
        self.pattern_diagnostic(1005, pos, pos, "expected colon after inline RegExp modifiers")
        modifiers["missingColon"] = True
        return modifiers, pos

    def t_CLOSE(self, token):
        r"\)"
        if self.typescript:
            if len(self.capture_scopes) > 1:
                self.capture_scopes.pop()
            else:
                self.pattern_diagnostic(1508, token.lexpos, token.lexpos + 1, "unexpected closing parenthesis")
                token.type, token.value = "ATOM", {"type": "Character", "value": ")"}
        return token

    def t_BAR(self, token):
        r"\|"
        if self.typescript:
            self.capture_scopes[-1].clear()
        return token

    def t_ASSERTION(self, token):
        r"[\^$]|\\[bB]"
        return token

    def t_QUANTIFIER(self, token):
        r"[+*]|\{[0-9]*(?:,[0-9]*)?\}?"
        if token.value[0] != "{":
            return token
        closed = token.value.endswith("}")
        bounds = token.value[1:-1] if closed else token.value[1:]
        low, comma, high = bounds.partition(",")
        start = token.lexpos
        end = start + 1 + len(bounds)
        missing_min = not low and comma and (high or closed)
        if ((not low and not (self.typescript and self.unicode and missing_min)) or
                (not closed and not self.unicode)):
            if self.unicode:
                self.pattern_diagnostic(1508, start, start + 1, "unescaped opening brace")
            token.lexer.lexpos = start + 1
            token.type, token.value = "ATOM", {"type": "Character", "value": "{"}
            return token
        if missing_min:
            self.pattern_diagnostic(1505, start + 1, start + 1, "quantifier minimum expected")
        if low and high:
            low, high = low.lstrip("0") or "0", high.lstrip("0") or "0"
            if (len(low), low) > (len(high), high):
                if self.typescript and float(low) == float(high):
                    self.compatibility.append({"offset": self.offset + start, "message": "quantifier bounds reversed in ECMAScript"})
                else:
                    self.pattern_diagnostic(1506, start + 1, end, "quantifier range out of order")
        if not closed:
            self.pattern_diagnostic(1005, end, end, "expected }")
        return token

    t_QUESTION = r"\?"

    def t_ATOM(self, token):
        r"\\[\s\S]|\[|[^()|*+?\\\[]"
        text = token.value
        if text == "[":
            token.value, token.lexer.lexpos = self.character_class(token.lexpos)
        elif text.startswith("\\"):
            token.value, token.lexer.lexpos = self.escape(token.lexpos, in_class=False)
        elif text == ".":
            token.value = {"type": "Wildcard"}
        else:
            if self.unicode and text in "}]":
                self.pattern_diagnostic(1508, token.lexpos, token.lexpos + 1, "unescaped syntax character")
            token.value = {"type": "Character", "value": text}
        return token

    def group_name(self, start):
        index, chars, scanner_chars = start, [], []
        after_escape = None
        while index < len(self.pattern):
            char = self.pattern[index]
            end = index + 1
            escaped = char == "\\"
            missing_brace = False
            if escaped:
                if (self.typescript and not chars) or not self.pattern.startswith("\\u", index):
                    break
                char, end = self.unicode_escape(index, code_points=True, combine_surrogates=not self.typescript)
                if char is None:
                    # The TS identifier lookahead tests the scalar before it checks the closing brace.
                    match = _BRACED_IDENTIFIER_PREFIX.match(self.pattern, index) if self.typescript else None
                    if not match or self.pattern.startswith("}", match.end()):
                        break
                    digits = match[1].lstrip("0") or "0"
                    if len(digits) > 6 or int(digits, 16) > 0x10ffff:
                        break
                    char, end, missing_brace = chr(int(digits, 16)), match.end(), True
            if not self.identifier_char(char, first=not chars):
                break
            if missing_brace:
                self.invalid_hex_escape(index)
                char = self.pattern[index:end]
            chars.append(char)
            if self.typescript and escaped and after_escape is not None and self.pattern.startswith("\\u{", index):
                # TS 5.9.3 drops pending unescaped text before a subsequent braced escape.
                del scanner_chars[after_escape:]
            scanner_chars.append(char)
            if escaped:
                after_escape = len(scanner_chars)
            index = end
        if not chars:
            self.pattern_diagnostic(1514, start, start, "expected a capturing group name")
        return "".join(chars) or None, "".join(scanner_chars) or None, index

    def close_group_name(self, index):
        if self.pattern.startswith(">", index):
            return index + 1
        self.pattern_diagnostic(1005, index, index, "expected > after capture group name")
        return index

    def unicode_escape(self, start, code_points, *, combine_surrogates=True):
        index = start + 2
        if code_points and self.pattern.startswith("{", index):
            match = re.match(r"\{([0-9a-fA-F]+)\}", self.pattern[index:])
            if not match:
                return None, index
            digits = match[1].lstrip("0") or "0"
            if len(digits) > 6 or int(digits, 16) > 0x10ffff:
                return None, index
            return chr(int(digits, 16)), index + match.end()
        match = re.match(r"[0-9a-fA-F]{4}", self.pattern[index:])
        if not match:
            return None, index
        cp = int(match[0], 16)
        index += 4
        if code_points and combine_surrogates and 0xd800 <= cp <= 0xdbff:
            low = re.match(r"\\u([dD][c-fC-F][0-9a-fA-F]{2})", self.pattern[index:])
            if low:
                cp = 0x10000 + ((cp - 0xd800) << 10) + int(low[1], 16) - 0xdc00
                index += low.end()
        return chr(cp), index

    def invalid_hex_escape(self, start):
        """Recover the exact prefix consumed by the TypeScript regexp scanner."""
        source = self.pattern
        digits = start + 2
        braced = source.startswith("\\u{", start)
        if braced:
            digits += 1
        end = digits
        limit = len(source) if braced else min(len(source), digits + (2 if source[start + 1] == "x" else 4))
        while end < limit and source[end] in "0123456789abcdefABCDEF":
            end += 1
        if not braced or end == digits:
            self.pattern_diagnostic(1125, end, end, "hexadecimal digit expected")
        else:
            significant = source[digits:end].lstrip("0")
            if len(significant) > 6 or int(significant or "0", 16) > 0x10ffff:
                self.pattern_diagnostic(1198, digits, end, "Unicode code point out of range")
        if braced:
            if end == len(source):
                self.pattern_diagnostic(1126, end, end, "unexpected end of text")
            elif source[end] == "}":
                end += 1
            else:
                self.pattern_diagnostic(1199, end, end, "unterminated Unicode escape")
        return {"type": "InvalidEscape", "value": source[start:end]}, end

    def suggest_spelling(self, start, end, name, candidates):
        suggestion = spelling_suggestion(name, candidates)
        if suggestion is not None:
            self.pattern_diagnostic(1369, start, end, f"did you mean {suggestion}?")
            self.diagnostics[-1]["suggestion"] = suggestion

    def typescript_property_escape(self, start):
        source = self.pattern
        negate = source[start + 1] == "P"
        pos = start + 2
        if not source.startswith("{", pos):
            self.pattern_diagnostic(1531, start, pos, "Unicode property escape requires braces")
            return {"type": "UnicodePropertyEscape", "name": None, "value": None, "negate": negate,
                    "strings": False, "missingBraces": True}, pos
        name_start = pos + 1
        name_token = _PROPERTY_WORD.match(source, name_start)
        name, pos = name_token[0], name_token.end()
        value = None
        strings = False
        if source.startswith("=", pos):
            values = _PROPERTY_VALUES.get(name)
            if not name:
                self.pattern_diagnostic(1523, pos, pos, "expected a Unicode property name")
            elif values is None:
                self.pattern_diagnostic(1524, name_start, pos, "unknown Unicode property name")
                self.suggest_spelling(name_start, pos, name, _PROPERTY_VALUES)
            value_start = pos + 1
            value_token = _PROPERTY_WORD.match(source, value_start)
            value, pos = value_token[0], value_token.end()
            if not value:
                self.pattern_diagnostic(1525, pos, pos, "expected a Unicode property value")
            elif values is not None and value not in values:
                self.pattern_diagnostic(1526, value_start, pos, "unknown Unicode property value")
                self.suggest_spelling(value_start, pos, value, values)
        elif not name:
            self.pattern_diagnostic(1527, pos, pos, "expected a Unicode property name or value")
        elif name in STRINGS:
            if not self.unicode_sets:
                self.pattern_diagnostic(1528, name_start, pos, "Unicode property of strings requires the v flag")
            elif negate:
                self.pattern_diagnostic(1518, name_start, pos, "negated property may contain strings")
            else:
                strings = True
        elif name not in GENERAL_CATEGORY and name not in BINARY:
            self.pattern_diagnostic(1529, name_start, pos, "unknown Unicode property name or value")
            self.suggest_spelling(name_start, pos, name, (*GENERAL_CATEGORY, *BINARY, *STRINGS))
        node = {"type": "UnicodePropertyEscape", "name": name, "value": value, "negate": negate, "strings": strings}
        if source.startswith("}", pos):
            pos += 1
        else:
            node["missingClose"] = True
            self.pattern_diagnostic(1005, pos, pos, "expected } after Unicode property")
        if not self.unicode:
            self.pattern_diagnostic(1530, start, pos, "Unicode property escape requires the u or v flag")
        return node, pos

    def escape(self, index, in_class):
        source = self.pattern
        char = source[index + 1:index + 2]
        if not char:
            self.fail(index, "incomplete RegExp escape")
        if char in "dDsSwW":
            return {"type": "CharacterSetEscape", "kind": char}, index + 2
        if char in "0123456789":
            digits = re.match(r"[0-9]+", source[index + 1:])[0]
            if digits == "0":
                return {"type": "Character", "value": "\0"}, index + 2
            largest = str(self.capture_count)
            if not in_class and char != "0" and (len(digits), digits) <= (len(largest), largest):
                return {"type": "Backreference", "index": int(digits)}, index + 1 + len(digits)
            if self.typescript and not in_class and char != "0":
                end = index + 1 + len(digits)
                self.unresolved_decimal.append((index + 1, end))
                if self.unicode:
                    return {"type": "InvalidBackreference", "raw": source[index:end]}, end
            if self.unicode and not self.typescript:
                self.fail(index, "invalid decimal escape")
            if char in "89":
                value, end = char, index + 2
            else:
                octal = re.match(r"[0-7]{1,%d}" % (3 if char in "0123" else 2), digits)[0]
                value, end = chr(int(octal, 8)), index + 1 + len(octal)
            if self.typescript and (in_class or char == "0"):
                code = 1537 if char in "89" else 1487 if char == "0" else 1536
                self.pattern_diagnostic(code, index, end, "invalid decimal or octal escape")
            return {"type": "Character", "value": value}, end
        if char == "q" and self.typescript and self.unicode_sets and not in_class:
            self.pattern_diagnostic(1511, index, index + 2, "string alternatives require a UnicodeSets class")
            return {"type": "InvalidEscape", "value": source[index:index + 2]}, index + 2
        if char == "k" and in_class and (self.unicode or self.has_named):
            if not self.typescript or self.unicode:
                self.pattern_diagnostic(1535, index, index + 2, "invalid character escape in class")
            return {"type": "Character", "value": "k"}, index + 2
        if char == "k" and not in_class and (self.typescript or self.unicode or self.has_named):
            if source.startswith("<", index + 2):
                start = index + 3
                name, scanner_name, name_end = self.group_name(start)
                if name:
                    self.references.append((scanner_name, start, name_end))
                node = {"type": "Backreference", "name": name}
                if scanner_name != name:
                    node["scannerName"] = scanner_name
                return node, self.close_group_name(name_end)
            if self.unicode or self.has_named:
                self.pattern_diagnostic(1510, index, index + 2, "expected a capture group name after backreference")
                return {"type": "InvalidEscape", "value": source[index:index + 2]}, index + 2
        if char in "pP" and self.typescript and (self.unicode or source.startswith("{", index + 2)):
            return self.typescript_property_escape(index)
        if char in "pP" and self.unicode:
            prop = re.match(r"\{([A-Za-z0-9_]+)(?:=([A-Za-z0-9_]+))?\}", source[index + 2:])
            if not prop:
                self.fail(index, "invalid Unicode property escape")
            name, value = prop.groups()
            strings = value is None and name in STRINGS
            if value is None:
                valid = name in BINARY or name in GENERAL_CATEGORY or (self.unicode_sets and strings and char == "p")
            else:
                valid = ((name in {"gc", "General_Category"} and value in GENERAL_CATEGORY) or
                         (name in {"sc", "Script", "scx", "Script_Extensions"} and value in SCRIPT))
            if not valid:
                self.fail(index, "unknown or disallowed Unicode property")
            return ({"type": "UnicodePropertyEscape", "name": name, "value": value,
                     "negate": char == "P", "strings": strings}, index + 2 + prop.end())
        if char == "u":
            braced_legacy = self.typescript and not self.unicode and source.startswith("{", index + 2)
            value, end = self.unicode_escape(index, self.unicode or braced_legacy)
            if value is not None:
                node = {"type": "Character", "value": value}
            elif self.typescript:
                node, end = self.invalid_hex_escape(index)
            elif self.unicode:
                self.fail(index, "invalid Unicode escape")
            else:
                return {"type": "Character", "value": "u"}, index + 2
            if braced_legacy:
                self.pattern_diagnostic(1538, index, end, "braced Unicode escape requires the u or v flag")
            return node, end
        if char == "x":
            match = re.match(r"[0-9A-Fa-f]{2}", source[index + 2:])
            if match:
                return {"type": "Character", "value": chr(int(match[0], 16))}, index + 4
            if self.typescript:
                return self.invalid_hex_escape(index)
            if self.unicode:
                self.fail(index, "invalid hexadecimal RegExp escape")
        controls = {"t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r"}
        if in_class:
            controls["b"] = "\b"
        if char == "c":
            letter = source[index + 2:index + 3]
            if letter.isascii() and letter.isalpha():
                return {"type": "Character", "value": chr(ord(letter) % 32)}, index + 3
            if self.typescript and self.unicode:
                self.pattern_diagnostic(1512, index, index + 2, "control escape requires an ASCII letter")
                # The scanner returns the following UTF-16 unit and leaves it for the next atom.
                value = letter or "\uffff"
                if ord(value) > 0xffff:
                    value = surrogate_units(value)[0]
                return {"type": "Character", "value": value}, index + 2
            if not self.unicode:
                if in_class and letter and letter in "0123456789_":
                    return {"type": "Character", "value": chr(ord(letter) % 32)}, index + 3
                return {"type": "Character", "value": "\\"}, index + 1
            self.fail(index, "invalid RegExp control escape")
        syntax = "^$\\.*+?()[]{}|/" + ("-" if in_class else "")
        if self.unicode and char not in syntax and char not in controls:
            self.pattern_diagnostic(1535, index, index + 2, "invalid identity escape")
        return {"type": "Character", "value": controls.get(char, char)}, index + 2

    def character_class(self, start):
        source = self.pattern
        if self.unicode_sets:
            return read_set(self, start)
        index = start + 1
        negate = source[index:index + 1] == "^"
        index += int(negate)
        atoms = []
        while index < len(source) and source[index] != "]":
            begin = index
            if source[index] == "\\":
                node, index = self.escape(index, in_class=True)
                atoms.append((node, begin, index))
            else:
                char = source[index]
                index += 1
                if not self.unicode and ord(char) > 0xffff:
                    atoms.extend(({"type": "Character", "value": unit}, begin, index) for unit in surrogate_units(char))
                else:
                    atoms.append((char if char == "-" else {"type": "Character", "value": char}, begin, index))
        if index == len(source):
            self.fail(start, "unterminated character class")
        terms = []
        cursor = 0
        while cursor < len(atoms):
            left, left_start, left_end = atoms[cursor]
            if left == "-":
                left = {"type": "Character", "value": "-"}
            if cursor + 2 < len(atoms) and atoms[cursor + 1][0] == "-":
                right, right_start, right_end = atoms[cursor + 2]
                if right == "-":
                    right = {"type": "Character", "value": "-"}
                if all(node["type"] in {"Character", "InvalidEscape"} for node in (left, right)):
                    if left["type"] == right["type"] == "Character" and ord(left["value"]) > ord(right["value"]):
                        self.pattern_diagnostic(1517, left_start, right_end, "character class range out of order")
                    terms.append({"type": "CharacterRange", "min": left, "max": right})
                elif self.unicode:
                    for node, begin, end in ((left, left_start, left_end), (right, right_start, right_end)):
                        if node["type"] not in {"Character", "InvalidEscape"}:
                            self.pattern_diagnostic(1516, begin, end, "invalid character class range endpoint")
                    terms.append({"type": "CharacterRange", "min": left, "max": right})
                else:
                    terms.extend([left, {"type": "Character", "value": "-"}, right])
                cursor += 3
            else:
                terms.append(left)
                cursor += 1
        return {"type": "CharacterClass", "negate": negate, "elements": terms}, index + 1

    def pattern_diagnostic(self, code, start, end, message):
        if not self.typescript:
            self.fail(start, message)
        self.diagnostics.append({"component": "pattern", "offset": self.offset + start, "length": end - start,
                                 "code": code, "message": message})

    def atom_tokens(self, lexer):
        for token in lexer:
            if (not self.unicode and token.type == "ATOM" and token.value["type"] == "Character"
                    and ord(token.value["value"]) > 0xffff):
                # In legacy mode a quantifier consumes the trailing UTF-16 unit.
                high, low = surrogate_units(token.value["value"])
                first = copy.copy(token)
                first.value = {"type": "Character", "value": high}
                yield first
                token.value = {"type": "Character", "value": low}
            yield token
        while self.typescript and len(self.capture_scopes) > 1:
            self.capture_scopes.pop()
            closing = lex.LexToken()
            closing.type, closing.value = "CLOSE", ""
            closing.lexpos, closing.lineno = len(self.pattern), 1
            yield closing

    def t_error(self, token):
        self.fail(token.lexpos, "invalid RegExp token")

    def p_alternatives(self, p):
        """alternatives : sequence
                        | alternatives BAR sequence"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_sequence(self, p):
        """sequence :
                    | sequence term"""
        if len(p) == 1:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_term(self, p):
        """term : atom %prec TERM_END
                | ASSERTION
                | atom quantifier %prec TERM_END
                | atom quantifier QUESTION"""
        if len(p) == 2:
            p[0] = {"type": "Assertion", "kind": p[1]} if p.slice[1].type == "ASSERTION" else p[1]
        else:
            if p[1].get("kind") in {"(?<=", "(?<!"} or (self.unicode and p[1].get("kind") in {"(?=", "(?!"}):
                self.pattern_diagnostic(1507, p.lexpos(2), p.lexpos(2) + len(p[2]) + (len(p) == 4),
                                        "quantified assertion")
            p[0] = {"type": "Quantified", "atom": p[1], "quantifier": p[2], "greedy": len(p) == 3}

    def p_orphan_quantifier(self, p):
        """term : quantifier %prec TERM_END
                | quantifier QUESTION"""
        lazy = len(p) == 3
        self.pattern_diagnostic(1507, p.lexpos(1), p.lexpos(1) + len(p[1]) + lazy, "nothing available for repetition")
        p[0] = {"type": "InvalidQuantifier", "quantifier": p[1], "greedy": not lazy}

    def p_quantifier(self, p):
        """quantifier : QUANTIFIER
                      | QUESTION"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = p[1]

    def p_atom(self, p):
        """atom : ATOM
                | OPEN alternatives CLOSE"""
        p[0] = p[1] if len(p) == 2 else {"type": "Group", "kind": p[1], "alternatives": p[2]}

        if len(p) == 4 and not p[3]:
            p[0]["missingClose"] = True
            self.pattern_diagnostic(1005, p.lexpos(3), p.lexpos(3), "expected closing parenthesis")
        if len(p) == 4 and hasattr(p.slice[1], "modifiers"):
            p[0]["modifiers"] = p.slice[1].modifiers
        if len(p) == 4 and hasattr(p.slice[1], "capture_index"):
            p[0]["index"] = p.slice[1].capture_index
            if hasattr(p.slice[1], "scanner_name"):
                p[0]["scannerName"] = p.slice[1].scanner_name
            if hasattr(p.slice[1], "group_name"):
                p[0]["name"] = p.slice[1].group_name

    def p_error(self, token):
        self.fail(token.lexpos if token else len(self.pattern), "invalid RegExp pattern")

    def note(self, offset, message):
        self.diagnostics.append({"component": "pattern", "offset": self.offset + offset, "message": message})

    def fail(self, offset, message):
        raise self.error(self.offset + offset, message)


_local = threading.local()
_lock = threading.Lock()


def check_capture_count(count, offset, error):
    if count >= 2**32 - 1:
        raise error(offset, "too many capturing groups")


class RegExpPatternError(ValueError):
    def __init__(self, offset, message):
        super().__init__(message)
        self.offset = offset


def scan_flags(flags, start, target_year=2024):
    diagnostics, seen = [], set()
    for index, flag in enumerate(flags):
        if flag not in "dgimsuvy":
            code, message = 1499, "unknown RegExp flag"
        elif flag in seen:
            code, message = 1500, "duplicate RegExp flag"
        elif (flag == "u" and "v" in seen) or (flag == "v" and "u" in seen):
            code, message = 1502, "incompatible Unicode RegExp flags"
        else:
            seen.add(flag)
            check_flag_target(flag, target_year, diagnostics, "flags", start + index)
            continue
        diagnostics.append({"code": code, "component": "flags", "offset": start + index, "length": 1, "message": message})
    return seen, diagnostics


def read_regexp(grammar, token):
    source = grammar.source
    start = token.lexpos + 1
    index = start
    in_class = False
    capture_count = 0
    has_named = False
    failure = None
    while index < len(source):
        char = source[index]
        if char in "\n\r\u2028\u2029":
            failure = (index, "line break in RegExp literal")
            break
        if char == "\\":
            index += 1
            if index == len(source) or source[index] in "\n\r\u2028\u2029":
                failure = (index, "incomplete RegExp escape")
                break
        elif char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "(" and not in_class:
            if not source.startswith("?", index + 1):
                capture_count += 1
            elif source.startswith("(?<", index) and source[index + 3:index + 4] not in {"=", "!"}:
                capture_count += 1
                has_named = True
        elif char == "/" and not in_class:
            break
        index += 1
    else:
        failure = (start - 1, "unterminated RegExp literal")
    if failure:
        if grammar.typescript_regexp:
            return grammar.unterminated_regexp(token, index)
        raise grammar.error(*failure)
    pattern = source[start:index]
    end = index + 1
    while end < len(source) and grammar.identifier_char(source[end], first=False):
        end += 1
    flags = source[index + 1:end]
    active_flags, diagnostics = scan_flags(flags, index + 1, grammar.regexp_target_year)
    if diagnostics and not grammar.typescript_regexp:
        raise grammar.error(index + 1, "invalid RegExp flags")
    error = RegExpPatternError if grammar.typescript_regexp else grammar.error
    compatibility = []
    try:
        check_capture_count(capture_count, start, error)
        alternatives = parse_pattern(pattern, active_flags, start, capture_count, has_named, error, grammar.typescript_regexp,
                                     diagnostics, compatibility, grammar.identifier_char, grammar.regexp_target_year)
    except RegExpPatternError as issue:
        # The TS source scanner accepts a delimited token. Keep validation failures
        # on that literal. Unterminated tokens have already raised a source error.
        diagnostics.append({"component": "pattern", "offset": issue.offset, "message": str(issue)})
        alternatives = None
    token.pattern = {"type": "RegExpLiteral", "pattern": pattern, "flags": flags, "alternatives": alternatives}
    if compatibility:
        token.pattern["compatibilityDiagnostics"] = compatibility
    if diagnostics:
        token.pattern["diagnostics"] = diagnostics
    token.type, token.value, grammar.lexer.lexpos = "REGEXP", source[token.lexpos:end], end


def parse_pattern(pattern, flags, start, capture_count, has_named, error, typescript, diagnostics, compatibility,
                  valid_char=identifier_char, target_year=2024):
    if not hasattr(_local, "driver"):
        with _lock:
            rules = PatternGrammar()
            lexer = lex.lex(module=rules)
            parser = yacc.yacc(module=rules, write_tables=False, debug=False)
        _local.driver = rules, lexer, parser
    rules, lexer, parser = _local.driver
    rules.diagnostics, rules.compatibility = diagnostics, compatibility
    rules.target_year = target_year
    rules.typescript = typescript
    rules.identifier_char = valid_char
    rules.ecma_group_names = set()
    rules.unresolved_decimal = []
    rules.capture_scopes = [set()]
    rules.pattern, rules.offset, rules.error = pattern, start, error
    rules.unicode, rules.unicode_sets = "u" in flags or "v" in flags, "v" in flags
    rules.capture_count, rules.capture_index = capture_count, 0
    rules.has_named, rules.group_names, rules.references = has_named, {}, []
    lexer.input(pattern)
    atoms = rules.atom_tokens(lexer)
    alternatives = parser.parse(lexer=lexer, tokenfunc=lambda: next(atoms, None))
    for name, start, end in rules.references:
        if name not in rules.group_names:
            rules.pattern_diagnostic(1532, start, end, f"unknown named capture {name}")
            rules.suggest_spelling(start, end, name, rules.group_names)
    for start, end in rules.unresolved_decimal:
        code = 1533 if capture_count else 1534
        rules.pattern_diagnostic(code, start, end, f"backreference exceeds the {capture_count} available capturing groups")
    return alternatives
