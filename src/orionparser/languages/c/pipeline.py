"""PLY grammar for preprocessed C translation units."""
from threading import Lock, local

from ply import lex, yacc

from orionparser.languages.c_family import CFamilyPipeline, stack_prefix
from .declarations import DeclarationRules
from .lexer import LexicalRules
from .system_headers import header_tokens


_BUILTINS = {"__builtin_va_arg": "BUILTIN_VA_ARG", "__builtin_offsetof": "BUILTIN_OFFSETOF"}


class CGrammar(DeclarationRules, LexicalRules):
    start = "translation_unit"

    def p_block(self, p):
        """block : BLOCK_OPEN items '}'"""
        p[0] = {"type": "CompoundStatement", "items": p[2]}

    def p_items(self, p):
        """items : empty
                 | items statement
                 | items declaration"""
        if len(p) == 2:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_statement(self, p):
        """statement : block
                     | optional_expression ';'
                     | RETURN optional_expression ';'
                     | BREAK ';'
                     | CONTINUE ';'"""
        kind = p.slice[1].type
        if kind == "block":
            p[0] = p[1]
        elif kind == "optional_expression":
            p[0] = {"type": "ExpressionStatement", "expression": p[1]}
        elif kind == "RETURN":
            p[0] = {"type": "ReturnStatement", "expression": p[2]}
        else:
            enclosing = {"WHILE", "FOR", "DO"} if kind == "CONTINUE" else {"WHILE", "FOR", "DO", "SWITCH"}
            if self.enclosing_control(p.stack, enclosing) is None:
                raise self.error(p.lexpos(1), f"{p[1]} outside its enclosing control statement")
            p[0] = {"type": p[1].capitalize() + "Statement"}

    def p_controlled(self, p):
        "controlled : control_scope statement"
        p[0] = p[2]

    def p_control_scope(self, p):
        "control_scope :"
        p.slice[0].scope = {}
        p.slice[0].control = next(sym.type for sym in reversed(p.stack)
                                  if sym.type in {"IF", "ELSE", "WHILE", "DO", "FOR", "SWITCH"})

    @staticmethod
    def enclosing_control(stack, kinds):
        return next((sym for sym in reversed(stack) if getattr(sym, "control", None) in kinds), None)

    def p_label(self, p):
        """statement : LABEL_NAME ':' statement
                     | CASE conditional ':' statement
                     | DEFAULT ':' statement"""
        if p.slice[1].type == "LABEL_NAME":
            if p[1] in self.labels:
                raise self.error(max(self.labels[p[1]], p.lexpos(1)), f"duplicate label {p[1]!r}")
            self.labels[p[1]] = p.lexpos(1)
            p[0] = {"type": "LabeledStatement", "label": p[1], "body": p[3]}
        else:
            switch = self.enclosing_control(p.stack, {"SWITCH"})
            if switch is None:
                raise self.error(p.lexpos(1), f"{p[1]} outside switch")
            if p.slice[1].type == "DEFAULT":
                if hasattr(switch, "default_offset"):
                    raise self.error(max(switch.default_offset, p.lexpos(1)), "duplicate default label")
                switch.default_offset = p.lexpos(1)
            p[0] = {"type": "CaseStatement", "test": p[2] if len(p) == 5 else None, "body": p[len(p)-1]}

    def p_goto(self, p):
        "statement : GOTO LABEL_NAME ';'"
        self.goto_targets.setdefault(p[2], p.lexpos(2))
        p[0] = {"type": "GotoStatement", "label": p[2]}

    def p_switch(self, p):
        "statement : SWITCH '(' expression ')' controlled"
        p[0] = {"type": "SwitchStatement", "test": p[3], "body": p[5]}

    def p_if(self, p):
        """statement : IF '(' expression ')' controlled %prec IF
                     | IF '(' expression ')' controlled ELSE controlled"""
        p[0] = {"type": "IfStatement", "test": p[3], "consequent": p[5], "alternate": p[7] if len(p) == 8 else None}

    def p_loop(self, p):
        """statement : WHILE '(' expression ')' controlled
                     | DO controlled WHILE '(' expression ')' ';'"""
        if p.slice[1].type == "WHILE":
            p[0] = {"type": "WhileStatement", "test": p[3], "body": p[5]}
        else:
            p[0] = {"type": "DoWhileStatement", "test": p[5], "body": p[2]}

    def p_for(self, p):
        """statement : FOR '(' for_init optional_expression ';' optional_expression ')' controlled
           for_init : declaration
                    | optional_expression ';'"""
        if p.slice[0].type == "for_init":
            p[0] = p[1]
        else:
            p[0] = {"type": "ForStatement", "init": p[3], "test": p[4], "update": p[6], "body": p[8]}

    def p_optional(self, p):
        """optional_expression : empty
                               | expression
           optional_assignment : empty
                               | assignment"""
        p[0] = p[1]

    def p_empty(self, p):
        "empty :"
        p[0] = None

    def p_expression(self, p):
        """expression : assignment
                      | expression ',' assignment"""
        p[0] = p[1] if len(p) == 2 else {"type": "CommaExpression", "left": p[1], "right": p[3]}

    def p_assignment(self, p):
        """assignment : conditional
                      | unary '=' assignment
                      | unary ASSIGN_OP assignment"""
        p[0] = p[1] if len(p) == 2 else {"type": "AssignmentExpression", "operator": p[2], "left": p[1], "right": p[3]}

    def p_conditional(self, p):
        """conditional : logical_or
                       | logical_or '?' expression ':' conditional"""
        p[0] = p[1] if len(p) == 2 else {"type": "ConditionalExpression", "test": p[1], "consequent": p[3], "alternate": p[5]}

    def p_binary(self, p):
        """logical_or : logical_and
                      | logical_or OR logical_and
           logical_and : bit_or
                       | logical_and AND bit_or
           bit_or : bit_xor
                  | bit_or '|' bit_xor
           bit_xor : bit_and
                   | bit_xor '^' bit_and
           bit_and : equality
                   | bit_and '&' equality
           equality : relation
                    | equality EQUAL relation
           relation : shift
                    | relation '<' shift
                    | relation '>' shift
                    | relation COMPARE shift
           shift : additive
                 | shift SHIFT additive
           additive : multiplicative
                    | additive '+' multiplicative
                    | additive '-' multiplicative
           multiplicative : cast
                          | multiplicative '*' cast
                          | multiplicative '/' cast
                          | multiplicative '%' cast"""
        p[0] = p[1] if len(p) == 2 else {"type": "BinaryExpression", "operator": p[2], "left": p[1], "right": p[3]}

    def p_cast(self, p):
        """cast : unary
                | '(' type_name ')' cast"""
        p[0] = p[1] if len(p) == 2 else {"type": "CastExpression", "target": p[2], "operand": p[4]}

    def p_unary(self, p):
        """unary : postfix
                 | INC unary
                 | DEC unary
                 | '+' cast
                 | '-' cast
                 | '*' cast
                 | '&' cast
                 | '!' cast
                 | '~' cast
                 | SIZEOF unary
                 | SIZEOF '(' type_name ')'
                 | _ALIGNOF '(' type_name ')'"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            p[0] = {"type": "UnaryExpression", "operator": p[1], "operand": p[len(p)-2] if len(p) == 5 else p[2],
                    "prefix": True}

    def p_compound_literal(self, p):
        """postfix : '(' type_name ')' '{' initializers '}'
                   | '(' type_name ')' '{' initializers ',' '}'"""
        p[0] = {"type": "CompoundLiteral", "target": p[2], "elements": p[5]}

    def p_postfix(self, p):
        """postfix : primary
                   | postfix '[' expression ']'
                   | postfix '(' ')'
                   | postfix '(' arguments ')'
                   | postfix '.' MEMBER_NAME
                   | postfix ARROW MEMBER_NAME
                   | postfix INC
                   | postfix DEC"""
        if len(p) == 2:
            p[0] = p[1]
        elif len(p) == 3:
            p[0] = {"type": "UnaryExpression", "operator": p[2], "operand": p[1], "prefix": False}
        elif p[2] == "[":
            p[0] = {"type": "SubscriptExpression", "base": p[1], "index": p[3]}
        elif p[2] == "(":
            p[0] = {"type": "CallExpression", "callee": p[1], "arguments": p[3] if len(p) == 5 else []}
        else:
            p[0] = {"type": "MemberExpression", "operator": p[2], "base": p[1], "member": p[3]}

    def p_gnu_statement_expression(self, p):
        "primary : '(' GNU_BLOCK_OPEN items '}' ')'"
        p[0] = {"type": "GNUStatementExpression", "body": {"type": "CompoundStatement", "items": p[3]}}

    def p_gnu_typeof(self, p):
        """type_specifier : GNU_TYPEOF '(' expression ')'
                          | GNU_TYPEOF '(' type_name ')'"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "GNUTypeof", "operand": p[3]}

    def p_builtin(self, p):
        """primary : BUILTIN_VA_ARG '(' assignment ',' type_name ')'
                   | BUILTIN_OFFSETOF '(' type_name ',' offset_member ')'"""
        p[0] = {"type": "BuiltinExpression", "name": p[1], "arguments": [p[3], p[5]]}

    def p_offset_member(self, p):
        """offset_member : MEMBER_NAME
                         | offset_member '.' MEMBER_NAME
                         | offset_member '[' expression ']'"""
        if len(p) == 2:
            p[0] = {"type": "Identifier", "name": p[1]}
        elif p[2] == ".":
            p[0] = {"type": "MemberExpression", "base": p[1], "member": p[3], "operator": "."}
        else:
            p[0] = {"type": "SubscriptExpression", "base": p[1], "index": p[3]}

    def p_generic(self, p):
        "primary : _GENERIC '(' assignment ',' associations ')'"
        p[0] = {"type": "GenericSelection", "expression": p[3], "associations": p[5]}

    def p_association(self, p):
        """association : type_name ':' assignment
                       | DEFAULT ':' assignment"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "GenericAssociation", "target": None if p.slice[1].type == "DEFAULT" else p[1],
                "expression": p[3]}

    def p_primary(self, p):
        """primary : NAME
                   | NUMBER
                   | CHARACTER
                   | string_literal
                   | '(' expression ')'"""
        if len(p) == 4:
            p[0] = p[2]
        elif p.slice[1].type == "NAME":
            p[0] = {"type": "Identifier", "name": p[1]}
        elif p.slice[1].type == "string_literal":
            p[0] = p[1]
        else:
            p[0] = {"type": {"NUMBER": "NumericLiteral", "CHARACTER": "CharacterLiteral"}[p.slice[1].type],
                    "raw": p[1]}

    def p_string_literal(self, p):
        """string_literal : STRING
                          | string_literal STRING"""
        literal = p[len(p)-1]
        prefix = literal[:literal.index('"')]
        previous = p.slice[1].prefix if len(p) == 3 else ""
        if previous and prefix and previous != prefix:
            raise self.error(p.lexpos(2), "incompatible string literal encoding prefixes")
        p.slice[0].prefix = prefix or previous
        if len(p) == 2:
            p[0] = {"type": "StringLiteral", "parts": [p[1]]}
        else:
            p[1]["parts"].append(p[2])
            p[0] = p[1]

    stack_prefix = staticmethod(stack_prefix)

    def name_binding(self, name, stack):
        for symbol in reversed(stack):
            if hasattr(symbol, "scope") and name in symbol.scope:
                return symbol.scope[name]
        return self.file_scope.get(name, False)

    def is_typedef(self, name, stack):
        return bool(self.name_binding(name, stack))

    def classify_name(self, token, parser):
        fallback = "NAME"
        for kind in ("TYPEDEF_NAME", "DECL_NAME", "MEMBER_NAME", "TAG_NAME", "ENUM_NAME", "NAME"):
            prefix = self.stack_prefix(parser, kind)
            if prefix is None:
                continue
            if kind in {"TYPEDEF_NAME", "NAME"}:
                is_type = self.is_typedef(token.value, parser.symstack[:prefix])
                fallback = "TYPEDEF_NAME" if is_type else "NAME"
                if is_type != (kind == "TYPEDEF_NAME"):
                    continue
            return kind
        return fallback

    def definition_declarator(self, head, offset):
        if self.storage_classes(head["specifiers"]) not in ([], ["static"], ["extern"]):
            raise self.error(offset, "invalid function definition storage class")
        node = head["declarators"][0]["declarator"]
        constructor = None
        while node["type"] != "Identifier":
            constructor, node = node, node["declarator"]
        if not constructor or constructor["type"] != "FunctionDeclarator":
            raise self.error(offset, "function definition requires a function declarator")
        return constructor

    def tokens_for_parse(self, tokens, parser):
        self.file_scope = {}
        self.labels = {}
        self.goto_targets = {}
        self.prototype_openings = {}
        self.parameter_arrays = {}
        self.identifier_lists = {}
        self.void_parameters = set()
        self.void_declarations = set()
        following = None
        previous = None
        token = next(tokens, None)
        while token is not None:
            if token.type == "NAME":
                builtin = _BUILTINS.get(token.value)
                if builtin and self.stack_prefix(parser, builtin) is not None:
                    following = next(tokens, None)
                    if following is not None and following.type == "(":
                        token.type = builtin
                if token.type == "NAME" and self.stack_prefix(parser, "LABEL_NAME") is not None:
                    if following is None:
                        following = next(tokens, None)
                    if previous == "GOTO" or (following and following.type == ":"):
                        token.type = "LABEL_NAME"
                if token.type == "NAME":
                    token.type = self.classify_name(token, parser)
            elif token.type == "_ATOMIC":
                following = next(tokens, None)
                if following is None or following.type != "(":
                    token.type = "QUALIFIER"
            elif token.type == "(" and (prefix := self.stack_prefix(parser, "PARAM_OPEN")) is not None:
                if self.stack_prefix(parser, "(") is None:
                    token.type = "PARAM_OPEN"
                else:
                    # In a parameter declaration, (T) starts an abstract
                    # function declarator when T is a visible typedef name.
                    following = next(tokens, None)
                    if following is not None and (following.type in {"TYPE", "STORAGE", "STATIC", "FUNCTION_SPEC", "QUALIFIER", "_ALIGNAS", "_ATOMIC", "STRUCT", "UNION", "ENUM", ")"}
                            or (following.type == "NAME" and self.is_typedef(following.value, parser.symstack[:prefix]))):
                        token.type = "PARAM_OPEN"
            elif token.type == "{":
                kinds = ("FUNCTION_OPEN", "BLOCK_OPEN", "GNU_BLOCK_OPEN") if token.system_header else ("FUNCTION_OPEN", "BLOCK_OPEN")
                for kind in kinds:
                    if self.stack_prefix(parser, kind) is not None:
                        token.type = kind
                        break
            if token.type in {"FUNCTION_OPEN", "BLOCK_OPEN", "GNU_BLOCK_OPEN", "PARAM_OPEN", "FOR", "IF", "WHILE", "DO", "SWITCH"}:
                token.scope = {}
            self.lookahead_offset = token.lexpos
            yield token
            if token.type == "FUNCTION_OPEN":
                # The header has reduced before the first body token is read.
                head = next(sym for sym in reversed(parser.symstack) if sym.type in {"first_head", "old_head"})
                constructor = self.definition_declarator(head.value, token.lexpos)
                if head.type == "old_head":
                    declarations = next(sym.value for sym in reversed(parser.symstack) if sym.type == "old_declarations")
                    self.check_identifier_declarations(constructor["parameters"], declarations, token.lexpos)
                    del self.identifier_lists[id(constructor)]
                    token.scope.update(head.scope)
                else:
                    parameters = constructor["parameters"]
                    if parameters and parameters[0]["type"] == "Identifier":
                        raise self.error(token.lexpos, "missing declarations for identifier-list parameters")
                    if len(parameters) != 1 or id(parameters[0]) not in self.void_parameters:
                        for param in parameters:
                            if param["type"] == "Parameter" and self.declarator_name(param["declarator"]) is None:
                                raise self.error(token.lexpos, "unnamed parameter in C17 function definition")
                    opening = self.prototype_openings[id(constructor)]
                    if hasattr(opening, "star_offset"):
                        raise self.error(opening.star_offset, "[*] requires function prototype scope")
                    token.scope.update(opening.scope)
            previous = token.type
            token = following if following is not None else next(tokens, None)
            following = None

    def p_error(self, token):
        if token is None:
            raise self.error(len(self.source), "unexpected end of file")
        raise self.error(token.lexpos, f"unexpected {token.value!r}")


_state = local()
_build_lock = Lock()


def parser_state(source):
    if not hasattr(_state, "grammar"):
        grammar = CGrammar()
        with _build_lock:
            _state.lexer = lex.lex(module=grammar)
            _state.parser = yacc.yacc(module=grammar, start="translation_unit", write_tables=False, debug=False)
        _state.grammar = grammar
    _state.grammar.source = source
    _state.grammar.in_system_header = False
    _state.lexer.lineno = 1
    _state.lexer.input(source)
    return _state


class CPipeline(CFamilyPipeline):
    source_suffixes = frozenset({".c"})
    preprocessor = "cpp"
    standard = "c17"
    dialect = "c"

    def tokenize(self, source):
        return [self.token_record(token) for token in parser_state(source).lexer]

    def _parse(self, source, collected):
        state = parser_state(source)

        def raw_tokens():
            for token in state.lexer:
                if collected is not None:
                    collected.append(self.token_record(token))
                yield token

        extensions = []
        normalized = header_tokens(raw_tokens(), state.grammar, extensions)
        tokens = state.grammar.tokens_for_parse(normalized, state.parser)
        unit = state.parser.parse(lexer=state.lexer, tokenfunc=lambda: next(tokens, None))
        if state.grammar.parameter_arrays:
            offset = min(state.grammar.parameter_arrays.values())
            raise state.grammar.error(offset, "array qualifiers and static require an outermost parameter array")
        if state.grammar.identifier_lists:
            offset = min(state.grammar.identifier_lists.values())
            raise state.grammar.error(offset, "identifier list outside its function definition")
        if extensions:
            unit["systemHeaderExtensions"] = extensions
        return unit
