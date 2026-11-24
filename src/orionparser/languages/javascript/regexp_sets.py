"""PLY grammar for ECMAScript UnicodeSets-mode character classes."""
import threading

from ply import lex, yacc

_RESERVED = frozenset("&-!#%,:;<=>@`~")
_DOUBLE = frozenset("&!#$%*+,.:;<=>?@^`~")
_SYNTAX = frozenset("()[]{}/-\\|")
_STRING_ESCAPES = _SYNTAX | _RESERVED | frozenset("^$.*+?btnvfrcux0123456789")


def ts_set_contains_strings(expr):
    # TS 5.9's scanner propagates the first union operand's string flag.
    kind = expr["type"]
    if kind == "SetUnion":
        elements = expr["elements"]
        return bool(elements) and (ts_set_contains_strings(elements[0]) or
                                   any(e["type"] == "CharacterRange" and ts_set_contains_strings(e) for e in elements[1:]))
    if kind == "CharacterRange":
        return expr["max"] is not None and ts_set_contains_strings(expr["max"])
    if expr.get("expectedOperator") == "&&" or (kind == "SetIntersection" and "expectedOperator" not in expr):
        return ts_set_contains_strings(expr["left"]) and (expr["right"]["type"] == "MissingSetOperand" or
                                                         ts_set_contains_strings(expr["right"]))
    if kind in {"SetIntersection", "SetSubtraction"}:
        return ts_set_contains_strings(expr["left"])
    if kind == "UnicodeSetClass":
        return not expr["negate"] and ts_set_contains_strings(expr["expression"])
    if kind == "ClassStringDisjunction":
        counts = expr.get("characterCounts") or [len(s) for s in expr["alternatives"]]
        return any(n != 1 for n in (counts[:-1] if expr.get("missingClose") else counts))
    return expr.get("strings", False)


class SetGrammar:
    tokens = ("OPEN", "NEGATED", "CLOSE", "CHAR", "SET", "DASH", "TRAILING_DASH", "AND", "SUB",
              "STR_OPEN", "STR_BAR", "STR_CLOSE", "SINGLE_AMP")
    start = "set_class"
    # Shift the first doubled operator and prefer a present operand over an empty right side.
    precedence = (("nonassoc", "UNION_ITEM", "EMPTY_RIGHT"), ("nonassoc", "AND", "SUB"),
                  ("nonassoc", "CHAR", "SET", "OPEN", "NEGATED", "STR_OPEN", "SINGLE_AMP"))

    def preceding_union_term(self):
        # PLY asks for lookahead before reducing the most recently shifted
        # operand. A nested set or string disjunction still occupies three symbols.
        stack = self.parser.symstack
        last = stack[-1].type
        if last in {"CLOSE", "STR_CLOSE"}:
            width = 3
        elif last in {"CHAR", "SINGLE_AMP", "SET"}:
            width = 1
        else:
            return None
        if len(stack) > width + 1 and stack[-width - 1].type == "DASH" and stack[-width - 2].type == "operand":
            return "range"
        if len(stack) > width and stack[-width - 1].type == "union":
            return "union"
        return None

    def token(self):
        if self.finished:
            return None
        if self.index >= len(self.rules.pattern):
            if not self.rules.typescript or not self.depth:
                return None
            token = lex.LexToken()
            token.lexpos = token.endlexpos = self.index
            token.lineno, token.value, token.missing = 1, "", True
            if self.in_string:
                token.type = "STR_CLOSE"
                self.in_string = False
            else:
                token.type = "CLOSE"
                self.depth -= 1
                self.finished = self.depth == 0
            return token
        source, start = self.rules.pattern, self.index
        char = source[start]
        token = lex.LexToken()
        token.lexpos, token.lineno, token.value = start, 1, char
        token.issue_start = len(self.rules.diagnostics)
        self.index += 1
        if not self.in_string and char == "[":
            self.depth += 1
            negated = source.startswith("^", self.index)
            self.index += int(negated)
            token.type = "NEGATED" if negated else "OPEN"
        elif not self.in_string and char == "]":
            self.depth -= 1
            self.finished = self.depth == 0
            token.type = "CLOSE"
        elif not self.in_string and source.startswith(r"\q{", start):
            self.in_string = True
            self.index = start + 3
            token.type = "STR_OPEN"
        elif self.in_string and char in "|}":
            token.type = "STR_BAR" if char == "|" else "STR_CLOSE"
            self.in_string = char != "}"
        elif char == "\\":
            following = source[self.index:self.index + 1]
            if not self.in_string and following == "q":
                self.rules.pattern_diagnostic(1521, start, start + 2, "expected string alternatives in braces after \\q")
                token.value = {"type": "Character", "value": following}
                self.index += 1
            elif self.in_string and following and following not in _STRING_ESCAPES:
                # The invalid escape consumes one UTF-16 unit. If the source
                # is astral the scanner counts its second unit as another atom.
                token.character_count = 2 if ord(following) > 0xffff else 1
                self.rules.pattern_diagnostic(1535, start, start + 2, "invalid character escape in string alternative")
                token.value = {"type": "Character", "value": following}
                self.index += 1
            elif following in _RESERVED:
                token.value = {"type": "Character", "value": following}
                self.index += 1
            else:
                token.value, self.index = self.rules.escape(start, in_class=True)
            token.type = "CHAR" if token.value["type"] in {"Character", "InvalidEscape"} else "SET"
        elif not self.in_string and char in "&-":
            self.set_punctuation(token, char)
        else:
            if self.rules.typescript and char in "$^" and source.startswith(char + char, start):
                self.rules.compatibility.append({"offset": self.rules.offset + start,
                                                 "message": "reserved double punctuator in ECMAScript UnicodeSets"})
            elif char in _DOUBLE and source.startswith(char + char, start):
                self.index += 1
                if self.in_string:
                    self.rules.pattern_diagnostic(1522, start, self.index, "reserved double punctuator in string alternative")
                else:
                    token.set_error = (1522, "reserved double punctuator in set operand")
            elif char in _SYNTAX:
                self.rules.pattern_diagnostic(1508, start, self.index, "unescaped syntax character in UnicodeSets class")
            kind = "InvalidSetCharacter" if hasattr(token, "set_error") else "Character"
            token.type, token.value = "CHAR", {"type": kind, "value": source[start:self.index]}
        token.endlexpos = self.index
        self.prev_type = token.type
        return token

    def set_punctuation(self, token, char):
        source = self.rules.pattern
        doubled = source.startswith(char, self.index)
        typescript = self.rules.typescript
        preceding = self.preceding_union_term() if typescript else None
        needs_operand = self.prev_type in {"AND", "SUB", "DASH"} or (
            self.prev_type == "SINGLE_AMP" and self.parser.symstack[-2].type == "operation")
        if typescript and char == "-" and (needs_operand or (
                not doubled and (preceding == "range" or self.prev_type in {"OPEN", "NEGATED"}))):
            token.type, token.value = "CHAR", {"type": "Character", "value": "-"}
            token.set_error = (1508, "unescaped dash in set operand")
        elif doubled:
            operator = char * 2
            self.index += 1
            if typescript and needs_operand:
                token.type, token.value = "CHAR", {"type": "InvalidSetCharacter", "value": operator}
                token.set_error = (1522, "reserved double punctuator in set operand")
                return
            if preceding:
                token.type, token.value = "CHAR", {"type": "InvalidSetOperator", "operator": operator}
                token.mixed_operator = True
            else:
                token.type, token.value = ("AND" if char == "&" else "SUB"), operator
            if char == "&" and preceding != "range" and source.startswith("&", self.index):
                token.extra_ampersand = True
                if preceding:
                    token.value["extraAmpersand"] = True
                self.index += 1
        elif char == "-":
            token.type = "TRAILING_DASH" if source.startswith("]", self.index) else "DASH"
        else:
            token.type = "SINGLE_AMP" if typescript else "CHAR"
            token.value = {"type": "Character", "value": "&"}

    def p_class(self, p):
        """set_class : OPEN contents CLOSE
                     | NEGATED contents CLOSE"""
        p.set_lexpos(0, p.lexpos(1))
        p.slice[0].issue_start = p.slice[1].issue_start
        p.slice[0].endlexpos = p.slice[3].endlexpos
        expr, strings = p[2]
        negate = p.slice[1].type == "NEGATED"
        if negate:
            checked = expr
            if expr["type"] == "SetUnion":
                elements = expr["elements"]
                checked = elements[0] if elements and elements[0]["type"] != "CharacterRange" else None
            if self.rules.typescript and checked and ts_set_contains_strings(checked):
                opening = p.slice[1]
                start = opening.endlexpos
                intersection = expr.get("expectedOperator", "&&" if expr["type"] == "SetIntersection" else "") == "&&"
                end = p.lexpos(3) if intersection else opening.first_operand_end
                diagnostic = {"code": 1518, "component": "pattern", "offset": self.rules.offset + start,
                              "length": end - start, "message": "negated set may contain strings"}
                if intersection:
                    self.rules.diagnostics.append(diagnostic)
                else:
                    self.rules.diagnostics.insert(opening.after_first_operand, diagnostic)
            elif strings:
                if not self.rules.typescript:
                    self.rules.fail(p.lexpos(1), "negated set may contain strings")
                self.rules.compatibility.append({"offset": self.rules.offset + p.lexpos(1),
                                                 "message": "negated set may contain strings in ECMAScript"})
            strings = False
        node = {"type": "UnicodeSetClass", "negate": negate, "expression": expr}
        if getattr(p.slice[3], "missing", False):
            node["missingClose"] = True
            self.rules.pattern_diagnostic(1005, p.lexpos(3), p.lexpos(3), "expected ]")
        p[0] = node, strings

    def p_contents(self, p):
        """contents :
                    | union
                    | operation"""
        p[0] = ({"type": "SetUnion", "elements": []}, False) if len(p) == 1 else p[1]

    def p_union(self, p):
        """union : item
                 | union item"""
        if len(p) == 2:
            node, strings = p[1]
            p[0] = ({"type": "SetUnion", "elements": [node]}, strings)
        else:
            union, prev_strings = p[1]
            node, strings = p[2]
            union["elements"].append(node)
            p[0] = union, prev_strings or strings

    def p_operation_head(self, p):
        """operation_head : operand AND
                          | operand SUB
                          | operation AND
                          | operation SUB
                          | operation DASH
                          | operation TRAILING_DASH
                          | operation SINGLE_AMP
                          | AND
                          | SUB"""
        op_index = len(p) - 1
        operator = "&" if p.slice[op_index].type == "SINGLE_AMP" else p[op_index]
        pos = p.lexpos(op_index)
        if op_index == 1:
            self.rules.pattern_diagnostic(1520, pos, pos, "expected a class set operand")
            left, strings = {"type": "MissingSetOperand"}, False
        else:
            left, strings = p[1]
        expected = p.slice[1].operator if p.slice[1].type == "operation" else operator
        if operator == "&":
            self.rules.pattern_diagnostic(1508, pos, pos + 1, "unexpected ampersand")
        elif operator != expected:
            self.rules.pattern_diagnostic(1519, pos, pos + len(operator), "mixed operators in UnicodeSets class")
        extra = getattr(p.slice[op_index], "extra_ampersand", False)
        if extra:
            self.rules.pattern_diagnostic(1508, pos + 2, pos + 3, "unexpected third ampersand")
        p[0] = left, strings, operator, expected, extra
        p.slice[0].endlexpos = p.slice[op_index].endlexpos

    def p_set_operation(self, p):
        """operation : operation_head operand
                     | operation_head %prec EMPTY_RIGHT"""
        left, left_strings, operator, expected, extra = p[1]
        if len(p) == 2:
            pos = p.slice[1].endlexpos
            self.rules.pattern_diagnostic(1520, pos, pos, "expected a class set operand")
            # The scanner exits before updating the intersection's string flag.
            right, right_strings = {"type": "MissingSetOperand"}, left_strings
        else:
            right, right_strings = p[2]
        mode = operator if len(operator) == 2 else expected
        node = {"type": "SetIntersection" if mode == "&&" else "SetSubtraction", "left": left, "right": right}
        if extra:
            node["extraAmpersand"] = True
        if operator != expected:
            node["expectedOperator"] = expected
            if len(operator) == 1:
                node["operator"] = operator
        p[0] = node, left_strings and (expected == "--" or right_strings)
        p.slice[0].operator = expected

    def p_missing_set_operator(self, p):
        "operation : operation non_amp_operand"
        left, left_strings = p[1]
        right, right_strings = p[2]
        expected = p.slice[1].operator
        pos = p.lexpos(2)
        self.rules.pattern_diagnostic(1005, pos, pos, f"expected {expected} before class set operand")
        # The right operand may already have emitted diagnostics while reducing.
        issues = self.rules.diagnostics
        missing = issues.pop()
        before_right = next((i for i in range(p.slice[2].issue_start, len(issues))
                             if issues[i]["offset"] >= missing["offset"]), len(issues))
        issues.insert(before_right, missing)
        p[0] = ({"type": "SetIntersection" if expected == "&&" else "SetSubtraction",
                 "left": left, "right": right, "missingOperator": True}, left_strings and (expected == "--" or right_strings))
        p.slice[0].operator = expected

    def p_item(self, p):
        """item : operand %prec UNION_ITEM
                | operand DASH operand
                | operand TRAILING_DASH"""
        if len(p) == 2:
            p[0] = p[1]
            return
        left, _ = p[1]
        if len(p) == 3:
            if not self.rules.typescript:
                self.rules.fail(p.lexpos(2), "missing UnicodeSets range endpoint")
            self.rules.compatibility.append({"offset": self.rules.offset + p.lexpos(2),
                                             "message": "missing UnicodeSets range endpoint in ECMAScript"})
            p[0] = {"type": "CharacterRange", "min": left, "max": None}, False
            return
        right, right_strings = p[3]
        if left["type"] not in {"Character", "InvalidEscape", "InvalidSetCharacter", "InvalidSetOperator"}:
            self.rules.pattern_diagnostic(1516, p.lexpos(1), p.slice[1].endlexpos, "invalid character class range endpoint")
        if right["type"] not in {"Character", "InvalidEscape", "InvalidSetCharacter", "InvalidSetOperator"}:
            if self.rules.typescript and ts_set_contains_strings(right):
                opening = next(sym.type for sym in reversed(p.stack) if sym.type in {"OPEN", "NEGATED"})
                if opening == "NEGATED":
                    self.rules.pattern_diagnostic(1518, p.lexpos(3), p.slice[3].endlexpos, "negated set may contain strings")
            self.rules.pattern_diagnostic(1516, p.lexpos(3), p.slice[3].endlexpos, "invalid character class range endpoint")
        elif left["type"] == right["type"] == "Character" and ord(left["value"]) > ord(right["value"]):
            self.rules.pattern_diagnostic(1517, p.lexpos(1), p.slice[3].endlexpos, "character range out of order")
        p[0] = {"type": "CharacterRange", "min": left, "max": right}, False

    def p_operand(self, p):
        """operand : non_amp_operand
                   | SINGLE_AMP"""
        p.set_lexpos(0, p.lexpos(1))
        p.slice[0].issue_start = p.slice[1].issue_start
        p.slice[0].endlexpos = p.slice[1].endlexpos
        if p.slice[1].type == "SINGLE_AMP":
            if p.stack[-1].type == "union":
                previous = p.stack[-1].value[0]["elements"]
                if previous[-1]["type"] != "CharacterRange":
                    pos = p.lexpos(1)
                    if len(previous) == 1:
                        self.rules.pattern_diagnostic(1508, pos, pos + 1, "unexpected ampersand after first operand")
                    self.rules.pattern_diagnostic(1508, pos, pos + 1, "unexpected ampersand")
            p[0] = p[1], False
        else:
            p[0] = p[1]

    def p_non_amp_operand(self, p):
        """non_amp_operand : CHAR
                           | SET
                           | set_class
                           | disjunction"""
        p.set_lexpos(0, p.lexpos(1))
        p.slice[0].issue_start = p.slice[1].issue_start
        p.slice[0].endlexpos = p.slice[1].endlexpos
        if getattr(p.slice[1], "mixed_operator", False):
            start = p.lexpos(1)
            self.rules.pattern_diagnostic(1519, start, start + 2, "mixed operators in UnicodeSets class")
            if p[1].get("extraAmpersand"):
                self.rules.pattern_diagnostic(1508, start + 2, start + 3, "unexpected third ampersand")
        if hasattr(p.slice[1], "set_error"):
            code, message = p.slice[1].set_error
            self.rules.pattern_diagnostic(code, p.lexpos(1), p.slice[1].endlexpos, message)
        if p.stack[-1].type == "NEGATED":
            p.stack[-1].first_operand_end = p.slice[0].endlexpos
            # A PLY lookahead token may already have reported a lexical error
            # from the next operand. The complement diagnostic precedes it.
            issues = self.rules.diagnostics
            end = self.rules.offset + p.slice[0].endlexpos
            p.stack[-1].after_first_operand = next(
                (i for i in range(p.stack[-1].issue_start, len(issues)) if issues[i]["offset"] > end or
                 (issues[i]["offset"] == end and issues[i].get("length", 0) > 0)), len(issues))

        if p.slice[1].type in {"CHAR", "SET"}:
            p[0] = p[1], p[1].get("strings", False)
        else:
            p[0] = p[1]

    def p_disjunction(self, p):
        "disjunction : STR_OPEN strings STR_CLOSE"
        p.set_lexpos(0, p.lexpos(1))
        p.slice[0].issue_start = p.slice[1].issue_start
        p.slice[0].endlexpos = p.slice[3].endlexpos
        values = ["".join(value for value, _ in chars) for chars in p[2]]
        counts = [sum(count for _, count in chars) for chars in p[2]]
        node = {"type": "ClassStringDisjunction", "alternatives": values}
        if any(count != len(value) for count, value in zip(counts, values)):
            node["characterCounts"] = counts
        if getattr(p.slice[3], "missing", False):
            node["missingClose"] = True
            self.rules.pattern_diagnostic(1005, p.lexpos(3), p.lexpos(3), "expected }")
            counts = counts[:-1]
        p[0] = node, any(count != 1 for count in counts)

    def p_strings(self, p):
        """strings : chars
                   | strings STR_BAR chars"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_chars(self, p):
        """chars :
                 | chars CHAR"""
        if len(p) == 1:
            p[0] = []
        else:
            p[1].append((p[2]["value"], getattr(p.slice[2], "character_count", 1)))
            p[0] = p[1]

    def p_error(self, token):
        self.rules.fail(token.lexpos if token else self.index, "invalid UnicodeSets class")


_local = threading.local()
_lock = threading.Lock()


def read_set(rules, index):
    if not hasattr(_local, "driver"):
        with _lock:
            grammar = SetGrammar()
            parser = yacc.yacc(module=grammar, write_tables=False, debug=False)
        _local.driver = grammar, parser
    grammar, parser = _local.driver
    grammar.rules, grammar.index, grammar.parser = rules, index, parser
    grammar.depth, grammar.in_string, grammar.finished, grammar.prev_type = 0, False, False, None
    ast, _ = parser.parse(lexer=grammar)
    return ast, grammar.index
