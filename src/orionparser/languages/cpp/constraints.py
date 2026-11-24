"""C++20 constraints, concept definitions and requirements."""


class ConstraintRules:
    def p_concept_definition(self, p):
        "concept_definition : concept_head ';'"
        p[0] = p[1]

    def p_concept_head(self, p):
        "concept_head : CONCEPT IDENT '=' logical_or"
        parameters = next(sym.value for sym in reversed(p.stack) if sym.type == "template_parameters")
        required = sum(not param.get("pack") and "default" not in param for param in parameters)
        form = self.concept_constraint(p.stack, parameters, p[4], p.lexpos(2))
        self.bind(p.stack, p[2], ("concept", parameters[0]["type"] == "TypeTemplateParameter", required, form, len(parameters)))
        p[0] = {"type": "ConceptDefinition", "name": p[2], "constraint": p[4]}

    def p_concept_id(self, p):
        "concept_id : CONCEPT_NAME ANGLE_OPEN template_arguments_opt ANGLE_CLOSE"
        p.slice[0].concept_info = p.slice[1].concept_info
        p[0] = {"type": "ConceptId", "name": p[1], "arguments": p[3]}

    def p_primary_concept(self, p):
        "primary : concept_id"
        p[0] = p[1]

    def p_type_constraint(self, p):
        """type_constraint : CONCEPT_NAME
                           | concept_id"""
        _, type_concept, required = p.slice[1].concept_info[:3]
        if not type_concept:
            raise self.source.error(p.lexpos(1), "type constraint requires a type concept")
        args = [] if p.slice[1].type == "CONCEPT_NAME" else p[1]["arguments"]
        if len(args) + 1 < required and not any(arg["type"] == "PackExpansion" for arg in args):
            raise self.source.error(p.lexpos(1), "too few arguments for type constraint")
        p[0] = {"type": "TypeConstraint", "name": p[1]} if p.slice[1].type == "CONCEPT_NAME" else {
            **p[1], "type": "TypeConstraint"}

    def p_requires_clause(self, p):
        """requires_opt : empty
                        | REQUIRES constraint_or"""
        p[0] = p[2] if len(p) == 3 else None

    def p_constraint_logical(self, p):
        """constraint_or : constraint_and
                         | constraint_or OR constraint_and
           constraint_and : primary
                          | constraint_and AND primary"""
        p[0] = p[1] if len(p) == 2 else {"type": "BinaryExpression", "operator": p[2], "left": p[1], "right": p[3]}

    def p_requires_expression(self, p):
        "primary : requirement_head '{' requirements '}'"
        p[0] = {"type": "RequiresExpression", "parameters": p[1], "requirements": p[3]}

    def p_requirement_head(self, p):
        """requirement_head : REQUIRES
                            | REQUIRES PARAM_OPEN parameters_opt ')'"""
        p[0] = None
        p.slice[0].locals = {}
        if len(p) > 2:
            if any(arg["type"] == "Ellipsis" or arg["default"] is not None for arg in p[3]):
                raise self.source.error(p.lexpos(2), "invalid requires-expression parameter list")
            p[0] = p[3]
            p.slice[0].locals = p.slice[2].locals

    def p_requirements(self, p):
        """requirements : requirement
                        | requirements requirement"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_requirement(self, p):
        """requirement : expression ';'
                       | TYPENAME IDENT ';'
                       | TYPENAME IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE ';'
                       | dependent_type ';'
                       | '{' expression '}' requirement_noexcept return_requirement ';'
                       | NESTED_REQUIRES logical_or ';'"""
        kind = p.slice[1].type
        if kind == "expression":
            p[0] = {"type": "SimpleRequirement", "expression": p[1]}
        elif kind == "TYPENAME":
            target = {"type": "TypeName", "name": p[2]}
            if len(p) == 7:
                if self.lookup(p.stack, [p[2]], False) != "type_template":
                    raise self.source.error(p.lexpos(2), "type requirement expects a template name")
                target["arguments"] = p[4]
            p[0] = {"type": "TypeRequirement", "target": target}
        elif kind == "dependent_type":
            p[0] = {"type": "TypeRequirement", "target": p[1]}
        elif kind == "NESTED_REQUIRES":
            p[0] = {"type": "NestedRequirement", "constraint": p[2]}
        else:
            p[0] = {"type": "CompoundRequirement", "expression": p[2], "noexcept": p[4], "constraint": p[5]}

    def p_requirement_noexcept(self, p):
        """requirement_noexcept : NOEXCEPT
                                | empty"""
        p[0] = p[1] == "noexcept"

    def p_return_requirement(self, p):
        """return_requirement : ARROW type_constraint
                              | empty"""
        p[0] = p[2] if len(p) == 3 else None
