"""TypeScript import attributes in declarations, type queries and dynamic imports."""


class ImportAttributeRules:
    def p_module_specifier(self, p):
        """module_specifier : MODULE_STRING
                            | expression"""
        if p.slice[1].type == "MODULE_STRING":
            self.p_string(p)
        else:
            p[0] = p[1]

    def p_module_source(self, p):
        """module_source : string_literal
                         | string_literal ATTRIBUTE_KEYWORD attribute_object
           from_source : module_specifier
                       | module_specifier ATTRIBUTE_KEYWORD attribute_object"""
        attrs = {} if len(p) == 2 else {"attributeKeyword": p[2], "attributes": p[3]}
        p[0] = p[1], attrs

    def p_attribute_object(self, p):
        """attribute_object : LBRACE RBRACE
                            | LBRACE attributes RBRACE
                            | LBRACE attributes COMMA RBRACE"""
        p[0] = [] if len(p) == 3 else p[2]

    def p_attributes(self, p):
        """attributes : attribute
                      | attributes COMMA attribute"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_attribute(self, p):
        "attribute : module_name COLON assignment"
        p[0] = {"type": "ImportAttribute", "key": p[1], "value": p[3]}

    def p_import_decl(self, p):
        """import_decl : IMPORT module_source SEMICOLON
                       | IMPORT import_clause FROM from_source SEMICOLON"""
        p[len(p)-2], attrs = p[len(p)-2]
        super().p_import_decl(p)
        p[0].update(attrs)

    def p_expression_source_import(self, p):
        "import_decl : SOURCE_IMPORT from_source SEMICOLON"
        source, attributes = p[2]
        p[0] = {"type": "ImportDeclaration", "source": source, "specifiers": [], **attributes}
        self.decl_offsets[id(p[0])] = p.lexpos(1)

    def p_export_all(self, p):
        """export_decl : EXPORT MULTIPLY FROM from_source SEMICOLON
                       | EXPORT MULTIPLY AS module_name FROM from_source SEMICOLON"""
        p[len(p)-2], attrs = p[len(p)-2]
        super().p_export_all(p)
        p[0].update(attrs)

    def p_export_named(self, p):
        """export_decl : EXPORT named_exports SEMICOLON
                       | EXPORT named_exports FROM from_source SEMICOLON"""
        attrs = {}
        if len(p) == 6:
            p[4], attrs = p[4]
        super().p_export_named(p)
        p[0].update(attrs)

    def p_deferred_import(self, p):
        """import_decl : IMPORT DEFER_IMPORT import_clause FROM from_source SEMICOLON
                       | IMPORT SOURCE_DEFER from_source SEMICOLON"""
        source, attrs = p[len(p) - 2]
        has_clause = len(p) == 7
        p[0] = {"type": "ImportDeclaration", "source": source, "specifiers": p[3] if has_clause else [], **attrs}
        if has_clause:
            p[0]["phase"] = "defer"
        self.decl_offsets[id(p[0])] = p.lexpos(1)

    def p_import_keyword(self, p):
        "primary : IMPORT_VALUE"
        p[0] = {"type": "TSImportKeyword"}
        self.import_keyword_offsets[id(p[0])] = p.lexpos(1)

    def p_arguments(self, p):
        """arguments : argument
                     | arguments COMMA argument"""
        super().p_arguments(p)
        if len(p) == 2:
            p.slice[0].commas = []
        else:
            p.slice[0].commas = p.slice[1].commas
            p.slice[0].commas.append(p.slice[2])

    def p_call_arguments(self, p):
        """call_arguments : LPAREN RPAREN
                          | LPAREN arguments RPAREN
                          | LPAREN arguments COMMA RPAREN"""
        super().p_call_arguments(p)
        delimiters = [p.slice[1]]
        if len(p) > 3:
            delimiters.extend(p.slice[2].commas)
        if p.slice[0].trailing:
            delimiters.append(p.slice[3])
        delimiters.append(p.slice[-1])
        p.slice[0].delimiters = delimiters

    def import_call(self, argument_list, start, *, types=None, deferred=False):
        args = argument_list.value
        trailing = argument_list.trailing
        node = {"type": "ImportExpression", "source": args[0] if args else None}
        if deferred or len(args) > 1 or trailing:
            node["options"] = args[1] if len(args) > 1 else None
        if len(args) > 2:
            node["extraArguments"] = args[2:]
        if trailing:
            node["trailingComma"] = True
        if types is not None:
            node["typeArguments"] = types
        if deferred:
            node["phase"] = "defer"
        diagnostics = self.import_call_diagnostics(start, argument_list, types, deferred)
        if diagnostics:
            node["diagnostics"] = diagnostics
        return node

    def import_call_diagnostics(self, start, argument_list, types, deferred):
        args = argument_list.value
        delimiters = argument_list.delimiters
        end = delimiters[-1].lexpos + len(delimiters[-1].value)
        diagnostics = []

        def report(code, message, begin=start, stop=end):
            diagnostics.append({"code": code, "offset": begin, "length": stop - begin, "message": message})
            return diagnostics

        if self.verbatim_import_error:
            return report(self.verbatim_import_error, "ECMAScript import in a CommonJS file under verbatimModuleSyntax")
        if deferred and self.import_module not in {"esnext", "preserve"}:
            return report(18060, "deferred imports require module esnext or preserve")
        if not deferred and self.import_module == "es2015":
            return report(1323, "dynamic import is not supported with module es2015")
        if types is not None:
            return report(1326, "dynamic import cannot have type arguments")
        if self.import_module not in {"node16", "node18", "node20", "nodenext", "esnext", "preserve"}:
            if argument_list.trailing:
                comma = delimiters[-2].lexpos
                report(1009, "trailing comma not allowed in dynamic import", comma, comma + 1)
            if len(args) > 1:
                begin, stop = self.import_argument_span(args[1], delimiters[1], delimiters[2])
                return report(1324, "second import argument requires a supported module setting", begin, stop)
        if not 1 <= len(args) <= 2:
            return report(1450, "dynamic import requires a module specifier and an optional attributes argument")
        for i, arg in enumerate(args):
            if arg["type"] == "SpreadElement":
                begin, stop = self.import_argument_span(arg, delimiters[i], delimiters[i + 1])
                return report(1325, "dynamic import argument cannot be a spread element", begin, stop)
        return diagnostics

    def import_argument_span(self, arg, before, after):
        start = getattr(before, "item_start", before.lexpos + len(before.value))
        end = getattr(after, "previous_end", after.lexpos)
        if id(arg) not in self.grouped_patterns:
            if arg["type"] == "YieldExpression":
                end = before.item_end
            elif arg["type"] in {"FunctionExpression", "ClassExpression"}:
                if arg.get("id") and id(arg["id"]) in self.import_error_spans:
                    return self.import_error_spans[id(arg["id"])][1:]
                end = before.item_end
            elif arg["type"] == "TSSatisfiesExpression":
                return self.import_error_spans[id(arg)][1:]
            elif arg["type"] == "ArrowFunctionExpression" and id(arg) in self.import_error_spans:
                end = self.import_error_spans[id(arg)][2]
        return start, end

    def p_import_expression(self, p):
        """call : IMPORT call_arguments
           member : IMPORT DOT property_name
           decorator_call : IMPORT call_arguments
           decorator_member : IMPORT DOT property_name"""
        if len(p) == 3:
            p[0] = self.import_call(p.slice[2], p.lexpos(1))
        else:
            super().p_import_expression(p)
            self.import_keyword_offsets[id(p[0])] = p.lexpos(1)

    def p_dynamic_defer_import(self, p):
        """call : IMPORT DOT DEFER_CALL call_arguments
           decorator_call : IMPORT DOT DEFER_CALL call_arguments"""
        p[0] = self.import_call(p.slice[4], p.lexpos(1), deferred=True)

    def p_type_import_attributes(self, p):
        """type_import_options : COMMA LBRACE ATTRIBUTE_KEYWORD COLON attribute_object RBRACE
                               | COMMA LBRACE ATTRIBUTE_KEYWORD COLON attribute_object COMMA RBRACE"""
        p[0] = {"attributeKeyword": p[3], "attributes": p[5]}
