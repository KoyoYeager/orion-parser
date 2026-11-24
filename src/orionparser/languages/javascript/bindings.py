"""Binding patterns and BoundNames for declarations, parameters, and catches."""


from .strict import STRICT_IDENTIFIERS


def bound_names(pattern):
    kind = pattern["type"]
    if kind == "Identifier":
        yield pattern["name"]
    elif kind == "AssignmentPattern":
        yield from bound_names(pattern["left"])
    elif kind == "RestElement":
        yield from bound_names(pattern["argument"])
    elif kind == "ArrayPattern":
        for element in pattern["elements"]:
            if element is not None:
                yield from bound_names(element)
    elif kind == "ObjectPattern":
        for prop in pattern["properties"]:
            yield from bound_names(prop if prop["type"] == "RestElement" else prop["value"])


class BindingRules:
    contextual_shorthand_bindings = frozenset()

    def p_binding(self, p):
        """binding : identifier
                   | binding_array
                   | binding_object"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = p[1]

    def p_binding_element(self, p):
        """binding_element : binding
                           | binding ASSIGN assignment"""
        p[0] = p[1] if len(p) == 2 else {"type": "AssignmentPattern", "left": p[1], "right": p[3]}

    def p_binding_rest(self, p):
        "binding_rest : ELLIPSIS binding"
        p[0] = {"type": "RestElement", "argument": p[2]}

    def p_binding_array(self, p):
        """binding_array : BIND_ARRAY binding_prefix RBRACKET
                         | BIND_ARRAY binding_prefix binding_element RBRACKET
                         | BIND_ARRAY binding_prefix binding_rest RBRACKET"""
        if len(p) == 5:
            p[2].append(p[3])
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "ArrayPattern", "elements": p[2]}

    def p_binding_prefix(self, p):
        """binding_prefix :
                          | binding_prefix COMMA
                          | binding_prefix binding_element COMMA"""
        if len(p) == 1:
            p[0] = []
        else:
            p[1].append(None if len(p) == 3 else p[2])
            p[0] = p[1]

    def p_binding_object(self, p):
        """binding_object : BIND_OBJECT RBRACE
                          | BIND_OBJECT binding_props RBRACE
                          | BIND_OBJECT binding_props COMMA RBRACE
                          | BIND_OBJECT object_rest RBRACE
                          | BIND_OBJECT binding_props COMMA object_rest RBRACE"""
        props = [] if len(p) == 3 else p[2]
        if len(p) > 3 and p.slice[2].type == "object_rest":
            props = [p[2]]
        elif len(p) == 6:
            props.append(p[4])
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "ObjectPattern", "properties": props}

    def p_object_rest(self, p):
        "object_rest : ELLIPSIS identifier"
        p[0] = {"type": "RestElement", "argument": p[2]}

    def p_binding_props(self, p):
        """binding_props : binding_property
                         | binding_props COMMA binding_property"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_binding_property(self, p):
        """binding_property : property_key COLON binding_element
                            | property_key
                            | property_key ASSIGN assignment"""
        key, computed, shorthand_allowed, offset = p[1]
        shorthand = len(p) == 2 or p.slice[2].type == "ASSIGN"
        if shorthand and key.get("name") in STRICT_IDENTIFIERS:
            self.strict_violation(offset, "reserved shorthand binding")
        if shorthand and not shorthand_allowed:
            if computed or key["type"] != "Identifier" or key["name"] not in self.contextual_shorthand_bindings:
                self.invalid_shorthand_binding(p, offset)
        if len(p) == 2:
            value = key
        elif shorthand:
            value = {"type": "AssignmentPattern", "left": key, "right": p[3]}
        else:
            value = p[3]
        p[0] = {"type": "Property", "key": key, "computed": computed, "value": value,
                "shorthand": shorthand, "method": False, "kind": "init"}

    def invalid_shorthand_binding(self, p, offset):
        raise self.error(offset, "invalid shorthand binding")


def assignment_pattern(grammar, node, offset, nested=False, *, allow_expression=False):
    """Reinterpret a cover array/object literal in an assignment-target context."""
    kind = node["type"]
    if not allow_expression and grammar.is_simple_target(node, offset):
        return node
    if id(node) in grammar.grouped_patterns:
        if allow_expression:
            return node
        raise grammar.error(offset, "parenthesized destructuring pattern")
    if nested and kind == "AssignmentExpression" and node["operator"] == "=":
        target = assignment_pattern(grammar, node["left"], offset, nested=True, allow_expression=allow_expression)
        return {"type": "AssignmentPattern", "left": target, "right": node["right"]}
    if nested and kind in {"ArrayPattern", "ObjectPattern"}:
        return node
    if kind not in {"ArrayExpression", "ObjectExpression"}:
        if allow_expression:
            return node
        raise grammar.error(offset, "invalid assignment target")
    is_array = kind == "ArrayExpression"
    field = "elements" if is_array else "properties"
    items = node[field]
    children = []
    for index, item in enumerate(items):
        if item is None:
            children.append(None)
        elif item["type"] == "SpreadElement":
            if not allow_expression and (index + 1 != len(items) or id(node) in grammar.trailing_comma):
                raise grammar.error(offset, "rest element must be last")
            target = assignment_pattern(grammar, item["argument"], offset, nested=allow_expression, allow_expression=allow_expression)
            if not allow_expression and not is_array and not grammar.is_simple_target(target, offset):
                raise grammar.error(offset, "invalid object rest target")
            children.append({"type": "RestElement", "argument": target})
        elif is_array:
            children.append(assignment_pattern(grammar, item, offset, nested=True, allow_expression=allow_expression))
        else:
            if item["method"] or item["kind"] != "init":
                if allow_expression:
                    children.append(item)
                    continue
                raise grammar.error(offset, "method in assignment pattern")
            grammar.cover_errors.pop(id(item), None)
            value = assignment_pattern(grammar, item["value"], offset, nested=True, allow_expression=allow_expression)
            children.append({**item, "value": value})
    grammar.cover_errors.pop(id(node), None)
    pattern = {"type": "ArrayPattern" if is_array else "ObjectPattern", field: children}
    if node.get("trailingComma"):
        pattern["trailingComma"] = True
    return pattern


def check_loop_scope(grammar, declaration, body, offset):
    """Loop-head lexical names cannot occur in VarDeclaredNames of the body."""
    if not declaration or declaration.get("kind") not in {"const", "let", "using", "await using"}:
        return
    lexical = {name for item in declaration["declarations"] for name in bound_names(item["id"])}
    pending = [body]
    while pending:
        stmt = pending.pop()
        if not isinstance(stmt, dict):
            continue
        if stmt["type"] == "VariableDeclaration" and stmt["kind"] == "var":
            for item in stmt["declarations"]:
                if lexical.intersection(bound_names(item["id"])):
                    raise grammar.error(offset, "loop binding redeclared by var")
        elif stmt["type"] != "FunctionDeclaration":
            for field in ("body", "consequent", "alternate", "init", "left", "block", "handler", "finalizer", "cases"):
                child = stmt.get(field)
                if isinstance(child, list):
                    pending.extend(child)
                elif isinstance(child, dict):
                    pending.append(child)
