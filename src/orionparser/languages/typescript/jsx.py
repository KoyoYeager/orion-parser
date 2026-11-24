"""JSX text, tag and expression lexical modes for TSX source files."""
from copy import copy
import re

from ply import lex

from orionparser.languages.javascript.identifiers import identifier_char, scan_identifier
from orionparser.languages.javascript.pipeline import accepts_lookahead, inserted_token
from orionparser.languages.javascript.strings import read_string

_LINE_BREAKS = re.compile(r"\r\n|[\r\n\u2028\u2029]")
_TAG_SPACE = re.compile(r"(?:[ \t\v\f\r\n\u0085\u00a0\u1680\u2000-\u200b\u2028\u2029\u202f\u205f\u3000\ufeff]+|/\*[\s\S]*?\*/|//[^\n\r\u2028\u2029]*)+")
CONFLICT_MARKER = re.compile(r"(?<![^\r\n\u2028\u2029])(?:<{7}(?=[ ])|>{7}(?=[ ])|\|{7}(?=[ ])|={7}(?=[\s\S]))")
_TEXT = re.compile(r"[^<>{}]+")


class JsxRules:
    jsx_tokens = ("JSX_LT", "JSX_CLOSE_LT", "JSX_GT", "JSX_SLASH_GT", "JSX_NAME", "JSX_TEXT",
                  "JSX_STRING", "JSX_EXPR_OPEN", "JSX_EXPR_END", "JSX_DOT", "JSX_COLON", "JSX_EQUALS", "JSX_AFTER_LT", "JSX_ADJACENT", "JSX_ADJACENT_END",
                  "JSX_EOF")

    def start_jsx(self, parser, token, upcoming):
        if token.type != "RELATION" or token.value != "<" or not accepts_lookahead(parser, "JSX_LT"):
            return
        if accepts_lookahead(parser, "REGEXP", "POWER"):
            # In update-expression position the compiler looks ahead for
            # IdentifierName or '>'. A prefix unary operand commits directly.
            start = token.lexpos + 1
            trivia = _TAG_SPACE.match(self.source, start)
            if trivia:
                start = trivia.end()
            char = self.source[start:start + 1]
            if not (char and (char == ">" or self.identifier_char(char, first=True)
                              or (char == "\\" and self.identifier_escape_digits_end(start, True) is not None))):
                error = self.token_error(token, "expression expected", 1109)
                if self.script_pass is None:
                    raise error
                # Let yacc read '<' as a binary operator after the missing
                # operand. A later slash must then use the JS lexical goal.
                self.script_pass.record(error)
                upcoming.appendleft(copy(token))
                token.type, token.value, token.end_pos = "IDENTIFIER", "", token.lexpos
                token.escaped = False
                token.missing_identifier = True
                return
        token.type = "JSX_LT"
        self.jsx_elements.append(self.jsx_mode)
        self.jsx_mode = "tag"

    def raw_tokens(self):
        while True:
            if self.jsx_mode in {"text", "tag", "close"}:
                token = self.scan_jsx()
            else:
                token = self.lexer.token()
                if (token and token.type == "RELATION" and token.value == "<"
                        and self.source.startswith("/", token.lexpos + 1)
                        and not self.source.startswith("/*", token.lexpos + 1)):
                    token = self.jsx_token("JSX_CLOSE_LT", token.lexpos, token.lexpos + 2)
                    token.in_js_expression = True
                if token and self.jsx_exprs:
                    if token.type == "LBRACE":
                        self.jsx_exprs[-1][1] += 1
                    elif token.type == "RBRACE":
                        if self.jsx_exprs[-1][1]:
                            self.jsx_exprs[-1][1] -= 1
                        else:
                            token.type = "JSX_EXPR_END"
                            self.jsx_mode, _ = self.jsx_exprs.pop()
            if not token:
                if self.jsx_mode in {"text", "close", "tag"}:
                    eof = self.jsx_token("JSX_EOF", len(self.source), len(self.source))
                    eof.mode = self.jsx_mode
                    yield eof
                return
            self.line_has_token = True
            yield token

    def recover_jsx_name_punctuation(self, parser, token, previous, upcoming):
        if previous.type == "JSX_EQUALS":
            raise self.token_error(token, "JSX attribute value expected", 1145)
        expects_name = accepts_lookahead(parser, "JSX_NAME")
        if previous.type == "JSX_CLOSE_LT" and not expects_name:
            raise self.token_error(token, "expected JSX fragment closing tag", 17015)
        closing = token.jsx_name_mode == "close" and not expects_name
        if (token.type == "JSX_DOT" and previous.type == "JSX_NAME"
                and parser.symstack[-2].type == "JSX_COLON"):
            reason = "member access after namespaced JSX tag"
        else:
            context = "after closing tag name" if closing else "where a JSX identifier was expected"
            reason = f"{token.value!r} {context}"
        error = self.token_error(token, reason, 1005 if closing else 1003)
        if self.script_pass is None:
            raise error
        self.script_pass.record(error)
        if expects_name and token.type in {"JSX_DOT", "JSX_COLON", "ELLIPSIS", "SEMICOLON", "RBRACE"}:
            if previous.type in {"JSX_DOT", "JSX_COLON"}:
                # Complete the missing component before examining the punctuation again.
                upcoming.appendleft(copy(token))
            token.type, token.value, token.end_pos = "JSX_NAME", "", token.lexpos
        elif ((closing or token.type == "NUMBER") and self.jsx_mode == token.jsx_name_mode
              and self.lexer.lexpos == token.lexpos + len(token.value) and self.jsx_elements):
            # The compiler finishes this tag before the unexpected token and
            # reads it again in the enclosing JS expression or JSX children.
            boundary = "JSX_GT" if closing else "JSX_SLASH_GT"
            if not accepts_lookahead(parser, boundary):
                raise error
            self.jsx_mode = self.jsx_elements.pop()
            resume = token.lexpos
            upcoming.clear()
            if self.jsx_mode == "js" and accepts_lookahead(parser, boundary, "SEMICOLON"):
                # A completed JSX statement can be followed by another
                # expression. A stray dot or colon does not start that statement.
                upcoming.appendleft(inserted_token(previous, "SEMICOLON", ";"))
                if token.type in {"JSX_DOT", "JSX_COLON"}:
                    resume += len(token.value)
            self.lexer.lexpos, self.lexer.lineno = resume, token.lineno
            token.type, token.value, token.end_pos = boundary, "", token.lexpos
            token.pending_jsx_tokens = upcoming
        else:
            raise error
        del token.jsx_name_mode

    def closing_tag_in_expression(self, parser, token, previous, upcoming):
        if accepts_lookahead(parser, "EMPTY_SEMI"):
            kind, value = "EMPTY_SEMI", ";"
            error = self.token_error(token, "declaration or statement expected", 1128)
        elif previous and token.lineno > previous.lineno and accepts_lookahead(parser, "SEMICOLON"):
            kind, value = "SEMICOLON", ";"
            error = self.token_error(token, "declaration or statement expected", 1128)
        elif accepts_lookahead(parser, "REGEXP"):
            if "argument" in parser.goto.get(parser.statestack[-1], {}) and accepts_lookahead(parser, "RPAREN"):
                kind, value = "RPAREN", ")"
                error = self.token_error(token, "argument expression expected", 1135)
            else:
                kind, value = "IDENTIFIER", ""
                error = self.token_error(token, "expression expected", 1109)
        elif (previous and previous.type == "IDENTIFIER" and parser.symstack[-1] is previous
              and parser.symstack[-2].type in {"body", "module_items"}):
            end = getattr(previous, "end_pos", previous.lexpos + len(previous.value))
            error = self.missing_semicolon_after_name(previous.value, previous.lexpos, end, token)
            kind, value = "SEMICOLON", ";"
        elif not self.jsx_exprs and accepts_lookahead(parser, "SEMICOLON"):
            error = self.token_error(token, "expected ';' before JSX closing delimiter", 1005)
            kind, value = "SEMICOLON", ";"
        else:
            error = self.token_error(token, "JSX closing delimiter before the expression ended", 1005)
            for kind, value in (("JSX_EXPR_END", "}"), ("RPAREN", ")"), ("RBRACKET", "]"), ("RBRACE", "}"), ("COLON", ":")):
                if accepts_lookahead(parser, kind):
                    break
            else:
                raise error
        if self.script_pass is None:
            raise error
        if kind in {"SEMICOLON", "EMPTY_SEMI"}:
            self.script_pass.record(error)
            token.in_js_expression = False
            token.type, token.value = kind, value
            return
        if not self.jsx_exprs or self.jsx_exprs[-1][0] != "text":
            raise error
        self.script_pass.record(error)
        closing = copy(token)
        if kind == "JSX_EXPR_END":
            # Resume tag scanning at the original delimiter, after the
            # provisional tree has closed any nested calls and expressions.
            closing.in_js_expression = False
            self.lexer.lexpos, self.lexer.lineno = token.lexpos + 2, token.lineno
            self.jsx_exprs.pop()
            self.jsx_mode = "close"
            upcoming.clear()
        elif kind == "RBRACE" and self.jsx_exprs[-1][1]:
            self.jsx_exprs[-1][1] -= 1
        if kind in {"JSX_EXPR_END", "RBRACE"} and self.template_braces and self.template_braces[-1]:
            self.template_braces[-1] -= 1
        upcoming.appendleft(closing)
        token.type, token.value, token.end_pos = kind, value, token.lexpos
        token.in_js_expression = False
        token.escaped = False

    def check_jsx_eof(self, parser, token, previous):
        if token.mode == "text":
            return  # yacc reduces the innermost unclosed element or fragment
        end = previous.lexpos + len(previous.value)
        if token.mode == "close":
            if accepts_lookahead(parser, "JSX_NAME"):
                raise self.error(end, "identifier expected in JSX closing tag", code=1003, length=0)
            if previous.type == "JSX_CLOSE_LT":
                raise self.token_error(token, "expected JSX fragment closing tag", 17015)
            raise self.token_error(token, "expected '>' in JSX closing tag", 1005)
        if previous.type == "JSX_LT" and self.jsx_elements[-1] == "js" and not previous.adjacent_element:
            raise self.token_error(previous, "expression expected", 1109)
        if previous.type in {"JSX_LT", "JSX_DOT", "JSX_COLON"}:
            raise self.error(end, "identifier expected in JSX opening tag", code=1003, length=0)
        if previous.type == "JSX_EQUALS":
            raise self.token_error(token, "expected '{' or JSX element", 1145)
        error = self.token_error(token, "expected '/' in JSX opening tag", 1005)
        if self.script_pass is None or not accepts_lookahead(parser, "JSX_SLASH_GT"):
            raise error
        self.script_pass.record(error)
        token.type = "JSX_SLASH_GT"
        self.jsx_mode = self.jsx_elements.pop()

    def jsx_token(self, kind, start, end):
        token = lex.LexToken()
        token.type, token.value = kind, self.source[start:end]
        token.lexpos, token.lineno = start, self.lexer.lineno
        self.lexer.lexpos = end
        self.lexer.lineno += len(_LINE_BREAKS.findall(token.value))
        token.end_line = self.lexer.lineno
        return token

    def scan_jsx(self):
        start = self.lexer.lexpos
        source = self.source
        if self.jsx_mode != "text":
            space = _TAG_SPACE.match(source, start)
            if space:
                self.lexer.lineno += len(_LINE_BREAKS.findall(space[0]))
                self.lexer.lexpos = start = space.end()
        if start >= len(source):
            return None
        char = source[start]
        if self.jsx_mode != "text" and char in "<>=|" and CONFLICT_MARKER.match(source, start):
            raise self.error(start, "merge conflict marker", code=1185, length=7)
        if char == "<":
            if self.jsx_mode == "text" and source.startswith("</", start):
                self.jsx_mode = "close"
                return self.jsx_token("JSX_CLOSE_LT", start, start + 2)
            self.jsx_elements.append(self.jsx_mode)
            self.jsx_mode = "tag"
            return self.jsx_token("JSX_LT", start, start + 1)
        if char == "{" and self.jsx_mode != "close":
            if self.template_braces:
                self.template_braces[-1] += 1
            self.jsx_exprs.append([self.jsx_mode, 0])
            self.jsx_mode = "js"
            return self.jsx_token("JSX_EXPR_OPEN", start, start + 1)
        if self.jsx_mode == "text":
            match = _TEXT.match(source, start)
            if not match:
                error = self.error(start, "unescaped " + char + " in JSX text",
                                   code=1382 if char == ">" else 1381, length=1)
                if self.script_pass is None:
                    raise error
                self.script_pass.record(error)
                return self.jsx_token("JSX_TEXT", start, start + 1)
            if source.startswith("<", match.end()) and CONFLICT_MARKER.match(source, match.end()):
                raise self.error(match.end(), "merge conflict marker", code=1185, length=7)
            return self.jsx_token("JSX_TEXT", start, match.end())
        if char == "/" and self.jsx_mode == "tag":
            trivia = _TAG_SPACE.match(source, start + 1)
            closing = trivia.end() if trivia else start + 1
            if closing == len(source):
                raise self.error(closing, "expected '>' after JSX slash", code=1005, length=0)
            if source.startswith(">", closing):
                self.jsx_mode = self.jsx_elements.pop()
                return self.jsx_token("JSX_SLASH_GT", start, closing + 1)
        if char == ">":
            self.jsx_mode = self.jsx_elements.pop() if self.jsx_mode == "close" else "text"
            return self.jsx_token("JSX_GT", start, start + 1)
        if (char in "0123456789" or source.startswith(("...", "==", "=>"), start)
                or (char == "." and start + 1 < len(source) and source[start + 1] in "0123456789")):
            token = self.lexer.token()
            token.jsx_name_mode = self.jsx_mode
            return token
        if char in ".:=":
            token = self.jsx_token({".": "JSX_DOT", ":": "JSX_COLON", "=": "JSX_EQUALS"}[char], start, start + 1)
            token.jsx_name_mode = self.jsx_mode
            return token
        if char in "\"'":
            if space:
                # After trivia, TS scanJsxAttributeValue delegates to the ordinary string scanner.
                end, cooked = read_string(source, start, True, self.string_error)
                token = self.jsx_token("JSX_STRING", start, end)
                token.cooked = cooked
                return token
            end = source.find(char, start + 1)
            if end < 0:
                raise self.error(len(source), "unterminated JSX attribute", code=1002, length=0)
            return self.jsx_token("JSX_STRING", start, end + 1)
        if self.identifier_char(char, first=True) or char == "\\" or not char.isascii():
            token = self.jsx_token("JSX_NAME", start, start)
            end, name = self.read_identifier(token, start, jsx_name=True)
            if not name:
                token.jsx_escape_error = self.invalid_character_error(start, char)
                end = start + 1
                if self.script_pass is not None and identifier_char(char, first=True):
                    end, _ = scan_identifier(source, start, self.error, identifier_char, jsx_name=True,
                                             recover_escape=lambda offset, first: None)
                elif self.script_pass is not None and token.jsx_escape_error.code == 1127:
                    token.invalid_character = token.jsx_escape_error
            token.value = source[start:end]
            self.lexer.lexpos = token.end_pos = end
            return token
        # TS falls back to the ordinary scanner for other tag punctuation.
        # In particular +=, **= and similar operators each span a single token.
        token = self.lexer.token()
        if token is not None:
            token.jsx_name_mode = self.jsx_mode
        return token

    def p_jsx_primary(self, p):
        """exponential : jsx_update
                       | jsx_update POWER exponential
           unary_operand : jsx"""
        if len(p) == 4:
            self.p_binary(p)
        else:
            p[0] = p[1]

    def p_jsx_update(self, p):
        """jsx_update : jsx
                      | jsx_adjacent
           primary : jsx_adjacent JSX_ADJACENT_END"""
        if p.slice[1].type == "jsx_adjacent" and len(p) == 2:
            self.report_adjacent_jsx(p.slice[1])
        p[0] = p[1]

    def report_adjacent_jsx(self, node):
        error = self.error(node.jsx_start, "JSX expressions must have one parent element", code=2657,
                           length=node.jsx_end - node.jsx_start)
        if self.script_pass is None:
            raise error
        self.script_pass.record(error)

    def p_jsx_adjacent(self, p):
        """jsx_adjacent : jsx JSX_ADJACENT jsx
                        | jsx_adjacent JSX_ADJACENT jsx"""
        p.slice[0].jsx_start = p.slice[1].jsx_start
        p.slice[0].jsx_end = p.slice[3].jsx_end
        if self.source_lookahead is not None and self.source_lookahead.type == "JSX_ADJACENT_END":
            self.report_adjacent_jsx(p.slice[0])
        if p.slice[1].type == "jsx_adjacent":
            p[0] = p[1]
            p[0]["expressions"].append(p[3])
        else:
            p[0] = {"type": "SequenceExpression", "expressions": [p[1], p[3]]}

    def p_comparison_after_jsx(self, p):
        """relational : relational JSX_AFTER_LT shift
           relational_no_in : relational_no_in JSX_AFTER_LT shift"""
        self.p_binary(p)

    def p_jsx_identifier(self, p):
        "jsx_identifier : JSX_NAME"
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "JSXIdentifier", "name": p[1]}

    def p_jsx_attribute_name(self, p):
        """jsx_attribute_name : jsx_identifier
                              | jsx_identifier JSX_COLON jsx_identifier"""
        p.set_lexpos(0, p.lexpos(1))
        p.slice[0].name_end = p.lexpos(len(p)-1) + len(p[len(p)-1]["name"])
        p[0] = p[1] if len(p) == 2 else {"type": "JSXNamespacedName", "namespace": p[1], "name": p[3]}

    def p_jsx_tag(self, p):
        """jsx_tag : jsx_attribute_name
                   | jsx_member_name"""
        p.set_lexpos(0, p.lexpos(1))
        p.slice[0].name_end = p.slice[1].name_end
        p[0] = p[1]

    def p_jsx_member_name(self, p):
        """jsx_member_name : jsx_identifier JSX_DOT jsx_identifier
                           | jsx_member_name JSX_DOT jsx_identifier"""
        p.set_lexpos(0, p.lexpos(1))
        p.slice[0].name_end = p.lexpos(3) + len(p[3]["name"])
        p[0] = {"type": "JSXMemberExpression", "object": p[1], "property": p[3]}

    def p_jsx_opening(self, p):
        """jsx_opening : JSX_LT jsx_tag jsx_attributes JSX_GT
           jsx_typed_opening : JSX_LT jsx_tag jsx_type_arguments jsx_attributes JSX_GT"""
        p.set_lexpos(0, p.lexpos(2))
        p.slice[0].jsx_start = p.lexpos(1)
        p.slice[0].name_start = p.lexpos(1) + 1
        p.slice[0].name_end = p.slice[2].name_end
        p[0] = {"type": "JSXOpeningElement", "name": p[2], "attributes": p[len(p)-2], "selfClosing": False}
        if len(p) == 6:
            p[0]["typeArguments"] = p[3]

    def p_jsx_close_name(self, p):
        "jsx_close_name : JSX_CLOSE_LT jsx_tag"
        # This reduction runs with '>' as lookahead. The stack ends with
        # the current opening element and its children, including at EOF
        # immediately after the closing tag.
        opening = p.stack[-2]
        if p[2] != opening.value["name"]:
            parent = p.stack[-4] if len(p.stack) >= 4 and p.stack[-3].type == "jsx_children" else None
            if parent and parent.type in {"jsx_opening", "jsx_typed_opening"} and parent.value["name"] == p[2]:
                error = self.error(opening.name_start, "unclosed JSX element", code=17008,
                                   length=opening.name_end - opening.name_start)
                if self.script_pass is None:
                    raise error
                self.script_pass.record(error)
                # The scanner already left the child when it read the '>'
                # lookahead. The parent consumes the same closing tag next.
                self.source_lookahead.pending_jsx_tokens.clear()
                self.lexer.lexpos, self.lexer.lineno = p.lexpos(1), p.lineno(1)
                self.jsx_mode = "text"
                p[0] = {"type": "JSXClosingElement", "name": {"type": "JSXIdentifier", "name": ""}}
                return
            start = p.lexpos(1) + 2
            error = self.error(start, "mismatched JSX closing tag", code=17002, length=p.slice[2].name_end - start)
            if self.script_pass is None:
                raise error
            self.script_pass.record(error)
        p[0] = {"type": "JSXClosingElement", "name": p[2]}

    def set_jsx_span(self, p):
        if self.script_pass is not None:
            self.script_pass.has_jsx = True
        closing = p.slice[-1]
        p.set_lexpos(0, closing.lexpos)
        p.slice[0].jsx_start = getattr(p.slice[1], "jsx_start", p.lexpos(1))
        p.slice[0].jsx_end = closing.lexpos + len(closing.value)

    def p_jsx_element(self, p):
        """jsx : JSX_LT jsx_tag jsx_attributes JSX_SLASH_GT
               | jsx_opening jsx_children jsx_close_name JSX_GT"""
        self.set_jsx_span(p)
        if p.slice[1].type == "jsx_opening":
            p[0] = {"type": "JSXElement", "openingElement": p[1], "children": p[2], "closingElement": p[3]}
        else:
            p[0] = {"type": "JSXElement", "openingElement": {"type": "JSXOpeningElement", "name": p[2],
                    "attributes": p[3], "selfClosing": True}, "children": [], "closingElement": None}

    def p_jsx_type_arguments(self, p):
        """jsx_type_arguments : JSX_TYPE_LT JSX_TYPE_GT
                              | JSX_TYPE_LT ts_type_list JSX_TYPE_GT
                              | JSX_TYPE_LT ts_type_list COMMA JSX_TYPE_GT"""
        self.p_ts_arguments(p)

    def p_jsx_typed_element(self, p):
        """jsx : JSX_LT jsx_tag jsx_type_arguments jsx_attributes JSX_SLASH_GT
               | jsx_typed_opening jsx_children jsx_close_name JSX_GT"""
        self.set_jsx_span(p)
        if p.slice[1].type == "jsx_typed_opening":
            p[0] = {"type": "JSXElement", "openingElement": p[1], "children": p[2], "closingElement": p[3]}
        else:
            p[0] = {"type": "JSXElement", "openingElement": {"type": "JSXOpeningElement", "name": p[2],
                    "attributes": p[4], "typeArguments": p[3], "selfClosing": True},
                    "children": [], "closingElement": None}

    def p_jsx_unclosed(self, p):
        """jsx_unclosed : jsx_opening jsx_children
                        | jsx_typed_opening jsx_children
                        | JSX_LT JSX_GT jsx_children"""
        if len(p) == 4:
            start = p.slice[1].jsx_full_start
            raise self.error(start, "unclosed JSX fragment", code=17014, length=p.lexpos(2) + 1 - start)
        start = p.lexpos(1)
        raise self.error(start, "unclosed JSX element", code=17008, length=p.slice[1].name_end - start)

    def p_jsx_missing_close(self, p):
        "jsx : jsx_unclosed JSX_EOF"
        # jsx_unclosed raises with JSX_EOF as its lookahead.
        raise AssertionError("unclosed JSX element reduced without a diagnostic")

    def p_jsx_fragment(self, p):
        "jsx : JSX_LT JSX_GT jsx_children JSX_CLOSE_LT JSX_GT"
        self.set_jsx_span(p)
        p[0] = {"type": "JSXFragment", "openingFragment": {"type": "JSXOpeningFragment"},
                "closingFragment": {"type": "JSXClosingFragment"}, "children": p[3]}

    def p_jsx_attributes(self, p):
        """jsx_attributes :
                          | jsx_attributes jsx_attribute"""
        if len(p) == 1:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_jsx_attribute(self, p):
        """jsx_attribute : jsx_attribute_name
                         | jsx_attribute_name JSX_EQUALS jsx_value
                         | JSX_EXPR_OPEN ELLIPSIS expression JSX_EXPR_END"""
        if p.slice[1].type == "JSX_EXPR_OPEN":
            p[0] = {"type": "JSXSpreadAttribute", "argument": p[3]}
        else:
            p[0] = {"type": "JSXAttribute", "name": p[1], "value": p[3] if len(p) == 4 else None}

    def p_jsx_value(self, p):
        """jsx_value : JSX_STRING
                     | jsx_expression
                     | jsx"""
        if p.slice[1].type == "JSX_STRING":
            p[0] = {"type": "Literal", "raw": p[1], "value": getattr(p.slice[1], "cooked", p[1][1:-1])}
        else:
            p[0] = p[1]

    def p_jsx_expression(self, p):
        """jsx_expression : JSX_EXPR_OPEN expression JSX_EXPR_END
                          | JSX_EXPR_OPEN JSX_EXPR_END"""
        expr = p[2] if len(p) == 4 else {"type": "JSXEmptyExpression"}
        p[0] = {"type": "JSXExpressionContainer", "expression": expr}

    def p_jsx_children(self, p):
        """jsx_children :
                        | jsx_children jsx_child"""
        if len(p) == 1:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_jsx_child(self, p):
        """jsx_child : JSX_TEXT
                     | jsx_expression
                     | jsx
                     | JSX_EXPR_OPEN ELLIPSIS expression JSX_EXPR_END"""
        if p.slice[1].type == "JSX_TEXT":
            p[0] = {"type": "JSXText", "value": p[1], "raw": p[1]}
        elif len(p) == 5:
            p[0] = {"type": "JSXSpreadChild", "expression": p[3]}
        else:
            p[0] = p[1]
