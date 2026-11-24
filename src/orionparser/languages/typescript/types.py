"""TypeScript type grammar, signatures and type parameter lists."""

from orionparser.languages.javascript.templates import propagate_template_escape


KEYWORD_TYPES = {
    name: "TS" + name.capitalize() + "Keyword" for name in
    ("any", "unknown", "never", "string", "number", "boolean", "symbol", "object",
     "undefined")
}
KEYWORD_TYPES["bigint"] = "TSBigIntKeyword"


class TypeRules:
    def p_index_signature(self, p):
        """ts_member : index_signature
                     | type_member_modifiers index_signature
           class_element : index_signature SEMICOLON
                         | CLASS_STATIC index_signature SEMICOLON
                         | ASYNC_METHOD index_signature SEMICOLON
                         | CLASS_STATIC ASYNC_METHOD index_signature SEMICOLON
                         | async_class_prefix index_signature SEMICOLON"""
        if p.slice[0].type == "class_element":
            p[0] = p[len(p)-2]
            self.finish_index_span(p[0], p.slice[-1])
            if len(p) == 4 and p.slice[1].type == "CLASS_STATIC":
                p[0]["static"] = True
                self.index_spans[id(p[0])][0] = p.lexpos(1)
            elif len(p) > 3:
                prefix = p[1] if p.slice[1].type == "async_class_prefix" else p.slice[1:-2]
                self.apply_class_prefix(p[0], prefix)
        elif p.slice[1].type == "type_member_modifiers":
            p[0] = p[2]
            p[0].update(p[1])
            self.index_spans[id(p[0])][0] = p.lexpos(1)
        else:
            p[0] = p[1]

    def p_index_signature_parts(self, p):
        """index_signature : TS_INDEX_OPEN index_parameters RBRACKET
                           | TS_INDEX_OPEN index_parameters RBRACKET annotation"""
        p[0] = {"type": "TSIndexSignature", "parameters": p[2], "typeAnnotation": p[4] if len(p) == 5 else None}

        self.index_spans[id(p[0])] = [p.lexpos(1), p.lexpos(3) + 1]
        self.pending_parameter_lists.setdefault(id(p[2]), (p[2], None, None))

    def finish_index_span(self, node, terminator):
        # Explicit member terminators belong to the signature. An ASI token
        # points to the end of its preceding source token.
        end = terminator.lexpos
        if self.source[end:end + 1] in {";", ","}:
            end += 1
        self.index_spans[id(node)][1] = end

    def p_index_parameters(self, p):
        """index_parameters :
                            | parameters
                            | parameters COMMA"""
        p[0] = p[1] if len(p) > 1 else []
        if len(p) == 3:
            self.register_parameter_list(p[0], p.lexpos(2))

    def p_formal_list(self, p):
        """formal_list : RPAREN
                       | parameters RPAREN
                       | parameters COMMA RPAREN"""
        p[0] = [] if len(p) == 2 else p[1]
        self.register_parameter_list(p[0], p.lexpos(2) if len(p) == 4 else None)

    def register_parameter_list(self, params, comma):
        issue = self.parameter_list_error(params)
        if comma is not None or issue:
            # Keep the list alive until its function or signature is assembled.
            self.pending_parameter_lists[id(params)] = (params, comma, issue)

    def p_parameters(self, p):
        """parameters : ts_parameter
                      | parameters COMMA ts_parameter"""
        super().p_parameters(p)
        delimiter = p.stack[-1] if len(p) == 2 else p.slice[2]
        parameter = p[0][-1]
        if parameter.get("name") == "this" and (parameter.get("decorators") or parameter.get("modifiers")):
            raise self.error(delimiter.item_start, "decorator or modifier on this parameter")
        self.parameter_starts[id(parameter)] = delimiter.item_start

    def p_ts_parameter_item(self, p):
        """ts_parameter : parameter
                        | rest_parameter"""
        p[0] = p[1]

    def p_sig_params(self, p):
        "signature_formals : SIG_PARAMS formal_list"
        p[0] = p[2]

    def p_abstract_constructor_type(self, p):
        "function_type : ABSTRACT NEW ts_params formals TYPE_ARROW return_type"
        p[0] = {"type": "TSConstructorType", "abstract": True, "typeParameters": p[3], "params": p[4],
                "returnType": p[6]}

    def p_function_type(self, p):
        """function_type : signature_formals TYPE_ARROW return_type
                   | ts_required_params formals TYPE_ARROW return_type
                   | NEW ts_params formals TYPE_ARROW return_type"""
        ctor = p.slice[1].type == "NEW"
        p[0] = {"type": "TSConstructorType" if ctor else "TSFunctionType", "params": p[len(p)-3],
                "typeParameters": p[len(p)-4] if len(p) >= 5 else None, "returnType": p[len(p)-1]}

    def p_call_signature(self, p):
        """ts_member : formals
                     | formals return_annotation
                     | ts_required_params formals
                     | ts_required_params formals return_annotation"""
        generic = p.slice[1].type == "ts_required_params"
        p[0] = {"type": "TSCallSignatureDeclaration", "params": p[2 if generic else 1],
                "typeParameters": p[1] if generic else None,
                "returnType": p[len(p)-1] if p.slice[len(p)-1].type == "return_annotation" else None}

    def p_ts_tuple(self, p):
        """ts_atom : LBRACKET RBRACKET
                   | LBRACKET tuple_members RBRACKET
                   | LBRACKET tuple_members COMMA RBRACKET"""
        p[0] = {"type": "TSTupleType", "elementTypes": p[2] if len(p) > 3 else []}

    def p_tuple_members(self, p):
        """tuple_members : tuple_member
                         | tuple_members COMMA tuple_member"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_tuple_member(self, p):
        """tuple_member : ts_type
                        | ELLIPSIS ts_type
                        | TUPLE_LABEL COLON named_tuple_type
                        | TUPLE_LABEL TUPLE_OPTIONAL COLON named_tuple_type
                        | ELLIPSIS TUPLE_LABEL COLON named_tuple_type
                        | ELLIPSIS TUPLE_LABEL TUPLE_OPTIONAL COLON named_tuple_type"""
        element = p[len(p)-1]
        if len(p) == 3 and p.slice[1].type == "ELLIPSIS":
            p[0] = {"type": "TSRestType", "typeAnnotation": element}
            return
        if element["type"] == "JSDocNullableType" and element["postfix"]:
            element = {"type": "TSOptionalType", "typeAnnotation": element["typeAnnotation"]}
        if len(p) == 2:
            p[0] = element
        else:
            rest = p.slice[1].type == "ELLIPSIS"
            member = {"type": "TSNamedTupleMember", "label": {"type": "Identifier", "name": p[2] if rest else p[1]},
                      "optional": p.slice[len(p)-3].type == "TUPLE_OPTIONAL", "elementType": element}
            p[0] = {"type": "TSRestType", "typeAnnotation": member} if rest else member

    def p_named_tuple_type(self, p):
        """named_tuple_type : ts_type
                            | ELLIPSIS ts_type"""
        p[0] = p[1] if len(p) == 2 else {"type": "TSRestType", "typeAnnotation": p[2]}

    def p_type_query(self, p):
        """ts_atom : TYPEOF ts_query_name
                   | TYPEOF ts_query_name reference_arguments
                   | TYPEOF import_type"""
        p[0] = {"type": "TSTypeQuery", "exprName": p[2]}
        if len(p) == 4:
            p[0]["typeArguments"] = p[3]

    def p_query_name(self, p):
        """ts_query_name : ts_name
                         | this_query_name
           this_query_name : THIS
                           | this_query_name DOT property_name"""
        if len(p) == 4:
            p[0] = {"type": "TSQualifiedName", "left": p[1], "right": p[3]}
        else:
            p[0] = {"type": "TSThisType"} if p.slice[1].type == "THIS" else p[1]

    def p_ts_import_type_atom(self, p):
        "ts_atom : import_type"
        p[0] = p[1]

    def p_import_type(self, p):
        """import_type : import_type_base
                       | import_type_base ts_arguments
                       | import_type_base DOT ts_name
                       | import_type_base DOT ts_name reference_arguments"""
        qualified = len(p) > 2 and p.slice[2].type == "DOT"
        p[0] = {**p[1], "qualifier": p[3] if qualified else None,
                "typeArguments": p[len(p)-1] if p.slice[len(p)-1].type in {"ts_arguments", "reference_arguments"} else None}

    def p_import_type_base(self, p):
        """import_type_base : IMPORT LPAREN ts_type RPAREN
                            | IMPORT LPAREN ts_type type_import_options RPAREN"""
        argument = p[3]
        literal = argument.get("literal", {})
        if argument["type"] == "TSLiteralType" and isinstance(literal.get("value"), str):
            argument = literal
        p[0] = {"type": "TSImportType", "argument": argument}
        if len(p) == 6:
            p[0].update(p[4])

    def p_negative_type_literal(self, p):
        "ts_atom : MINUS numeric_literal"
        p[0] = {"type": "TSLiteralType", "literal": {"type": "UnaryExpression", "operator": "-",
                                                     "prefix": True, "argument": p[2]}}

    def p_type_template(self, p):
        """ts_atom : TEMPLATE
                   | type_template_span UNTAGGED_TEMPLATE_TAIL"""
        if len(p) == 2:
            p[0] = {"type": "TSTemplateLiteralType", "quasis": [p.slice[1].quasi], "types": []}
        else:
            p[0] = p[1]
            p[0]["quasis"].append(p.slice[2].quasi)
            # TypeScript only rescans for invalid escapes in an interpolated type.
            propagate_template_escape(p, 1, 2)
            if hasattr(p.slice[0], "invalid_escape"):
                raise p.slice[0].invalid_escape

    def p_type_template_span(self, p):
        """type_template_span : UNTAGGED_TEMPLATE_HEAD ts_type
                              | type_template_span UNTAGGED_TEMPLATE_MIDDLE ts_type"""
        p.set_lexpos(0, p.lexpos(1))
        propagate_template_escape(p, 1, 2)
        if len(p) == 3:
            p[0] = {"type": "TSTemplateLiteralType", "quasis": [p.slice[1].quasi], "types": [p[2]]}
        else:
            p[0] = p[1]
            p[0]["quasis"].append(p.slice[2].quasi)
            p[0]["types"].append(p[3])

    def p_type_literal(self, p):
        "ts_atom : TS_OBJECT type_members RBRACE"
        p[0] = {"type": "TSTypeLiteral", "members": p[2]}

    def p_type_members(self, p):
        """type_members :
                        | type_members ts_member SEMICOLON
                        | type_members ts_member COMMA
                        | type_members type_accessor_implementation"""
        if len(p) == 1:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]
            if p[2]["type"] == "TSIndexSignature":
                self.finish_index_span(p[2], p.slice[-1])

    def p_type_member_modifiers(self, p):
        """type_member_modifiers : TYPE_MEMBER_MODIFIER
                                 | type_member_modifiers TYPE_MEMBER_MODIFIER"""
        p.set_lexpos(0, p.lexpos(1))
        info = p[1] if len(p) == 3 else {"modifiers": []}
        modifier = p[len(p) - 1]
        info["modifiers"].append(modifier)
        if modifier in {"public", "protected", "private"}:
            info["accessibility"] = modifier
        else:
            info[modifier] = True
        p[0] = info

    def p_member_key(self, p):
        """member_key : property_key
                      | property_key QUESTION
                      | type_member_modifiers property_key
                      | type_member_modifiers property_key QUESTION"""
        modified = p.slice[1].type == "type_member_modifiers"
        key, computed, _, offset = p[2 if modified else 1]
        p.set_lexpos(0, offset)
        p[0] = {"key": key, "computed": computed, "readonly": False,
                "optional": p.slice[len(p) - 1].type == "QUESTION"}
        if modified:
            p[0].update(p[1])

    def p_type_accessor_head(self, p):
        """type_accessor_head : CLASS_ACCESSOR property_key ts_params formals
                              | type_member_modifiers CLASS_ACCESSOR property_key ts_params formals"""
        pos = len(p) - 4
        key, computed, _, _ = p[pos + 1]
        p.set_lexpos(0, p.lexpos(pos + 3))
        p[0] = {"type": "TSMethodSignature", "kind": p[pos], "key": key, "computed": computed,
                "params": p[pos + 3], "returnType": None}
        if p[pos + 2]:
            p[0]["typeParameters"] = p[pos + 2]
        if pos == 2:
            # isTypeMemberStart scans modifiers and then tests the token after
            # get/set as if the accessor keyword were a literal property name.
            if p.slice[pos].name_on_same_line:
                raise self.error(p.lexpos(1), "modifier before type accessor")
            p[0].update(p[1])

    def p_type_accessor_signature(self, p):
        """ts_member : type_accessor_head
                     | type_accessor_head return_annotation"""
        p[0] = p[1]
        if len(p) == 3:
            p[0]["returnType"] = p[2]

    def p_type_accessor_implementation(self, p):
        "type_accessor_implementation : type_accessor_head function_body"
        p[0] = p[1]
        function = self.function_node("FunctionExpression", None, p[1]["params"], p[2], p.lexpos(1), method=True)
        p[0].update(body=function["body"], returnType=function.get("returnType"))

    def p_initialized_property_signature(self, p):
        """ts_member : member_key ASSIGN assignment
                     | member_key annotation ASSIGN assignment"""
        key = p[1]
        equals = p.slice[len(p) - 2]
        # isTypeMemberStart admits a bare literal name before '=' only
        # across a line break. get/set and computed names start members directly.
        accessor_name = not key.get("modifiers") and key["key"].get("name") in {"get", "set"}
        if len(p) == 4 and not (key["computed"] or key["optional"] or accessor_name or equals.after_line_break):
            raise self.error(p.lexpos(1), "expected type member")
        p[0] = {"type": "TSPropertySignature", **key, "typeAnnotation": p[2] if len(p) == 5 else None,
                "initializer": p[len(p) - 1]}

    def p_ts_member(self, p):
        """ts_member : member_key
                     | member_key annotation
                     | member_key ts_params formals
                     | member_key ts_params formals return_annotation"""
        if len(p) < 4:
            p[0] = {"type": "TSPropertySignature", **p[1], "typeAnnotation": p[2] if len(p) == 3 else None}
        else:
            info = p[1]
            signature = {"typeParameters": p[2], "params": p[3], "returnType": p[4] if len(p) == 5 else None}
            if info["key"]["type"] == "Identifier" and info["key"]["name"] == "new" and not (info["optional"] or info.get("modifiers") or info["computed"]):
                if not self.source.startswith("new", p.lexpos(1)):
                    raise self.error(p.lexpos(1), "escaped new keyword in construct signature")
                p[0] = {"type": "TSConstructSignatureDeclaration", **signature}
            else:
                p[0] = {"type": "TSMethodSignature", **info, **signature}

    def p_ts_params(self, p):
        """ts_params :
                     | ts_required_params"""
        p[0] = p[1] if len(p) == 2 else None

    def p_ts_required_params(self, p):
        """ts_required_params : PARAM_LT TYPE_GT
                              | PARAM_LT ts_param_list TYPE_GT
                              | PARAM_LT ts_param_list COMMA TYPE_GT"""
        p[0] = {"type": "TSTypeParameterDeclaration", "params": [] if len(p) == 3 else p[2]}
        if len(p) == 5:
            p[0]["trailingComma"] = True
        if not p[0]["params"]:
            self.mark_generic_list(p[0], 1098, p.lexpos(1), p.lexpos(2) + 1)

    def mark_generic_list(self, node, code, start, end, import_span=None):
        # The owning declaration or expression determines which grammar check runs.
        self.pending_generic_lists[id(node)] = (node, code, start, end, import_span)

    def p_ts_param_list(self, p):
        """ts_param_list : ts_param
                         | ts_param_list COMMA ts_param"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_ts_param(self, p):
        """ts_param : identifier
                    | identifier EXTENDS ts_type
                    | identifier ASSIGN ts_type
                    | identifier EXTENDS ts_type ASSIGN ts_type
                    | identifier EXPRESSION_EXTENDS exponential
                    | identifier EXPRESSION_EXTENDS exponential ASSIGN ts_type"""
        constraint = p[3] if len(p) > 2 and p.slice[2].type == "EXTENDS" else None
        default = p[len(p)-1] if len(p) > 2 and p.slice[len(p)-2].type == "ASSIGN" else None
        p[0] = {"type": "TSTypeParameter", "name": p[1], "constraint": constraint, "default": default}
        if len(p) > 2 and p.slice[2].type == "EXPRESSION_EXTENDS":
            p[0]["expression"] = p[3]
            # A top-level power expression rescans the following operator before
            # comparing precedence. Its '>' is then unavailable to close the list.
            following = self.source_lookahead
            width = getattr(following, "unsplit_operator_length", 0)
            if (len(p) == 4 and following.type == "TYPE_GT" and width and p[3].get("operator") == "**"
                    and id(p[3]) not in self.grouped_patterns):
                error = self.error(following.lexpos, "expected separator after expression constraint", code=1005, length=width)
                if self.script_pass is None:
                    raise error
                self.script_pass.record(error)
        if self.restrict_angles:
            self.type_parameter_offsets[id(p[0])] = p.lexpos(1)

    def p_variant_parameter(self, p):
        "ts_param : TYPE_PARAM_MODIFIER ts_param"
        p[0] = p[2]
        p[0].setdefault("modifiers", []).insert(0, p[1])
        if p[1] in {"in", "out", "const"}:
            p[0][p[1]] = True
        if self.restrict_angles:
            self.type_parameter_offsets[id(p[0])] = p.lexpos(1)

    def p_ts_type(self, p):
        """ts_type : check_type %prec TYPE_BASE
                   | function_type
           conditional_bound : check_type
                             | function_type
           check_type : ts_union %prec TYPE_BASE
                      | TYPE_OR ts_union
           ts_union : ts_intersection %prec TYPE_BASE
           ts_intersection : ts_operator
                           | TYPE_AND ts_operator
           ts_operator : ts_postfix %prec TYPE_BASE
           ts_postfix : ts_atom"""
        p[0] = p[len(p)-1]
        if len(p) == 3:
            kind = "TSUnionType" if p[1] == "|" else "TSIntersectionType"
            if p[0]["type"] != kind:
                p[0] = {"type": kind, "types": [p[0]]}

    def p_conditional_type(self, p):
        "ts_type : check_type CONDITIONAL_EXTENDS conditional_bound QUESTION ts_type COLON ts_type"
        p[0] = {"type": "TSConditionalType", "checkType": p[1], "extendsType": p[3],
                "trueType": p[5], "falseType": p[7]}

    def p_type_operator(self, p):
        """ts_operator : TYPE_OPERATOR ts_operator
                       | INFER identifier
                       | INFER identifier INFER_EXTENDS conditional_bound"""
        if p.slice[1].type == "INFER":
            param = {"type": "TSTypeParameter", "name": p[2]}
            if len(p) == 5:
                param["constraint"] = p[4]
            p[0] = {"type": "TSInferType", "typeParameter": param}
        else:
            p[0] = {"type": "TSTypeOperator", "operator": p[1], "typeAnnotation": p[2]}

    def p_mapped_type(self, p):
        """ts_atom : TS_OBJECT mapped_head mapped_optional mapped_annotation RBRACE
                   | TS_OBJECT mapped_head mapped_optional mapped_annotation SEMICOLON type_members RBRACE"""
        p[0] = {"type": "TSMappedType", **p[2], "optional": p[3], "typeAnnotation": p[4]}
        if len(p) == 8 and p[6]:
            p[0]["members"] = p[6]

    def p_mapped_head(self, p):
        "mapped_head : mapped_open identifier IN ts_type mapped_as RBRACKET"
        p[0] = {"readonly": p[1], "key": p[2], "constraint": p[4], "nameType": p[5]}

    def p_mapped_open(self, p):
        """mapped_open : MAP_OPEN
                       | MAPPED_READONLY MAP_OPEN
                       | PLUS MAPPED_READONLY MAP_OPEN
                       | MINUS MAPPED_READONLY MAP_OPEN"""
        p[0] = False if len(p) == 2 else True if len(p) == 3 else p[1]

    def p_mapped_as(self, p):
        """mapped_as :
                     | AS ts_type"""
        p[0] = p[2] if len(p) == 3 else None

    def p_mapped_optional(self, p):
        """mapped_optional :
                           | QUESTION
                           | PLUS QUESTION
                           | MINUS QUESTION"""
        p[0] = False if len(p) == 1 else True if len(p) == 2 else p[1]

    def p_mapped_annotation(self, p):
        """mapped_annotation :
                             | annotation"""
        p[0] = p[1]["typeAnnotation"] if len(p) == 2 else None

    def p_type_combination(self, p):
        """ts_union : ts_union TYPE_OR ts_intersection
           ts_intersection : ts_intersection TYPE_AND ts_operator"""
        kind = "TSUnionType" if p[2] == "|" else "TSIntersectionType"
        if p[1]["type"] == kind:
            p[1]["types"].append(p[3])
            p[0] = p[1]
        else:
            p[0] = {"type": kind, "types": [p[1], p[3]]}

    def p_ts_postfix(self, p):
        """ts_postfix : ts_postfix TYPE_INDEX RBRACKET
                      | ts_postfix TYPE_INDEX ts_type RBRACKET"""
        if len(p) == 4:
            p[0] = {"type": "TSArrayType", "elementType": p[1]}
        else:
            p[0] = {"type": "TSIndexedAccessType", "objectType": p[1], "indexType": p[3]}

    def p_ts_group(self, p):
        "ts_atom : LPAREN ts_type RPAREN"
        p[0] = {"type": "TSParenthesizedType", "typeAnnotation": p[2]}

    def p_ts_literal(self, p):
        """ts_atom : string_literal
                   | numeric_literal
                   | TRUE
                   | FALSE
                   | NULL
                   | VOID
                   | THIS"""
        if p.slice[1].type in {"NULL", "VOID", "THIS"}:
            p[0] = {"type": {"null": "TSNullKeyword", "void": "TSVoidKeyword", "this": "TSThisType"}[p[1]]}
        else:
            literal = {"type": "Literal", "value": p[1] == "true"} if isinstance(p[1], str) else p[1]
            p[0] = {"type": "TSLiteralType", "literal": literal}

    def p_ts_named(self, p):
        """ts_atom : ts_name
                   | ts_name reference_arguments"""
        keyword = KEYWORD_TYPES.get(p[1].get("name"))
        if keyword and (len(p) == 2 or not p[2].get("dotted")):
            escaped = getattr(p.slice[1], "escaped_token", None)
            if escaped:
                raise self.token_error(escaped, "escape in keyword type", 1260)
            if len(p) > 2:
                raise self.error(p.lexpos(2), "type arguments after keyword type")
            p[0] = {"type": keyword}
        else:
            p[0] = {"type": "TSTypeReference", "typeName": p[1], "typeArguments": p[2] if len(p) == 3 else None}

    def p_reference_arguments(self, p):
        """reference_arguments : ts_arguments
                               | TYPE_ARGUMENT_DOT ts_arguments"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = p[len(p)-1]
        if len(p) == 3:
            p[0]["dotted"] = True

    def p_ts_arguments(self, p):
        """ts_arguments : TYPE_LT TYPE_GT
                        | TYPE_LT ts_type_list TYPE_GT
                        | TYPE_LT ts_type_list COMMA TYPE_GT"""
        p.set_lexpos(0, p.lexpos(1))
        p[0] = {"type": "TSTypeParameterInstantiation", "params": [] if len(p) == 3 else p[2]}
        end = p.lexpos(len(p)-1) + 1
        callee = getattr(p.stack[-1], "value", None)
        import_span = None
        if isinstance(callee, dict) and callee.get("type") == "TSImportKeyword":
            import_span = (self.import_keyword_offsets[id(callee)], end)
        if len(p) == 3:
            self.mark_generic_list(p[0], 1099, p.lexpos(1), end, import_span)
        elif len(p) == 5:
            p[0]["trailingComma"] = True
            self.mark_generic_list(p[0], 1009, p.lexpos(3), p.lexpos(3) + 1, import_span)
        elif import_span:
            self.mark_generic_list(p[0], None, p.lexpos(1), end, import_span)

    def p_ts_name(self, p):
        """ts_name : identifier
                   | TYPE_NAME
                   | PRIVATE_NAME
                   | ts_name DOT property_name"""
        p.set_lexpos(0, p.lexpos(1))
        if len(p) == 2:
            if getattr(p.slice[1], "escaped", False):
                p.slice[0].escaped_token = p.slice[1]
            elif hasattr(p.slice[1], "escaped_token"):
                p.slice[0].escaped_token = p.slice[1].escaped_token
        if p.slice[1].type == "PRIVATE_NAME":
            if getattr(p.slice[1], "after_type_list_delimiter", False):
                raise self.error(p.lexpos(1), "private identifier at start of type list")
            p[0] = {"type": "Identifier", "name": "#" + p[1]}
            self.private_offsets[id(p[0])] = p.lexpos(1)
            return
        if p.slice[1].type == "TYPE_NAME":
            p[0] = {"type": "Identifier", "name": p[1]}
            return
        p[0] = p[1] if len(p) == 2 else {"type": "TSQualifiedName", "left": p[1], "right": p[3]}

    def p_ts_type_list(self, p):
        """ts_type_list : ts_type
                        | ts_type_list COMMA ts_type"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_return_annotation(self, p):
        "return_annotation : COLON return_type"
        p[0] = {"type": "TSTypeAnnotation", "typeAnnotation": p[2]}

    def p_return_type(self, p):
        """return_type : ts_type
                       | identifier IS ts_type
           ts_atom : THIS IS ts_type
                   | ASSERTS predicate_name
                   | ASSERTS predicate_name ASSERT_IS ts_type"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            asserts = p.slice[1].type == "ASSERTS"
            target = p[2] if asserts else p[1]
            if p.slice[1].type == "THIS":
                target = {"type": "TSThisType"}
            annotation = None if len(p) == 3 else {"type": "TSTypeAnnotation", "typeAnnotation": p[len(p)-1]}
            p[0] = {"type": "TSTypePredicate", "asserts": asserts, "parameterName": target, "typeAnnotation": annotation}

    def p_predicate_name(self, p):
        """predicate_name : identifier
                          | THIS"""
        p[0] = {"type": "TSThisType"} if p.slice[1].type == "THIS" else p[1]

    def p_annotation(self, p):
        "annotation : COLON ts_type"
        p[0] = {"type": "TSTypeAnnotation", "typeAnnotation": p[2]}
