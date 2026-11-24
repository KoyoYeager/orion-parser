"""CoverParenthesizedExpressionAndArrowParameterList and concise arrow bodies."""
from .bindings import assignment_pattern, bound_names


class ArrowRules:
    check_rest_parameter_rules = True

    def p_parenthesized(self, p):
        "primary : cover_parens"
        items, trailing, offset = p[1]
        if not items or trailing or any(node["type"] == "RestElement" for node in items):
            raise self.error(offset, "invalid parenthesized expression")
        if len(items) > 1:
            p[0] = {"type": "SequenceExpression", "expressions": items}
        else:
            p[0] = items[0]
        self.grouped_patterns[id(p[0])] = p[0]

    def p_cover_parens(self, p):
        """cover_parens : LPAREN RPAREN
                        | LPAREN cover_items RPAREN
                        | LPAREN cover_items COMMA RPAREN"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = ([] if len(p) == 3 else p[2], len(p) == 5, p.lexpos(1))

    def p_cover_items(self, p):
        """cover_items : cover_item
                       | cover_items COMMA cover_item"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_cover_item(self, p):
        """cover_item : assignment
                      | ELLIPSIS assignment"""
        p[0] = p[1] if len(p) == 2 else {"type": "RestElement", "argument": p[2]}

    def p_async_head(self, p):
        """async_head : ASYNC_SINGLE identifier
                      | call"""
        if len(p) == 3:
            p[0] = ([p[2]], False, p.lexpos(1))
            return
        call = p[1]
        info = self.async_calls.get(id(call))
        if info is None:
            raise self.error(p.lexpos(1), "expected async arrow head")
        offset, trailing = info
        p[0] = (call["arguments"], trailing, offset)

    def p_arrow(self, p):
        """assignment : identifier ARROW concise
                      | cover_parens ARROW concise
                      | async_head ASYNC_ARROW async_concise
           assignment_no_in : identifier ARROW concise_no_in
                            | cover_parens ARROW concise_no_in
                            | async_head ASYNC_ARROW async_concise_no_in"""
        is_async = p.slice[2].type == "ASYNC_ARROW"
        offset = p.lexpos(1)
        if p.slice[1].type == "identifier":
            params = [p[1]]
        else:
            items, trailing, offset = p[1]
            params = []
            for i, node in enumerate(items):
                if node["type"] in {"RestElement", "SpreadElement"}:
                    if self.check_rest_parameter_rules and (trailing or i != len(items) - 1):
                        raise self.error(offset, "rest parameter must be last")
                    arg = self.arrow_binding(node["argument"], offset)
                    if self.check_rest_parameter_rules and arg["type"] == "AssignmentPattern":
                        raise self.error(offset, "rest parameter with initializer")
                    params.append({"type": "RestElement", "argument": arg})
                else:
                    params.append(self.arrow_binding(node, offset))
        p[0] = self.arrow_node(params, p[3], is_async, offset, arrow_token=p.slice[2])

    def arrow_node(self, params, body, is_async, offset, *, arrow_token=None):
        pending = [] if self.allow_parameter_operators else list(params)
        while pending:
            node = pending.pop()
            if isinstance(node, list):
                pending.extend(node)
            elif isinstance(node, dict):
                if node.get("type") in {"YieldExpression", "AwaitExpression"}:
                    raise self.error(offset, "yield or await in arrow parameters")
                if is_async and node.get("type") == "Identifier" and node["name"] == "await":
                    raise self.error(offset, "await in async arrow parameters")
                kind = node.get("type")
                if kind == "MemberExpression" and not node["computed"]:
                    pending.append(node["object"])
                elif kind in {"Property", "MethodDefinition", "PropertyDefinition"}:
                    if node["computed"]:
                        pending.append(node["key"])
                    pending.append(node["value"])
                elif kind == "ArrowFunctionExpression":
                    pending.extend(node["params"])
                elif kind not in {"FunctionExpression", "FunctionDeclaration"}:
                    pending.extend(node.values())
        names = [name for param in params for name in bound_names(param)]
        if self.check_duplicate_parameters and len(names) != len(set(names)):
            raise self.error(offset, "duplicate arrow parameter")
        expr = body["type"] != "BlockStatement"
        if expr:
            if {"eval", "arguments"}.intersection(names):
                self.strict_violation(offset, "invalid strict arrow binding")
            node = {"type": "ArrowFunctionExpression", "id": None, "async": is_async,
                    "generator": False, "params": params, "body": body}
        else:
            node = self.function_node("ArrowFunctionExpression", None, params, body, offset, is_async=is_async)
        node["expression"] = expr
        return node

    def p_concise(self, p):
        """concise : assignment
                   | function_body
           concise_no_in : assignment_no_in
                         | function_body
           async_concise : assignment
                         | async_body
           async_concise_no_in : assignment_no_in
                               | async_body"""
        p[0] = p[1]

    def arrow_binding(self, node, offset):
        if id(node) in self.grouped_patterns:
            raise self.error(offset, "parenthesized binding")
        pattern = assignment_pattern(self, node, offset, nested=True)
        pending = [pattern]
        while pending:
            item = pending.pop()
            if id(item) in self.grouped_patterns:
                raise self.error(offset, "parenthesized binding")
            kind = item["type"]
            if kind == "ArrayPattern":
                pending.extend(element for element in item["elements"] if element)
            elif kind == "ObjectPattern":
                pending.extend(prop["value"] if prop["type"] == "Property" else prop for prop in item["properties"])
                self.check_arrow_object_pattern(item, offset)
            elif kind == "RestElement":
                pending.append(item["argument"])
            elif kind == "AssignmentPattern":
                pending.append(item["left"])
            elif kind != "Identifier":
                raise self.error(offset, "invalid arrow parameter")
        return pattern

    def check_arrow_object_pattern(self, pattern, offset):
        if any(prop["type"] == "RestElement" and prop["argument"]["type"] != "Identifier"
               for prop in pattern["properties"]):
            raise self.error(offset, "invalid object rest binding")
