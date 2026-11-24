"""C++20 lambda introducers, captures and call-operator declarators."""


class LambdaRules:
    def p_lambda(self, p):
        """primary : lambda_intro lambda_signature block
                   | lambda_intro ANGLE_OPEN template_parameters ANGLE_CLOSE requires_opt lambda_signature block"""
        generic = len(p) == 8
        p[0] = {"type": "LambdaExpression", **p[1], "templateParameters": p[3] if generic else [],
                "templateRequires": p[5] if generic else None, **p[len(p)-2], "body": p[len(p)-1]}

        token = p.slice[len(p)-2].deduced_return
        self.lambda_types[id(p[0])] = (p[0], token)

    def p_lambda_intro(self, p):
        """lambda_intro : LAMBDA_OPEN ']'
                        | LAMBDA_OPEN capture_default ']'
                        | LAMBDA_OPEN captures ']'
                        | LAMBDA_OPEN capture_default ',' captures ']'"""
        default = p[2] if p.slice[2].type == "capture_default" else None
        captures = p[len(p)-2] if p.slice[-2].type == "captures" else []
        locals_ = {}
        for capture, offset in captures:
            name = capture["name"]
            if name in locals_:
                raise self.source.error(offset, "duplicate lambda capture")
            if name != "this" and capture["initializer"] is None and default == capture["mode"]:
                raise self.source.error(offset, "capture repeats lambda capture default")
            receiver = self.initializer_receiver(p.stack, capture["initializer"] or {"type": "NameExpression", "name": name})
            locals_[name] = "value_pack" if capture["pack"] else receiver or "value"
        p[0] = {"captureDefault": default, "captures": [capture for capture, _ in captures]}
        p.slice[0].locals = locals_
        p.slice[0].template_types = set()
        p.slice[0].template_names = set()
        p.slice[0].template_values = set()
        p.slice[0].template_packs = set()

    def p_capture_default(self, p):
        """capture_default : '&'
                           | '='"""
        p[0] = p.slice[1].type

    def p_captures(self, p):
        """captures : capture
                    | captures ',' capture"""
        p[0] = [p[1]] if len(p) == 2 else [*p[1], p[3]]

    def p_capture(self, p):
        """capture : IDENT
                   | IDENT ELLIPSIS
                   | '&' IDENT
                   | '&' IDENT ELLIPSIS
                   | THIS
                   | '*' THIS
                   | IDENT binding_initializer
                   | '&' IDENT binding_initializer
                   | ELLIPSIS IDENT binding_initializer
                   | '&' ELLIPSIS IDENT binding_initializer"""
        name = next(sym.value for sym in p.slice if sym.type in {"IDENT", "THIS"})
        mode = p.slice[1].type if p.slice[1].type in {"*", "&"} else "="
        pack = any(sym.type == "ELLIPSIS" for sym in p.slice)
        initializer = p[len(p)-1] if p.slice[-1].type == "binding_initializer" else None
        p[0] = ({"name": name, "mode": mode, "pack": pack, "initializer": initializer}, p.lexpos(1))

    def p_lambda_params(self, p):
        "lambda_params : PARAM_OPEN parameters_opt ')'"
        intro = next(sym for sym in reversed(p.stack) if sym.type == "lambda_intro")
        for parameter in p[2]:
            if parameter["name"] in intro.locals:
                raise self.source.error(p.lexpos(1), f"lambda parameter repeats capture {parameter['name']!r}")
        p[0] = p[2]
        p.slice[0].locals = p.slice[1].locals

    def p_lambda_signature(self, p):
        """lambda_signature : empty
                            | lambda_params lambda_specifiers noexcept_opt function_type_attributes trailing_return_opt requires_opt"""
        written = len(p) > 2
        p[0] = {"parameters": p[1] if written else None, "specifiers": p[2] if written else [],
                "noexcept": p[3] if written else None, "returnType": p[len(p)-2] if written else None,
                "requires": p[len(p)-1] if written else None}
        index = next(i for i in reversed(range(len(p.stack))) if p.stack[i].type == "lambda_intro")
        explicit_template = any(sym.type == "template_parameters" for sym in p.stack[index+1:])
        key = self.lambda_return_key(p.stack[index], p[0]["parameters"] or [], explicit_template)
        p.slice[0].deduced_return = key
        target = p[0]["returnType"]
        if target and "auto" not in target["specifiers"] and {"type": "Decltype", "operand": "auto"} not in target["specifiers"]:
            p.slice[0].declared_result = True
            self.deduced_returns[key] = {(self.object_binding(p.stack, target), self.type_argument_identity(p.stack, target))}
        if written and p[4]:
            p[0]["attributes"] = p[4]
        p.slice[0].locals = getattr(p.slice[1], "locals", {})

    def p_lambda_specifiers(self, p):
        """lambda_specifiers : empty
                             | lambda_specifiers SPECIFIER"""
        if len(p) == 2:
            p[0] = []
            return
        if p[2] not in {"mutable", "constexpr", "consteval"} or p[2] in p[1]:
            raise self.source.error(p.lexpos(2), "invalid lambda specifier")
        if set(p[1] + [p[2]]) >= {"constexpr", "consteval"}:
            raise self.source.error(p.lexpos(2), "incompatible lambda specifiers")
        p[0] = [*p[1], p[2]]
