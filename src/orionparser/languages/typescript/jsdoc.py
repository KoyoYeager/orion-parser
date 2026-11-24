"""JSDoc-style types accepted by the TypeScript source grammar."""
import re

from orionparser.languages.javascript.pipeline import accepts_lookahead
from orionparser.languages.javascript.strict import STRICT_IDENTIFIERS


_TYPE_LIST_OPENERS = {"DOC_OPEN", "TYPE_LT", "CALL_TYPE_LT", "TYPE_INDEX", "LBRACKET", "COMMA", "JSX_TYPE_LT"}


class JSDocTypeRules:
    jsdoc_tokens = ("DOC_FUNCTION_NAME", "DOC_OPEN", "DOC_NAMEPATH", "DOC_RETURN", "DOC_FUNCTION", "DOC_RECEIVER", "DOC_ALL",
                    "DOC_UNKNOWN", "DOC_NULLABLE", "DOC_NON_NULL", "DOC_POST_NULLABLE", "DOC_POST_NON_NULL")

    @staticmethod
    def in_jsdoc_parameter_type(parser):
        # parseJSDocType enables margin scanning after the parameter's first
        # token and disables it before consuming the optional equals sign.
        # An enclosing parameter can keep it enabled inside a nested signature.
        stack = [symbol.type for symbol in parser.symstack]
        for index, symbol in enumerate(stack):
            if symbol != "DOC_OPEN":
                continue
            suffix = stack[index + 1:]
            if suffix[:2] == ["doc_parameter_list", "COMMA"]:
                suffix = suffix[2:]
            if suffix[:2] == ["DOC_RECEIVER", "COLON"]:
                suffix = suffix[2:]
            if (suffix and suffix[0] not in {"DOC_RECEIVER", "doc_parameters", "doc_parameter_list"}
                    and suffix not in (["return_type", "ASSIGN"], ["ELLIPSIS", "return_type", "ASSIGN"])):
                return True
        return False

    @staticmethod
    def jsdoc_lookahead(token, raw_peek):
        def peek(distance=1):
            index = 0
            preceding = token
            for _ in range(distance):
                index += 1
                following = raw_peek(index)
                if (following and following.type == "MULTIPLY"
                        and following.lineno > getattr(preceding, "end_line", preceding.lineno)):
                    index += 1
                    following = raw_peek(index)
                if following is None:
                    return None
                preceding = following
            return preceding
        return peek

    @staticmethod
    def starts_type_after_question(peek):
        distance = 1
        token = peek()
        while token and token.type == "LPAREN":
            distance += 1
            token = peek(distance)
            if token and token.type == "RPAREN":
                return True
        if not token:
            return False
        if token.type == "MINUS":
            number = peek(distance + 1)
            return bool(number and number.type == "NUMBER")
        if token.type == "RESERVED":
            return token.value in STRICT_IDENTIFIERS or token.value == "await"
        return token.value == "<" or token.type in {
            "IDENTIFIER", "LET", "VOID", "NULL", "THIS", "TYPEOF", "LBRACE", "LBRACKET", "BIT_OR", "BIT_AND",
            "NEW", "STRING", "NUMBER", "TRUE", "FALSE", "MULTIPLY", "QUESTION", "NOT", "ELLIPSIS", "IMPORT",
            "TEMPLATE", "TEMPLATE_HEAD", "FUNCTION",
        }

    def classify_jsdoc_token(self, parser, token, previous, peek, upcoming, same_line):
        if token.type == "LPAREN" and accepts_lookahead(parser, "DOC_OPEN"):
            self.has_jsdoc_parameters = True
            token.type = "DOC_OPEN"
            return True
        if token.type == "IDENTIFIER" and token.value == "module" and accepts_lookahead(parser, "DOC_NAMEPATH"):
            token.type = "DOC_NAMEPATH"
            first = peek()
            if first and first.type not in {"COMMA", "RBRACE"}:
                # parseJSDocType consumes the first ordinary token, then JSDoc
                # token text through (but excluding) comma, close brace or EOF.
                end = getattr(first, "end_pos", first.lexpos + len(first.value))
                while end < len(self.source) and self.source[end] not in ",}":
                    if self.source[end] in " \t\f\v":
                        raise self.error(end, "whitespace inside JSDoc module namepath")
                    end += 1
                token.value = self.source[token.lexpos:end]
                token.end_pos = self.lexer.lexpos = end
                token.end_line = self.lexer.lineno = token.lineno + len(re.findall(r"\r\n|[\r\n\u2028\u2029]", token.value))
                upcoming.clear()
            return True
        if token.type == "COLON" and accepts_lookahead(parser, "DOC_RETURN"):
            token.type = "DOC_RETURN"
            return True
        if token.value == "function" and accepts_lookahead(parser, "DOC_FUNCTION") and peek() and peek().type == "LPAREN":
            if getattr(token, "escaped", False):
                raise self.token_error(token, "escape in function type keyword", 1260)
            token.type = "DOC_FUNCTION"
            return True
        if token.type in {"THIS", "NEW"} and accepts_lookahead(parser, "DOC_RECEIVER"):
            token.type = "DOC_RECEIVER"
            return True
        if token.value in {"*", "*=", "?", "??"}:
            prefix = "DOC_ALL" if token.value.startswith("*") else "DOC_NULLABLE"
            if accepts_lookahead(parser, prefix):
                if len(token.value) == 2:
                    # isStartOfType does not recognize the compound scanner token at the start of a list.
                    if previous and previous.type in _TYPE_LIST_OPENERS:
                        return True
                    self.lexer.lexpos = token.lexpos + 1
                    upcoming.clear()
                    token.value = token.value[0]
                token.type = prefix
                if prefix == "DOC_NULLABLE":
                    following = peek()
                    if following and (following.type in {"COMMA", "RBRACE", "RPAREN", "ASSIGN", "BIT_OR"}
                                      or following.value.startswith(">")):
                        token.type = "DOC_UNKNOWN"
                return True
        if token.type == "NOT" and accepts_lookahead(parser, "DOC_NON_NULL"):
            token.type = "DOC_NON_NULL"
            return True
        if token.type == "NOT" and same_line and accepts_lookahead(parser, "DOC_POST_NON_NULL"):
            token.type = "DOC_POST_NON_NULL"
            return True
        if token.type == "QUESTION" and same_line and accepts_lookahead(parser, "DOC_POST_NULLABLE"):
            following = peek()
            named_marker = following and following.type == "COLON" and (
                accepts_lookahead(parser, "TUPLE_OPTIONAL") or accepts_lookahead(parser, "OPTIONAL_PARAM"))
            if not named_marker and not self.starts_type_after_question(peek):
                token.type = "DOC_POST_NULLABLE"
                return True
        return False

    def p_jsdoc_function_name(self, p):
        "ts_atom : DOC_FUNCTION_NAME"
        p[0] = {"type": "TSTypeReference", "typeName": {"type": "Identifier", "name": p[1]}, "typeArguments": None}

    def p_jsdoc_function(self, p):
        """ts_atom : DOC_FUNCTION DOC_OPEN doc_parameters RPAREN
                   | DOC_FUNCTION DOC_OPEN doc_parameters RPAREN DOC_RETURN return_type"""
        p[0] = {"type": "JSDocFunctionType", "params": p[3], "returnType": p[6] if len(p) == 7 else None}

    def p_doc_parameters(self, p):
        """doc_parameters :
                          | doc_parameter_list
                          | doc_parameter_list COMMA"""
        p[0] = p[1] if len(p) > 1 else []
        if len(p) == 3:
            self.register_parameter_list(p[0], p.lexpos(2))

    def p_doc_parameter_list(self, p):
        """doc_parameter_list : doc_parameter
                              | doc_parameter_list COMMA doc_parameter"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_doc_parameter(self, p):
        """doc_parameter : doc_parameter_type
                         | DOC_RECEIVER COLON doc_parameter_type"""
        name = {"type": "Identifier", "name": p[1]} if len(p) == 4 else None
        p[0] = {"type": "JSDocParameter", "name": name, "typeAnnotation": p[len(p)-1]}

    def p_doc_namepath(self, p):
        "doc_parameter_type : DOC_NAMEPATH"
        p[0] = {"type": "JSDocNamepathType", "text": p[1]}

    def p_doc_parameter_type(self, p):
        """doc_parameter_type : return_type
                              | return_type ASSIGN
                              | ELLIPSIS return_type
                              | ELLIPSIS return_type ASSIGN"""
        rest = p.slice[1].type == "ELLIPSIS"
        t = p[2 if rest else 1]
        if rest:
            t = {"type": "JSDocVariadicType", "typeAnnotation": t}
        p[0] = {"type": "JSDocOptionalType", "typeAnnotation": t} if p.slice[len(p)-1].type == "ASSIGN" else t

    def p_jsdoc_type(self, p):
        """ts_atom : DOC_ALL
                   | DOC_UNKNOWN
                   | DOC_NULLABLE ts_type
                   | DOC_NON_NULL ts_atom
           ts_postfix : ts_postfix DOC_POST_NULLABLE
                      | ts_postfix DOC_POST_NON_NULL"""
        if len(p) == 2:
            p[0] = {"type": "JSDocAllType" if p.slice[1].type == "DOC_ALL" else "JSDocUnknownType"}
        else:
            postfix = p.slice[0].type == "ts_postfix"
            marker = p[2] if postfix else p[1]
            p[0] = {"type": "JSDocNullableType" if marker == "?" else "JSDocNonNullableType",
                    "postfix": postfix, "typeAnnotation": p[1] if postfix else p[2]}
