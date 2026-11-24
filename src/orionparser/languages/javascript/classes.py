"""ECMAScript class declarations, expressions, and public elements."""


class ClassRules:
    check_private_name_early_errors = True

    def p_class(self, p):
        """class_declaration : DECL_CLASS identifier heritage class_body
           primary : CLASS identifier heritage class_body
                   | CLASS heritage class_body"""
        named = len(p) == 5
        name = p[2] if named else None
        body = p[len(p) - 1]
        self.strict_regions.append((p.lexpos(1), self.class_ends[id(body)]))
        if self.check_declaration_early_errors and name and name["name"] in {"eval", "arguments"}:
            raise self.error(p.lexpos(2), "invalid class binding")
        p[0] = {"type": "ClassDeclaration" if p.slice[1].type == "DECL_CLASS" else "ClassExpression",
                "id": name, "superClass": p[len(p) - 2], "body": body}

        self.decl_offsets[id(p[0])] = p.lexpos(1)

    def p_heritage(self, p):
        """heritage :
                    | EXTENDS chain"""
        p[0] = p[2] if len(p) == 3 else None

    def p_class_body(self, p):
        "class_body : LBRACE class_elements RBRACE"
        private = {}
        constructor_seen = False
        for elem in p[2]:
            key = elem.get("key", {})
            if elem.get("kind") == "constructor" and elem["value"]["body"] is not None:
                if self.check_declaration_early_errors and constructor_seen:
                    raise self.error(self.class_key_offsets[id(key)], "duplicate constructor")
                constructor_seen = True
            if not self.check_private_name_early_errors or key.get("type") != "PrivateIdentifier":
                continue
            name, kind = key["name"], elem.get("kind")
            prior = private.setdefault(name, [])
            if prior and (len(prior) != 1 or {prior[0][0], kind} != {"get", "set"} or prior[0][1] != elem["static"]):
                raise self.error(self.class_key_offsets[id(key)], "duplicate private name #" + name)
            prior.append((kind, elem["static"]))
        p[0] = {"type": "ClassBody", "body": p[2]}
        self.class_ends[id(p[0])] = p.lexpos(3)

    def p_class_elements(self, p):
        """class_elements :
                          | class_elements class_element
                          | class_elements EMPTY_SEMI"""
        if len(p) == 1:
            p[0] = []
        else:
            if p.slice[2].type == "class_element":
                p[1].append(p[2])
            p[0] = p[1]

    def p_class_element_key(self, p):
        """class_element_key : property_key
                             | PRIVATE_NAME"""
        if p.slice[1].type == "PRIVATE_NAME":
            if p[1] == "constructor":
                raise self.error(p.lexpos(1), "private name #constructor")
            p[0] = ({"type": "PrivateIdentifier", "name": p[1]}, False, False, p.lexpos(1))
        else:
            p[0] = p[1]

        self.class_key_offsets[id(p[0][0])] = p[0][3]

    def p_class_field(self, p):
        """class_element : class_element_key SEMICOLON
                         | class_element_key ASSIGN assignment SEMICOLON
                         | CLASS_STATIC class_element_key SEMICOLON
                         | CLASS_STATIC class_element_key ASSIGN assignment SEMICOLON"""
        static = p.slice[2].type == "class_element_key"
        index = 2 if static else 1
        key, computed, _, offset = p[index]
        value = p[index + 2] if p.slice[index + 1].type == "ASSIGN" else None
        self.check_class_arguments(value)
        self.check_class_field_key(key, computed, static, offset)
        p[0] = {"type": "PropertyDefinition", "static": static, "computed": computed, "key": key, "value": value}

    def p_class_method(self, p):
        """class_element : class_element_key formals function_body
                         | CLASS_STATIC class_element_key formals function_body
                         | CLASS_ACCESSOR class_element_key formals function_body
                         | CLASS_STATIC CLASS_ACCESSOR class_element_key formals function_body
                         | MULTIPLY class_element_key generator_formals generator_body
                         | CLASS_STATIC MULTIPLY class_element_key generator_formals generator_body
                         | ASYNC_METHOD class_element_key async_formals async_body
                         | CLASS_STATIC ASYNC_METHOD class_element_key async_formals async_body
                         | ASYNC_METHOD MULTIPLY class_element_key async_gen_formals async_gen_body
                         | CLASS_STATIC ASYNC_METHOD MULTIPLY class_element_key async_gen_formals async_gen_body"""
        key, computed, _, offset = p[len(p) - 3]
        params_type = p.slice[len(p) - 2].type
        generator = params_type in {"generator_formals", "async_gen_formals"}
        is_async = params_type in {"async_formals", "async_gen_formals"}
        static = p.slice[1].type == "CLASS_STATIC"
        kind = p[len(p) - 4] if len(p) >= 5 and p.slice[len(p) - 4].type == "CLASS_ACCESSOR" else "method"
        params, body = p[len(p) - 2], p[len(p) - 1]
        kind = self.class_method_kind(key, computed, static, offset, kind, generator, is_async)
        self.check_accessor_parameters(kind, params, offset)
        method = self.function_node("FunctionExpression", None, params, body,
                                    p.lexpos(len(p) - 2), method=True, generator=generator, is_async=is_async)
        p[0] = {"type": "MethodDefinition", "static": static, "computed": computed,
                "kind": kind, "key": key, "value": method}

    def p_static_begin(self, p):
        "static_begin :"
        p[0] = self.function_depth
        self.function_depth = 0

    def p_static_block(self, p):
        "class_element : CLASS_STATIC STATIC_OPEN static_begin body RBRACE"
        self.function_depth = p[3]
        self.check_class_arguments(p[4])
        p[0] = {"type": "StaticBlock", "body": p[4]}

    def check_class_arguments(self, root):
        if not self.check_declaration_early_errors or not self.arguments_offsets:
            return
        pending = [root]
        while pending:
            node = pending.pop()
            if isinstance(node, list):
                pending.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            kind = node.get("type")
            if kind == "Identifier" and node["name"] == "arguments" and id(node) in self.arguments_offsets:
                raise self.error(self.arguments_offsets[id(node)], "arguments in class initializer")
            if kind in {"FunctionExpression", "FunctionDeclaration"}:
                continue
            if kind in {"ClassExpression", "ClassDeclaration"}:
                pending.append(node["superClass"])
                pending.extend(elem["key"] for elem in node["body"]["body"] if elem.get("computed"))
            else:
                pending.extend(node.values())

    def check_class_field_key(self, key, computed, static, offset):
        if self.class_key(key, computed, static, offset) == "constructor":
            raise self.error(offset, "field named constructor")

    def class_method_kind(self, key, computed, static, offset, kind, generator, is_async):
        name = self.class_key(key, computed, static, offset)
        if name == "constructor" and not static:
            if generator or is_async or kind != "method":
                raise self.error(offset, "invalid constructor")
            kind = "constructor"
        return kind

    def class_key(self, key, computed, static, offset):
        name = None if computed or key["type"] == "PrivateIdentifier" else key.get("name", key.get("value"))
        if self.check_declaration_early_errors and static and name == "prototype":
            raise self.error(offset, "static element named prototype")
        return name


def validate_private(body, offsets, error):
    """Private names in a class body can resolve to that class or an enclosing class."""
    pending = [(body, frozenset())]
    while pending:
        node, names = pending.pop()
        if isinstance(node, list):
            pending.extend((item, names) for item in node)
        elif isinstance(node, dict):
            if node.get("type") in {"ClassDeclaration", "ClassExpression"}:
                pending.append((node["superClass"], names))
                elements = node["body"]["body"]
                declared = {elem["key"]["name"] for elem in elements
                            if elem.get("key", {}).get("type") == "PrivateIdentifier"}
                pending.append((elements, names | declared))
            elif node.get("type") == "PrivateIdentifier":
                if id(node) in offsets and node["name"] not in names:
                    raise error(offsets[id(node)], "undeclared private name")
            else:
                pending.extend((child, names) for child in node.values() if isinstance(child, (dict, list)))
