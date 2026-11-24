"""C++ expressions and initializer clauses."""


class ExpressionRules:
    def p_expression_or_braces(self, p):
        """expression_or_braces : expression
                                | braces"""
        p[0] = p[1]

    def p_expression(self, p):
        """expression : assignment
                      | expression ',' assignment"""
        p[0] = p[1] if len(p) == 2 else {"type": "CommaExpression", "left": p[1], "right": p[3]}

    def p_await_expression(self, p):
        "unary : CO_AWAIT cast_expression"
        self.check_coroutine_context(p)
        p[0] = {"type": "AwaitExpression", "operand": p[2]}

    def p_yield_expression(self, p):
        """assignment : CO_YIELD assignment
                      | CO_YIELD braces"""
        self.check_coroutine_context(p)
        p[0] = {"type": "YieldExpression", "operand": p[2]}

    def p_assignment(self, p):
        """assignment : conditional
                      | logical_or '=' initializer
                      | logical_or ASSIGN_OP initializer"""
        p[0] = p[1] if len(p) == 2 else {"type": "AssignmentExpression", "operator": p[2], "left": p[1], "right": p[3]}

    def p_conditional(self, p):
        """conditional : logical_or %prec END_WIDTH
                       | logical_or '?' expression ':' assignment"""
        p[0] = p[1] if len(p) == 2 else {"type": "ConditionalExpression", "test": p[1], "then": p[3], "else": p[5]}

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
           equality : relational
                    | equality EQ relational
           relational : compare
                      | relational '<' compare
                      | relational '>' compare
                      | relational REL compare
           compare : shift
                   | compare SPACESHIP shift
           shift : additive
                 | shift SHIFT additive
           additive : product
                    | additive '+' product
                    | additive '-' product
           product : member_pointer_expr
                   | product '*' member_pointer_expr
                   | product '/' member_pointer_expr
                   | product '%' member_pointer_expr
           member_pointer_expr : cast_expression
                               | member_pointer_expr DOT_STAR cast_expression
                               | member_pointer_expr ARROW_STAR cast_expression"""
        p[0] = p[1] if len(p) == 2 else {"type": "BinaryExpression", "operator": p[2], "left": p[1], "right": p[3]}

    def p_cast_expression(self, p):
        """cast_expression : unary
                           | TYPE_PAREN abstract_type ')' cast_expression"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            p[0] = {"type": "CastExpression", "cast": "c-style", "target": p[2], "operand": p[4]}

    def p_new_expression(self, p):
        """unary : new_head new_target new_initializer
                 | new_head placement new_target new_initializer"""
        target, dimensions, parenthesized = p[len(p)-2]
        p[0] = {"type": "NewExpression", "global": p[1], "placement": p[2] if len(p) == 5 else [],
                "allocatedType": target, "dimensions": dimensions, "parenthesizedType": parenthesized,
                "initializer": p[len(p)-1]}

        if hasattr(p.slice[-2], "dimension_attributes"):
            p[0]["dimensionAttributes"] = p.slice[-2].dimension_attributes

    def p_new_head(self, p):
        """new_head : NEW
                    | SCOPE NEW"""
        p[0] = len(p) == 3

    def p_placement(self, p):
        "placement : '(' initializers ')'"
        p[0] = p[2]

    def p_new_target(self, p):
        """new_target : type
                      | type new_dimensions
                      | NEW_TYPE_OPEN abstract_type ')'"""
        parenthesized = p.slice[1].type == "NEW_TYPE_OPEN"
        index = 2 if parenthesized else 1
        target = p[index]
        self.require_type_specifiers(target, p.lexpos(index), "new-expression")
        dimensions = p[2] if not parenthesized and len(p) == 3 else []
        p[0] = target, dimensions, parenthesized
        if dimensions and hasattr(p.slice[2], "dimension_attributes"):
            p.slice[0].dimension_attributes = p.slice[2].dimension_attributes

    def p_new_dimensions(self, p):
        """new_dimensions : '[' expression_opt ']'
                          | new_dimensions '[' conditional ']'
                          | new_dimensions attribute_specifier"""
        if len(p) == 4:
            p[0] = [p[2]]
        elif len(p) == 3:
            p[0] = p[1]
            attrs = getattr(p.slice[1], "dimension_attributes", [[] for _ in p[1]])
            attrs[-1].append(p[2])
            p.slice[0].dimension_attributes = attrs
        else:
            p[0] = [*p[1], p[3]]
            if hasattr(p.slice[1], "dimension_attributes"):
                p.slice[0].dimension_attributes = [*p.slice[1].dimension_attributes, []]

    def p_new_initializer(self, p):
        """new_initializer : %prec END_WIDTH
                           | '(' arguments_opt ')'
                           | braces"""
        if len(p) == 1:
            p[0] = None
        else:
            p[0] = {"type": "DirectInitializer", "arguments": p[2]} if len(p) == 4 else p[1]

    def p_delete_expression(self, p):
        """unary : DELETE cast_expression
                 | DELETE OP_ARRAY cast_expression
                 | SCOPE DELETE cast_expression
                 | SCOPE DELETE OP_ARRAY cast_expression"""
        p[0] = {"type": "DeleteExpression", "global": p.slice[1].type == "SCOPE",
                "array": p.slice[-2].type == "OP_ARRAY", "operand": p[len(p)-1]}

    def p_type_trait(self, p):
        """primary : UNARY_TRAIT '(' abstract_type ')'
                   | BINARY_TRAIT '(' abstract_type ',' abstract_type ')'
                   | VARIADIC_TRAIT '(' trait_types ')'"""
        if p.slice[1].type == "VARIADIC_TRAIT":
            operands = p[3]
        else:
            operands = [p[3], p[5]] if len(p) == 7 else [p[3]]
        p[0] = {"type": "BuiltinTypeTraitExpression", "name": p[1], "operands": operands}

    def p_trait_types(self, p):
        """trait_types : trait_type
                       | trait_types ',' trait_type"""
        p[0] = [p[1]] if len(p) == 2 else [*p[1], p[3]]

    def p_trait_type(self, p):
        """trait_type : abstract_type
                      | abstract_type ELLIPSIS"""
        p[0] = p[1] if len(p) == 2 else {"type": "PackExpansion", "pattern": p[1]}

    def p_type_operand(self, p):
        """unary : SIZEOF TYPE_PAREN abstract_type ')'
                 | GNU_ALIGNOF unary
                 | GNU_ALIGNOF TYPE_PAREN abstract_type ')'
                 | ALIGNOF TYPE_PAREN abstract_type ')'"""
        p[0] = {"type": "UnaryExpression", "operator": p[1], "operand": p[2] if len(p) == 3 else p[3], "prefix": True}

    def p_noexcept_expression(self, p):
        "unary : NOEXCEPT '(' expression ')'"
        p[0] = {"type": "NoexceptExpression", "expression": p[3]}

    def p_typeid(self, p):
        """primary : TYPEID '(' expression ')'
                   | TYPEID TYPE_PAREN abstract_type ')'"""
        p[0] = {"type": "TypeidExpression", "operand": p[3]}

    def p_gnu_extension_expression(self, p):
        "unary : GNU_EXTENSION cast_expression"
        p[0] = {"type": "GnuExtensionExpression", "operand": p[2]}

    def p_unary(self, p):
        """unary : postfix
                 | '+' cast_expression
                 | '-' cast_expression
                 | '!' cast_expression
                 | '~' cast_expression
                 | '*' cast_expression
                 | '&' cast_expression
                 | INC cast_expression
                 | DEC cast_expression
                 | SIZEOF unary"""
        p[0] = p[1] if len(p) == 2 else {"type": "UnaryExpression", "operator": p[1], "operand": p[2], "prefix": True}

    def p_fold(self, p):
        """primary : '(' ELLIPSIS FOLD_OP cast_expression ')'
                   | '(' cast_expression FOLD_OP ELLIPSIS ')'
                   | '(' cast_expression FOLD_OP ELLIPSIS FOLD_OP cast_expression ')'"""
        left = None if p.slice[2].type == "ELLIPSIS" else p[2]
        right = p[len(p)-2] if p.slice[-2].type != "ELLIPSIS" else None
        if len(p) == 8 and p[3] != p[5]:
            raise self.source.error(p.lexpos(5), "binary fold operators must match")
        left_pack = self.contains_pack(left, p.stack)
        right_pack = self.contains_pack(right, p.stack)
        if left_pack == right_pack:
            raise self.source.error(p.lexpos(2 if left is None else 4), "fold requires an unexpanded pack on exactly one side")
        p[0] = {"type": "FoldExpression", "direction": "right" if left_pack else "left",
                "operator": p[3], "left": left, "right": right}

    def contains_pack(self, node, stack):
        pending = [node]
        while pending:
            item = pending.pop()
            if isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, dict):
                if item.get("type") in {"PackExpansion", "SizeofPack", "FoldExpression"}:
                    continue
                if item.get("type") in {"NameExpression", "TypeName", "TemplateName", "DependentTemplateId", "DependentType"}:
                    if item["type"] == "DependentType":
                        name = "" if item["absolute"] else item["segments"][0].get("name", "")
                    else:
                        name = item.get("qualifier", item.get("name", "")).split("::")[0]
                    for symbol in reversed([*self.inherited_stack, *stack]):
                        local = getattr(symbol, "locals", {})
                        if name in local:
                            if local[name] == "value_pack":
                                return True
                            break
                        if name in getattr(symbol, "template_packs", ()):
                            return True
                pending.extend(item.values())
        return False

    def p_pack_size(self, p):
        "unary : SIZEOF ELLIPSIS '(' IDENT ')'"
        p[0] = {"type": "SizeofPack", "name": p[4]}

    def p_builtin_bit_cast(self, p):
        "postfix : BUILTIN_BIT_CAST '(' abstract_type ',' assignment ')'"
        self.require_type_specifiers(p[3], p.lexpos(3), "builtin bit cast")
        p[0] = {"type": "BuiltinBitCast", "target": p[3], "operand": p[5]}

    def p_cast(self, p):
        """postfix : STATIC_CAST '<' abstract_type '>' '(' expression ')'
                 | CONST_CAST '<' abstract_type '>' '(' expression ')'
                 | REINTERPRET_CAST '<' abstract_type '>' '(' expression ')'
                 | DYNAMIC_CAST '<' abstract_type '>' '(' expression ')'"""
        p[0] = {"type": "CastExpression", "cast": p[1], "target": p[3], "operand": p[6]}

    def p_postfix(self, p):
        """postfix : primary
                   | postfix '(' arguments_opt ')'
                   | postfix '[' expression_or_braces ']'
                   | postfix '.' qualified_name
                   | postfix ARROW qualified_name
                   | postfix '.' operator_id
                   | postfix ARROW operator_id
                   | postfix INC
                   | postfix DEC"""
        if len(p) == 2:
            p[0] = p[1]
        elif len(p) == 3:
            p[0] = {"type": "UnaryExpression", "operator": p[2], "operand": p[1], "prefix": False}
        elif p[2] == "(":
            callee = p[1]
            while callee["type"] == "ParenthesizedExpression":
                callee = callee["expression"]
            if "destructorType" in callee:
                self.pending_destructors.pop(id(callee), None)
            if p[3]:
                if "conversionType" in callee or callee["type"] == "ConversionFunctionId":
                    raise self.source.error(p.lexpos(3), "conversion function call cannot take arguments")
                if "destructorType" in callee:
                    raise self.source.error(p.lexpos(3), "destructor call cannot take arguments")
            p[0] = {"type": "CallExpression", "callee": p[1], "arguments": p[3]}
        elif p[2] == "[":
            p[0] = {"type": "SubscriptExpression", "base": p[1], "index": p[3]}
        else:
            p[0] = {"type": "MemberExpression", "base": p[1], "operator": p[2], "member": p[3]}

    def p_conversion_member(self, p):
        """postfix : postfix '.' OPERATOR type
                   | postfix ARROW OPERATOR type
                   | postfix '.' qualified_name SCOPE OPERATOR type
                   | postfix ARROW qualified_name SCOPE OPERATOR type
                   | postfix '.' member_class_qualifier OPERATOR type
                   | postfix ARROW member_class_qualifier OPERATOR type"""
        target = p[len(p)-1]
        self.require_type_specifiers(target, p.lexpos(len(p)-1), "conversion type")
        p[0] = {"type": "MemberExpression", "base": p[1], "operator": p[2],
                "member": "operator", "conversionType": target}
        if p.slice[3].type == "member_class_qualifier":
            p[0]["qualifier"] = p[3]
        elif p.slice[3].type == "qualified_name":
            p[0]["qualifier"] = {"type": "TypeName", "name": p[3]}

    def p_conversion_primary(self, p):
        """primary : CONVERSION_OPERATOR type
                   | qualified_name SCOPE CONVERSION_OPERATOR type"""
        if len(p) == 3 and self.namespace([*self.inherited_stack, *p.stack]) not in self.class_scopes:
            raise self.source.error(p.lexpos(1), "unqualified conversion function requires a class scope")
        target = p[len(p)-1]
        self.require_type_specifiers(target, p.lexpos(len(p)-1), "conversion type")
        p[0] = {"type": "ConversionFunctionId", "qualifier": p[1] if len(p) == 5 else None, "target": target}

    def p_destructor_qualifier(self, p):
        """destructor_qualifier : qualified_name SCOPE
                                | member_class_qualifier"""
        if len(p) == 3:
            p[0] = {"type": "TypeName", "name": p[1]}
            scope = self.namespace_path(p.stack, p[1])
            parts = p[1].removeprefix("::").split("::")
            absolute = p[1].startswith("::")
            dependent = self.has_dependent_qualifier(p.stack, p[1])
            if dependent:
                p.slice[0].dependent_destructor = True
            elif scope not in self.class_scopes and scope not in self.namespaces:
                binding = self.lookup(p.stack, parts, absolute)
                if not absolute and len(parts) == 1 and binding != "type":
                    receiver = self.receiver_binding(p.stack, p.stack[-2].value)
                    if isinstance(receiver, tuple) and receiver[0] == "object":
                        binding = self.member_binding(receiver[1], p[1])
                        if binding == "type":
                            scope = receiver[1]
                if binding not in {"type", "type_template"}:
                    raise self.source.error(p.lexpos(1), "unknown destructor qualifier")
        else:
            p[0] = p[1]
            scope = self.specialization_scope(p.stack, p[1])
        if scope in self.class_scopes or scope in self.namespaces:
            p.slice[0].namespace = scope

    def p_destructor_member(self, p):
        """postfix : postfix '.' '~' named_type
                   | postfix ARROW '~' named_type
                   | postfix '.' '~' decltype_spec
                   | postfix ARROW '~' decltype_spec
                   | postfix '.' destructor_qualifier '~' named_type
                   | postfix ARROW destructor_qualifier '~' named_type"""
        end = len(p)-1
        spelling = self.source.spelling(p.lexpos(end-1), p.slice[end].endlexpos)
        obj = self.argument_identity(p.stack, p[1])
        if obj is not None and obj.record is None and obj.words and obj.words != ("auto",):
            layers = obj.layers
            if layers and layers[-1].operator in ("&", "&&"):
                layers = layers[:-1]
            if p[2] == "->" and layers:
                layers = layers[:-1]
            destroyed = self.type_argument_identity(p.stack, {"type": "Type", "specifiers": [p[end]], "indirections": []})
            if destroyed is not None and not layers and (obj.words != destroyed.words or destroyed.layers or destroyed.record):
                raise self.source.error(p.lexpos(end), "pseudo-destructor names a different scalar type")
        p[0] = {"type": "MemberExpression", "base": p[1], "operator": p[2],
                "member": spelling, "destructorType": p[end]}
        if self.start == "translation_unit":
            self.pending_destructors[id(p[0])] = (p[0], p.lexpos(end-1))
        if end == 5:
            p[0]["qualifier"] = p[3]

    def p_primary(self, p):
        """primary : qualified_name %prec END_NAME
                   | overload_name
                   | NUMBER
                   | CHARACTER
                   | string_literal
                   | TRUE
                   | FALSE
                   | NULLPTR
                   | THIS
                   | '(' expression ')'"""
        kind = p.slice[1].type
        if kind in {"qualified_name", "overload_name"}:
            if kind == "qualified_name" and self.lookup(p.stack, p[1].removeprefix("::").split("::"), p[1].startswith("::")) == "ambiguous":
                raise self.source.error(p.lexpos(1), f"ambiguous name {p[1]!r}")
            p[0] = {"type": "NameExpression", "name": p[1]}
        elif kind == "string_literal":
            p[0] = {"type": "StringLiteral", "parts": p[1]}
            if p.slice[1].encoding_prefix:
                p[0]["encodingPrefix"] = p.slice[1].encoding_prefix
            if p.slice[1].user_defined:
                p[0]["userDefined"] = p.slice[1].user_defined
        elif kind == "(":
            p[0] = {"type": "ParenthesizedExpression", "expression": p[2]}
        elif kind == "THIS":
            p[0] = {"type": "ThisExpression"}
        else:
            p[0] = {"type": "Literal", "raw": p[1]}
            if hasattr(p.slice[1], "code_unit"):
                p[0].update(encodingPrefix=p.slice[1].encoding_prefix, codeUnit=p.slice[1].code_unit)
            if hasattr(p.slice[1], "user_defined"):
                p[0]["userDefined"] = p.slice[1].user_defined

    def p_member_template_id(self, p):
        """member_template_id : TEMPLATE IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE
                              | TEMPLATE operator_id ANGLE_OPEN template_arguments_opt ANGLE_CLOSE
                              | operator_id OP_TEMPLATE_OPEN template_arguments_opt ANGLE_CLOSE
                              | MEMBER_TEMPLATE ANGLE_OPEN template_arguments_opt ANGLE_CLOSE"""
        name = len(p)-4
        p[0] = {"member": p[name], "template": name == 2, "arguments": p[len(p)-2]}
        p.slice[0].name_offset = p.lexpos(name)

    def p_member_template(self, p):
        """postfix : postfix '.' member_template_id
                   | postfix ARROW member_template_id
                   | postfix '.' qualified_name SCOPE member_template_id
                   | postfix ARROW qualified_name SCOPE member_template_id
                   | postfix '.' member_class_qualifier member_template_id
                   | postfix ARROW member_class_qualifier member_template_id"""
        member = p[len(p)-1]
        p[0] = {"type": "MemberExpression", "base": p[1], "operator": p[2], **member}
        scope = None
        if p.slice[3].type == "member_template_id":
            if member["template"]:
                receiver = self.receiver_binding(p.stack, p[1])
                if isinstance(receiver, tuple) and receiver[0] == "closure":
                    if member["member"] != "operator()" or not receiver[1]:
                        raise self.source.error(p.slice[-1].name_offset, "expected a lambda call operator template")
                if isinstance(receiver, tuple) and receiver[0] == "object":
                    scope = receiver[1]
        else:
            owner = p[3] if p.slice[3].type == "member_class_qualifier" else {"type": "TypeName", "name": p[3]}
            p[0]["qualifier"] = owner
            if member["template"] and not self.has_dependent_qualifier(p.stack, owner["name"]):
                scope = (self.specialization_scope(p.stack, owner) if "arguments" in owner
                         else self.namespace_path(p.stack, owner["name"]))
        # A dependent specialization may supply a different member at instantiation.
        if scope is not None and self.bindings.get(scope) != "type_template":
            binding = self.member_binding(scope, member["member"])
            if binding is not None and binding not in {"function_template", "variable_template"}:
                raise self.source.error(p.slice[-1].name_offset, "expected a member template")

    def p_member_class_qualifier(self, p):
        "member_class_qualifier : MEMBER_CLASS ANGLE_OPEN template_arguments_opt ANGLE_CLOSE SCOPE"
        p[0] = {"type": "TypeName", "name": p[1], "arguments": p[3],
                "spelling": self.source.spelling(p.lexpos(1), p.slice[4].endlexpos)}

    def p_class_qualified_access(self, p):
        """postfix : postfix '.' member_class_qualifier IDENT
                   | postfix ARROW member_class_qualifier IDENT
                   | postfix '.' member_class_qualifier operator_id
                   | postfix ARROW member_class_qualifier operator_id"""
        p[0] = {"type": "MemberExpression", "base": p[1], "operator": p[2],
                "member": p[4], "qualifier": p[3]}

    def p_dependent_qualified_template(self, p):
        """primary : qualified_name SCOPE TEMPLATE IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE
                   | named_type TEMPLATE_MEMBER_SCOPE TEMPLATE IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE"""
        qualifier = p[1] if p.slice[1].type == "qualified_name" else self.source.spelling(p.lexpos(1), p.slice[1].endlexpos)
        p[0] = {"type": "DependentTemplateId", "qualifier": qualifier, "name": p[4], "arguments": p[6]}
        if p.slice[1].type == "named_type":
            p[0]["owner"] = p[1]

    def p_qualified_member_expression(self, p):
        """qualified_member_value : decltype_spec DECLTYPE_SCOPE IDENT
                               | named_type TEMPLATE_MEMBER_SCOPE IDENT
                                  | qualified_member_value SCOPE IDENT"""
        p[0] = {"type": "QualifiedMemberExpression", "owner": p[1], "name": p[3]}

    def p_qualified_primary(self, p):
        "primary : qualified_member_value %prec END_NAME"
        p[0] = p[1]

    def p_template_id(self, p):
        """primary : TEMPLATE_ID ANGLE_OPEN template_arguments_opt ANGLE_CLOSE
                   | overload_name OP_TEMPLATE_OPEN template_arguments_opt ANGLE_CLOSE"""
        p[0] = {"type": "TemplateId", "name": p[1], "arguments": p[3]}

    def p_construction(self, p):
        """primary : named_type braces
                   | named_type '(' arguments_opt ')'
                   | decltype_spec braces
                   | decltype_spec '(' arguments_opt ')'
                   | type_transform braces
                   | type_transform '(' arguments_opt ')'
                   | dependent_type braces
                   | dependent_type '(' arguments_opt ')'
                   | BUILTIN braces
                   | BUILTIN '(' arguments_opt ')'"""
        target = {"type": "TypeName", "name": p[1]} if p.slice[1].type == "BUILTIN" else p[1]
        p[0] = {"type": "TypeConstruction", "target": target,
                "initializer": p[2] if len(p) == 3 else {"type": "Arguments", "values": p[3]}}

    def p_string_literal(self, p):
        """string_literal : STRING
                          | string_literal STRING
           unsuffixed_string : STRING
                             | unsuffixed_string STRING"""
        index = len(p)-1
        suffix = getattr(p.slice[index], "user_defined", None)
        if suffix and p.slice[0].type == "unsuffixed_string":
            raise self.source.error(p.slice[index].suffix_offset, "expected a string literal without a user-defined suffix")
        encoding = p.slice[index].encoding_prefix
        previous_encoding = p.slice[1].encoding_prefix if index == 2 else ""
        if encoding and previous_encoding and encoding != previous_encoding:
            raise self.source.error(p.lexpos(index), "incompatible encoding prefixes in string literal concatenation")
        p.slice[0].encoding_prefix = previous_encoding or encoding
        previous = p.slice[1].user_defined if index == 2 else None
        if previous and suffix and previous != suffix:
            raise self.source.error(p.lexpos(index), "differing user-defined suffixes in string literal concatenation")
        p.slice[0].user_defined = previous or suffix
        p[0] = p[1] if index == 2 else []
        p[0].append(p[index])

    def p_arguments_opt(self, p):
        """arguments_opt : empty
                         | initializers"""
        p[0] = p[1] or []

    def p_initializer(self, p):
        """initializer : assignment
                       | braces"""
        p[0] = p[1]

    def p_initializers(self, p):
        """initializers : initializer_element
                        | initializers ',' initializer_element"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_initializer_element(self, p):
        """initializer_element : initializer
                               | initializer ELLIPSIS"""
        p[0] = p[1] if len(p) == 2 else {"type": "PackExpansion", "pattern": p[1]}

    def p_designator(self, p):
        "designator : '.' IDENT"
        p[0] = p[2]

    def p_designated_clause(self, p):
        """designated_clause : designator '=' initializer
                             | designator braces"""
        p[0] = {"type": "DesignatedInitializer", "member": p[1], "form": "=" if len(p) == 4 else "{}",
                "value": p[len(p)-1]}

    def p_designated_list(self, p):
        """designated_list : designated_clause
                           | designated_list ',' designated_clause"""
        clause = p[len(p)-1]
        seen = set() if len(p) == 2 else p.slice[1].designated_names
        if clause["member"] in seen:
            raise self.source.error(p.lexpos(len(p)-1), "duplicate member designator")
        seen.add(clause["member"])
        p.slice[0].designated_names = seen
        p[0] = [] if len(p) == 2 else p[1]
        p[0].append(clause)

    def p_designated_braces(self, p):
        """braces : '{' designated_list '}'
                  | '{' designated_list ',' '}'"""
        p[0] = {"type": "InitializerList", "elements": p[2], "trailingComma": len(p) == 5}

    def p_braces(self, p):
        """braces : '{' '}'
                  | '{' initializers '}'
                  | '{' initializers ',' '}'"""
        p[0] = {"type": "InitializerList", "elements": [] if len(p) == 3 else p[2]}
