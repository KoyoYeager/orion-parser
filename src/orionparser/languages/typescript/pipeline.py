"""TypeScript source-file grammar built on the ECMAScript PLY productions."""
from bisect import bisect_right
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
import re
import unicodedata

from ply.lex import TOKEN

from orionparser.languages.javascript.pipeline import (
    Grammar, JavaScriptPipeline, SourceSyntaxError, accepts_lookahead, inserted_token, parser_for_thread, statement_tokens,
)

from orionparser.languages.javascript.identifiers import IDENTIFIER_ESCAPE, scan_identifier
from orionparser.languages.javascript.strict import STRICT_IDENTIFIERS

from .declarations import DeclarationRules
from .decorators import DecoratorRules
from . import es5_identifiers
from .imports import ImportAttributeRules
from .jsx import CONFLICT_MARKER, JsxRules
from .jsdoc import JSDocTypeRules
from .options import SyntaxOptions
from .references import references
from .spelling import keyword_suggestion
from .strict import check_strict_diagnostics
from .types import KEYWORD_TYPES, TypeRules


_HEX_DIGITS = re.compile(r"[0-9a-fA-F]*")

# Used only to find the end of a malformed literal in the preliminary script.
_NUMERIC_FRAGMENTS = {
    "x": re.compile(r"0[xX][0-9a-fA-F_]*n?"),
    "o": re.compile(r"0[oO][0-7_]*n?"),
    "b": re.compile(r"0[bB][01_]*n?"),
    "": re.compile(r"(?:[0-9][0-9_]*(?:\.[0-9_]*)?|\.[0-9][0-9_]*)(?:[eE][+-]?[0-9_]*)?n?"),
}


@dataclass
class ScriptPass:
    statements: list = field(default_factory=list)
    first_error: SourceSyntaxError | None = None
    incomplete_module_indicator: bool = False
    has_jsx: bool = False

    def record(self, error):
        if self.first_error is None:
            self.first_error = error


def es5_identifier_char(char, first):
    bounds = es5_identifiers.START if first else es5_identifiers.PART
    return bisect_right(bounds, ord(char)) % 2 == 1


def retained_context_offsets(statement, context_offsets):
    """Locate source offsets whose enclosing statement retains its script context."""
    if statement["type"] == "ExportNamedDeclaration":
        statement = statement.get("declaration")
        if not statement or statement["type"] not in {"VariableDeclaration", "TSModuleDeclaration", "TSTypeAliasDeclaration", "TSInterfaceDeclaration"}:
            return ()
    if statement["type"] == "ExportDefaultDeclaration":
        statement = statement["declaration"]
        if statement["type"] not in {"TSTypeAliasDeclaration", "TSInterfaceDeclaration"}:
            return ()
    if statement["type"] == "TSExportAssignment":
        return ()
    offsets = []
    pending = [statement]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(item)
            continue
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind in {"TSTypeAliasDeclaration", "TSInterfaceDeclaration"}:
            if id(item) in context_offsets:
                offsets.append(context_offsets[id(item)])
            continue
        if kind in {"ClassExpression", "ClassDeclaration"} and id(item) in context_offsets:
            offsets.append(context_offsets[id(item)])
        if kind == "TSModuleDeclaration":
            if id(item) in context_offsets:
                offsets.append(context_offsets[id(item)])
            continue
        if kind == "TSEnumDeclaration":
            # The compiler clears the possible-top-level-await flag on an enum.
            continue
        if kind == "CatchClause":
            pending.extend((item["body"], item.get("initializer")))
            param = item.get("param")
            if param and param["type"] != "Identifier":
                pending.append(param)
            continue
        if kind == "Identifier":
            if item["name"] == "await":
                return ()
            continue
        if kind in {"FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression", "TSDeclareFunction"}:
            continue
        if kind == "MethodDefinition" or (kind == "Property" and (item.get("method") or item["kind"] in {"get", "set"})):
            function = item["value"]
            if function.get("body") is not None:
                pending.extend((item.get("decorators"), item["key"] if item["computed"] else None))
                for param in function["params"]:
                    if param["type"] == "Identifier":
                        pending.append(param.get("decorators"))
                    else:
                        pending.append(param)
            continue
        if kind in {"PropertyDefinition", "Property"}:
            if item["computed"]:
                pending.append(item["key"])
            value = item.get("value")
            if item.get("shorthand"):
                if id(item["key"]) in context_offsets:
                    offsets.append(context_offsets[id(item["key"])])
                value = value.get("right")
            pending.extend((value, item.get("decorators")))
            continue
        if kind == "MemberExpression":
            pending.append(item["object"])
            if item["computed"]:
                pending.append(item["property"])
            continue
        pending.extend(value for key, value in item.items()
                       if key not in {"id", "typeParameters", "typeArguments", "typeAnnotation", "returnType"})
    return offsets


def stack_before_shift(parser, terminal, *, prefix=()):
    """Simulate the prefix and the final lookahead reductions without running grammar actions."""
    states = parser.statestack.copy()
    symbols = [symbol.type for symbol in parser.symstack]
    for index, lookahead in enumerate((*prefix, terminal)):
        while True:
            action = parser.action[states[-1]].get(lookahead)
            if action is None:
                return []
            if action >= 0:
                if index == len(prefix):
                    return symbols
                states.append(action)
                symbols.append(lookahead)
                break
            rule = parser.productions[-action]
            if rule.len:
                del states[-rule.len:]
                del symbols[-rule.len:]
            symbols.append(rule.name)
            states.append(parser.goto[states[-1]][rule.name])


def conditional_separator(parser, *, after_identifier=False):
    prefix = ("IDENTIFIER",) if after_identifier else ()
    return stack_before_shift(parser, "COLON", prefix=prefix)[-2:] == ["QUESTION", "assignment"]


_PARAMETER_PROPERTY_MODIFIERS = {"public", "private", "protected", "readonly", "override"}
_PARAMETER_MODIFIERS = _PARAMETER_PROPERTY_MODIFIERS | {"abstract", "accessor", "async", "declare", "default", "in", "out", "static", "export"}


# Keywords that the shared ECMAScript scanner can return as IDENTIFIER.
_TS_IDENTIFIER_KEYWORDS = STRICT_IDENTIFIERS | frozenset(
    "abstract accessor as asserts assert any async await boolean constructor declare get infer intrinsic is keyof "
    "module namespace never out readonly require number object satisfies set string symbol type undefined unique "
    "unknown using from global bigint override of defer".split()
)


# parseType permits an IdentifierName in a mandatory reference. The
# isStartOfType lookahead at a list boundary accepts only these reserved
# keywords as type starters (plus identifiers and contextual keywords).
_NON_TYPE_LIST_KEYWORDS = (Grammar.keywords.keys() | Grammar.reserved) - {
    "let", "this", "typeof", "void", "new", "function", "import", "null", "true", "false",
}

_IDENTIFIER_EXCLUDED_SCOPES = {
    "await": {"async", "async parameters", "async generator", "async generator parameters", "static block"},
    "yield": {"generator", "generator parameters", "async generator", "async generator parameters"},
}


class TypeScriptGrammar(ImportAttributeRules, DecoratorRules, DeclarationRules, JSDocTypeRules, TypeRules, Grammar):
    require_simple_strict_parameters = False
    diagnose_strict_parameters = False
    check_duplicate_proto = False
    allow_html_comments = False
    allow_legacy_numeric_literals_and_escapes = False
    typescript_regexp = True
    preserve_template_spelling = True
    check_meta_early_errors = False
    check_assignment_targets = False
    check_declaration_early_errors = False
    allow_parameter_operators = True
    allow_line_break_before_arrow = True
    contextual_shorthand_bindings = STRICT_IDENTIFIERS | {"await"}
    check_control_flow_early_errors = False
    check_private_name_early_errors = False
    check_duplicate_parameters = False
    check_rest_parameter_rules = False
    # Within an infer bound, intersections bind inside unions, and a leading
    # union bar still permits the following union terms before reduction.
    # Postfixes attach inside a prefix JSDoc nullable type before its operand is reduced.
    precedence = Grammar.precedence + (("nonassoc", "TYPE_BASE"), ("right", "CONDITIONAL_EXTENDS"), ("right", "TYPE_OR"), ("left", "TYPE_AND"),
                                        ("left", "DOC_POST_NULLABLE", "DOC_POST_NON_NULL", "TYPE_INDEX"))
    t_ignore = Grammar.t_ignore + "\u0085\u200b"
    additional_openers = {"TS_OBJECT", "SIG_PARAMS", "DOC_OPEN"}
    lexical_dialect_types = {"TYPE_LT", "PARAM_LT", "TYPE_GT", "TYPE_INDEX"}
    tokens = Grammar.tokens + JSDocTypeRules.jsdoc_tokens + ("TS_STATIC_BLOCK", "INVALID_BINDING_CHAIN", "UNARY_POWER_ERROR", "FIELD_TERMINATOR_ERROR", "TAG_TERMINATOR_ERROR", "MISSING_CLASS_BODY", "ENUM_OPEN", "SUPER_VALUE", "MISSING_NEW_ARGS", "MISSING_SUPER_MEMBER", "BARE_THROW", "ARROW_PARAMS", "ORDINARY_ARROW_PROBE", "DECL_MODIFIER", "MODIFIED_ASYNC_FUNCTION", "MODIFIED_LET", "ASYNC_ARROW_HEAD", "AT", "DECL_AT", "DEFAULT_AT", "EXPR_AT", "TS_GOAL", "FOR_LET", "TYPE_ALIAS", "INTERFACE", "DECLARE", "TYPE_MEMBER_MODIFIER", "OBJECT_MODIFIER", "OBJECT_DECORATED_MODIFIER", "OBJECT_ASYNC", "TS_OBJECT",
                               "TYPE_INDEX", "TYPE_LT", "TYPE_ARGUMENT_DOT", "PARAM_LT", "TYPE_GT", "NS", "TS_MODULE", "GLOBAL", "TS_ENUM", "SIG_PARAMS", "TS_INDEX_OPEN", "IMPLEMENTS",
                               "TUPLE_LABEL", "TUPLE_OPTIONAL", "CALL_TYPE_LT", "TYPE_ARGS_GOAL", "OPTIONAL_PARAM",
                               "FIELD_ASSIGN", "MODULE_STRING", "TS_AS", "SATISFIES", "TYPE_OR", "TYPE_AND", "TYPE_IMPORT", "CLASS_MODIFIER",
                               "PARAM_AT", "PARAM_MODIFIER", "COVER_MODIFIER", "TYPE_OPERATOR", "INFER", "INFER_EXTENDS", "EXPRESSION_EXTENDS", "CONDITIONAL_EXTENDS", "MAP_OPEN", "MAPPED_READONLY", "NON_NULL", "IS", "ASSERTS", "DEFINITE", "ARROW_RETURN", "ASSERT_IS", "SPEC_TYPE", "TYPE_PARAM_MODIFIER", "GENERIC_ARROW_LT", "ARROW_PROBE", "ASSERT_LT",
                               "ABSTRACT", "EXPORT_TYPE", "USING", "AWAIT_USING", "RETURN_ARM_GOAL", "RETURN_TYPE_GOAL", "BINDING_PROBE_GOAL", "TYPE_ARROW", "INFER_BOUND_GOAL", "DEFAULT_INTERFACE", "ATTRIBUTE_KEYWORD", "SOURCE_IMPORT", "SOURCE_DEFER", "DEFER_IMPORT", "DEFER_CALL", "IMPORT_VALUE", "TYPE_NAME", "INTRINSIC_ALIAS")

    def p_identifier(self, p):
        """identifier : IDENTIFIER
                      | LET"""
        super().p_identifier(p)
        if self.track_import_arguments and getattr(p.stack[-1], "value", None) in ("function", "class", "*"):
            start = p.lexpos(1)
            self.import_error_spans[id(p[0])] = (p[0], start, getattr(p.slice[1], "end_pos", start + len(p[1])))

    def identifier_node(self, name, offset):
        node = super().identifier_node(name, offset)
        if name in {"eval", "arguments"}:
            node["_strictNameOffset"] = offset
            self.has_strict_diagnostics = True
        return node

    def strict_statement(self, node, keyword, reason):
        if keyword.type == "DELETE":
            if id(node["argument"]) in self.grouped_patterns:
                return
            code, offset = 1102, keyword.operand_offset
        else:
            code, offset = 1101, keyword.lexpos
        node["_strictDiagnostic"] = {"code": code, "offset": offset, "message": reason}
        self.has_strict_diagnostics = True

    def check_strict_regions(self, body):
        super().check_strict_regions(body)
        if self.has_strict_diagnostics:
            check_strict_diagnostics(self, body)

    @TOKEN(CONFLICT_MARKER.pattern)
    def t_conflict_marker(self, token):
        raise self.error(token.lexpos, "merge conflict marker (TS1185)")

    def strict_violation(self, offset, reason):
        if reason in {"invalid strict binding", "invalid strict catch binding", "invalid strict arrow binding",
                      "invalid strict assignment target"}:
            return
        if reason.startswith("reserved identifier ") or reason in {"reserved shorthand identifier", "reserved shorthand binding"}:
            return
        super().strict_violation(offset, reason)

    def check_import_binding(self, node, offset):
        if node.get("name") in STRICT_IDENTIFIERS | {"await", "eval", "arguments"}:
            return
        super().check_import_binding(node, offset)

    def legacy_number(self, token):
        token.legacy_number_code = 1489 if re.match(r"0[0-7]*[89]", token.value) else 1121

    def report_legacy_number(self, token, previous):
        # The octal suggestion includes one preceding character when the last
        # scanned token was minus, even if trivia separated it from the number.
        start = token.lexpos
        if token.legacy_number_code == 1121 and previous and previous.type == "MINUS":
            start -= 1
        end = token.lexpos + len(token.value)
        error = self.error(start, "legacy numeric literal", code=token.legacy_number_code, length=end - start)
        if self.script_pass is None:
            raise error
        self.script_pass.record(error)
        if not hasattr(token, "provisional_lexical_error"):
            token.provisional_lexical_error = error

    @staticmethod
    def numeric_suffix_length(spelling, name):
        if "\\" not in spelling:
            return len(spelling)
        # scanIdentifierParts measures the cooked suffix in UTF-16. Braced
        # escapes omit the plain text since the preceding escape.
        units = len(name.encode("utf-16-le", "surrogatepass")) // 2
        previous = 0
        for escape in IDENTIFIER_ESCAPE.finditer(spelling):
            if escape[2] is not None:
                plain = spelling[previous:escape.start()]
                units -= len(plain.encode("utf-16-le", "surrogatepass")) // 2
            previous = escape.end()
        prefix = spelling.encode("utf-16-le", "surrogatepass")[:2 * units]
        return len(prefix.decode("utf-16-le", "surrogatepass"))

    def check_number_suffix(self, token, following):
        offset = token.lexer.lexpos
        raw = token.value
        prefix = self.source[token.lexpos:token.lexpos + 2].lower()
        radix = prefix[1] if prefix in {"0x", "0o", "0b"} and token.lexpos + 2 < len(self.source) else ""
        if radix and raw == "0" and not self.source.startswith("_", offset + 1):
            code = {"x": 1125, "o": 1178, "b": 1177}[radix]
            error = self.error(offset + 1, "digit expected after radix prefix", code=code, length=0)
            self.record_numeric_error(token, error, offset + 1)
            return
        exponent_digits = None
        if not radix and following in "eE" and not raw.endswith("n") and "e" not in raw.lower():
            exponent_digits = offset + 1
            if self.source.startswith(("+", "-"), exponent_digits):
                exponent_digits += 1
        if len(raw) > 1 and raw[0] == "0" and raw[1].isdigit():
            # A non-octal decimal scans its fraction and exponent before the
            # leading-zero diagnostic. Octal literals end at the initial digits.
            fraction_separator = following == "_" and any(c in raw for c in ".eE")
            if not re.match(r"0[0-7]*[89]", raw) or (not fraction_separator and exponent_digits is None):
                return
        separator = None
        fragment_start = False
        if following == "_" and not raw.endswith("n"):
            separator = offset
            fragment_start = raw == "0" or raw.endswith(".")
        elif radix and raw == "0":
            separator, fragment_start = offset + 1, True
        elif exponent_digits is not None and self.source.startswith("_", exponent_digits):
            separator, fragment_start = exponent_digits, True
        if separator is not None:
            repeated = not fragment_start and self.source.startswith("__", separator)
            error = self.error(separator + int(repeated), "invalid numeric separator",
                               code=6189 if repeated else 6188, length=1)
            end = _NUMERIC_FRAGMENTS[radix].match(self.source, token.lexpos).end()
            self.record_numeric_error(token, error, end)
            return
        if radix:
            # Radix-prefixed numbers may be immediately followed by an operator such as in.
            return
        # This check applies only to an unescaped IdentifierStart. The next
        # scanner invocation classifies an escape or a digit after a BigInt.
        if not self.identifier_char(following, first=True):
            return
        consume_to = offset
        if exponent_digits is not None:
            consume_to = exponent_digits
            error = self.error(consume_to, "digit expected in exponent", code=1124, length=0)
        else:
            end, name = self.read_identifier(token, offset)
            length = self.numeric_suffix_length(self.source[offset:end], name)
            if following == "n" and length == 1:
                consume_to = end
                scientific = "e" in raw.lower() and "." not in raw
                error = self.error(token.lexpos, "invalid BigInt suffix", code=1352 if scientific else 1353,
                                   length=offset + 1 - token.lexpos)
            else:
                error = self.error(offset, "identifier immediately after numeric literal", code=1351, length=length)
        self.record_numeric_error(token, error, consume_to)

    def record_numeric_error(self, token, error, consume_to):
        if self.script_pass is None:
            raise error
        if not hasattr(token, "provisional_lexical_error"):
            token.provisional_lexical_error = error
        token.lexer.lexpos = token.end_pos = consume_to
        token.value = self.source[token.lexpos:consume_to]

    def identifier_escape_digits_end(self, offset, first):
        if self.source.startswith("\\u{", offset):
            digits = _HEX_DIGITS.match(self.source, offset + 3)
            end, text = digits.end(), digits[0]
        elif self.source.startswith("\\u", offset):
            end = offset + 6
            text = self.source[offset + 2:end]
            if len(text) != 4 or not _HEX_DIGITS.fullmatch(text):
                return None
        else:
            return None
        significant = text.lstrip("0") or "0"
        if not text or len(significant) > 6:
            return None
        code = int(significant, 16)
        return end if code <= 0x10ffff and self.identifier_char(chr(code), first) else None

    def read_identifier(self, token, start, *, jsx_name=False):
        def recover_escape(offset, first):
            # A bad continuation ends the current name. At the start of the
            # next token the same backslash gets a zero-width TS1127.
            if not self.source.startswith("\\u{", offset):
                return None
            end = self.identifier_escape_digits_end(offset, first)
            if end is None:
                return None
            # The point fits this position. Only the closing brace is missing,
            # so the scanner stays in the identifier after the error.
            diagnostic = self.error(end, "unterminated Unicode escape", length=0,
                                    code=1126 if end == len(self.source) else 1199)
            if jsx_name:
                if not hasattr(token, "jsx_escape_error"):
                    token.jsx_escape_error = diagnostic
            elif self.script_pass is None:
                raise diagnostic
            elif not hasattr(token, "provisional_lexical_error"):
                token.provisional_lexical_error = diagnostic
            return end, self.source[offset:end]

        return scan_identifier(self.source, start, self.error, self.identifier_char,
                               jsx_name=jsx_name, recover_escape=recover_escape)

    def invalid_character(self, token):
        char = self.source[token.lexpos]
        error = self.invalid_character_error(token.lexpos, char)
        if self.script_pass is None or error.code != 1127:
            raise error
        # A speculative lexer may read ahead into a different lexical context.
        # Report this character only when the preliminary parser consumes it.
        token.invalid_character = error
        token.type, token.value, token.escaped = "RESERVED", char, False
        token.lexer.lexpos = token.end_pos = token.lexpos + 1
        return token

    def recover_invalid_character(self, parser, token, peek, upcoming):
        self.script_pass.record(token.invalid_character)
        if token.type == "JSX_NAME":
            following = peek()
            if following and accepts_lookahead(parser, following.type):
                return False
            return accepts_lookahead(parser, "JSX_NAME")
        if (Grammar.identifier_char(token.value, first=True) and accepts_lookahead(parser, "IDENTIFIER")
                and not accepts_lookahead(parser, "EMPTY_SEMI")):
            # createIdentifier speculatively rescans an Unknown as an ESNext
            # name. Keep the lexical error from the requested target.
            end, token.value = scan_identifier(self.source, token.lexpos, self.error, Grammar.identifier_char,
                                               recover_escape=lambda offset, first: None)
            token.type = "IDENTIFIER"
            self.lexer.lexpos = token.end_pos = end
            self.lexer.lineno = token.lineno
            upcoming.clear()
        else:
            following = peek()
            if (following is None or hasattr(following, "invalid_character") or accepts_lookahead(parser, following.type)
                    or (following.value in {"/", "/="} and accepts_lookahead(parser, "REGEXP"))):
                return False
            if accepts_lookahead(parser, "SEMICOLON", following.type):
                token.type, token.value = "SEMICOLON", ";"
            elif accepts_lookahead(parser, "COMMA", following.type):
                token.type, token.value = "COMMA", ","
            elif accepts_lookahead(parser, "IDENTIFIER"):
                token.type, token.value = "IDENTIFIER", ""
            else:
                return False
        token.missing_identifier = True
        return True

    def invalid_character_error(self, offset, char):
        if char == "\ufffd":
            return self.error(0, "non-text source file", code=1490, length=0)
        if char == "#" and offset and self.source.startswith("#!", offset):
            return self.error(offset, "shebang outside start of file", code=18026, length=2)
        return self.error(offset, repr(char), code=1127, length=0 if char == "\\" else 1)

    def string_error(self, offset, reason):
        if reason == "line break in string":
            return self.error(offset, "unterminated string literal", code=1002, length=0)
        if reason == "unterminated string":
            end = len(self.source)
            trailing_slashes = end - len(self.source.rstrip("\\"))
            if trailing_slashes % 2:
                return self.error(end, "end of input in escape sequence", code=1126, length=0)
            return self.error(end, "unterminated string literal", code=1002, length=0)
        if reason == "legacy decimal escape":
            digit = self.source[offset + 1]
            if digit in "89":
                return self.error(offset, reason, code=1488, length=2)
            tail = 2 if digit in "0123" else 1
            end = offset + 2
            while end < min(len(self.source), offset + 2 + tail) and self.source[end] in "01234567":
                end += 1
            return self.error(offset, reason, code=1487, length=end - offset)
        if reason == "invalid hexadecimal escape":
            digits = offset + 2
            return self.error(_HEX_DIGITS.match(self.source, digits).end(), "hexadecimal digit expected",
                              code=1125, length=0)
        if reason in {"invalid Unicode escape", "Unicode escape outside code point range"}:
            digits = _HEX_DIGITS.match(self.source, offset + 3)
            value = digits[0].lstrip("0").lower()
            if not digits[0]:
                return self.error(digits.start(), "hexadecimal digit expected", code=1125, length=0)
            if len(value) > 6 or (len(value) == 6 and value > "10ffff"):
                return self.error(digits.start(), "Unicode escape outside code point range", code=1198,
                                  length=digits.end() - digits.start())
            if digits.end() == len(self.source):
                return self.error(digits.end(), "end of input in Unicode escape", code=1126, length=0)
            return self.error(digits.end(), "unterminated Unicode escape", code=1199, length=0)
        return self.error(offset, reason)

    template_escape_error = string_error

    def handle_unterminated_template(self, token, initial, trailing_escape):
        if trailing_escape:
            error = self.error(len(self.source), "end of input in escape sequence", code=1126, length=0)
        else:
            error = self.error(len(self.source), "unterminated template", code=1160, length=0)
        if initial:
            raise error
        # Rescanning a substitution tail checks escapes before EOF only
        # for untagged templates. The yacc state identifies that context.
        token.unterminated_error = error

    def check_template_substitution_eof(self, parser, previous):
        if accepts_lookahead(parser, "UNTAGGED_TEMPLATE_TAIL") or accepts_lookahead(parser, "TEMPLATE_TAIL"):
            raise self.error(len(self.source), "expected '}' in template substitution", code=1005, length=0)
        expected = (("RBRACE", "}"), ("RBRACKET", "]"), ("TYPE_GT", ">"))
        # An empty argument or parameter list may close immediately. A
        # parenthesized expression at the same position needs an operand.
        reductions = parser.goto.get(parser.statestack[-1], {})
        if "argument" in reductions or "parameters" in reductions:
            expected += (("RPAREN", ")"),)
        for kind, spelling in expected:
            if accepts_lookahead(parser, kind):
                raise self.error(len(self.source), f"expected '{spelling}' in template substitution",
                                 code=1005, length=0)
        end = getattr(previous, "end_pos", previous.lexpos + len(previous.value))
        if accepts_lookahead(parser, "TYPE_OPERATOR"):
            raise self.error(end, "type expected", code=1110, length=0)
        if accepts_lookahead(parser, "REGEXP"):
            raise self.error(end, "expression expected", code=1109, length=0)
        if previous.type in {"DOT", "OPTIONAL", "TYPEOF"} and accepts_lookahead(parser, "IDENTIFIER"):
            raise self.error(end, "identifier expected", code=1003, length=0)
        for kind, spelling in (("RPAREN", ")"), ("COLON", ":")):
            if accepts_lookahead(parser, kind):
                raise self.error(len(self.source), f"expected '{spelling}' in template substitution",
                                 code=1005, length=0)

    def missing_substitution(self, token):
        # The compiler diagnoses the closing brace as a single token before
        # rescanning the rest of a template tail.
        length = 1 if token.type in {"TEMPLATE_MIDDLE", "TEMPLATE_TAIL"} else len(token.value)
        if token.expects_substitution_type:
            return self.error(token.lexpos, "type expected", code=1110, length=length)
        return self.error(token.lexpos, "expression expected", code=1109, length=length)

    def token_error(self, token, message, code):
        length = getattr(token, "end_pos", token.lexpos + len(token.value)) - token.lexpos
        return self.error(token.lexpos, message, code=code, length=length)

    def substitution_delimiter(self):
        parser = self.parser
        if accepts_lookahead(parser, "UNTAGGED_TEMPLATE_TAIL") or accepts_lookahead(parser, "TEMPLATE_TAIL"):
            return "}"
        # Look back only within the innermost template substitution. Its
        # already-reduced operands can be followed by different delimiters
        # in type arguments, indexed access, tuples and object types.
        opener = None
        for symbol in reversed(parser.symstack):
            if symbol.type in {"UNTAGGED_TEMPLATE_HEAD", "UNTAGGED_TEMPLATE_MIDDLE", "TEMPLATE_HEAD", "TEMPLATE_MIDDLE"}:
                break
            if opener is None and symbol.type in {"TYPE_LT", "TYPE_INDEX", "LBRACKET", "TS_OBJECT", "OBJECT_OPEN", "LPAREN", "SIG_PARAMS"}:
                opener = symbol.type
        else:
            return None
        if opener == "TYPE_LT" and accepts_lookahead(parser, "TYPE_GT"):
            return ">"
        if opener == "TYPE_INDEX" and accepts_lookahead(parser, "RBRACKET"):
            return "]"
        if opener == "TS_OBJECT" and accepts_lookahead(parser, "SEMICOLON"):
            return ";"
        if opener in {"LBRACKET", "OBJECT_OPEN", "LPAREN", "SIG_PARAMS"} and accepts_lookahead(parser, "COMMA"):
            return ","
        if opener == "LPAREN" and accepts_lookahead(parser, "RPAREN"):
            return ")"
        return None

    def type_parameter_value_error(self, parser, token):
        stack = parser.symstack
        index = len(stack) - 1
        complete = stack[index].type in {"ts_type", "exponential"}
        if complete:
            index -= 1
        separator = stack[index]
        if separator.type not in {"EXTENDS", "EXPRESSION_EXTENDS", "ASSIGN"}:
            return None
        index -= 1
        if separator.type == "ASSIGN" and stack[index].type in {"ts_type", "exponential"}:
            index -= 2  # skip the constraint and its extends token
        if index < 2 or stack[index].type != "identifier":
            return None
        index -= 1
        while stack[index].type == "TYPE_PARAM_MODIFIER":
            index -= 1
        if stack[index].type not in {"PARAM_LT", "GENERIC_ARROW_LT"} and not (
                stack[index].type == "COMMA" and stack[index - 1].type == "ts_param_list"):
            return None
        if complete:
            if token is None:
                return self.error(len(self.source), "expected '>' after type parameters", code=1005, length=0)
            return self.token_error(token, "expected a separator after the type parameter", 1005)
        expression = separator.type == "EXPRESSION_EXTENDS" or (
            separator.type == "EXTENDS" and token is not None and token.value.startswith(">"))
        code, message = (1109, "expression expected") if expression else (1110, "type expected")
        if token is None:
            end = getattr(separator, "end_pos", separator.lexpos + len(separator.value))
            return self.error(end, message, code=code, length=0)
        if token.value.startswith(">"):
            # Before operator rescanning, the compiler sees one closing angle.
            return self.error(token.lexpos, message, code=code, length=1)
        if token.type in {"COMMA", "SEMICOLON", "RPAREN", "RBRACKET", "RBRACE", "ASSIGN", "COLON", "ARROW"}:
            return self.token_error(token, message, code)
        return None

    def type_parameter_list_error(self, parser, token):
        stack = parser.symstack
        last = stack[-1].type
        at_start = last == "PARAM_LT" or (last == "COMMA" and stack[-2].type == "ts_param_list")
        after_name = (last == "identifier" and stack[-2].type in {"PARAM_LT", "TYPE_PARAM_MODIFIER"}) or (
            last == "ts_param_list")
        if not (at_start or after_name or last == "TYPE_PARAM_MODIFIER"):
            return None
        if token is None:
            if last == "TYPE_PARAM_MODIFIER":
                return self.error(len(self.source), "identifier expected", code=1003, length=0)
            return self.error(len(self.source), "expected '>' after type parameters", code=1005, length=0)
        if last == "TYPE_PARAM_MODIFIER" and token.type == "PRIVATE_NAME":
            return self.token_error(token, "private identifier cannot name a type parameter", 18016)
        if last == "TYPE_PARAM_MODIFIER" or (at_start and token.type in {"IN", "CONST"}):
            reserved = token.value in self.keywords or token.value in self.reserved
            return self.token_error(token, "identifier expected in type parameter", 1359 if reserved else 1003)
        if at_start:
            if token.type in {"LPAREN", "LBRACE", "EXTENDS"}:
                return self.token_error(token, "expected '>' after type parameters", 1005)
            return self.token_error(token, "type parameter declaration expected", 1139)
        return self.token_error(token, "expected separator after type parameter", 1005)

    def p_error(self, token):
        if self.missing_arrow_kind(self.parser):
            if token is None:
                raise self.error(len(self.source), "expected '=>' after arrow parameters", code=1005, length=0)
            raise self.token_error(token, "expected '=>' after arrow parameters", 1005)
        if hasattr(token, "expects_substitution_type"):
            raise self.missing_substitution(token)
        error = self.type_parameter_value_error(self.parser, token) or self.type_parameter_list_error(self.parser, token)
        if error is not None:
            raise error
        missing = self.missing_assertion_token(self.parser, token)
        if missing:
            raise self.assertion_token_error(token, missing)
        stack = self.parser.symstack
        if token is not None and stack[-1].type in {"TS_AS", "SATISFIES"} and token.type == "COLON":
            raise self.token_error(token, "type expected in assertion", 1110)
        if (token is not None and stack[-1].type == "identifier" and stack[-2].type == "PARAM_MODIFIER"
                and accepts_lookahead(self.parser, "COMMA")):
            raise self.token_error(token, "expected ',' after modified parameter", 1005)
        if stack[-1].type == "COMMA" and "other_imports" in self.parser.goto.get(self.parser.statestack[-1], {}):
            # A top-level default import followed by a comma has already
            # established the module goal, even if its named imports are absent.
            if self.script_pass and [symbol.type for symbol in stack[1:4]] == ["TS_GOAL", "module_items", "IMPORT"]:
                self.script_pass.incomplete_module_indicator = True
            if token is None:
                raise self.error(len(self.source), "expected '{' in import clause", code=1005, length=0)
            raise self.token_error(token, "expected '{' in import clause", 1005)
        if (token is not None and token.type == "COLON" and stack[-1].type == "ts_type"
                and accepts_lookahead(self.parser, "COMMA") and accepts_lookahead(self.parser, "RBRACKET")):
            raise self.token_error(token, "':' where a comma was expected", 1005)
        if token is not None:
            if (getattr(token, "escaped", False) and token.value in {"of", "in", "instanceof"}
                    and accepts_lookahead(self.parser, token.value.upper())):
                raise self.token_error(token, "escape in operator", 1260)
            delimiter = self.substitution_delimiter()
            if delimiter:
                reason = f"expected '{delimiter}' in template substitution"
                # The reference scanner initially reads > as one token. In
                # a valid shift expression the expression parser rescans it.
                if token.value.startswith(">"):
                    raise self.error(token.lexpos, reason, code=1005, length=1)
                raise self.token_error(token, reason, 1005)
        if token is None and stack[-1].type == "SUPER" and accepts_lookahead(self.parser, "MISSING_SUPER_MEMBER"):
            raise self.error(len(self.source), "expected an argument list or member access after super", code=1034, length=0)
        if stack[-1].type in {"AWAIT", "NEW"} and accepts_lookahead(self.parser, "REGEXP"):
            keyword = stack[-1]
            reason = "expression expected after " + keyword.value
            if token is None:
                end = getattr(keyword, "end_pos", keyword.lexpos + len(keyword.value))
                raise self.error(end, reason, code=1109, length=0)
            raise self.token_error(token, reason, 1109)
        head = getattr(token, "statement_identifier", None)
        if head is not None:
            end = getattr(head, "end_pos", head.lexpos + len(head.value))
            raise self.missing_semicolon_after_name(head.value, head.lexpos, end, token)
        if token is not None and token.type == "PRIVATE_NAME" and stack[-1].type == "FOR" and accepts_lookahead(self.parser, "AWAIT"):
            raise self.token_error(token, "expected '(' after for", 1005)
        if stack[-1].type in {"DOT", "OPTIONAL"} and accepts_lookahead(self.parser, "IDENTIFIER"):
            raise self.missing_property_name(stack[-1], token)
        super().p_error(token)

    def missing_property_name(self, operator, token):
        if token is None:
            end = len(self.source) if operator.type == "OPTIONAL" else operator.lexpos + 1
            return self.error(end, "end of input where a property name was required", code=1003, length=0)
        if token.type == "PRIVATE_NAME":
            # parseRightSideOfDot reads the entire private name before
            # attaching a zero-width diagnostic in an ordinary entity name.
            return self.error(token.end_pos, "identifier expected after property access", code=1003, length=0)
        if token.value.startswith(">"):
            return self.error(token.lexpos, "identifier expected after property access", code=1003, length=1)
        return self.token_error(token, f"{token.value!r} where a property name was required", 1003)

    def missing_semicolon_after_name(self, name, start, end, token):
        if name in {"interface", "type", "module", "namespace"}:
            if name == "interface":
                code = 1438 if token.value == "{" else 2427
            elif name == "type":
                code = 1439 if token.value == "=" else 2457
            else:
                code = 1437 if token.value == "{" else 2819
            return self.token_error(token, f"invalid {name} name", code)
        if name in {"const", "let", "var"}:
            return self.error(start, "variable declaration not allowed here", code=1440, length=end - start)
        if name == "is":
            return self.error(start, "type predicate outside return position", code=1228, length=token.lexpos - start)
        suggestion = keyword_suggestion(name)
        if suggestion:
            return self.error(start, f"keyword or identifier. Did you mean '{suggestion}'?", code=1435, length=end - start)
        return self.error(start, "keyword or identifier", code=1434, length=end - start)

    def class_name_separator_error(self, p, token):
        marked = p.stack[-1].type in {"NOT", "QUESTION"}
        index = -2 if marked else -1
        key, computed, _, start = p.stack[index].value
        if computed or key["type"] != "Identifier":
            return self.token_error(token, "semicolon required after property name", 1005)
        name = key["name"]
        end, _ = scan_identifier(self.source, start, self.error, self.identifier_char)
        if (not marked and p.stack[index - 1].type == "class_elements" and token.value != "["
                and (name in self.keywords or name in _TS_IDENTIFIER_KEYWORDS)
                and name not in {"public", "private", "protected", "readonly", "override", "accessor", "static", "get", "set"}):
            return self.error(start, "class member expected", code=1068, length=end - start)
        return self.missing_semicolon_after_name(name, start, end, token)

    def goal_token(self):
        return "TS_GOAL"

    def reset(self, source, source_type):
        super().reset(source, source_type)
        self.type_parameter_offsets = {}
        self.applied_argument_spans = {}
        self.has_strict_diagnostics = False
        self.has_jsdoc_parameters = False
        self.always_strict = False
        self.recover_regexp = False
        self.script_pass = None
        self.first_pass_contexts = None
        self.script_context_offsets = ()
        self.parameter_starts = {}
        self.pending_parameter_lists = {}
        self.pending_generic_lists = {}
        self.import_keyword_offsets = {}
        self.import_module = "es2015"
        self.verbatim_import_error = None
        self.import_error_spans = {}
        self.track_import_arguments = "import" in source or "\\" in source
        self.index_spans = {}
        self.parameter_spans = {}
        self.optional_parameter_offsets = {}
        self.cover_starts = {}
        self.directive_offsets = {}
        self.arrow_heads = {}
        self.ordinary_arrow_probe = False
        self.last_possible_arrow = -1
        self.arrow_probe_depth = 0
        self.return_types = {}
        self.cover_annotations = {}
        self.cover_modifiers = {}
        self.object_marker_offsets = {}
        self.ambient_depth = 0

    def type_member_modifier(self, parser, token, peek):
        word = token.value
        if word not in {"abstract", "accessor", "async", "const", "declare", "default", "export", "in", "out",
                        "override", "private", "protected", "public", "readonly", "static"}:
            return False
        if not accepts_lookahead(parser, "TYPE_MEMBER_MODIFIER"):
            return False
        following = peek()
        if not following:
            return False
        if word == "readonly" and following.type == "LBRACKET" and peek(3) and peek(3).type == "IN":
            if accepts_lookahead(parser, "MAPPED_READONLY"):
                return False
        if word == "static":
            for symbol in reversed(parser.symstack):
                if symbol.type == "type_member_modifiers":
                    if "static" in symbol.value["modifiers"]:
                        return False
                elif symbol.type == "TYPE_MEMBER_MODIFIER":
                    if symbol.value == "static":
                        return False
                else:
                    break
        return self.member_modifier_follows(word, token, peek)

    def type_parameter_modifier(self, parser, token, previous, peek):
        # An export or default token cannot itself start the TypeParameters
        # list element, but can be inspected after a preceding modifier.
        if token.value in {"export", "default"} and previous.type != "TYPE_PARAM_MODIFIER":
            return False
        if token.value == "static":
            for sym in reversed(parser.symstack):
                if sym.type != "TYPE_PARAM_MODIFIER":
                    break
                if sym.value == "static":
                    return False
        return self.member_modifier_follows(token.value, token, peek, class_member=True)

    @staticmethod
    def default_modifier_follows(peek, distance):
        head = peek(distance)
        if not head:
            return False
        if head.value in {"class", "function", "interface"} or head.type == "AT":
            return True
        tail = peek(distance + 1)
        return bool(tail and tail.lineno == head.lineno and
                    (head.value, tail.value) in {("abstract", "class"), ("async", "function")})

    def member_modifier_follows(self, word, token, peek, *, class_member=False):
        following = peek()
        if following is None:
            return False
        if word == "const" and not class_member:
            return following.value == "enum"
        if word == "default" or (word == "export" and following.value == "default"):
            return self.default_modifier_follows(peek, 2 if word == "export" else 1)
        if word == "export":
            if following.value == "type":
                following = peek(2)
            if class_member and following and following.type == "AT":
                return True
            if not following or following.value == "as" or following.type == "MULTIPLY":
                return False
        elif word != "static" and following.lineno != token.lineno:
            return False
        return following.type in {"LBRACKET", "MULTIPLY", "IDENTIFIER", "RESERVED", "PRIVATE_NAME", "NUMBER", "STRING"} or following.value in self.keywords

    def parameter_modifier_before(self, token, peek, distance=1):
        following = peek(distance)
        if not following or getattr(token, "escaped", False) or token.value not in _PARAMETER_MODIFIERS:
            return False
        if token.value == "default" or (token.value == "export" and following.value == "default"):
            return self.default_modifier_follows(peek, distance + int(token.value == "export"))
        if token.value == "export":
            if following.value == "type":
                following = peek(distance + 1)
            if following and following.type == "AT":
                return True
            if not following or following.value == "as" or following.type == "LBRACE":
                return False
        elif token.value != "static" and following.lineno != token.lineno:
            return False
        return (following.type in {"IDENTIFIER", "LET", "RESERVED", "PRIVATE_NAME", "THIS", "ELLIPSIS", "LBRACE", "LBRACKET"}
                or following.value in _PARAMETER_MODIFIERS)

    def can_follow_declaration_of(self, token, peek):
        name = peek()
        if not name or not self.binding_identifier(name):
            return False
        closing = peek(2)
        if not closing or closing.type != "RPAREN":
            return False
        scope = token.enclosing_scope
        if not self.arrow_head_identifier(name, scope) or (
            scope == "module" and name.value == "await" and not self.declaration_file
        ):
            # The reference parser treats 'of' as the binding here, then
            # diagnoses the following keyword where it expects a comma.
            raise self.token_error(name, "expected comma between declarations", 1005)
        return True

    @staticmethod
    def arrow_head_identifier(token, scope):
        if scope in _IDENTIFIER_EXCLUDED_SCOPES.get(token.value, ()):
            return False
        return token.type in {"IDENTIFIER", "LET"} or (token.type == "RESERVED" and
                (token.value in STRICT_IDENTIFIERS or token.value == "await"))

    def parenthesized_arrow_head(self, token, peek, distance, parser, *, ordinary=False):
        opening = token if distance == 1 else peek(distance - 1)
        first = peek(distance)
        if first is None:
            return False
        if first.type == "ELLIPSIS":
            return True
        if first.type == "RPAREN":
            following = peek(distance + 1)
            return following is not None and following.type in {"ARROW", "COLON", "LBRACE"}
        if first.type not in {"LBRACE", "LBRACKET"}:
            scope = token.enclosing_scope
            identifier = first.type == "THIS" or self.arrow_head_identifier(first, scope)
            if not identifier and first.value not in _PARAMETER_MODIFIERS:
                return False
            following = peek(distance + 1)
            if not following:
                return False
            if (first.type != "PRIVATE_NAME" and first.value in _PARAMETER_MODIFIERS and first.value != "async"
                    and self.arrow_head_identifier(following, scope)):
                return following.value != "as"
            if not identifier:
                return False
            if following.type == "COLON":
                return True
            if following.type == "QUESTION":
                after = peek(distance + 2)
                return after is not None and after.type in {"COLON", "COMMA", "ASSIGN", "RPAREN"}
            if following.type not in {"RPAREN", "COMMA", "ASSIGN"}:
                return False
        # Binding patterns, plain names and default values can also form
        # ordinary expressions. These heads require a successful yacc probe.
        return opening.lexpos < self.last_possible_arrow and self.has_arrow_head(opening, parser, ordinary=ordinary)

    @staticmethod
    def missing_arrow_kind(parser):
        stack = parser.symstack
        i = len(stack) - 1
        if stack[i].type == "return_annotation":
            i -= 1
        if stack[i].type in {"formal_list", "async_formals"}:
            i -= 1
        elif stack[i].type == "RPAREN":
            i -= 1
            while stack[i].type in {"parameters", "rest_parameter", "COMMA"}:
                i -= 1
        else:
            return None
        if stack[i].type == "ARROW_PARAMS" and accepts_lookahead(parser, "ARROW"):
            return "ARROW"
        if stack[i].type == "ASYNC_PARAMS":
            i -= 1
        if (stack[i].type == "ts_params" and stack[i - 1].type == "ASYNC_ARROW_HEAD"
                and accepts_lookahead(parser, "ASYNC_ARROW")):
            return "ASYNC_ARROW"
        return None

    @staticmethod
    def exported_head(stack, index):
        index -= 1
        while stack[index].type in {"DECL_ASYNC", "EXPR_ASYNC", "DEFAULT_ASYNC", "DEFAULT", "DECLARE",
                                    "ABSTRACT", "ambient_scope", "DECL_MODIFIER", "declaration_decorator", "default_decorator"}:
            index -= 1
        return stack[index].type == "EXPORT"

    def unterminated_regexp(self, token, line_end):
        start = token.lexpos
        end = start + 1
        classes = groups = 0
        quantifier = False
        while end < line_end:
            char = self.source[end]
            if char == "\\":
                end = min(end + 2, line_end)
                continue
            if char == "[":
                classes += 1
            elif char == "]" and classes:
                classes -= 1
            elif not classes:
                if char == "{":
                    quantifier = True
                elif char == "}" and quantifier:
                    quantifier = False
                elif not quantifier:
                    if char == "(":
                        groups += 1
                    elif char == ")" and groups:
                        groups -= 1
                    elif char in ")]}":
                        break
            end += 1
        # TypeScript leaves trailing whitespace, semicolons and the first
        # unmatched closing delimiter for the enclosing grammar.
        while end > start + 1:
            char = self.source[end - 1]
            if char != ";" and char not in self.t_ignore and unicodedata.category(char) != "Zs":
                break
            end -= 1
        error = self.error(start, "unterminated RegExp literal", code=1161, length=end - start)
        if self.script_pass is None:
            raise error
        self.script_pass.record(error)
        token.type, token.value, token.end_pos = "REGEXP", self.source[start:end], end
        token.pattern = {"type": "RegExpLiteral", "pattern": self.source[start + 1:end], "flags": "", "alternatives": None}
        token.unterminated_regexp = True
        self.lexer.lexpos, self.lexer.lineno = end, token.lineno

    @staticmethod
    def missing_assertion_token(parser, token):
        if token is None or token.value not in {"/", "/="}:
            return None
        if parser.symstack[-1].type == "ASSERT_LT" and accepts_lookahead(parser, "IDENTIFIER", "TYPE_GT"):
            return "IDENTIFIER"
        if accepts_lookahead(parser, "TYPE_GT", "REGEXP"):
            opening = next((s.type for s in reversed(parser.symstack)
                            if s.type in {"ASSERT_LT", "TYPE_LT", "CALL_TYPE_LT", "PARAM_LT", "GENERIC_ARROW_LT"}), None)
            if opening == "ASSERT_LT":
                return "TYPE_GT"
        return None

    def assertion_token_error(self, token, kind):
        if kind == "IDENTIFIER":
            return self.token_error(token, "type expected in angle assertion", 1110)
        return self.token_error(token, "expected '>' after asserted type", 1005)

    def provisional_expression_tokens(self, parser, previous, token):
        if token.value in {"/", "/="}:
            missing = self.missing_assertion_token(parser, token)
            while missing:
                self.script_pass.record(self.assertion_token_error(token, missing))
                yield inserted_token(previous, missing, "" if missing == "IDENTIFIER" else ">")
                missing = self.missing_assertion_token(parser, token)
        # When the script scan sees division, a regexp group can look like
        # an incomplete conditional. Recover only in the tree used for replay.
        missing_operand = ((previous.type == "DIVIDE" and token.type in {"SEMICOLON", "DOT", "OPTIONAL"})
                           or (previous.type == "LPAREN" and token.type == "QUESTION")
                           or (previous.type == "QUESTION" and token.type == "COLON"))
        missing_else = (token.type == "RPAREN" and self.script_pass.first_error and
                        any(getattr(s, "provisional_conditional", False) for s in parser.symstack) and
                        accepts_lookahead(parser, "COLON"))
        if not (missing_operand or missing_else) or accepts_lookahead(parser, token.type):
            return
        if missing_operand and not accepts_lookahead(parser, "IDENTIFIER"):
            return
        if self.script_pass.first_error is None:
            self.script_pass.record(self.token_error(token, "expression expected", 1109))
        if token.type == "QUESTION":
            token.provisional_conditional = True
        if missing_else:
            yield inserted_token(previous, "COLON", "")
        yield inserted_token(previous, "IDENTIFIER", "")

    def await_context_boundaries(self, parser, token, previous, scope):
        stack = parser.symstack
        computed = False
        for i in range(len(stack) - 1, 1, -1):
            kind = stack[i].type
            if kind == "class_elements":
                # An unreduced bracket after the member modifiers starts a computed key.
                key = i + 1
                while key < len(stack) and stack[key].type in {
                    "CLASS_MODIFIER", "CLASS_STATIC", "ASYNC_METHOD", "MULTIPLY", "CLASS_ACCESSOR",
                    "async_class_prefix", "element_decorator"
                }:
                    key += 1
                if key == len(stack) or stack[key].type != "LBRACKET":
                    return False
                head = i - 3  # class keyword or name, followed by heritage and LBRACE
                if stack[head].type == "identifier":
                    head -= 1
                if stack[head].type not in {"DECL_CLASS", "DEFAULT_CLASS", "CLASS"}:
                    return False
                if scope == "module" and stack[head].lexpos in self.script_context_offsets:
                    token.type = "IDENTIFIER"
                    token.script_await = True
                    return False
                computed = True
                if self.exported_head(stack, head) or scope in {"async", "async generator"}:
                    break
                continue
            if not computed and kind in {"DEFAULT_FUNCTION", "DEFAULT_ASYNC", "DEFAULT_CLASS", "DEFAULT_INTERFACE"}:
                return False
            if kind in {"DEFAULT", "ASSIGN"} and stack[i - 1].type == "EXPORT":
                break
            if kind in {"ARROW", "ASYNC_ARROW", "FN_OPEN", "ASYNC_OPEN", "GEN_OPEN", "ASYNC_GEN_OPEN",
                        "FN_PARAMS", "ASYNC_PARAMS", "GEN_PARAMS", "ASYNC_GEN_PARAMS", "FIELD_ASSIGN", "STATIC_OPEN"}:
                return False
            if kind != "heritage_clauses":
                continue
            j = i - 1
            while stack[j].type in {"ts_params", "identifier"}:
                j -= 1
            if stack[j].type not in {"CLASS", "DECL_CLASS", "DEFAULT_CLASS"}:
                return False
            exported = self.exported_head(stack, j)
            bare = (i == len(stack) - 2 and previous.type in {"EXTENDS", "IMPLEMENTS"}) or (
                i == len(stack) - 4 and previous.type == "COMMA" and stack[-2].type == "heritage_list")
            # The outer heritage type-argument list also stops before an
            # await that cannot start a type in this declaration context.
            clause = [sym.type for sym in stack[i + 2:]]
            if clause[:2] == ["heritage_list", "COMMA"]:
                clause = clause[2:]
            at_type_argument = clause in (["chain", "TYPE_LT"], ["chain", "TYPE_LT", "ts_type_list", "COMMA"])
            if bare or at_type_argument:
                top_level = not any(sym.type in {"LBRACE", "FN_OPEN", "ASYNC_OPEN", "GEN_OPEN", "ASYNC_GEN_OPEN"}
                                    for sym in stack[:j])
                if exported and top_level and not self.declaration_file:
                    # TS reparses the following await as a separate source-file statement.
                    return ("TYPE_GT", "MISSING_CLASS_BODY") if at_type_argument else ("MISSING_CLASS_BODY",)
                module_await = bare and scope == "module" and top_level and not (self.declaration_file or self.ambient_depth)
                if exported or module_await or scope in {"async", "async generator"}:
                    if at_type_argument:
                        raise self.error(token.lexpos, "expected > in heritage type arguments (TS1005)")
                    raise self.error(token.lexpos, "expression expected in heritage clause (TS1109)")
            elif exported and accepts_lookahead(parser, "AWAIT") and not accepts_lookahead(parser, "RESERVED"):
                token.type = "AWAIT"
                token.await_expression = True
            return False
        else:
            return False
        if accepts_lookahead(parser, "RESERVED"):
            token.type = "RESERVED"
            token.await_property_name = True
        elif accepts_lookahead(parser, "AWAIT"):
            token.type = "AWAIT"
            token.await_expression = True
        return False

    def declaration_decorator_scope(self, stack, end, scope):
        for j in range(end, 0, -1):
            kind = stack[j].type
            if kind in {"FN_OPEN", "GEN_OPEN", "ASYNC_OPEN", "ASYNC_GEN_OPEN", "STATIC_OPEN", "FIELD_ASSIGN",
                        "FN_PARAMS", "GEN_PARAMS", "ASYNC_PARAMS", "ASYNC_GEN_PARAMS", "ARROW_PARAMS", "PARAM_AT",
                        "ARROW", "ASYNC_ARROW"}:
                break
            if kind in {"DECL_CLASS", "DEFAULT_CLASS", "CLASS"} and self.exported_head(stack, j):
                return "async"
            if kind in {"NS", "TS_MODULE", "INTERFACE", "TYPE_ALIAS"}:
                return "ordinary" if scope == "module" else scope
        return scope

    def parameter_decorator_scope(self, parser, current):
        # The parameter list establishes yield/await for bindings. Its
        # decorators instead use the await context outside that list.
        stack = parser.symstack
        for i in range(len(stack) - 1, 0, -1):
            opener = stack[i]
            if opener.type not in {"FN_PARAMS", "GEN_PARAMS", "ASYNC_PARAMS", "ASYNC_GEN_PARAMS",
                                    "ARROW_PARAMS", "SIG_PARAMS", "TS_INDEX_OPEN"}:
                continue
            outer = getattr(opener, "enclosing_scope", current)
            j = i - 1
            while stack[j].type in {"ts_required_params", "identifier", "MULTIPLY"}:
                j -= 1
            if stack[j].type in {"FUNCTION", "DECL_FUNCTION", "DEFAULT_FUNCTION", "MODIFIED_ASYNC_FUNCTION"}:
                if self.exported_head(stack, j):
                    outer = "async"
                elif outer == "module":
                    outer = "ordinary"
            elif outer == "module":
                # Which declarations are reparsed in top-level await context
                # depends on their kind. Async method signatures and type-only
                # declarations by themselves do not trigger that reparse.
                outer = "ordinary" if opener.type in {"ASYNC_PARAMS", "ASYNC_GEN_PARAMS"} else "module"
            outer = self.declaration_decorator_scope(stack, i - 1, outer)
            awaited = outer in {"module", "async", "async parameters", "async generator", "async generator parameters", "static block"}
            generator = current in {"generator", "generator parameters", "async generator", "async generator parameters"}
            if generator:
                return "async generator" if awaited else "generator"
            return "async" if awaited else "ordinary"
        return current

    @staticmethod
    def tuple_label_follows(token, previous, peek):
        # An ellipsis already establishes a tuple element. Without it, the
        # list lookahead must admit the name as the start of a type.
        if not (previous and previous.type == "ELLIPSIS"):
            if token.type == "PRIVATE_NAME":
                return False
            if (token.type not in {"IDENTIFIER", "LET"} and token.value not in STRICT_IDENTIFIERS
                    and token.value not in {"await", "true", "false", "null", "void", "this", "typeof", "new", "function", "import"}):
                return False
        following = peek()
        return bool(following and (following.type == "COLON" or
                    (following.type == "QUESTION" and peek(2) and peek(2).type == "COLON")))

    @staticmethod
    def global_declaration_follows(token):
        return token and (token.type in {"LBRACE", "EXPORT"} or
                          (token.type == "IDENTIFIER" and token.value not in _TS_IDENTIFIER_KEYWORDS))

    @staticmethod
    def in_decorated_declaration(parser):
        for symbol in reversed(parser.symstack):
            if symbol.type in {"DECL_AT", "DEFAULT_AT", "declaration_decorator", "default_decorator"}:
                return True
            if symbol.type in {"module_items", "body", "class_elements"}:
                break
        return False

    def type_declaration_name(self, head, name, scope):
        if name.value == "await" and scope == "module":
            return self.declaration_file or head.lexpos in self.script_context_offsets
        return self.arrow_head_identifier(name, scope)

    def recover_type_declaration_name(self, following, error):
        if self.script_pass is None or following.value not in {"await", "yield"}:
            raise error
        # Complete this provisional declaration so a later export can trigger
        # module replay and expose a diagnostic earlier in the file.
        self.script_pass.record(error)
        following.provisional_type_name = True

    def require_type_declaration_name(self, head, name):
        alias = head.value == "type"
        if alias and (name.lineno if name else self.lexer.lineno) != head.lineno:
            if name is None:
                raise self.error(len(self.source), "line break after type", code=1142, length=0)
            raise self.token_error(name, "line break after type", 1142)
        if name is None:
            end = getattr(head, "end_pos", head.lexpos + len(head.value))
            raise self.error(end, f"identifier expected after {head.value}", code=1003, length=0)
        if not self.type_declaration_name(head, name, getattr(head, "enclosing_scope", None)):
            reserved = name.value in self.keywords or name.value in self.reserved
            code = 1359 if reserved and name.value not in {"await", "yield"} else 1003
            self.recover_type_declaration_name(name, self.token_error(name, f"identifier expected after {head.value}", code))

    def starts_modified_declaration(self, token, peek):
        prefixes = {"abstract", "accessor", "async", "declare", "private", "protected", "public", "readonly", "static"}
        distance = 1
        word = token
        while word.value in prefixes or word.value == "export":
            following = peek(distance)
            if not following or (word.value not in {"static", "export"} and following.lineno != word.lineno):
                return False
            if word.value == "declare" and following.value == "type":
                return True
            if word.value == "export" and following.value in {"=", "*", "{", "as", "default", "@"}:
                return True
            word = following
            distance += 1
        if word.value in {"var", "let", "const", "function", "class", "enum"}:
            return True
        following = peek(distance)
        if not following:
            return False
        if word.value == "import":
            return following.type in {"STRING", "LBRACE", "MULTIPLY", "IDENTIFIER", "RESERVED", "LET"} or following.value in self.keywords
        if word.value == "await":
            return following.value == "using" and self.resource_binding_follows(following, peek(distance + 1))
        if word.value == "using":
            return self.resource_binding_follows(word, following)
        if word.value == "global":
            return self.global_declaration_follows(following)
        if following.lineno != word.lineno:
            return False
        if word.value in {"interface", "type"}:
            return self.type_declaration_name(word, following, getattr(token, "enclosing_scope", None))
        if word.value in {"defer", "namespace", "module"}:
            return (following.type in {"IDENTIFIER", "LET"} or following.value in STRICT_IDENTIFIERS or
                    (word.value in {"namespace", "module"} and following.type == "STRING") or
                    (word.value == "using" and following.type == "LBRACE"))
        return False

    @staticmethod
    def class_prefix_symbols(parser):
        for symbol in reversed(parser.symstack):
            if symbol.type == "async_class_prefix":
                yield from reversed(symbol.value)
            elif symbol.type in {"CLASS_MODIFIER", "CLASS_STATIC", "ASYNC_METHOD", "element_decorator"}:
                yield symbol
            else:
                break

    def check_class_decorator_prefix(self, parser, token, previous):
        if not previous or previous.type != "CLASS_MODIFIER" or not accepts_lookahead(parser, "CLASS_MODIFIER"):
            return
        first = previous
        definite_start = False
        seen_decorator = False
        for symbol in self.class_prefix_symbols(parser):
            if symbol.type == "element_decorator":
                definite_start = seen_decorator = True
            else:
                if seen_decorator:
                    end = previous.lexpos + len(previous.value)
                    raise self.error(end, "declaration expected", code=1146, length=0)
                first = symbol
                if symbol.type == "CLASS_STATIC" or symbol.value in _PARAMETER_PROPERTY_MODIFIERS | {"accessor"}:
                    definite_start = True
        if not definite_start and previous.lineno == token.lineno:
            raise self.token_error(first, "class member expected", 1068)

    def is_property_name_token(self, token):
        return token.type in {"IDENTIFIER", "RESERVED", "PRIVATE_NAME", "JSX_NAME"} or token.value in self.keywords

    @staticmethod
    def binding_identifier(token):
        return token.type in {"IDENTIFIER", "LET"} or token.value in STRICT_IDENTIFIERS or token.value == "await"

    def resource_binding_follows(self, using, binding):
        return binding and binding.lineno == using.lineno and (binding.type == "LBRACE" or self.binding_identifier(binding))

    def check_type_list_start(self, parser, token, previous, peek):
        if previous is None or previous.type not in {"LBRACKET", "TYPE_INDEX", "TYPE_LT", "CALL_TYPE_LT", "JSX_TYPE_LT", "COMMA"}:
            return
        if token.value not in _NON_TYPE_LIST_KEYWORDS and token.value not in _IDENTIFIER_EXCLUDED_SCOPES and token.type != "LPAREN":
            return
        boundary = previous.type
        opening = previous
        if boundary == "COMMA":
            boundary = parser.symstack[-2].type
            if boundary not in {"tuple_members", "ts_type_list"}:
                return
            opening = parser.symstack[-3]
        if token.value in _IDENTIFIER_EXCLUDED_SCOPES:
            if getattr(opening, "type_argument_scope", None) not in _IDENTIFIER_EXCLUDED_SCOPES[token.value]:
                return
        if not accepts_lookahead(parser, "TYPE_OPERATOR"):
            return
        if token.type == "LPAREN":
            distance = 1
            first = peek(distance)
            while first and first.type == "LPAREN":
                distance += 1
                first = peek(distance)
            if not first or first.value not in _NON_TYPE_LIST_KEYWORDS:
                return
            if first.value in _PARAMETER_MODIFIERS or first.value == "const":
                return
        if getattr(opening, "optional_type_arguments", False):
            raise self.token_error(opening, "identifier expected after optional chain", 1003)
        if boundary in {"LBRACKET", "tuple_members"}:
            raise self.token_error(token, "type expected in tuple", 1110)
        expected = "]" if boundary == "TYPE_INDEX" else ">"
        raise self.token_error(token, f"expected '{expected}'", 1005)

    @staticmethod
    def declaration_name_position(parser, previous):
        # ASI may already have terminated the declaration even though
        # 'previous' still refers to the previous source token.
        if previous is None or parser.symstack[-1] is not previous:
            return False
        return previous.type in {"CONST", "VAR", "FOR_LET", "MODIFIED_LET", "USING"} or (
            previous.type == "COMMA" and parser.symstack[-2].type in {"declarators", "declarators_no_in"})

    def declaration_name_error(self, parser, previous, token, *, reserved=False):
        if token.lineno > getattr(previous, "end_line", previous.lineno):
            if accepts_lookahead(parser, "FOR_SEMI"):
                return self.token_error(token, "expected ';' in for statement", 1005)
            if accepts_lookahead(parser, "SEMICOLON", "CASE"):
                return self.token_error(token, "statement expected", 1129)
            if accepts_lookahead(parser, "SEMICOLON"):
                return self.token_error(token, "declaration or statement expected", 1128)
        if reserved:
            return self.token_error(token, "reserved variable name", 1389)
        return self.token_error(token, "variable declaration expected", 1134)

    def missing_identifier_error(self, parser, token, previous):
        """Diagnose a missing binding or operand only when yacc can accept the insertion."""
        if previous and parser.symstack[-1] is previous:
            if previous.type in {"DOT", "OPTIONAL"} and accepts_lookahead(parser, "IDENTIFIER", token.type):
                return self.missing_property_name(previous, token)
            if previous.type == "COLON":
                if accepts_lookahead(parser, "TYPE_OPERATOR"):
                    # A type member may end with an inserted semicolon before }.
                    terminator = "SEMICOLON" if token.type == "RBRACE" else token.type
                    if accepts_lookahead(parser, "IDENTIFIER", terminator):
                        return self.token_error(token, f"{token.value!r} where a type was required", 1110)
                if accepts_lookahead(parser, "IDENTIFIER", token.type):
                    key = parser.symstack[-2].type
                    if key == "object_key":
                        return self.token_error(token, "expression expected", 1109)
                    if key == "property_key":
                        return self.token_error(token, "binding identifier expected", 1003)
            if (token.type in {"RBRACE", "RBRACKET", "RPAREN", "COMMA"}
                    and previous.type in {"ASSIGN", "COMPOUND_ASSIGN", "PLUS", "MINUS", "MULTIPLY", "DIVIDE",
                                          "REMAINDER", "POWER", "RELATION", "EQUALITY", "SHIFT", "AND", "OR",
                                          "COALESCE", "BIT_AND", "BIT_OR", "BIT_XOR", "NOT", "BIT_NOT", "AWAIT"}
                    and accepts_lookahead(parser, "REGEXP") and accepts_lookahead(parser, "IDENTIFIER", token.type)):
                return self.token_error(token, "expression expected", 1109)
        if token.type in {"RBRACE", "RBRACKET", "RPAREN"}:
            return None
        if token.type == "SEMICOLON":
            if (accepts_lookahead(parser, "REGEXP")
                    and not any(accepts_lookahead(parser, kind) for kind in ("EMPTY_SEMI", "FOR_SEMI"))
                    and any(accepts_lookahead(parser, "IDENTIFIER", kind) for kind in ("SEMICOLON", "FOR_SEMI"))):
                return self.token_error(token, "expression expected", 1109)
            return None
        if not accepts_lookahead(parser, "IDENTIFIER", token.type):
            return None
        if self.declaration_name_position(parser, previous):
            return self.declaration_name_error(parser, previous, token)
        entries = parser.goto.get(parser.statestack[-1], {})
        if token.type in {"COLON", "COMMA"} and "property" in entries:
            return self.token_error(token, "property assignment expected", 1136)
        if token.type == "COMMA":
            if "argument" in entries:
                return self.token_error(token, "argument expression expected", 1135)
            if "parameter" in entries:
                return self.token_error(token, "parameter declaration expected", 1138)
        return None

    def recover_missing_identifier(self, token, upcoming, error):
        if self.script_pass is None:
            raise error
        # Only the preliminary script tree may contain this placeholder.
        # Keep the original token for yacc to consume after the identifier.
        self.script_pass.record(error)
        upcoming.appendleft(copy(token))
        token.type, token.value, token.end_pos = "IDENTIFIER", "", token.lexpos
        token.escaped = False
        token.missing_identifier = True

    def resume_jsx_after_missing_brace(self, token, upcoming):
        self.jsx_mode, _ = self.jsx_exprs.pop()
        if self.template_braces and self.template_braces[-1]:
            self.template_braces[-1] -= 1
        # Child text starts at the unexpected token. In an attribute list the
        # erroneous assignment operator is consumed before scanning the next name.
        self.lexer.lexpos = token.lexpos if self.jsx_mode == "text" else getattr(token, "end_pos", token.lexpos + len(token.value))
        self.lexer.lineno = token.lineno
        upcoming.clear()

    def recover_expression_before_equals(self, parser, previous, token, upcoming):
        error = self.token_error(token, "expression expected", 1109)
        if self.script_pass is None:
            raise error
        if accepts_lookahead(parser, "IDENTIFIER", "SEMICOLON"):
            boundary = inserted_token(previous, "SEMICOLON", ";")
        elif (getattr(self, "jsx_exprs", None) and self.jsx_exprs[-1][0] == "text"
              and accepts_lookahead(parser, "IDENTIFIER", "JSX_EXPR_END")):
            # The equals sign and its right operand now belong to JSX text.
            boundary = inserted_token(previous, "JSX_EXPR_END", "}")
            self.resume_jsx_after_missing_brace(token, upcoming)
        elif accepts_lookahead(parser, "IDENTIFIER", "COMMA"):
            boundary = inserted_token(previous, "COMMA", ",")
        else:
            raise error
        self.script_pass.record(error)
        upcoming.appendleft(boundary)
        token.type, token.value, token.end_pos = "IDENTIFIER", "", token.lexpos
        token.escaped = False
        token.missing_identifier = True

    def binding_continuation(self, parser, previous, token, peek, upcoming):
        # Use the state that shifted the name. A qualified type or a spread
        # argument may have the same spelling and uses a different production.
        if (previous is None or parser.symstack[-1] is not previous
                or "binding" not in parser.goto.get(parser.statestack[-2], {})
                or accepts_lookahead(parser, token.type)):
            return
        if token.lineno > previous.lineno and accepts_lookahead(parser, "SEMICOLON", token.type):
            return
        error = self.token_error(token, f"{token.value!r} after binding name", 1005)
        if self.script_pass is None and not isinstance(self, ArrowHeadProbe):
            raise error
        following = peek() if token.type in {"DOT", "OPTIONAL"} else None
        optional_call = token.type == "OPTIONAL" and following is not None and following.type == "LPAREN"
        if (self.script_pass is not None and (token.type in {"LPAREN", "NOT"} or optional_call)
                and accepts_lookahead(parser, "INVALID_BINDING_CHAIN")):
            self.script_pass.record(error)
            # Replay the receiver and its real suffix through the chain grammar.
            upcoming.appendleft(copy(token))
            upcoming.appendleft(copy(previous))
            token.type, token.value, token.end_pos = "INVALID_BINDING_CHAIN", "", token.lexpos
            return
        if (token.type in {"PLUS", "MINUS"} and self.script_pass is not None
                and accepts_lookahead(parser, "ASSIGN", token.type)):
            # Preserve the unary expression for module detection in the provisional tree.
            self.script_pass.record(error)
            upcoming.appendleft(copy(token))
            token.type, token.value, token.end_pos = "ASSIGN", "=", token.lexpos
            return
        if token.type == "LBRACKET" and accepts_lookahead(parser, "COMMA", "BIND_ARRAY"):
            upcoming.appendleft(copy(token))
        elif token.type in {"DOT", "OPTIONAL"}:
            if following is None:
                raise error
            next_kind = following.type
            if self.script_pass is not None:
                if next_kind == "LBRACKET":
                    next_kind = "BIND_ARRAY"
                elif following.value in self.keywords and not self.binding_identifier(following):
                    next_kind = "IDENTIFIER"
            if not accepts_lookahead(parser, "COMMA", next_kind):
                raise error
        else:
            raise error
        if self.script_pass is not None:
            self.script_pass.record(error)
        token.type, token.value, token.end_pos = "COMMA", ",", token.lexpos

    def expression_only_item(self, item):
        if item["type"] in {"RestElement", "SpreadElement"}:
            item = item["argument"]
        if id(item) in self.grouped_patterns:
            return True
        if item["type"] == "AssignmentExpression" and item["operator"] == "=":
            item = item["left"]
        return (id(item) in self.grouped_patterns or
                item["type"] not in {"Identifier", "ThisExpression", "ObjectExpression", "ArrayExpression"})

    def parenthesized_expression_error(self, items, trailing, opening, closing):
        for index, item in enumerate(items):
            if item["type"] == "RestElement":
                offset = self.cover_starts[opening][index]
                return self.error(offset, "expression expected in parentheses", code=1109, length=3)
        if not items or trailing:
            return self.token_error(closing, "expression expected before ')'", 1109)
        return None

    def recover_expression_separator(self, parser, token, previous, upcoming):
        # Check the production that could end here. Type-list closers and
        # class property separators have their own context and diagnostics.
        for terminal, spelling, endings in (
                ("SEMICOLON", ";", {"expression", "optional_expression", "variable_declaration", "lexical_declaration"}),
                ("RPAREN", ")", {"expression"}),
                ("JSX_EXPR_END", "}", {"expression"}),
                ("COMMA", ",", {"assignment", "assignment_no_in", "arguments", "cover_items", "array_element", "properties"}),
                ("COLON", ":", {"assignment"})):
            stack = stack_before_shift(parser, terminal)
            if not stack or stack[-1] not in endings:
                continue
            if terminal == "RPAREN" and (len(stack) < 3 or stack[-2] != "LPAREN" or
                                         stack[-3] not in {"IF", "WHILE", "WITH", "SWITCH"}):
                continue
            line_break = token.lineno > getattr(previous, "end_line", previous.lineno)
            code = 1128 if terminal == "SEMICOLON" and line_break else 1005
            error = self.token_error(token, "separator expected after expression", code)
            if self.script_pass is None:
                raise error
            if terminal == "RPAREN" and stack[-3] == "SWITCH":
                # The missing case block precedes the next recovered statement.
                upcoming.appendleft(inserted_token(previous, "RBRACE", "}"))
                upcoming.appendleft(inserted_token(previous, "LBRACE", "{"))
            if terminal == "JSX_EXPR_END":
                if not getattr(self, "jsx_exprs", None):
                    raise error
                self.resume_jsx_after_missing_brace(token, upcoming)
            if terminal == "COLON":
                # Complete the missing conditional arm before parsing the following statement.
                prefix = ("COLON", "IDENTIFIER")
                if stack_before_shift(parser, "SEMICOLON", prefix=prefix):
                    boundary = inserted_token(previous, "SEMICOLON", ";")
                elif stack_before_shift(parser, "COMMA", prefix=prefix):
                    boundary = inserted_token(previous, "COMMA", ",")
                else:
                    raise error
                upcoming.appendleft(boundary)
                missing = inserted_token(previous, "IDENTIFIER", "")
                missing.missing_identifier = True
                upcoming.appendleft(missing)
            self.script_pass.record(error)
            token.type, token.value = terminal, spelling
            return

    def expression_list_arrow_error(self, parser, previous, token):
        stack = parser.symstack
        if (token.type == "COLON" and stack[-1] is previous and stack[-2].type in {"LPAREN", "COMMA"}
                and accepts_lookahead(parser, "OPTIONAL_PARAM")):
            earlier = stack[-3] if stack[-2].type == "COMMA" else None
            if previous.type == "PRIVATE_NAME" or (earlier and earlier.type in {"cover_items", "arguments"}
                                                   and any(self.expression_only_item(item) for item in earlier.value)):
                return self.token_error(token, "unexpected type annotation in expression", 1005)
        if previous.type in {"JSX_GT", "JSX_SLASH_GT", "JSX_ADJACENT_END"}:
            if token.lineno > getattr(previous, "end_line", previous.lineno) and accepts_lookahead(parser, "SEMICOLON"):
                return self.token_error(token, "declaration or statement expected", 1128)
            return self.token_error(token, "separator expected after JSX expression", 1005)
        if previous.type != "RPAREN" or len(stack) < 4:
            return None
        i = -2
        trailing = stack[i].type == "COMMA"
        if trailing:
            i -= 1
        if stack[i].type == "cover_items" and stack[i-1].type == "LPAREN":
            items = stack[i].value
            if not any(self.expression_only_item(item) for item in items):
                return None
            list_error = self.parenthesized_expression_error(items, trailing, stack[i-1].lexpos, previous)
        elif ((stack[i].type == "arguments" and stack[i-1].type == "LPAREN")
              or (stack[i].type == "LPAREN" and stack[i-1].type in {"member", "call", "optional_chain", "optional_base"})):
            # A confirmed async arrow uses async_formals. These tokens have
            # completed a call expression, including calls with spread arguments.
            list_error = None
        else:
            return None
        if token.type == "COLON" and accepts_lookahead(parser, "COLON"):
            # The colon belongs to the surrounding conditional or case clause.
            token.expression_separator = True
        if list_error:
            return list_error
        if getattr(token, "expression_separator", False):
            return None
        if token.lineno > previous.lineno and accepts_lookahead(parser, "SEMICOLON"):
            return self.token_error(token, "declaration or statement expected", 1128)
        return self.token_error(token, "separator expected after expression", 1005)

    def dialect_token(self, parser, token, previous, peek, upcoming):
        self.source_lookahead = token
        if previous and token.type in {"COMMA", "RPAREN"}:
            token.previous_end = getattr(previous, "end_pos", previous.lexpos + len(previous.value))
        if previous and token.type in {"ARROW", "ASYNC_ARROW"}:
            token.after_line_break = token.lineno > getattr(previous, "end_line", previous.lineno)
        if (previous and previous.type == "SUPER" and not accepts_lookahead(parser, token.type)
                and accepts_lookahead(parser, "MISSING_SUPER_MEMBER")):
            if token.type == "RELATION" and token.value == "<" and self.can_start_type_arguments(token):
                token.type, token.type_argument_scope = "CALL_TYPE_LT", token.enclosing_scope
                token.optional_type_arguments = False
                return
            error = self.token_error(token, "expected an argument list or member access after super", 1034)
            if self.script_pass is None:
                raise error
            self.script_pass.record(error)
            upcoming.appendleft(copy(token))
            token.type = "DOT" if accepts_lookahead(parser, "DOT", token.type) else "MISSING_SUPER_MEMBER"
            token.value, token.end_pos = "", token.lexpos
            return
        if (previous and previous.type in {"RELATION", "DIVIDE", "PLUS", "MINUS", "MULTIPLY", "REMAINDER",
                                          "POWER", "EQUALITY", "SHIFT", "BIT_AND", "BIT_OR", "BIT_XOR", "AND", "OR", "COALESCE"}
                and (token.value.startswith(">") or token.type == "EQUALITY")
                and not accepts_lookahead(parser, token.type) and accepts_lookahead(parser, "REGEXP")):
            # The reference scanner rescans '>' only when consuming an operator.
            # At a missing operand the diagnostic still covers one greater-than.
            length = 1 if token.value.startswith(">") else len(token.value)
            error = self.error(token.lexpos, "expression expected", code=1109, length=length)
            self.recover_missing_identifier(token, upcoming, error)
            return
        if (token.type == "OPTIONAL" and not accepts_lookahead(parser, "OPTIONAL")
                and accepts_lookahead(parser, "MISSING_NEW_ARGS")):
            error = self.token_error(token, "invalid optional chain directly after a constructor", 1209)
            if self.script_pass is None:
                raise error
            self.script_pass.record(error)
            upcoming.appendleft(copy(token))
            token.type, token.value, token.end_pos = "MISSING_NEW_ARGS", "", token.lexpos
            return
        if previous and previous.type == "IDENTIFIER" and token.type in {"DOT", "OPTIONAL", "LPAREN", "LBRACKET", "PLUS", "MINUS"}:
            self.binding_continuation(parser, previous, token, peek, upcoming)
        if (previous and previous.type == "NEW" and token.type in {"RELATION", "SHIFT", "SEMICOLON", "COMMA", "RPAREN", "RBRACKET", "RBRACE"}
                and accepts_lookahead(parser, "REGEXP") and not accepts_lookahead(parser, token.type)):
            # In a new expression the constructor must be a member expression.
            # Constructor signatures and methods named new use different yacc states.
            self.recover_missing_identifier(token, upcoming, self.token_error(token, "constructor expression expected", 1109))
            return
        if previous and ((previous.type == "RPAREN" and token.type in {"ARROW", "COLON"})
                         or (token.type == "ARROW" and previous.type in {"JSX_GT", "JSX_SLASH_GT", "JSX_ADJACENT_END"})
                         or (token.type == "COLON" and previous.type in {"IDENTIFIER", "PRIVATE_NAME", "THIS", "RESERVED"})):
            error = self.expression_list_arrow_error(parser, previous, token)
            if error:
                if self.script_pass is None:
                    raise error
                if getattr(token, "expression_separator", False):
                    self.script_pass.record(error)
                    return
                for boundary, value in (("SEMICOLON", ";"), ("COMMA", ",")):
                    if accepts_lookahead(parser, boundary):
                        self.script_pass.record(error)
                        token.type, token.value = boundary, value
                        return
                raise error
        if previous and token.type in {"SEMICOLON", "LBRACE", "RBRACE"} and not accepts_lookahead(parser, token.type):
            kind = self.missing_arrow_kind(parser)
            if kind:
                error = self.token_error(token, "expected '=>' after arrow parameters", 1005)
                if self.script_pass is None:
                    raise error
                self.script_pass.record(error)
                upcoming.appendleft(copy(token))
                if token.type != "LBRACE":
                    missing = inserted_token(previous, "IDENTIFIER", "")
                    missing.escaped = False
                    missing.missing_identifier = True
                    upcoming.appendleft(missing)
                token.type, token.value, token.end_pos = kind, "=>", token.lexpos
                return
        if (previous and (self.is_property_name_token(token) or token.type in {"NUMBER", "STRING", "LBRACKET"})
                and not accepts_lookahead(parser, token.type) and accepts_lookahead(parser, "FN_PARAMS")
                and accepts_lookahead(parser, "COLON", "REGEXP") and accepts_lookahead(parser, "COMMA", token.type)):
            # A property name can now start another member. get/set prefixes
            # have their own terminal and already accept their property key.
            error = self.token_error(token, "separator expected after object property name", 1005)
            if self.script_pass is None:
                raise error
            self.script_pass.record(error)
            upcoming.appendleft(copy(token))
            token.type, token.value, token.end_pos = "COMMA", ",", token.lexpos
            return
        if (previous and token.type in {"IDENTIFIER", "RESERVED", "NUMBER", "PRIVATE_NAME"}
                and (previous.type in {"NUMBER", "PRIVATE_NAME"} or (
                    previous.type in {"STRING", "MODULE_STRING"} and token.type == "PRIVATE_NAME"))):
            contextual = {"as": "TS_AS", "satisfies": "SATISFIES", "of": "OF", "in": "IN", "instanceof": "INSTANCEOF"}
            operator = contextual.get(token.value)
            if operator and accepts_lookahead(parser, operator):
                if getattr(token, "escaped", False):
                    raise self.token_error(token, "escape in operator", 1260)
            elif not accepts_lookahead(parser, token.type) and not accepts_lookahead(parser, "FIELD_TERMINATOR_ERROR"):
                for boundary, spelling in (("SEMICOLON", ";"), ("FOR_SEMI", ";"), ("COMMA", ",")):
                    if accepts_lookahead(parser, boundary, token.type):
                        if boundary == "SEMICOLON" and token.lineno > previous.lineno:
                            break  # The ordinary ASI pass will terminate this statement.
                        error = self.token_error(token, "separator expected before the next token", 1005)
                        if self.script_pass is None:
                            raise error
                        self.script_pass.record(error)
                        upcoming.appendleft(copy(token))
                        token.type, token.value, token.end_pos = boundary, spelling, token.lexpos
                        return
        if (self.script_pass is not None and previous is not None and
                ((token.type in {"EXPORT", "IMPORT"} and getattr(token, "statement_identifier", None) is previous)
                 or (token.type == "LBRACE" and previous.type == "IDENTIFIER"
                     # A module replay may consume this block as an await
                     # operand, changing the boundary of the next statement.
                     and previous.value not in {"declare", "await"} and previous.lineno == token.lineno and parser.symstack[-1] is previous
                     and parser.symstack[-2].type in {"body", "module_items"}))
                and not accepts_lookahead(parser, token.type) and accepts_lookahead(parser, "SEMICOLON", token.type)):
            end = getattr(previous, "end_pos", previous.lexpos + len(previous.value))
            self.script_pass.record(self.missing_semicolon_after_name(previous.value, previous.lexpos, end, token))
            upcoming.appendleft(copy(token))
            token.type, token.value, token.end_pos = "SEMICOLON", ";", token.lexpos
            return
        if previous and previous.type in {"INCREMENT", "DECREMENT"} and parser.symstack[-1] is previous:
            scope = getattr(token, "enclosing_scope", None)
            excluded_name = (scope in _IDENTIFIER_EXCLUDED_SCOPES.get(token.value, ())
                             or (token.value == "await" and scope == "module" and not self.declaration_file
                                 and not getattr(token, "script_await", False)))
            if excluded_name or token.type in {"PLUS", "MINUS", "NOT", "BIT_NOT", "DELETE", "TYPEOF", "VOID",
                                               "INCREMENT", "DECREMENT"} or token.value == "<":
                error = self.token_error(token, "expression expected after prefix update", 1109)
                if self.script_pass is None:
                    raise error
                if excluded_name:
                    self.script_pass.record(error)
                    token.type, token.escaped = "IDENTIFIER", False
                    token.recovered_binding = True
                elif accepts_lookahead(parser, "IDENTIFIER", token.type):
                    self.recover_missing_identifier(token, upcoming, error)
                else:
                    raise error
                return
        if (token.type in {"INCREMENT", "DECREMENT"} and previous
                and token.lineno == getattr(previous, "end_line", previous.lineno)
                and not accepts_lookahead(parser, token.type) and not accepts_lookahead(parser, "POST_" + token.type)):
            for boundary, spelling in (("SEMICOLON", ";"), ("COMMA", ",")):
                if accepts_lookahead(parser, boundary, token.type):
                    error = self.token_error(token, "separator expected before update operator", 1005)
                    if self.script_pass is None:
                        raise error
                    self.script_pass.record(error)
                    upcoming.appendleft(copy(token))
                    token.type, token.value, token.end_pos = boundary, spelling, token.lexpos
                    return
            if accepts_lookahead(parser, "RPAREN"):
                raise self.token_error(token, "expected ')' before update operator", 1005)
        if (token.type == "POWER" and previous and not accepts_lookahead(parser, "POWER")
                and accepts_lookahead(parser, "UNARY_POWER_ERROR")):
            token.type = "UNARY_POWER_ERROR"
            token.operand_end = getattr(previous, "end_pos", previous.lexpos + len(previous.value))
            return
        if (self.script_pass is not None and getattr(previous, "unterminated_regexp", False)
                and token.type in {"RPAREN", "RBRACKET"} and not accepts_lookahead(parser, token.type)
                and accepts_lookahead(parser, "SEMICOLON") and not accepts_lookahead(parser, "SEMICOLON", token.type)):
            # The scanner retained this unmatched bracket for error recovery.
            # Finish the already rejected statement so later module items can be read.
            token.type, token.value = "SEMICOLON", ";"
            return
        if (token.type == "ASSIGN" and previous and previous.type in {
                "TYPE_GT", "IN", "INSTANCEOF", "PLUS", "MINUS", "MULTIPLY", "DIVIDE", "REMAINDER",
                "POWER", "EQUALITY", "RELATION", "SHIFT", "BIT_AND", "BIT_OR", "BIT_XOR", "AND", "OR", "COALESCE"}
                and accepts_lookahead(parser, "REGEXP") and not accepts_lookahead(parser, "ASSIGN")):
            self.recover_expression_before_equals(parser, previous, token, upcoming)
            return
        if (previous and previous.type in {"EXTENDS", "EXPRESSION_EXTENDS", "ASSIGN"}
                and (token.value.startswith(">") or token.type in {"COMMA", "ASSIGN"})
                and not accepts_lookahead(parser, token.type)):
            error = self.type_parameter_value_error(parser, token)
            terminator = "TYPE_GT" if token.value.startswith(">") else token.type
            if error and accepts_lookahead(parser, "IDENTIFIER", terminator):
                self.recover_missing_identifier(token, upcoming, error)
                return
        if (previous and previous.type == "TYPE_GT" and token.type in {"RBRACE", "COMMA"}
                and not accepts_lookahead(parser, token.type) and accepts_lookahead(parser, "FN_PARAMS", "RPAREN")):
            error = self.token_error(token, "expected '(' after method type parameters", 1005)
            if self.script_pass is None:
                raise error
            self.script_pass.record(error)
            upcoming.appendleft(copy(token))
            upcoming.appendleft(inserted_token(previous, "SEMICOLON", ";"))
            upcoming.appendleft(inserted_token(previous, "RPAREN", ")"))
            token.type, token.value, token.end_pos = "FN_PARAMS", "(", token.lexpos
            return
        if (self.script_pass is not None and token.type in {"NUMBER", "STRING", "COMMA", "DIVIDE"}
                and previous and previous.type in {"PARAM_LT", "COMMA", "TYPE_PARAM_MODIFIER"}
                and not accepts_lookahead(parser, token.type)):
            error = self.type_parameter_list_error(parser, token)
            if error and token.type == "COMMA" and accepts_lookahead(parser, "IDENTIFIER", "COMMA"):
                self.recover_missing_identifier(token, upcoming, error)
                return
            following = peek() if error else None
            skip_slash = token.type == "DIVIDE" and following and following.type == "IDENTIFIER"
            if following and (skip_slash or following.type == "COMMA" or following.value.startswith(">")):
                if skip_slash:
                    upcoming.appendleft(inserted_token(previous, "COMMA", ","))
                # Preserve the rest of the parameter list only for module detection.
                self.script_pass.record(error)
                token.type, token.value = "IDENTIFIER", ""
                token.escaped = False
                token.missing_identifier = True
                return
        if getattr(token, "provisional_type_statement", False):
            return
        if getattr(token, "provisional_type_name", False):
            token.type = "IDENTIFIER"
            return
        if getattr(token, "recovered_binding", False):
            return
        if token.type in {"ASSIGN", "COLON", "COMMA", "SEMICOLON", "RBRACE", "RBRACKET", "RPAREN"} and not accepts_lookahead(parser, token.type):
            error = self.missing_identifier_error(parser, token, previous)
            if error is not None:
                self.recover_missing_identifier(token, upcoming, error)
                return
        if previous and previous.type in {"TEMPLATE_HEAD", "TEMPLATE_MIDDLE", "UNTAGGED_TEMPLATE_HEAD", "UNTAGGED_TEMPLATE_MIDDLE"}:
            token.expects_substitution_type = accepts_lookahead(parser, "TYPE_OPERATOR")
        if hasattr(token, "unterminated_error"):
            if hasattr(token, "expects_substitution_type"):
                raise self.missing_substitution(token)
            if hasattr(token, "invalid_escape") and accepts_lookahead(parser, "UNTAGGED_TEMPLATE_TAIL"):
                raise token.invalid_escape
            raise token.unterminated_error
        if self.has_jsdoc_parameters and (self.in_jsdoc_parameter_type(parser) or accepts_lookahead(parser, "DOC_NAMEPATH")):
            peek = self.jsdoc_lookahead(token, peek)
        if previous and previous.type in {"CLASS_STATIC", "CLASS_MODIFIER"} and token.type in {"VAR", "LET", "CONST"}:
            following = peek()
            if following and following.lineno == token.lineno:
                following.statement_identifier = token
        if previous and previous.type in {"DOT", "OPTIONAL", "JSX_DOT"} and token.lineno > previous.lineno:
            # The TS parser diagnoses a missing name at the dot when two names
            # on the next line could instead start a new statement.
            receiver = parser.symstack[-2].type
            if (receiver not in {"IMPORT", "NEW", "namespace_name", "import_type_base"} and self.is_property_name_token(token)
                    and not (token.type == "JSX_NAME" and "-" in token.value)):
                following = peek()
                if following and following.lineno == token.lineno and self.is_property_name_token(following):
                    raise self.error(previous.lexpos + len(previous.value), "identifier expected after dot (TS1003)")
        if token.type == "RBRACKET" and previous and previous.type == "LBRACKET":
            if parser.symstack[-2].type in {"member", "call", "SUPER", "optional_base", "optional_chain", "decorator_optional_base"}:
                raise self.error(previous.lexpos + 1, "element access requires an argument (TS1011)")
        # Select formal parameters directly for definite heads. Ambiguous
        # expressions need the probe even inside enclosing generators.
        if (token.type == "LPAREN" and accepts_lookahead(parser, "ARROW_PARAMS")
                and self.parenthesized_arrow_head(token, peek, 1, parser, ordinary=True)):
            token.type = "ARROW_PARAMS"
        if (previous and previous.type in {"PARAM_AT", "AT", "DECL_AT", "DEFAULT_AT", "EXPR_AT"}
                and token.type in {"AWAIT", "IDENTIFIER", "RESERVED"} and token.value == "await"
                and previous.decorator_scope in {"module", "async", "async parameters", "async generator", "async generator parameters", "static block"}):
            raise self.error(token.lexpos, "await as decorator in await context")
        if previous and previous.type == "ASYNC_SINGLE" and token.value in {"await", "yield"}:
            token.type = "IDENTIFIER"
            return
        if token.type == "LBRACE" and token.lexpos in self.script_context_offsets:
            token.contents_scope = "ordinary"
        if token.type == "LBRACE" and accepts_lookahead(parser, "ENUM_OPEN"):
            token.type = "ENUM_OPEN"
        if token.type == "SUPER" and previous and accepts_lookahead(parser, "SUPER_VALUE"):
            if previous.type == "NEW":
                token.type = "SUPER_VALUE"
            elif previous.type in {"AT", "PARAM_AT", "DECL_AT", "EXPR_AT", "DEFAULT_AT"}:
                following = peek()
                if following and following.type == "LBRACKET":
                    # The bracket starts the decorated name or binding pattern.
                    token.type = "SUPER_VALUE"
        if token.type == "THROW" and accepts_lookahead(parser, "BARE_THROW"):
            following = peek()
            next_line = following.lineno if following else self.lexer.lineno
            if next_line > token.lineno:
                token.type = "BARE_THROW"
            elif following is None:
                raise self.error(token.lexpos + len(token.value), "expression expected after throw", code=1109, length=0)
            elif following.type in {"RBRACE", "RPAREN", "RBRACKET", "COMMA"}:
                raise self.token_error(following, "expression expected after throw", 1109)
        if token.type == "ASSIGN" and accepts_lookahead(parser, "FIELD_ASSIGN"):
            token.type = "FIELD_ASSIGN"
        if token.type == "STRING" and accepts_lookahead(parser, "MODULE_STRING"):
            token.type = "MODULE_STRING"
        if previous and previous.value in ("(", ",", "["):
            previous.item_start = token.lexpos
            previous.item_end = getattr(token, "end_pos", token.lexpos + len(token.value))
        if (token.type == "PRIVATE_NAME" and not accepts_lookahead(parser, token.type)
                and accepts_lookahead(parser, "BIND_ARRAY")):
            # A private property key is valid before a destructuring colon.
            # Once yacc expects a binding, its enclosing production determines the error.
            if accepts_lookahead(parser, "THIS"):
                error = self.token_error(token, "private identifier used as a parameter", 18009)
            elif previous and previous.type == "LET" and parser.symstack[-2].type in {"body", "module_items"}:
                if token.lineno > previous.lineno:
                    return  # ASI can leave let and the private name as separate expressions.
                error = self.missing_semicolon_after_name("let", previous.lexpos, previous.lexpos + 3, token)
            else:
                boundary = next((symbol.type for symbol in reversed(parser.symstack)
                                 if symbol.type in {"BIND_ARRAY", "BIND_OBJECT", "body", "module_items", "CATCH"}), None)
                nested = boundary in {"BIND_ARRAY", "BIND_OBJECT"}
                error = self.token_error(token, "private identifier used as a binding", 18016 if nested else 18029)
            if self.script_pass is not None:
                self.script_pass.record(error)
            elif error.code != 18016 or not isinstance(self, ArrowHeadProbe):
                raise error
            # In a speculative formal list, a binding pattern already starts
            # a parameter. Its invalid inner binding does not cancel the probe.
            token.type, token.value = "IDENTIFIER", "#" + token.value
            token.recovered_binding = True
            return
        if previous and previous.type == "CLASS_ACCESSOR":
            previous.name_on_same_line = token.lineno == previous.lineno
        if previous and previous.type == "ASSIGN":
            previous.initializer_start = token.lexpos
        if previous and previous.type == "DELETE":
            previous.operand_offset = token.lexpos
        if token.type == "RESERVED" and token.value in STRICT_IDENTIFIERS and token.value != "yield":
            token.type = "IDENTIFIER"
        same_line = previous is None or token.lineno == getattr(previous, "end_line", previous.lineno)
        if token.type in {"ASSIGN", "NOT"}:
            token.after_line_break = not same_line
        if self.classify_jsdoc_token(parser, token, previous, peek, upcoming, same_line):
            return
        if token.type == "FUNCTION" and accepts_lookahead(parser, "MODIFIED_ASYNC_FUNCTION"):
            for sym in reversed(parser.symstack):
                if sym.type == "DECL_MODIFIER" and sym.value == "async":
                    token.type = "MODIFIED_ASYNC_FUNCTION"
                    return
                if sym.type not in {"DECL_MODIFIER", "DECLARE", "ambient_scope", "EXPORT", "declaration_decorator", "default_decorator", "decorator_expr", "DECL_AT", "DEFAULT_AT"}:
                    break
        if token.type == "LET" and accepts_lookahead(parser, "MODIFIED_LET") and not accepts_lookahead(parser, "IDENTIFIER"):
            if not peek() or peek().type in {"SEMICOLON", "RBRACE"}:
                token.type = "MODIFIED_LET"
                return
        if token.value == "defer" and previous and previous.type in {"DECLARE", "DECL_MODIFIER"}:
            # Declaration lookahead commits to the modifier list before the parser
            # discovers that defer cannot introduce this declaration.
            raise self.error(getattr(previous, "end_pos", previous.lexpos + len(previous.value)),
                             "declaration expected", code=1146, length=0)
        if (token.type in {"IDENTIFIER", "RESERVED", "EXPORT", "IN"}
                and token.value in {"abstract", "accessor", "async", "declare", "private", "protected", "public",
                                    "readonly", "static", "export", "in", "out"}
                and accepts_lookahead(parser, "DECL_MODIFIER") and (
                    self.starts_modified_declaration(token, peek)
                    or (not accepts_lookahead(parser, "IDENTIFIER") and self.in_decorated_declaration(parser)
                        and self.member_modifier_follows(token.value, token, peek))
                )):
            if getattr(token, "escaped", False):
                raise self.token_error(token, "escape in declaration modifier", 1260)
            if token.value == "declare":
                token.type = "DECLARE"
            elif token.value == "export":
                if peek().value != "export":
                    return
                token.type = "DECL_MODIFIER"
            elif token.value == "abstract" and peek().value == "class":
                token.type = "ABSTRACT"
            else:
                token.type = "DECL_MODIFIER"
            return
        if (token.value == "export" and getattr(token, "escaped", False) and accepts_lookahead(parser, "EMPTY_SEMI")
                and accepts_lookahead(parser, "DECL_MODIFIER")):
            if accepts_lookahead(parser, "CASE"):
                raise self.token_error(token, "case or default expected", 1129)
            if accepts_lookahead(parser, "RBRACE") or accepts_lookahead(parser, "$end"):
                raise self.token_error(token, "declaration or statement expected", 1128)
            raise self.token_error(token, "expression expected", 1109)
        if (token.type == "IDENTIFIER" and token.value in {"accessor", "public", "private", "protected", "static", "readonly"}
                and accepts_lookahead(parser, "EMPTY_SEMI") and accepts_lookahead(parser, "DECL_MODIFIER")):
            following = peek()
            if following and following.lineno == token.lineno:
                name_follows = self.is_property_name_token(following)
                if name_follows and (accepts_lookahead(parser, "RBRACE") or accepts_lookahead(parser, "$end")):
                    if accepts_lookahead(parser, "CASE"):
                        raise self.token_error(token, "case or default expected", 1129)
                    raise self.token_error(token, "declaration or statement expected", 1128)
                if ((name_follows and following.value not in {"as", "satisfies", "in", "instanceof"})
                        or following.type in {"STRING", "NUMBER"}):
                    raise self.token_error(token, "keyword or identifier", 1434)
        if token.value == "let" and getattr(token, "escaped", False):
            declaration_only = accepts_lookahead(parser, "MODIFIED_LET") and not accepts_lookahead(parser, "IDENTIFIER")
            if declaration_only or accepts_lookahead(parser, "FOR_LET"):
                raise self.token_error(token, "escape in let declaration", 1260)
            if accepts_lookahead(parser, "BARE_THROW"):
                following = peek()
                binding = following and (following.type in {"LBRACE", "LBRACKET"} or self.binding_identifier(following))
                if binding:
                    raise self.token_error(token, "escape in let declaration", 1260)
        if token.type == "LET" and accepts_lookahead(parser, "FOR_LET"):
            token.type = "FOR_LET"
            return
        if (token.type == "IDENTIFIER" and token.value == "of" and previous
                and previous.type in {"VAR", "CONST", "FOR_LET", "USING"} and accepts_lookahead(parser, "OF")
                and self.can_follow_declaration_of(token, peek)):
            if token.escaped:
                raise self.token_error(token, "escape in for-of keyword", 1260)
            token.type = "OF"
            return
        # A reserved keyword can start the module expression without an import
        # clause. Parentheses immediately after import instead start a call.
        if token.type == "IMPORT" and accepts_lookahead(parser, "SOURCE_IMPORT"):
            following = peek()
            if following and following.value in self.keywords and following.value != "let":
                token.type = "SOURCE_IMPORT"
                return
        if (token.type == "IMPORT" and (previous is None or previous.type != "NEW") and peek()
                and peek().value == "<" and accepts_lookahead(parser, "IMPORT_VALUE")):
            token.type = "IMPORT_VALUE"
            return
        if token.type == "DOT" and accepts_lookahead(parser, "TYPE_ARGUMENT_DOT"):
            following = peek()
            if following and following.value == "<" and following.lineno == token.lineno:
                token.type = "TYPE_ARGUMENT_DOT"
                return
        self.check_type_list_start(parser, token, previous, peek)
        if token.type == "PRIVATE_NAME" and previous:
            # The compiler's isStartOfType skips a private identifier in tuple,
            # index and argument lists, but parseType accepts it in required types.
            token.after_type_list_delimiter = previous.type in {"TYPE_LT", "CALL_TYPE_LT", "TYPE_INDEX", "LBRACKET", "COMMA"}
        if (token.type == "LBRACE" and previous and previous.type in {"EXTENDS", "IMPLEMENTS", "COMMA"}
                and accepts_lookahead(parser, "LBRACE") and accepts_lookahead(parser, "OBJECT_OPEN")):
            first = peek()
            if first and (first.type != "RBRACE" or (peek(2) and peek(2).value in {",", "{", "extends", "implements"})):
                token.type = "OBJECT_OPEN"
                return
        if (token.type in {"WITH", "IDENTIFIER", "RESERVED"} and token.value in {"with", "assert"}
                and not getattr(token, "escaped", False)
                and accepts_lookahead(parser, "ATTRIBUTE_KEYWORD") and (same_line or previous.type == "LBRACE")):
            token.type = "ATTRIBUTE_KEYWORD"
            return
        if token.type == "IDENTIFIER" and token.value == "async" and not token.escaped:
            if accepts_lookahead(parser, "ASYNC_ARROW_HEAD"):
                opening = peek()
                if (opening and opening.value in {"<", "("} and opening.lineno == token.lineno
                        and (self.parenthesized_arrow_head(token, peek, 2, parser) if opening.type == "LPAREN"
                             else self.has_arrow_head(opening, parser))):
                    token.type = "ASYNC_ARROW_HEAD"
                    return
        if (token.type in {"AWAIT", "RESERVED", "IDENTIFIER"} and token.value == "await" and previous and previous.type == "FOR"
                and accepts_lookahead(parser, "AWAIT")):
            if getattr(token, "escaped", False):
                raise self.token_error(token, "escape in for-await keyword", 1260)
            token.type = "AWAIT"
            return
        if token.value == "await" and token.type in {"AWAIT", "IDENTIFIER", "RESERVED"} and accepts_lookahead(parser, "AWAIT_USING"):
            using = peek()
            if using and using.value == "using" and self.resource_binding_follows(using, peek(2)):
                if getattr(token, "escaped", False):
                    raise self.token_error(token, "escape in await using declaration", 1260)
                token.type = "AWAIT_USING"
                return
        if token.type == "IDENTIFIER" and token.value == "using" and accepts_lookahead(parser, "USING"):
            binding = peek()
            decorated = not accepts_lookahead(parser, "IDENTIFIER") and self.in_decorated_declaration(parser)
            if decorated or self.resource_binding_follows(token, binding):
                if (decorated or binding.value != "of" or (previous and previous.type == "AWAIT_USING") or not accepts_lookahead(parser, "FOR_SEMI")
                        or (peek(2) and peek(2).type in {"ASSIGN", "COLON", "SEMICOLON"})):
                    if token.escaped:
                        raise self.token_error(token, "escape in using declaration", 1260)
                    token.type = "USING"
                    return
        if (token.type in {"IDENTIFIER", "RESERVED"} and token.value == "interface"
                and not getattr(token, "escaped", False) and accepts_lookahead(parser, "DEFAULT_INTERFACE")):
            self.require_type_declaration_name(token, peek())
            token.type = "DEFAULT_INTERFACE"
            return
        if token.type == "EXTENDS" and accepts_lookahead(parser, "INFER_EXTENDS"):
            if not accepts_lookahead(parser, "CONDITIONAL_EXTENDS") or self.has_infer_bound(token):
                token.type = "INFER_EXTENDS"
                return
        if token.type == "ARROW" and accepts_lookahead(parser, "TYPE_ARROW"):
            token.type = "TYPE_ARROW"
            return
        if (token.type == "EXTENDS" and accepts_lookahead(parser, "EXPRESSION_EXTENDS")
                and self.expression_constraint_follows(token.enclosing_scope, peek)):
            if peek().value == "yield":
                raise self.error(peek().lexpos, "expected unary expression in type parameter constraint")
            token.type = "EXPRESSION_EXTENDS"
            return
        if token.type == "EXTENDS" and same_line and accepts_lookahead(parser, "CONDITIONAL_EXTENDS"):
            token.type = "CONDITIONAL_EXTENDS"
            return
        if token.type == "IDENTIFIER" and token.value == "intrinsic" and accepts_lookahead(parser, "INTRINSIC_ALIAS"):
            if not peek() or peek().type != "DOT":
                if token.escaped:
                    raise self.token_error(token, "escaped intrinsic keyword", 1260)
                token.type = "INTRINSIC_ALIAS"
                return
        if (token.type in {"IDENTIFIER", "LET", "RESERVED", "AWAIT", "YIELD", "BARE_YIELD", "PRIVATE_NAME"}
                or token.value in self.keywords) and accepts_lookahead(parser, "TUPLE_LABEL"):
            if self.tuple_label_follows(token, previous, peek):
                if token.type == "PRIVATE_NAME":
                    token.value = "#" + token.value
                token.type = "TUPLE_LABEL"
                return
        if token.type == "AT":
            self.check_class_decorator_prefix(parser, token, previous)
            token.decorator_scope = self.declaration_decorator_scope(parser.symstack, len(parser.symstack)-1, token.enclosing_scope)
            if accepts_lookahead(parser, "PARAM_AT"):
                if previous and previous.type == "PARAM_MODIFIER":
                    seen_decorator = False
                    for symbol in reversed(parser.symstack):
                        if symbol.type == "parameter_decorator":
                            seen_decorator = True
                        elif symbol.type != "PARAM_MODIFIER":
                            break
                        elif seen_decorator:
                            raise self.token_error(token, "identifier expected after parameter modifiers", 1003)
                token.decorator_scope = self.parameter_decorator_scope(parser, token.enclosing_scope)
                token.type = "PARAM_AT"
            elif accepts_lookahead(parser, "DEFAULT_AT"):
                token.type = "DEFAULT_AT"
            elif accepts_lookahead(parser, "DECL_AT"):
                token.type = "DECL_AT"
            elif not accepts_lookahead(parser, "AT") and accepts_lookahead(parser, "EXPR_AT"):
                token.type = "EXPR_AT"
        if (token.type != "PRIVATE_NAME" and token.value in _PARAMETER_MODIFIERS | {"const"}
                and accepts_lookahead(parser, "TYPE_PARAM_MODIFIER")
                and self.type_parameter_modifier(parser, token, previous, peek)):
            if getattr(token, "escaped", False):
                raise self.error(token.lexpos, "escaped type parameter modifier")
            token.type = "TYPE_PARAM_MODIFIER"
            return
        if (token.type in {"EXPORT", "DEFAULT", "RESERVED"} and token.value in {"export", "default"}
                and accepts_lookahead(parser, "OBJECT_DECORATED_MODIFIER")
                and peek() and peek().type == "AT"):
            if getattr(token, "escaped", False):
                raise self.error(token.lexpos, "escaped object member modifier")
            token.type = "OBJECT_DECORATED_MODIFIER"
            return
        if (token.type in {"IDENTIFIER", "ASYNC_HEAD"} and token.value == "async" and accepts_lookahead(parser, "OBJECT_ASYNC")
                and self.member_modifier_follows("async", token, peek)):
            if getattr(token, "escaped", False):
                raise self.error(token.lexpos, "escaped object member modifier")
            token.type = "OBJECT_ASYNC"
            return
        if token.type in {"IDENTIFIER", "RESERVED", "CLASS_STATIC"} and token.value == "static" and accepts_lookahead(parser, "TS_STATIC_BLOCK"):
            following = peek()
            if following and following.type == "LBRACE":
                if getattr(token, "escaped", False):
                    raise self.token_error(token, "escape in static block keyword", 1260)
                token.type = "TS_STATIC_BLOCK"
                return
        if token.type in {"IDENTIFIER", "RESERVED", "CLASS_STATIC", "CLASS_ACCESSOR"} and token.value in {"static", "get", "set"}:
            modifier = "CLASS_STATIC" if token.value == "static" else "CLASS_ACCESSOR"
            if accepts_lookahead(parser, modifier):
                following = peek()
                name_follows = following and (self.is_property_name_token(following)
                                               or following.type in {"NUMBER", "STRING", "LBRACKET"})
                static_prefix = following and modifier == "CLASS_STATIC" and following.type in {"MULTIPLY", "LBRACE"}
                if modifier == "CLASS_STATIC" and any(s.type == "CLASS_STATIC" for s in self.class_prefix_symbols(parser)):
                    token.type = "IDENTIFIER"
                    return
                if name_follows or static_prefix:
                    if getattr(token, "escaped", False):
                        raise self.token_error(token, "escape in class member keyword", 1260)
                    token.type = modifier
                    return
                if token.type == modifier:
                    token.type = "IDENTIFIER"
        if (getattr(token, "escaped", False) and token.value in _PARAMETER_MODIFIERS - {"static", "default", "export"}
                and accepts_lookahead(parser, "CLASS_MODIFIER")):
            following = peek()
            required = (following and following.type == "LBRACE" and following.lineno == token.lineno
                        and token.value in _PARAMETER_PROPERTY_MODIFIERS | {"accessor"})
            if required or self.member_modifier_follows(token.value, token, peek, class_member=True):
                raise self.token_error(token, "escape in class member modifier", 1260)
        if token.type in {"IDENTIFIER", "RESERVED", "CONST", "IN", "EXPORT", "DEFAULT", "ASYNC_HEAD"}:
            if self.type_member_modifier(parser, token, peek):
                if getattr(token, "escaped", False):
                    raise self.error(token.lexpos, "escaped type member modifier")
                token.type = "TYPE_MEMBER_MODIFIER"
                return
            if token.value in _PARAMETER_MODIFIERS | {"const"} and token.value != "async":
                if accepts_lookahead(parser, "OBJECT_MODIFIER") and self.member_modifier_follows(token.value, token, peek):
                    if getattr(token, "escaped", False):
                        raise self.error(token.lexpos, "escaped object member modifier")
                    token.type = "OBJECT_MODIFIER"
                    return
                if (token.value in {"export", "default", "const", "in", "out"}
                        and accepts_lookahead(parser, "CLASS_MODIFIER")
                        and self.member_modifier_follows(token.value, token, peek, class_member=True)):
                    if getattr(token, "escaped", False):
                        raise self.token_error(token, "escaped class member modifier", 1260)
                    token.type = "CLASS_MODIFIER"
                    return
            if token.value in _PARAMETER_MODIFIERS and accepts_lookahead(parser, "PARAM_MODIFIER"):
                if self.parameter_modifier_before(token, peek):
                    token.type = "PARAM_MODIFIER"
                    return
        if token.type in {"IDENTIFIER", "RESERVED"}:
            if token.value == "defer":
                following = peek()
                if (accepts_lookahead(parser, "DEFER_IMPORT") and following and
                        following.type not in {"COMMA", "ASSIGN"} and
                        not (following.value == "from" and peek(2) and peek(2).type == "STRING")):
                    has_clause = (following.type in {"IDENTIFIER", "LET", "LBRACE", "MULTIPLY"}
                                  or following.value in STRICT_IDENTIFIERS or following.value == "await")
                    token.type = "DEFER_IMPORT" if has_clause else "SOURCE_DEFER"
                    return
            if token.value == "type" and accepts_lookahead(parser, "SPEC_TYPE"):
                following = peek()
                if following and following.type not in {"COMMA", "RBRACE"}:
                    if following.value != "as" or (peek(2) and (peek(2).type in {"COMMA", "RBRACE"} or
                            (peek(2).value == "as" and peek(3) and peek(3).type not in {"COMMA", "RBRACE"}))):
                        token.type = "SPEC_TYPE"
                        return
            if token.value == "type" and accepts_lookahead(parser, "TYPE_IMPORT"):
                following = peek()
                if following and (following.type in {"MULTIPLY", "LBRACE"} or
                                  (following.type == "IDENTIFIER" and (following.value != "from" or
                                   (peek(2) and peek(2).type != "STRING")))):
                    token.type = "TYPE_IMPORT"
                    return
        if token.type in {"FUNCTION", "RESERVED"} and token.value == "function" and accepts_lookahead(parser, "DOC_FUNCTION_NAME"):
            token.type = "DOC_FUNCTION_NAME"
            return
        if token.type in {"IDENTIFIER", "RESERVED"} and getattr(token, "escaped", False):
            if token.value == "this" and accepts_lookahead(parser, "PARAM_AT") and accepts_lookahead(parser, "THIS"):
                token.type = "THIS"
                return
            if accepts_lookahead(parser, "TYPE_OPERATOR"):
                if token.value in {"true", "false", "null", "this", "void", "typeof", "new", "import",
                                   "readonly", "keyof", "unique", "infer"}:
                    raise self.token_error(token, "escape in type keyword", 1260)
                if token.value == "asserts":
                    following = peek()
                    if following and following.lineno == token.lineno and (
                            following.type in {"IDENTIFIER", "RESERVED", "LET"} or following.value in self.keywords):
                        raise self.token_error(token, "escape in asserts keyword", 1260)
                if token.value == "abstract" and peek() and peek().value == "new":
                    raise self.token_error(token, "escape in abstract keyword", 1260)
            if previous and previous.type == "TYPEOF" and token.value == "import" and accepts_lookahead(parser, "TYPE_NAME"):
                raise self.token_error(token, "escape in import type", 1260)
        if token.type in {"IDENTIFIER", "RESERVED"} and not getattr(token, "escaped", False):
            keywords = {"type": "TYPE_ALIAS", "declare": "DECLARE", "interface": "INTERFACE",
                        "namespace": "NS", "module": "TS_MODULE", "global": "GLOBAL", "enum": "TS_ENUM", "implements": "IMPLEMENTS"}
            candidate = keywords.get(token.value)
            if token.value == "abstract" and accepts_lookahead(parser, "ABSTRACT"):
                if peek() and peek().lineno == token.lineno and peek().type in {"CLASS", "NEW"}:
                    token.type = "ABSTRACT"
                    return
            if token.value == "defer":
                if accepts_lookahead(parser, "DEFER_CALL") and peek() and peek().type == "LPAREN":
                    token.type = "DEFER_CALL"
                    return
            if token.value == "type" and accepts_lookahead(parser, "EXPORT_TYPE"):
                following = peek()
                if following and following.type in {"LBRACE", "MULTIPLY"}:
                    token.type = "EXPORT_TYPE"
                    return
                if previous and previous.type == "EXPORT" and following and (
                        following.value == "as" or following.type in {"ASSIGN", "DEFAULT", "AT"}):
                    if self.script_pass and [s.type for s in parser.symstack[1:]] == ["TS_GOAL", "module_items", "EXPORT"]:
                        self.script_pass.incomplete_module_indicator = True
                    if following.value == "as" or following.type == "ASSIGN":
                        raise self.token_error(following, "expected '{' in type-only export", 1005)
                    if following.lineno != token.lineno:
                        raise self.token_error(following, "line break after exported type", 1142)
                    raise self.token_error(following, "identifier expected after exported type",
                                           1359 if following.type == "DEFAULT" else 1003)
            if token.value == "is" and accepts_lookahead(parser, "ASSERT_IS"):
                token.type = "ASSERT_IS"
                return
            if token.value == "is" and same_line and accepts_lookahead(parser, "IS"):
                token.type = "IS"
                return
            if token.value == "asserts" and accepts_lookahead(parser, "ASSERTS"):
                if peek() and peek().lineno == token.lineno and peek().type in {"IDENTIFIER", "THIS"}:
                    token.type = "ASSERTS"
                    return
            if token.value == "readonly" and accepts_lookahead(parser, "MAPPED_READONLY"):
                if peek() and peek().type == "LBRACKET" and peek(2) and peek(2).type == "IDENTIFIER" and peek(3) and peek(3).type == "IN":
                    token.type = "MAPPED_READONLY"
                    return
            if token.value in {"keyof", "unique", "readonly", "infer"}:
                operator = "INFER" if token.value == "infer" else "TYPE_OPERATOR"
                if accepts_lookahead(parser, operator):
                    token.type = operator
                    return
            if token.value in _PARAMETER_PROPERTY_MODIFIERS:
                following = peek()
                if following and following.lineno == token.lineno:
                    if following.type in {"IDENTIFIER", "LET", "RESERVED"} and accepts_lookahead(parser, "COVER_MODIFIER"):
                        # In an expression, readonly/override can be the left operand of an assertion.
                        if following.value == "as" and previous and previous.type == "LPAREN":
                            return  # The first modifier followed by 'as' starts a cast.
                        if (following.value not in {"as", "satisfies"} or
                                (peek(2) and peek(2).type in {"COLON", "COMMA", "RPAREN", "ASSIGN", "QUESTION"})):
                            token.type = "COVER_MODIFIER"
                            return
            if token.value in {"public", "private", "protected", "readonly", "abstract", "override", "declare", "accessor"}:
                if accepts_lookahead(parser, "CLASS_MODIFIER"):
                    following = peek()
                    if following and following.lineno == token.lineno and following.value != "<" and following.type not in {
                        "LPAREN", "COLON", "SEMICOLON", "QUESTION", "NOT", "ASSIGN", "RBRACE", "AT",
                    }:
                        token.type = "CLASS_MODIFIER"
                        return
            if (token.value in {"as", "satisfies"} and same_line
                    and not (previous and previous.type == "LET" and accepts_lookahead(parser, "IDENTIFIER"))):
                operator = "TS_AS" if token.value == "as" else "SATISFIES"
                if accepts_lookahead(parser, operator):
                    token.type = operator
            if candidate == "IMPLEMENTS" and accepts_lookahead(parser, candidate):
                following = peek()
                if previous and previous.value == "class" and accepts_lookahead(parser, "IDENTIFIER"):
                    if following and (following.type in {"IDENTIFIER", "RESERVED"} or following.value in self.keywords):
                        token.type = candidate
                elif (not previous or previous.type not in {"EXTENDS", "IMPLEMENTS", "COMMA"} or
                      not following or following.type not in {"DOT", "COMMA", "RPAREN", "SEMICOLON"}):
                    token.type = candidate
            elif candidate and accepts_lookahead(parser, candidate):
                following = peek()
                name_follows = following and (following.type in {"IDENTIFIER", "LET"} or
                                              following.value in STRICT_IDENTIFIERS or following.value == "await")
                if candidate in {"TYPE_ALIAS", "INTERFACE"} and (
                        (candidate == "TYPE_ALIAS" and previous and previous.type == "DECLARE")
                        or (not accepts_lookahead(parser, "EMPTY_SEMI") and self.in_decorated_declaration(parser))):
                    self.require_type_declaration_name(token, following)
                    token.type = candidate
                    return
                if candidate == "TS_ENUM" and name_follows:
                    token.type = candidate
                elif candidate == "GLOBAL" and self.global_declaration_follows(following):
                    token.type = candidate
                elif following and following.lineno == token.lineno:
                    if candidate in {"TYPE_ALIAS", "INTERFACE"}:
                        scope = getattr(token, "enclosing_scope", None)
                        if self.type_declaration_name(token, following, scope):
                            token.type = candidate
                        elif (previous and previous.type == "EXPORT") or following.value in {"await", "yield"}:
                            if previous and previous.type == "EXPORT":
                                error = self.token_error(previous, "declaration or statement expected", 1128)
                            else:
                                code = 2457 if candidate == "TYPE_ALIAS" else 2427
                                error = self.token_error(following, f"invalid {token.value} name", code)
                                if self.script_pass is not None and peek(2) and peek(2).value in {"<", "("}:
                                    # Parse await/yield and its operand as a new statement.
                                    # In TSX that operand may consume a later export as JSX text.
                                    self.script_pass.record(error)
                                    token.type = "IDENTIFIER"
                                    token.provisional_type_statement = True
                                    upcoming.appendleft(inserted_token(token, "SEMICOLON", ";"))
                                    return
                            self.recover_type_declaration_name(following, error)
                            token.type = candidate
                    elif candidate == "NS" and name_follows:
                        token.type = candidate
                    elif candidate == "TS_MODULE" and (name_follows or following.type == "STRING"):
                        token.type = candidate
                    elif candidate == "DECLARE" and following.value in {"using", "await"}:
                        using = following if following.value == "using" else peek(2)
                        binding = peek(2 if following.value == "using" else 3)
                        if using and using.value == "using" and self.resource_binding_follows(using, binding):
                            token.type = candidate
                    elif candidate == "DECLARE" and self.starts_modified_declaration(token, peek):
                        token.type = candidate
        if token.value in {"await", "yield"} and token.type in {"IDENTIFIER", "RESERVED"}:
            operator = token.value.upper()
            if accepts_lookahead(parser, operator):
                following = peek()
                operand_follows = following and following.lineno == token.lineno and (
                    following.type in {"IDENTIFIER", "RESERVED", "LET", "STRING", "NUMBER"} or following.value in self.keywords
                )
                if getattr(token, "escaped", False):
                    scope = getattr(token, "enclosing_scope", None)
                    required = scope in _IDENTIFIER_EXCLUDED_SCOPES[token.value] or (scope == "module" and token.value == "await")
                    if (required or operand_follows) and accepts_lookahead(parser, "REGEXP"):
                        raise self.token_error(token, "escape in " + token.value + " keyword", 1260)
                elif token.type == "IDENTIFIER" and operand_follows:
                    token.type = operator
                    if operator == "AWAIT":
                        token.await_expression = True
        elif (token.type == "COLON" and previous and previous.type == "RPAREN"
              and not getattr(token, "expression_separator", False) and accepts_lookahead(parser, "ARROW_RETURN")):
            if not accepts_lookahead(parser, "COLON") or self.has_typed_conditional_arm(token, conditional_separator(parser)):
                token.type = "ARROW_RETURN"
        elif token.type == "NOT" and same_line and accepts_lookahead(parser, "DEFINITE"):
            token.type = "DEFINITE"
        elif token.type == "NOT" and same_line and accepts_lookahead(parser, "NON_NULL"):
            token.type = "NON_NULL"
        elif token.type == "NOT" and same_line and previous and previous.type == "IDENTIFIER":
            self.binding_continuation(parser, previous, token, peek, upcoming)
        elif token.type in {"BIT_OR", "BIT_AND"}:
            operator = "TYPE_OR" if token.type == "BIT_OR" else "TYPE_AND"
            if accepts_lookahead(parser, operator):
                token.type = operator
        elif token.type == "QUESTION" and getattr(token, "provisional_conditional", False):
            return
        elif token.type == "QUESTION" and accepts_lookahead(parser, "OPTIONAL_PARAM"):
            following = peek()
            if following and following.type in {"COLON", "COMMA", "RPAREN", "ASSIGN"}:
                if previous.type == "PRIVATE_NAME":
                    error = self.token_error(following, "expression expected in conditional", 1109)
                    if self.script_pass is None:
                        raise error
                    self.script_pass.record(error)
                token.type = "OPTIONAL_PARAM"
        elif token.type == "QUESTION" and accepts_lookahead(parser, "TUPLE_OPTIONAL"):
            if peek() and peek().type == "COLON":
                token.type = "TUPLE_OPTIONAL"
        elif token.type == "LPAREN" and accepts_lookahead(parser, "SIG_PARAMS"):
            first = peek()
            if first and first.type in {"RPAREN", "ELLIPSIS"}:
                token.type = "SIG_PARAMS"
            elif first and self.parameter_starts_function_type(first, peek):
                token.type = "SIG_PARAMS"
        elif (token.type == "LBRACKET" and accepts_lookahead(parser, "MAP_OPEN") and peek()
              and peek().type == "IDENTIFIER" and peek(2) and peek(2).type == "IN"):
            token.type = "MAP_OPEN"
        elif token.type == "LBRACKET" and accepts_lookahead(parser, "TS_INDEX_OPEN"):
            first = peek()
            if first and first.type in {"ELLIPSIS", "RBRACKET"}:
                token.type = "TS_INDEX_OPEN"
            elif first and peek(2):
                second = peek(2)
                modifier = first.value in _PARAMETER_MODIFIERS or first.value == "const"
                # Index lookahead uses isIdentifier, which respects the
                # surrounding await/yield context even though a binding may
                # otherwise carry either spelling.
                scope = token.enclosing_scope
                if first.value in _IDENTIFIER_EXCLUDED_SCOPES or second.value in _IDENTIFIER_EXCLUDED_SCOPES:
                    for symbol in reversed(parser.symstack):
                        if symbol.type == "TS_OBJECT":
                            scope = "ordinary"  # parseType clears await and yield contexts.
                            break
                        if symbol.type == "LBRACE":  # class or interface body
                            break
                if modifier or self.arrow_head_identifier(first, scope):
                    if (second.type in {"COLON", "COMMA"} or (modifier and self.arrow_head_identifier(second, scope))
                            or (second.type == "QUESTION" and peek(3) and peek(3).type in {"COLON", "COMMA", "RBRACKET"})):
                        token.type = "TS_INDEX_OPEN"
        elif token.type == "LBRACE" and accepts_lookahead(parser, "TS_OBJECT"):
            token.type = "TS_OBJECT"
        elif token.type == "LBRACKET" and same_line and accepts_lookahead(parser, "TYPE_INDEX"):
            token.type = "TYPE_INDEX"
        elif token.type in {"RELATION", "SHIFT"} and token.value in {"<", "<<"}:
            if (token.value == "<" and accepts_lookahead(parser, "GENERIC_ARROW_LT")
                    and self.has_arrow_head(token)):
                token.type = "GENERIC_ARROW_LT"
            elif token.value == "<" and accepts_lookahead(parser, "ASSERT_LT") and self.allow_angle_assertions:
                token.type = "ASSERT_LT"
            elif token.value == "<" and accepts_lookahead(parser, "PARAM_LT"):
                token.type = "PARAM_LT"
            elif accepts_lookahead(parser, "CALL_TYPE_LT") and self.can_start_type_arguments(token):
                token.type = "CALL_TYPE_LT"
            elif same_line and accepts_lookahead(parser, "TYPE_LT"):
                if self.reference_arguments_start_here(parser, previous, token):
                    token.type = "TYPE_LT"
            if token.type == "CALL_TYPE_LT" or (token.type == "TYPE_LT" and previous and previous.type == "OPTIONAL"):
                token.type_argument_scope = token.enclosing_scope
                token.optional_type_arguments = previous.type == "OPTIONAL"
            elif token.type == "TYPE_LT" and previous is None and self.goal_token() == "TYPE_ARGS_GOAL":
                token.type_argument_scope = self.probe_argument_scope
            if token.value == "<<" and token.type != "SHIFT":
                # reScanLessThanToken splits a shift only after a type or
                # generic-call context has actually been established.
                self.lexer.lexpos, self.lexer.lineno = token.lexpos + 1, token.lineno
                upcoming.clear()
                token.value = "<"
        elif token.type in {"RELATION", "SHIFT", "COMPOUND_ASSIGN"} and token.value.startswith(">"):
            if accepts_lookahead(parser, "TYPE_GT"):
                if len(token.value) > 1:
                    # Rescan from the next character: in T>=>x the remaining
                    # '=' begins an arrow, even though the scanner first saw '>='.
                    token.unsplit_operator_length = len(token.value)
                    self.lexer.lexpos = token.lexpos + 1
                    self.lexer.lineno = token.lineno
                    upcoming.clear()
                token.type, token.value = "TYPE_GT", ">"

        replaying_error = self.script_pass is not None and self.script_pass.first_error is not None
        if token.type == "SEMICOLON" and replaying_error and not accepts_lookahead(parser, "SEMICOLON"):
            closing_stack = stack_before_shift(parser, "RPAREN")
            if closing_stack[-1:] in (["arguments"], ["cover_items"]) or closing_stack[-3:] in (
                    ["IF", "LPAREN", "expression"], ["WHILE", "LPAREN", "expression"], ["WITH", "LPAREN", "expression"]):
                # An argument list terminates on a semicolon during error recovery.
                # Replay the semicolon after each missing closing parenthesis.
                upcoming.appendleft(copy(token))
                token.type, token.value, token.end_pos = "RPAREN", ")", token.lexpos
                return
        if token.type == "RPAREN" and replaying_error and not accepts_lookahead(parser, "RPAREN"):
            # The reference parser can end the preceding statement and discard
            # an unmatched closing paren after recovering a missing control delimiter.
            if accepts_lookahead(parser, "SEMICOLON") or accepts_lookahead(parser, "EMPTY_SEMI"):
                token.type, token.value = "SEMICOLON", ";"
        separator_candidate = token.type in {"ASSIGN", "COMPOUND_ASSIGN"} or (token.type == "COLON" and replaying_error)
        if previous and separator_candidate and not accepts_lookahead(parser, token.type):
            self.recover_expression_separator(parser, token, previous, upcoming)
        if (token.type == "DOT" and replaying_error and not accepts_lookahead(parser, "DOT")
                and stack_before_shift(parser, "COMMA")[-1:] == ["properties"]):
            token.type, token.value = "COMMA", ","

        if (token.type in {"LET", "IDENTIFIER"} and token.value != "declare"
                and accepts_lookahead(parser, "EMPTY_SEMI") and accepts_lookahead(parser, "DECL_MODIFIER")):
            following = peek()
            if following and following.lineno == token.lineno and (
                    self.is_property_name_token(following) or following.type in {"STRING", "NUMBER"}
                    or (following.type == "LBRACE" and token.value in {"interface", "type", "namespace", "module"})):
                # Use the head's diagnostic only if yacc actually rejects the following token.
                following.statement_identifier = token
        if token.value == "declare" and token.type == "IDENTIFIER":
            # The compiler omits its missing-semicolon diagnostic after
            # a standalone identifier expression whose spelling is declare.
            token.declare_statement = accepts_lookahead(parser, "EMPTY_SEMI") and accepts_lookahead(parser, "DECL_MODIFIER")

        if (token.type == "IDENTIFIER" and token.value in STRICT_IDENTIFIERS
                and accepts_lookahead(parser, "TYPE_NAME")):
            token.type = "TYPE_NAME"
        if token.type in {"RESERVED", "AWAIT", "YIELD", "BARE_YIELD"} and token.value in (STRICT_IDENTIFIERS | {"await"}):
            # The next identifier can trigger the reduction that ends a declare
            # item. Enclosing ambient declarations still apply after an inner item ends.
            ambient = self.declaration_file or (self.ambient_depth and "ambient_scope" in stack_before_shift(parser, "IDENTIFIER"))
            ambient_name = (ambient and token.type not in {"YIELD", "BARE_YIELD"}
                            and not getattr(token, "await_property_name", False)
                            and not (getattr(token, "await_expression", False) and
                                     (token.type == "AWAIT" or accepts_lookahead(parser, "OBJECT_ASYNC"))))
            if (getattr(token, "in_yield_context", False) and not accepts_lookahead(parser, token.type)
                    and accepts_lookahead(parser, "REGEXP") and not accepts_lookahead(parser, "TYPE_OPERATOR")):
                raise self.token_error(token, "expression expected", 1109)
            if ((ambient_name or not accepts_lookahead(parser, token.type))
                    and accepts_lookahead(parser, "IDENTIFIER")):
                token.type = "IDENTIFIER"
        # Entity names at the start of a type reference admit reserved words
        # (TS 5.9 parseEntityNameOfTypeReference), independently of value bindings.
        if (token.type in {"RESERVED", "YIELD", "BARE_YIELD", "AWAIT"} or token.value in self.keywords):
            if not accepts_lookahead(parser, token.type) and accepts_lookahead(parser, "TYPE_NAME"):
                token.type = "TYPE_NAME"

        reserved_name = (token.value in self.keywords or token.value in self.reserved) and not self.binding_identifier(token)
        if (reserved_name or token.type in {"NUMBER", "STRING"}) and not accepts_lookahead(parser, token.type):
            if self.declaration_name_position(parser, previous) and accepts_lookahead(parser, "IDENTIFIER"):
                if previous.lineno < token.lineno and accepts_lookahead(parser, "SEMICOLON"):
                    return  # ASI can terminate the declaration before a new statement.
                error = self.declaration_name_error(parser, previous, token, reserved=reserved_name)
            elif previous and (previous.type == "BIND_ARRAY" or (
                    previous.type in {"COMMA", "ELLIPSIS"}
                    and any(symbol.type == "binding_prefix" for symbol in parser.symstack[-3:-1]))):
                if previous.type == "ELLIPSIS":
                    error = self.token_error(token, "identifier expected after rest prefix", 1359 if reserved_name else 1003)
                else:
                    error = self.token_error(token, "array element destructuring pattern expected", 1181)
            elif "parameter" in parser.goto.get(parser.statestack[-1], {}):
                if reserved_name:
                    # A modifier, type starter or rest prefix has already
                    # committed the reference parser to a parameter.
                    parameter_start = (
                        (previous and previous.type in {"ELLIPSIS", "PARAM_MODIFIER"})
                        or token.value in _PARAMETER_MODIFIERS
                        or token.value in {"const", "new", "true", "false", "null", "void", "typeof", "import"}
                    )
                    error = self.token_error(token, "reserved parameter name", 1359 if parameter_start else 1390)
                else:
                    error = self.token_error(token, "identifier expected", 1003)
            else:
                return
            if self.script_pass is None:
                raise error
            self.script_pass.record(error)
            following = peek()
            if not following or not (accepts_lookahead(parser, "IDENTIFIER", following.type) or
                    (following.type == "DOT" and accepts_lookahead(parser, "IDENTIFIER", "COMMA"))):
                raise error
            token.type = "IDENTIFIER"
            token.recovered_binding = True

    allow_angle_assertions = True
    restrict_angles = False

    @staticmethod
    def expression_constraint_follows(scope, peek):
        # isStartOfType takes priority over the expression recovery branch.
        # Inside parentheses, decorator and private names can start parameters.
        distance = 1
        first = peek(distance)
        while first and first.type == "LPAREN":
            distance += 1
            first = peek(distance)
        if not first:
            return False
        if first.type == "MINUS":
            next_token = peek(distance + 1)
            return not next_token or next_token.type != "NUMBER"
        if first.value == "await":
            return distance == 1 and scope in {"async", "async parameters", "async generator", "async generator parameters"}
        if first.value == "yield":
            return distance == 1 and scope in {"generator", "generator parameters", "async generator", "async generator parameters"}
        if first.type in {"PRIVATE_NAME", "AT"}:
            return distance == 1
        return first.type in {"PLUS", "INCREMENT", "DECREMENT", "BIT_NOT", "DELETE", "CLASS", "SUPER", "DIVIDE"} or first.value == "/="

    def parameter_starts_function_type(self, first, peek):
        position = 1
        while first.value in _PARAMETER_MODIFIERS:
            following = peek(position + 1)
            if not self.parameter_modifier_before(first, peek, position + 1):
                break
            first = following
            position += 1
        if first.type in {"LBRACE", "LBRACKET"}:
            return self.binding_starts_formals(first)
        if first.value != "this" and not self.binding_identifier(first):
            return False
        following = peek(position + 1)
        if following and following.type == "RPAREN":
            arrow = peek(position + 2)
            return bool(arrow and arrow.type == "ARROW")
        return bool(following and following.type in {"COLON", "COMMA", "QUESTION", "ASSIGN"})

    def make_probe(self, grammar_class, *, level=0):
        probe, parser = parser_for_thread(self.source, self.source_type, grammar_class, level=level)
        probe.identifier_char = self.identifier_char
        probe.regexp_target_year = self.regexp_target_year
        probe.declaration_file = self.declaration_file
        return probe, parser

    def binding_starts_formals(self, first):
        probe, parser = self.make_probe(BindingProbe)
        probe.lexer.lexpos, probe.lexer.lineno = first.lexpos, first.lineno
        tokens = statement_tokens(probe, parser, None)
        last = None

        def next_token():
            nonlocal last
            if last and accepts_lookahead(parser, "$end"):
                return None
            last = next(tokens, None)
            return last

        try:
            parser.parse(lexer=probe.lexer, tokenfunc=next_token)
            probe.lexer.lexpos, probe.lexer.lineno = last.lexpos + 1, last.lineno
            following = probe.lexer.token()
            if following and following.type == "RPAREN":
                arrow = probe.lexer.token()
                return bool(arrow and arrow.type == "ARROW")
            return bool(following and following.type in {"COLON", "COMMA", "QUESTION", "ASSIGN"})
        except SourceSyntaxError:
            return False

    def p_binding_probe(self, p):
        "program : BINDING_PROBE_GOAL binding"
        p[0] = p[2]

    def has_infer_bound(self, opening):
        probe, parser = self.make_probe(InferBoundProbe)
        probe.lexer.lexpos, probe.lexer.lineno = opening.lexpos, opening.lineno
        stream = statement_tokens(probe, parser, None)
        boundary = None

        def next_token():
            nonlocal boundary
            token = next(stream, None)
            if token and not accepts_lookahead(parser, token.type) and accepts_lookahead(parser, "$end"):
                boundary = token
                return None
            return token

        try:
            parser.parse(lexer=probe.lexer, tokenfunc=next_token)
            return boundary is None or boundary.type != "QUESTION"
        except SourceSyntaxError:
            return False

    def p_infer_bound_probe(self, p):
        "program : INFER_BOUND_GOAL EXTENDS conditional_bound"
        p[0] = p[3]

    def has_typed_conditional_arm(self, colon, conditional):
        # In "flag ? (x): T => x : y", the first colon annotates a return
        # type only if the completed arrow body leaves a conditional separator.
        probe_class = ReturnArmProbe if conditional else ReturnTypeProbe
        probe, parser = self.make_probe(probe_class)
        probe.lexer.lexpos, probe.lexer.lineno = colon.lexpos, colon.lineno
        tokens = statement_tokens(probe, parser, None)

        def next_token():
            if accepts_lookahead(parser, "$end"):
                return None
            return next(tokens, None)

        try:
            return parser.parse(lexer=probe.lexer, tokenfunc=next_token) is True
        except SourceSyntaxError:
            return False

    def p_return_arm_probe(self, p):
        """program : RETURN_ARM_GOAL COLON return_type ARROW concise COLON
                   | RETURN_TYPE_GOAL COLON return_type ARROW"""
        p[0] = True

    def has_arrow_head(self, opening, outer_parser=None, *, ordinary=False):
        key = opening.lexpos, ordinary
        if key not in self.arrow_heads:
            self.arrow_heads[key] = None
            self.arrow_heads[key] = self.probe_arrow_head(opening, ordinary)
        boundary = self.arrow_heads[key]
        if boundary is None:
            return False
        if boundary.type == "COLON":
            return self.has_typed_conditional_arm(boundary, conditional_separator(outer_parser, after_identifier=True))
        return True

    def probe_arrow_head(self, opening, ordinary):
        probe_class = TsxArrowHeadProbe if isinstance(self, JsxRules) else ArrowHeadProbe
        probe, parser = self.make_probe(probe_class, level=self.arrow_probe_depth)
        probe.allow_angle_assertions = self.allow_angle_assertions
        probe.ordinary_arrow_probe = ordinary
        probe.last_possible_arrow = self.last_possible_arrow
        probe.arrow_heads = self.arrow_heads
        probe.arrow_probe_depth = self.arrow_probe_depth + 1
        probe.lexer.lexpos, probe.lexer.lineno = opening.lexpos, opening.lineno
        tokens = statement_tokens(probe, parser, None)
        boundary = None

        def next_token():
            nonlocal boundary
            token = next(tokens, None)
            if token and accepts_lookahead(parser, "$end") and (token.type == "ARROW" or
                    (opening.type == "LPAREN" and token.type == "COLON")):
                boundary = token
                return None
            return token

        try:
            unambiguous = parser.parse(lexer=probe.lexer, tokenfunc=next_token)
        except SourceSyntaxError:
            return None
        return boundary if self.allow_angle_assertions or unambiguous else None

    def p_arrow_head_probe(self, p):
        """program : ARROW_PROBE async_formals
                   | ORDINARY_ARROW_PROBE formals
                   | ARROW_PROBE ts_required_params formals
                   | ARROW_PROBE ts_required_params formals return_annotation"""
        if len(p) == 3:
            p[0] = True
        else:
            params = p[2]["params"]
            if not params:
                raise self.error(p.lexpos(1), "expected arrow type parameter")
            p[0] = bool(p[2].get("trailingComma") or len(params) > 1 or params[0]["constraint"] or params[0]["default"])

    def p_generic_arrow_params(self, p):
        """generic_arrow_params : GENERIC_ARROW_LT ts_param_list TYPE_GT
                                | GENERIC_ARROW_LT ts_param_list COMMA TYPE_GT"""
        p[0] = {"type": "TSTypeParameterDeclaration", "params": p[2]}
        if len(p) == 5:
            p[0]["trailingComma"] = True
        p.set_lexpos(0, p.lexpos(1))

    def attach_arrow_types(self, arrow, types):
        arrow["typeParameters"] = types
        params = types["params"]
        if (self.restrict_angles and len(params) == 1 and not types.get("trailingComma") and not params[0]["constraint"]
                and not self.parameter_list_error(arrow["params"])):
            arrow.setdefault("diagnostics", []).insert(0, {
                "code": 7060, "offset": self.type_parameter_offsets[id(params[0])],
                "message": "generic arrow in .mts or .cts requires a trailing comma or an explicit constraint"})

    def p_formal_arrow(self, p):
        """assignment : ARROW_PARAMS formal_list ARROW concise
                      | ARROW_PARAMS formal_list return_annotation ARROW concise
           assignment_no_in : ARROW_PARAMS formal_list ARROW concise_no_in
                            | ARROW_PARAMS formal_list return_annotation ARROW concise_no_in"""
        p[0] = self.arrow_node(p[2], p[len(p)-1], False, p.lexpos(1), arrow_token=p.slice[-2])
        if len(p) == 6:
            p[0]["returnType"] = p[3]

    def p_generic_arrow(self, p):
        """assignment : generic_arrow_params formals ARROW concise
                      | generic_arrow_params formals return_annotation ARROW concise
           assignment_no_in : generic_arrow_params formals ARROW concise_no_in
                            | generic_arrow_params formals return_annotation ARROW concise_no_in"""
        p[0] = self.arrow_node(p[2], p[len(p)-1], False, p.lexpos(1), arrow_token=p.slice[-2])
        self.attach_arrow_types(p[0], p[1])
        if len(p) == 6:
            p[0]["returnType"] = p[3]

    def p_async_head(self, p):
        "async_head : ASYNC_SINGLE identifier"
        super().p_async_head(p)

    def p_async_formal_arrow(self, p):
        """assignment : ASYNC_ARROW_HEAD ts_params async_formals ASYNC_ARROW async_concise
                      | ASYNC_ARROW_HEAD ts_params async_formals return_annotation ASYNC_ARROW async_concise
           assignment_no_in : ASYNC_ARROW_HEAD ts_params async_formals ASYNC_ARROW async_concise_no_in
                            | ASYNC_ARROW_HEAD ts_params async_formals return_annotation ASYNC_ARROW async_concise_no_in"""
        p[0] = self.arrow_node(p[3], p[len(p)-1], True, p.lexpos(1), arrow_token=p.slice[-2])
        if p[2]:
            self.attach_arrow_types(p[0], p[2])
        if len(p) == 7:
            p[0]["returnType"] = p[4]

    def p_invalid_power_left(self, p):
        "invalid_power_left : unary_expression"
        start = p.lexpos(1)
        end = self.source_lookahead.operand_end
        assertion = p[1]["type"] == "TSTypeAssertion"
        error = self.error(start, "unparenthesized left operand of exponentiation",
                           code=17007 if assertion else 17006, length=end - start)
        if self.script_pass is None:
            raise error
        self.script_pass.record(error)
        p[0] = p[1]

    def p_recovered_power(self, p):
        "exponential : invalid_power_left UNARY_POWER_ERROR exponential"
        self.p_binary(p)

    def p_angle_assertion(self, p):
        "unary_expression : ASSERT_LT ts_type TYPE_GT unary_operand"
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "TSTypeAssertion", "typeAnnotation": p[2], "expression": p[4]}
        if self.restrict_angles:
            p[0]["diagnostics"] = [{"code": 7059, "offset": p.lexpos(1),
                                    "message": "angle assertion in .mts or .cts requires an as expression"}]

    @staticmethod
    def reference_arguments_start_here(parser, previous, opening):
        stack = parser.symstack
        if previous is None or stack[-1] is not previous or len(stack) < 2:
            return True
        # parseTypeQuery checks for a single '<' without splitting '<<'.
        # An import type uses the reference-type rule even underneath typeof.
        dotted = stack[-2].type == "DOT"
        query = stack[-2].type == "TYPEOF" or (dotted and len(stack) >= 4
                and stack[-3].type in {"ts_name", "this_query_name"} and stack[-4].type == "TYPEOF")
        if query:
            return opening.value == "<"
        # A bare keyword type ends before a relational or shift operator.
        # N.number can take reference arguments just like N.T.
        return dotted or previous.value not in KEYWORD_TYPES or not accepts_lookahead(parser, opening.type)

    def can_start_type_arguments(self, opening):
        # Speculate on the type list using an independent PLY stack. The real
        # value-expression stack and its pending tokens stay intact on failure.
        probe, parser = self.make_probe(TypeArgumentProbe)
        probe.probe_argument_scope = opening.enclosing_scope
        probe.lexer.lexpos, probe.lexer.lineno = opening.lexpos, opening.lineno
        tokens = statement_tokens(probe, parser, None)
        last = None

        def next_token():
            nonlocal last
            if last and last.type == "TYPE_GT" and accepts_lookahead(parser, "$end"):
                return None
            last = next(tokens, None)
            return last

        try:
            parser.parse(lexer=probe.lexer, tokenfunc=next_token)
            # Nested type arguments may split a shift token. The outermost
            # expression list must finish with a standalone greater-than token.
            if getattr(last, "unsplit_operator_length", 1) > 1:
                return False
            probe.lexer.lexpos, probe.lexer.lineno = last.lexpos + 1, last.lineno
            following = probe.lexer.token()
        except SourceSyntaxError:
            return False
        if following is None or following.type in {"LPAREN", "TEMPLATE", "TEMPLATE_HEAD"}:
            return True
        if following.value.startswith(">") or following.value in {"<", "+", "-"}:
            return False
        if following.lineno > last.lineno or following.value in {"as", "satisfies", "in", "instanceof"}:
            return True
        return following.type not in {
            "NUMBER", "IDENTIFIER", "STRING", "LBRACKET", "LBRACE", "TRUE", "FALSE", "NULL",
            "THIS", "SUPER", "NEW", "FUNCTION", "CLASS", "DELETE", "TYPEOF", "VOID", "NOT",
            "BIT_NOT", "INCREMENT", "DECREMENT", "IMPORT",
        }

    def p_member(self, p):
        """member : member DOT property_name
                  | member LBRACKET expression RBRACKET
           call : call DOT property_name
                | call LBRACKET expression RBRACKET"""
        if p.slice[2].type == "DOT":
            self.check_instantiation_access(p[1])
        super().p_member(p)

    def check_instantiation_access(self, obj):
        if obj["type"] == "TSInstantiationExpression" and id(obj) not in self.grouped_patterns:
            start, end = self.applied_argument_spans[id(obj["typeArguments"])]
            error = self.error(start, "property access after unparenthesized instantiation", code=1477, length=end - start)
            if self.script_pass is None:
                raise error
            self.script_pass.record(error)

    def p_private_reference(self, p):
        "private_reference : PRIVATE_NAME"
        super().p_private_reference(p)
        p.slice[0].private_token = p.slice[1]

    def p_private_expression(self, p):
        "primary : private_reference"
        p[0] = p[1]

    def p_private_meta_property(self, p):
        """member : IMPORT DOT PRIVATE_NAME
                  | NEW DOT PRIVATE_NAME
           decorator_member : IMPORT DOT PRIVATE_NAME
                            | NEW DOT PRIVATE_NAME"""
        p[0] = {"type": "MetaProperty", "meta": {"type": "Identifier", "name": p[1]},
                "property": {"type": "Identifier", "name": "#" + p[3]}}

    def p_private_property_key(self, p):
        "property_key : private_reference"
        p[0] = (p[1], False, False, self.private_offsets[id(p[1])])

    def p_class_element_key(self, p):
        "class_element_key : property_key"
        super().p_class_element_key(p)

    def p_private_member(self, p):
        """member : member DOT private_reference
           call : call DOT private_reference"""
        self.check_instantiation_access(p[1])
        super().p_private_member(p)

    def p_super_private_member(self, p):
        "member : SUPER DOT private_reference"
        self.p_super_member(p)

    @staticmethod
    def finish_optional_chain(root):
        # Only nodes flagged as a chain by the type grammar belong inside
        # ChainExpression. A trailing non-null assertion or instantiation
        # may still surround that chain.
        node, parent = root, None
        while node["type"] in {"TSNonNullExpression", "TSInstantiationExpression"} and "optional" not in node:
            parent, node = node, node["expression"]
        if "optional" not in node:
            return root
        chain = {"type": "ChainExpression", "expression": node}
        if parent is None:
            return chain
        parent["expression"] = chain
        return root

    def resolve_optional_continuation(self, node, field):
        base = node[field]
        if node["optional"]:
            if base["type"] in {"TSNonNullExpression", "TSInstantiationExpression"}:
                node[field] = self.finish_optional_chain(base)
            return
        current = base
        assertions = []
        if field != "tag":
            while current["type"] == "TSNonNullExpression" and "optional" not in current:
                assertions.append(current)
                current = current["expression"]
        if "optional" in current:
            for assertion in assertions:
                assertion["optional"] = False
        else:
            del node["optional"]
            node[field] = self.finish_optional_chain(base)

    def p_chain_expression(self, p):
        "chain : optional_chain"
        p[0] = self.finish_optional_chain(p[1])

    def p_optional_member(self, p):
        """optional_chain : optional_base property_name
                          | optional_base private_reference
                          | optional_base LBRACKET expression RBRACKET
                          | optional_chain DOT property_name
                          | optional_chain DOT private_reference
                          | optional_chain LBRACKET expression RBRACKET"""
        super().p_optional_member(p)
        self.finish_ts_property_access(p)

    def finish_ts_property_access(self, p):
        if "optional" in p[0]:
            self.resolve_optional_continuation(p[0], "object")
        if p[0]["computed"]:
            return
        if "optional" in p[0] and p.slice[-1].type == "private_reference":
            error = self.token_error(p.slice[-1].private_token, "private name in optional chain", 18030)
            if self.script_pass is None:
                raise error
            self.script_pass.record(error)
        self.check_instantiation_access(p[1])

    def p_non_null(self, p):
        """member : member NON_NULL
           call : call NON_NULL
           optional_chain : optional_chain NON_NULL"""
        p[0] = {"type": "TSNonNullExpression", "expression": p[1]}

    def p_short_circuit(self, p):
        """short_circuit : logical_or
           short_circuit_no_in : logical_or_no_in"""
        p[0] = p[1]

    def p_coalesce(self, p):
        """logical_or : logical_or COALESCE logical_and
           logical_or_no_in : logical_or_no_in COALESCE logical_and_no_in"""
        self.p_logical_operator(p)

    def p_update(self, p):
        """update : chain POST_INCREMENT
                  | chain POST_DECREMENT
                  | INCREMENT chain
                  | DECREMENT chain"""
        super().p_update(p)

    def is_simple_target(self, node, offset):
        while node["type"] in {"TSNonNullExpression", "TSAsExpression", "TSSatisfiesExpression", "TSTypeAssertion"}:
            node = node["expression"]
        return node["type"] == "PrivateIdentifier" or super().is_simple_target(node, offset)

    def p_type_assertion(self, p):
        """assertion : relational TS_AS ts_type
                      | relational SATISFIES ts_type
           assertion_no_in : relational_no_in TS_AS ts_type
                            | relational_no_in SATISFIES ts_type"""
        p[0] = {"type": "TSAsExpression" if p[2] == "as" else "TSSatisfiesExpression",
                "expression": p[1], "typeAnnotation": p[3]}
        if self.track_import_arguments and p[2] == "satisfies":
            self.import_error_spans[id(p[0])] = (p[0], p.lexpos(2), p.lexpos(2) + len(p[2]))

    # The assertion consumes a relational expression on its left, then
    # becomes the left operand of any following arithmetic or shift operator.
    def p_assertion_operand(self, p):
        """relational : assertion_shift
           assertion_shift : assertion_sum
           assertion_sum : assertion_product
           assertion_product : assertion_power
           assertion_power : assertion
           relational_no_in : assertion_shift_no_in
           assertion_shift_no_in : assertion_sum_no_in
           assertion_sum_no_in : assertion_product_no_in
           assertion_product_no_in : assertion_power_no_in
           assertion_power_no_in : assertion_no_in"""
        p[0] = p[1]

    def p_assertion_binary(self, p):
        """assertion_power : assertion POWER exponential
           assertion_product : assertion_product MULTIPLY exponential
                             | assertion_product DIVIDE exponential
                             | assertion_product REMAINDER exponential
           assertion_sum : assertion_sum PLUS multiplicative
                         | assertion_sum MINUS multiplicative
           assertion_shift : assertion_shift SHIFT additive
           assertion_power_no_in : assertion_no_in POWER exponential
           assertion_product_no_in : assertion_product_no_in MULTIPLY exponential
                                   | assertion_product_no_in DIVIDE exponential
                                   | assertion_product_no_in REMAINDER exponential
           assertion_sum_no_in : assertion_sum_no_in PLUS multiplicative
                               | assertion_sum_no_in MINUS multiplicative
           assertion_shift_no_in : assertion_shift_no_in SHIFT additive"""
        self.p_binary(p)

    def p_return_typed_arrow(self, p):
        """assignment : typed_arrow_head ARROW concise
                      | typed_async_head ASYNC_ARROW async_concise
           assignment_no_in : typed_arrow_head ARROW concise_no_in
                            | typed_async_head ASYNC_ARROW async_concise_no_in"""
        self.p_arrow(p)
        p[0]["returnType"] = p.slice[1].return_annotation

    def p_return_typed_head(self, p):
        """typed_arrow_head : cover_parens ARROW_RETURN return_type
           typed_async_head : async_head ARROW_RETURN return_type"""
        p[0] = p[1]
        p.set_lexpos(0, p.lexpos(1))
        p.slice[0].return_annotation = {"type": "TSTypeAnnotation", "typeAnnotation": p[3]}

    def p_string(self, p):
        "string_literal : STRING"
        super().p_string(p)
        if p[0]["value"] == "use strict":
            self.directive_offsets[id(p[0])] = p.lexpos(1)

    def p_cover_parens(self, p):
        """cover_parens : LPAREN RPAREN
                        | LPAREN cover_items RPAREN
                        | LPAREN cover_items COMMA RPAREN"""
        super().p_cover_parens(p)
        p.slice[0].closing = p.slice[-1]

    def p_parenthesized(self, p):
        "primary : cover_parens"
        items, trailing, start = p[1]
        error = self.parenthesized_expression_error(items, trailing, start, p.slice[1].closing)
        if error:
            if self.script_pass is None:
                raise error
            self.script_pass.record(error)
            # The preliminary script can recover missing operands in the
            # expression list while it looks for a later module indicator.
            missing = {"type": "Identifier", "name": ""}
            items = [missing if item["type"] == "RestElement" else item for item in items]
            if trailing or not items:
                items.append(missing)
            p[1] = items, False, start
        super().p_parenthesized(p)

    def p_cover_items(self, p):
        """cover_items : cover_item
                       | cover_items COMMA cover_item"""
        super().p_cover_items(p)
        opening = p.stack[-1]
        if len(p) == 2:
            self.cover_starts[opening.lexpos] = [opening.item_start]
        else:
            self.cover_starts[opening.lexpos].append(p.slice[2].item_start)

    def p_typed_cover_item(self, p):
        """cover_item : typed_cover_parameter
                      | ELLIPSIS typed_cover_parameter
           argument : typed_cover_parameter
                    | ELLIPSIS typed_cover_parameter"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            kind = "RestElement" if p.slice[0].type == "cover_item" else "SpreadElement"
            p[0] = {"type": kind, "argument": p[2]}

    def p_cover_modifiers(self, p):
        """cover_modifiers : COVER_MODIFIER
                           | cover_modifiers COVER_MODIFIER"""
        p.set_lexpos(0, p.lexpos(1))
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_modified_cover_parameter(self, p):
        """cover_item : cover_modifiers assignment
                      | cover_modifiers typed_cover_parameter
           argument : cover_modifiers assignment
                    | cover_modifiers typed_cover_parameter"""
        p[0] = p[2]
        self.cover_modifiers[id(p[0])] = p[1]
        self.cover_errors[id(p[0])] = (p.lexpos(1), "parameter modifier outside arrow parameters")

    def p_typed_cover_parameter(self, p):
        """typed_cover_parameter : chain annotation
                                 | chain OPTIONAL_PARAM
                                 | chain OPTIONAL_PARAM annotation
                                 | chain annotation ASSIGN assignment
                                 | chain OPTIONAL_PARAM ASSIGN assignment
                                 | chain OPTIONAL_PARAM annotation ASSIGN assignment"""
        optional = p.slice[2].type == "OPTIONAL_PARAM"
        annotation = next((sym.value for sym in p.slice[2:] if sym.type == "annotation"), None)
        binding = p[1]
        p[0] = ({"type": "AssignmentExpression", "operator": "=", "left": binding, "right": p[len(p)-1]}
                if p.slice[len(p)-1].type == "assignment" else binding)
        self.cover_annotations[id(p[0])] = (optional, annotation)
        self.cover_errors[id(p[0])] = (p.lexpos(2), "type annotation outside arrow parameters")

    def check_arrow_object_pattern(self, pattern, offset):
        super().check_arrow_object_pattern(pattern, offset)
        for prop in pattern["properties"]:
            if prop.get("modifiers"):
                raise self.error(self.object_marker_offsets[id(prop["key"])], "modifier in binding pattern")
            if prop.get("optional") or prop.get("definite"):
                raise self.error(self.object_marker_offsets[id(prop["key"])], "property marker in binding pattern")

    def arrow_binding(self, node, offset):
        info = self.cover_annotations.pop(id(node), None)
        modifiers = self.cover_modifiers.pop(id(node), [])
        if info or modifiers:
            self.cover_errors.pop(id(node))
        pattern = super().arrow_binding(node, offset)
        if info:
            target = pattern["left"] if pattern["type"] == "AssignmentPattern" else pattern
            target["optional"] = info[0]
            if info[1]:
                target["typeAnnotation"] = info[1]
        for modifier in reversed(modifiers):
            self.apply_parameter_modifier(pattern, modifier)
        return pattern

    def arrow_node(self, params, body, is_async, offset, *, arrow_token=None):
        block = body["type"] == "BlockStatement"
        if not block:
            self.check_implementation_parameters(params, "ArrowFunctionExpression", offset)
        node = super().arrow_node(params, body, is_async, offset, arrow_token=arrow_token)
        if self.track_import_arguments and block and arrow_token is not None:
            body_start = arrow_token.lexpos + len(arrow_token.value)
            line_break = re.compile(r"[\n\r\u2028\u2029]").search(self.source, body_start, self.function_ends[id(body)])
            if line_break:
                self.import_error_spans[id(node)] = (node, offset, line_break.start())
        if getattr(arrow_token, "after_line_break", False):
            if not self.parameter_list_error(params):
                node.setdefault("diagnostics", []).append({
                    "code": 1200, "offset": arrow_token.lexpos, "length": 2,
                    "message": "line terminator not permitted before arrow"})
        elif block and self.diagnose_strict_parameters and any(param["type"] != "Identifier" for param in params):
            self.check_parameter_directive(params, body, offset, "ArrowFunctionExpression")
        return node

    def p_type_argument_probe(self, p):
        "program : TYPE_ARGS_GOAL ts_arguments"
        p[0] = p[2]

    def p_missing_tag_terminator(self, p):
        """statement : expression TAG_TERMINATOR_ERROR
                     | THROW expression TAG_TERMINATOR_ERROR"""
        expression = p[len(p)-2]
        if expression["type"] == "ChainExpression":
            expression = expression["expression"]
        if expression["type"] == "TaggedTemplateExpression":
            end = p.slice[len(p)-1].template_end
            raise self.error(self.last_tag_start, "tagged template before missing semicolon",
                             code=1443, length=end - self.last_tag_start)
        raise self.token_error(p.slice[len(p)-1], "expected semicolon", 1005)

    def p_optional_template(self, p):
        """optional_chain : optional_chain template
                          | optional_base template
                          | optional_base ts_arguments template"""
        p[0] = {"type": "TaggedTemplateExpression", "tag": p[1], "quasi": p[len(p)-1],
                "optional": p.slice[1].type == "optional_base"}
        if len(p) == 4:
            p[0]["typeArguments"] = p[2]
        elif not p[0]["optional"]:
            self.apply_callee_types(p[0], "tag")
        self.resolve_optional_continuation(p[0], "tag")
        self.last_tag_start = p.lexpos(len(p)-1)

    def p_tagged_template(self, p):
        """member : member template
           call : call template"""
        super().p_tagged_template(p)
        self.last_tag_start = p.lexpos(2)
        self.apply_callee_types(p[0], "tag")

    def p_typed_optional_call(self, p):
        "optional_chain : optional_base ts_arguments call_arguments"
        p[0] = {"type": "CallExpression", "callee": p[1], "arguments": p[3],
                "typeArguments": p[2], "optional": True}
        self.finish_call(p)

    def p_optional_instantiation(self, p):
        "optional_chain : optional_chain applied_arguments"
        p[0] = {"type": "TSInstantiationExpression", "expression": p[1], "typeArguments": p[2]}

    def p_optional_call(self, p):
        """optional_chain : optional_base call_arguments
                          | optional_chain call_arguments"""
        super().p_optional_call(p)
        self.finish_call(p)

    def finish_call(self, p):
        if p.slice[-1].trailing:
            p[0]["trailingComma"] = True
        if not p[0].get("optional") and "typeArguments" not in p[0]:
            self.apply_callee_types(p[0])
        if "optional" in p[0]:
            self.resolve_optional_continuation(p[0], "callee")

        call = p[0]
        callee = call["callee"]
        deferred = (callee["type"] == "MetaProperty" and callee["meta"]["name"] == "import"
                    and callee["property"]["name"] == "defer" and id(callee) not in self.grouped_patterns)
        if callee["type"] == "TSImportKeyword" or deferred:
            p[0] = self.import_call(p.slice[-1], self.import_keyword_offsets[id(callee)],
                                    types=call.get("typeArguments"), deferred=deferred)
            if "optional" in call:
                p[0]["optional"] = call["optional"]

    def p_super_call(self, p):
        """call : SUPER call_arguments
           decorator_call : SUPER call_arguments"""
        super().p_super_call(p)
        self.finish_call(p)

    def p_instantiation(self, p):
        """member : member applied_arguments
           call : call applied_arguments"""
        p[0] = {"type": "TSInstantiationExpression", "expression": p[1], "typeArguments": p[2]}

    def p_applied_arguments(self, p):
        """applied_arguments : CALL_TYPE_LT TYPE_GT
                             | CALL_TYPE_LT ts_type_list TYPE_GT
                             | CALL_TYPE_LT ts_type_list COMMA TYPE_GT"""
        self.p_ts_arguments(p)
        self.applied_argument_spans[id(p[0])] = (p.lexpos(1), p.lexpos(len(p)-1) + 1)

    def p_call(self, p):
        """call : member call_arguments
                | call call_arguments"""
        super().p_call(p)
        self.finish_call(p)

    def p_new(self, p):
        """new_expression : NEW new_expression
           member : NEW member call_arguments
                  | NEW member MISSING_NEW_ARGS"""
        super().p_new(p)
        has_arguments = p.slice[-1].type == "call_arguments"
        p[0]["hasArgumentList"] = has_arguments
        if p.slice[-1].type == "MISSING_NEW_ARGS":
            p[0]["arguments"] = []
        if has_arguments and p.slice[3].trailing:
            p[0]["trailingComma"] = True
        self.apply_callee_types(p[0])

    def apply_callee_types(self, node, field="callee"):
        callee = node[field]
        if callee["type"] == "TSInstantiationExpression" and id(callee) not in self.grouped_patterns:
            node[field], node["typeArguments"] = callee["expression"], callee["typeArguments"]

    def p_invalid_super(self, p):
        """primary : SUPER applied_arguments
                   | SUPER MISSING_SUPER_MEMBER"""
        p[0] = {"type": "Super"}
        if p.slice[2].type == "applied_arguments":
            start = getattr(p.slice[1], "end_pos", p.lexpos(1) + len(p[1]))
            _, end = self.applied_argument_spans[id(p[2])]
            error = self.error(start, "super may not use type arguments", code=2754, length=end - start)
            if self.script_pass is None:
                raise error
            self.script_pass.record(error)
            p[0] = {"type": "TSInstantiationExpression", "expression": p[0], "typeArguments": p[2]}

    def p_super_value(self, p):
        "primary : SUPER_VALUE"
        p[0] = {"type": "Super"}

    def p_line_break_after_throw(self, p):
        "statement : BARE_THROW SEMICOLON"
        p[0] = {"type": "ThrowStatement", "argument": None, "missingArgumentOffset": p.lexpos(1) + len(p[1])}

    def p_ts_program(self, p):
        "program : TS_GOAL module_items"
        p[0] = p[2]
        if self.pending_parameter_lists or self.pending_generic_lists:
            self.finish_signature_lists(p[0])

    def finish_signature_lists(self, statements):
        # A signature may be wrapped in a method, a type or a declare item.
        # By this reduction its final owner and ambient ancestry are both known.
        pending = [(statements, self.declaration_file)]
        invalid_methods = set()
        class_indexes = set()
        while pending:
            item, ambient = pending.pop()
            if isinstance(item, list):
                pending.extend((child, ambient) for child in item)
                continue
            if not isinstance(item, dict):
                continue
            ambient = ambient or item.get("declare", False)
            if item.get("type") in {"ClassDeclaration", "ClassExpression"}:
                abstract_class = item["type"] == "ClassDeclaration" and item.get("abstract")
                for member in item["body"]["body"]:
                    if member.get("type") == "TSIndexSignature":
                        class_indexes.add(id(member))
                    elif member.get("type") == "MethodDefinition" and (id(member["value"]["params"]) in self.pending_parameter_lists
                            or id(member["value"].get("typeParameters")) in self.pending_generic_lists):
                        if not self.method_allows_parameter_check(member, abstract_class):
                            invalid_methods.add(id(member["value"]))
            elif item.get("type") == "Property" and (item.get("method") or item.get("kind") in {"get", "set"}):
                if not self.method_allows_parameter_check(item, False):
                    invalid_methods.add(id(item["value"]))
            if self.pending_generic_lists:
                for field in ("typeArguments", "typeParameters", "superTypeArguments"):
                    generic = self.pending_generic_lists.get(id(item.get(field)))
                    if generic:
                        self.check_generic_list(item, generic, field, ambient, id(item) in invalid_methods)
            params = item.get("params", item.get("parameters"))
            mark = self.pending_parameter_lists.get(id(params))
            if mark:
                _, comma, issue = mark
                if comma is not None:
                    item["parameterListTrailingComma"] = True
                if id(item) not in invalid_methods:
                    self.check_parameter_list(item, params, comma, issue, ambient, id(item) in class_indexes)
            pending.extend((child, ambient) for child in item.values() if isinstance(child, (list, dict)))

    @staticmethod
    def check_generic_list(owner, generic, field, ambient, invalid_method):
        _, code, start, end, import_span = generic
        kind = owner["type"]
        if field == "typeParameters":
            if kind in {"TSInterfaceDeclaration", "TSTypeAliasDeclaration"} or invalid_method:
                return
            if kind not in {"ClassDeclaration", "ClassExpression"} and (
                    owner.get("decorators") or (kind == "TSMethodSignature" and owner.get("modifiers"))
                    or (ambient and owner.get("async"))):
                return
        elif import_span and (kind in {"TSInstantiationExpression", "TSExpressionWithTypeArguments"} or field == "superTypeArguments"):
            code = 1326
            start, end = import_span
        elif (code is None or kind in {"ImportExpression", "TSImportType"}
              or (kind == "TaggedTemplateExpression" and "optional" in owner)):
            return
        messages = {1098: "type parameter list cannot be empty", 1099: "type argument list cannot be empty",
                    1009: "trailing comma not allowed in type argument list", 1326: "invalid import expression with type arguments"}
        owner.setdefault("diagnostics", []).append({"code": code, "offset": start, "length": end - start, "message": messages[code]})

    @staticmethod
    def method_allows_parameter_check(member, abstract_class):
        # checkGrammarFunctionLikeDeclaration stops on a method modifier error.
        modifiers = member.get("modifiers", ())
        ranks = {"private": 0, "public": 0, "protected": 0, "static": 1, "abstract": 1, "override": 2, "async": 3}
        last = -1
        for modifier in modifiers:
            rank = ranks.get(modifier, -1)
            if rank <= last:
                return False
            last = rank
        if "abstract" in modifiers and (not abstract_class or "private" in modifiers or "async" in modifiers
                                        or member["kind"] == "constructor" or member["key"]["type"] == "PrivateIdentifier"):
            return False
        if member["kind"] == "constructor" and member.get("static"):
            return False
        if "async" in modifiers and member["kind"] in {"get", "set", "constructor"}:
            return False
        if member["key"]["type"] == "PrivateIdentifier" and member.get("accessibility"):
            return False
        return not member.get("decorators") or member["value"].get("body") is not None

    @staticmethod
    def intrinsic_index_key(annotation):
        # These forms guarantee a valid key without resolving symbols or
        # simplifying types. Other key types require the reference checker.
        pending = [annotation]
        while pending:
            node = pending.pop()
            if node["type"] == "TSParenthesizedType":
                pending.append(node["typeAnnotation"])
            elif node["type"] == "TSUnionType":
                pending.extend(node["types"])
            elif node["type"] not in {"TSStringKeyword", "TSNumberKeyword", "TSSymbolKeyword"}:
                return False
        return True

    def check_index_parameters(self, owner, params, comma, class_index):
        modifiers = tuple(owner.get("modifiers", ()))
        if owner.get("decorators") or (modifiers not in ((), ("readonly",)) and
                not (class_index and modifiers in (("static",), ("static", "readonly")))):
            return
        if len(params) != 1:
            target = owner
            start, end = self.index_spans[id(owner)]
            if params:
                target = params[0]
                start, end = self.parameter_spans[id(target.get("argument", target))]
            code, message = 1096, "index signature must have exactly one parameter"
        else:
            if comma is not None:
                owner.setdefault("diagnostics", []).append({
                    "code": 1025, "offset": comma, "length": 1, "message": "index signature cannot have a trailing comma"})
            target = params[0]
            start, end = self.parameter_spans[id(target)]
            if target["type"] == "RestElement":
                code, message = 1017, "index signature cannot have a rest parameter"
            elif target.get("modifiers"):
                code, message = 1018, "index signature parameter cannot have a modifier"
            elif target.get("left", target).get("optional"):
                start = self.optional_parameter_offsets[id(target.get("left", target))]
                end = start + 1
                code, message = 1019, "index signature parameter cannot have a question mark"
            elif target["type"] == "AssignmentPattern":
                code, message = 1020, "index signature parameter cannot have an initializer"
            elif not target.get("typeAnnotation"):
                code, message = 1022, "index signature parameter must have a type annotation"
            elif not owner.get("typeAnnotation") and self.intrinsic_index_key(target["typeAnnotation"]["typeAnnotation"]):
                target = owner
                start, end = self.index_spans[id(owner)]
                code, message = 1021, "index signature must have a type annotation"
            else:
                return
        target.setdefault("diagnostics", []).append({"code": code, "offset": start, "length": end - start, "message": message})

    def check_parameter_list(self, owner, params, comma, issue, ambient, class_index):
        if owner["type"] == "TSIndexSignature":
            self.check_index_parameters(owner, params, comma, class_index)
            return
        if (owner.get("decorators") or (owner["type"] == "TSMethodSignature" and owner.get("modifiers"))
                or (ambient and owner.get("async"))
                or (owner["type"] in {"FunctionDeclaration", "TSDeclareFunction"}
                    and any(m in {"static", "public", "protected", "private", "readonly", "const"} for m in owner.get("modifiers", ())))
                or (owner.get("typeParameters") and not owner["typeParameters"]["params"])):
            return
        if (comma is not None and not ambient and params[-1]["type"] == "RestElement"
                and (not issue or issue[0] == len(params) - 1)):
            owner.setdefault("diagnostics", []).append({
                "code": 1013, "offset": comma, "length": 1, "message": "rest parameter cannot have a trailing comma"})
        if issue:
            index, code = issue
            param = params[index]
            if code == 1047:
                argument = param["argument"]
                start = self.optional_parameter_offsets[id(argument.get("left", argument))]
                end = start + 1
            else:
                target = param["argument"] if code == 1048 else param
                start, end = self.parameter_spans[id(target)]
            messages = {1014: "rest parameter must be last", 1015: "optional parameter cannot have an initializer",
                        1016: "required parameter cannot follow an optional parameter", 1047: "rest parameter cannot be optional",
                        1048: "rest parameter cannot have an initializer"}
            param.setdefault("diagnostics", []).append({"code": code, "offset": start, "length": end - start, "message": messages[code]})


class TypeArgumentProbe(TypeScriptGrammar):
    def dialect_token(self, parser, token, previous, peek, upcoming):
        if self.goal_token() == "TYPE_ARGS_GOAL":
            # TypeScript can commit a speculative list even when it diagnosed
            # a keyword escape or inserted a missing operand. Only the fresh
            # parse of the selected branch reports these errors.
            if getattr(token, "escaped", False):
                token.type = self.keywords.get(token.value, token.type)
                token.escaped = False
            if (previous and previous.type in {"TYPE_OPERATOR", "INFER", "TYPEOF"}
                    and (token.value.startswith(">") or token.type in {"COMMA", "DOT"})
                    and accepts_lookahead(parser, "IDENTIFIER")):
                upcoming.appendleft(copy(token))
                token.type, token.value, token.end_pos = "IDENTIFIER", "", token.lexpos
                token.escaped = False
        super().dialect_token(parser, token, previous, peek, upcoming)

    def has_arrow_head(self, opening, outer_parser=None, *, ordinary=False):
        return False

    def goal_token(self):
        return "TYPE_ARGS_GOAL"

    def can_start_type_arguments(self, opening):
        return False


class ReturnArmProbe(TypeArgumentProbe):
    def goal_token(self):
        return "RETURN_ARM_GOAL"

    def has_typed_conditional_arm(self, colon, conditional):
        return False


class ReturnTypeProbe(ReturnArmProbe):
    def goal_token(self):
        return "RETURN_TYPE_GOAL"


class InferBoundProbe(TypeArgumentProbe):
    def goal_token(self):
        return "INFER_BOUND_GOAL"

    def has_infer_bound(self, opening):
        return False


class BindingProbe(TypeArgumentProbe):
    def goal_token(self):
        return "BINDING_PROBE_GOAL"

    def binding_starts_formals(self, first):
        return False


class ArrowHeadProbe(TypeScriptGrammar):
    def goal_token(self):
        return "ORDINARY_ARROW_PROBE" if self.ordinary_arrow_probe else "ARROW_PROBE"


class TsxGrammar(JsxRules, TypeScriptGrammar):
    allow_angle_assertions = False


    tokens = TypeScriptGrammar.tokens + JsxRules.jsx_tokens + ("JSX_TYPE_LT", "JSX_TYPE_GT")
    lexical_dialect_types = TypeScriptGrammar.lexical_dialect_types | set(JsxRules.jsx_tokens)

    def reset(self, source, source_type):
        super().reset(source, source_type)
        self.jsx_mode = "js"
        self.jsx_elements = []
        self.jsx_exprs = []

    def dialect_token(self, parser, token, previous, peek, upcoming):
        if self.script_pass is not None and token.type == "JSX_GT":
            token.pending_jsx_tokens = upcoming
        if getattr(token, "in_js_expression", False):
            self.closing_tag_in_expression(parser, token, previous, upcoming)
            return
        if hasattr(token, "jsx_name_mode") and not accepts_lookahead(parser, token.type):
            self.recover_jsx_name_punctuation(parser, token, previous, upcoming)
        if (previous and previous.type in {"JSX_DOT", "JSX_COLON"} and token.type in {"JSX_GT", "JSX_SLASH_GT"}
                and not accepts_lookahead(parser, token.type)):
            # The ordinary scanner reads the slash before the closing angle.
            error = self.error(token.lexpos, "identifier expected in JSX name", code=1003, length=1)
            if self.script_pass is None or not accepts_lookahead(parser, "JSX_NAME", token.type):
                raise error
            self.script_pass.record(error)
            upcoming.appendleft(copy(token))
            token.type, token.value, token.end_pos = "JSX_NAME", "", token.lexpos
        if hasattr(token, "jsx_escape_error"):
            error = token.jsx_escape_error
            dash = token.value.find("-") if previous.type in {"JSX_DOT", "JSX_EQUALS"} else -1
            if dash < 0 or error.offset <= token.lexpos + dash:
                # JSX child scanning can rescan a binary marker as text and
                # reach the parent's closing tag. At source level the scanner
                # consumes the remainder of the file.
                if self.script_pass is None or (error.code == 1490 and "text" not in self.jsx_elements
                                                and not any(mode == "text" for mode, _ in self.jsx_exprs)):
                    raise error
                self.script_pass.record(error)
                return
        if previous and previous.type == "JSX_EQUALS" and token.type == "JSX_NAME":
            # The initial attribute-value scan reads an ordinary identifier.
            # JSX rescanning of its hyphenated suffix occurs only afterwards.
            length = len(token.value.partition("-")[0])
            error = self.error(token.lexpos, "JSX attribute value expected", code=1145, length=length)
            if self.script_pass is None:
                raise error
            self.script_pass.record(error)
            upcoming.appendleft(copy(token))
            token.type, token.value, token.cooked = "JSX_STRING", '""', ""
            return
        if token.type == "JSX_NAME" and "\\" in token.value and accepts_lookahead(parser, "JSX_NAME"):
            # A member after a dot uses ordinary IdentifierName scanning.
            spelling = token.value.partition("-")[0] if previous.type == "JSX_DOT" else token.value
            if "\\" in spelling:
                error = self.error(token.lexpos, "Unicode escape in JSX name", code=17021, length=len(spelling))
                if self.script_pass is None:
                    raise error
                self.script_pass.record(error)
                return
        if token.type == "JSX_NAME" and previous.type == "JSX_DOT" and "-" in token.value:
            # A dotted JSX member uses the ordinary identifier scanner. The
            # remaining dash starts a minus, decrement or assignment token.
            offset = token.lexpos + token.value.index("-")
            width = 2 if self.source.startswith(("--", "-="), offset) else 1
            closing = parser.symstack[-3].type == "JSX_CLOSE_LT"
            error = self.error(offset, "hyphen in JSX member name", code=1005 if closing else 1003, length=width)
            suffix = token.lexpos + token.value.rindex("-") + 1
            if (self.script_pass is None or suffix == token.lexpos + len(token.value)
                    or (self.source[suffix] == "\\" and self.identifier_escape_digits_end(suffix, True) is None)):
                raise error
            self.script_pass.record(error)
            return
        if (previous and previous.type == "JSX_EXPR_OPEN" and token.type != "ELLIPSIS"
                and accepts_lookahead(parser, "ELLIPSIS") and not accepts_lookahead(parser, "REGEXP")):
            # A brace in an opening tag starts a spread attribute. The reference
            # parser continues with its expression even when the dots are missing.
            error = self.token_error(token, "expected '...' in JSX spread attribute", 1005)
            if self.script_pass is None:
                raise error
            self.script_pass.record(error)
            upcoming.appendleft(copy(token))
            if token.type == "JSX_EXPR_END":
                upcoming.appendleft(inserted_token(previous, "IDENTIFIER", ""))
            token.type, token.value, token.end_pos = "ELLIPSIS", "...", token.lexpos
        if token.type == "JSX_EOF":
            self.check_jsx_eof(parser, token, previous)
        if previous and previous.type == "JSX_CLOSE_LT":
            expects_name = accepts_lookahead(parser, "JSX_NAME")
            if expects_name and (token.type == "JSX_GT" or token.value.startswith("*")):
                raise self.token_error(token, "identifier expected in JSX closing tag", 1003)
            if not expects_name and (token.type == "JSX_NAME" or token.value.startswith("*")):
                # The fragment parser sees an ordinary identifier before JSX
                # name rescanning can include a hyphenated suffix.
                length = len(token.value.partition("-")[0])
                raise self.error(token.lexpos, "expected JSX fragment closing tag", code=17015, length=length)
        if (token.type == "RELATION" and token.value == "<" and previous and previous.type in {"JSX_GT", "JSX_SLASH_GT"}
                and accepts_lookahead(parser, "JSX_AFTER_LT")):
            # Only an update expression can be the direct left operand of **.
            # A JSX operand of a prefix unary expression takes the comparison path.
            if accepts_lookahead(parser, "POWER") and accepts_lookahead(parser, "JSX_ADJACENT"):
                upcoming.appendleft(copy(token))
                token.type, token.value = "JSX_ADJACENT", ""
                token.lexpos = token.end_pos = previous.lexpos + len(previous.value)
                token.lineno = getattr(previous, "end_line", previous.lineno)
            else:
                token.type = "JSX_AFTER_LT"
        elif (previous and previous.type in {"JSX_GT", "JSX_SLASH_GT"}
              and accepts_lookahead(parser, "JSX_ADJACENT_END") and not accepts_lookahead(parser, token.type)):
            # Reduce the complete sibling group before reporting a later invalid suffix.
            upcoming.appendleft(copy(token))
            token.type, token.value, token.end_pos = "JSX_ADJACENT_END", "", token.lexpos
        super().dialect_token(parser, token, previous, peek, upcoming)
        if token.type == "JSX_LT" and accepts_lookahead(parser, "JSX_TYPE_LT"):
            # The tag scanner encountered '<' after the opening tag name.
            self.jsx_elements.pop()
            self.jsx_mode = "js"
            token.type = "JSX_TYPE_LT"
            token.type_argument_scope = token.enclosing_scope
        elif token.type in {"RELATION", "SHIFT", "COMPOUND_ASSIGN"} and token.value.startswith(">"):
            if accepts_lookahead(parser, "JSX_TYPE_GT"):
                # A remaining '>' closes the opening JSX tag and belongs to
                # its scanner, including when the type scanner saw '>>'.
                token.type, token.value = "JSX_TYPE_GT", ">"
                self.lexer.lexpos, self.lexer.lineno = token.lexpos + 1, token.lineno
                upcoming.clear()
                self.jsx_mode = "tag"
        else:
            self.start_jsx(parser, token, upcoming)
        if token.type == "JSX_LT":
            token.adjacent_element = previous is not None and previous.type == "JSX_ADJACENT"
            token.jsx_full_start = getattr(previous, "end_pos", previous.lexpos + len(previous.value)) if previous else 0


class TsxArrowHeadProbe(TsxGrammar, ArrowHeadProbe):
    pass


class TypeScriptPipeline(JavaScriptPipeline):
    grammar_class = TypeScriptGrammar

    def __init__(self, filename="input.ts"):
        self.path = Path(filename)
        # The compiler recognizes both path separators when deriving the source-file kind.
        name = self.path.name.rsplit("\\", 1)[-1]
        self.syntax_options = SyntaxOptions()
        self.script_kind = "TSX" if name.lower().endswith(".tsx") else "TS"
        if self.script_kind == "TSX":
            self.grammar_class = TsxGrammar
        self.declaration_file = name.endswith((".d.mts", ".d.cts")) or (name.endswith(".ts") and ".d." in name)
        self.restrict_angles = name.endswith((".mts", ".cts"))

    @classmethod
    def from_path(cls, path: Path):
        return cls(path)

    def configure_grammar(self, grammar, *, first_pass_contexts=None, script_context_offsets=(), script_pass=None):
        super().configure_grammar(grammar)
        grammar.import_module = self.syntax_options.effective_module()
        if self.syntax_options.verbatim_module_syntax and grammar.import_module == "commonjs":
            grammar.verbatim_import_error = 1286 if self.path.name.endswith(".cts") else 1295
        grammar.script_pass = script_pass
        grammar.recover_regexp = first_pass_contexts is not None and script_pass is not None and "/" in grammar.source
        grammar.first_pass_contexts = first_pass_contexts
        grammar.script_context_offsets = script_context_offsets
        grammar.last_possible_arrow = grammar.source.rfind("=>")
        target = self.syntax_options.target
        if target == "esnext":
            grammar.regexp_target_year = 2024
        elif target == "es6":
            grammar.regexp_target_year = 2015
        else:
            grammar.regexp_target_year = int(target.removeprefix("es"))
        grammar.identifier_char = es5_identifier_char if self.syntax_options.target == "es5" else Grammar.identifier_char
        grammar.diagnose_strict_parameters = self.syntax_options.target not in {"es5", "es6", "es2015"}
        grammar.allow_angle_assertions = self.script_kind != "TSX"
        grammar.restrict_angles = self.restrict_angles
        grammar.always_strict = self.syntax_options.always_strict and not self.declaration_file
        if grammar.always_strict:
            grammar.strict_regions.append((0, len(grammar.source)))

    def jsx_implies_module(self):
        return (not self.declaration_file and self.script_kind == "TSX" and
                self.syntax_options.module_detection == "auto" and
                self.syntax_options.jsx in {"react-jsx", "react-jsxdev"})

    def is_external_module(self, root, source):
        explicit = {"ImportDeclaration", "ExportNamedDeclaration", "ExportDefaultDeclaration",
                    "ExportAllDeclaration", "TSExportAssignment"}
        if any(stmt["type"] in explicit or (stmt["type"] == "TSImportEqualsDeclaration" and
               stmt["moduleReference"]["type"] == "TSExternalModuleReference") for stmt in root["body"]):
            return True
        automatic_jsx = self.jsx_implies_module()
        if not automatic_jsx and "import" not in source:
            return False
        pending = list(root["body"])
        while pending:
            node = pending.pop()
            if isinstance(node, list):
                pending.extend(node)
            elif isinstance(node, dict):
                if automatic_jsx and node.get("type") in {"JSXElement", "JSXFragment"}:
                    return True
                if (node.get("type") == "MetaProperty" and node["meta"]["name"] == "import"
                        and node["property"]["name"] == "meta"):
                    return True
                pending.extend(node.values())
        return False

    def tokenize(self, source):
        tokens = []
        self._parse(source, tokens)
        return tokens

    def _parse(self, source, collected):
        # An import/export makes a .ts or .tsx file an external module. Replay
        # with Module's Await and strict contexts when the first tree proves it.
        forced = self.syntax_options.forces_module(self.path, self.declaration_file)
        track_contexts = ("await" in source or "\\u" in source) and (
            "{" in source or "type" in source or ("[" in source and "class" in source)
            or any(word in source for word in ("module", "namespace", "global")))
        if forced and not track_contexts:
            result = self._parse_goal(source, collected, "module")
        else:
            script = ScriptPass()
            first_pass_contexts = {} if track_contexts else None
            stopped_at = len(source)
            try:
                result = self._parse_goal(source, collected, "script", first_pass_contexts=first_pass_contexts,
                                          script_pass=script)
            except SourceSyntaxError as error:
                result = None
                # A binary-file marker spans the rest of the input but reports
                # its diagnostic at offset zero.
                stopped_at = len(source) if error.code == 1490 else error.offset
                script.record(error)

            known_module = (forced or script.incomplete_module_indicator or (script.has_jsx and self.jsx_implies_module())
                            or self.is_external_module({"body": script.statements}, source))
            if known_module or result is None:
                if collected is not None:
                    collected.clear()
                offsets = set()
                if first_pass_contexts:
                    for statement in script.statements:
                        offsets.update(retained_context_offsets(statement, first_pass_contexts))
                try:
                    result = self._parse_goal(source, collected, "module", script_context_offsets=offsets)
                except SourceSyntaxError as module_error:
                    if known_module or module_error.offset > stopped_at:
                        raise
                    raise script.first_error from None
                if script.first_error and not forced and not self.is_external_module(result, source):
                    raise script.first_error
            elif script.first_error:
                raise script.first_error
        result.update(scriptKind=self.script_kind, declarationFile=self.declaration_file)
        directives = references(source)
        if directives:
            result["references"] = directives
        return result
