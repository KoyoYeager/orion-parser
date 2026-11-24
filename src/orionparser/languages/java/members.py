"""Class members, executable blocks and expression grammar for Java."""
class MemberRules:
    # A cast may introduce a lambda inside another expression. Keep the longest
    # expression in its body using the same precedence as the binary productions.
    precedence = (("nonassoc", "IF"), ("nonassoc", "ELSE"), ("nonassoc", "BODY_PROMOTION"), ("right", "?"), ("left", "OR"),
                  ("left", "AND"), ("left", "|"), ("left", "^"), ("left", "&"), ("left", "EQ"),
                  ("left", "<", ">", "REL", "INSTANCEOF"), ("left", "SHIFT"), ("left", "+", "-"), ("left", "*", "/", "%"))

    def p_members(self, p):
        """members : empty
                   | members member"""
        if len(p) == 2:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_member(self, p):
        """member : prefix type variables ';'
                  | prefix type IDENT '(' method_parameters ')' dims throws_opt method_body
                  | prefix VOID IDENT '(' method_parameters ')' dims throws_opt method_body
                  | prefix block
                  | prefix IDENT block
                  | prefix IDENT '(' method_parameters ')' throws_opt constructor_body
                  | prefix type_parameters type IDENT '(' method_parameters ')' dims throws_opt method_body
                  | prefix type_parameters VOID IDENT '(' method_parameters ')' dims throws_opt method_body
                  | prefix type_parameters type_annotations type IDENT '(' method_parameters ')' dims throws_opt method_body
                  | prefix type_parameters type_annotations VOID IDENT '(' method_parameters ')' dims throws_opt method_body
                  | prefix type_parameters IDENT '(' method_parameters ')' throws_opt constructor_body
                  | type_declaration
                  | ';'"""
        if len(p) == 2:
            p[0] = p[1] if p.slice[1].type == "type_declaration" else {"type": "EmptyDeclaration"}
        elif len(p) == 3:
            if p[1] not in ([], ["static"]):
                raise self.source.error(p.lexpos(1), "invalid initializer modifier")
            p[0] = {"type": "Initializer", "static": bool(p[1]), "body": p[2]}
        elif len(p) == 4:
            p[0] = {"type": "CompactConstructorDeclaration", "modifiers": p[1], "name": p[2], "body": p[3]}
        elif len(p) == 5:
            self.check_named_type(p[2]["name"], p.lexpos(2))
            p[0] = {"type": "FieldDeclaration", "modifiers": p[1], "fieldType": p[2], "variables": p[3]}
        else:
            generic = p.slice[2].type == "type_parameters"
            annotated_result = generic and p.slice[3].type == "type_annotations"
            first = 4 if annotated_result else 3 if generic else 2
            constructor = p.slice[first].type == "IDENT"
            name_index = first if constructor else first + 1
            receiver, parameters = p[name_index+2]
            p[0] = {"type": "ConstructorDeclaration" if constructor else "MethodDeclaration",
                    "name": p[name_index], "modifiers": p[1], "typeParameters": p[2] if generic else [],
                    "parameters": parameters, "throws": p[len(p)-2], "body": p[len(p)-1]}
            if receiver is not None:
                p[0]["receiverParameter"] = receiver
            if not constructor:
                if isinstance(p[first], dict):
                    self.check_named_type(p[first]["name"], p.lexpos(first))
                p[0]["returnType"] = p[first]
                if annotated_result:
                    p[0]["resultAnnotations"] = p[3]
                dims = p[name_index+4]
                if dims:
                    if p[first] == "void":
                        raise self.source.error(p.lexpos(name_index+4), "void method cannot declare array dimensions")
                    p[0]["dimensions"] = dims
                    self.attach_dimension_annotations(p[0], p.slice[name_index+4])

    def check_named_type(self, name, offset, *, allow_var=False):
        if name == "var" and allow_var:
            return
        if name.rsplit(".", 1)[-1] in {"var", "yield", "record", "sealed", "permits"}:
            raise self.source.error(offset, "restricted identifier in type name")

    def p_type(self, p):
        """type : PRIMITIVE dims
                | name dims
                | parameterized dims"""
        p.set_lexpos(0, p.lexpos(1))
        if isinstance(p[1], str):
            p[0] = {"type": "Type", "name": p[1], "dimensions": p[2]}
        else:
            p[0] = {**p[1], "dimensions": p[2]}
        self.check_named_type(p[0]["name"], p.lexpos(1), allow_var=p[2] == 0 and isinstance(p[1], str))
        self.attach_dimension_annotations(p[0], p.slice[2])

    def p_reference(self, p):
        """reference : name
                     | parameterized"""
        if isinstance(p[1], str):
            self.check_named_type(p[1], p.lexpos(1))
        p.set_lexpos(0, p.lexpos(1))
        p[0] = p[1]

    def p_parameterized(self, p):
        """parameterized : name type_arguments
                         | parameterized '.' IDENT
                         | parameterized '.' IDENT type_arguments
                         | name '.' type_annotations IDENT
                         | name '.' type_annotations IDENT type_arguments
                         | parameterized '.' type_annotations IDENT
                         | parameterized '.' type_annotations IDENT type_arguments"""
        p.set_lexpos(0, p.lexpos(1))
        if isinstance(p[1], str):
            segments = [{"name": part, "arguments": []} for part in p[1].split(".")]
            node = {"type": "Type", "name": p[1], "segments": segments}
        else:
            node = p[1]
        if len(p) == 3:
            node["segments"][-1]["arguments"] = p[2]
        else:
            annotated = p.slice[3].type == "type_annotations"
            ident = 4 if annotated else 3
            segment = {"name": p[ident], "arguments": p[ident+1] if ident+1 < len(p) else []}
            if annotated:
                segment["annotations"] = p[3]
            node["name"] += "." + p[ident]
            node["segments"].append(segment)
        self.check_named_type(node["name"], p.lexpos(1))
        p[0] = node

    def p_type_arguments(self, p):
        "type_arguments : TYPE_OPEN type_argument_list TYPE_CLOSE"
        p[0] = p[2]

    def p_reference_list(self, p):
        """type_argument_list : type_argument
                              | type_argument_list ',' type_argument
           references : annotated_reference
                      | references ',' annotated_reference
           type_parameter_list : type_parameter
                               | type_parameter_list ',' type_parameter
           bounds : annotated_reference
                  | bounds '&' annotated_reference"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    @staticmethod
    def annotate_type(t, annotations):
        node = {"type": "Type", "name": t} if isinstance(t, str) else t
        return {**node, "annotations": annotations}

    def p_annotated_type(self, p):
        """annotated_type : type
                          | type_annotations type
           annotated_reference : reference
                               | type_annotations reference"""
        p[0] = p[1] if len(p) == 2 else self.annotate_type(p[2], p[1])
        if isinstance(p[0], dict):
            self.check_named_type(p[0]["name"], p.lexpos(len(p)-1))

    def p_type_argument(self, p):
        """type_argument : annotated_type
                         | wildcard
                         | type_annotations wildcard"""
        p[0] = p[1] if len(p) == 2 else {**p[2], "annotations": p[1]}
        operand = p[0].get("bound") if p[0]["type"] == "Wildcard" else p[0]
        if operand and operand.get("dimensions") == 0 and operand["name"] in {
            "boolean", "byte", "char", "double", "float", "int", "long", "short"
        }:
            raise self.source.error(p.lexpos(1), "primitive type argument requires array dimensions")

    def p_wildcard(self, p):
        """wildcard : '?'
                    | '?' EXTENDS annotated_type
                    | '?' SUPER annotated_type"""
        p[0] = {"type": "Wildcard", "boundKind": p[2] if len(p) == 4 else None,
                "bound": p[3] if len(p) == 4 else None}

    def p_type_parameters(self, p):
        """type_parameters : TYPE_OPEN type_parameter_list TYPE_CLOSE"""
        p[0] = p[2]

    def p_type_parameter(self, p):
        """type_parameter : IDENT
                          | IDENT EXTENDS bounds
                          | type_annotations IDENT
                          | type_annotations IDENT EXTENDS bounds"""
        ident = 1 if p.slice[1].type == "IDENT" else 2
        if p[ident] in {"var", "yield", "record", "sealed", "permits"}:
            raise self.source.error(p.lexpos(ident), "restricted type parameter name")
        p[0] = {"type": "TypeParameter", "name": p[ident], "bounds": p[len(p)-1] if p.slice[-1].type == "bounds" else []}
        if ident == 2:
            p[0]["annotations"] = p[1]

    @staticmethod
    def attach_dimension_annotations(node, symbol):
        annotations = getattr(symbol, "dimension_annotations", None)
        if annotations:
            node["dimensionAnnotations"] = annotations

    def p_dims(self, p):
        """dims : empty
                | nonempty_dims"""
        p[0] = p[1] or 0
        p.slice[0].dimension_annotations = getattr(p.slice[1], "dimension_annotations", None)

    def p_nonempty_dims(self, p):
        """nonempty_dims : DIM
                         | nonempty_dims DIM
                         | dimension_annotations DIM
                         | nonempty_dims dimension_annotations DIM"""
        prefix = p.slice[1].type == "nonempty_dims"
        previous = p[1] if prefix else 0
        p[0] = previous + 1
        last = p[len(p)-2] if p.slice[-2].type == "dimension_annotations" else []
        dimensions = getattr(p.slice[1], "dimension_annotations", None) if prefix else None
        if dimensions is not None:
            dimensions.append(last)
        elif last:
            dimensions = [[] for _ in range(previous)] + [last]
        p.slice[0].dimension_annotations = dimensions

    def p_dimension_annotations(self, p):
        """dimension_annotations : dimension_annotation
                                 | dimension_annotations dimension_annotation"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_method_parameters(self, p):
        """method_parameters : parameters
                             | receiver_parameter
                             | receiver_parameter ',' parameter_list"""
        if p.slice[1].type == "parameters":
            p[0] = (None, p[1])
        else:
            p[0] = (p[1], p[3] if len(p) == 4 else [])
        offset = getattr(p.slice[-1], "var_offset", None)
        if offset is not None:
            raise self.source.error(offset, "var is not a method or constructor parameter type")

    def p_receiver_parameter(self, p):
        """receiver_parameter : type THIS
                              | type IDENT '.' THIS
                              | parameter_modifiers type THIS
                              | parameter_modifiers type IDENT '.' THIS"""
        index = 2 if p.slice[1].type == "parameter_modifiers" else 1
        modifiers = p[1] if index == 2 else []
        self.check_named_type(p[index]["name"], p.lexpos(index))
        if "final" in modifiers:
            raise self.source.error(p.lexpos(1), "receiver parameters permit annotations only")
        p[0] = {"type": "ReceiverParameter", "receiverType": p[index], "annotations": modifiers,
                "qualifier": p[index+1] if p.slice[index+1].type == "IDENT" else None}

    def p_parameters(self, p):
        """parameters : empty
                      | parameter_list"""
        p[0] = p[1] or []
        p.slice[0].var_offset = getattr(p.slice[1], "var_offset", None)

    def p_nonempty_list(self, p):
        """parameter_list : parameter
                          | parameter_list ',' parameter
           variables : variable
                     | variables ',' variable
           arguments : expression
                     | arguments ',' expression"""
        if p.slice[0].type == "parameter_list":
            prior = getattr(p.slice[1], "var_offset", None)
            param = p[len(p)-1]
            p.slice[0].var_offset = p.lexpos(len(p)-1) if prior is None and param["parameterType"]["name"] == "var" else prior
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            if p.slice[0].type == "parameter_list" and p[1][-1]["variadic"]:
                raise self.source.error(p.lexpos(2), "variable arity parameter must be last")
            p[1].append(p[3])
            p[0] = p[1]

    def p_parameter(self, p):
        """parameter : type IDENT dims
                     | parameter_modifiers type IDENT dims
                     | type ELLIPSIS IDENT
                     | parameter_modifiers type ELLIPSIS IDENT
                     | type type_annotations ELLIPSIS IDENT
                     | parameter_modifiers type type_annotations ELLIPSIS IDENT"""
        modified = p.slice[1].type == "parameter_modifiers"
        modifiers = p[1] if modified else []
        variadic = p.slice[-2].type == "ELLIPSIS"
        type_index = 2 if modified else 1
        p.set_lexpos(0, p.lexpos(type_index))
        p[0] = {"type": "Parameter", "name": p[len(p)-1] if variadic else p[len(p)-2],
                "parameterType": p[type_index], "dimensions": 0 if variadic else p[len(p)-1],
                "final": "final" in modifiers, "modifiers": modifiers, "variadic": variadic}
        if not variadic:
            self.attach_dimension_annotations(p[0], p.slice[-1])
        if variadic and p.slice[type_index+1].type == "type_annotations":
            p[0]["varargAnnotations"] = p[type_index+1]

    def p_parameter_modifiers(self, p):
        """parameter_modifiers : FINAL
                               | annotation
                               | parameter_modifiers FINAL
                               | parameter_modifiers annotation
           type_annotations : annotation
                              | type_annotations annotation"""
        values = p[1] if len(p) == 3 else []
        last = p[len(p)-1]
        if last == "final" and "final" in values:
            raise self.source.error(p.lexpos(len(p)-1), "duplicate final parameter modifier")
        values.append(last)
        p[0] = values

    def p_variable(self, p):
        """variable : IDENT dims
                    | IDENT dims '=' variable_initializer"""
        p[0] = {"type": "VariableDeclarator", "name": p[1], "dimensions": p[2],
                "initializer": p[4] if len(p) == 5 else None}
        self.attach_dimension_annotations(p[0], p.slice[2])

    def p_variable_initializer(self, p):
        """variable_initializer : expression
                                | array_initializer"""
        p[0] = p[1]

    def p_array_initializer(self, p):
        """array_initializer : '{' '}'
                             | '{' ',' '}'
                             | '{' variable_initializers '}'
                             | '{' variable_initializers ',' '}'"""
        p[0] = {"type": "ArrayInitializer", "values": p[2] if p.slice[2].type == "variable_initializers" else []}

    def p_variable_initializers(self, p):
        """variable_initializers : variable_initializer
                                 | variable_initializers ',' variable_initializer"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_method_body(self, p):
        """method_body : block
                       | ';'"""
        p[0] = None if p[1] == ";" else p[1]

    def p_constructor_body(self, p):
        "constructor_body : '{' constructor_invocation block_items '}'"
        statements = p[3] if p[2] is None else [p[2], *p[3]]
        p[0] = {"type": "Block", "statements": statements}

    def p_constructor_invocation(self, p):
        """constructor_invocation : empty
                                  | CTOR_HEAD ref_arguments CTOR_CALL '(' arguments_opt ')' ';'
                                  | CTOR_HEAD name '.' ref_arguments CTOR_CALL '(' arguments_opt ')' ';'
                                  | CTOR_HEAD primary '.' ref_arguments CTOR_CALL '(' arguments_opt ')' ';'"""
        if len(p) == 2:
            p[0] = None
            return
        call = len(p)-5
        target = p[call]
        p[0] = {"type": "ConstructorInvocation", "target": target, "arguments": p[call+2]}
        if p[call-1]:
            p[0]["typeArguments"] = p[call-1]
        if call == 5:
            if target != "super":
                raise self.source.error(p.lexpos(call), "qualified constructor invocation requires super")
            p[0]["qualifier"] = {"type": "NameExpression", "name": p[2]} if p.slice[2].type == "name" else p[2]

    def p_block(self, p):
        "block : '{' block_items '}'"
        p[0] = {"type": "Block", "statements": p[2]}

    def p_block_items(self, p):
        """block_items : empty
                       | block_items local_type
                       | block_items statement
                       | block_items local_declaration ';'"""
        if len(p) == 2:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_local_type(self, p):
        """local_type : local_type_base
                      | parameter_modifiers local_type_base
                      | local_class_modifiers local_type_base"""
        p[0] = p[1] if len(p) == 2 else self.modified_type(p[2], p[1], p.lexpos(1))

    def p_local_type_base(self, p):
        """local_type_base : normal_type
                           | record_base
                           | enum_base"""
        p[0] = p[1]

    def p_local_class_modifiers(self, p):
        """local_class_modifiers : ABSTRACT
                                 | STRICTFP
                                 | parameter_modifiers ABSTRACT
                                 | parameter_modifiers STRICTFP
                                 | local_class_modifiers ABSTRACT
                                 | local_class_modifiers STRICTFP
                                 | local_class_modifiers FINAL
                                 | local_class_modifiers annotation"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_local_declaration(self, p):
        """local_declaration : type variables
                             | parameter_modifiers type variables"""
        if p[len(p)-2]["name"] == "var":
            variables = p[len(p)-1]
            if len(variables) != 1 or variables[0]["dimensions"] or variables[0]["initializer"] is None:
                raise self.source.error(p.lexpos(len(p)-2), "var requires one initialized variable without trailing dimensions")
            if variables[0]["initializer"]["type"] == "ArrayInitializer":
                raise self.source.error(p.lexpos(len(p)-1), "var cannot infer an array initializer")
        p[0] = {"type": "LocalVariableDeclaration", "variableType": p[len(p)-2],
                "variables": p[len(p)-1], "final": len(p) == 4 and "final" in p[1],
                "modifiers": p[1] if len(p) == 4 else []}

    def p_statement(self, p):
        """statement : block
                     | ';'
                     | RETURN expression_opt ';'
                     | THROW expression ';'
                     | statement_expression ';'
                     | IF '(' expression ')' statement %prec IF
                     | IF '(' expression ')' statement ELSE statement
                     | WHILE '(' expression ')' statement
                     | FOR '(' parameter ':' expression ')' statement"""
        kind = p.slice[1].type
        if kind == "block":
            p[0] = p[1]
        elif kind == ";":
            p[0] = {"type": "EmptyStatement"}
        elif kind == "statement_expression":
            p[0] = {"type": "ExpressionStatement", "expression": p[1]}
        elif kind in {"RETURN", "THROW"}:
            p[0] = {"type": p[1].capitalize() + "Statement", "expression": p[2]}
        elif kind == "IF":
            p[0] = {"type": "IfStatement", "condition": p[3], "then": p[5], "else": p[7] if len(p) == 8 else None}
        elif kind == "WHILE":
            p[0] = {"type": "WhileStatement", "condition": p[3], "body": p[5]}
        else:
            if p[3]["variadic"]:
                raise self.source.error(p.lexpos(3), "variable arity is not permitted in enhanced for")
            p[0] = {"type": "EnhancedForStatement", "variable": p[3], "iterable": p[5], "body": p[7]}

    @staticmethod
    def is_statement_expression(expr):
        return expr["type"] in {"AssignmentExpression", "MethodInvocation", "NewClass"} or (
            expr["type"] == "UnaryExpression" and expr["operator"] in {"++", "--"})

    def p_statement_expression(self, p):
        "statement_expression : expression"
        expr = p[1]
        if not self.is_statement_expression(expr):
            raise self.source.error(p.lexpos(1), "expected a statement expression")
        p[0] = expr

    def p_basic_for(self, p):
        "statement : FOR '(' for_init ';' expression_opt ';' for_update ')' statement"
        p[0] = {"type": "ForStatement", "init": p[3], "condition": p[5], "update": p[7], "body": p[9]}

    def p_for_init(self, p):
        """for_init : local_declaration
                    | for_update"""
        p[0] = p[1]

    def p_for_update(self, p):
        """for_update : empty
                      | statement_expressions"""
        p[0] = p[1] or []

    def p_statement_expressions(self, p):
        """statement_expressions : statement_expression
                                 | statement_expressions ',' statement_expression"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_do_while(self, p):
        "statement : DO statement WHILE '(' expression ')' ';'"
        p[0] = {"type": "DoWhileStatement", "body": p[2], "condition": p[5]}

    def p_label(self, p):
        "statement : IDENT ':' statement"
        p[0] = {"type": "LabeledStatement", "label": p[1], "body": p[3]}

    def p_jump(self, p):
        """statement : BREAK ';'
                     | BREAK IDENT ';'
                     | CONTINUE ';'
                     | CONTINUE IDENT ';'"""
        p[0] = {"type": p[1].capitalize() + "Statement", "label": p[2] if len(p) == 4 else None}

    def p_assert(self, p):
        """statement : ASSERT expression ';'
                     | ASSERT expression ':' expression ';'"""
        p[0] = {"type": "AssertStatement", "condition": p[2], "detail": p[4] if len(p) == 6 else None}

    def p_synchronized(self, p):
        "statement : SYNCHRONIZED '(' expression ')' block"
        p[0] = {"type": "SynchronizedStatement", "monitor": p[3], "body": p[5]}

    def p_expression_opt(self, p):
        """expression_opt : empty
                          | expression"""
        p[0] = p[1]

    def p_expression(self, p):
        """expression : conditional
                      | lambda_expression
                      | postfix '=' expression
                      | postfix ASSIGN_OP expression"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            if p[1]["type"] not in {"NameExpression", "MemberAccess", "ArrayAccess"}:
                raise self.source.error(p.lexpos(2), "expected a variable before assignment")
            p[0] = {"type": "AssignmentExpression", "operator": p[2], "left": p[1], "right": p[3]}

    def p_lambda(self, p):
        """lambda_expression : LAMBDA_IDENT ARROW lambda_body
                             | LAMBDA_OPEN lambda_parameters ')' ARROW lambda_body"""
        params = [{"type": "InferredParameter", "name": p[1]}] if len(p) == 4 else p[2]
        p[0] = {"type": "LambdaExpression", "parameters": params, "body": p[len(p)-1]}

    def p_lambda_body(self, p):
        """lambda_body : expression
                       | block"""
        p[0] = p[1]

    def p_lambda_parameters(self, p):
        """lambda_parameters : parameters
                             | inferred_parameters"""
        p[0] = p[1]
        if p[0] and p[0][0]["type"] == "Parameter":
            inferred = [param["parameterType"]["name"] == "var" for param in p[0]]
            if any(is_var and (param["variadic"] or param["dimensions"] or param["parameterType"]["dimensions"])
                   for is_var, param in zip(inferred, p[0])):
                raise self.source.error(p.lexpos(1), "var lambda parameter cannot have array dimensions or ellipsis")
            if any(inferred) and not all(inferred):
                raise self.source.error(p.lexpos(1), "mixed var and explicit lambda parameter types")

    def p_inferred_parameters(self, p):
        """inferred_parameters : IDENT
                               | inferred_parameters ',' IDENT"""
        param = {"type": "InferredParameter", "name": p[len(p)-1]}
        if len(p) == 2:
            p[0] = [param]
        else:
            p[1].append(param)
            p[0] = p[1]

    def p_cast(self, p):
        """unary : CAST_OPEN annotated_type ')' unary
                 | CAST_OPEN annotated_type ')' lambda_expression"""
        if p.slice[4].type == "lambda_expression" and p[2]["name"] in {"int", "boolean", "long", "char", "byte", "short", "float", "double"} and not p[2]["dimensions"]:
            raise self.source.error(p.lexpos(2), "lambda requires a reference cast")
        p[0] = {"type": "CastExpression", "target": p[2], "operand": p[4]}

    def p_intersection_cast(self, p):
        """unary : CAST_OPEN annotated_reference '&' bounds ')' unary
                 | CAST_OPEN annotated_reference '&' bounds ')' lambda_expression"""
        p[0] = {"type": "CastExpression", "target": {"type": "IntersectionType", "bounds": [p[2], *p[4]]},
                "operand": p[6]}

    def p_reference_annotations(self, p):
        """reference_annotations : reference_annotation
                                 | reference_annotations annotation"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_annotated_method_reference(self, p):
        """primary : reference_annotations reference COLONS ref_arguments ref_member
                   | reference_annotations reference nonempty_dims COLONS ref_arguments ref_member
                   | reference_annotations PRIMITIVE nonempty_dims COLONS ref_arguments ref_member"""
        qualifier = self.annotate_type(p[2], p[1])
        qualifier["dimensions"] = p[3] if len(p) == 7 else 0
        if len(p) == 7:
            self.attach_dimension_annotations(qualifier, p.slice[3])
        p[0] = self.method_reference(qualifier, p[len(p)-2], p[len(p)-1], p.lexpos(len(p)-1))

    def p_method_reference(self, p):
        """primary : name COLONS ref_arguments ref_member
                   | primary COLONS ref_arguments IDENT
                   | parameterized COLONS ref_arguments ref_member
                   | name nonempty_dims COLONS ref_arguments ref_member
                   | parameterized nonempty_dims COLONS ref_arguments ref_member
                   | PRIMITIVE nonempty_dims COLONS ref_arguments ref_member
                   | SUPER COLONS ref_arguments IDENT
                   | name '.' SUPER COLONS ref_arguments IDENT"""
        kind = p.slice[1].type
        if len(p) == 7:
            qualifier = {"type": "SuperExpression", "qualifier": p[1]}
        elif kind == "SUPER":
            qualifier = {"type": "SuperExpression"}
        elif kind == "primary":
            qualifier = p[1]
        elif len(p) == 6 or kind == "parameterized":
            qualifier = dict(p[1]) if isinstance(p[1], dict) else {"type": "Type", "name": p[1]}
            qualifier["dimensions"] = p[2] if len(p) == 6 else 0
        elif p[len(p)-1] == "new":
            qualifier = {"type": "Type", "name": p[1], "dimensions": 0}
        else:
            qualifier = {"type": "NameExpression", "name": p[1]}
        if len(p) == 6:
            self.attach_dimension_annotations(qualifier, p.slice[2])
        if qualifier["type"] == "Type":
            self.check_named_type(qualifier["name"], p.lexpos(1))
        p[0] = self.method_reference(qualifier, p[len(p)-2], p[len(p)-1], p.lexpos(len(p)-1))

    def method_reference(self, qualifier, arguments, name, offset):
        if qualifier.get("dimensions") and name == "new" and arguments:
            raise self.source.error(offset, "array constructor reference cannot take type arguments")
        return {"type": "MethodReference", "qualifier": qualifier, "typeArguments": arguments, "name": name}

    def p_ref_arguments(self, p):
        """ref_arguments : empty
                         | type_arguments"""
        p[0] = p[1] or []

    def p_ref_member(self, p):
        """ref_member : IDENT
                      | NEW"""
        p[0] = p[1]

    def p_conditional(self, p):
        """conditional : logical_or %prec BODY_PROMOTION
                       | logical_or '?' expression ':' conditional
                       | logical_or '?' expression ':' lambda_expression"""
        p[0] = p[1] if len(p) == 2 else {"type": "ConditionalExpression", "condition": p[1], "then": p[3], "else": p[5]}

    def p_try(self, p):
        """statement : TRY block try_tail
                     | TRY resource_spec block try_tail_opt"""
        with_resources = len(p) == 5
        catches, cleanup = p[len(p)-1]
        p[0] = {"type": "TryStatement", "resources": p[2] if with_resources else [],
                "body": p[len(p)-2], "catches": catches, "finally": cleanup}

    def p_try_tail_opt(self, p):
        """try_tail_opt : empty
                        | try_tail"""
        p[0] = p[1] if p[1] is not None else ([], None)

    def p_try_tail(self, p):
        """try_tail : catches
                    | catches FINALLY block
                    | FINALLY block"""
        if p.slice[1].type == "FINALLY":
            p[0] = ([], p[2])
        else:
            p[0] = (p[1], p[3] if len(p) == 4 else None)

    def p_catches(self, p):
        """catches : catch_clause
                   | catches catch_clause"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_catch(self, p):
        "catch_clause : CATCH '(' catch_parameter ')' block"
        p[0] = {"type": "CatchClause", "parameter": p[3], "body": p[5]}

    def p_catch_parameter(self, p):
        """catch_parameter : catch_types IDENT dims
                           | parameter_modifiers catch_types IDENT dims"""
        types = p[len(p)-3]
        if "var" in types:
            raise self.source.error(p.lexpos(len(p)-3), "var is not a catch parameter type")
        p[0] = {"type": "CatchParameter", "name": p[len(p)-2], "types": types, "dimensions": p[len(p)-1],
                "modifiers": p[1] if len(p) == 5 else []}
        self.attach_dimension_annotations(p[0], p.slice[-1])

    def p_catch_types(self, p):
        """catch_types : reference
                       | catch_types '|' annotated_reference"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_resource_spec(self, p):
        """resource_spec : '(' resources ')'
                         | '(' resources ';' ')'"""
        p[0] = p[2]

    def p_resources(self, p):
        """resources : resource
                     | resources ';' resource"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_resource(self, p):
        """resource : local_declaration
                    | expression"""
        resource = p[1]
        if resource["type"] == "LocalVariableDeclaration":
            variables = resource["variables"]
            if len(variables) != 1 or variables[0]["initializer"] is None:
                raise self.source.error(p.lexpos(1), "expected one initialized resource variable")
        elif resource["type"] not in {"NameExpression", "MemberAccess"}:
            raise self.source.error(p.lexpos(1), "expected a resource variable access")
        p[0] = resource

    def p_switch(self, p):
        """statement : SWITCH_STMT '(' expression ')' switch_block
           unary : SWITCH '(' expression ')' switch_block"""
        p[0] = {"type": "SwitchStatement" if p.slice[0].type == "statement" else "SwitchExpression",
                "selector": p[3], "body": p[5]}

    def p_switch_block(self, p):
        "switch_block : '{' switch_entries '}'"
        p[0] = {"type": "SwitchBlock", "entries": p[2]}

    def p_switch_entries(self, p):
        """switch_entries : empty
                          | switch_entries switch_entry"""
        if len(p) == 2:
            p[0] = []
            return
        entries, entry = p[1], p[2]
        if entries and entries[0]["type"] != entry["type"]:
            raise self.source.error(p.lexpos(2), "mixed switch rule and colon labels")
        if entries and entry["type"] == "SwitchGroup" and not entries[-1]["statements"]:
            entries[-1]["labels"].extend(entry["labels"])
            entries[-1]["statements"] = entry["statements"]
        else:
            entries.append(entry)
        p[0] = entries

    def p_switch_entry(self, p):
        """switch_entry : switch_label ':' block_items
                        | switch_label ARROW expression ';'
                        | switch_label ARROW block
                        | switch_label ARROW THROW expression ';'"""
        if p[2] == ":":
            p[0] = {"type": "SwitchGroup", "labels": [p[1]], "statements": p[3]}
        else:
            if p.slice[3].type == "expression" and not self.is_statement_expression(p[3]):
                enclosing = next(sym.type for sym in reversed(p.stack) if sym.type in {"SWITCH", "SWITCH_STMT"})
                if enclosing == "SWITCH_STMT":
                    raise self.source.error(p.lexpos(3), "expected a statement expression in switch rule")
            body = {"type": "ThrowStatement", "expression": p[4]} if len(p) == 6 else p[3]
            p[0] = {"type": "SwitchRule", "label": p[1], "body": body}

    def p_switch_label(self, p):
        """switch_label : DEFAULT
                        | CASE constants
                        | CASE constants ',' DEFAULT
                        | CASE pattern
                        | CASE pattern WHEN expression"""
        if len(p) == 2:
            p[0] = {"type": "DefaultLabel"}
        elif p.slice[2].type == "constants":
            combined = len(p) == 5
            if combined and p[2] != [{"type": "Literal", "raw": "null"}]:
                raise self.source.error(p.lexpos(4), "default may follow only case null")
            p[0] = {"type": "CaseConstants", "values": p[2], "includesDefault": combined}
        else:
            self.check_top_pattern(p[2], p.lexpos(2))
            p[0] = {"type": "CasePattern", "pattern": p[2], "guard": p[4] if len(p) == 5 else None}

    def p_case_constants(self, p):
        """constants : conditional
                     | constants ',' conditional"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_yield(self, p):
        "statement : YIELD expression ';'"
        p[0] = {"type": "YieldStatement", "expression": p[2]}

    def check_top_pattern(self, pattern, offset):
        if pattern["type"] == "TypePattern" and pattern["variable"]["parameterType"]["name"] == "var":
            raise self.source.error(offset, "var pattern requires an enclosing record pattern")

    def p_instanceof(self, p):
        """relation : relation INSTANCEOF type
                    | relation INSTANCEOF parameter_modifiers type
                    | relation INSTANCEOF pattern"""
        target = p[len(p)-1]
        if len(p) == 5:
            if "final" in p[3]:
                raise self.source.error(p.lexpos(3), "final requires a binding variable")
            target = self.annotate_type(target, p[3])
        if target["type"] == "Type" and target["name"] in {"boolean", "byte", "char", "double", "float", "int", "long", "short"} and not target["dimensions"]:
            raise self.source.error(p.lexpos(3), "expected a reference type after instanceof")
        if p.slice[3].type == "pattern":
            self.check_top_pattern(p[3], p.lexpos(3))
        p[0] = {"type": "InstanceOfExpression", "operand": p[1], "test": target}

    def p_pattern(self, p):
        """pattern : parameter
                   | type PATTERN_OPEN pattern_list_opt ')'
                   | parameter_modifiers type PATTERN_OPEN pattern_list_opt ')'"""
        if len(p) == 2:
            if p[1]["variadic"]:
                raise self.source.error(p.lexpos(1), "ellipsis is not allowed in a type pattern")
            p[0] = {"type": "TypePattern", "variable": p[1]}
        else:
            target = p[len(p)-4]
            if len(p) == 6:
                raise self.source.error(p.lexpos(1), "record pattern type cannot have modifiers or annotations")
            pending = [target]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    if value.get("annotations") or value.get("dimensionAnnotations"):
                        raise self.source.error(p.lexpos(1), "record pattern type cannot have annotations")
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
            p[0] = {"type": "RecordPattern", "recordType": target, "components": p[len(p)-2]}

    def p_pattern_list(self, p):
        """pattern_list_opt : empty
                            | pattern_list
           pattern_list : pattern
                        | pattern_list ',' pattern"""
        if p.slice[0].type == "pattern_list_opt":
            p[0] = p[1] or []
        elif len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_binary(self, p):
        """logical_or : logical_and %prec BODY_PROMOTION
                      | logical_or OR logical_and
           logical_and : bit_or %prec BODY_PROMOTION
                       | logical_and AND bit_or
           bit_or : bit_xor %prec BODY_PROMOTION
                  | bit_or '|' bit_xor
           bit_xor : bit_and %prec BODY_PROMOTION
                   | bit_xor '^' bit_and
           bit_and : equality %prec BODY_PROMOTION
                   | bit_and '&' equality
           equality : relation %prec BODY_PROMOTION
                    | equality EQ relation
           relation : shift %prec BODY_PROMOTION
                    | relation '<' shift
                    | relation '>' shift
                    | relation REL shift
           shift : additive %prec BODY_PROMOTION
                 | shift SHIFT additive
           additive : product %prec BODY_PROMOTION
                    | additive '+' product
                    | additive '-' product
           product : unary
                   | product '*' unary
                   | product '/' unary
                   | product '%' unary"""
        p[0] = p[1] if len(p) == 2 else {"type": "BinaryExpression", "operator": p[2], "left": p[1], "right": p[3]}

    def p_unary(self, p):
        """unary : postfix
                 | INC unary
                 | DEC unary
                 | '+' unary
                 | '-' unary
                 | '-' LIMIT_NUMBER
                 | '!' unary
                 | '~' unary"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            operand = {"type": "Literal", "raw": p[2]} if p.slice[2].type == "LIMIT_NUMBER" else p[2]
            p[0] = {"type": "UnaryExpression", "operator": p[1], "prefix": True, "operand": operand}

    def p_postfix(self, p):
        """postfix : name
                   | primary
                   | postfix INC
                   | postfix DEC"""
        if len(p) == 3:
            p[0] = {"type": "UnaryExpression", "operator": p[2], "prefix": False, "operand": p[1]}
        elif p.slice[1].type == "name":
            p[0] = {"type": "NameExpression", "name": p[1]}
        else:
            p[0] = p[1]

    def p_primary(self, p):
        """primary : NUMBER
                   | STRING
                   | TEXT_BLOCK
                   | CHARACTER
                   | TRUE
                   | FALSE
                   | NULL
                   | THIS
                   | '(' expression ')'
                   | name '(' arguments_opt ')'
                   | primary '.' IDENT
                   | primary '.' IDENT '(' arguments_opt ')'
                   | name '[' expression ']'
                   | primary '[' expression ']'
                   | new_class
                   | new_class '{' members '}'"""
        kind = p.slice[1].type
        if kind == "new_class":
            p[0] = p[1]
            if len(p) == 5:
                p[0]["members"] = p[3]
        elif len(p) == 2:
            p[0] = {"type": "ThisExpression"} if kind == "THIS" else {"type": "Literal", "raw": p[1]}
            if kind == "TEXT_BLOCK":
                p[0]["value"] = p.slice[1].decoded
        elif kind == "(":
            p[0] = {"type": "ParenthesizedExpression", "expression": p[2]}
        elif p[2] == "[":
            base = {"type": "NameExpression", "name": p[1]} if kind == "name" else p[1]
            p[0] = {"type": "ArrayAccess", "array": base, "index": p[3]}
        elif p[2] == "(":
            if p[1] == "yield":
                raise self.source.error(p.lexpos(1), "yield requires a receiver in a method invocation")
            p[0] = {"type": "MethodInvocation", "name": p[1], "receiver": None, "arguments": p[3]}
        elif len(p) == 4:
            p[0] = {"type": "MemberAccess", "receiver": p[1], "name": p[3]}
        else:
            p[0] = {"type": "MethodInvocation", "name": p[3], "receiver": p[1], "arguments": p[5]}

    def p_new_class(self, p):
        """new_class : new_start new_type '(' arguments_opt ')'
                     | new_start type_arguments new_type '(' arguments_opt ')'"""
        name, diamond = p[len(p)-4]
        p[0] = {"type": "NewClass", "name": name, "arguments": p[len(p)-2]}
        if diamond:
            p[0]["diamond"] = True
        if p[1] is not None:
            p[0]["qualifier"] = p[1]
        if len(p) == 7:
            p[0]["constructorTypeArguments"] = p[2]

    def p_new_type(self, p):
        """new_type : annotated_reference
                    | diamond_type
                    | type_annotations diamond_type"""
        if len(p) == 3:
            p[0] = (self.annotate_type(p[2], p[1]), True)
        else:
            p[0] = (p[1], p.slice[1].type == "diamond_type")

    def p_diamond_type(self, p):
        """diamond_type : name TYPE_OPEN TYPE_CLOSE
                        | name '.' type_annotations IDENT TYPE_OPEN TYPE_CLOSE
                        | parameterized '.' IDENT TYPE_OPEN TYPE_CLOSE
                        | parameterized '.' type_annotations IDENT TYPE_OPEN TYPE_CLOSE"""
        if len(p) == 4:
            p[0] = p[1]
            return
        if isinstance(p[1], str):
            segments = [{"name": name, "arguments": []} for name in p[1].split(".")]
            p[0] = {"type": "Type", "name": p[1], "segments": segments}
        else:
            p[0] = p[1]
        name = p[len(p)-3]
        segment = {"name": name, "arguments": []}
        if p.slice[3].type == "type_annotations":
            segment["annotations"] = p[3]
        p[0]["name"] += "." + name
        p[0]["segments"].append(segment)

    def p_new_start(self, p):
        """new_start : NEW
                     | name '.' NEW
                     | primary '.' NEW"""
        if len(p) == 2:
            p[0] = None
        elif p.slice[1].type == "name":
            p[0] = {"type": "NameExpression", "name": p[1]}
        else:
            p[0] = p[1]

    def p_new_array(self, p):
        """primary : new_start array_element_type new_dimensions
                   | new_start array_element_type new_dimensions array_initializer"""
        if p[1] is not None:
            raise self.source.error(p.lexpos(1), "array creation cannot have a receiver")
        sized = p[3][0]["size"] is not None
        initialized = len(p) == 5
        if sized == initialized:
            offset = p.lexpos(4) if initialized else p.lexpos(3)
            raise self.source.error(offset, "array creation requires size expressions or an initializer")
        p[0] = {"type": "NewArray", "elementType": p[2], "dimensions": p[3], "initializer": p[4] if initialized else None}

    def p_array_element_type(self, p):
        """array_element_type : PRIMITIVE
                              | type_annotations PRIMITIVE
                              | annotated_reference"""
        p[0] = p[1] if len(p) == 2 else self.annotate_type(p[2], p[1])

    def p_new_dimensions(self, p):
        """new_dimensions : new_dimension
                          | new_dimensions new_dimension"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            if p[1][-1]["size"] is None and p[2]["size"] is not None:
                raise self.source.error(p.lexpos(2), "sized array dimension after an empty dimension")
            p[1].append(p[2])
            p[0] = p[1]

    def p_new_dimension(self, p):
        """new_dimension : DIM
                         | SIZE_OPEN expression ']'
                         | type_annotations DIM
                         | type_annotations SIZE_OPEN expression ']'"""
        annotations = p[1] if p.slice[1].type == "type_annotations" else []
        size = p[len(p)-2] if p.slice[-1].type == "]" else None
        p[0] = {"type": "ArrayDimension", "size": size, "annotations": annotations}

    def p_class_literal(self, p):
        """primary : name '.' CLASS
                   | name nonempty_dims '.' CLASS
                   | PRIMITIVE dims '.' CLASS
                   | VOID '.' CLASS"""
        if p.slice[1].type == "name":
            self.check_named_type(p[1], p.lexpos(1))
        if getattr(p.slice[2], "dimension_annotations", None):
            raise self.source.error(p.lexpos(2), "array dimensions in class literals cannot be annotated")
        p[0] = {"type": "ClassLiteral", "name": p[1], "dimensions": p[2] if len(p) == 5 else 0}

    def p_explicit_invocation(self, p):
        """primary : name '.' type_arguments IDENT '(' arguments_opt ')'
                   | primary '.' type_arguments IDENT '(' arguments_opt ')'"""
        receiver = {"type": "NameExpression", "name": p[1]} if p.slice[1].type == "name" else p[1]
        p[0] = {"type": "MethodInvocation", "name": p[4], "receiver": receiver, "arguments": p[6], "typeArguments": p[3]}

    def p_qualified_this(self, p):
        "primary : name '.' THIS"
        p[0] = {"type": "ThisExpression", "qualifier": p[1]}

    def p_super_access(self, p):
        """primary : SUPER '.' IDENT
                   | SUPER '.' IDENT '(' arguments_opt ')'
                   | SUPER '.' type_arguments IDENT '(' arguments_opt ')'
                   | name '.' SUPER '.' IDENT
                   | name '.' SUPER '.' IDENT '(' arguments_opt ')'
                   | name '.' SUPER '.' type_arguments IDENT '(' arguments_opt ')'"""
        qualified = p.slice[1].type == "name"
        base = {"type": "SuperExpression"}
        if qualified:
            base["qualifier"] = p[1]
        i = 5 if qualified else 3
        explicit = p.slice[i].type == "type_arguments"
        ident = i + int(explicit)
        if len(p) == ident+1:
            p[0] = {"type": "MemberAccess", "name": p[ident], "receiver": base}
        else:
            p[0] = {"type": "MethodInvocation", "name": p[ident], "receiver": base, "arguments": p[ident+2]}
            if explicit:
                p[0]["typeArguments"] = p[i]

    def p_arguments_opt(self, p):
        """arguments_opt : empty
                         | arguments"""
        p[0] = p[1] or []
