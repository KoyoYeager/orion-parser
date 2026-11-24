"""TypeScript decorator expressions and attachment to declarations and members."""


class DecoratorRules:
    t_AT = r"@"

    def p_decorator_expr(self, p):
        """decorator_expr : decorator_new
                          | decorator_call
                          | decorator_optional
           decorator_new : decorator_member
           decorator_member : primary"""
        if p.slice[1].type == "decorator_optional":
            p[0] = self.finish_optional_chain(p[1])
        else:
            p[0] = p[1]

    def p_decorator_new(self, p):
        """decorator_new : NEW decorator_new
           decorator_member : NEW decorator_member call_arguments
                            | NEW decorator_member MISSING_NEW_ARGS"""
        self.p_new(p)

    def p_decorator_new_target(self, p):
        "decorator_member : NEW DOT property_name"
        self.p_new_target(p)

    def p_decorator_super_member(self, p):
        """decorator_member : SUPER DOT property_name
                            | SUPER DOT private_reference"""
        self.p_super_member(p)

    def p_decorator_call(self, p):
        """decorator_call : decorator_member call_arguments
                          | decorator_call call_arguments
           decorator_optional : decorator_optional call_arguments
                              | decorator_optional_base call_arguments
                              | decorator_optional_base ts_arguments call_arguments"""
        optional = p.slice[0].type == "decorator_optional"
        p[0] = {"type": "CallExpression", "callee": p[1], "arguments": p[len(p)-1]}
        if optional:
            p[0]["optional"] = p.slice[1].type == "decorator_optional_base"
        if len(p) == 4:
            p[0]["typeArguments"] = p[2]
        self.finish_call(p)

    def p_decorator_optional_base(self, p):
        """decorator_optional_base : decorator_member OPTIONAL
                                   | decorator_call OPTIONAL
                                   | decorator_optional OPTIONAL"""
        p[0] = p[1]

    def p_decorator_access(self, p):
        """decorator_member : decorator_member DOT property_name
                            | decorator_member DOT private_reference
           decorator_call : decorator_call DOT property_name
                          | decorator_call DOT private_reference
           decorator_optional : decorator_optional DOT property_name
                              | decorator_optional DOT private_reference
                              | decorator_optional_base property_name
                              | decorator_optional_base private_reference
                              | decorator_optional_base LBRACKET expression RBRACKET"""
        computed = len(p) == 5
        prop = p[3] if computed else p[len(p)-1]
        p[0] = {"type": "MemberExpression", "object": p[1], "property": prop, "computed": computed}
        if p.slice[0].type == "decorator_optional":
            p[0]["optional"] = p.slice[1].type == "decorator_optional_base"
        self.finish_ts_property_access(p)

    def p_decorator_postfix(self, p):
        """decorator_member : decorator_member applied_arguments
                            | decorator_member NON_NULL
                            | decorator_member template
           decorator_call : decorator_call applied_arguments
                          | decorator_call NON_NULL
                          | decorator_call template
           decorator_optional : decorator_optional applied_arguments
                              | decorator_optional NON_NULL
                              | decorator_optional template
                              | decorator_optional_base template
                              | decorator_optional_base ts_arguments template"""
        if p.slice[2].type == "applied_arguments":
            p[0] = {"type": "TSInstantiationExpression", "expression": p[1], "typeArguments": p[2]}
        elif p.slice[2].type == "NON_NULL":
            p[0] = {"type": "TSNonNullExpression", "expression": p[1]}
        else:
            p[0] = {"type": "TaggedTemplateExpression", "tag": p[1], "quasi": p[len(p)-1]}
            if p.slice[0].type == "decorator_optional":
                p[0]["optional"] = p.slice[1].type == "decorator_optional_base"
            if len(p) == 4:
                p[0]["typeArguments"] = p[2]
            elif not p[0].get("optional"):
                self.apply_callee_types(p[0], "tag")
            if "optional" in p[0]:
                self.resolve_optional_continuation(p[0], "tag")

    def p_decorator_prefix(self, p):
        """declaration_decorator : DECL_AT decorator_expr
           default_decorator : DEFAULT_AT decorator_expr
           element_decorator : AT decorator_expr
           parameter_decorator : PARAM_AT decorator_expr
           expression_decorator : EXPR_AT decorator_expr"""
        p[0] = {"type": "Decorator", "expression": p[2]}

    def p_decorated_declaration(self, p):
        """modified_decl : declaration_decorator ambient_item
                         | declaration_decorator DEFAULT default_declaration
           default_declaration : default_decorator default_declaration
                               | default_decorator ambient_item"""
        node = p[len(p)-1]
        if len(p) == 4:
            self.prepend_declaration_modifier(node, "default", p.lexpos(2))
        target = self.declaration_modifier_target(node)
        p[1]["modifierIndex"] = 0
        target.setdefault("decorators", []).insert(0, p[1])
        p[0] = node

    def p_decorated_element(self, p):
        """class_element : element_decorator class_element
           ts_parameter : parameter_decorator ts_parameter"""
        p[0] = p[2]
        p[1]["modifierIndex"] = 0
        p[0].setdefault("decorators", []).insert(0, p[1])

    def p_decorated_expression(self, p):
        """primary : expression_decorator decorated_class
           decorated_class : expression_decorator decorated_class"""
        p[0] = p[2]
        p[0].setdefault("decorators", []).insert(0, p[1])

    def p_decorated_class(self, p):
        """decorated_class : CLASS identifier heritage class_body
                           | CLASS heritage class_body"""
        self.p_class(p)
