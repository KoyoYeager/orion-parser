"""Operator-function and conversion-function names in C++20."""


class OperatorRules:
    def p_operator_owner(self, p):
        "operator_owner : qualified_name SCOPE"
        p[0] = p[1]
        p.slice[0].namespace = self.namespace_path(p.stack, p[1])

    def p_overload_name(self, p):
        """overload_name : operator_id
                         | SCOPE operator_id
                         | operator_owner operator_id"""
        if p.slice[1].type == "operator_owner":
            p[0] = p[1] + "::" + p[2]
            p.slice[0].namespace = p.slice[1].namespace
        else:
            p[0] = "".join(p[1:])

    def operator_template_ahead(self, stack):
        index = len(stack)-1
        last = stack[index]
        if last.type in {"overload_name", "operator_id"}:
            name = last.value
        else:
            while index >= max(0, len(stack)-4) and stack[index].type != "OPERATOR":
                index -= 1
            if index < 0 or stack[index].type != "OPERATOR":
                return False
            spelling = "".join(sym.value for sym in stack[index+1:])
            if not spelling:
                return False
            name = "operator" + (" " if spelling[0].isalpha() else "") + spelling
        if index >= 2 and stack[index-1].type in {".", "ARROW"}:
            receiver = self.receiver_binding(stack[:index-2], stack[index-2].value)
            if isinstance(receiver, tuple) and receiver[0] == "closure":
                return name == "operator()" and receiver[1] and len(receiver[2]) == (stack[index-1].type == "ARROW")
            return (isinstance(receiver, tuple) and receiver[0] == "object"
                    and self.member_binding(receiver[1], name) == "function_template")
        if index >= 1 and stack[index-1].type == "member_class_qualifier":
            scope = self.specialization_scope(stack[:index-1], stack[index-1].value)
            return self.member_binding(scope, name) == "function_template"
        if (index >= 3 and stack[index-1].type == "SCOPE" and stack[index-2].type == "qualified_name"
                and stack[index-3].type in {".", "ARROW"}):
            owner = stack[index-2].value
            if self.has_dependent_qualifier(stack[:index-2], owner):
                return False
            scope = self.namespace_path(stack[:index-2], owner)
            return self.member_binding(scope, name) == "function_template"
        return self.lookup(stack, name.removeprefix("::").split("::"), name.startswith("::")) == "function_template"

    def p_operator_id(self, p):
        """operator_id : OPERATOR overload_symbol
                       | OPERATOR '(' ')'
                       | OPERATOR OP_ARRAY
                       | OPERATOR NEW
                       | OPERATOR DELETE
                       | OPERATOR NEW OP_ARRAY
                       | OPERATOR DELETE OP_ARRAY
                       | OPERATOR CO_AWAIT"""
        symbol = "".join(p[2:])
        p[0] = "operator" + (" " if symbol[0].isalpha() else "") + symbol

    def p_literal_operator_id(self, p):
        """operator_id : OPERATOR STRING IDENT
                       | OPERATOR UD_STRING"""
        raw = p[2]
        if raw.startswith('""'):
            suffix = raw[2:]
        elif raw.startswith('R"'):
            start = raw.index("(")
            empty = raw[:start+1] + ")" + raw[2:start] + '"'
            if not raw.startswith(empty):
                raise self.source.error(p.lexpos(2), "literal operator requires an empty string")
            suffix = raw[len(empty):]
        else:
            raise self.source.error(p.lexpos(2), "literal operator requires an unprefixed empty string")
        if suffix:
            suffix = p.slice[2].user_defined["suffix"]
        if (len(p) == 4) == bool(suffix):
            raise self.source.error(p.lexpos(2), "literal operator requires one suffix identifier")
        p[0] = 'operator""' + (p[3] if len(p) == 4 else suffix)

    def p_overload_symbol(self, p):
        """overload_symbol : ARROW
                           | ARROW_STAR
                           | '~'
                           | '!'
                           | '+'
                           | '-'
                           | '*'
                           | '/'
                           | '%'
                           | '^'
                           | '&'
                           | '|'
                           | '='
                           | ASSIGN_OP
                           | EQ
                           | '<'
                           | '>'
                           | REL
                           | SPACESHIP
                           | AND
                           | OR
                           | SHIFT
                           | INC
                           | DEC
                           | ','"""
        p[0] = p[1]

    def p_conversion_id(self, p):
        """conversion_id : OPERATOR type
                         | operator_owner OPERATOR type"""
        self.require_type_specifiers(p[len(p)-1], p.lexpos(len(p)-1), "conversion type")
        p[0] = {"type": "ConversionFunctionId", "qualifier": p[1] if len(p) == 4 else None, "target": p[len(p)-1]}
        if len(p) == 4:
            p.slice[0].namespace = p.slice[1].namespace

    def p_conversion_head(self, p):
        """special_head : conversion_id function_suffix requires_opt virt_specifiers
                        | modifiers conversion_id function_suffix requires_opt virt_specifiers"""
        index = 1 if p.slice[1].type == "conversion_id" else 2
        ident, function = p[index], p[index+1]
        if not ident["qualifier"] and not any(hasattr(s, "class_name") for s in p.stack):
            raise self.source.error(p.lexpos(index), "conversion function requires a class")
        if function["parameters"]:
            raise self.source.error(p.lexpos(index+1), "conversion function cannot take parameters")
        if ident["qualifier"]:
            p.slice[0].namespace = self.namespace_path(p.stack, ident["qualifier"])
        p.slice[0].locals = {}
        p[0] = {"type": "ConversionFunctionDeclaration", "name": "operator", "qualifier": ident["qualifier"],
                "target": ident["target"], "parameters": [], "specifiers": p[1] if index == 2 else [],
                "qualifiers": function["qualifiers"], "noexcept": function["noexcept"], "virtSpecifiers": p[len(p)-1]}
        if not ident["qualifier"] and "explicit" not in p[0]["specifiers"] and p[index+2] is None:
            converted = self.type_argument_identity(p.stack, ident["target"])
            if converted is not None:
                self.implicit_conversions.setdefault(self.namespace(p.stack), set()).add(converted)
        if "attributes" in function:
            p[0]["functionTypeAttributes"] = function["attributes"]
        if p[index+2] is not None:
            p[0]["requires"] = p[index+2]
