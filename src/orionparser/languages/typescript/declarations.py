"""TypeScript declarations, module forms, and annotated JavaScript bindings."""

from dataclasses import dataclass


@dataclass
class HeritageClause:
    kind: str
    elements: list
    keyword_offset: int
    comma_offset: int | None
    second_span: tuple[int, int] | None


class DeclarationRules:
    def p_abstract_class(self, p):
        """class_declaration : ABSTRACT class_declaration
           default_declaration : ABSTRACT default_declaration"""
        if p[2]["type"] != "ClassDeclaration":
            raise self.error(p.lexpos(1), "expected abstract class")
        p[0] = p[2]
        p[0]["abstract"] = True

    def p_using_keyword(self, p):
        """using_keyword : USING
                         | AWAIT_USING USING"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = "using" if len(p) == 2 else "await using"

    def p_using_declaration(self, p):
        """lexical_declaration : using_keyword declarators
           for_declaration : using_keyword declarators_no_in"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = self.variable_declaration(p[1], p[2], p.lexpos(1))

    def p_type_exports(self, p):
        """export_decl : EXPORT EXPORT_TYPE named_exports SEMICOLON
                       | EXPORT EXPORT_TYPE named_exports FROM from_source SEMICOLON
                       | EXPORT EXPORT_TYPE MULTIPLY FROM from_source SEMICOLON
                       | EXPORT EXPORT_TYPE MULTIPLY AS module_name FROM from_source SEMICOLON"""
        attrs = {}
        if p.slice[len(p)-2].type == "from_source":
            p[len(p)-2], attrs = p[len(p)-2]
        if p.slice[3].type == "MULTIPLY":
            p[0] = {"type": "ExportAllDeclaration", "exported": p[5] if len(p) == 9 else None,
                    "source": p[len(p)-2]}
        else:
            p[0] = {"type": "ExportNamedDeclaration", "declaration": None, "specifiers": p[3],
                    "source": p[5] if len(p) == 7 else None}
        p[0].update(attrs)
        p[0]["exportKind"] = "type"
        self.export_offsets[id(p[0])] = p.lexpos(1)

    def p_type_export_specifier(self, p):
        """export_name_spec : SPEC_TYPE module_name
                            | SPEC_TYPE module_name AS module_name"""
        p[0] = {"type": "ExportSpecifier", "exportKind": "type", "local": p[2],
                "exported": p[4] if len(p) == 5 else p[2]}

    def check_class_field_key(self, key, computed, static, offset):
        if not computed and key["type"] == "Identifier" and key["name"] == "constructor":
            raise self.error(offset, "field named constructor")

    def class_method_kind(self, key, computed, static, offset, kind, generator, is_async, *, optional=False, generic=False):
        if kind != "method" or generator or self.class_key(key, computed, static, offset) != "constructor":
            return kind
        if key["type"] == "Literal":
            return "method" if optional or generic else "constructor"
        if optional or not self.source.startswith("constructor", offset):
            raise self.error(offset, "invalid constructor name")
        return "constructor"

    def p_heritage(self, p):
        "heritage : ts_params heritage_clauses"
        p[0] = p[1], p[2]

    def p_heritage_clauses(self, p):
        """heritage_clauses :
                            | heritage_clauses heritage_clause"""
        if len(p) == 1:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_heritage_clause(self, p):
        """heritage_clause : EXTENDS
                           | EXTENDS heritage_list
                           | EXTENDS heritage_list COMMA
                           | IMPLEMENTS
                           | IMPLEMENTS heritage_list
                           | IMPLEMENTS heritage_list COMMA"""
        elements = p[2] if len(p) >= 3 else []
        second = getattr(p.slice[2], "second_span", None) if elements else None
        p[0] = HeritageClause(p[1], elements, p.lexpos(1), p.lexpos(3) if len(p) == 4 else None, second)

    def heritage_fields(self, clauses, *, interface=False, parameters=None):
        kinds = [clause.kind for clause in clauses]
        ordinary = kinds in ([], ["extends"]) if interface else kinds in (
            [], ["extends"], ["implements"], ["extends", "implements"])
        fields = {"extends": []} if interface else {"superClass": None, "superTypeArguments": None, "implements": []}
        if ordinary and all(clause.elements and clause.comma_offset is None and (interface or clause.kind != "extends" or len(clause.elements) == 1)
                            for clause in clauses):
            for clause in clauses:
                if not interface and clause.kind == "extends":
                    fields["superClass"], fields["superTypeArguments"] = clause.elements[0]
                else:
                    fields[clause.kind] = [self.heritage_reference(expr, args) for expr, args in clause.elements]
            return fields

        seen = set()
        stopped = False
        fields["heritageClauses"] = []
        for clause in clauses:
            node = {"type": "TSHeritageClause", "kind": clause.kind, "trailingComma": clause.comma_offset is not None,
                    "types": [self.heritage_reference(expr, args) for expr, args in clause.elements]}
            fields["heritageClauses"].append(node)
            if not stopped:
                issue = None
                start, end = clause.keyword_offset, clause.keyword_offset + len(clause.kind)
                if interface and clause.kind == "implements":
                    issue = (1176, "interface declaration cannot have an implements clause")
                elif clause.kind in seen:
                    issue = (1172 if clause.kind == "extends" else 1175, clause.kind + " clause already seen")
                elif clause.kind == "extends" and "implements" in seen:
                    issue = (1173, "extends clause must precede implements clause")
                elif not interface and clause.kind == "extends" and clause.second_span:
                    start, end = clause.second_span
                    issue = (1174, "classes can only extend a single class")
                stopped = issue is not None
                if stopped:
                    self.pending_generic_lists.pop(id(parameters), None)
                elif clause.comma_offset is not None:
                    start, end = clause.comma_offset, clause.comma_offset + 1
                    issue = (1009, "trailing comma not allowed in heritage clause")
                elif not clause.elements:
                    start = end
                    issue = (1097, clause.kind + " list cannot be empty")
                if issue:
                    code, message = issue
                    node["diagnostics"] = [{"code": code, "offset": start, "length": end - start, "message": message}]
            if stopped or (clause.comma_offset is not None and not interface and clause.kind == "extends"):
                for _, args in clause.elements:
                    self.pending_generic_lists.pop(id(args), None)
            seen.add(clause.kind)
        return fields

    def p_missing_class_body(self, p):
        "class_body : MISSING_CLASS_BODY"
        p[0] = {"type": "ClassBody", "body": [], "missing": True}
        self.class_ends[id(p[0])] = p.lexpos(1)

    def p_class_elements(self, p):
        """class_elements :
                          | class_elements class_element
                          | class_elements EMPTY_SEMI"""
        super().p_class_elements(p)
        if len(p) == 3 and p.slice[2].type == "EMPTY_SEMI":
            p[0].append({"type": "SemicolonClassElement"})

    def p_class(self, p):
        """class_declaration : DECL_CLASS identifier heritage class_body
                             | DECL_CLASS heritage class_body
           primary : CLASS identifier heritage class_body
                   | CLASS heritage class_body"""
        params, clauses = p[len(p)-2]
        fields = self.heritage_fields(clauses, parameters=params)
        p[len(p)-2] = fields["superClass"]
        super().p_class(p)
        p[0].update(typeParameters=params, **fields)
        if self.first_pass_contexts is not None and any(member.get("computed") for member in p[0]["body"]["body"]):
            self.first_pass_contexts[id(p[0])] = p.lexpos(1)

    def p_typed_import_specifier(self, p):
        """import_name : SPEC_TYPE module_name
                       | SPEC_TYPE module_name AS identifier"""
        local = p[2] if len(p) == 3 else p[4]
        self.check_import_binding(local, p.lexpos(2))
        p[0] = {"type": "ImportSpecifier", "importKind": "type", "local": local, "imported": p[2]}

    def p_static_modified_element(self, p):
        "class_element : CLASS_STATIC CLASS_MODIFIER class_element"
        node = p[3]
        if node.get("key") is None and node["type"] not in {"TSIndexSignature", "StaticBlock"}:
            raise self.error(p.lexpos(2), "invalid static modifier")
        if node["type"] == "TSIndexSignature":
            self.index_spans[id(node)][0] = p.lexpos(1)
        self.prepend_class_modifiers(node, ["static", p[2]])
        p[0] = node

    def prepend_class_modifiers(self, node, modifiers):
        suffix = node.get("modifiers")
        if suffix is None:
            suffix = ["static"] if node.get("static") else []
            if node["type"] == "MethodDefinition" and node["value"].get("async"):
                suffix.append("async")
        decorators = node.get("decorators", [])
        for decorator in decorators:
            decorator["modifierIndex"] += len(modifiers)
        node["modifiers"] = modifiers + suffix
        for modifier in modifiers:
            if modifier in {"private", "public", "protected"}:
                node["accessibility"] = modifier
            else:
                node[modifier] = True

    def p_ts_type_import(self, p):
        "import_decl : IMPORT TYPE_IMPORT import_clause FROM from_source SEMICOLON"
        p[0] = {"type": "ImportDeclaration", "importKind": "type", "specifiers": p[3], "source": p[5][0], **p[5][1]}
        self.decl_offsets[id(p[0])] = p.lexpos(1)

    def p_modified_class_element(self, p):
        "class_element : CLASS_MODIFIER class_element"
        p[0] = p[2]
        if p[0]["type"] == "TSIndexSignature":
            self.index_spans[id(p[0])][0] = p.lexpos(1)
        self.prepend_class_modifiers(p[0], [p[1]])

    def p_optional_member_name(self, p):
        """optional_member_name : class_element_key QUESTION
                                | CLASS_STATIC class_element_key QUESTION"""
        p[0] = p[len(p)-2], p.slice[1].type == "CLASS_STATIC"

    def p_marked_method_head(self, p):
        """marked_method_head : optional_member_name ts_params formals
                              | class_element_key ts_required_params formals
                              | CLASS_STATIC class_element_key ts_required_params formals
                              | CLASS_ACCESSOR class_element_key ts_required_params formals
                              | CLASS_STATIC CLASS_ACCESSOR class_element_key ts_required_params formals"""
        optional = p.slice[1].type == "optional_member_name"
        key, static = p[1] if optional else (p[len(p)-3], p.slice[1].type == "CLASS_STATIC")
        accessor = next((sym.value for sym in p.slice[1:] if sym.type == "CLASS_ACCESSOR"), None)
        p[0] = key, static, optional, accessor, p[len(p)-2], p[len(p)-1]

    def p_marked_method(self, p):
        """class_element : marked_method_head SEMICOLON
                         | marked_method_head return_annotation SEMICOLON
                         | marked_method_head function_body"""
        (key, computed, _, offset), static, optional, accessor, types, params = p[1]
        kind = self.class_method_kind(key, computed, static, offset, accessor or "method", False, False,
                                      optional=optional, generic=bool(types))
        if p.slice[2].type == "function_body":
            fn = self.function_node("FunctionExpression", None, params, p[2], offset, method=True)
        else:
            fn = {"type": "TSDeclareFunction", "id": None, "params": params, "body": None,
                  "returnType": p[2] if len(p) == 4 else None}
        fn["typeParameters"] = types
        p[0] = {"type": "MethodDefinition", "kind": kind,
                "static": static, "computed": computed, "optional": optional, "key": key, "value": fn}

    def p_static_block(self, p):
        "class_static_block : TS_STATIC_BLOCK STATIC_OPEN static_begin body RBRACE"
        super().p_static_block(p)

    def p_class_static_block_element(self, p):
        """class_element : class_static_block
                         | CLASS_STATIC class_static_block
                         | ASYNC_METHOD class_static_block
                         | CLASS_STATIC ASYNC_METHOD class_static_block
                         | async_class_prefix class_static_block"""
        p[0] = p[len(p)-1]
        if len(p) > 2:
            prefix = p[1] if p.slice[1].type == "async_class_prefix" else p.slice[1:-1]
            self.apply_class_prefix(p[0], prefix)

    def p_async_class_prefix(self, p):
        """async_class_prefix : ASYNC_METHOD CLASS_MODIFIER
                              | ASYNC_METHOD CLASS_STATIC
                              | CLASS_STATIC ASYNC_METHOD CLASS_MODIFIER
                              | async_class_prefix CLASS_MODIFIER
                              | async_class_prefix CLASS_STATIC
                              | async_class_prefix element_decorator"""
        if p.slice[1].type == "async_class_prefix":
            prefix = p[1]
            prefix.append(p.slice[2])
        else:
            prefix = list(p.slice[1:])
        p[0] = prefix

    def apply_class_prefix(self, node, prefix):
        modifiers = []
        decorators = []
        for symbol in prefix:
            if symbol.type == "element_decorator":
                symbol.value["modifierIndex"] = len(modifiers)
                decorators.append(symbol.value)
            else:
                modifiers.append(symbol.value)
        self.prepend_class_modifiers(node, modifiers)
        if decorators:
            node["decorators"] = decorators + node.get("decorators", [])

    def p_async_modified_method_head(self, p):
        """async_modified_head : async_class_prefix class_element_key ts_params async_formals
                               | async_class_prefix CLASS_ACCESSOR class_element_key ts_params async_formals
                               | ASYNC_METHOD CLASS_ACCESSOR class_element_key ts_params async_formals
           async_modified_generator_head : async_class_prefix MULTIPLY class_element_key ts_params async_gen_formals"""
        key, computed, _, offset = p[len(p)-3]
        prefix = p[1] if p.slice[1].type == "async_class_prefix" else [p.slice[1]]
        static = any(symbol.type == "CLASS_STATIC" for symbol in prefix)
        kind = p[2] if p.slice[2].type == "CLASS_ACCESSOR" else "method"
        generator = p.slice[len(p)-1].type == "async_gen_formals"
        kind = self.class_method_kind(key, computed, static, offset, kind, generator, True, generic=bool(p[len(p)-2]))
        p.set_lexpos(0, p.lexpos(len(p)-1))
        method = {"type": "MethodDefinition", "kind": kind, "static": static, "key": key,
                  "computed": computed, "modifiers": []}
        self.apply_class_prefix(method, prefix)
        p[0] = method, p[len(p)-2], p[len(p)-1]

    def p_async_modified_method(self, p):
        """class_element : async_modified_head async_body
                         | async_modified_generator_head async_gen_body
                         | async_modified_head SEMICOLON
                         | async_modified_head return_annotation SEMICOLON
                         | async_modified_generator_head SEMICOLON
                         | async_modified_generator_head return_annotation SEMICOLON"""
        method, types, params = p[1]
        generator = p.slice[1].type == "async_modified_generator_head"
        if p.slice[len(p)-1].type == "SEMICOLON":
            value = {"type": "TSDeclareFunction", "id": None, "params": params, "body": None,
                     "returnType": p[2] if len(p) == 4 else None, "async": True, "generator": generator}
        else:
            value = self.function_node("FunctionExpression", None, params, p[2], p.lexpos(1), method=True,
                                       generator=generator, is_async=True)
        if types:
            value["typeParameters"] = types
        p[0] = {**method, "value": value}

    def p_ts_method_signature(self, p):
        """class_element : class_element_key formals SEMICOLON
                         | class_element_key formals return_annotation SEMICOLON
                         | CLASS_STATIC class_element_key formals SEMICOLON
                         | CLASS_STATIC class_element_key formals return_annotation SEMICOLON
                         | CLASS_ACCESSOR class_element_key formals SEMICOLON
                         | CLASS_ACCESSOR class_element_key formals return_annotation SEMICOLON
                         | CLASS_STATIC CLASS_ACCESSOR class_element_key formals SEMICOLON
                         | CLASS_STATIC CLASS_ACCESSOR class_element_key formals return_annotation SEMICOLON"""
        static = p.slice[1].type == "CLASS_STATIC"
        index = 2 if static else 1
        accessor = p[index] if p.slice[index].type == "CLASS_ACCESSOR" else None
        index += int(accessor is not None)
        key, computed, _, offset = p[index]
        kind = self.class_method_kind(key, computed, static, offset, accessor or "method", False, False)
        signature = {"type": "TSDeclareFunction", "id": None, "params": p[index + 1], "body": None,
                     "returnType": p[index + 2] if p.slice[index + 2].type == "return_annotation" else None}
        p[0] = {"type": "MethodDefinition", "kind": kind, "key": key, "static": static,
                "computed": computed, "value": signature}

    def p_class_field(self, p):
        """ts_class_field : class_element_key class_field_tail
                          | class_element_key QUESTION class_field_tail
                          | class_element_key NOT class_field_tail"""
        key, computed, _, _ = p[1]
        marker = p.slice[2].type
        if marker == "NOT" and p.slice[2].after_line_break:
            raise self.error(p.lexpos(2), "line break before definite assignment assertion")
        annotation, value = p[len(p)-1]
        self.check_class_arguments(value)
        p[0] = {"type": "PropertyDefinition", "key": key, "computed": computed, "static": False, "value": value}
        if annotation or marker in {"NOT", "QUESTION"}:
            p[0]["typeAnnotation"] = annotation
        if marker in {"NOT", "QUESTION"}:
            p[0]["optional"] = marker == "QUESTION"
        if marker == "NOT":
            p[0]["definite"] = True

    def p_class_field_tail(self, p):
        """class_field_tail : SEMICOLON
                            | FIELD_ASSIGN assignment SEMICOLON
                            | annotation SEMICOLON
                            | annotation FIELD_ASSIGN assignment SEMICOLON"""
        p[0] = (p[1] if p.slice[1].type == "annotation" else None,
                p[len(p)-2] if len(p) > 3 else None)

    def p_invalid_class_field_tail(self, p):
        """class_field_tail : FIELD_TERMINATOR_ERROR
                            | FIELD_ASSIGN assignment FIELD_TERMINATOR_ERROR
                            | annotation FIELD_TERMINATOR_ERROR
                            | annotation FIELD_ASSIGN assignment FIELD_TERMINATOR_ERROR"""
        token = p.slice[len(p)-1]
        if token.value == "@":
            raise self.token_error(token, "decorator after class property name", 1436)
        if token.value == "(":
            raise self.token_error(token, "call in property type annotation", 1441)
        if len(p) == 3:
            raise self.token_error(token, "expected = for property initializer", 1442)
        if len(p) > 3:
            raise self.token_error(token, "expected semicolon after property initializer", 1005)
        raise self.class_name_separator_error(p, token)

    def p_class_field_element(self, p):
        """class_element : ts_class_field
                         | CLASS_STATIC ts_class_field
                         | ASYNC_METHOD ts_class_field
                         | async_class_prefix ts_class_field
                         | CLASS_STATIC ASYNC_METHOD ts_class_field"""
        node = p[len(p)-1]
        if len(p) == 3 and p.slice[1].type == "CLASS_STATIC":
            node["static"] = True
        elif len(p) > 2:
            prefix = p[1] if p.slice[1].type == "async_class_prefix" else p.slice[1:-1]
            self.apply_class_prefix(node, prefix)
        self.check_class_field_key(node["key"], node["computed"], node["static"], self.class_key_offsets[id(node["key"])])
        p[0] = node

    def p_generic_generator(self, p):
        """function_declaration : DECL_FUNCTION MULTIPLY identifier ts_required_params generator_formals generator_body
           default_declaration : DEFAULT_FUNCTION MULTIPLY identifier ts_required_params generator_formals generator_body
                               | DEFAULT_FUNCTION MULTIPLY ts_required_params generator_formals generator_body
           primary : FUNCTION MULTIPLY identifier ts_required_params generator_formals generator_body
                   | FUNCTION MULTIPLY ts_required_params generator_formals generator_body"""
        kind = "FunctionExpression" if p.slice[1].type == "FUNCTION" else "FunctionDeclaration"
        name = p[3] if p.slice[3].type == "identifier" else None
        p[0] = self.function_node(kind, name, p[len(p)-2], p[len(p)-1], p.lexpos(1), generator=True)
        p[0]["typeParameters"] = p[len(p)-3]

    def p_generic_async_function(self, p):
        """function_declaration : DECL_ASYNC FUNCTION identifier ts_required_params async_formals async_body
                                | DECL_ASYNC FUNCTION MULTIPLY identifier ts_required_params async_gen_formals async_gen_body
           default_declaration : DEFAULT_ASYNC FUNCTION ts_required_params async_formals async_body
                               | DEFAULT_ASYNC FUNCTION identifier ts_required_params async_formals async_body
                               | DEFAULT_ASYNC FUNCTION MULTIPLY ts_required_params async_gen_formals async_gen_body
                               | DEFAULT_ASYNC FUNCTION MULTIPLY identifier ts_required_params async_gen_formals async_gen_body
           primary : EXPR_ASYNC FUNCTION ts_required_params async_formals async_body
                   | EXPR_ASYNC FUNCTION identifier ts_required_params async_formals async_body
                   | EXPR_ASYNC FUNCTION MULTIPLY ts_required_params async_gen_formals async_gen_body
                   | EXPR_ASYNC FUNCTION MULTIPLY identifier ts_required_params async_gen_formals async_gen_body"""
        name_index = len(p) - 4
        name = p[name_index] if p.slice[name_index].type == "identifier" else None
        expression = p.slice[1].type == "EXPR_ASYNC"
        generator = p.slice[len(p)-2].type == "async_gen_formals"
        p[0] = self.function_node("FunctionExpression" if expression else "FunctionDeclaration", name,
                                  p[len(p)-2], p[len(p)-1], p.lexpos(1), generator=generator, is_async=True)
        p[0]["typeParameters"] = p[len(p)-3]

    def p_object_decorators(self, p):
        """object_decorators : element_decorator
                             | object_decorators element_decorator"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_object_modifier(self, p):
        """property : OBJECT_MODIFIER property
                    | OBJECT_DECORATED_MODIFIER object_decorators property"""
        node = p[len(p)-1]
        if node["type"] == "SpreadElement":
            raise self.error(p.lexpos(len(p)-1), "modifier before object spread")
        modifiers = node.get("modifiers")
        if modifiers is None:
            modifiers = ["async"] if node.get("method") and node["value"].get("async") else []
            node["modifiers"] = modifiers
        if p[1] == "static" and "static" in modifiers:
            raise self.error(p.lexpos(1), "duplicate static object member modifier")
        if len(p) == 4:
            if node.get("decorators"):
                raise self.error(p.lexpos(1), "second decorator list in object member")
            node["decorators"] = p[2]
            for decorator in p[2]:
                decorator["modifierIndex"] = 1
        else:
            for decorator in node.get("decorators", ()):
                decorator["modifierIndex"] += 1
        modifiers.insert(0, p[1])
        self.object_marker_offsets[id(node["key"])] = p.lexpos(1)
        p[0] = node

    def p_object_signature_end(self, p):
        """object_signature_end : SEMICOLON
                                | return_annotation SEMICOLON"""
        p[0] = {"type": "TSDeclareFunction", "body": None, "returnType": p[1] if len(p) == 3 else None}

    def p_object_method_body(self, p):
        """object_method_body : function_body
                              | object_signature_end
           object_async_body : async_body
                             | object_signature_end
           object_gen_body : generator_body
                           | object_signature_end
           object_async_gen_body : async_gen_body
                                 | object_signature_end"""
        p[0] = p[1]

    def p_accessor(self, p):
        "property : CLASS_ACCESSOR property_key formals object_method_body"
        self.build_accessor(p, p[1], p.lexpos(1))

    def p_object_async_prefix(self, p):
        """object_async_prefix : OBJECT_ASYNC
                               | object_async_prefix OBJECT_ASYNC
                               | object_async_prefix OBJECT_MODIFIER
                               | object_async_prefix OBJECT_DECORATED_MODIFIER object_decorators"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            if p[2] == "static" and "static" in p[1]:
                raise self.error(p.lexpos(2), "duplicate static object member modifier")
            p[0] = p[1]
            p[0].append(p[2])
            decorators = getattr(p.slice[1], "decorators", None)
            if len(p) == 4:
                if decorators:
                    raise self.error(p.lexpos(2), "second decorator list in object member")
                decorators = p[3]
                for decorator in decorators:
                    decorator["modifierIndex"] = len(p[0])
            if decorators:
                p.slice[0].decorators = decorators
        p.set_lexpos(0, p.lexpos(1))

    def attach_object_async_prefix(self, p):
        p[0]["modifiers"] = p[1]
        if hasattr(p.slice[1], "decorators"):
            p[0]["decorators"] = p.slice[1].decorators

    def p_async_data_property(self, p):
        """property : object_async_prefix object_key
                    | object_async_prefix object_key COLON assignment
                    | object_async_prefix object_key ASSIGN assignment"""
        self.build_property(p, 2)
        p[0].update(p.slice[2].markers)
        self.attach_object_async_prefix(p)
        self.cover_errors.pop(id(p[0]), None)
        self.object_marker_offsets[id(p[0]["key"])] = p.lexpos(1)

    def p_async_object_accessor(self, p):
        "property : object_async_prefix CLASS_ACCESSOR property_key ts_params async_formals object_async_body"
        key, computed, _, _ = p[3]
        value = self.function_node("FunctionExpression", None, p[5], p[6], p.lexpos(5), method=True, is_async=True)
        if p[4]:
            value["typeParameters"] = p[4]
        p[0] = {"type": "Property", "kind": p[2], "key": key, "value": value, "computed": computed,
                "shorthand": False, "method": False}
        self.attach_object_async_prefix(p)

    def p_property_key(self, p):
        """property_key : property_name
                        | string_literal
                        | numeric_literal
                        | LBRACKET expression RBRACKET"""
        super().p_property_key(p)
        token = getattr(p.slice[1], "identifier_token", None)
        if token and (token.type == "LET" or token.value == "yield"
                      or (token.value == "await" and token.lexpos in self.script_context_offsets)):
            key, computed, _, offset = p[0]
            p[0] = (key, computed, not getattr(token, "in_yield_context", False), offset)

    def p_object_key(self, p):
        """object_key : property_key
                      | property_key QUESTION
                      | property_key NOT
                      | property_key QUESTION NOT"""
        p[0] = p[1]
        key, computed, shorthand_allowed, offset = p[1]
        following = self.source_lookahead
        if not shorthand_allowed and following.type in {"ASSIGN", "COMMA", "RBRACE"}:
            error = self.token_error(following, f"{following.value!r} where ':' was required after the property name", 1005)
            if self.script_pass is None:
                raise error
            # The preliminary script tree is used to find later module indicators.
            # Its stored diagnostic rejects this shorthand even if yacc reaches EOF.
            self.script_pass.record(error)
            p[0] = (key, computed, True, offset)
        if (self.first_pass_contexts is not None and shorthand_allowed and key.get("name") == "await"
                and following.type in {"ASSIGN", "COMMA", "RBRACE"}):
            self.first_pass_contexts[id(key)] = offset
        p.slice[0].markers = {}
        if len(p) > 2:
            self.object_marker_offsets[id(p[1][0])] = p.lexpos(2)
        if len(p) > 2 and p.slice[2].type == "QUESTION":
            p.slice[0].markers["optional"] = True
        if p.slice[len(p)-1].type == "NOT":
            p.slice[0].markers["definite"] = True

    def p_property(self, p):
        """property : object_key COLON assignment
                    | object_key ASSIGN assignment
                    | object_key formals object_method_body
                    | object_key"""
        super().p_property(p)
        p[0].update(p.slice[1].markers)
        if len(p) == 4 and p.slice[2].type == "ASSIGN":
            self.cover_errors.pop(id(p[0]), None)

    def p_async_method(self, p):
        """property : object_async_prefix object_key async_formals object_async_body
                    | object_async_prefix MULTIPLY object_key async_gen_formals object_async_gen_body"""
        super().p_async_method(p)
        if len(p[1]) > 1:
            self.attach_object_async_prefix(p)
        p[0].update(p.slice[len(p)-3].markers)

    def p_generator_method(self, p):
        "property : MULTIPLY object_key generator_formals object_gen_body"
        super().p_generator_method(p)
        p[0].update(p.slice[2].markers)

    def p_generic_async_method(self, p):
        """property : object_async_prefix object_key ts_required_params async_formals object_async_body
                    | object_async_prefix MULTIPLY object_key ts_required_params async_gen_formals object_async_gen_body
           class_element : ASYNC_METHOD class_element_key ts_required_params async_formals async_body
                         | ASYNC_METHOD MULTIPLY class_element_key ts_required_params async_gen_formals async_gen_body
                         | CLASS_STATIC ASYNC_METHOD class_element_key ts_required_params async_formals async_body
                         | CLASS_STATIC ASYNC_METHOD MULTIPLY class_element_key ts_required_params async_gen_formals async_gen_body"""
        self.generic_method_node(p, is_async=True)
        if p.slice[1].type == "object_async_prefix" and len(p[1]) > 1:
            self.attach_object_async_prefix(p)

    def p_generic_generator_method(self, p):
        """property : MULTIPLY object_key ts_required_params generator_formals object_gen_body
           class_element : MULTIPLY class_element_key ts_required_params generator_formals generator_body
                         | CLASS_STATIC MULTIPLY class_element_key ts_required_params generator_formals generator_body"""
        self.generic_method_node(p, is_async=False)

    def generic_method_node(self, p, is_async):
        key, computed, _, offset = p[len(p)-4]
        generator = p.slice[len(p)-2].type in {"async_gen_formals", "generator_formals"}
        value = self.function_node("FunctionExpression", None, p[len(p)-2], p[len(p)-1], p.lexpos(len(p)-2),
                                   method=True, generator=generator, is_async=is_async)
        value["typeParameters"] = p[len(p)-3]
        if p.slice[0].type == "property":
            p[0] = {"type": "Property", "kind": "init", "key": key, "value": value,
                    "computed": computed, "shorthand": False, "method": True, **p.slice[len(p)-4].markers}
        else:
            static = p.slice[1].type == "CLASS_STATIC"
            kind = self.class_method_kind(key, computed, static, offset, "method", generator, is_async, generic=True)
            p[0] = {"type": "MethodDefinition", "kind": kind, "key": key, "value": value,
                    "static": static, "computed": computed}

    def p_generic_object_accessor(self, p):
        "property : CLASS_ACCESSOR property_key ts_required_params formals object_method_body"
        self.p_accessor(p)
        p[0]["value"]["typeParameters"] = p[3]

    def p_generic_object_method(self, p):
        "property : object_key ts_required_params formals object_method_body"
        key, computed, _, offset = p[1]
        value = self.function_node("FunctionExpression", None, p[3], p[4], offset, method=True)
        value["typeParameters"] = p[2]
        p[0] = {"type": "Property", "kind": "init", "key": key, "value": value,
                "computed": computed, "shorthand": False, "method": True, **p.slice[1].markers}

    def p_generic_function(self, p):
        """function_declaration : DECL_FUNCTION identifier ts_required_params formals function_body
           default_declaration : DEFAULT_FUNCTION identifier ts_required_params formals function_body
                               | DEFAULT_FUNCTION ts_required_params formals function_body
           primary : FUNCTION identifier ts_required_params formals function_body
                   | FUNCTION ts_required_params formals function_body"""
        kind = "FunctionExpression" if p.slice[1].type == "FUNCTION" else "FunctionDeclaration"
        name = p[2] if p.slice[2].type == "identifier" else None
        p[0] = self.function_node(kind, name, p[len(p)-2], p[len(p)-1], p.lexpos(1))
        p[0]["typeParameters"] = p[len(p)-3]

    def p_generator_signature(self, p):
        """function_declaration : DECL_FUNCTION MULTIPLY identifier generator_signature
           default_declaration : DEFAULT_FUNCTION MULTIPLY identifier generator_signature
                               | DEFAULT_FUNCTION MULTIPLY generator_signature"""
        name = p[3] if len(p) == 5 else None
        p[0] = {"type": "TSDeclareFunction", "id": name, "async": False, "body": None, **p[len(p)-1]}

    def p_class_function_signature(self, p):
        """class_element : MULTIPLY class_element_key generator_signature
                         | CLASS_STATIC MULTIPLY class_element_key generator_signature
                         | ASYNC_METHOD class_element_key async_signature
                         | CLASS_STATIC ASYNC_METHOD class_element_key async_signature
                         | ASYNC_METHOD MULTIPLY class_element_key async_generator_signature
                         | CLASS_STATIC ASYNC_METHOD MULTIPLY class_element_key async_generator_signature
                         | MULTIPLY class_element_key QUESTION generator_signature
                         | CLASS_STATIC MULTIPLY class_element_key QUESTION generator_signature
                         | ASYNC_METHOD class_element_key QUESTION async_signature
                         | CLASS_STATIC ASYNC_METHOD class_element_key QUESTION async_signature
                         | ASYNC_METHOD MULTIPLY class_element_key QUESTION async_generator_signature
                         | CLASS_STATIC ASYNC_METHOD MULTIPLY class_element_key QUESTION async_generator_signature"""
        optional = p.slice[len(p)-2].type == "QUESTION"
        key, computed, _, offset = p[len(p)-3 if optional else len(p)-2]
        signature = p[len(p)-1]
        static = p.slice[1].type == "CLASS_STATIC"
        is_async = p.slice[len(p)-1].type != "generator_signature"
        kind = self.class_method_kind(key, computed, static, offset, "method", signature["generator"], is_async,
                                      optional=optional, generic=bool(signature["typeParameters"]))
        p[0] = {"type": "MethodDefinition", "kind": kind, "key": key, "computed": computed, "static": static,
                "optional": optional, "value": {"type": "TSDeclareFunction", "id": None, "async": is_async, "body": None, **signature}}

    def p_async_signature(self, p):
        """function_declaration : DECL_ASYNC FUNCTION identifier async_signature
                                | DECL_ASYNC FUNCTION MULTIPLY identifier async_generator_signature
           default_declaration : DEFAULT_ASYNC FUNCTION identifier async_signature
                               | DEFAULT_ASYNC FUNCTION async_signature
                               | DEFAULT_ASYNC FUNCTION MULTIPLY identifier async_generator_signature
                               | DEFAULT_ASYNC FUNCTION MULTIPLY async_generator_signature"""
        name = p[len(p)-2] if p.slice[len(p)-2].type == "identifier" else None
        p[0] = {"type": "TSDeclareFunction", "id": name, "async": True, "body": None, **p[len(p)-1]}

    def p_function_signature_tail(self, p):
        """async_signature : async_formals SEMICOLON
                           | async_formals return_annotation SEMICOLON
                           | ts_required_params async_formals SEMICOLON
                           | ts_required_params async_formals return_annotation SEMICOLON
           generator_signature : generator_formals SEMICOLON
                               | generator_formals return_annotation SEMICOLON
                               | ts_required_params generator_formals SEMICOLON
                               | ts_required_params generator_formals return_annotation SEMICOLON
           async_generator_signature : async_gen_formals SEMICOLON
                                     | async_gen_formals return_annotation SEMICOLON
                                     | ts_required_params async_gen_formals SEMICOLON
                                     | ts_required_params async_gen_formals return_annotation SEMICOLON"""
        generic = p.slice[1].type == "ts_required_params"
        p[0] = {"generator": p.slice[0].type != "async_signature", "params": p[2 if generic else 1],
                "typeParameters": p[1] if generic else None,
                "returnType": p[len(p)-2] if p.slice[len(p)-2].type == "return_annotation" else None}

    def p_modified_async_function(self, p):
        """function_declaration : MODIFIED_ASYNC_FUNCTION identifier async_signature
                                | MODIFIED_ASYNC_FUNCTION MULTIPLY identifier async_generator_signature
                                | MODIFIED_ASYNC_FUNCTION identifier async_formals async_body
                                | MODIFIED_ASYNC_FUNCTION identifier ts_required_params async_formals async_body
                                | MODIFIED_ASYNC_FUNCTION MULTIPLY identifier async_gen_formals async_gen_body
                                | MODIFIED_ASYNC_FUNCTION MULTIPLY identifier ts_required_params async_gen_formals async_gen_body"""
        generator = p.slice[2].type == "MULTIPLY"
        name = p[3 if generator else 2]
        if p.slice[len(p)-1].type in {"async_signature", "async_generator_signature"}:
            node = {"type": "TSDeclareFunction", "id": name, "async": True, "body": None, **p[len(p)-1]}
        else:
            node = self.function_node("FunctionDeclaration", name, p[len(p)-2], p[len(p)-1], p.lexpos(1),
                                      is_async=True, generator=generator)
            if p.slice[len(p)-3].type == "ts_required_params":
                node["typeParameters"] = p[len(p)-3]
        node["modifiers"] = []
        p[0] = node

    def p_signature_tail(self, p):
        """signature_tail : formals SEMICOLON
                          | formals return_annotation SEMICOLON"""
        p[0] = {"params": p[1], "returnType": p[2] if len(p) == 4 else None}

    def p_function_signature(self, p):
        """function_declaration : DECL_FUNCTION identifier signature_tail
                                | DECL_FUNCTION identifier ts_required_params signature_tail
           default_declaration : DEFAULT_FUNCTION identifier signature_tail
                               | DEFAULT_FUNCTION identifier ts_required_params signature_tail
                               | DEFAULT_FUNCTION signature_tail
                               | DEFAULT_FUNCTION ts_required_params signature_tail"""
        name = p[2] if p.slice[2].type == "identifier" else None
        types = p[len(p)-2] if p.slice[len(p)-2].type == "ts_required_params" else None
        p[0] = {"type": "TSDeclareFunction", "id": name, "typeParameters": types, **p[len(p)-1]}

    def p_empty_declaration(self, p):
        """variable_declaration : VAR
           lexical_declaration : CONST
                               | using_keyword
                               | MODIFIED_LET
           for_declaration : VAR
                           | CONST
                           | FOR_LET
                           | using_keyword"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = self.variable_declaration(p[1], [], p.lexpos(1))

    def p_trailing_declaration_comma(self, p):
        """variable_declaration : VAR declarators COMMA
           lexical_declaration : LET declarators COMMA
                               | CONST declarators COMMA
                               | using_keyword declarators COMMA
           for_declaration : VAR declarators_no_in COMMA
                           | FOR_LET declarators_no_in COMMA
                           | CONST declarators_no_in COMMA
                           | using_keyword declarators_no_in COMMA"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = self.variable_declaration(p[1], p[2], p.lexpos(1))
        p[0]["trailingComma"] = True

    def p_for_declaration(self, p):
        """for_declaration : VAR declarators_no_in
                           | FOR_LET declarators_no_in
                           | CONST declarators_no_in"""
        super().p_for_declaration(p)

    def p_iteration(self, p):
        """statement : FOR LPAREN expression_no_in IN expression RPAREN statement
                     | FOR LPAREN expression_no_in OF assignment RPAREN statement
                     | FOR LPAREN for_declaration IN expression RPAREN statement
                     | FOR LPAREN for_declaration OF assignment RPAREN statement
                     | async_for LPAREN expression_no_in OF assignment RPAREN statement
                     | async_for LPAREN for_declaration OF assignment RPAREN statement"""
        super().p_iteration(p)

    def p_module_items(self, p):
        """module_items :
                        | module_items list_item"""
        if len(p) == 1 and p.stack[-1].type == "TS_GOAL" and self.script_pass is not None:
            p[0] = self.script_pass.statements
        else:
            super().p_module_items(p)

    def p_list_item(self, p):
        "list_item : statement"
        p[0] = p[1]

    def p_statement_declaration(self, p):
        """statement : class_declaration
                     | function_declaration
                     | ts_enum
                     | lexical_declaration SEMICOLON"""
        p[0] = p[1]

    def p_ts_item(self, p):
        """statement : ts_alias
                     | ts_interface
                     | ts_namespace
                     | ts_ambient
                     | modified_decl
                     | import_decl
                     | export_decl"""
        p[0] = p[1]

    def p_default_export(self, p):
        """export_decl : EXPORT DEFAULT assignment SEMICOLON
                       | EXPORT DEFAULT default_declaration"""
        decl = p[3]
        if len(p) == 4 and (decl.get("decorators") or decl.get("modifiers")):
            self.prepend_declaration_modifier(decl, "default", p.lexpos(2))
            self.prepend_declaration_modifier(decl, "export", p.lexpos(1))
            if decl["type"].startswith(("Export", "TSExport", "TSNamespaceExport")):
                self.export_offsets[id(decl)] = p.lexpos(1)
                p[0] = decl
                return
        super().p_default_export(p)

    def p_ts_export(self, p):
        """export_decl : EXPORT ts_alias
                       | EXPORT ts_interface
                       | EXPORT ts_enum
                       | EXPORT ts_namespace
                       | EXPORT import_decl
                       | EXPORT ts_ambient
                       | EXPORT modified_decl"""
        if p[2]["type"].startswith(("Export", "TSExport", "TSNamespaceExport")):
            p[0] = self.prepend_declaration_modifier(p[2], "export", p.lexpos(1))
            return
        if p[2].get("modifiers") or p[2].get("decorators"):
            self.prepend_declaration_modifier(p[2], "export", p.lexpos(1))
        if p[2].get("default"):
            p[0] = {"type": "ExportDefaultDeclaration", "declaration": p[2]}
        else:
            p[0] = {"type": "ExportNamedDeclaration", "declaration": p[2], "source": None, "specifiers": []}
        self.export_offsets[id(p[0])] = p.lexpos(1)

    def p_ts_external_import(self, p):
        "import_decl : ts_import_alias"
        p[0] = p[1]

    def p_ts_import_alias(self, p):
        """ts_import_alias : IMPORT identifier ASSIGN alias_reference SEMICOLON
                           | IMPORT TYPE_IMPORT identifier ASSIGN alias_reference SEMICOLON"""
        typed = p.slice[2].type == "TYPE_IMPORT"
        p[0] = {"type": "TSImportEqualsDeclaration", "id": p[3] if typed else p[2],
                "moduleReference": p[len(p)-2]}
        if typed:
            p[0]["importKind"] = "type"

    def p_alias_reference(self, p):
        """alias_reference : ts_name
                           | identifier LPAREN module_specifier RPAREN"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            if p[1]["name"] != "require" or not self.source.startswith("require", p.lexpos(1)):
                raise self.error(p.lexpos(1), "expected require in import declaration")
            p[0] = {"type": "TSExternalModuleReference", "expression": p[3]}

    def p_ts_export_assignment(self, p):
        "export_decl : EXPORT ASSIGN assignment SEMICOLON"
        p[0] = {"type": "TSExportAssignment", "expression": p[3]}

    def p_ts_export_namespace(self, p):
        "export_decl : EXPORT AS NS identifier SEMICOLON"
        p[0] = {"type": "TSNamespaceExportDeclaration", "id": p[4]}

    def p_namespace_name(self, p):
        """namespace_name : identifier
                          | namespace_name DOT property_name
                          | namespace_name DOT PRIVATE_NAME"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            name = {"type": "Identifier", "name": "#" + p[3]} if p.slice[3].type == "PRIVATE_NAME" else p[3]
            p[0] = {"type": "TSQualifiedName", "left": p[1], "right": name}

    def p_ts_namespace(self, p):
        """ts_namespace : NS namespace_name LBRACE module_items RBRACE
                        | TS_MODULE namespace_name LBRACE module_items RBRACE
                        | TS_MODULE string_literal LBRACE module_items RBRACE
                        | TS_MODULE string_literal SEMICOLON
                        | GLOBAL LBRACE module_items RBRACE
                        | GLOBAL SEMICOLON"""
        if p.slice[1].type == "GLOBAL":
            ident = {"type": "Identifier", "name": "global"}
            body = {"type": "TSModuleBlock", "body": p[3]} if len(p) == 5 else None
        else:
            ident = p[2]
            body = None if len(p) == 4 else {"type": "TSModuleBlock", "body": p[4]}
        while ident["type"] == "TSQualifiedName":
            body = {"type": "TSModuleDeclaration", "kind": p[1], "id": ident["right"], "body": body}
            ident = ident["left"]
        p[0] = {"type": "TSModuleDeclaration", "kind": p[1], "id": ident, "body": body}

        if self.first_pass_contexts is not None and body is not None:
            opening = 2 if p.slice[1].type == "GLOBAL" else 3
            self.first_pass_contexts[id(p[0])] = p.lexpos(opening)

    def p_ts_enum(self, p):
        """ts_enum : TS_ENUM identifier ENUM_OPEN enum_body RBRACE
                   | CONST TS_ENUM identifier ENUM_OPEN enum_body RBRACE"""
        p[0] = {"type": "TSEnumDeclaration", "id": p[len(p)-4], "const": p.slice[1].type == "CONST",
                "members": p[len(p)-2]}
        if p.slice[len(p)-2].trailing:
            p[0]["trailingComma"] = True

    def p_enum_body(self, p):
        """enum_body :
                     | enum_members
                     | enum_members COMMA"""
        p.slice[0].trailing = len(p) == 3
        p[0] = p[1] if len(p) > 1 else []

    def p_enum_members(self, p):
        """enum_members : enum_member
                        | enum_members COMMA enum_member"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_enum_member(self, p):
        """enum_member : property_key
                       | property_key ASSIGN assignment"""
        key, computed, _, _ = p[1]
        p[0] = {"type": "TSEnumMember", "id": key, "computed": computed, "initializer": p[3] if len(p) == 4 else None}

    def p_ts_interface(self, p):
        """ts_interface : INTERFACE identifier ts_params heritage_clauses LBRACE type_members RBRACE
           default_declaration : DEFAULT_INTERFACE identifier ts_params heritage_clauses LBRACE type_members RBRACE"""
        p[0] = {"type": "TSInterfaceDeclaration", "id": p[2], "typeParameters": p[3], **self.heritage_fields(p[4], interface=True),
                "body": {"type": "TSInterfaceBody", "body": p[6]}}
        if self.first_pass_contexts is not None and p[2]["name"] == "await":
            self.first_pass_contexts[id(p[0])] = p.lexpos(1)

    def p_heritage_list(self, p):
        """heritage_list : heritage_element
                         | heritage_list COMMA heritage_element"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p.slice[0].second_span = ((p.slice[2].item_start, p.slice[2].item_end) if len(p[1]) == 1
                                      else p.slice[1].second_span)
            p[1].append(p[3])
            p[0] = p[1]

    def p_heritage_element(self, p):
        """heritage_element : chain
                            | chain ts_arguments"""
        expr = p[1]
        arguments = p[2] if len(p) == 3 else None
        if arguments is None and expr["type"] == "TSInstantiationExpression" and id(expr) not in self.grouped_patterns:
            expr, arguments = expr["expression"], expr["typeArguments"]
        leading = expr
        fields = {"MemberExpression": "object", "CallExpression": "callee", "TaggedTemplateExpression": "tag",
                  "TSInstantiationExpression": "expression", "ChainExpression": "expression", "TSNonNullExpression": "expression"}
        while leading["type"] in fields and id(leading) not in self.grouped_patterns:
            leading = leading[fields[leading["type"]]]
        if leading["type"] == "PrivateIdentifier" and id(leading) not in self.grouped_patterns:
            raise self.error(self.private_offsets[id(leading)], "private identifier at start of heritage clause")
        p[0] = expr, arguments

    def heritage_reference(self, expr, arguments):
        # Keep the existing type-reference representation for ordinary entity names.
        parts, base = [], expr
        while base["type"] == "MemberExpression" and not base["computed"] and id(base) not in self.grouped_patterns:
            parts.append(base["property"])
            base = base["object"]
        if base["type"] == "Identifier" and id(base) not in self.grouped_patterns and all(q["type"] == "Identifier" for q in parts):
            for right in reversed(parts):
                base = {"type": "TSQualifiedName", "left": base, "right": right}
            return {"type": "TSTypeReference", "typeName": base, "typeArguments": arguments}
        return {"type": "TSExpressionWithTypeArguments", "expression": expr, "typeArguments": arguments}

    def p_alias(self, p):
        """ts_alias : TYPE_ALIAS identifier ts_params ASSIGN ts_type SEMICOLON
                    | TYPE_ALIAS identifier ts_params ASSIGN INTRINSIC_ALIAS SEMICOLON"""
        value = {"type": "TSIntrinsicKeyword"} if p.slice[5].type == "INTRINSIC_ALIAS" else p[5]
        p[0] = {"type": "TSTypeAliasDeclaration", "id": p[2], "typeParameters": p[3], "typeAnnotation": value}
        if self.first_pass_contexts is not None and p[2]["name"] == "await":
            self.first_pass_contexts[id(p[0])] = p.lexpos(1)

    def invalid_shorthand_binding(self, p, offset):
        following = p.slice[2] if len(p) > 2 else self.source_lookahead
        error = self.token_error(following, "expected ':' after binding property name", 1005)
        if self.script_pass is None:
            raise error
        self.script_pass.record(error)

    def mark_literal_trailing_comma(self, literal):
        super().mark_literal_trailing_comma(literal)
        literal["trailingComma"] = True

    def p_binding(self, p):
        """binding : identifier
                   | binding_array
                   | binding_object"""
        super().p_binding(p)
        if p.slice[1].type == "identifier":
            escaped = getattr(p.slice[1], "escaped_token", None)
            p.slice[0].name_end = escaped.end_pos if escaped else p.lexpos(1) + len(p[1]["name"])
        else:
            p.slice[0].name_end = p.slice[1].name_end

    def p_binding_rest(self, p):
        "binding_rest : ELLIPSIS binding_element"
        p[0] = {"type": "RestElement", "argument": p[2]}

    def p_binding_prefix(self, p):
        """binding_prefix :
                          | binding_prefix COMMA
                          | binding_prefix binding_element COMMA
                          | binding_prefix binding_rest COMMA"""
        super().p_binding_prefix(p)

    def p_binding_array(self, p):
        """binding_array : BIND_ARRAY binding_prefix RBRACKET
                         | BIND_ARRAY binding_prefix binding_element RBRACKET
                         | BIND_ARRAY binding_prefix binding_rest RBRACKET"""
        super().p_binding_array(p)
        p.slice[0].name_end = p.slice[-1].lexpos + 1
        if len(p) == 4 and p[2]:
            p[0]["trailingComma"] = True

    def p_object_rest(self, p):
        "object_rest : ELLIPSIS binding_property"
        prop = p[2]
        p[0] = {"type": "RestElement", "argument": prop["value"]}
        if not prop["shorthand"]:
            p[0].update(propertyName=prop["key"], computed=prop["computed"])

    def p_binding_props(self, p):
        """binding_props : binding_property
                         | object_rest
                         | binding_props COMMA binding_property
                         | binding_props COMMA object_rest"""
        super().p_binding_props(p)

    def p_binding_object(self, p):
        """binding_object : BIND_OBJECT RBRACE
                          | BIND_OBJECT binding_props RBRACE
                          | BIND_OBJECT binding_props COMMA RBRACE"""
        super().p_binding_object(p)
        p.slice[0].name_end = p.slice[-1].lexpos + 1
        if len(p) == 5:
            p[0]["trailingComma"] = True

    def p_binding_chain_recovery(self, p):
        "binding : identifier INVALID_BINDING_CHAIN chain"
        # Only the provisional script tree includes the invalid expression.
        p.set_lexpos(0, p.lexpos(1))
        p.slice[0].name_end = p.lexpos(1) + len(p[1]["name"])
        p[0] = {**p[1], "recoveryExpression": p[3]}

    def p_annotated_binding(self, p):
        "annotated_binding : binding annotation"
        p.slice[0].name_end = p.slice[1].name_end
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {**p[1], "typeAnnotation": p[2]}

    def p_ts_declarator(self, p):
        """declarator : annotated_binding
                      | annotated_binding ASSIGN assignment
           declarator_no_in : annotated_binding
                            | annotated_binding ASSIGN assignment_no_in"""
        self.p_declarator(p)

    def p_definite_declarator(self, p):
        """declarator : identifier DEFINITE
                      | identifier DEFINITE annotation
                      | identifier DEFINITE ASSIGN assignment
                      | identifier DEFINITE annotation ASSIGN assignment"""
        binding = p[1]
        if len(p) > 3 and p.slice[3].type == "annotation":
            binding = {**binding, "typeAnnotation": p[3]}
        value = p[len(p)-1] if p.slice[len(p)-2].type == "ASSIGN" else None
        p[0] = {"type": "VariableDeclarator", "id": binding, "init": value, "definite": True}

    def p_parameter(self, p):
        """parameter : binding
                     | binding ASSIGN assignment"""
        super().p_parameter(p)
        self.parameter_spans[id(p[0])] = (p.lexpos(1), p.slice[1].name_end)

    def p_ts_parameter(self, p):
        """parameter : annotated_binding
                     | annotated_binding ASSIGN assignment"""
        self.p_parameter(p)

    def p_parameter_property(self, p):
        "ts_parameter : PARAM_MODIFIER ts_parameter"
        p[0] = p[2]
        if p[1] == "static" and "static" in p[0].get("modifiers", []):
            raise self.error(p.lexpos(1), "duplicate static parameter modifier")
        self.apply_parameter_modifier(p[0], p[1])

    def apply_parameter_modifier(self, parameter, modifier):
        for decorator in parameter.get("decorators", ()):
            decorator["modifierIndex"] = decorator.get("modifierIndex", 0) + 1
        if modifier in {"public", "private", "protected", "readonly", "override"}:
            parameter["parameterProperty"] = True
        parameter.setdefault("modifiers", []).insert(0, modifier)
        if modifier in {"public", "private", "protected"}:
            parameter["accessibility"] = modifier
        else:
            parameter[modifier] = True

    def p_this_parameter(self, p):
        """parameter : THIS
                     | THIS annotation"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "Identifier", "name": "this"}
        self.parameter_spans[id(p[0])] = (p.lexpos(1), p.lexpos(1) + 4)
        if len(p) == 3:
            p[0]["typeAnnotation"] = p[2]

    def p_optional_parameter(self, p):
        """optional_binding : binding QUESTION
                            | binding QUESTION annotation"""
        p.set_lexpos(0, p.lexpos(1))
        p.slice[0].name_end = p.slice[1].name_end
        p[0] = {**p[1], "optional": True}
        self.optional_parameter_offsets[id(p[0])] = p.lexpos(2)
        if len(p) == 4:
            p[0]["typeAnnotation"] = p[3]

    def p_optional_parameter_value(self, p):
        """parameter : optional_binding
                     | optional_binding ASSIGN assignment"""
        self.p_parameter(p)

    def p_rest_parameter(self, p):
        "rest_parameter : ELLIPSIS parameter"
        if p[2].get("name") == "this":
            raise self.error(p.lexpos(2), "this cannot be a rest parameter")
        p[0] = {"type": "RestElement", "argument": p[2]}
        self.parameter_spans[id(p[0])] = (p.lexpos(1), p.lexpos(1) + 3)

    def p_ts_return_body(self, p):
        """function_body : return_annotation FN_OPEN function_scope body RBRACE
           async_body : return_annotation ASYNC_OPEN function_scope body RBRACE
           generator_body : return_annotation GEN_OPEN function_scope body RBRACE
           async_gen_body : return_annotation ASYNC_GEN_OPEN function_scope body RBRACE"""
        self.function_depth -= 1
        p[0] = {"type": "BlockStatement", "body": p[4]}
        self.function_ends[id(p[0])] = p.lexpos(5)
        self.return_types[id(p[0])] = p[1]

    def p_typed_catch(self, p):
        "catch_clause : CATCH LPAREN annotated_binding RPAREN block"
        self.p_catch_clause(p)

    def p_initialized_catch(self, p):
        """catch_clause : CATCH LPAREN binding ASSIGN assignment RPAREN block
                        | CATCH LPAREN annotated_binding ASSIGN assignment RPAREN block"""
        p[0] = {"type": "CatchClause", "param": p[3], "initializer": p[5], "body": p[7]}
        if p.slice[3].type == "binding":
            p[0]["diagnostics"] = [{"code": 1197, "offset": p.slice[4].initializer_start,
                                    "message": "catch clause variable cannot have an initializer"}]

    def parameter_start(self, param, index, kind, offset):
        if kind == "ArrowFunctionExpression" and offset in self.cover_starts:
            return self.cover_starts[offset][index]
        return self.parameter_starts[id(param)]

    def check_implementation_parameters(self, params, kind, offset):
        for index, param in enumerate(params):
            binding = param["argument"] if param["type"] == "RestElement" else param
            if binding.get("optional") and binding["type"] in {"ArrayPattern", "ObjectPattern"}:
                param.setdefault("diagnostics", []).append({
                    "code": 2463, "offset": self.parameter_start(param, index, kind, offset),
                    "message": "optional binding pattern in implementation signature"})

    def function_node(self, kind, name, params, body, offset, **options):
        if body["type"] == "TSDeclareFunction":
            return {**body, "id": name, "params": params, "async": options.get("is_async", False),
                    "generator": options.get("generator", False)}
        self.check_implementation_parameters(params, kind, offset)
        node = super().function_node(kind, name, params, body, offset, **options)
        if (kind != "ArrowFunctionExpression" and self.diagnose_strict_parameters
                and any(param["type"] != "Identifier" for param in params)):
            self.check_parameter_directive(params, body, offset, kind)
        if id(body) in self.return_types:
            node["returnType"] = self.return_types.pop(id(body))
        return node

    @staticmethod
    def parameter_list_error(params):
        optional_seen = False
        for index, param in enumerate(params):
            if param["type"] == "RestElement":
                argument = param["argument"]
                if index != len(params) - 1:
                    return index, 1014
                if argument.get("left", argument).get("optional"):
                    return index, 1047
                if argument["type"] == "AssignmentPattern":
                    return index, 1048
            elif param.get("left", param).get("optional"):
                if param["type"] == "AssignmentPattern":
                    return index, 1015
                optional_seen = True
            elif optional_seen and param["type"] != "AssignmentPattern":
                return index, 1016
        return None

    def check_parameter_directive(self, params, body, offset, kind):
        for statement in body["body"]:
            expr = statement.get("expression", {})
            if (statement["type"] != "ExpressionStatement" or expr.get("type") != "Literal"
                    or not isinstance(expr.get("value"), str) or id(expr) in self.grouped_patterns):
                return
            if expr["value"] == "use strict":
                break
        else:
            return

        if self.parameter_list_error(params):
            return
        directive_start = self.directive_offsets[id(expr)]
        related = []
        for index, param in enumerate(params):
            if param["type"] == "Identifier":
                continue
            start = self.parameter_start(param, index, kind, offset)
            param.setdefault("diagnostics", []).append({
                "code": 1346, "offset": start, "message": "non-simple parameter with use strict directive",
                "relatedInformation": [{"code": 1349, "offset": directive_start, "message": "'use strict' directive used here."}]})
            code, message = (6204, "and here.") if related else (1348, "Non-simple parameter declared here.")
            related.append({"code": code, "offset": start, "message": message})
        statement.setdefault("diagnostics", []).append({
            "code": 1347, "offset": directive_start, "message": "use strict directive with non-simple parameter list",
            "relatedInformation": related})

    def p_ambient_scope(self, p):
        "ambient_scope :"
        self.ambient_depth += 1

    def p_ambient_item(self, p):
        """ambient_item : variable_declaration SEMICOLON
                        | lexical_declaration SEMICOLON
                        | ts_alias
                        | ts_interface
                        | ts_enum
                        | ts_namespace
                        | function_declaration
                        | class_declaration
                        | modified_decl
                        | ts_ambient
                        | import_decl
                        | export_decl"""
        p[0] = p[1]

    def p_modified_declaration(self, p):
        "modified_decl : DECL_MODIFIER ambient_item"
        p[0] = self.prepend_declaration_modifier(p[2], p[1], p.lexpos(1))

    @staticmethod
    def declaration_modifier_target(node):
        wrapped = node.get("declaration")
        if wrapped and (wrapped["type"].endswith("Declaration") or wrapped["type"] == "TSDeclareFunction"):
            return wrapped
        return node

    def prepend_declaration_modifier(self, node, word, offset):
        target = self.declaration_modifier_target(node)
        wrapped = target is not node
        modifiers = target.get("modifiers")
        if modifiers is None:
            modifiers = ["export"] if wrapped else []
            if wrapped and node["type"] == "ExportDefaultDeclaration":
                modifiers.append("default")
            modifiers.extend(m for m in ("declare", "abstract", "async", "const") if target.get(m))
        if word == "static" and "static" in modifiers:
            raise self.error(offset, "duplicate static declaration modifier")
        target["modifiers"] = [word, *modifiers]
        decorators = target.get("decorators", [])
        if len({d.get("modifierIndex", 0) for d in decorators}) > 1:
            raise self.error(offset, "separated decorator groups after modifier")
        for decorator in decorators:
            decorator["modifierIndex"] = decorator.get("modifierIndex", 0) + 1
        if word != "export":
            target[word] = True
        return node

    def p_ts_ambient(self, p):
        "ts_ambient : DECLARE ambient_scope ambient_item"
        self.ambient_depth -= 1
        p[0] = self.prepend_declaration_modifier(p[3], "declare", p.lexpos(1))
