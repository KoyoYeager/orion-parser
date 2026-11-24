"""Class declarations, base classes and special member functions."""

from orionparser.languages.c_family import stack_prefix


class ClassRules:
    def p_class_decl(self, p):
        """class_decl : class_head ';'
                      | class_specifier ';'
                      | class_specifier trailing_variables ';'
                      | modifiers class_specifier trailing_variables ';'
                      | class_specifier modifiers trailing_variables ';'
                      | modifiers class_specifier modifiers trailing_variables ';'"""
        if p.slice[1].type == "class_head":
            if p[1]["name"] is None:
                raise self.source.error(p.lexpos(2), "unnamed class requires a definition")
            if p[1]["final"] or p[1]["bases"]:
                raise self.source.error(p.lexpos(2), "expected class body after final or base clause")
            p[0] = {**p[1], "members": None}
        else:
            prefix = p[1] if p.slice[1].type == "modifiers" else []
            suffix = p[len(p)-3] if p.slice[-3].type == "modifiers" else []
            p[0] = p[2] if prefix else p[1]
            if prefix or suffix:
                allowed = ("const", "volatile", "constexpr", "constinit", "inline", "static", "extern", "thread_local", "mutable")
                if any(spec not in allowed for spec in prefix + suffix):
                    raise self.source.error(p.lexpos(1), "invalid specifier on class object declaration")
                p[0]["declarationSpecifiers"] = prefix + suffix
                if suffix:
                    p[0]["postClassSpecifiers"] = suffix
        if p.slice[-2].type == "trailing_variables":
            p[0]["declarators"] = p[len(p)-2]
        elif p[0]["name"] is None and p[0]["key"] == "union":
            for member in p[0]["members"]:
                fields = member["declarations"] if member["type"] == "DeclarationGroup" else [member]
                for field in fields:
                    if field["type"] == "VariableDeclaration" and field["name"] is not None:
                        self.bind(p.stack, field["name"], self.object_binding(p.stack, field["variableType"]))

    def p_record_typedef(self, p):
        """class_decl : TYPEDEF class_specifier record_aliases ';'
                      | TYPEDEF modifiers class_specifier record_aliases ';'
                      | TYPEDEF class_specifier modifiers record_aliases ';'
                      | TYPEDEF modifiers class_specifier modifiers record_aliases ';'"""
        index = 3 if p.slice[2].type == "modifiers" else 2
        qualifiers = p[2] if index == 3 else []
        if p.slice[index+1].type == "modifiers":
            qualifiers = qualifiers + p[index+1]
        if any(q not in ("const", "volatile") for q in qualifiers):
            raise self.source.error(p.lexpos(1), "expected cv qualifiers on a typedef record definition")
        p[0] = {**p[index], "typedefs": p[len(p)-2]}
        if qualifiers:
            p[0]["declarationSpecifiers"] = qualifiers

    def p_record_aliases(self, p):
        """record_aliases : record_alias
                          | record_aliases ',' record_alias"""
        p[0] = [p[1]] if len(p) == 2 else [*p[1], p[3]]

    def p_record_alias(self, p):
        "record_alias : nested_named"
        name, operators = p[1]
        source = next(sym for sym in reversed(p.stack) if sym.type == "class_specifier")
        if any(op["type"] == "FunctionOperator" for op in operators):
            raise self.source.error(p.lexpos(1), "class definition in a function result type")
        self.bind_record_typedef(p.stack, name, source.record_scope, operators)
        p[0] = {"type": "TypedefDeclarator", "name": name, "declarator": operators}

    def p_gnu_record_alias_attribute(self, p):
        "record_alias : record_alias gnu_attribute"
        p[0] = {**p[1], "gnuAttributes": [*p[1].get("gnuAttributes", []), p[2]]}

    def p_gnu_class_attribute(self, p):
        "class_specifier : class_specifier gnu_attribute"
        p.slice[0].record_scope = p.slice[1].record_scope
        p[0] = {**p[1], "gnuAttributes": [*p[1].get("gnuAttributes", []), p[2]]}

    def p_unnamed_class_head(self, p):
        """unnamed_class_head : STRUCT
                              | CLASS
                              | UNION
                              | STRUCT attribute_sequence
                              | CLASS attribute_sequence
                              | UNION attribute_sequence
                              | STRUCT gnu_attribute
                              | CLASS gnu_attribute
                              | UNION gnu_attribute"""
        p.slice[0].namespace = (*self.namespace(p.stack), f"<unnamed class at {p.lexpos(1)}>")
        p[0] = {"type": "ClassDeclaration", "key": p[1], "name": None}
        if len(p) == 3:
            if p.slice[2].type == "gnu_attribute":
                p[0]["gnuAttributes"] = [p[2]]
            else:
                p[0]["attributes"] = p[2]

    def p_class_specifier(self, p):
        "class_specifier : class_head '{' members '}'"
        self.finish_member_bodies(p.slice[1].pending_bodies)
        p.slice[0].record_scope = p.slice[1].namespace
        self.class_scopes.add(p.slice[1].namespace)
        p[0] = {**p[1], "members": p[3]}

    def p_trailing_variables(self, p):
        """trailing_variables : trailing_variable
                              | trailing_variables ',' trailing_variable"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_record_object_head(self, p):
        "record_object_head : nested_named"
        name, operators = p[1]
        source = next(sym for sym in reversed(p.stack) if sym.type == "class_specifier")
        if any(op["type"] == "FunctionOperator" for op in operators):
            raise self.source.error(p.lexpos(1), "class definition in a function result type")
        arrays = []
        for op in operators:
            if op["type"] != "ArrayOperator":
                break
            arrays.append(op)
        p[0] = {"type": "InitDeclarator", "name": name, "dimensions": [op["size"] for op in arrays]}
        if rest := operators[len(arrays):]:
            p[0]["declarator"] = rest
        self.attach_dimension_attributes(p[0], arrays)
        if attrs := getattr(p.slice[1], "id_attributes", None):
            p[0]["declaratorAttributes"] = attrs
        layers = self.receiver_layers(p.stack, operators)
        kind = ("object", source.record_scope, layers) if layers is not None else "value"
        self.bind(p.stack, name, kind)

    def p_trailing_variable(self, p):
        "trailing_variable : record_object_head init_clause"
        form, value = p[2]
        if form in {"default", "delete"}:
            raise self.source.error(p.lexpos(2), "expected function declarator")
        self.bind_initialized_array(p.stack, p[1], value)
        p[0] = {**p[1], "initializer": value}

    def p_class_name_head(self, p):
        """class_name_head : STRUCT qualified_name
                           | CLASS qualified_name
                           | UNION qualified_name
                           | STRUCT attribute_sequence qualified_name
                           | CLASS attribute_sequence qualified_name
                           | UNION attribute_sequence qualified_name
                           | CLASS gnu_attribute qualified_name
                           | STRUCT gnu_attribute qualified_name
                           | UNION gnu_attribute qualified_name"""
        name = p[len(p)-1]
        if "::" in name:
            scope = self.namespace_path(p.stack, name)
            if scope not in self.class_scopes:
                raise self.source.error(p.lexpos(len(p)-1), "qualified class definition requires a previous declaration")
        else:
            scope = (*self.namespace(p.stack), name)
        template = len(p.stack) >= 5 and p.stack[-1].type == "requires_opt" and p.stack[-5].type == "TEMPLATE"
        self.bind(p.stack, name, "type_template" if template else "type", class_target=scope)
        self.class_scopes.add(scope)
        if template:
            self.register_template_parameters(p.stack, scope, p.stack[-3].value)
        p.slice[0].namespace = scope
        p[0] = {"type": "ClassDeclaration", "key": p[1], "name": name}
        if len(p) == 4:
            if p.slice[2].type == "gnu_attribute":
                p[0]["gnuAttributes"] = [p[2]]
            else:
                p[0]["attributes"] = p[2]

    def p_template_member_class_head(self, p):
        """class_name_head : CLASS template_owner IDENT
                           | STRUCT template_owner IDENT
                           | UNION template_owner IDENT"""
        scope = (*p.slice[2].namespace, p[3])
        if scope not in self.class_scopes:
            raise self.source.error(p.lexpos(3), "unknown member class of class template")
        p.slice[0].namespace = scope
        p[0] = {"type": "ClassDeclaration", "key": p[1], "name": p[2]["name"] + "::" + p[3], "owner": p[2]}

    def p_specialized_class_name(self, p):
        "specialized_class_name : qualified_name ANGLE_OPEN template_arguments_opt ANGLE_CLOSE"
        name = p[1]
        binding = self.lookup(p.stack, name.removeprefix("::").split("::"), name.startswith("::"))
        if binding != "type_template" or self.namespace_path(p.stack, name) not in self.class_scopes:
            raise self.source.error(p.lexpos(1), "expected a previously declared class template")
        p[0] = {"type": "TypeName", "name": name, "arguments": p[3],
                "spelling": self.source.spelling(p.lexpos(1), p.slice[4].endlexpos)}

    def p_specialized_class_head(self, p):
        """class_name_head : STRUCT specialized_class_name
                           | CLASS specialized_class_name
                           | UNION specialized_class_name
                           | STRUCT attribute_sequence specialized_class_name
                           | CLASS attribute_sequence specialized_class_name
                           | UNION attribute_sequence specialized_class_name"""
        if p.stack[-1].type not in {"explicit_header", "requires_opt"}:
            raise self.source.error(p.lexpos(1), "specialized class declaration requires a template header")
        target = p[len(p)-1]
        scope = self.specialization_scope(p.stack, target, register=True)
        self.class_scopes.add(scope)
        p.slice[0].namespace = scope
        p[0] = {"type": "ClassDeclaration", "key": p[1], "name": target["name"], "specialization": target}
        if len(p) == 4:
            p[0]["attributes"] = p[2]

    def p_members(self, p):
        """members : empty
                   | members member"""
        if len(p) == 2:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_bit_field_initializer(self, p):
        """bit_field_initializer : empty
                                 | '=' initializer
                                 | braces"""
        p[0] = p[2] if len(p) == 3 else p[1]

    def p_bit_field(self, p):
        """init_declarators : declared_head ':' conditional bit_field_initializer
                            | following_head ':' conditional bit_field_initializer
                            | type ':' conditional bit_field_initializer
                            | enum_type ':' conditional bit_field_initializer
                            | init_declarators ',' ':' conditional bit_field_initializer"""
        if p.stack[-1].type != "members":
            raise self.source.error(p.lexpos(len(p)-3), "bit-field requires class member scope")
        if p.slice[1].type in {"declared_head", "following_head"}:
            node, specs = p[1], p.slice[1].specifiers
            declarations = getattr(p.slice[1], "previous_declarations", [])
            if node["type"] != "VariableDeclaration" or node["dimensions"] or node["variableType"]["indirections"]:
                raise self.source.error(p.lexpos(2), "expected a bit-field identifier")
        else:
            if p.slice[1].type in {"type", "enum_type"}:
                specs, declarations = p[1]["specifiers"], []
                if p[1]["indirections"]:
                    raise self.source.error(p.lexpos(2), "unexpected pointer on unnamed bit-field")
            else:
                specs, declarations = p[1]
            node = {"type": "VariableDeclaration", "name": None, "dimensions": [],
                    "variableType": {"type": "Type", "specifiers": specs, "indirections": []}}
            if p[len(p)-1] is not None:
                raise self.source.error(p.lexpos(len(p)-1), "unnamed bit-field cannot have an initializer")
        node["bitWidth"], node["initializer"] = p[len(p)-2], p[len(p)-1]
        declarations.append(node)
        p[0] = specs, declarations

    def p_friend_key(self, p):
        """friend_key : FRIEND_KEY CLASS
                      | FRIEND_KEY STRUCT
                      | FRIEND_KEY UNION"""
        p[0] = p[2]

    def p_friend_type(self, p):
        """friend_type : friend_key qualified_name ';'
                  | friend_key qualified_name ANGLE_OPEN template_arguments_opt ANGLE_CLOSE ';'"""
        name = p[2]
        target = {"type": "TypeName", "name": name}
        if len(p) == 7:
            if self.lookup(p.stack, name.removeprefix("::").split("::"), name.startswith("::")) != "type_template":
                raise self.source.error(p.lexpos(2), "expected a class template in friend declaration")
            target["arguments"] = p[4]
        elif "::" in name:
            parts = name.removeprefix("::").split("::")
            dependent = not name.startswith("::") and any(parts[0] in getattr(sym, "template_types", ()) for sym in p.stack)
            binding = self.lookup(p.stack, parts, name.startswith("::"))
            template_friend = p.stack[-1].type == "requires_opt" and binding == "type_template"
            if not dependent and binding != "type" and not template_friend:
                raise self.source.error(p.lexpos(2), "unknown qualified friend type")
        # A first declaration of a friend class does not introduce a name for ordinary lookup.
        p[0] = {"type": "FriendTypeDeclaration", "key": p[1], "target": target}

    def p_friend_member_template(self, p):
        "friend_type : friend_key qualified_name SCOPE TEMPLATE IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE ';'"
        owner = p[2]
        if not self.has_dependent_qualifier(p.stack, owner):
            scope = self.namespace_path(p.stack, owner)
            if self.member_binding(scope, p[5]) != "type_template":
                raise self.source.error(p.lexpos(5), "expected a class template in friend declaration")
        target = {"type": "QualifiedType", "qualifier": {"type": "TypeName", "name": owner},
                  "template": True, "name": p[5], "arguments": p[7]}
        p[0] = {"type": "FriendTypeDeclaration", "key": p[1], "target": target}

    def p_friend_specialized_owner(self, p):
        """friend_type : friend_key template_owner TEMPLATE IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE ';'
                       | friend_key template_owner IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE ';'"""
        explicit = p.slice[3].type == "TEMPLATE"
        index = 4 if explicit else 3
        if not explicit and self.member_binding(p.slice[2].namespace, p[index]) != "type_template":
            raise self.source.error(p.lexpos(index), "expected a member class template in friend declaration")
        target = {"type": "QualifiedType", "qualifier": p[2], "name": p[index], "arguments": p[index+2]}
        if explicit:
            target["template"] = True
        p[0] = {"type": "FriendTypeDeclaration", "key": p[1], "target": target}

    def p_friend_simple_type(self, p):
        "friend_type : specs ';'"
        specs = p[1]
        if specs.count("friend") != 1:
            raise self.source.error(p.lexpos(2), "expected a member declarator")
        target = {"type": "Type", "specifiers": [s for s in specs if s != "friend"], "indirections": []}
        self.require_type_specifiers(target, p.lexpos(1), "friend declaration")
        if any(s in ("const", "volatile") for s in specs):
            raise self.source.error(p.lexpos(1), "cv qualifier is invalid in a friend declaration")
        p[0] = {"type": "FriendTypeDeclaration", "key": None, "target": target}

    def p_friend_member(self, p):
        """member : friend_type
                  | TEMPLATE ANGLE_OPEN template_parameters ANGLE_CLOSE requires_opt friend_type"""
        if len(p) == 2:
            p[0] = p[1]
            return
        if p[6]["key"] is None:
            raise self.source.error(p.lexpos(6), "expected a class template friend")
        p[0] = {"type": "TemplateDeclaration", "parameters": p[3], "declaration": p[6]}
        if p[5] is not None:
            p[0]["requires"] = p[5]

    def p_member(self, p):
        """member : typed_declaration
                  | PUBLIC ':'
                  | PROTECTED ':'
                  | PRIVATE ':'
                  | ';'"""
        if len(p) == 3:
            p[0] = {"type": "AccessSpecifier", "access": p[1]}
        else:
            p[0] = {"type": "EmptyDeclaration"} if p[1] == ";" else p[1]

    def p_class_head(self, p):
        """class_head : class_name_head final_opt base_clause
                      | unnamed_class_head base_clause"""
        scope = p.slice[1].namespace
        p.slice[0].namespace = scope
        p.slice[0].class_name = p[1]["name"].rsplit("::", 1)[-1] if p[1]["name"] else None
        if p.slice[0].class_name:
            # The injected class name is visible during member lookup through a base.
            simple = p.slice[0].class_name
            kind = self.bindings.get((*scope[:-1], simple), "type")
            self.bindings[(*scope, simple)] = "type_template" if kind == "type_template" else "type"
        p.slice[0].pending_bodies = []
        bases = p[len(p)-1]
        p[0] = {**p[1], "final": len(p) == 4 and p[2], "bases": bases}
        if bases:
            if p[1]["key"] == "union":
                raise self.source.error(p.lexpos(len(p)-1), "a union cannot have base classes")
            self.base_scopes[scope] = [base_scope for base in bases if (base_scope := self.base_scope(p.stack, base["target"]))]

    def p_final_opt(self, p):
        """final_opt : empty
                     | FINAL"""
        p[0] = p[1] == "final"

    def p_base_clause(self, p):
        """base_clause : empty
                       | ':' base_classes"""
        p[0] = [] if len(p) == 2 else p[2]

    def p_base_classes(self, p):
        """base_classes : base_entry
                        | base_classes ',' base_entry"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_base_entry(self, p):
        """base_entry : base_class
                      | base_class ELLIPSIS"""
        p[0] = p[1] if len(p) == 2 else {**p[1], "pack": True}

    def p_base_class(self, p):
        """base_class : base_type
                      | access base_type
                      | VIRTUAL base_type
                      | VIRTUAL access base_type
                      | access VIRTUAL base_type"""
        mods = p[1:len(p)-1]
        p[0] = {"type": "BaseSpecifier", "target": p[len(p)-1], "virtual": "virtual" in mods,
                "access": next((m for m in mods if m != "virtual"), None)}

    def p_base_type(self, p):
        """base_type : named_type
                     | decltype_spec
                     | qualified_name %prec END_NAME
                     | qualified_name SCOPE TEMPLATE IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE
                     | base_type SCOPE IDENT
                     | base_type SCOPE TEMPLATE IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE"""
        if p.slice[1].type == "qualified_name":
            absolute = p[1].startswith("::")
            parts = p[1].removeprefix("::").split("::")
            dependent = not absolute and any(parts[0] in getattr(sym, "template_types", ())
                                             for sym in [*self.inherited_stack, *p.stack])
            if not dependent and self.lookup(p.stack, parts, absolute) != "type":
                raise self.source.error(p.lexpos(1), "expected a class name in base specifier")
            target = {"type": "TypeName", "name": ("::" if absolute else "") + parts[0]}
            for part in parts[1:]:
                target = {"type": "QualifiedType", "qualifier": target, "name": part}
        else:
            target = p[1]
        if len(p) == 2:
            p[0] = target
        else:
            p[0] = {"type": "QualifiedType", "qualifier": target, "name": p[3] if len(p) == 4 else p[4]}
            if len(p) == 8:
                p[0].update(template=True, arguments=p[6])

    def base_scope(self, stack, target):
        if target["type"] == "Decltype":
            return None
        if target["type"] == "QualifiedType":
            parent = self.base_scope(stack, target["qualifier"])
            return (*parent, target["name"]) if parent else None
        if "arguments" in target:
            return self.specialization_scope(stack, target)
        return self.namespace_path(stack, target["name"])

    def p_access(self, p):
        """access : PUBLIC
                  | PROTECTED
                  | PRIVATE"""
        p[0] = p[1]

    def p_virt_specifiers(self, p):
        """virt_specifiers : empty
                           | virt_specifiers OVERRIDE
                           | virt_specifiers FINAL"""
        if len(p) == 2:
            p[0] = []
        else:
            if p[2] in p[1]:
                raise self.source.error(p.lexpos(2), "duplicate virtual specifier")
            p[1].append(p[2])
            p[0] = p[1]

    def special_name(self, token, peek, parser):
        absolute = token.type == "SCOPE"
        current = peek(0) if absolute else token
        i = 1 if absolute else 0
        qualifiers = []
        while current and current.type == "IDENT" and peek(i) and peek(i).type == "SCOPE":
            qualifiers.append(current.value)
            current = peek(i+1)
            i += 2
        destructor = current is not None and current.type == "~"
        if destructor:
            current = peek(i)
            i += 1
        if current is None or current.type != "IDENT" or not peek(i) or peek(i).type != "(":
            return None
        kind = "DTOR_NAME" if destructor else "CTOR_NAME"
        prefix = stack_prefix(parser, kind)
        if prefix is None:
            return None
        scope = parser.symstack[:prefix]
        if qualifiers:
            path = self.namespace_path(scope, ("::" if absolute else "") + "::".join(qualifiers))
            if path not in self.class_scopes or current.value != path[-1]:
                return None
        elif absolute or current.value != next((s.class_name for s in reversed(scope) if hasattr(s, "class_name")), None):
            return None
        name = "::".join([*qualifiers, ("~" if destructor else "") + current.value])
        return kind, ("::" if absolute else "") + name, i

    def p_special_head(self, p):
        """special_head : special_id PARAM_OPEN parameters_opt ')' noexcept_opt function_type_attributes requires_opt virt_specifiers
                        | modifiers special_id PARAM_OPEN parameters_opt ')' noexcept_opt function_type_attributes requires_opt virt_specifiers"""
        start = 2 if p.slice[1].type == "modifiers" else 1
        name, destructor = p[start]
        parameters = p[start+2]
        void_parameter = (len(parameters) == 1 and parameters[0] == {
            "type": "Parameter", "name": None, "default": None,
            "parameterType": {"type": "Type", "specifiers": ["void"], "indirections": []}})
        if destructor and parameters and not void_parameter:
            raise self.source.error(p.lexpos(start+1), "destructor cannot take parameters")
        node = {"type": "DestructorDeclaration" if destructor else "ConstructorDeclaration",
                "name": name, "specifiers": p[1] if start == 2 else [], "parameters": parameters,
                "noexcept": p[start+4], "virtSpecifiers": p[start+7]}
        if (not destructor and "::" not in name and "explicit" not in node["specifiers"]
                and parameters and parameters[0].get("parameterType") and p[start+6] is None
                and all(arg.get("default") is not None for arg in parameters[1:])):
            source = self.type_argument_identity(p.stack, parameters[0]["parameterType"])
            if source is not None:
                self.converting_constructors.setdefault(self.namespace(p.stack), set()).add(source)
        if p[start+5]:
            node["functionTypeAttributes"] = p[start+5]
        if p[start+6] is not None:
            node["requires"] = p[start+6]
        if not destructor and node["virtSpecifiers"]:
            raise self.source.error(p.lexpos(start+7), "constructor cannot have virtual specifiers")
        if hasattr(p.slice[start], "owner"):
            node["owner"] = p.slice[start].owner
            p.slice[0].namespace = p.slice[start].namespace
        elif "::" in name:
            p.slice[0].namespace = self.namespace_path(p.stack, name.rsplit("::", 1)[0])
        p.slice[0].locals = p.slice[start+1].locals
        p[0] = node

    def p_special_id(self, p):
        """special_id : CTOR_NAME
                      | DTOR_NAME"""
        p[0] = (p[1], p.slice[1].type == "DTOR_NAME")
        if "::" in p[1]:
            p.slice[0].namespace = self.namespace_path(p.stack, p[1].rsplit("::", 1)[0])

    def p_nested_constructor_owner(self, p):
        "ctor_template_owner : ctor_template_owner IDENT SCOPE"
        scope = (*p.slice[1].namespace, p[2])
        if scope not in self.class_scopes:
            raise self.source.error(p.lexpos(2), "unknown nested constructor owner")
        p[0] = {"type": "QualifiedType", "qualifier": p[1], "name": p[2],
                "spelling": self.source.spelling(p.lexpos(1), p.slice[2].endlexpos)}
        p.slice[0].namespace = scope
        p.slice[0].owner_name = getattr(p.slice[1], "owner_name", p[1]["name"]) + "::" + p[2]

    def p_template_special_id(self, p):
        """special_id : ctor_template_owner IDENT
                      | ctor_template_owner '~' IDENT"""
        owner, name = p[1], p[len(p)-1]
        if name != owner["name"].rsplit("::", 1)[-1]:
            raise self.source.error(p.lexpos(len(p)-1), "expected the constructor or destructor name")
        destructor = len(p) == 4
        owner_name = getattr(p.slice[1], "owner_name", owner["name"])
        p[0] = (owner_name + "::" + ("~" if destructor else "") + name, destructor)
        p.slice[0].owner = owner
        p.slice[0].namespace = p.slice[1].namespace

    def p_special_function(self, p):
        """special_function : special_head ';'
                            | special_head '=' DEFAULT ';'
                            | special_head '=' DELETE ';'
                            | special_head '=' NUMBER ';'
                            | special_head block
                            | special_head try_block
                            | special_head TRY ':' member_initializers block handlers
                            | special_head ':' member_initializers block"""
        p[0] = {**p[1], "body": None, "initializers": []}
        if p.slice[2].type == "=":
            spec = p[3]
            if p.slice[3].type == "NUMBER":
                if spec != "0" or p[1]["type"] not in {"DestructorDeclaration", "ConversionFunctionDeclaration"}:
                    raise self.source.error(p.lexpos(3), "invalid pure specifier")
                spec = "pure"
            p[0]["functionSpecifier"] = spec
        elif p.slice[2].type in {":", "TRY"}:
            if p[1]["type"] != "ConstructorDeclaration":
                raise self.source.error(p.lexpos(2), "member initializers require a constructor")
            if p.slice[2].type == "TRY":
                p[0]["initializers"] = p[4]
                p[0]["body"] = {"type": "TryBlock", "body": p[5], "handlers": p[6]}
            else:
                p[0]["initializers"], p[0]["body"] = p[3], p[4]
        elif p.slice[2].type in {"block", "try_block"}:
            p[0]["body"] = p[2]

    def p_member_initializers(self, p):
        """member_initializers : member_initializer
                               | member_initializers ',' member_initializer"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_member_initializer(self, p):
        """member_initializer : qualified_name ctor_arguments
                              | named_type ctor_arguments"""
        p[0] = {"type": "MemberInitializer", "target": p[1], "initializer": p[2]}

    def p_ctor_arguments(self, p):
        """ctor_arguments : '(' arguments_opt ')'
                          | braces"""
        p[0] = p[1] if len(p) == 2 else {"type": "Arguments", "values": p[2]}
