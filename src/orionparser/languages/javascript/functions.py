"""PLY productions for ordinary functions and object initializers."""


from .bindings import bound_names
from .strict import STRICT_IDENTIFIERS


class FunctionAndObjectRules:
    require_simple_strict_parameters = True
    check_duplicate_parameters = True

    def p_function_scope(self, p):
        "function_scope :"
        self.function_depth += 1

    def p_function_body(self, p):
        "function_body : FN_OPEN function_scope body RBRACE"
        self.function_depth -= 1
        p[0] = {"type": "BlockStatement", "body": p[3]}
        self.function_ends[id(p[0])] = p.lexpos(4)

    def p_generator_body(self, p):
        "generator_body : GEN_OPEN function_scope body RBRACE"
        self.p_function_body(p)

    def p_async_body(self, p):
        """async_body : ASYNC_OPEN function_scope body RBRACE
           async_gen_body : ASYNC_GEN_OPEN function_scope body RBRACE"""
        self.p_function_body(p)

    def p_async_function(self, p):
        """function_declaration : DECL_ASYNC FUNCTION identifier async_formals async_body
                                | DECL_ASYNC FUNCTION MULTIPLY identifier async_gen_formals async_gen_body
           default_declaration : DEFAULT_ASYNC FUNCTION async_formals async_body
                               | DEFAULT_ASYNC FUNCTION identifier async_formals async_body
                               | DEFAULT_ASYNC FUNCTION MULTIPLY async_gen_formals async_gen_body
                               | DEFAULT_ASYNC FUNCTION MULTIPLY identifier async_gen_formals async_gen_body
           primary : EXPR_ASYNC FUNCTION async_formals async_body
                   | EXPR_ASYNC FUNCTION identifier async_formals async_body
                   | EXPR_ASYNC FUNCTION MULTIPLY async_gen_formals async_gen_body
                   | EXPR_ASYNC FUNCTION MULTIPLY identifier async_gen_formals async_gen_body"""
        expression = p.slice[1].type == "EXPR_ASYNC"
        generator = p.slice[3].type == "MULTIPLY"
        name = p[len(p) - 3] if p.slice[len(p) - 3].type == "identifier" else None
        if (self.check_declaration_early_errors and expression and name
                and (name["name"] == "await" or (generator and name["name"] == "yield"))):
            raise self.error(p.lexpos(len(p) - 3), "invalid async function expression name")
        p[0] = self.function_node("FunctionExpression" if expression else "FunctionDeclaration",
                                  name, p[len(p) - 2], p[len(p) - 1], p.lexpos(1),
                                  generator=generator, is_async=True)

    def p_async_method(self, p):
        """property : ASYNC_METHOD property_key async_formals async_body
                    | ASYNC_METHOD MULTIPLY property_key async_gen_formals async_gen_body"""
        key, computed, _, _ = p[len(p) - 3]
        value = self.function_node("FunctionExpression", None, p[len(p) - 2], p[len(p) - 1],
                                   p.lexpos(len(p) - 2), method=True, generator=len(p) == 6, is_async=True)
        p[0] = {"type": "Property", "kind": "init", "key": key, "value": value,
                "computed": computed, "shorthand": False, "method": True}

    def p_generator_declaration(self, p):
        "function_declaration : DECL_FUNCTION MULTIPLY identifier generator_formals generator_body"
        p[0] = self.function_node("FunctionDeclaration", p[3], p[4], p[5], p.lexpos(1), generator=True)

    def p_generator_expression(self, p):
        """primary : FUNCTION MULTIPLY generator_formals generator_body
                   | FUNCTION MULTIPLY identifier generator_formals generator_body"""
        name, params, body = (p[3], p[4], p[5]) if len(p) == 6 else (None, p[3], p[4])
        if self.check_declaration_early_errors and name and name["name"] == "yield":
            raise self.error(p.lexpos(3), "generator expression named yield")
        p[0] = self.function_node("FunctionExpression", name, params, body, p.lexpos(1), generator=True)

    def p_generator_method(self, p):
        "property : MULTIPLY property_key generator_formals generator_body"
        key, computed, _, _ = p[2]
        value = self.function_node("FunctionExpression", None, p[3], p[4], p.lexpos(3),
                                   method=True, generator=True)
        p[0] = {"type": "Property", "kind": "init", "key": key, "value": value,
                "computed": computed, "shorthand": False, "method": True}

    def p_yield(self, p):
        """assignment : BARE_YIELD
                      | YIELD
                      | YIELD assignment
                      | YIELD MULTIPLY assignment
           assignment_no_in : BARE_YIELD
                            | YIELD
                            | YIELD assignment_no_in
                            | YIELD MULTIPLY assignment_no_in"""
        arg = p[len(p) - 1] if len(p) > 2 else None
        p[0] = {"type": "YieldExpression", "argument": arg, "delegate": len(p) == 4}

    def p_function_declaration(self, p):
        "function_declaration : DECL_FUNCTION identifier formals function_body"
        p[0] = self.function_node("FunctionDeclaration", p[2], p[3], p[4], p.lexpos(1))

    def p_function_expression(self, p):
        """primary : FUNCTION formals function_body
                   | FUNCTION identifier formals function_body"""
        name, params, body = (p[2], p[3], p[4]) if len(p) == 5 else (None, p[2], p[3])
        p[0] = self.function_node("FunctionExpression", name, params, body, p.lexpos(1))

    def function_node(self, kind, name, params, body, offset, method=False, generator=False, is_async=False):
        names = [name for param in params for name in bound_names(param)]
        if self.check_declaration_early_errors:
            lexical_names = set()
            for stmt in body["body"]:
                if stmt["type"] == "ClassDeclaration":
                    lexical_names.add(stmt["id"]["name"])
                elif stmt["type"] == "VariableDeclaration" and stmt["kind"] != "var":
                    for decl in stmt["declarations"]:
                        lexical_names.update(bound_names(decl["id"]))
            if lexical_names.intersection(names):
                raise self.error(offset, "parameter redeclared in function body")
        simple = all(param["type"] == "Identifier" for param in params)
        if self.strict_directive(body["body"]):
            if self.require_simple_strict_parameters and not simple:
                raise self.error(offset, "strict directive with non-simple parameters")
            self.strict_regions.append((offset, self.function_ends[id(body)]))
        if self.check_duplicate_parameters and len(set(names)) != len(names):
            if method or not simple:
                raise self.error(offset, "duplicate parameter")
            self.strict_violation(offset, "duplicate parameter")
        if {"eval", "arguments"}.intersection(names + ([name["name"]] if name else [])):
            self.strict_violation(offset, "invalid strict binding")
        node = {"type": kind, "id": name, "params": params, "body": body, "async": is_async, "generator": generator}
        if kind == "FunctionDeclaration":
            self.decl_offsets[id(node)] = offset
        return node

    def p_formals(self, p):
        """formals : FN_PARAMS formal_list
           generator_formals : GEN_PARAMS formal_list
           async_formals : ASYNC_PARAMS formal_list
           async_gen_formals : ASYNC_GEN_PARAMS formal_list"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = p[2]

    def p_formal_list(self, p):
        """formal_list : RPAREN
                       | parameters RPAREN
                       | parameters COMMA RPAREN
                       | rest_parameter RPAREN
                       | parameters COMMA rest_parameter RPAREN"""
        if len(p) == 2:
            p[0] = []
        elif p.slice[1].type == "rest_parameter":
            p[0] = [p[1]]
        else:
            p[0] = p[1]
            if len(p) == 5:
                p[0].append(p[3])

    def p_parameters(self, p):
        """parameters : parameter
                      | parameters COMMA parameter"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_parameter(self, p):
        """parameter : binding
                     | binding ASSIGN assignment"""
        p[0] = p[1] if len(p) == 2 else {"type": "AssignmentPattern", "left": p[1], "right": p[3]}

    def p_rest_parameter(self, p):
        "rest_parameter : ELLIPSIS binding"
        p[0] = {"type": "RestElement", "argument": p[2]}

    def p_return(self, p):
        "statement : RETURN_STMT optional_expression SEMICOLON"
        if self.check_control_flow_early_errors and not self.function_depth:
            raise self.error(p.lexpos(1), "return outside function")
        p[0] = {"type": "ReturnStatement", "argument": p[2]}

    def p_object(self, p):
        """primary : OBJECT_OPEN RBRACE
                   | OBJECT_OPEN properties RBRACE
                   | OBJECT_OPEN properties COMMA RBRACE"""
        properties = [] if len(p) == 3 else p[2]
        p[0] = {"type": "ObjectExpression", "properties": properties}
        if len(p) == 5:
            self.mark_literal_trailing_comma(p[0])
        if not self.check_duplicate_proto:
            return
        proto_seen = False
        for prop in properties:
            if prop.get("kind") == "init" and not (prop["method"] or prop["computed"] or prop["shorthand"]):
                key = prop["key"]
                if key.get("name", key.get("value")) == "__proto__":
                    if proto_seen:
                        self.cover_errors[id(p[0])] = (p.lexpos(1), "duplicate __proto__ property")
                    proto_seen = True

    def p_properties(self, p):
        """properties : property
                      | properties COMMA property"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_property_spread(self, p):
        "property : ELLIPSIS assignment"
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "SpreadElement", "argument": p[2]}

    def p_property(self, p):
        """property : property_key COLON assignment
                    | property_key ASSIGN assignment
                    | property_key formals function_body
                    | property_key"""
        self.build_property(p, 1)

    def build_property(self, p, key_index):
        key, computed, shorthand_allowed, offset = p[key_index]
        method = len(p) == key_index + 3 and p.slice[key_index + 1].type == "formals"
        initialized = len(p) == key_index + 3 and p.slice[key_index + 1].type == "ASSIGN"
        shorthand = len(p) == key_index + 1 or initialized
        if shorthand and key.get("name") == "arguments":
            self.arguments_offsets[id(key)] = offset
        if shorthand and key.get("name") in STRICT_IDENTIFIERS:
            self.strict_violation(offset, "reserved shorthand identifier")
        if shorthand and not shorthand_allowed:
            raise self.error(offset, "invalid shorthand property")
        value = key if shorthand else p[key_index + 2]
        if initialized:
            value = {"type": "AssignmentExpression", "operator": "=", "left": key, "right": p[key_index + 2]}
        if method:
            value = self.function_node("FunctionExpression", None, p[key_index + 1], p[key_index + 2], p.lexpos(key_index + 1), method=True)
        p[0] = {"type": "Property", "kind": "init", "key": key, "value": value,
                "computed": computed, "shorthand": shorthand, "method": method}

        if initialized:
            self.cover_errors[id(p[0])] = (offset, "initialized shorthand outside assignment pattern")

    def check_accessor_parameters(self, kind, params, offset):
        if not self.check_declaration_early_errors:
            return
        if kind == "get" and params:
            raise self.error(offset, "getter with parameters")
        if kind == "set" and (len(params) != 1 or params[0]["type"] == "RestElement"):
            raise self.error(offset, "setter requires one non-rest parameter")

    def p_accessor(self, p):
        "property : property_key property_key formals function_body"
        prefix, prefix_computed, _, offset = p[1]
        kind = prefix.get("name")
        if prefix_computed or kind not in {"get", "set"} or not self.source.startswith(kind, offset):
            raise self.error(offset, "expected get or set before property name")
        self.build_accessor(p, kind, offset)

    def build_accessor(self, p, kind, offset):
        key, computed, _, _ = p[2]
        params = p[len(p)-2]
        self.check_accessor_parameters(kind, params, offset)
        value = self.function_node("FunctionExpression", None, params, p[len(p)-1], p.lexpos(len(p)-2), method=True)
        p[0] = {"type": "Property", "kind": kind, "key": key, "value": value,
                "computed": computed, "shorthand": False, "method": False}

    def p_property_key(self, p):
        """property_key : property_name
                        | string_literal
                        | numeric_literal
                        | LBRACKET assignment RBRACKET"""
        if len(p) == 4:
            p[0] = (p[2], True, False, p.lexpos(1))
        else:
            key = p[1]
            token = getattr(p.slice[1], "identifier_token", None)
            allowed = token is not None and (token.type == "IDENTIFIER" or (token.type == "LET" and self.source_type == "script"))
            p[0] = (key, False, allowed, p.lexpos(1))
