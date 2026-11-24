"""Apply TypeScript binder diagnostics in their lexical strict-mode contexts."""


_FUNCTIONS = {"FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression", "TSDeclareFunction"}
_SIGNATURES = _FUNCTIONS | {
    "TSFunctionType", "TSConstructorType", "TSCallSignatureDeclaration", "TSConstructSignatureDeclaration",
    "TSMethodSignature", "TSIndexSignature", "JSDocFunctionType",
}


def diagnose(owner, identifier, code):
    offset = identifier.get("_strictNameOffset") if identifier else None
    if offset is not None:
        owner.setdefault("diagnostics", []).append({
            "code": code, "offset": offset, "message": f"invalid use of '{identifier['name']}' in strict mode"})


def check_binding(owner, binding, code, ambient_parameter=False):
    if not binding:
        return
    kind = binding["type"]
    if kind == "Identifier":
        if not ambient_parameter:
            diagnose(owner, binding, code)
    elif kind in {"RestElement", "AssignmentPattern"}:
        target = binding["argument"] if kind == "RestElement" else binding["left"]
        check_binding(owner, target, code, ambient_parameter)
    elif kind == "ArrayPattern":
        for element in binding["elements"]:
            if element:
                check_binding(element, element, code)
    elif kind == "ObjectPattern":
        for prop in binding["properties"]:
            check_binding(prop, prop.get("value", prop), code)


def check_strict_diagnostics(grammar, body):
    module = grammar.source_type == "module"
    strict = module or grammar.always_strict or grammar.strict_directive(body)
    pending = [(body, strict, False, grammar.declaration_file)]
    marked = []
    while pending:
        node, strict, in_class, ambient = pending.pop()
        if isinstance(node, list):
            pending.extend((item, strict, in_class, ambient) for item in node)
            continue
        if not isinstance(node, dict):
            continue
        if "_strictNameOffset" in node:
            marked.append(node)
        kind = node.get("type")
        in_class = in_class or kind in {"ClassDeclaration", "ClassExpression"}
        ambient = ambient or node.get("declare", False)
        strict = strict or in_class or (kind == "TSModuleBlock" and grammar.strict_directive(node["body"]))
        statement_diagnostic = node.pop("_strictDiagnostic", None)
        if strict:
            if statement_diagnostic:
                node.setdefault("diagnostics", []).append(statement_diagnostic)
            code = 1210 if in_class else 1215 if module else 1100
            if kind == "VariableDeclarator":
                check_binding(node, node["id"], code)
            elif kind == "CatchClause":
                check_binding(node, node["param"], code)
            elif kind in _SIGNATURES:
                if not ambient and kind in _FUNCTIONS:
                    diagnose(node, node.get("id"), code)
                for param in node.get("params", node.get("parameters", [])):
                    check_binding(param, param, code, ambient_parameter=ambient)
            elif kind in {"UpdateExpression", "AssignmentExpression"}:
                target = node["argument"] if kind == "UpdateExpression" else node["left"]
                if id(target) not in grammar.grouped_patterns:
                    diagnose(node, target, code)

        # A function's directive takes effect when binding its body. Its name
        # and parameters are bound in the surrounding strict-mode context.
        for key, child in node.items():
            child_strict = strict
            if (not strict and key == "body" and (kind in _FUNCTIONS or kind == "TSMethodSignature")
                    and child and child["type"] == "BlockStatement"):
                child_strict = grammar.strict_directive(child["body"])
            if isinstance(child, (dict, list)):
                pending.append((child, child_strict, in_class, ambient))
    # Grammar actions can copy identifiers when adding annotations, and
    # shorthand properties share key/value nodes. Clean up after all uses.
    for node in marked:
        node.pop("_strictNameOffset", None)
