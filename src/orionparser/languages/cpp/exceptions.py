"""C++20 exception declarations, handlers and throw expressions."""


class ExceptionRules:
    def p_throw_expression(self, p):
        """assignment : THROW
                      | THROW assignment"""
        p[0] = {"type": "ThrowExpression", "operand": p[2] if len(p) == 3 else None}

    def p_try_statement(self, p):
        "statement : try_block"
        p[0] = p[1]

    def p_try_block(self, p):
        "try_block : TRY block handlers"
        p[0] = {"type": "TryBlock", "body": p[2], "handlers": p[3]}

    def p_handlers(self, p):
        """handlers : handler
                    | handlers handler"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            if p[1][-1]["parameter"] is None:
                raise self.source.error(p.lexpos(2), "handler follows catch-all")
            p[0] = [*p[1], p[2]]

    def p_handler(self, p):
        "handler : catch_head block"
        p[0] = {"type": "CatchHandler", "parameter": p[1], "body": p[2]}

    def p_catch_head(self, p):
        """catch_head : CATCH '(' ELLIPSIS ')'
                      | CATCH '(' abstract_type ')'
                      | CATCH '(' type direct_named ')'
                      | CATCH '(' attribute_sequence abstract_type ')'
                      | CATCH '(' attribute_sequence type direct_named ')'"""
        if p.slice[3].type == "ELLIPSIS":
            p[0] = None
            return
        index = 4 if p.slice[3].type == "attribute_sequence" else 3
        name, target = None, p[index]
        self.require_type_specifiers(target, p.lexpos(index), "exception declaration")
        if p.slice[-2].type == "direct_named":
            name, base, operators = self.declared_type(target, p[index+1])
            target = self.derived_type(base, operators)
            p.slice[0].locals = {name: "value"}
        p[0] = {"type": "ExceptionDeclaration", "name": name, "exceptionType": target}
        if index == 4:
            p[0]["attributes"] = p[3]
