"""C++20 attribute specifiers and balanced token arguments."""


import re


_NO_ARGUMENT = {"carries_dependency", "fallthrough", "likely", "maybe_unused", "no_unique_address", "noreturn", "unlikely"}
_STANDARD_ATTRIBUTES = _NO_ARGUMENT | {"deprecated", "nodiscard"}


class AttributeRules:
    def check_type_attributes(self, specifiers, target):
        for spec in specifiers:
            if spec["type"] == "AlignmentSpecifier":
                raise self.source.error(spec["startOffset"], f"alignas cannot apply to {target}")
            if not spec["usingNamespace"]:
                for item in spec["items"]:
                    if item and not item["namespace"] and item["name"] in _STANDARD_ATTRIBUTES:
                        raise self.source.error(item["startOffset"], f"{item['name']} cannot apply to {target}")

    def p_attributed(self, p):
        """typed_declaration : attribute_specifier typed_declaration
           statement : attribute_specifier statement
           parameter : attribute_specifier parameter"""
        node = p[2]
        p[0] = {**node, "attributes": [p[1], *node.get("attributes", [])]}

    def p_gnu_attributed_declaration(self, p):
        "typed_declaration : gnu_attribute typed_declaration"
        p[0] = {**p[2], "gnuAttributes": [p[1], *p[2].get("gnuAttributes", [])]}

    def p_gnu_declarator_attribute(self, p):
        """declared_head : declared_head gnu_attribute
                         | declared_head GNU_ASM '(' string_literal ')'
           special_head : special_head gnu_attribute"""
        if len(p) == 3:
            p[0] = {**p[1], "gnuAttributes": [*p[1].get("gnuAttributes", []), p[2]]}
        else:
            if "asmLabel" in p[1] or any(not part.endswith('"') for part in p[4]):
                raise self.source.error(p.lexpos(2), "invalid asm label")
            p[0] = {**p[1], "asmLabel": {"spelling": p[2], "parts": p[4]}}
        for key in ("locals", "namespace", "specifiers", "previous_declarations"):
            if hasattr(p.slice[1], key):
                setattr(p.slice[0], key, getattr(p.slice[1], key))

    def p_attribute_declaration(self, p):
        "typed_declaration : attribute_specifier ';'"
        p[0] = {"type": "AttributeDeclaration", "attributes": [p[1]]}

    def p_gnu_attribute(self, p):
        "gnu_attribute : GNU_ATTRIBUTE '(' '(' gnu_attribute_list ')' ')'"
        p[0] = {"type": "GnuAttributeSpecifier", "spelling": p[1], "items": p[4],
                "startOffset": p.lexpos(1), "endOffset": p.slice[-1].endlexpos}

    def p_gnu_attribute_list(self, p):
        """gnu_attribute_list : attribute
                              | gnu_attribute_list ',' attribute"""
        p[0] = [p[1]] if len(p) == 2 else [*p[1], p[3]]

    def p_attribute_sequence(self, p):
        """attribute_sequence : attribute_specifier
                              | attribute_sequence attribute_specifier"""
        p[0] = [p[1]] if len(p) == 2 else [*p[1], p[2]]

    def p_attribute_specifier(self, p):
        """attribute_specifier : ATTR_OPEN attribute_list ATTR_CLOSE
                               | ATTR_OPEN USING ATTR_NAME ':' attribute_list ATTR_CLOSE"""
        namespace = p[3] if len(p) == 7 else None
        items = p[len(p)-2]
        if namespace and any(item.get("namespace") for item in items if item):
            raise self.source.error(p.lexpos(3), "scoped attribute with a using-prefix")
        for item in items:
            if item is None or namespace or item["namespace"] or item["arguments"] is None:
                continue
            name, args = item["name"], item["arguments"]
            if name in _NO_ARGUMENT:
                raise self.source.error(item["startOffset"], f"{name} does not take an argument clause")
            if name in {"nodiscard", "deprecated"} and (not args or not all(
                isinstance(token, str) and re.match(r'(?:u8|u|U|L)?R?"', token) and token.endswith('"') for token in args
            )):
                raise self.source.error(item["startOffset"], f"{name} requires a string literal in its argument clause")
        p[0] = {"type": "AttributeSpecifier", "usingNamespace": namespace, "items": items,
                "startOffset": p.lexpos(1), "endOffset": p.slice[-1].endlexpos}

    def p_attribute_list(self, p):
        """attribute_list : attribute_slot
                          | attribute_list ',' attribute_slot"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_attribute_slot(self, p):
        """attribute_slot : empty
                          | attribute
                          | attribute ELLIPSIS"""
        p[0] = {**p[1], "pack": True} if len(p) == 3 else p[1]

    def p_attribute_name(self, p):
        """attribute_name : ATTR_NAME
                          | ATTR_NAME SCOPE ATTR_NAME"""
        p[0] = {"name": p[len(p)-1], "namespace": p[1] if len(p) == 4 else None}

    def p_attribute(self, p):
        """attribute : attribute_name
                     | attribute_name '(' balanced_opt ')'"""
        p[0] = {**p[1], "arguments": p[3] if len(p) == 5 else None,
                "startOffset": p.lexpos(1), "endOffset": p.slice[-1].endlexpos}

    def p_balanced_opt(self, p):
        """balanced_opt : empty
                        | balanced_tokens"""
        p[0] = p[1] or []

    def p_balanced_tokens(self, p):
        """balanced_tokens : balanced_token
                           | balanced_tokens balanced_token"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_balanced_token(self, p):
        """balanced_token : ATTR_ATOM
                          | '(' balanced_opt ')'
                          | '[' balanced_opt ']'
                          | '{' balanced_opt '}'"""
        p[0] = p[1] if len(p) == 2 else {"delimiter": p[1]+p[3], "tokens": p[2]}

    def p_alignment(self, p):
        """attribute_specifier : ALIGNAS TYPE_PAREN abstract_type ')'
                               | ALIGNAS TYPE_PAREN abstract_type ELLIPSIS ')'
                               | ALIGNAS '(' conditional ')'
                               | ALIGNAS '(' conditional ELLIPSIS ')'"""
        if p.slice[2].type == "TYPE_PAREN":
            self.require_type_specifiers(p[3], p.lexpos(3), "alignment specifier")
        p[0] = {"type": "AlignmentSpecifier", "operand": p[3], "pack": len(p) == 6,
                "startOffset": p.lexpos(1), "endOffset": p.slice[-1].endlexpos}
