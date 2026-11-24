"""PLY parser for Java SE 21 compilation units and module declarations."""
from collections import deque
from copy import copy
from threading import Lock, local

from ply import yacc

from orionparser.core.pipeline import BasePipeline, ParseResult
from .lexer import CONTEXTUAL, JavaSource
from .members import MemberRules
from .numbers import requires_unary_minus
from .declarations import DeclarationRules


class JavaGrammar(MemberRules, DeclarationRules):
    start = "unit"
    tokens = tuple(sorted({"IDENT", "ENUM", "CLASS", "INTERFACE", "PUBLIC", "STATIC", "FINAL", "ABSTRACT",
                           "STRICTFP", "DEFAULT", "IMPORT", "PACKAGE", "PRIMITIVE", "VOID", "LIMIT_NUMBER", "NUMBER", "STRING", "TEXT_BLOCK", "CHARACTER",
                           "TRUE", "FALSE", "NULL", "REF_AT", "DIM_AT", "DIM", "ASSIGN_OP", "EQ", "REL", "SHIFT", "AND", "OR",
                           "INC", "DEC", "THIS", "NEW", "RETURN", "THROW", "IF", "ELSE", "WHILE", "FOR", "DO", "BREAK", "CONTINUE", "ASSERT",
                           "SWITCH", "SWITCH_STMT", "CASE", "SIZE_OPEN", "PATTERN_OPEN", "NON_SEALED", "LAMBDA_OPEN", "LAMBDA_IDENT", "CAST_OPEN", "ARROW", "ELLIPSIS", "COLONS", "TYPE_OPEN", "TYPE_CLOSE", "SUPER", "EXTENDS", "IMPLEMENTS", "THROWS", "CTOR_HEAD", "CTOR_CALL", "TRY", "CATCH", "FINALLY", "INSTANCEOF", "PRIVATE", "PROTECTED", "NATIVE", "SYNCHRONIZED", "TRANSIENT", "VOLATILE", *(w.upper() for w in CONTEXTUAL)}))

    def p_unit(self, p):
        """unit : empty
                | unit item"""
        if len(p) == 2:
            p[0] = {"type": "CompilationUnit", "package": None, "imports": [], "module": None, "declarations": []}
            return
        unit, item = p[1], p[2]
        kind = item["type"]
        if unit["module"] is not None:
            raise self.source.error(p.lexpos(2), "unexpected declaration after module")
        if kind == "PackageDeclaration":
            if unit["package"] or unit["imports"] or unit["declarations"]:
                raise self.source.error(p.lexpos(2), "package declaration must come first")
            unit["package"] = item
        elif kind == "ImportDeclaration":
            if unit["declarations"]:
                raise self.source.error(p.lexpos(2), "import after type declaration")
            unit["imports"].append(item)
        elif kind == "ModuleDeclaration":
            if unit["package"] or unit["declarations"]:
                raise self.source.error(p.lexpos(2), "module declaration in an ordinary compilation unit")
            unit["module"] = item
        else:
            unit["declarations"].append(item)
        p[0] = unit

    def p_empty(self, p):
        "empty :"
        p[0] = None

    def p_item(self, p):
        """item : prefix PACKAGE name ';'
                | IMPORT static_opt name ';'
                | IMPORT static_opt name '.' '*' ';'
                | prefix open_opt MODULE name '{' directives '}'
                | type_declaration
                | ';'"""
        first = 1
        if p.slice[1].type == "prefix" and not p[1]:
            first = 3 if p.slice[2].type == "open_opt" and not p[2] else 2
        p.set_lexpos(0, p.lexpos(first))
        if len(p) == 2:
            p[0] = p[1] if p.slice[1].type == "type_declaration" else {"type": "EmptyDeclaration"}
        elif p.slice[1].type == "IMPORT":
            if p[2] and len(p) == 5 and "." not in p[3]:
                raise self.source.error(p.lexpos(4), "expected a member name in single static import")
            p[0] = {"type": "ImportDeclaration", "static": p[2], "name": p[3], "onDemand": len(p) == 7}
        else:
            if any(isinstance(m, str) for m in p[1]):
                raise self.source.error(p.lexpos(1), "only annotations may precede a package or module")
            if p.slice[2].type == "PACKAGE":
                p[0] = {"type": "PackageDeclaration", "annotations": p[1], "name": p[3]}
            else:
                p[0] = {"type": "ModuleDeclaration", "annotations": p[1], "open": p[2], "name": p[4], "directives": p[6]}

    def p_type_declaration(self, p):
        """type_declaration : prefix normal_type
                            | prefix record_base
                            | prefix enum_base
                            | prefix annotation_base"""
        p.set_lexpos(0, p.lexpos(1) if p[1] else p.lexpos(2))
        p[0] = self.modified_type(p[2], p[1], p.lexpos(1))

    def modified_type(self, base, modifiers, offset):
        if base["type"] == "RecordDeclaration" and any(m in ("sealed", "non-sealed", "abstract") for m in modifiers):
            raise self.source.error(offset, "invalid record modifier")
        return {**base, "modifiers": modifiers}

    def p_normal_type(self, p):
        """normal_type : CLASS IDENT type_parameters_opt class_extends interfaces permits_opt '{' members '}'
                       | INTERFACE IDENT type_parameters_opt interface_extends permits_opt '{' members '}'"""
        is_class = p.slice[1].type == "CLASS"
        p[0] = {"type": p[1].capitalize() + "Declaration", "modifiers": [], "name": p[2],
                "typeParameters": p[3], "extends": p[4], "implements": p[5] if is_class else [],
                "permits": p[6] if is_class else p[5], "members": p[len(p)-2]}
        self.check_type_body(p[0], p.lexpos(2))

    def p_record_base(self, p):
        "record_base : RECORD IDENT type_parameters_opt record_header interfaces '{' members '}'"
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "RecordDeclaration", "name": p[2], "modifiers": [], "typeParameters": p[3],
                "components": p[4], "extends": [], "implements": p[5], "members": p[7]}
        self.check_type_body(p[0], p.lexpos(2))

    def check_type_body(self, decl, offset):
        if decl["name"] in {"var", "yield", "record", "sealed", "permits"}:
            raise self.source.error(offset, "restricted type identifier")
        kind = decl["type"]
        for member in decl["members"]:
            if member["type"] in {"ConstructorDeclaration", "CompactConstructorDeclaration"}:
                if kind == "InterfaceDeclaration" or member["name"] != decl["name"]:
                    raise self.source.error(offset, "constructor name differs from enclosing type")
                if member["type"] == "CompactConstructorDeclaration" and kind != "RecordDeclaration":
                    raise self.source.error(offset, "compact constructor requires a record")
            if member["type"] == "Initializer" and (kind == "InterfaceDeclaration" or
                    (kind == "RecordDeclaration" and not member["static"])):
                raise self.source.error(offset, "initializer not allowed in this type declaration")
            if kind == "RecordDeclaration" and member["type"] == "FieldDeclaration" and "static" not in member["modifiers"]:
                raise self.source.error(offset, "record instance fields must be declared in the header")

    def p_record_header(self, p):
        "record_header : '(' parameters ')'"
        for component in p[2]:
            if component["final"] or component["dimensions"] or component["parameterType"]["name"] == "var":
                raise self.source.error(p.lexpos(1), "invalid record component declaration")
        p[0] = [{**param, "type": "RecordComponent"} for param in p[2]]

    def p_permits(self, p):
        """permits_opt : empty
                       | PERMITS names"""
        p[0] = [] if len(p) == 2 else p[2]

    def p_type_parameters_opt(self, p):
        """type_parameters_opt : empty
                               | type_parameters"""
        p[0] = p[1] or []

    def p_class_extends(self, p):
        """class_extends : empty
                         | EXTENDS annotated_reference"""
        p[0] = [] if len(p) == 2 else [p[2]]

    def p_name_clause(self, p):
        """interface_extends : empty
                             | EXTENDS references
           interfaces : empty
                      | IMPLEMENTS references
           throws_opt : empty
                      | THROWS references"""
        p[0] = [] if len(p) == 2 else p[2]

    def p_prefix(self, p):
        """prefix : empty
                  | prefix annotation
                  | prefix PUBLIC
                  | prefix ABSTRACT
                  | prefix FINAL
                  | prefix DEFAULT
                  | prefix SEALED
                  | prefix NON_SEALED
                  | prefix STRICTFP
                  | prefix PRIVATE
                  | prefix PROTECTED
                  | prefix STATIC
                  | prefix NATIVE
                  | prefix SYNCHRONIZED
                  | prefix TRANSIENT
                  | prefix VOLATILE"""
        if len(p) == 2:
            p[0] = []
        else:
            p.set_lexpos(0, p.lexpos(1) if p[1] else p.lexpos(2))
            p[1].append(p[2])
            p[0] = p[1]

    def p_annotation(self, p):
        """annotation : '@' name
                      | '@' name '(' ')'
                      | '@' name '(' annotation_pairs ')'
                      | '@' name '(' annotation_value ')'
           dimension_annotation : DIM_AT name
                                | DIM_AT name '(' ')'
                                | DIM_AT name '(' annotation_pairs ')'
                                | DIM_AT name '(' annotation_value ')'
           reference_annotation : REF_AT name
                                | REF_AT name '(' ')'
                                | REF_AT name '(' annotation_pairs ')'
                                | REF_AT name '(' annotation_value ')'"""
        p.set_lexpos(0, p.lexpos(1))
        if len(p) == 3:
            p[0] = {"type": "MarkerAnnotation", "name": p[2]}
        elif len(p) == 5 or p.slice[4].type == "annotation_pairs":
            p[0] = {"type": "NormalAnnotation", "name": p[2], "elements": [] if len(p) == 5 else p[4]}
        else:
            p[0] = {"type": "SingleElementAnnotation", "name": p[2], "value": p[4]}

    def p_annotation_pair(self, p):
        "annotation_pair : IDENT '=' annotation_value"
        p[0] = {"name": p[1], "value": p[3]}

    def p_annotation_value(self, p):
        """annotation_value : conditional
                            | annotation
                            | '{' '}'
                            | '{' ',' '}'
                            | '{' annotation_values '}'
                            | '{' annotation_values ',' '}'"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            p[0] = {"type": "ElementValueArrayInitializer", "values": p[2] if p.slice[2].type == "annotation_values" else []}

    def p_annotation_list(self, p):
        """annotation_pairs : annotation_pair
                            | annotation_pairs ',' annotation_pair
           annotation_values : annotation_value
                             | annotation_values ',' annotation_value"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_option(self, p):
        """static_opt : STATIC
                      | empty
           open_opt : OPEN
                    | empty"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = p[1] is not None

    def p_name(self, p):
        """name : IDENT
                | name '.' IDENT"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = p[1] if len(p) == 2 else p[1] + "." + p[3]

    def p_names(self, p):
        """names : name
                 | names ',' name"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_directives(self, p):
        """directives : empty
                      | directives directive"""
        if len(p) == 2:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_directive(self, p):
        """directive : REQUIRES requires_modifiers name ';'
                     | EXPORTS name targets ';'
                     | OPENS name targets ';'
                     | USES name ';'
                     | PROVIDES name WITH names ';'"""
        kind = p.slice[1].type
        if kind == "REQUIRES":
            p[0] = {"type": "Requires", "name": p[3], "modifiers": p[2]}
        elif kind in {"EXPORTS", "OPENS"}:
            p[0] = {"type": p[1].capitalize(), "name": p[2], "targets": p[3]}
        elif kind == "USES":
            p[0] = {"type": "Uses", "name": p[2]}
        else:
            p[0] = {"type": "Provides", "name": p[2], "implementations": p[4]}

    def p_targets(self, p):
        """targets : empty
                   | TO names"""
        p[0] = [] if len(p) == 2 else p[2]

    def p_requires_modifiers(self, p):
        """requires_modifiers : empty
                              | requires_modifiers STATIC
                              | requires_modifiers TRANSITIVE"""
        if len(p) == 2:
            p[0] = []
        else:
            if p[2] in p[1]:
                raise self.source.error(p.lexpos(2), f"repeated requires modifier {p[2]}")
            p[1].append(p[2])
            p[0] = p[1]

    def p_error(self, token):
        if token is None:
            raise self.source.error(len(self.source.raw), "unexpected end of file")
        if token.type == "LIMIT_NUMBER":
            raise self.source.error(token.lexpos, "decimal integer literal requires unary minus")
        raise self.source.error(token.lexpos, f"unexpected {token.value!r}")


def before_shift(parser, kind, stack=None):
    states = (parser.statestack if stack is None else stack).copy()
    while True:
        action = parser.action[states[-1]].get(kind)
        if action is None:
            return None
        if action >= 0:
            return states
        rule = parser.productions[-action]
        if rule.len:
            del states[-rule.len:]
        states.append(parser.goto[states[-1]][rule.name])


def can_shift(parser, kind):
    action = parser.action[parser.statestack[-1]].get(kind)
    if action is None:
        return False
    return action >= 0 or before_shift(parser, kind) is not None


_state = local()
_build = Lock()


class JavaPipeline(BasePipeline):
    def preprocess(self, source):
        return source

    def preprocess_file(self, path):
        return path.read_bytes().decode("utf-8")

    @staticmethod
    def token_record(token):
        return {"type": token.type, "value": token.value, "line": token.lineno, "offset": token.lexpos}

    def tokenize(self, source):
        return [self.token_record(token) for token in JavaSource(source).tokens()]

    def parse(self, source):
        return self._parse(source, None)

    def _parse(self, raw, collected):
        source = JavaSource(raw)
        if not hasattr(_state, "parser"):
            grammar = JavaGrammar()
            with _build:
                _state.parser = yacc.yacc(module=grammar, write_tables=False, debug=False)
            _state.grammar = grammar
        grammar, parser = _state.grammar, _state.parser
        grammar.source = source
        tokens = source.tokens()
        pending = deque()
        depth = 0
        source.lexpos, source.lineno = 0, 1

        def peek(index=0):
            while len(pending) <= index:
                token = next(tokens, None)
                if token is None:
                    return None
                pending.append(token)
            return pending[index]

        def after_annotations(index):
            while peek(index) is not None and peek(index).type == "@":
                index += 1
                if peek(index) is None or peek(index).type != "IDENT":
                    return None
                index += 1
                while peek(index) is not None and peek(index).type == ".":
                    if peek(index+1) is None or peek(index+1).type != "IDENT":
                        break
                    index += 2
                if peek(index) is not None and peek(index).type == "(":
                    index = after_balanced(index, "(", ")")
                    if index is None:
                        return None
            return index

        def annotated_reference_ahead():
            end = after_annotations(0)
            if end is None:
                return False
            index = end
            while (part := peek(index)) is not None:
                if part.type == "COLONS":
                    return index > end
                if part.type == "@":
                    index = after_annotations(index)
                    if index is None:
                        break
                elif part.type in {"PRIMITIVE", "IDENT", ".", "<", ">", "SHIFT", "[", "]", ",", "?", "EXTENDS", "SUPER"}:
                    index += 1
                else:
                    break
            return False

        def type_arguments_ahead():
            level = 1
            index = 0
            while (following := peek(index)) is not None:
                kind = following.type
                if kind == "@":
                    index = after_annotations(index)
                    if index is None:
                        return False
                    continue
                if kind == "<":
                    level += 1
                elif following.value in {">", ">>", ">>>"}:
                    level -= len(following.value)
                    if level <= 0:
                        if level < 0:
                            return depth + level >= 0
                        after = peek(index + 1)
                        if after is None:
                            return False
                        stack = before_shift(parser, "TYPE_OPEN")
                        target = parser.goto[stack[-1]].get("type_arguments")
                        if target is None:
                            return False
                        kind = after.type
                        if kind == "[" and peek(index + 2) is not None and peek(index + 2).type == "]":
                            kind = "DIM"
                        if kind == "@":
                            end = after_annotations(index+1)
                            if end is not None and peek(end) is not None and peek(end).type == "[":
                                kind = "DIM_AT"
                        completed = [*stack, target]
                        if kind == "(" and before_shift(parser, "PATTERN_OPEN", completed) is not None:
                            return True
                        return before_shift(parser, kind, completed) is not None
                elif kind not in {"IDENT", "PRIMITIVE", "EXTENDS", "SUPER", ".", ",", "?", "[", "]", "&"}:
                    return False
                index += 1
            return False

        def opening_kind():
            level, index = 1, 0
            valid_type_head = True
            while (following := peek(index)) is not None:
                kind = following.type
                if kind == "@":
                    end = after_annotations(index)
                    if end is not None:
                        index = end
                        continue
                if kind == "(":
                    level += 1
                elif kind == ")":
                    level -= 1
                    if not level:
                        break
                if kind not in {"IDENT", "PRIMITIVE", ".", "<", ">", "SHIFT", "?", "EXTENDS", "SUPER", ",", "[", "]", "&"}:
                    valid_type_head = False
                index += 1
            after = peek(index + 1) if following is not None else None
            if after is None:
                return "("
            if after.type == "ARROW":
                return "(" if arrow_belongs_to_label(parenthesized=True) else "LAMBDA_OPEN"
            starts_operand = after.type in {"IDENT", "NUMBER", "STRING", "TEXT_BLOCK", "CHARACTER", "THIS", "SUPER", "NEW",
                                             "TRUE", "FALSE", "NULL", "SWITCH", "PRIMITIVE", "VOID", "(", "!", "~"}
            first = after_annotations(0)
            if first is not None and index == first+1 and peek(first).type == "PRIMITIVE":
                starts_operand |= after.type in {"+", "-", "INC", "DEC"}
            if index and valid_type_head and starts_operand:
                return "CAST_OPEN"
            return "("

        def after_balanced(index, opening, closing, level=0):
            while (part := peek(index)) is not None:
                if part.type == opening:
                    level += 1
                elif part.type == closing:
                    level -= 1
                    if level == 0:
                        return index + 1
                index += 1
            return None

        def deconstruction_ahead():
            if not can_shift(parser, "("):
                return True
            # Inside a case label the same prefix may start a method call.
            # A binding ends in a type and identifier; a nested deconstruction
            # must itself contain only patterns (or have an empty header).
            def components(index):
                if peek(index) is not None and peek(index).type == ")":
                    return index + 1
                while True:
                    previous = last = None
                    angles = 0
                    nested = False
                    while (part := peek(index)) is not None:
                        kind = part.type
                        if angles:
                            if kind == "<":
                                angles += 1
                            elif part.value in {">", ">>", ">>>"}:
                                angles -= len(part.value)
                        elif kind == "<":
                            angles = 1
                        elif kind in {",", ")"}:
                            break
                        elif kind == "(":
                            end = components(index + 1)
                            if end is None:
                                return None
                            index = end
                            nested = True
                            break
                        elif kind in {"FINAL", "@"}:
                            # A modifier starts a pattern, never a constant expression.
                            return after_balanced(index, "(", ")", 1)
                        elif kind not in {"IDENT", "PRIMITIVE", ".", "[", "]"}:
                            return None
                        previous, last = last, kind
                        index += 1
                    if not nested and not (last == "IDENT" and previous in {"IDENT", "PRIMITIVE", "]", ">", "SHIFT"}
                                           or last == "]" and previous == "["):
                        return None
                    separator = peek(index)
                    if separator is None or separator.type not in {",", ")"}:
                        return None
                    index += 1
                    if separator.type == ")":
                        return index

            return components(0) is not None

        def arrow_belongs_to_label(parenthesized=False):
            first = "(" if parenthesized else "IDENT"
            stack = before_shift(parser, first)
            if stack is None:
                return False
            stack.append(parser.action[stack[-1]][first])
            if parenthesized:
                target = parser.goto[stack[-1]].get("expression")
                if target is None:
                    return False
                stack = before_shift(parser, ")", [*stack, target])
                if stack is None:
                    return False
                stack.append(parser.action[stack[-1]][")"])
            return before_shift(parser, "ARROW", stack) is not None

        def starts_constructor_invocation():
            index = 0
            while (part := peek(index)) is not None:
                if part.type in {"THIS", "SUPER"} and peek(index+1) is not None and peek(index+1).type == "(":
                    return True
                if part.type in {"(", "["}:
                    index = after_balanced(index, part.type, ")" if part.type == "(" else "]")
                    if index is None:
                        return False
                elif part.type == "{" and index and peek(index-1).type == ")":
                    index = after_balanced(index, "{", "}")
                    if index is None:
                        return False
                elif part.type in {";", "{", "}", "=", "ARROW"}:
                    return False
                else:
                    index += 1
            return False

        def next_token():
            nonlocal depth
            token = pending.popleft() if pending else next(tokens, None)
            if token is None:
                source.lexpos, source.lineno = len(raw), len(source.line_starts)
                return None
            source.lexpos, source.lineno = token.lexpos, token.lineno
            if can_shift(parser, "CTOR_HEAD"):
                pending.appendleft(token)
                if starts_constructor_invocation():
                    marker = copy(token)
                    marker.type = "CTOR_HEAD"
                    return marker
                pending.popleft()
            if collected is not None and not getattr(token, "split_part", False):
                collected.append(self.token_record(token))
            if token.type == "NUMBER":
                try:
                    if requires_unary_minus(token.value):
                        token.type = "LIMIT_NUMBER"
                except ValueError as error:
                    raise source.error(token.lexpos, str(error)) from error
            if token.type == "SWITCH" and can_shift(parser, "SWITCH_STMT"):
                token.type = "SWITCH_STMT"
            elif token.type == "(" and can_shift(parser, "PATTERN_OPEN") and deconstruction_ahead():
                token.type = "PATTERN_OPEN"
            elif token.type == "(" and can_shift(parser, "LAMBDA_OPEN"):
                token.type = opening_kind()
            elif token.type == "(" and can_shift(parser, "CAST_OPEN"):
                if opening_kind() == "CAST_OPEN":
                    token.type = "CAST_OPEN"
            elif token.type == "IDENT" and can_shift(parser, "LAMBDA_IDENT") and peek() is not None and peek().type == "ARROW":
                if not arrow_belongs_to_label():
                    token.type = "LAMBDA_IDENT"
            elif token.type == "<" and can_shift(parser, "TYPE_OPEN"):
                if not can_shift(parser, "<") or type_arguments_ahead():
                    token.type = "TYPE_OPEN"
                    depth += 1
            elif depth and token.value in {">", ">>", ">>>"} and can_shift(parser, "TYPE_CLOSE"):
                if len(token.value) > 1:
                    rest = copy(token)
                    rest.logical_pos += 1
                    rest.lexpos = source.offsets[rest.logical_pos]
                    rest.type = ">" if len(token.value) == 2 else "SHIFT"
                    rest.value = token.value[1:]
                    rest.split_part = True
                    pending.appendleft(rest)
                token.type, token.value = "TYPE_CLOSE", ">"
                depth -= 1
            elif token.type in {"THIS", "SUPER"} and can_shift(parser, "CTOR_CALL"):
                following = peek()
                if following is not None and following.type == "(":
                    token.type = "CTOR_CALL"
            elif token.type == "@" and (can_shift(parser, "DIM_AT") or can_shift(parser, "REF_AT")):
                # The current @ has already been consumed. Scan through the
                # annotations to distinguish annotated [] from annotated ellipsis.
                pending.appendleft(token)
                end = after_annotations(0)
                brackets = (end is not None and peek(end) is not None and peek(end).type == "["
                            and peek(end+1) is not None and peek(end+1).type == "]")
                if brackets and can_shift(parser, "DIM_AT"):
                    token.type = "DIM_AT"
                elif can_shift(parser, "REF_AT") and annotated_reference_ahead():
                    token.type = "REF_AT"
                pending.popleft()
            elif token.type == "[":
                following = peek()
                if following is not None and following.type == "]":
                    pending.popleft()
                    if collected is not None:
                        collected.append(self.token_record(following))
                    token.type, token.value = "DIM", "[]"
                elif can_shift(parser, "SIZE_OPEN"):
                    token.type = "SIZE_OPEN"
            elif token.type == "IDENT" and token.value == "non" and can_shift(parser, "NON_SEALED"):
                minus, sealed = peek(), peek(1)
                if (minus is not None and minus.value == "-" and sealed is not None and sealed.value == "sealed"
                        and minus.logical_pos == token.logical_pos + 3 and sealed.logical_pos == minus.logical_pos + 1):
                    pending.popleft()
                    pending.popleft()
                    if collected is not None:
                        collected.extend(map(self.token_record, (minus, sealed)))
                    token.type, token.value = "NON_SEALED", "non-sealed"
            elif token.type == "IDENT" and token.value == "record" and can_shift(parser, "RECORD"):
                following = peek()
                if following is not None and following.type == "IDENT":
                    token.type = "RECORD"
            elif token.type == "IDENT" and token.value == "yield" and can_shift(parser, "YIELD"):
                following = peek()
                if following is not None and following.type not in {"=", "ASSIGN_OP", ".", "[", ":", "COLONS"}:
                    if following.type not in {"INC", "DEC"} or (peek(1) is not None and peek(1).type != ";"):
                        token.type = "YIELD"
            elif token.type == "IDENT" and token.value in CONTEXTUAL and can_shift(parser, token.value.upper()):
                following = peek() if token.value == "transitive" else None
                if following is None or following.value not in {".", ";"}:
                    token.type = token.value.upper()
            return token

        return parser.parse(lexer=source, tokenfunc=next_token, tracking=True)

    def analyze_file(self, path):
        tokens = []
        try:
            tree = self._parse(self.preprocess_file(path), tokens)
        except (ValueError, OSError) as error:
            return ParseResult(str(path), False, errors=[str(error)], tokens=tokens)
        return ParseResult(str(path), True, ast=tree, tokens=tokens)
