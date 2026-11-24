"""Enum and annotation interface declarations."""


class DeclarationRules:
    def p_enum_base(self, p):
        "enum_base : ENUM IDENT interfaces '{' enum_body '}'"
        p[0] = {"type": "EnumDeclaration", "name": p[2], "typeParameters": [], "extends": [],
                "implements": p[3], "modifiers": [], "constants": p[5][0], "members": p[5][1]}
        self.check_type_body(p[0], p.lexpos(2))

    def p_enum_body(self, p):
        """enum_body : enum_members
                     | ',' enum_members
                     | enum_constants enum_members
                     | enum_constants ',' enum_members"""
        constants = p[1] if p.slice[1].type == "enum_constants" else []
        p[0] = (constants, p[len(p)-1])

    def p_enum_members(self, p):
        """enum_members : empty
                        | ';' members"""
        p[0] = [] if len(p) == 2 else p[2]

    def p_enum_constants(self, p):
        """enum_constants : enum_constant
                          | enum_constants ',' enum_constant"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_enum_constant(self, p):
        "enum_constant : annotations IDENT enum_arguments enum_constant_body"
        p[0] = {"type": "EnumConstant", "name": p[2], "annotations": p[1], "arguments": p[3], "body": p[4]}

    def p_enum_arguments(self, p):
        """enum_arguments : empty
                          | '(' arguments_opt ')'"""
        p[0] = None if len(p) == 2 else p[2]

    def p_enum_constant_body(self, p):
        """enum_constant_body : empty
                              | '{' members '}'"""
        p[0] = None if len(p) == 2 else p[2]

    def p_annotations(self, p):
        """annotations : empty
                       | annotations annotation"""
        if len(p) == 2:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_annotation_declaration(self, p):
        "annotation_base : '@' INTERFACE IDENT '{' annotation_members '}'"
        p[0] = {"type": "AnnotationInterfaceDeclaration", "name": p[3], "modifiers": [], "typeParameters": [],
                "extends": [], "implements": [], "members": p[5]}
        self.check_type_body(p[0], p.lexpos(3))

    def p_annotation_members(self, p):
        """annotation_members : empty
                              | annotation_members annotation_member"""
        if len(p) == 2:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_annotation_member(self, p):
        """annotation_member : prefix type IDENT '(' ')' dims default_opt ';'
                             | prefix type variables ';'
                             | type_declaration
                             | ';'"""
        if len(p) == 2:
            p[0] = p[1] if p.slice[1].type == "type_declaration" else {"type": "EmptyDeclaration"}
        elif len(p) == 5:
            self.check_named_type(p[2]["name"], p.lexpos(2))
            p[0] = {"type": "FieldDeclaration", "modifiers": p[1], "fieldType": p[2], "variables": p[3]}
        else:
            self.check_named_type(p[2]["name"], p.lexpos(2))
            if any(isinstance(m, str) and m not in {"public", "abstract"} for m in p[1]):
                raise self.source.error(p.lexpos(1), "invalid annotation element modifier")
            p[0] = {"type": "AnnotationElement", "modifiers": p[1], "elementType": p[2],
                    "name": p[3], "dimensions": p[6], "default": p[7]}
            self.attach_dimension_annotations(p[0], p.slice[6])

    def p_default_opt(self, p):
        """default_opt : empty
                       | DEFAULT annotation_value"""
        p[0] = None if len(p) == 2 else p[2]
