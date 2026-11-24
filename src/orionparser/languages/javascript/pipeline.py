"""ECMAScript Script and Module pipelines."""
from collections import deque
from copy import copy
import re
import threading
import unicodedata

from ply import lex, yacc

from orionparser.core.encoding import read_file
from orionparser.core.pipeline import BasePipeline, ParseResult
from .scopes import validate_scopes
from .modules import ModuleRules, check_exports
from .meta import validate_meta
from .regexp import read_regexp
from .templates import TemplateRules, template_part
from .classes import ClassRules, validate_private
from .arrows import ArrowRules
from .bindings import BindingRules, assignment_pattern, bound_names, check_loop_scope
from .control_flow import ControlFlowRules, validate_jumps
from .functions import FunctionAndObjectRules
from .strict import STRICT_IDENTIFIERS, StrictRules
from .identifiers import identifier_char, scan_identifier
from .strings import read_string


_LINE_BREAK = re.compile(r"\r\n|[\n\r\u2028\u2029]")


class SourceSyntaxError(ValueError):
    def __init__(self, offset, message, *, code=None, length=None):
        super().__init__(message)
        self.offset = offset
        self.code = code
        self.length = length


class Grammar(FunctionAndObjectRules, ControlFlowRules, BindingRules, StrictRules, ArrowRules, ClassRules, TemplateRules, ModuleRules):
    identifier_char = staticmethod(identifier_char)
    check_duplicate_proto = True
    allow_html_comments = True
    allow_legacy_numeric_literals_and_escapes = True
    additional_openers = frozenset()
    lexical_dialect_types = frozenset()
    tokens = (
        "ANNEX_FUNCTION", "OPTIONAL", "ASYNC_ARROW", "ASYNC_SINGLE", "DECL_ASYNC", "EXPR_ASYNC", "DEFAULT_ASYNC", "ASYNC_METHOD",
        "ASYNC_PARAMS", "ASYNC_GEN_PARAMS", "ASYNC_OPEN", "ASYNC_GEN_OPEN",
        "PRIVATE_NAME", "STATIC_OPEN", "SUPER", "REGEXP", "TEMPLATE", "TEMPLATE_HEAD", "TEMPLATE_MIDDLE", "TEMPLATE_TAIL",
        "UNTAGGED_TEMPLATE_HEAD", "UNTAGGED_TEMPLATE_MIDDLE", "UNTAGGED_TEMPLATE_TAIL",
        "CLASS_STATIC", "CLASS_ACCESSOR", "CLASS", "DECL_CLASS", "EXTENDS",
        "AWAIT", "SCRIPT_GOAL", "MODULE_GOAL", "IMPORT", "EXPORT", "AS", "FROM", "DEFAULT_FUNCTION", "DEFAULT_CLASS",
        "ARROW", "WITH",
        "FN_OPEN", "GEN_OPEN", "FN_PARAMS", "GEN_PARAMS", "YIELD", "BARE_YIELD",
        "BIND_ARRAY", "BIND_OBJECT",
        "BREAK", "CONTINUE", "BREAK_STMT", "CONTINUE_STMT", "WHILE", "DO", "DO_SEMI",
        "SWITCH", "CASE", "DEFAULT",
        "IN", "OF", "TRY", "CATCH", "FINALLY", "INSTANCEOF",
        "SHIFT", "BIT_AND", "BIT_OR", "BIT_XOR", "AND", "OR", "COALESCE", "QUESTION",
        "FUNCTION", "DECL_FUNCTION", "RETURN", "RETURN_STMT", "OBJECT_OPEN", "COLON",
        "SEMICOLON", "LBRACE", "RBRACE", "DEBUGGER", "IDENTIFIER", "NUMBER",
        "NULL", "TRUE", "FALSE", "THIS", "LPAREN", "RPAREN", "PLUS", "MINUS",
        "MULTIPLY", "DIVIDE", "REMAINDER", "POWER", "NOT", "BIT_NOT",
        "TYPEOF", "VOID", "DELETE", "LBRACKET", "RBRACKET", "DOT", "COMMA",
        "EQUALITY", "NEW", "IF", "ELSE", "THROW", "EMPTY_SEMI", "ELLIPSIS", "FOR", "FOR_SEMI", "RELATION", "STRING", "ASSIGN", "COMPOUND_ASSIGN", "VAR", "LET", "CONST",
        "RESERVED", "INCREMENT", "DECREMENT", "POST_INCREMENT", "POST_DECREMENT",
    )
    t_OPTIONAL = r"\?\.(?![0-9])"
    t_ARROW = r"=>"
    t_SHIFT = r">>>|>>|<<"
    t_BIT_AND = r"&"
    t_BIT_OR = r"\|"
    t_BIT_XOR = r"\^"
    t_AND = r"&&"
    t_OR = r"\|\|"
    t_COALESCE = r"\?\?"
    t_QUESTION = r"\?"
    t_EQUALITY = r"===|!==|==|!="
    t_ELLIPSIS = r"\.\.\."
    t_RELATION = r"<=|>=|<(?!<)|>(?!>)"
    t_COMPOUND_ASSIGN = r"(?:>>>|>>|<<|\*\*|&&|\|\||\?\?|[+*/%&^|\-])="
    t_ASSIGN = r"="
    t_COLON = r":"
    t_SEMICOLON = r";"
    t_LPAREN = r"\("
    t_RPAREN = r"\)"
    t_LBRACKET = r"\["
    t_RBRACKET = r"\]"
    t_DOT = r"\."
    t_COMMA = r","
    t_INCREMENT = r"\+\+"
    t_DECREMENT = r"--"
    t_PLUS = r"\+"
    t_MINUS = r"-"
    t_MULTIPLY = r"\*"
    t_POWER = r"\*\*"
    t_DIVIDE = r"/"
    t_REMAINDER = r"%"
    t_NOT = r"!"
    t_BIT_NOT = r"~"
    t_ignore = " \t\v\f\ufeff"
    precedence = (("nonassoc", "IF_NO_ELSE"), ("nonassoc", "ELSE"))
    start = "program"

    keywords = {word: word.upper() for word in
                ("debugger", "null", "true", "false", "this", "typeof", "void", "delete", "var", "let", "const", "for", "new", "if", "else", "throw", "return", "function", "try", "catch", "finally", "instanceof", "in",
                 "break", "continue", "while", "do", "switch", "case", "default", "with", "class", "extends", "super", "import", "export")}
    reserved = {"enum"}

    def t_PRIVATE_NAME(self, token):
        r"\#(?![!])"
        end, token.value = self.read_identifier(token, token.lexpos + 1)
        if not token.value:
            return self.invalid_character(token)
        token.lexer.lexpos = token.end_pos = end
        return token

    def t_IDENTIFIER(self, token):
        r"[A-Za-z_$\\]|[^\x00-\x7f]"
        if token.value in "\u2028\u2029":
            self.line_has_token = False
            token.lexer.lineno += 1
            return
        if unicodedata.category(token.value) == "Zs":
            return
        if not token.value.isascii() and not self.identifier_char(token.value, first=True):
            return self.invalid_character(token)
        end, token.value = self.read_identifier(token, token.lexpos)
        if not token.value:
            return self.invalid_character(token)
        token.lexer.lexpos = token.end_pos = end
        token.escaped = end - token.lexpos != len(token.value)
        if token.escaped and token.value in self.keywords and token.value != "let":
            token.type = "RESERVED"
            return token
        if token.value in self.reserved or (
            self.source_type == "module" and token.value in {
                "await", "yield", "static", "implements", "interface",
                "package", "private", "protected", "public",
            }
        ):
            token.type = "RESERVED"
            return token
        token.type = "IDENTIFIER" if token.escaped else self.keywords.get(token.value, "IDENTIFIER")
        return token

    def t_TEMPLATE(self, token):
        r"`"
        return template_part(self, token, initial=True)

    def t_LBRACE(self, token):
        r"\{"
        if self.template_braces:
            self.template_braces[-1] += 1
        return token

    def t_RBRACE(self, token):
        r"\}"
        if self.template_braces:
            if not self.template_braces[-1]:
                return template_part(self, token, initial=False)
            self.template_braces[-1] -= 1
        return token

    def advance_multiline(self, token, end):
        token.lexer.lexpos = end
        token.lexer.lineno += len(_LINE_BREAK.findall(token.value))
        token.end_line = token.lexer.lineno

    def string_error(self, offset, reason):
        return self.error(offset, reason)

    def t_STRING(self, token):
        r"""['"]"""
        strict_escapes = self.source_type == "module" or not self.allow_legacy_numeric_literals_and_escapes
        end, token.cooked = read_string(self.source, token.lexpos, strict_escapes, self.string_error)
        token.value = self.source[token.lexpos:end]
        if not strict_escapes and re.search(r"\\[0-9]", token.value):
            try:
                read_string(self.source, token.lexpos, True, self.error)
            except ValueError:
                self.strict_violation(token.lexpos, "legacy decimal escape in strict code")
        self.advance_multiline(token, end)
        return token

    def t_NUMBER(self, token):
        r"""(?:0[xX][0-9A-Fa-f](?:_?[0-9A-Fa-f])*n?
             |0[bB][01](?:_?[01])*n?
             |0[oO][0-7](?:_?[0-7])*n?
             |(?:0|[1-9](?:_?[0-9])*)n
             |(?:(?:0[0-7]*[89][0-9]*|0(?![0-9])|[1-9](?:_?[0-9])*)(?:\.(?:[0-9](?:_?[0-9])*)?)?
                 |\.[0-9](?:_?[0-9])*)(?:[eE][+-]?[0-9](?:_?[0-9])*)?
             |0[0-7]+)"""
        following = self.source[token.lexer.lexpos:token.lexer.lexpos + 1]
        if following and (following in "0123456789" or following == "\\" or self.identifier_char(following, first=True)):
            self.check_number_suffix(token, following)
        if len(token.value) > 1 and token.value[0] == "0" and token.value[1] in "0123456789":
            self.legacy_number(token)
        return token

    def legacy_number(self, token):
        if not self.allow_legacy_numeric_literals_and_escapes:
            raise self.error(token.lexpos, "legacy numeric literal")
        self.strict_violation(token.lexpos, "legacy numeric literal")

    def check_number_suffix(self, token, following):
        raise self.error(token.lexer.lexpos, "invalid character after numeric literal")

    def t_line_break(self, token):
        r"\r\n|[\n\r\u2028\u2029]"
        self.line_has_token = False
        token.lexer.lineno += 1

    def t_comment(self, token):
        r"//[^\n\r\u2028\u2029]*|/\*|\A\#\![^\n\r\u2028\u2029]*"
        if token.value == "/*":
            closing = self.source.find("*/", token.lexer.lexpos)
            if closing < 0:
                raise self.error(token.lexpos, "unterminated block comment")
            token.lexer.lexpos = closing + 2
            token.value = self.source[token.lexpos:token.lexer.lexpos]
        breaks = len(_LINE_BREAK.findall(token.value))
        token.lexer.lineno += breaks
        if breaks:
            self.line_has_token = False

    def t_html_comment(self, token):
        r"<!--|-->"
        opener = token.value == "<!--"
        if self.allow_html_comments and self.source_type == "script" and (opener or not self.line_has_token):
            end = _LINE_BREAK.search(self.source, token.lexer.lexpos)
            token.lexer.lexpos = end.start() if end else len(self.source)
            return
        token.type, token.value = ("RELATION", "<") if opener else ("DECREMENT", "--")
        token.lexer.lexpos = token.lexpos + len(token.value)
        return token

    def raw_tokens(self):
        for token in self.lexer:
            self.line_has_token = True
            yield token

    def t_error(self, token):
        if unicodedata.category(token.value[0]) == "Zs":
            token.lexer.skip(1)
            return
        return self.invalid_character(token)

    def read_identifier(self, token, start):
        if start == len(self.source):
            raise self.error(token.lexpos, "missing private name")
        return scan_identifier(self.source, start, self.error, self.identifier_char)

    def invalid_character(self, token):
        raise self.invalid_character_error(token.lexpos, self.source[token.lexpos])

    def invalid_character_error(self, offset, char):
        return self.error(offset, repr(char))

    def error(self, offset, found, *, code=None, length=None):
        lines = _LINE_BREAK.split(self.source[:offset])
        message = f"line {len(lines)}, column {len(lines[-1]) + 1}: unexpected {found}"
        if code is not None:
            message += f" (TS{code})"
        return SourceSyntaxError(offset, message, code=code, length=length)

    def p_body(self, p):
        """body :
                | body list_item"""
        if len(p) == 1:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_list_item(self, p):
        """list_item : statement
                     | class_declaration
                     | function_declaration
                     | lexical_declaration SEMICOLON"""
        p[0] = p[1]

    def p_empty_statement(self, p):
        "statement : EMPTY_SEMI"
        p[0] = {"type": "EmptyStatement"}

    def p_block(self, p):
        "block : LBRACE body RBRACE"
        p[0] = {"type": "BlockStatement", "body": p[2]}

    def p_block_statement(self, p):
        "statement : block"
        p[0] = p[1]

    def p_try_statement(self, p):
        """statement : TRY block catch_clause
                     | TRY block FINALLY block
                     | TRY block catch_clause FINALLY block"""
        handler = p[3] if p.slice[3].type == "catch_clause" else None
        finalizer = p[len(p) - 1] if len(p) > 4 else None
        p[0] = {"type": "TryStatement", "block": p[2], "handler": handler, "finalizer": finalizer}

    def p_catch_clause(self, p):
        """catch_clause : CATCH block
                        | CATCH LPAREN binding RPAREN block"""
        param = p[3] if len(p) == 6 else None
        names = list(bound_names(param)) if param else []
        if self.check_declaration_early_errors and len(set(names)) < len(names):
            raise self.error(p.lexpos(3), "duplicate catch binding")
        if {"eval", "arguments"}.intersection(names):
            self.strict_violation(p.lexpos(3), "invalid strict catch binding")
        p[0] = {"type": "CatchClause", "param": param, "body": p[len(p) - 1]}

    def p_debugger(self, p):
        "statement : DEBUGGER SEMICOLON"
        p[0] = {"type": "DebuggerStatement"}

    def p_expression_statement(self, p):
        "statement : expression SEMICOLON"
        p[0] = {"type": "ExpressionStatement", "expression": p[1]}

    def p_annex_function(self, p):
        "annex_function : ANNEX_FUNCTION identifier formals function_body"
        self.strict_violation(p.lexpos(1), "legacy function declaration in strict code")
        p[0] = self.function_node("FunctionDeclaration", p[2], p[3], p[4], p.lexpos(1))

    def p_if_arm(self, p):
        """if_arm : statement
                  | annex_function"""
        p[0] = p[1]

    def p_if(self, p):
        """statement : IF LPAREN expression RPAREN if_arm %prec IF_NO_ELSE
                     | IF LPAREN expression RPAREN if_arm ELSE if_arm"""
        p[0] = {"type": "IfStatement", "test": p[3], "consequent": p[5],
                "alternate": p[7] if len(p) == 8 else None}

    def p_with(self, p):
        "statement : WITH LPAREN expression RPAREN statement"
        p[0] = {"type": "WithStatement", "object": p[3], "body": p[5]}
        self.strict_statement(p[0], p.slice[1], "with statement in strict code")

    def p_throw(self, p):
        "statement : THROW expression SEMICOLON"
        p[0] = {"type": "ThrowStatement", "argument": p[2]}

    def p_conditional(self, p):
        """conditional : short_circuit
                       | short_circuit QUESTION assignment COLON assignment
           conditional_no_in : short_circuit_no_in
           conditional_no_in : short_circuit_no_in QUESTION assignment COLON assignment_no_in"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            p[0] = {"type": "ConditionalExpression", "test": p[1], "consequent": p[3], "alternate": p[5]}

    def p_short_circuit(self, p):
        """short_circuit : logical_or
                         | coalesce
           short_circuit_no_in : logical_or_no_in
                               | coalesce_no_in"""
        p[0] = p[1]

    def p_operator_operand(self, p):
        """logical_or : logical_and
           logical_and : bit_or
           bit_or : bit_xor
           bit_xor : bit_and
           bit_and : equality
           equality : relational
           relational : shift
           shift : additive
           logical_or_no_in : logical_and_no_in
           logical_and_no_in : bit_or_no_in
           bit_or_no_in : bit_xor_no_in
           bit_xor_no_in : bit_and_no_in
           bit_and_no_in : equality_no_in
           equality_no_in : relational_no_in
           relational_no_in : shift"""
        p[0] = p[1]

    def p_logical_operator(self, p):
        """logical_or : logical_or OR logical_and
           logical_and : logical_and AND bit_or
           logical_or_no_in : logical_or_no_in OR logical_and_no_in
           logical_and_no_in : logical_and_no_in AND bit_or_no_in"""
        p[0] = {"type": "LogicalExpression", "operator": p[2], "left": p[1], "right": p[3]}

    def p_coalesce(self, p):
        """coalesce : bit_or COALESCE bit_or
                    | coalesce COALESCE bit_or
           coalesce_no_in : bit_or_no_in COALESCE bit_or_no_in
           coalesce_no_in : coalesce_no_in COALESCE bit_or_no_in"""
        self.p_logical_operator(p)

    def p_for(self, p):
        "statement : FOR LPAREN for_init FOR_SEMI optional_expression FOR_SEMI optional_expression RPAREN statement"
        if self.check_declaration_early_errors:
            check_loop_scope(self, p[3], p[9], p.lexpos(1))
        p[0] = {"type": "ForStatement", "init": p[3], "test": p[5], "update": p[7], "body": p[9]}

    def p_for_init(self, p):
        """for_init :
                    | expression_no_in
                    | for_declaration"""
        p[0] = p[1] if len(p) == 2 else None
        if p[0] and p[0]["type"] == "VariableDeclaration":
            self.validate_initializers(p[0], p.lexpos(1))

    def p_for_declaration(self, p):
        """for_declaration : VAR declarators_no_in
                           | LET declarators_no_in
                           | CONST declarators_no_in"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = self.variable_declaration(p[1], p[2], p.lexpos(1))

    def p_async_for(self, p):
        "async_for : FOR AWAIT"
        p.set_lexpos(0, p.lexpos(1))

    typescript_regexp = False
    regexp_target_year = 2024
    check_meta_early_errors = True
    check_assignment_targets = True
    check_declaration_early_errors = True
    allow_parameter_operators = False
    allow_line_break_before_arrow = False

    def p_iteration(self, p):
        """statement : FOR LPAREN chain IN expression RPAREN statement
                     | FOR LPAREN chain OF assignment RPAREN statement
                     | FOR LPAREN for_declaration IN expression RPAREN statement
                     | FOR LPAREN for_declaration OF assignment RPAREN statement
                     | async_for LPAREN chain OF assignment RPAREN statement
                     | async_for LPAREN for_declaration OF assignment RPAREN statement"""
        left = p[3]
        is_of = p[4] == "of"
        is_await = p.slice[1].type == "async_for"
        if left["type"] != "VariableDeclaration":
            left = assignment_pattern(self, left, p.lexpos(4), allow_expression=not self.check_assignment_targets)
        elif self.check_declaration_early_errors:
            bindings = left["declarations"]
            if not is_of and left["kind"] in {"using", "await using"}:
                raise self.error(p.lexpos(4), "using declaration in for-in")
            if len(bindings) != 1:
                raise self.error(p.lexpos(4), "multiple iteration bindings")
            if bindings[0]["init"] is not None and (is_of or left["kind"] != "var" or bindings[0]["id"]["type"] != "Identifier"):
                raise self.error(p.lexpos(4), "initializer in iteration binding")
            if bindings[0]["init"] is not None:
                self.strict_violation(p.lexpos(4), "initializer in strict for-in")
        if self.check_assignment_targets and is_of and left["type"] != "VariableDeclaration":
            head = p.slice[2].first_for_token
            if not getattr(head, "escaped", False) and (head.value == "let" or (not is_await and head.value == "async" and left.get("name") == "async")):
                raise self.error(head.lexpos, "invalid for-of target")
        if self.check_declaration_early_errors:
            check_loop_scope(self, left, p[7], p.lexpos(1))
        p[0] = {"type": "ForOfStatement" if is_of else "ForInStatement",
                "left": left, "right": p[5], "body": p[7]}
        if is_of:
            p[0]["await"] = is_await

    def p_optional_expression(self, p):
        """optional_expression :
                               | expression"""
        p[0] = p[1] if len(p) == 2 else None

    def p_declaration_statement(self, p):
        "statement : variable_declaration SEMICOLON"
        p[0] = p[1]

    def p_declaration(self, p):
        """variable_declaration : VAR declarators
           lexical_declaration : LET declarators
                     | CONST declarators"""
        p[0] = self.variable_declaration(p[1], p[2], p.lexpos(1))
        self.validate_initializers(p[0], p.lexpos(1))

    def variable_declaration(self, kind, items, offset):
        if self.check_declaration_early_errors and kind != "var":
            names = [name for item in items for name in bound_names(item["id"])]
            if "let" in names or len(set(names)) < len(names):
                raise self.error(offset, "invalid lexical binding")
        result = {"type": "VariableDeclaration", "kind": kind, "declarations": items}
        self.decl_offsets[id(result)] = offset
        return result

    def validate_initializers(self, declaration, offset):
        if not self.check_declaration_early_errors:
            return
        if declaration["kind"] == "const" and any(item["init"] is None for item in declaration["declarations"]):
            raise self.error(offset, "const without initializer")
        if any(item["init"] is None and item["id"]["type"] != "Identifier" for item in declaration["declarations"]):
            raise self.error(offset, "binding pattern without initializer")

    def p_declarators(self, p):
        """declarators : declarator
                       | declarators COMMA declarator
           declarators_no_in : declarator_no_in
           declarators_no_in : declarators_no_in COMMA declarator_no_in"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_declarator(self, p):
        """declarator : binding
                      | binding ASSIGN assignment
           declarator_no_in : binding
           declarator_no_in : binding ASSIGN assignment_no_in"""
        if {"arguments", "eval"}.intersection(bound_names(p[1])):
            self.strict_violation(p.lexpos(1), "invalid strict binding")
        p[0] = {"type": "VariableDeclarator", "id": p[1], "init": p[3] if len(p) == 4 else None}

    def is_simple_target(self, node, offset):
        if node["type"] == "Identifier" and node["name"] in {"eval", "arguments"}:
            self.strict_violation(offset, "invalid strict assignment target")
        return node["type"] in {"MemberExpression", "Identifier"}

    def p_assignment(self, p):
        """assignment : conditional
                      | chain ASSIGN assignment
                      | chain COMPOUND_ASSIGN assignment
           assignment_no_in : conditional_no_in
           assignment_no_in : chain ASSIGN assignment_no_in
           assignment_no_in : chain COMPOUND_ASSIGN assignment_no_in"""
        if len(p) == 2:
            p[0] = p[1]
            return
        left = p[1]
        if p[2] == "=":
            left = assignment_pattern(self, left, p.lexpos(2), allow_expression=not self.check_assignment_targets)
        elif self.check_assignment_targets and not self.is_simple_target(left, p.lexpos(2)):
            raise self.error(p.lexpos(2), "invalid assignment target")
        p[0] = {"type": "AssignmentExpression", "operator": p[2], "left": left, "right": p[3]}

    def p_expression_single(self, p):
        """expression : assignment
           expression_no_in : assignment_no_in"""
        p[0] = p[1]

    def p_sequence(self, p):
        """expression : sequence
           expression_no_in : sequence_no_in"""
        p[0] = {"type": "SequenceExpression", "expressions": p[1]}

    def p_sequence_items(self, p):
        """sequence : assignment COMMA assignment
                    | sequence COMMA assignment
           sequence_no_in : assignment_no_in COMMA assignment_no_in
           sequence_no_in : sequence_no_in COMMA assignment_no_in"""
        if p.slice[1].type in {"sequence", "sequence_no_in"}:
            p[1].append(p[3])
            p[0] = p[1]
        else:
            p[0] = [p[1], p[3]]

    def p_chain(self, p):
        """chain : new_expression
                 | call
           new_expression : member
           member : primary"""
        p[0] = p[1]

    def p_chain_expression(self, p):
        "chain : optional_chain"
        p[0] = {"type": "ChainExpression", "expression": p[1]}

    def p_optional_base(self, p):
        """optional_base : member OPTIONAL
                         | call OPTIONAL
                         | optional_chain OPTIONAL"""
        p[0] = p[1]

    def p_optional_template(self, p):
        """optional_chain : optional_chain template
                          | optional_base template"""
        raise self.error(p.lexpos(2), "tagged template within optional chain")

    def p_optional_call(self, p):
        """optional_chain : optional_base call_arguments
                          | optional_chain call_arguments"""
        p[0] = {"type": "CallExpression", "callee": p[1], "arguments": p[2],
                "optional": p.slice[1].type == "optional_base"}

    def p_optional_member(self, p):
        """optional_chain : optional_base property_name
                          | optional_base private_reference
                          | optional_base LBRACKET expression RBRACKET
                          | optional_chain DOT property_name
                          | optional_chain DOT private_reference
                          | optional_chain LBRACKET expression RBRACKET"""
        computed = p.slice[2].type == "LBRACKET"
        p[0] = {"type": "MemberExpression", "object": p[1], "property": p[2] if len(p) == 3 else p[3],
                "computed": computed, "optional": p.slice[1].type == "optional_base"}

    def p_new_target(self, p):
        "member : NEW DOT property_name"
        if self.check_meta_early_errors and (p[3]["name"] != "target" or not self.source.startswith("target", p.lexpos(3))):
            raise self.error(p.lexpos(3), "expected target after new.")
        p[0] = {"type": "MetaProperty", "meta": {"type": "Identifier", "name": "new"}, "property": p[3]}
        self.meta_locations[id(p[0])] = (0, p.lexpos(1))

    def p_private_member(self, p):
        """member : member DOT private_reference
           call : call DOT private_reference"""
        p[0] = {"type": "MemberExpression", "object": p[1], "property": p[3], "computed": False}

    def p_private_expression(self, p):
        "relational : private_reference IN shift"
        p[0] = {"type": "BinaryExpression", "operator": "in", "left": p[1], "right": p[3]}

    def p_private_reference(self, p):
        "private_reference : PRIVATE_NAME"
        p[0] = {"type": "PrivateIdentifier", "name": p[1]}
        self.private_offsets[id(p[0])] = p.lexpos(1)

    def p_super_member(self, p):
        """member : SUPER DOT property_name
                  | SUPER LBRACKET expression RBRACKET"""
        p[0] = {"type": "MemberExpression", "object": {"type": "Super"}, "property": p[3], "computed": len(p) == 5}
        self.meta_locations[id(p[0])] = (1, p.lexpos(1))

    def p_super_call(self, p):
        "call : SUPER call_arguments"
        p[0] = {"type": "CallExpression", "callee": {"type": "Super"}, "arguments": p[2]}
        self.meta_locations[id(p[0])] = (2, p.lexpos(1))

    def p_new(self, p):
        """new_expression : NEW new_expression
           member : NEW member call_arguments"""
        p[0] = {"type": "NewExpression", "callee": p[2], "arguments": p[3] if len(p) == 4 else []}

    def p_call(self, p):
        """call : member call_arguments
                | call call_arguments"""
        p[0] = {"type": "CallExpression", "callee": p[1], "arguments": p[2]}

        callee = self.async_identifiers.get(id(p[1]))
        if callee and id(p[1]) not in self.grouped_patterns and callee[0] == p.lineno(2):
            self.async_calls[id(p[0])] = (callee[1], p.slice[2].trailing)

    def p_call_arguments(self, p):
        """call_arguments : LPAREN RPAREN
                          | LPAREN arguments RPAREN
                          | LPAREN arguments COMMA RPAREN"""
        p.set_lineno(0, p.lineno(1))
        p.slice[0].trailing = len(p) == 5
        p[0] = [] if len(p) == 3 else p[2]

    def p_argument(self, p):
        """argument : assignment
                    | ELLIPSIS assignment"""
        p[0] = p[1] if len(p) == 2 else {"type": "SpreadElement", "argument": p[2]}

    def p_arguments(self, p):
        """arguments : argument
                     | arguments COMMA argument"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_member(self, p):
        """member : member DOT property_name
                  | member LBRACKET expression RBRACKET
           call : call DOT property_name
                | call LBRACKET expression RBRACKET"""
        p[0] = {"type": "MemberExpression", "object": p[1], "property": p[3], "computed": len(p) == 5}

    def p_property_name(self, p):
        """property_name : IDENTIFIER
                         | RESERVED
                         | FOR
                         | NEW
                         | IF
                         | ELSE
                         | THROW
                         | TRY
                         | CATCH
                         | FINALLY
                         | BREAK
                         | CONTINUE
                         | WHILE
                         | DO
                         | SUPER
                         | IMPORT
                         | EXPORT
                         | CLASS
                         | EXTENDS
                         | SWITCH
                         | WITH
                         | CASE
                         | DEFAULT
                         | INSTANCEOF
                         | IN
                         | FUNCTION
                         | RETURN
                         | VAR
                         | CONST
                         | LET
                         | DEBUGGER
                         | THIS
                         | TRUE
                         | FALSE
                         | NULL
                         | TYPEOF
                         | DELETE
                         | VOID"""
        p.slice[0].identifier_token = p.slice[1]
        p.set_lexpos(0, p.lexpos(1))
        p[0] = self.identifier_node(p[1], p.lexpos(1))

    def p_update_chain(self, p):
        "update : chain"
        p[0] = p[1]

    def p_update(self, p):
        """update : chain POST_INCREMENT
                  | chain POST_DECREMENT
                  | INCREMENT unary_operand
                  | DECREMENT unary_operand"""
        prefix = p.slice[1].type in {"INCREMENT", "DECREMENT"}
        operator_index, operand_index = (1, 2) if prefix else (2, 1)
        operand = p[operand_index]
        if self.check_assignment_targets and not self.is_simple_target(operand, p.lexpos(operator_index)):
            raise self.error(p.lexpos(operator_index), "invalid update target")
        p[0] = {"type": "UpdateExpression", "operator": p[operator_index],
                "argument": operand, "prefix": prefix}

    def p_expression_operand(self, p):
        """additive : multiplicative
           multiplicative : exponential
           exponential : update
                       | unary_expression
           unary_operand : update
                         | unary_expression"""
        p[0] = p[1]

    def p_binary(self, p):
        """bit_or : bit_or BIT_OR bit_xor
           bit_xor : bit_xor BIT_XOR bit_and
           bit_and : bit_and BIT_AND equality
           equality : equality EQUALITY relational
           relational : relational RELATION shift
                      | relational INSTANCEOF shift
                      | relational IN shift
           shift : shift SHIFT additive
           additive : additive PLUS multiplicative
                    | additive MINUS multiplicative
           multiplicative : multiplicative MULTIPLY exponential
                          | multiplicative DIVIDE exponential
                          | multiplicative REMAINDER exponential
           exponential : update POWER exponential
           bit_or_no_in : bit_or_no_in BIT_OR bit_xor_no_in
           bit_xor_no_in : bit_xor_no_in BIT_XOR bit_and_no_in
           bit_and_no_in : bit_and_no_in BIT_AND equality_no_in
           equality_no_in : equality_no_in EQUALITY relational_no_in
           relational_no_in : relational_no_in RELATION shift
           relational_no_in : relational_no_in INSTANCEOF shift"""
        p[0] = {"type": "BinaryExpression", "operator": p[2], "left": p[1], "right": p[3]}

    def p_await(self, p):
        "unary_expression : AWAIT unary_operand"
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "AwaitExpression", "argument": p[2]}

    def p_unary(self, p):
        """unary_expression : PLUS unary_operand
                            | MINUS unary_operand
                            | NOT unary_operand
                            | BIT_NOT unary_operand
                            | TYPEOF unary_operand
                            | VOID unary_operand
                            | DELETE unary_operand"""
        target = p[2]["expression"] if p[2]["type"] == "ChainExpression" else p[2]
        if self.check_private_name_early_errors and p[1] == "delete" and target.get("property", {}).get("type") == "PrivateIdentifier":
            raise self.error(p.lexpos(1), "delete of private field")
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "UnaryExpression", "operator": p[1], "prefix": True, "argument": p[2]}
        if p[1] == "delete" and p[2]["type"] == "Identifier":
            self.strict_statement(p[0], p.slice[1], "delete of an unqualified identifier")

    def p_primary_identifier(self, p):
        "primary : identifier"
        p[0] = p[1]
        if p[1]["name"] == "arguments":
            self.arguments_offsets[id(p[0])] = p.lexpos(1)

    def p_identifier(self, p):
        """identifier : IDENTIFIER
                      | LET"""
        p.set_lexpos(0, p.lexpos(1))
        if getattr(p.slice[1], "escaped", False):
            p.slice[0].escaped_token = p.slice[1]
        if p[1] in STRICT_IDENTIFIERS:
            self.strict_violation(p.lexpos(1), "reserved identifier " + p[1])
        p[0] = self.identifier_node(p[1], p.lexpos(1))

        if p[1] == "async" and not getattr(p.slice[1], "escaped", False):
            self.async_identifiers[id(p[0])] = (p.lineno(1), p.lexpos(1))

    def identifier_node(self, name, offset):
        return {"type": "Identifier", "name": name}

    def p_primary_this(self, p):
        "primary : THIS"
        p[0] = {"type": "ThisExpression"}

    def p_primary_literal(self, p):
        """primary : NULL
                   | TRUE
                   | FALSE"""
        p[0] = {"type": "Literal", "value": {"null": None, "true": True, "false": False}[p[1]]}

    def mark_literal_trailing_comma(self, literal):
        self.trailing_comma[id(literal)] = literal

    def p_array(self, p):
        """primary : LBRACKET array_prefix RBRACKET
                   | LBRACKET array_prefix array_element RBRACKET"""
        if len(p) == 5:
            p[2].append(p[3])
        p[0] = {"type": "ArrayExpression", "elements": p[2]}
        if len(p) == 4 and p[2]:
            self.mark_literal_trailing_comma(p[0])

    def p_array_prefix(self, p):
        """array_prefix :
                        | array_prefix COMMA
                        | array_prefix array_element COMMA"""
        if len(p) == 1:
            p[0] = []
        else:
            p[1].append(p[2] if len(p) == 4 else None)
            p[0] = p[1]

    def p_array_element(self, p):
        """array_element : assignment
                         | ELLIPSIS assignment"""
        p[0] = p[1] if len(p) == 2 else {"type": "SpreadElement", "argument": p[2]}

    def p_primary_literals(self, p):
        """primary : string_literal
                   | numeric_literal"""
        p[0] = p[1]

    def p_string(self, p):
        "string_literal : STRING"
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "Literal", "value": p.slice[1].cooked, "raw": p[1]}

    def p_regexp(self, p):
        "primary : REGEXP"
        p[0] = p.slice[1].pattern

    def p_numeric(self, p):
        "numeric_literal : NUMBER"
        p.set_lexpos(0, p.lexpos(1))
        # Preserve spelling and arbitrary BigInt precision in JSON.
        kind = "BigIntLiteral" if p[1].endswith("n") else "NumericLiteral"
        p[0] = {"type": kind, "raw": p[1]}

    def p_error(self, token):
        if token is None:
            raise self.error(len(self.source), "end of input")
        raise self.error(token.lexpos, repr(token.value))

    def __init__(self, source, source_type="script"):
        self.reset(source, source_type)
        self.lexer = lex.lex(module=self)

    def goal_token(self):
        return "MODULE_GOAL" if self.source_type == "module" else "SCRIPT_GOAL"

    def reset(self, source, source_type):
        self.async_calls = {}
        self.async_identifiers = {}
        self.arguments_offsets = {}
        self.line_has_token = False
        self.decl_offsets = {}
        self.private_offsets = {}
        self.export_offsets = {}
        self.meta_locations = {}
        self.template_braces = []
        self.strict_errors = []
        self.strict_regions = []
        self.function_ends = {}
        self.class_ends = {}
        self.class_key_offsets = {}
        self.jump_offsets = {}
        self.cover_errors = {}
        self.grouped_patterns = {}
        self.trailing_comma = {}
        self.function_depth = 0
        self.source_type = source_type
        self.source = source


def accepts_lookahead(parser, kind, following=None):
    """Test one token or two consecutive tokens without running yacc actions."""
    states = parser.statestack.copy()
    while True:
        action = parser.action[states[-1]].get(kind)
        if action is None:
            return False
        if action >= 0:
            if following is None:
                return True
            if not action:  # Accepting $end leaves no state for a second token.
                return False
            states.append(action)
            kind, following = following, None
            continue
        production = parser.productions[-action]
        if production.len:
            del states[-production.len:]
        states.append(parser.goto[states[-1]][production.name])


_FUNCTION_SCOPES = {
    "ENUM_OPEN": "ordinary", "FN_OPEN": "ordinary", "FN_PARAMS": "ordinary", "ARROW_PARAMS": "ordinary",
    "GEN_OPEN": "generator", "GEN_PARAMS": "generator parameters",
    "ASYNC_OPEN": "async", "ASYNC_PARAMS": "async parameters",
    "ASYNC_GEN_OPEN": "async generator", "ASYNC_GEN_PARAMS": "async generator parameters",
    "STATIC_OPEN": "static block",
}


def contextual_kind(parser, kind):
    if kind in {"TEMPLATE_HEAD", "TEMPLATE_MIDDLE", "TEMPLATE_TAIL"} and accepts_lookahead(parser, "UNTAGGED_" + kind):
        return "UNTAGGED_" + kind
    if kind == "LPAREN":
        for formal in ("FN_PARAMS", "GEN_PARAMS", "ASYNC_PARAMS", "ASYNC_GEN_PARAMS"):
            if accepts_lookahead(parser, formal):
                return formal
    if kind == "LBRACE":
        for body in ("FN_OPEN", "GEN_OPEN", "STATIC_OPEN", "ASYNC_OPEN", "ASYNC_GEN_OPEN"):
            if accepts_lookahead(parser, body):
                return body
    if kind == "LBRACKET" and accepts_lookahead(parser, "BIND_ARRAY"):
        return "BIND_ARRAY"
    if kind == "LBRACE" and accepts_lookahead(parser, "BIND_OBJECT"):
        return "BIND_OBJECT"
    if kind == "LBRACE" and not accepts_lookahead(parser, "LBRACE"):
        return "OBJECT_OPEN"
    statement_start = (kind in {"ASYNC_HEAD", "CLASS", "FUNCTION"} and accepts_lookahead(parser, "EMPTY_SEMI")
                       and not accepts_lookahead(parser, "CLASS_STATIC"))
    if kind == "ASYNC_HEAD":
        if accepts_lookahead(parser, "DEFAULT_ASYNC"):
            return "DEFAULT_ASYNC"
        if accepts_lookahead(parser, "DECL_ASYNC") or statement_start:
            return "DECL_ASYNC"
        if accepts_lookahead(parser, "EXPR_ASYNC"):
            return "EXPR_ASYNC"
        return "IDENTIFIER"
    if kind in {"CLASS", "FUNCTION"} and accepts_lookahead(parser, "DEFAULT_" + kind):
        return "DEFAULT_" + kind
    if kind == "CLASS" and (accepts_lookahead(parser, "DECL_CLASS") or statement_start):
        return "DECL_CLASS"
    if kind == "FUNCTION":
        if accepts_lookahead(parser, "DECL_FUNCTION"):
            return "DECL_FUNCTION"
        if accepts_lookahead(parser, "ANNEX_FUNCTION"):
            return "ANNEX_FUNCTION"
        if statement_start:
            return "DECL_FUNCTION"
    if kind in {"RETURN", "BREAK", "CONTINUE"} and accepts_lookahead(parser, kind + "_STMT"):
        return kind + "_STMT"
    return kind


def statement_tokens(grammar, parser, collected):
    previous = None
    for_paren = None
    goal = lex.LexToken()
    goal.type = grammar.goal_token()
    goal.value, goal.lexpos, goal.lineno = "", 0, 1
    yield goal
    dialect_token = getattr(grammar, "dialect_token", None)
    await_context_boundaries = getattr(grammar, "await_context_boundaries", None)
    provisional_tokens = grammar.provisional_expression_tokens if getattr(grammar, "recover_regexp", False) else None
    skip_doc_margin = getattr(grammar, "in_jsdoc_parameter_type", None)
    stream = grammar.raw_tokens()
    upcoming = deque()

    def peek(distance=1):
        while len(upcoming) < distance:
            upcoming.append(next(stream, None))
        return upcoming[distance - 1]

    token = next(stream, None)
    scope = "module" if grammar.source_type == "module" else "ordinary"
    delimiters = []
    while token is not None:
        if hasattr(token, "provisional_lexical_error"):
            grammar.script_pass.record(token.provisional_lexical_error)
        if hasattr(token, "legacy_number_code"):
            grammar.report_legacy_number(token, previous)
        if hasattr(token, "invalid_character") and not grammar.recover_invalid_character(parser, token, peek, upcoming):
            token = upcoming.popleft() if upcoming else next(stream, None)
            continue
        if (token.type == "MULTIPLY" and skip_doc_margin and previous
                and token.lineno > getattr(previous, "end_line", previous.lineno) and skip_doc_margin(parser)):
            # The scanner skips at most one leading asterisk per returned token.
            token = upcoming.popleft() if upcoming else next(stream, None)
            if token is None:
                break
        if provisional_tokens and previous:
            yield from provisional_tokens(parser, previous, token)
        original_kind = token.type
        buffered = None
        if token.type == "ARROW" and dialect_token:
            dialect_token(parser, token, previous, peek, upcoming)
        if (token.type == "ARROW" and not grammar.allow_line_break_before_arrow and previous
                and token.lineno > getattr(previous, "end_line", previous.lineno)):
            raise grammar.error(token.lexpos, "line break before arrow")
        if token.type == "ARROW" and accepts_lookahead(parser, "ASYNC_ARROW"):
            token.type = "ASYNC_ARROW"
        yield_scope = scope
        contextual_word = token.type in {"IDENTIFIER", "RESERVED"}
        needs_scope = dialect_token and (token.type in {"LPAREN", "LBRACKET", "EXTENDS", "AT"} or token.value in {"<", "<<"}
                                         or (contextual_word and token.value in {
                                             "async", "await", "yield", "of", "type", "interface", "declare", "public",
                                             "private", "protected", "readonly", "abstract", "accessor", "static",
                                         }))
        if (contextual_word and token.value in {"yield", "await"}) or needs_scope:
            for symbol in reversed(parser.symstack):
                if symbol.type in {"ARROW", "ASYNC_ARROW"}:
                    yield_scope = "async" if symbol.type == "ASYNC_ARROW" else "ordinary"
                    break
                if symbol.type in {"PARAM_AT", "AT", "DECL_AT", "DEFAULT_AT", "EXPR_AT"}:
                    yield_scope = symbol.decorator_scope
                    break
                if symbol.type == "FIELD_ASSIGN":
                    yield_scope = "ordinary"
                    break
                if symbol.type in _FUNCTION_SCOPES:
                    break
        if (dialect_token and token.type == "RESERVED" and token.value == "await"
                and yield_scope in {"ordinary", "generator", "generator parameters"}):
            token.type = "IDENTIFIER"
        if (await_context_boundaries and previous and token.type in {"IDENTIFIER", "RESERVED"} and token.value == "await"
                and not token.escaped and (boundaries := await_context_boundaries(parser, token, previous, yield_scope))):
            for kind in boundaries:
                boundary = inserted_token(previous, kind, "")
                yield boundary
                previous = boundary
            token.type = "AWAIT"
            token.await_expression = True
        if needs_scope:
            token.enclosing_scope = yield_scope
        if contextual_word and token.value == "await" and not getattr(token, "script_await", False) and yield_scope in {"module", "async", "async generator",
                                                      "async parameters", "async generator parameters"}:
            token.await_expression = getattr(token, "await_expression", False) or yield_scope != "module"
            token.type = "RESERVED"
            if (yield_scope in {"module", "async", "async generator"} or grammar.allow_parameter_operators) and not getattr(token, "escaped", False):
                if not accepts_lookahead(parser, "RESERVED"):
                    token.type = "AWAIT"
        if contextual_word and token.value == "await" and yield_scope == "static block":
            head = [sym.type for sym in parser.symstack[-2:]]
            if previous.type != "FUNCTION" and head != ["FUNCTION", "MULTIPLY"]:
                token.type = "AWAIT" if grammar.allow_parameter_operators and accepts_lookahead(parser, "AWAIT") else "RESERVED"
        if contextual_word and token.value == "yield" and yield_scope in {"generator", "generator parameters", "async generator", "async generator parameters"}:
            token.in_yield_context = True
            # IdentifierName in a member or property key stays available even
            # where YieldExpression is forbidden (including formal parameters).
            token.type = "RESERVED"
            if previous and previous.type == "FUNCTION" and grammar.source_type == "script":
                token.type = "IDENTIFIER"
            elif ((yield_scope in {"generator", "async generator"} or grammar.allow_parameter_operators)
                  and not getattr(token, "escaped", False) and not accepts_lookahead(parser, "RESERVED")):
                buffered = peek()
                token.type = "YIELD" if buffered and buffered.lineno == token.lineno else "BARE_YIELD"
        modifier = {"static": "CLASS_STATIC", "get": "CLASS_ACCESSOR", "set": "CLASS_ACCESSOR"}.get(token.value)
        if not contextual_word or getattr(token, "escaped", False):
            modifier = None
        if modifier:
            buffered = peek()
            if (not buffered or buffered.value == "<" or buffered.type in {
                "LPAREN", "ASSIGN", "SEMICOLON", "RBRACE", "QUESTION", "COLON", "COMMA",
            }):
                modifier = None
            if modifier and accepts_lookahead(parser, modifier):
                token.type = modifier
        async_method_candidate = False
        if token.type == "IDENTIFIER" and token.value == "async" and not token.escaped:
            buffered = peek()
            if buffered and buffered.lineno == token.lineno:
                simple_binding = (grammar.arrow_head_identifier(buffered, yield_scope) if dialect_token
                                  else buffered.type in {"IDENTIFIER", "LET"})
                if simple_binding:
                    following = peek(2)
                    if following and following.type == "ARROW" and following.lineno == buffered.lineno:
                        token.type = "ASYNC_SINGLE"
                if buffered.type == "FUNCTION":
                    token.type = "ASYNC_HEAD"
                if buffered.value != "<" and buffered.type not in {"LPAREN", "ASSIGN", "COLON", "SEMICOLON", "COMMA", "RBRACE", "QUESTION", "NOT"}:
                    async_method_candidate = True
                    if accepts_lookahead(parser, "ASYNC_METHOD"):
                        token.type = "ASYNC_METHOD"
        if dialect_token:
            dialect_token(parser, token, previous, peek, upcoming)
        if for_paren is not None:
            for_paren.first_for_token = token
            for_paren = None
        if previous and previous.type in {"FOR", "AWAIT"} and token.type == "LPAREN":
            for_paren = token
        if token.type == "IDENTIFIER" and token.value == "of" and not token.escaped and accepts_lookahead(parser, "OF"):
            if not accepts_lookahead(parser, "IDENTIFIER"):
                token.type = "OF"
        if token.type == "IDENTIFIER" and token.value in {"as", "from"} and not token.escaped:
            keyword = token.value.upper()
            if accepts_lookahead(parser, keyword):
                token.type = keyword
        if token.type == "LET":
            token.starts_statement = (accepts_lookahead(parser, "EMPTY_SEMI")
                                      and not accepts_lookahead(parser, "CLASS_STATIC"))
        if token.type in {"AWAIT", "YIELD", "BARE_YIELD"} and getattr(previous, "starts_statement", False):
            raise grammar.error(token.lexpos, token.value + " as lexical binding")
        if token.type == "LBRACKET" and getattr(previous, "starts_statement", False):
            if not accepts_lookahead(parser, "BIND_ARRAY"):
                raise grammar.error(token.lexpos, "let [ at start of expression statement")
        if previous and previous.type == "THROW" and token.lineno > previous.lineno and accepts_lookahead(parser, "IDENTIFIER"):
            raise grammar.error(token.lexpos, "line break after throw")
        if accepts_lookahead(parser, "DO_SEMI"):
            if token.type == "SEMICOLON":
                token.type = "DO_SEMI"
            else:
                yield inserted_semicolon(previous, "DO_SEMI")
        if token.type == "SEMICOLON" and accepts_lookahead(parser, "FOR_SEMI"):
            token.type = "FOR_SEMI"
        elif token.type == "SEMICOLON" and accepts_lookahead(parser, "EMPTY_SEMI") and not accepts_lookahead(parser, "SEMICOLON"):
            token.type = "EMPTY_SEMI"
        if previous and token.type in {"INCREMENT", "DECREMENT"} and getattr(previous, "end_line", previous.lineno) == token.lineno:
            postfix = "POST_" + token.type
            if accepts_lookahead(parser, postfix):
                token.type = postfix
        if previous and previous.type in {"RETURN_STMT", "BREAK_STMT", "CONTINUE_STMT"} and token.lineno > previous.lineno and token.type != "SEMICOLON":
            yield inserted_semicolon(previous)
        if previous and (token.type == "RBRACE" or getattr(previous, "declare_statement", False)
                         or token.lineno > getattr(previous, "end_line", previous.lineno)):
            if not accepts_lookahead(parser, contextual_kind(parser, token.type)) and accepts_lookahead(parser, "SEMICOLON"):
                if dialect_token and token.type == "LPAREN" and accepts_lookahead(parser, "FIELD_TERMINATOR_ERROR"):
                    raise grammar.token_error(token, "call in property type annotation", 1441)
                yield inserted_semicolon(previous)
        if token.value in {"/", "/="} and not accepts_lookahead(parser, token.type) and accepts_lookahead(parser, "REGEXP"):
            read_regexp(grammar, token)
            if getattr(token, "unterminated_regexp", False):
                upcoming.clear()
            original_kind = "REGEXP"
        if token.type in grammar.lexical_dialect_types:
            original_kind = token.type
        if collected is not None and not getattr(token, "missing_identifier", False):
            collected.append({"type": original_kind, "value": token.value, "line": token.lineno, "offset": token.lexpos})
        if modifier and accepts_lookahead(parser, modifier):
            token.type = modifier
        if dialect_token:
            dialect_token(parser, token, previous, peek, upcoming)
        if async_method_candidate and accepts_lookahead(parser, "ASYNC_METHOD"):
            token.type = "ASYNC_METHOD"
        token.type = contextual_kind(parser, token.type)
        if hasattr(token, "invalid_escape") and token.type in {"UNTAGGED_TEMPLATE_HEAD", "UNTAGGED_TEMPLATE_MIDDLE", "UNTAGGED_TEMPLATE_TAIL"}:
            raise token.invalid_escape
        if dialect_token and previous:
            actions = parser.action[parser.statestack[-1]]
            field_candidate = "FIELD_TERMINATOR_ERROR" in actions
            tag_candidate = previous.type in {"TEMPLATE", "TEMPLATE_TAIL", "UNTAGGED_TEMPLATE_TAIL"} and "TAG_TERMINATOR_ERROR" in actions
            marker = None
            if (field_candidate or tag_candidate) and not accepts_lookahead(parser, token.type):
                if field_candidate and accepts_lookahead(parser, "FIELD_TERMINATOR_ERROR"):
                    marker = "FIELD_TERMINATOR_ERROR"
                elif tag_candidate and accepts_lookahead(parser, "TAG_TERMINATOR_ERROR"):
                    marker = "TAG_TERMINATOR_ERROR"
            if marker:
                # Let yacc reduce the name, annotation or expression before choosing its diagnostic.
                rejected = copy(token)
                rejected.type = marker
                if marker == "TAG_TERMINATOR_ERROR":
                    rejected.template_end = previous.lexpos + len(previous.value)
                yield rejected
                yield inserted_token(token, "EMPTY_SEMI", ";")
                grammar.p_error(token)
        if (token.type in _FUNCTION_SCOPES or token.type in grammar.additional_openers or
                token.type in {"LPAREN", "LBRACE", "OBJECT_OPEN", "BIND_OBJECT"}):
            delimiters.append(scope)
            scope = getattr(token, "contents_scope", _FUNCTION_SCOPES.get(token.type, scope))
        elif token.type in {"RPAREN", "RBRACE"} and delimiters:
            scope = delimiters.pop()
        yield token
        previous = token
        token = upcoming.popleft() if upcoming else next(stream, None)
    if previous and accepts_lookahead(parser, "DO_SEMI"):
        yield inserted_semicolon(previous, "DO_SEMI")
    if previous and not accepts_lookahead(parser, "$end") and accepts_lookahead(parser, "SEMICOLON"):
        yield inserted_semicolon(previous)
    if previous and grammar.template_braces:
        template_eof = getattr(grammar, "check_template_substitution_eof", None)
        if template_eof:
            template_eof(parser, previous)


def inserted_semicolon(previous, kind="SEMICOLON"):
    return inserted_token(previous, kind, ";")


def inserted_token(previous, kind, value):
    token = lex.LexToken()
    token.type = kind
    token.value = value
    token.lineno = previous.lineno
    token.lexpos = getattr(previous, "end_pos", previous.lexpos + len(previous.value))
    return token


_thread_parser = threading.local()
_build_lock = threading.Lock()


def parser_for_thread(source, source_type, grammar_class=Grammar, *, level=0):
    # PLY binds production actions to the grammar instance. Each thread owns
    # its stacks and lexer, and only table construction uses PLY's globals.
    if not hasattr(_thread_parser, "drivers"):
        _thread_parser.drivers = {}
    key = grammar_class, level
    if key not in _thread_parser.drivers:
        with _build_lock:
            grammar = grammar_class(source, source_type)
            base = _thread_parser.drivers.get((grammar_class, 0))
            if level and base:
                # PLY's automaton can be shared; nested parsing needs its own
                # lexer, semantic actions, error callback and parse stacks.
                parser = copy(base[1])
                parser.productions = [copy(rule) for rule in parser.productions]
                for rule in parser.productions:
                    if rule.func:
                        rule.callable = getattr(grammar, rule.func)
                parser.errorfunc = grammar.p_error
                parser.errorok = True
            else:
                parser = yacc.yacc(module=grammar, write_tables=False, debug=False)
        grammar.parser = parser
        _thread_parser.drivers[key] = grammar, parser
    grammar, parser = _thread_parser.drivers[key]
    grammar.reset(source, source_type)
    grammar.lexer.lineno = 1
    grammar.lexer.input(source)
    return grammar, parser


class JavaScriptPipeline(BasePipeline):
    grammar_class = Grammar
    declaration_file = False
    source_type = "script"

    def preprocess(self, source):
        return source

    def tokenize(self, source):
        if "/" not in source:
            grammar = self.grammar_class(source, self.source_type)
            grammar.lexer.input(source)
            return [{"type": t.type, "value": t.value, "line": t.lineno, "offset": t.lexpos} for t in grammar.raw_tokens()]
        tokens = []
        self._parse(source, tokens)
        return tokens

    def analyze_file(self, path):
        tokens = []
        try:
            ast = self._parse(self.preprocess(read_file(path)), tokens)
            return ParseResult(file_path=str(path), success=True, ast=ast, tokens=tokens)
        except (ValueError, OSError) as error:
            return ParseResult(file_path=str(path), success=False, errors=[str(error)], tokens=tokens)

    def parse(self, source):
        return self._parse(source, None)

    def _parse(self, source, collected):
        return self._parse_goal(source, collected, self.source_type)

    def configure_grammar(self, grammar):
        grammar.declaration_file = self.declaration_file

    def _parse_goal(self, source, collected, goal, **grammar_options):
        grammar, parser = parser_for_thread(source, goal, self.grammar_class)
        self.configure_grammar(grammar, **grammar_options)
        tokens = statement_tokens(grammar, parser, collected)
        body = parser.parse(lexer=grammar.lexer, tokenfunc=lambda: next(tokens, None))
        if goal == "module" and grammar.check_declaration_early_errors:
            check_exports(grammar, body)
        if grammar.check_private_name_early_errors and grammar.private_offsets:
            validate_private(body, grammar.private_offsets, grammar.error)
        if grammar.check_meta_early_errors and grammar.meta_locations:
            validate_meta(body, grammar.meta_locations, grammar.error)
        if grammar.check_declaration_early_errors:
            validate_scopes(grammar, body)
        grammar.check_strict_regions(body)
        if grammar.cover_errors:
            offset, reason = next(iter(grammar.cover_errors.values()))
            raise grammar.error(offset, reason)
        if grammar.check_control_flow_early_errors and grammar.jump_offsets:
            validate_jumps(body, grammar.jump_offsets, grammar.error)
        return {"type": "Program", "sourceType": goal, "body": body}


class JavaScriptModulePipeline(JavaScriptPipeline):
    source_type = "module"
