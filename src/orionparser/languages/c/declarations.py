"""C declaration specifiers, declarators, initializers and external definitions."""


class DeclarationRules:
    def p_translation_unit(self, p):
        """translation_unit : external
                            | translation_unit external"""
        if len(p) == 2:
            p[0] = {"type": "TranslationUnit", "declarations": [p[1]]}
        else:
            p[1]["declarations"].append(p[2])
            p[0] = p[1]

    def p_external(self, p):
        """external : declaration
                    | first_head FUNCTION_OPEN items '}'
                    | old_head old_declarations FUNCTION_OPEN items '}'"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            for label, offset in self.goto_targets.items():
                if label not in self.labels:
                    raise self.error(offset, f"undefined label {label!r}")
            self.labels.clear()
            self.goto_targets.clear()
            decl = p[1]
            p[0] = {"type": "FunctionDefinition", "specifiers": decl["specifiers"],
                    "declarator": decl["declarators"][0]["declarator"],
                    "body": {"type": "CompoundStatement", "items": p[len(p)-2]}}
            if len(p) == 6:
                p[0]["parameterDeclarations"] = p[2]

    def p_old_head(self, p):
        "old_head : first_head"
        p[0] = p[1]
        constructor = self.definition_declarator(p[1], self.lookahead_offset)
        parameters = constructor["parameters"]
        if not parameters or parameters[0]["type"] != "Identifier":
            raise self.error(self.lookahead_offset, "parameter declaration list requires an identifier-list declarator")
        p.slice[0].scope = self.prototype_openings[id(constructor)].scope.copy()

    def storage_classes(self, specifiers):
        return [spec for spec in specifiers if isinstance(spec, str) and self.keywords.get(spec) in {"STORAGE", "STATIC"}]

    def check_parameter_storage(self, specifiers, offset):
        if self.storage_classes(specifiers) not in ([], ["register"]):
            raise self.error(offset, "invalid parameter storage class")

    def check_identifier_declarations(self, parameters, declarations, offset):
        pending = {param["name"] for param in parameters}
        for decl in declarations:
            if not decl.get("declarators"):
                raise self.error(offset, "expected a named parameter declaration")
            self.check_parameter_storage(decl["specifiers"], offset)
            for item in decl["declarators"]:
                self.allow_parameter_array(item["declarator"])
                name = self.declarator_name(item["declarator"])
                if name not in pending or item["initializer"] is not None:
                    raise self.error(offset, f"invalid declaration of parameter {name!r}")
                pending.remove(name)
        if pending:
            raise self.error(offset, "missing parameter declaration for " + ", ".join(sorted(pending)))

    def p_old_declarations(self, p):
        """old_declarations : declaration
                            | old_declarations declaration"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_specifiers(self, p):
        """specifiers : builtin_specs
                      | named_specs
           builtin_specs : type_specifier
                         | modifiers type_specifier
                         | builtin_specs type_specifier
                         | builtin_specs modifier
           named_specs : TYPEDEF_NAME
                       | modifiers TYPEDEF_NAME
                       | named_specs modifier
           modifiers : modifier
                     | modifiers modifier"""
        p.set_lexpos(0, p.lexpos(1))
        if p.slice[0].type == "specifiers":
            storage = self.storage_classes(p[1])
            if len(storage) > 1 and sorted(storage) not in (["_Thread_local", "extern"], ["_Thread_local", "static"]):
                raise self.error(p.lexpos(1), "incompatible storage-class specifiers")
            p[0] = p[1]
            return
        last = p.slice[-1]
        value = {"type": "TypedefName", "name": last.value} if last.type == "TYPEDEF_NAME" else last.value
        p[0] = [] if len(p) == 2 else p[1]
        p[0].append(value)

    def p_type_specifier(self, p):
        """type_specifier : TYPE
                          | aggregate
                          | enumeration
                          | atomic_type"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = p[1]

    def p_aggregate_keyword(self, p):
        """aggregate_keyword : STRUCT
                             | UNION"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = p[1]

    def p_aggregate(self, p):
        """aggregate : aggregate_keyword TAG_NAME
                     | aggregate_keyword '{' members '}'
                     | aggregate_keyword TAG_NAME '{' members '}'"""
        p.set_lexpos(0, p.lexpos(1))
        tagged = p.slice[2].type == "TAG_NAME"
        p[0] = {"type": "StructSpecifier" if p[1] == "struct" else "UnionSpecifier",
                "tag": p[2] if tagged else None, "members": p[len(p)-2] if len(p) > 3 else None}

    def p_members(self, p):
        """members : member_declaration
                   | members member_declaration"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_member_declaration(self, p):
        """member_declaration : specifiers member_list ';'
                              | specifiers ';'
                              | static_assertion"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            self.check_type_specifiers(p)
            if len(p) == 3 and not any(
                isinstance(spec, dict) and spec["type"] in {"StructSpecifier", "UnionSpecifier"} and spec["tag"] is None
                for spec in p[1]
            ):
                raise self.error(p.lexpos(2), "expected a member declarator")
            p[0] = {"type": "MemberDeclaration", "specifiers": p[1], "members": p[2] if len(p) == 4 else []}

    def p_field(self, p):
        """field : declarator
                 | declarator ':' conditional
                 | ':' conditional"""
        p[0] = {"type": "Field", "declarator": p[1] if p.slice[1].type == "declarator" else None,
                "width": p[len(p)-1] if len(p) > 2 else None}

    def p_enumeration(self, p):
        """enumeration : ENUM TAG_NAME
                       | ENUM '{' enumerators '}'
                       | ENUM '{' enumerators ',' '}'
                       | ENUM TAG_NAME '{' enumerators '}'
                       | ENUM TAG_NAME '{' enumerators ',' '}'"""
        p.set_lexpos(0, p.lexpos(1))
        tagged = p.slice[2].type == "TAG_NAME"
        p[0] = {"type": "EnumSpecifier", "tag": p[2] if tagged else None,
                "enumerators": p[4 if tagged else 3] if len(p) > 3 else None}
        if p.slice[-2].type == ",":
            p[0]["trailingComma"] = True

    def p_enumerator(self, p):
        """enumerator : ENUM_NAME
                      | ENUM_NAME '=' conditional"""
        name = {"type": "Identifier", "name": p[1]}
        self.declare(p.stack, name, False)
        p[0] = {"type": "Enumerator", "name": p[1], "value": p[3] if len(p) == 4 else None}

    def p_static_assertion(self, p):
        "static_assertion : _STATIC_ASSERT '(' conditional ',' string_literal ')' ';'"
        p[0] = {"type": "StaticAssertion", "test": p[3], "message": p[5]}

    def p_atomic_type(self, p):
        "atomic_type : _ATOMIC '(' type_name ')'"
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "AtomicType", "target": p[3]}

    def p_alignment(self, p):
        """alignment : _ALIGNAS '(' type_name ')'
                     | _ALIGNAS '(' conditional ')'"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "AlignmentSpecifier", "operand": p[3]}

    def p_modifier(self, p):
        """modifier : STORAGE
                    | QUALIFIER
                    | FUNCTION_SPEC
                    | STATIC
                    | alignment"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = p[1]

    @staticmethod
    def declarator_name(node):
        while node and node["type"] != "Identifier":
            node = node["declarator"]
        return node["name"] if node else None

    def plain_void(self, specifiers, stack):
        if len(specifiers) != 1:
            return False
        spec = specifiers[0]
        return spec == "void" or (isinstance(spec, dict) and spec["type"] == "TypedefName"
                                  and self.name_binding(spec["name"], stack) == "void")

    def declare(self, stack, declarator, binding):
        scope = next((sym.scope for sym in reversed(stack) if hasattr(sym, "scope")), self.file_scope)
        name = self.declarator_name(declarator)
        if name is not None:
            scope[name] = binding

    def p_declarator(self, p):
        """declarator : direct
                      | '*' qualifiers declarator"""
        p[0] = p[1] if len(p) == 2 else {"type": "PointerDeclarator", "qualifiers": p[2], "declarator": p[3]}

    def p_qualifiers(self, p):
        """qualifiers : empty
                      | qualifier_list"""
        p[0] = p[1] or []

    def p_qualifier_list(self, p):
        """qualifier_list : QUALIFIER
                          | qualifier_list QUALIFIER"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_array_suffix(self, p):
        """array_suffix : '[' qualifiers optional_assignment ']'
                        | '[' qualifiers '*' ']'
                        | '[' STATIC qualifiers assignment ']'
                        | '[' qualifier_list STATIC assignment ']'"""
        static = len(p) == 6
        star = p.slice[3].type == "*"
        quals = p[3] if p.slice[2].type == "STATIC" else p[2]
        p[0] = {"type": "ArrayDeclarator", "qualifiers": quals, "size": None if star else p[len(p)-2],
                "static": static, "star": star}

        if static or quals:
            self.parameter_arrays[id(p[0])] = p.lexpos(1)
        if star:
            p.set_lexpos(0, p.lexpos(3))
            opening = next((symbol for symbol in reversed(p.stack) if symbol.type == "PARAM_OPEN"), None)
            if opening is None:
                raise self.error(p.lexpos(3), "[*] requires function prototype scope")
            opening.star_offset = p.lexpos(3)

    def allow_parameter_array(self, node):
        while node and node["type"] != "Identifier":
            child = node["declarator"]
            if node["type"] == "ArrayDeclarator" and (child is None or child["type"] == "Identifier"):
                self.parameter_arrays.pop(id(node), None)
            node = child

    def p_direct(self, p):
        """direct : DECL_NAME
                  | '(' declarator ')'
                  | direct array_suffix
                  | direct PARAM_OPEN parameters_opt ')'
                  | direct PARAM_OPEN identifiers ')'"""
        if len(p) == 2:
            p[0] = {"type": "Identifier", "name": p[1]}
        elif len(p) == 3:
            p[0] = p[2]
            p[0]["declarator"] = p[1]
        elif p.slice[1].type == "(":
            p[0] = p[2]
        else:
            p[0] = {"type": "FunctionDeclarator", "declarator": p[1], "parameters": p[3]}
            self.prototype_openings[id(p[0])] = p.slice[2]
            if p.slice[3].type == "identifiers":
                self.identifier_lists[id(p[0])] = p.lexpos(2)

    def p_abstract_declarator(self, p):
        """abstract_declarator : abstract_direct
                               | '*' qualifiers
                               | '*' qualifiers abstract_declarator"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            p[0] = {"type": "PointerDeclarator", "qualifiers": p[2], "declarator": p[3] if len(p) == 4 else None}

    def p_abstract_direct(self, p):
        """abstract_direct : '(' abstract_declarator ')'
                           | array_suffix
                           | abstract_direct array_suffix
                           | PARAM_OPEN parameters_opt ')'
                           | abstract_direct PARAM_OPEN parameters_opt ')'"""
        if p.slice[1].type == "(":
            p[0] = p[2]
        elif p.slice[-1].type == "array_suffix":
            p[0] = p[len(p)-1]
            if p[0]["star"] and p[0]["qualifiers"]:
                raise self.error(p.lexpos(len(p)-1), "qualified [*] requires a named array declarator")
            p[0]["declarator"] = p[1] if len(p) == 3 else None
        else:
            p[0] = {"type": "FunctionDeclarator", "declarator": p[1] if len(p) == 5 else None, "parameters": p[len(p)-2]}

    def check_type_specifiers(self, p):
        for specifier in p[1]:
            if isinstance(specifier, str) and self.keywords.get(specifier) in {"STORAGE", "STATIC", "FUNCTION_SPEC"}:
                raise self.error(p.lexpos(1), "storage class or function specifier in type name or member")

    def p_type_name(self, p):
        """type_name : specifiers
                     | specifiers abstract_declarator"""
        self.check_type_specifiers(p)
        p[0] = {"type": "TypeName", "specifiers": p[1], "declarator": p[2] if len(p) == 3 else None}

    def p_identifiers(self, p):
        """identifiers : DECL_NAME
                       | identifiers ',' DECL_NAME"""
        name = {"type": "Identifier", "name": p[len(p)-1]}
        scope = next(sym.scope for sym in reversed(p.stack) if sym.type == "PARAM_OPEN")
        if name["name"] in scope:
            raise self.error(p.lexpos(len(p)-1), "duplicate identifier-list parameter")
        if self.is_typedef(name["name"], p.stack):
            raise self.error(p.lexpos(len(p)-1), "typedef name in identifier list")
        scope[name["name"]] = False
        if len(p) == 2:
            p[0] = [name]
        else:
            p[1].append(name)
            p[0] = p[1]

    def p_parameters_opt(self, p):
        """parameters_opt : empty
                          | parameters
                          | parameters ',' ELLIPSIS"""
        p[0] = p[1] or []
        if len(p) == 4:
            p[0].append({"type": "Ellipsis"})

    def p_list(self, p):
        """parameters : parameter
                      | parameters ',' parameter
           member_list : field
                       | member_list ',' field
           enumerators : enumerator
                       | enumerators ',' enumerator
           arguments : assignment
                     | arguments ',' assignment
           initializers : initializer_item
                        | initializers ',' initializer_item
           associations : association
                        | associations ',' association"""
        if p.slice[0].type == "associations":
            previous_default = len(p) == 4 and p.slice[1].has_default
            is_default = p[len(p)-1]["target"] is None
            if previous_default and is_default:
                raise self.error(p.lexpos(3), "duplicate default generic association")
            p.slice[0].has_default = previous_default or is_default
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_parameter(self, p):
        """parameter : specifiers
                     | specifiers declarator
                     | specifiers abstract_declarator"""
        self.check_parameter_storage(p[1], p.lexpos(1))
        declarator = p[2] if len(p) == 3 else None
        self.allow_parameter_array(declarator)
        if len(p) == 3 and p.slice[2].type == "declarator":
            self.declare(p.stack, declarator, False)
        p[0] = {"type": "Parameter", "specifiers": p[1], "declarator": declarator}
        if declarator is None and self.plain_void(p[1], p.stack):
            self.void_parameters.add(id(p[0]))

    def p_declaration(self, p):
        """declaration : declared_list ';'
                       | specifiers ';'
                       | static_assertion"""
        if p.slice[1].type != "specifiers":
            p[0] = p[1]
            return
        if not self.declares_tag_or_enumerators(p[1]):
            raise self.error(p.lexpos(2), "declaration requires a declarator, tag or enumerators")
        p[0] = {"type": "Declaration", "specifiers": p[1], "declarators": []}

    @staticmethod
    def declares_tag_or_enumerators(specifiers):
        pending = list(specifiers)
        while pending:
            item = pending.pop()
            if isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, dict):
                if item.get("tag") or item.get("enumerators"):
                    return True
                pending.extend(item.values())
        return False

    def p_declaration_head(self, p):
        """first_head : specifiers declarator
           next_head : declared_list ',' declarator"""
        decl = ({"type": "Declaration", "specifiers": p[1], "declarators": []}
                if len(p) == 3 else p[1])
        declarator = p[len(p)-1]
        binding = "typedef" in decl["specifiers"]
        if binding:
            if len(p) == 3:
                specs = [spec for spec in decl["specifiers"] if spec != "typedef"]
                if self.plain_void(specs, p.stack):
                    self.void_declarations.add(id(decl))
            if id(decl) in self.void_declarations and declarator["type"] == "Identifier":
                binding = "void"
        self.declare(p.stack, declarator, binding)
        decl["declarators"].append({"type": "InitDeclarator", "declarator": declarator, "initializer": None})
        p[0] = decl

    def p_declared_list(self, p):
        """declared_list : first_head
                         | first_head '=' initializer
                         | next_head
                         | next_head '=' initializer"""
        p[0] = p[1]
        if len(p) == 4:
            p[0]["declarators"][-1]["initializer"] = p[3]

    def p_initializer_item(self, p):
        """initializer_item : initializer
                            | designators '=' initializer"""
        p[0] = p[1] if len(p) == 2 else {"type": "DesignatedInitializer", "designators": p[1], "value": p[3]}

    def p_designators(self, p):
        """designators : designator
                       | designators designator"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_designator(self, p):
        """designator : '[' conditional ']'
                      | '.' MEMBER_NAME"""
        p[0] = {"type": "IndexDesignator", "index": p[2]} if len(p) == 4 else {"type": "FieldDesignator", "name": p[2]}

    def p_initializer(self, p):
        """initializer : assignment
                       | '{' initializers '}'
                       | '{' initializers ',' '}'"""
        p[0] = p[1] if len(p) == 2 else {"type": "InitializerList", "elements": p[2]}
