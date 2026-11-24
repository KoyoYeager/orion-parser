"""Lexical and var declaration early errors for ECMAScript statement lists."""
from .bindings import bound_names


def declarations(stmt):
    while stmt["type"] == "LabeledStatement":
        stmt = stmt["body"]
    kind = stmt["type"]
    if kind in {"ExportDefaultDeclaration", "ExportNamedDeclaration"}:
        inner = stmt["declaration"]
        if inner:
            yield from declarations(inner)
    elif kind == "VariableDeclaration":
        for item in stmt["declarations"]:
            for name in bound_names(item["id"]):
                yield name, stmt["kind"], stmt
    elif kind in {"FunctionDeclaration", "ClassDeclaration"} and stmt["id"]:
        tag = "class" if kind == "ClassDeclaration" else "hoistable"
        if tag == "hoistable" and not stmt["async"] and not stmt["generator"]:
            tag = "function"
        yield stmt["id"]["name"], tag, stmt
    elif kind == "ImportDeclaration":
        for spec in stmt["specifiers"]:
            yield spec["local"]["name"], "import", stmt


def lexical_scope(grammar, statements, *, block, catch_names=()):
    lexical = {}
    var_functions = set()
    for stmt in statements:
        for name, kind, decl in declarations(stmt):
            if kind == "class" and (decl.get("declare") or getattr(grammar, "declaration_file", False)):
                kind = "ambient class"
            if kind == "var":
                continue
            offset = grammar.decl_offsets[id(decl)]
            if not block and kind in {"function", "hoistable"}:
                if name in lexical and lexical[name] != "ambient class":
                    raise grammar.error(offset, "function conflicts with lexical declaration " + name)
                var_functions.add(name)
                continue
            if name in var_functions and kind != "ambient class":
                raise grammar.error(offset, "lexical binding conflicts with function " + name)
            if name in catch_names:
                raise grammar.error(offset, "lexical declaration shadows catch binding " + name)
            if name in lexical:
                if kind in {"function", "hoistable"} and lexical[name] == "ambient class":
                    continue
                if kind == "ambient class" and lexical[name] in {"function", "hoistable"}:
                    lexical[name] = kind
                    continue
                if block and kind == lexical[name] == "function":
                    grammar.strict_violation(offset, "duplicate block function " + name)
                else:
                    raise grammar.error(offset, "duplicate lexical binding " + name)
            lexical[name] = kind
    return frozenset(lexical)


def validate_scopes(grammar, body):
    # var declarations reach every containing statement-list scope until the
    # nearest function, class static block, or program boundary.
    root = lexical_scope(grammar, body, block=grammar.source_type == "module")
    pending = [(body, root)]
    while pending:
        node, lexical = pending.pop()
        if isinstance(node, list):
            pending.extend((child, lexical) for child in node)
            continue
        if not isinstance(node, dict):
            continue
        kind = node.get("type")
        if kind in {"FunctionExpression", "FunctionDeclaration", "ArrowFunctionExpression"}:
            pending.append((node["params"], frozenset()))
            function_body = node["body"]
            if function_body["type"] == "BlockStatement":
                statements = function_body["body"]
                pending.append((statements, lexical_scope(grammar, statements, block=False)))
            else:
                pending.append((function_body, frozenset()))
            continue
        if kind == "BlockStatement":
            lexical = lexical | lexical_scope(grammar, node["body"], block=True)
        elif kind in {"StaticBlock", "TSModuleBlock"}:
            lexical = lexical_scope(grammar, node["body"], block=True)
        elif kind == "SwitchStatement":
            statements = [stmt for case in node["cases"] for stmt in case["consequent"]]
            lexical = lexical | lexical_scope(grammar, statements, block=True)
        elif kind == "CatchClause":
            binding = node["param"]
            names = set(bound_names(binding)) if binding else set()
            statements = node["body"]["body"]
            inner = lexical | lexical_scope(grammar, statements, block=True, catch_names=names)
            if binding and binding["type"] != "Identifier":
                inner |= names
            pending.extend(((binding, lexical), (statements, inner)))
            continue
        elif kind == "VariableDeclaration" and node["kind"] == "var":
            for item in node["declarations"]:
                for name in bound_names(item["id"]):
                    if name in lexical:
                        raise grammar.error(grammar.decl_offsets[id(node)], "var conflicts with lexical binding " + name)
        pending.extend((child, lexical) for child in node.values() if isinstance(child, (dict, list)))
