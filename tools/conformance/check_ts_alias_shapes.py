"""Compare nested type aliases, import types, or index signatures with the pinned compiler AST."""
import argparse
from pathlib import Path

from check_typescript import _STATEMENT_SHAPE, COMPILER_SHA, SOURCE_SHA, TypeScriptPipeline, check_pin, run_compiler, source_cases, statement_shape


def key(n):
    kind = n["type"]
    if kind in {"ArrayPattern", "ArrayExpression"}:
        return [kind, [key(e) if e else None for e in n["elements"]]]
    if kind in {"ObjectPattern", "ObjectExpression"}:
        return [kind, [key(e) for e in n["properties"]]]
    if kind == "Property":
        name = ["computed", operand(n["key"])] if n["computed"] else key(n["key"])
        return ["property", name, key(n["value"])]
    if kind == "RestElement":
        return ["rest", key(n["argument"])]
    if kind == "AssignmentPattern":
        return ["default", key(n["left"]), operand(n["right"])]
    if kind == "TSThisType":
        return ["id", "this"]
    if kind == "MemberExpression" and not n["computed"]:
        return ["access", key(n["object"]), key(n["property"])]
    if kind in {"AssignmentExpression", "BinaryExpression"}:
        return ["binary", n["operator"], key(n["left"]), key(n["right"])]
    if kind == "PrivateIdentifier":
        return ["private", n["name"]]
    if kind == "Identifier":
        return ["id", n["name"]]
    if kind == "TSQualifiedName":
        return ["qualified", key(n["left"]), key(n["right"])]
    if kind == "Literal" and isinstance(n["value"], str):
        return ["string", n["value"]]
    if kind in {"NumericLiteral", "BigIntLiteral"}:
        return ["number" if kind == "NumericLiteral" else "bigint", n["raw"]]
    raise ValueError("unmapped name: " + kind)


def params(n):
    records = []
    for p in (n.get("typeParameters") or {}).get("params", []):
        record = [p["name"]["name"], p.get("modifiers", []), typ(p.get("constraint")), typ(p.get("default"))]
        if "expression" in p:
            record.append(operand(p["expression"]))
        records.append(record)
    return records


def signature(n):
    return [params(n), [parameter(p) for p in n["params"]], typ(n.get("returnType"))]


def parameter(p):
    rest = p["type"] == "RestElement"
    binding = p["argument"] if rest else p
    initial = None
    if binding["type"] == "AssignmentPattern":
        initial = operand(binding["right"])
        binding = binding["left"]
    modifiers = p.get("modifiers", [])
    decorators = [[d.get("modifierIndex", 0), operand(d["expression"])] for d in p.get("decorators", [])]
    return [key(binding), bool(binding.get("optional")), rest, typ(binding.get("typeAnnotation")), modifiers, initial, decorators]


def member(n):
    kind = n["type"]
    if kind == "TSIndexSignature":
        return ["indexSignature", bool(n.get("readonly")), bool(n.get("static")),
                [parameter(p) for p in n["parameters"]], typ(n.get("typeAnnotation"))]
    if kind in {"TSPropertySignature", "TSMethodSignature"}:
        if n["computed"] and kind == "TSPropertySignature":
            name = ["computed", operand(n["key"])]
        else:
            name = key(n["key"])
            if n["computed"]:
                name = ["computed", name]
    if kind == "TSPropertySignature":
        tree = ["property", name, bool(n["optional"]), bool(n["readonly"]), typ(n.get("typeAnnotation"))]
        if "initializer" in n:
            tree.append(operand(n["initializer"]))
        return tree
    if kind == "TSMethodSignature":
        if n.get("kind") in {"get", "set"}:
            return [n["kind"], name, *signature(n)]
        return ["method", name, bool(n["optional"]), *signature(n)]
    if kind in {"TSConstructSignatureDeclaration", "TSCallSignatureDeclaration"}:
        return ["construct" if kind == "TSConstructSignatureDeclaration" else "call", *signature(n)]
    raise ValueError("unmapped member: " + kind)


def typ(n):
    if n is None:
        return None
    k = n["type"]
    if k == "JSDocNamepathType":
        return [k, n["text"]]
    if k in {"JSDocAllType", "JSDocUnknownType"}:
        return [k]
    if k in {"JSDocNullableType", "JSDocNonNullableType"}:
        return [k, n["postfix"], typ(n["typeAnnotation"])]
    if k in {"JSDocVariadicType", "JSDocOptionalType"}:
        return [k, typ(n["typeAnnotation"])]
    if k == "JSDocFunctionType":
        return [k, [[p["name"]["name"] if p["name"] else None, typ(p["typeAnnotation"])] for p in n["params"]],
                typ(n["returnType"])]
    if k == "TSThisType":
        return ["this"]
    if k == "TSTypePredicate":
        return ["predicate", n["asserts"], key(n["parameterName"]), typ(n.get("typeAnnotation"))]
    if k == "TSConditionalType":
        return ["conditional", *(typ(n[f]) for f in ("checkType", "extendsType", "trueType", "falseType"))]
    if k == "TSInferType":
        param = n["typeParameter"]
        return ["infer", param["name"]["name"], typ(param.get("constraint"))]
    if k == "TSTypeOperator":
        return ["operator", n["operator"], typ(n["typeAnnotation"])]
    if k == "TSIndexedAccessType":
        return ["index", typ(n["objectType"]), typ(n["indexType"])]
    if k in {"TSRestType", "TSOptionalType"}:
        return ["rest" if k == "TSRestType" else "optional", typ(n["typeAnnotation"])]
    if k == "TSNamedTupleMember":
        return ["named", key(n["label"]), n["optional"], typ(n["elementType"])]
    if k == "TSMappedType":
        return ["mapped", key(n["key"]), typ(n["constraint"]), typ(n["nameType"]), n["readonly"],
                n["optional"], typ(n["typeAnnotation"]), [member(m) for m in n.get("members", [])]]
    if k.endswith("Keyword"):
        return ["keyword", k[2:-7].lower()]
    if k == "TSTypeAnnotation":
        return typ(n["typeAnnotation"])
    if k == "TSImportType" or (k == "TSTypeQuery" and n["exprName"]["type"] == "TSImportType"):
        imported = n["exprName"] if k == "TSTypeQuery" else n
        arg = imported["argument"]
        options = None
        if "attributes" in imported:
            options = [imported["attributeKeyword"], [[key(a["key"]), key(a["value"])] for a in imported["attributes"]]]
        return ["import", k == "TSTypeQuery", key(arg) if arg["type"] == "Literal" else typ(arg), options,
                key(imported["qualifier"]) if imported["qualifier"] else None,
                [typ(p) for p in (imported["typeArguments"] or {}).get("params", [])]]
    if k in {"TSTypeReference", "TSTypeQuery"}:
        ref = k == "TSTypeReference"
        return ["ref" if ref else "typeof", key(n["typeName" if ref else "exprName"]),
                [typ(p) for p in (n.get("typeArguments") or {}).get("params", [])]]
    if k == "TSArrayType":
        return ["array", typ(n["elementType"])]
    if k == "TSTupleType":
        return ["tuple", [typ(x) for x in n["elementTypes"]]]
    if k == "TSParenthesizedType":
        return ["group", typ(n["typeAnnotation"])]
    if k in {"TSUnionType", "TSIntersectionType"}:
        return ["union" if k == "TSUnionType" else "intersection", [typ(x) for x in n["types"]]]
    if k == "TSTypeLiteral":
        return ["object", [member(m) for m in n["members"]]]
    if k in {"TSFunctionType", "TSConstructorType"}:
        return ["function" if k == "TSFunctionType" else "constructor", *signature(n)]
    if k == "TSTemplateLiteralType":
        return ["template", [s["value"]["cooked"] for s in n["quasis"]], [typ(t) for t in n["types"]]]
    if k == "TSLiteralType":
        lit = n["literal"]
        if isinstance(lit.get("value"), bool):
            return ["boolean", lit["value"]]
        if lit["type"] == "UnaryExpression":
            return ["prefix", lit["operator"], key(lit["argument"])]
        return key(lit)
    raise ValueError("unmapped type: " + k)


def marked_property(n):
    name = key(n["key"])
    name = ["computed", name] if n["computed"] else name
    value = n["value"]
    if n["method"]:
        payload = ["method", value["async"], value["generator"], signature(value)]
    elif n["shorthand"]:
        initial = value["right"] if value["type"] in {"AssignmentExpression", "AssignmentPattern"} else None
        payload = ["shorthand", key(initial) if initial else None]
    else:
        payload = ["assignment", key(value)]
    return [name, bool(n.get("optional")), bool(n.get("definite")), payload]


def private_shape(n):
    kind = n.get("type")
    if kind == "PrivateIdentifier":
        return ["private", n["name"]]
    if kind == "TSEnumMember" and n["id"]["type"] == "PrivateIdentifier":
        return ["enum", n["id"]["name"]]
    for field in ("key", "property", "left"):
        child = n.get(field)
        if isinstance(child, dict) and child.get("type") == "PrivateIdentifier":
            if kind in {"BinaryExpression", "AssignmentExpression"}:
                return ["left", n["operator"], child["name"]]
            if kind == "MemberExpression":
                return ["access", child["name"]]
            if field == "key":
                record = [kind, n.get("kind"), bool(n.get("static")), child["name"]]
                if kind == "MethodDefinition":
                    value = n["value"]
                    record.extend([bool(value.get("async")), bool(value.get("generator")), value.get("body") is not None])
                return record
    return None


def binding_names(binding):
    kind = binding["type"]
    if kind == "Identifier":
        return binding["name"]
    if kind == "RestElement":
        return ["rest", binding_names(binding["argument"])]
    if kind == "AssignmentPattern":
        return ["default", binding_names(binding["left"])]
    if kind == "ArrayPattern":
        return ["array", [binding_names(e) if e else None for e in binding["elements"]]]
    if kind == "ObjectPattern":
        return ["object", [binding_names(p["value"] if p["type"] == "Property" else p) for p in binding["properties"]]]
    raise ValueError("unmapped binding: " + kind)


def module_bindings(n):
    kind = n.get("type")
    if kind == "ImportDeclaration":
        specs = []
        for spec in n["specifiers"]:
            local = key(spec["local"])
            if spec["type"] == "ImportDefaultSpecifier":
                specs.append(["default", local])
            elif spec["type"] == "ImportNamespaceSpecifier":
                specs.append(["namespace", local])
            else:
                specs.append(["named", key(spec["imported"]), local, spec.get("importKind") == "type"])
        return ["import", operand(n["source"]), n.get("importKind") == "type", specs, n.get("phase")]
    if kind == "TSImportEqualsDeclaration":
        ref = n["moduleReference"]
        target = ["external", operand(ref["expression"])] if ref["type"] == "TSExternalModuleReference" else key(ref)
        return ["alias", key(n["id"]), n.get("importKind") == "type", target]
    if kind == "ExportAllDeclaration":
        return ["star", operand(n["source"]), n.get("exportKind") == "type", key(n["exported"]) if n["exported"] else None]
    if kind == "ExportNamedDeclaration" and not n["declaration"]:
        return ["export", operand(n["source"]) if n["source"] else None, n.get("exportKind") == "type",
                [[key(s["local"]), key(s["exported"]), s.get("exportKind") == "type"] for s in n["specifiers"]]]
    return None


def jsx_tree(n):
    kind = n["type"]
    if kind == "JSXElement":
        opening = n["openingElement"]
        arguments = opening.get("typeArguments")
        closing = n["closingElement"]
        return ["element", jsx_tree(opening["name"]), opening["selfClosing"],
                [typ(t) for t in arguments["params"]] if arguments else None,
                [jsx_tree(a) for a in opening["attributes"]], [jsx_tree(c) for c in n["children"]],
                jsx_tree(closing["name"]) if closing else None]
    if kind == "JSXFragment":
        return ["fragment", [jsx_tree(c) for c in n["children"]]]
    if kind == "JSXIdentifier":
        return ["id", n["name"]]
    if kind == "JSXNamespacedName":
        return ["namespace", jsx_tree(n["namespace"]), jsx_tree(n["name"])]
    if kind == "JSXMemberExpression":
        return ["member", jsx_tree(n["object"]), jsx_tree(n["property"])]
    if kind == "JSXSpreadAttribute":
        return ["spread attribute", operand(n["argument"])]
    if kind == "JSXAttribute":
        return ["attribute", jsx_tree(n["name"]), jsx_tree(n["value"]) if n["value"] else None]
    if kind == "JSXExpressionContainer":
        expr = n["expression"]
        return ["container", None if expr["type"] == "JSXEmptyExpression" else operand(expr)]
    if kind == "JSXSpreadChild":
        return ["spread child", operand(n["expression"])]
    if kind == "JSXText":
        return ["text", n["value"]]
    return operand(n)


def operand(n):
    kind = n["type"]
    if kind in {"JSXElement", "JSXFragment"}:
        return jsx_tree(n)
    if kind == "ChainExpression":
        return operand(n["expression"])
    if kind == "MemberExpression":
        return ["index" if n["computed"] else "access", "optional" in n, bool(n.get("optional")), operand(n["object"]), operand(n["property"])]
    if kind in {"CallExpression", "NewExpression"}:
        shape = ["call" if kind == "CallExpression" else "new", "optional" in n, bool(n.get("optional")), operand(n["callee"]),
                 [typ(t) for t in (n.get("typeArguments") or {}).get("params", [])], [operand(a) for a in n["arguments"]]]
        if kind == "NewExpression":
            shape.append(n["hasArgumentList"])
        shape.append(bool(n.get("trailingComma")))
        return shape
    if kind == "TemplateLiteral":
        return ["template", [q["value"]["cooked"] for q in n["quasis"]], [operand(e) for e in n["expressions"]]]
    if kind == "TaggedTemplateExpression":
        quasi = n["quasi"]
        return ["tag", "optional" in n, bool(n.get("optional")), operand(n["tag"]),
                [typ(t) for t in (n.get("typeArguments") or {}).get("params", [])],
                [q["value"]["cooked"] for q in quasi["quasis"]], [operand(e) for e in quasi["expressions"]]]
    if kind == "TSInstantiationExpression":
        return ["instantiation", operand(n["expression"]), [typ(t) for t in n["typeArguments"]["params"]]]
    if kind == "TSNonNullExpression":
        return ["nonNull", "optional" in n, operand(n["expression"])]
    if kind in {"TSAsExpression", "TSSatisfiesExpression", "TSTypeAssertion"}:
        return [kind, operand(n["expression"]), typ(n["typeAnnotation"])]
    if kind == "SequenceExpression":
        first, *tail = n["expressions"]
        tree = operand(first)
        for e in tail:
            tree = ["binary", ",", tree, operand(e)]
        return tree
    if kind in {"AssignmentPattern", "AssignmentExpression", "BinaryExpression", "LogicalExpression"}:
        return ["binary", n.get("operator", "="), operand(n["left"]), operand(n["right"])]
    if kind in {"UnaryExpression", "UpdateExpression"}:
        return ["unary", n["operator"], n["prefix"], operand(n["argument"])]
    if kind in {"ThisExpression", "Super"}:
        return ["keyword", "this" if kind == "ThisExpression" else "super"]
    if kind in {"ArrayExpression", "ArrayPattern"}:
        return ["array", [operand(e) if e else None for e in n["elements"]]]
    if kind in {"ObjectExpression", "ObjectPattern"}:
        return ["object", [operand(v) for v in n["properties"]]]
    if kind == "RegExpLiteral":
        return ["regexp", n["pattern"], n["flags"]]
    if kind == "Property" and (n.get("method") or n.get("kind") in {"get", "set"}):
        fn = n["value"]
        return ["method", n["kind"], n["computed"], operand(n["key"]), signature(fn), fn.get("body") is not None]
    if kind == "Property":
        return ["prop", n["computed"], operand(n["key"]), operand(n["value"])]
    if kind in {"SpreadElement", "RestElement"}:
        return ["spread", operand(n["argument"])]
    if kind == "ClassExpression":
        members = [[m.get("kind", m["type"]), bool(m.get("static")), bool(m.get("computed")),
                    operand(m["key"]) if m.get("key") and m.get("kind") != "constructor" else None]
                   for m in n["body"]["body"]]
        return ["class", heritage_record(n), params(n), members]
    if kind == "ImportExpression":
        args = [n.get("source"), n.get("options"), *n.get("extraArguments", [])]
        return ["import", n.get("phase"), "optional" in n, bool(n.get("optional")), [typ(t) for t in (n.get("typeArguments") or {}).get("params", [])],
                [operand(arg) for arg in args if arg], bool(n.get("trailingComma"))]
    if kind == "TSImportKeyword":
        return ["keyword", "import"]
    if kind in {"ArrowFunctionExpression", "FunctionExpression"}:
        body = n["body"]
        content = [statement_shape(stmt) for stmt in body["body"]] if body["type"] == "BlockStatement" else operand(body)
        return ["arrow" if kind == "ArrowFunctionExpression" else "function", n["async"], n["generator"], signature(n), content]
    if kind == "ConditionalExpression":
        return ["conditional", operand(n["test"]), operand(n["consequent"]), operand(n["alternate"])]
    if kind == "Literal" and not isinstance(n["value"], str):
        return ["literal", n["value"]]
    if kind == "YieldExpression":
        return ["yield", n["delegate"], operand(n["argument"]) if n["argument"] else None]
    if kind == "AwaitExpression":
        return ["await", operand(n["argument"])]
    if kind == "MetaProperty":
        return ["meta", n["meta"]["name"], n["property"]["name"]]
    return key(n)


def expression_pattern_defaults(pattern):
    """Find binary assignments reinterpreted as defaults on a destructuring target."""
    if not pattern:
        return
    kind = pattern["type"]
    if kind == "AssignmentPattern":
        yield id(pattern)
        yield from expression_pattern_defaults(pattern["left"])
    elif kind == "RestElement":
        yield from expression_pattern_defaults(pattern["argument"])
    elif kind == "ArrayPattern":
        for element in pattern["elements"]:
            yield from expression_pattern_defaults(element)
    elif kind == "ObjectPattern":
        for prop in pattern["properties"]:
            if prop["type"] == "RestElement":
                yield from expression_pattern_defaults(prop["argument"])
            elif not prop.get("shorthand"):
                yield from expression_pattern_defaults(prop["value"])


def rest_bindings(pattern):
    if not pattern:
        return
    kind = pattern.get("type")
    if kind in {"RestElement", "AssignmentPattern"}:
        yield from rest_bindings(pattern.get("argument") or pattern["left"])
    if kind not in {"ArrayPattern", "ObjectPattern"}:
        return
    elements = pattern["elements"] if kind == "ArrayPattern" else pattern["properties"]
    for index, element in enumerate(elements):
        if element is None:
            continue
        if element["type"] == "RestElement":
            target = element["argument"]
            initial = target["right"] if target["type"] == "AssignmentPattern" else None
            name = target["left"] if initial else target
            yield [kind, index, len(elements), bool(pattern.get("trailingComma")), bool(element.get("computed")),
                   operand(element["propertyName"]) if element.get("propertyName") else None,
                   binding_names(name), operand(initial) if initial else None]
        yield from rest_bindings(element["value"] if element["type"] == "Property" else element)


def heritage_name(n):
    if n["type"] == "TSQualifiedName":
        return ["access", False, False, heritage_name(n["left"]), operand(n["right"])]
    return operand(n)


def heritage_entry(expr, args):
    types = None if args is None else [[typ(t) for t in args["params"]], bool(args.get("trailingComma"))]
    return [expr, types]


def heritage_record(n):
    interface = n["type"] == "TSInterfaceDeclaration"
    clauses = []

    def entry(t):
        expr = heritage_name(t["typeName"]) if t["type"] == "TSTypeReference" else operand(t["expression"])
        return heritage_entry(expr, t.get("typeArguments"))

    if "heritageClauses" in n:
        for clause in n["heritageClauses"]:
            clauses.append([clause["kind"], clause["trailingComma"], [entry(t) for t in clause["types"]]])
    else:
        if not interface and n["superClass"]:
            clauses.append(["extends", False, [heritage_entry(operand(n["superClass"]), n.get("superTypeArguments"))]])
        kind = "extends" if interface else "implements"
        if n[kind]:
            clauses.append([kind, False, [entry(t) for t in n[kind]]])
    return ["interface" if interface else "class", n["id"]["name"] if n["id"] else None, clauses]


def type_list_owner(kind):
    if kind in {"ClassDeclaration", "ClassExpression"}:
        return "class"
    if kind in {"FunctionDeclaration", "FunctionExpression", "TSDeclareFunction", "ArrowFunctionExpression",
                "TSFunctionType", "TSConstructorType", "TSMethodSignature", "TSCallSignatureDeclaration",
                "TSConstructSignatureDeclaration"}:
        return "signature"
    return {"TSInterfaceDeclaration": "interface", "TSTypeAliasDeclaration": "alias", "TSTypeReference": "reference",
            "TSTypeQuery": "query", "TSInstantiationExpression": "instantiation", "ImportExpression": "call",
            "CallExpression": "call", "NewExpression": "new", "TaggedTemplateExpression": "tag",
            "TSImportType": "import type", "JSXOpeningElement": "jsx"}.get(kind, kind)


def declaration_modifiers(n, wrapped):
    kind = n["type"]
    target = n
    prefix = []
    if kind in {"ExportNamedDeclaration", "ExportDefaultDeclaration"}:
        inner = n.get("declaration") or {}
        if inner.get("type", "").endswith("Declaration") or inner.get("type") == "TSDeclareFunction":
            target = inner
            wrapped.add(id(inner))
            prefix = ["export", "default"] if kind == "ExportDefaultDeclaration" else ["export"]
    elif id(n) in wrapped or kind not in {
        "ClassDeclaration", "FunctionDeclaration", "TSDeclareFunction", "VariableDeclaration", "TSModuleDeclaration",
        "TSInterfaceDeclaration", "TSTypeAliasDeclaration", "TSEnumDeclaration", "ImportDeclaration",
        "TSImportEqualsDeclaration", "ExportAllDeclaration", "TSExportAssignment", "TSNamespaceExportDeclaration",
    }:
        return None
    mods = list(target.get("modifiers", prefix + [m for m in ("declare", "abstract", "async", "const") if target.get(m)]))
    for decorator in reversed(target.get("decorators", [])):
        mods.insert(decorator.get("modifierIndex", 0), ["decorator", operand(decorator["expression"])])
    return [*statement_shape(n), mods] if mods else None


def branch_statement(node):
    kind = node["type"]
    decl = node.get("declaration") if kind in {"ExportNamedDeclaration", "ExportDefaultDeclaration"} else node
    if decl and decl["type"] in {"TSTypeAliasDeclaration", "TSInterfaceDeclaration"}:
        record = declaration_modifiers(node, set())
        mods = record[-1] if record else []
        if decl["type"] == "TSInterfaceDeclaration":
            return [decl["type"], key(decl["id"]) if decl.get("id") else None,
                    [member(m) for m in decl["body"]["body"]], mods]
        return [decl["type"], key(decl["id"]), params(decl), typ(decl["typeAnnotation"]), mods]
    if kind in {"FunctionDeclaration", "TSDeclareFunction"}:
        return ["function", key(node["id"]) if node.get("id") else None, signature(node),
                branch_statement(node["body"]) if node.get("body") else None]
    if kind == "VariableDeclaration":
        return [kind, node["kind"], [[binding_names(d["id"]), operand(d["init"]) if d.get("init") else None]
                                     for d in node["declarations"]]]
    if kind == "ClassDeclaration":
        return [kind, key(node["id"]) if node["id"] else None, [[m["kind"],
                ["computed", operand(m["key"])] if m["computed"] else key(m["key"]),
                branch_statement(m["value"]["body"]) if m["value"].get("body") else None]
                for m in node["body"]["body"] if m["type"] == "MethodDefinition"]]
    if kind == "LabeledStatement":
        return [kind, key(node["label"]), branch_statement(node["body"])]
    if kind == "TSExportAssignment":
        return ["export assignment", True, operand(node["expression"])]
    if kind == "ExportDefaultDeclaration":
        return ["export assignment", False, operand(node["declaration"])]
    if kind == "TSNamespaceExportDeclaration":
        return [kind, key(node["id"])]
    if kind in {"EmptyStatement", "DebuggerStatement"}:
        return [kind]
    binding = module_bindings(node)
    if binding is not None:
        return binding
    if kind == "ThrowStatement":
        return [kind, operand(node["argument"]) if node["argument"] else None]
    if kind in {"ForStatement", "ForOfStatement", "ForInStatement"}:
        init = node.get("init") if kind == "ForStatement" else node["left"]
        target = None
        if init:
            target = branch_statement(init) if init["type"] == "VariableDeclaration" else operand(init)
        if kind == "ForStatement":
            return [kind, target, operand(node["test"]) if node["test"] else None,
                    operand(node["update"]) if node["update"] else None, branch_statement(node["body"])]
        return [kind, bool(node.get("await")), target, operand(node["right"]), branch_statement(node["body"])]
    if kind in {"WhileStatement", "DoWhileStatement"}:
        return [kind, operand(node["test"]), branch_statement(node["body"])]
    if kind == "WithStatement":
        return [kind, operand(node["object"]), branch_statement(node["body"])]
    if kind == "TSModuleDeclaration":
        return [kind, key(node["id"]), branch_statement(node["body"]) if node["body"] else None]
    if kind == "TSModuleBlock":
        return [kind, [branch_statement(child) for child in node["body"]]]
    if kind == "TSEnumDeclaration":
        return [kind, key(node["id"]), [[key(m["id"]), operand(m["initializer"]) if m["initializer"] else None]
                                       for m in node["members"]]]
    if kind == "TryStatement":
        handler = node["handler"]
        catch = None
        if handler:
            param = handler["param"]
            catch = [binding_names(param) if param else None, typ(param.get("typeAnnotation")) if param else None,
                     operand(handler["initializer"]) if "initializer" in handler else None, branch_statement(handler["body"])]
        return [kind, branch_statement(node["block"]), catch, branch_statement(node["finalizer"]) if node["finalizer"] else None]
    if kind == "SwitchStatement":
        return [kind, operand(node["discriminant"]), [
            [operand(c["test"]) if c["test"] else None, [branch_statement(stmt) for stmt in c["consequent"]]]
            for c in node["cases"]]]
    if kind in {"BreakStatement", "ContinueStatement"}:
        return [kind, node["label"]["name"] if node["label"] else None]
    if kind == "IfStatement":
        alternate = node["alternate"]
        return [kind, operand(node["test"]), branch_statement(node["consequent"]), branch_statement(alternate) if alternate else None]
    if kind == "BlockStatement":
        return [kind, [branch_statement(child) for child in node["body"]]]
    if kind == "ReturnStatement":
        return [kind, operand(node["argument"]) if node["argument"] else None]
    if kind == "ExpressionStatement":
        return [kind, operand(node["expression"])]
    raise ValueError("unmapped branch statement: " + kind)


def project_trees(root, label):
    if label in {"file context", "implied file context"}:
        return [[root["sourceType"], root["scriptKind"], root["declarationFile"],
                 [branch_statement(stmt) for stmt in root["body"]]]]
    if label in {"import grammar", "import diagnostics"}:
        diagnostics, pending = [], [root]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                if node.get("type") == "ImportExpression":
                    diagnostics.extend([d["code"], d["offset"], d["length"]] for d in node.get("diagnostics", []))
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        diagnostics.sort(key=lambda d: (d[1], d[0]))
        return diagnostics if label == "import diagnostics" else [[[branch_statement(s) for s in root["body"]], diagnostics]]
    if label in {"function grammar", "parameter diagnostics", "generic diagnostics"}:
        diagnostics, pending = [], [root]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                for diagnostic in node.get("diagnostics", []):
                    code = diagnostic.get("code")
                    parameter = code in {1013, 1014, 1015, 1016, 1017, 1018, 1019, 1020, 1021, 1022, 1025, 1047, 1048, 1096}
                    generic = node.get("type") != "ImportExpression" and code in {1009, 1097, 1098, 1099, 1172, 1173, 1174, 1175, 1176, 1326}
                    if ((parameter and label != "generic diagnostics") or (generic and label != "parameter diagnostics")
                            or (label == "function grammar" and code in {1200, 1346, 1347, 7060})):
                        row = [code, diagnostic["offset"]]
                        if code not in {1346, 1347, 7060}:
                            row.append(diagnostic["length"])
                        if label == "function grammar":
                            row.append([[d["code"], d["offset"]] for d in diagnostic.get("relatedInformation", [])])
                        diagnostics.append(row)
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        diagnostics.sort(key=lambda d: (d[1], d[0]))
        if label in {"parameter diagnostics", "generic diagnostics"}:
            return diagnostics
        return [[[branch_statement(stmt) for stmt in root["body"]], diagnostics]]
    if label == "resource statements":
        result = []
        for stmt in root["body"]:
            decl = stmt.get("declaration") if stmt["type"] == "ExportNamedDeclaration" else stmt
            modifiers = declaration_modifiers(stmt, set()) if decl and decl["type"] == "VariableDeclaration" else None
            result.append([branch_statement(decl or stmt), modifiers[-1] if modifiers else []])
        return result
    if label == "function source":
        records = []
        for node in root["body"]:
            if node["type"] in {"ExportNamedDeclaration", "ExportDefaultDeclaration"}:
                node = node["declaration"]
            if node["type"] == "VariableDeclaration":
                node = node["declarations"][0]["init"]
            body = node.get("body")
            records.append(["expression" if node["type"] == "FunctionExpression" else "declaration",
                            node["id"]["name"] if node.get("id") else None, bool(node.get("async")),
                            bool(node.get("generator")), signature(node), branch_statement(body) if body else None])
        return records
    if label == "object elements":
        records = []
        for statement in root["body"]:
            members = []
            for prop in statement["expression"]["properties"]:
                value = prop.get("value", {})
                method = prop.get("method") or prop.get("kind") in {"get", "set"}
                modifiers = prop.get("modifiers", ["async"] if method and value.get("async") else [])
                body = value.get("body") if method else None
                decorated = [[d["modifierIndex"], operand(d["expression"])] for d in prop.get("decorators", [])]
                members.append([operand(prop), modifiers, decorated, bool(prop.get("shorthand")), bool(prop.get("optional")),
                                bool(prop.get("definite")), bool(method and value.get("generator")),
                                branch_statement(body) if body else None])
            records.append(members)
        return records
    if label == "source references":
        refs = root.get("references", [])
        # The compiler exposes a separate ordered collection for each kind.
        records = [item for kind in ("path", "types", "lib", "amd-dependency") for item in refs if item["kind"] == kind]
        modules = [item for item in refs if item["kind"] == "amd-module"]
        if modules:
            records.append(modules[-1])
        if any(item["kind"] == "no-default-lib" for item in refs):
            records.append({"kind": "no-default-lib", "value": "true"})
        return records
    if label == "branch statement":
        return [branch_statement(stmt) for stmt in root["body"]]
    if label == "target expression":
        return [operand(stmt["expression"]) for stmt in root["body"] if stmt["type"] == "ExpressionStatement"]
    result, pending = [], [root]
    if label == "heritage source":
        result.append([["expression", operand(s["expression"])] if s["type"] == "ExpressionStatement" else statement_shape(s)
                       for s in root["body"]])
    expression_defaults = set()
    shorthand_defaults = set()
    heritage = set()
    wrapped = set()
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(reversed(item))
        elif isinstance(item, dict):
            kind = item.get("type")
            if label == "class method signature" and kind == "MethodDefinition" and item["kind"] == "method":
                name = ["computed", operand(item["key"])] if item["computed"] else key(item["key"])
                result.append(["method", name, signature(item["value"])])
            if label == "throw" and kind == "ThrowStatement":
                result.append([kind, operand(item["argument"]) if item["argument"] else None, item.get("missingArgumentOffset")])
            if label == "throw" and kind == "ExpressionStatement":
                result.append([kind, operand(item["expression"])])
            if label == "for statement" and kind == "ForStatement":
                result.append([kind, *[operand(item[f]) if item[f] else None for f in ("init", "test", "update")],
                               item["body"]["type"]])
            if label == "iteration" and kind in {"ForOfStatement", "ForInStatement"}:
                left = item["left"]
                target = ([left["kind"], [[binding_names(d["id"]), typ(d["id"].get("typeAnnotation")),
                                           operand(d["init"]) if d["init"] else None] for d in left["declarations"]]]
                          if left["type"] == "VariableDeclaration" else operand(left))
                result.append([kind, bool(item.get("await")), target, operand(item["right"]), item["body"]["type"]])
            if label == "rest binding":
                if kind == "VariableDeclarator":
                    result.extend(rest_bindings(item["id"]))
                elif kind == "CatchClause":
                    result.extend(rest_bindings(item["param"]))
                elif kind == "TSIndexSignature" or type_list_owner(kind) == "signature":
                    for param in item.get("params", item.get("parameters", [])):
                        result.extend(rest_bindings(param))
            if label == "decorated parameter" and (kind == "TSIndexSignature" or type_list_owner(kind) == "signature"):
                for param in item.get("params", item.get("parameters", [])):
                    if param.get("decorators"):
                        result.append(parameter(param))
            if label == "yield expression" and kind == "YieldExpression":
                result.append(operand(item))
            if label == "template spelling" and kind in {"TemplateLiteral", "TSTemplateLiteralType"}:
                quasis = [[q.get("rawText", q["value"]["raw"]), q["value"]["cooked"], q["tail"]] for q in item["quasis"]]
                if kind == "TemplateLiteral":
                    result.append(["expression", quasis, [operand(e) for e in item["expressions"]]])
                else:
                    result.append(["type", quasis, [typ(t) for t in item["types"]]])
            if label == "JSX" and kind in {"JSXElement", "JSXFragment"}:
                result.append(jsx_tree(item))
                continue
            if label == "namespace replay" and kind == "ExpressionStatement" and any(stmt is item for stmt in root["body"]):
                result.append(["expression", operand(item["expression"])])
            if label in {"namespace statements", "namespace replay"} and kind == "TSModuleBlock":
                statements = []
                for stmt in item["body"]:
                    decl = stmt.get("declaration") if stmt["type"] == "ExportNamedDeclaration" else stmt
                    if decl and decl["type"] == "VariableDeclaration":
                        statements.append([decl["kind"], [[key(d["id"]), operand(d["init"])] for d in decl["declarations"]]])
                    elif decl and decl["type"] == "TSModuleDeclaration":
                        statements.append(statement_shape(decl))
                    else:
                        statements.append(branch_statement(stmt))
                result.append(statements)
            if label == "namespace and enum" and kind == "TSModuleDeclaration":
                body = item.get("body")
                content = None
                if body:
                    content = (["nested", key(body["id"])] if body["type"] == "TSModuleDeclaration" else
                               ["block", [statement_shape(stmt) for stmt in body["body"]]])
                result.append([kind, item["kind"], key(item["id"]), content])
            if label == "namespace and enum" and kind == "TSEnumDeclaration":
                members = [[m["computed"], operand(m["id"]), operand(m["initializer"]) if m["initializer"] else None]
                           for m in item["members"]]
                result.append([kind, key(item["id"]), item["const"], bool(item.get("trailingComma")), members])
            if label in {"class members", "class member modifiers", "computed await", "class keyword members"} and kind in {"ClassDeclaration", "ClassExpression"}:
                members = []
                for node in item["body"]["body"]:
                    fn = node["value"] if node["type"] == "MethodDefinition" else {}
                    inferred = (["static"] if node.get("static") else []) + (["async"] if fn.get("async") else [])
                    mods = node.get("modifiers", inferred)
                    if label != "class member modifiers" or "async" in mods or "const" in mods:
                        members.append([node.get("kind", node["type"]), mods, bool(node.get("computed")),
                                       ["id", "constructor"] if node.get("kind") == "constructor" else operand(node["key"]) if node.get("key") else None, bool(node.get("optional")),
                                       bool(node.get("definite")), bool(fn.get("generator")), fn.get("body") is not None,
                                       bool(node.get("value")) if node["type"] == "PropertyDefinition" else False])
                    if label == "class keyword members":
                        members[-1].append([[d["modifierIndex"], operand(d["expression"])] for d in node.get("decorators", [])])
                        if node["type"] == "StaticBlock":
                            members[-1].append([branch_statement(stmt) for stmt in node["body"]])
                        elif node["type"] == "TSIndexSignature":
                            members[-1].append(member(node))
                    if label == "computed await":
                        field = node.get("value") if node["type"] == "PropertyDefinition" else None
                        statements = node.get("body") if node["type"] == "StaticBlock" else (fn.get("body") or {}).get("body")
                        members[-1].extend([operand(field) if field else None,
                                            [branch_statement(stmt) for stmt in statements] if statements is not None else None])
                if label != "class member modifiers":
                    result.append([kind, item["id"]["name"] if item.get("id") else None, members])
                else:
                    result.extend(members)
            if label == "declaration modifiers" and kind:
                if kind in {"MethodDefinition", "Property"} and item["value"].get("type") == "TSDeclareFunction":
                    wrapped.add(id(item["value"]))
                record = declaration_modifiers(item, wrapped)
                if record:
                    result.append(record)
            if label == "heritage source" and kind in {"ClassDeclaration", "ClassExpression"}:
                result.append([heritage_record(item), bool(item["body"].get("missing"))])
            if label == "heritage" and kind in {"ClassDeclaration", "ClassExpression", "TSInterfaceDeclaration"}:
                result.append(heritage_record(item))
            if label in {"type list", "empty type list"}:
                if kind == "TSHeritageClause":
                    heritage.update(id(e) for e in item["types"])
                for field in ("extends", "implements"):
                    if isinstance(item.get(field), list):
                        heritage.update(id(e) for e in item[field])
                for field in ("typeParameters", "superTypeArguments", "typeArguments"):
                    node = item.get(field)
                    if isinstance(node, dict) and (label == "type list" or not node["params"]):
                        owner = "heritage" if field == "superTypeArguments" or id(item) in heritage else type_list_owner(kind)
                        result.append([owner, "parameters" if field == "typeParameters" else "arguments",
                                       len(node["params"]), bool(node.get("trailingComma"))])
            if label == "import type" and (kind == "TSImportType" or (kind == "TSTypeQuery" and item["exprName"]["type"] == "TSImportType")):
                result.append(typ(item))
                continue
            if label == "index signature" and kind == "TSIndexSignature":
                result.append(member(item))
                continue
            if label == "property initializer" and kind == "TSPropertySignature" and "initializer" in item:
                result.append(member(item))
            if label == "type member list" and kind in {"TSInterfaceDeclaration", "TSTypeLiteral"}:
                members = item["body"]["body"] if kind == "TSInterfaceDeclaration" else item["members"]
                result.append(["interface" if kind == "TSInterfaceDeclaration" else "object",
                               [[m.get("modifiers", []), member(m)] for m in members]])
            if label == "declaration list" and kind == "VariableDeclaration":
                result.append([item["kind"], bool(item.get("trailingComma")), [
                    [binding_names(d["id"]), bool(d["id"].get("typeAnnotation")), d["init"] is not None,
                     bool(d.get("definite"))] for d in item["declarations"]]])
            if label == "chain continuation" and kind in {"CallExpression", "MemberExpression", "TaggedTemplateExpression"}:
                field = {"CallExpression": "callee", "MemberExpression": "object", "TaggedTemplateExpression": "tag"}[kind]
                base = item[field]
                if base["type"] == "ChainExpression":
                    base = base["expression"]
                if "optional" in item or base["type"] in {"TSNonNullExpression", "TSInstantiationExpression"}:
                    result.append(operand(item))
            if label == "module bindings":
                record = module_bindings(item)
                if record is not None:
                    if "attributes" in item:
                        record.append([item["attributeKeyword"], [[key(a["key"]), operand(a["value"])] for a in item["attributes"]]])
                    result.append(record)
            if label == "assignment":
                if kind in {"AssignmentExpression", "ForInStatement", "ForOfStatement"}:
                    expression_defaults.update(expression_pattern_defaults(item["left"]))
                if kind == "Property" and item.get("shorthand"):
                    # TypeScript stores the initializer directly on the shorthand property.
                    shorthand_defaults.add(id(item["value"]))
                if (kind == "AssignmentExpression" and id(item) not in shorthand_defaults) or id(item) in expression_defaults:
                    result.append(operand(item))
            if label == "update" and kind == "UpdateExpression":
                result.append(operand(item))
            if label == "definite field" and kind == "PropertyDefinition" and item.get("definite"):
                result.append([operand(item["key"]), item["computed"], item["static"], typ(item.get("typeAnnotation")),
                               operand(item["value"]) if item.get("value") else None])
            if label == "generator signature":
                if kind == "MethodDefinition":
                    fn = item["value"]
                    if fn.get("generator") and fn.get("body") is None:
                        result.append(["method", operand(item["key"]), item["computed"], item["static"],
                                       bool(item.get("optional")), fn["async"], signature(fn)])
                elif kind in {"FunctionDeclaration", "TSDeclareFunction"} and item.get("id") is not None and item.get("generator") and item.get("body") is None:
                    result.append(["function", key(item["id"]), item["async"], signature(item)])
                elif kind == "ExportDefaultDeclaration":
                    fn = item["declaration"]
                    if fn.get("type") == "TSDeclareFunction" and fn.get("generator") and fn.get("id") is None:
                        result.append(["function", None, fn["async"], signature(fn)])
            if label == "bodyless object member" and kind == "Property" and (item["method"] or item["kind"] in {"get", "set"}):
                fn = item["value"]
                if fn["body"] is None:
                    result.append([item["kind"], item["computed"], operand(item["key"]), fn.get("async", False),
                                   fn.get("generator", False), bool(item.get("optional")), bool(item.get("definite")),
                                   signature(fn)])
            if label == "accessor" and kind in {"MethodDefinition", "Property", "TSMethodSignature"} and item.get("kind") in {"get", "set"}:
                value = item if kind == "TSMethodSignature" else item["value"]
                modifiers = item.get("modifiers", ["static"] if item.get("static") else [])
                result.append([kind, item["kind"], modifiers, bool(item.get("computed")), operand(item["key"]),
                               signature(value), value.get("body") is not None])
            if label == "regexp spans" and kind == "RegExpLiteral":
                result.append([item["pattern"], item["flags"], [[d.get("code"), d["offset"], d.get("length"),
                               d.get("suggestion")] for d in item.get("diagnostics", [])]])
            if label == "regexp" and kind == "RegExpLiteral":
                issues = item.get("diagnostics", [])
                result.append([item["pattern"], item["flags"], not any(d["component"] == "pattern" for d in issues),
                               [d["offset"] for d in issues if d["component"] == "flags"]])
            if label == "parameter lists":
                owner = item
                if kind == "MethodDefinition" or (kind == "Property" and (item.get("method") or item.get("kind") in {"get", "set"})):
                    owner = item["value"]
                    wrapped.add(id(owner))
                if id(item) not in wrapped and (type_list_owner(owner.get("type")) == "signature" or
                                                owner.get("type") in {"JSDocFunctionType", "TSIndexSignature"}):
                    parameters = owner.get("params", owner.get("parameters", []))
                    result.append([len(parameters), [i for i, p in enumerate(parameters) if p["type"] == "RestElement"],
                                   bool(owner.get("parameterListTrailingComma"))])
            if label == "literal and binding lists" and kind in {"ArrayPattern", "ObjectPattern", "ArrayExpression", "ObjectExpression"}:
                array = "elements" in item
                children = item["elements"] if array else item["properties"]
                result.append(["array" if array else "object", len(children),
                               [i for i, child in enumerate(children) if child is None], bool(item.get("trailingComma"))])
            if label == "await expression" and kind == "AwaitExpression":
                result.append(operand(item))
            if label == "call expression" and kind in {"CallExpression", "ImportExpression"}:
                result.append(operand(item))
            if label == "new expression" and kind == "NewExpression":
                result.append(operand(item))
            if label == "meta property" and kind == "MetaProperty":
                result.append(operand(item))
            if label == "template tag" and kind == "TaggedTemplateExpression":
                result.append(operand(item))
            if label == "jump":
                if kind in {"BreakStatement", "ContinueStatement"}:
                    result.append([kind, item["label"]["name"] if item["label"] else None])
                elif kind == "LabeledStatement":
                    result.append([kind, item["label"]["name"], statement_shape(item["body"])])
                elif kind == "SwitchStatement":
                    result.append([kind, [[c["test"] is None, len(c["consequent"])] for c in item["cases"]]])
            if label == "private name":
                record = private_shape(item)
                if record is not None:
                    result.append(record)
            if label == "type predicate" and kind == "TSTypePredicate":
                result.append(typ(item))
            if label == "JSDoc type" and kind and kind.startswith("JSDoc") and kind.endswith("Type"):
                result.append(typ(item))
            if label == "function type" and kind == "TSFunctionType":
                result.append(typ(item))
            if label == "marked property" and kind == "Property" and (item.get("optional") or item.get("definite")):
                result.append(marked_property(item))
            if label == "arrow signature" and kind == "ArrowFunctionExpression":
                result.append([item["async"], item["expression"], *signature(item)])
            if label == "alias" and kind == "TSTypeAliasDeclaration":
                result.append([item["id"]["name"], params(item), typ(item["typeAnnotation"])])
            if kind == "PropertyDefinition":
                pending.extend([item.get("value"), item.get("typeAnnotation"), item["key"]])
            elif kind == "DoWhileStatement":
                pending.extend([item["test"], item["body"]])
            elif kind in {"CallExpression", "NewExpression"}:
                pending.extend([item["arguments"], item.get("typeArguments"), item["callee"]])
            elif kind in {"ClassDeclaration", "ClassExpression"}:
                pending.extend([item["body"], item.get("heritageClauses"), item.get("implements"),
                                item.get("superTypeArguments"), item.get("superClass"), item.get("typeParameters"), item.get("id")])
            elif type_list_owner(kind) == "signature":
                # Signature type parameters precede parameter and result types in the source.
                fields = ("typeParameters", "params", "returnType", "body")
                pending.extend(reversed([item.get(f) for f in fields]))
                pending.extend(reversed([v for k, v in item.items() if k not in fields and k != "decorators"]))
            else:
                pending.extend(reversed([v for k, v in item.items() if k != "decorators"]))
            if "decorators" in item:
                pending.append(item["decorators"])
    return result


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    cli.add_argument("source", type=Path)
    cli.add_argument("selection", nargs="?", default="types/typeAliases")
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument("--predicates", dest="label", action="store_const", const="type predicate", help="Compare assertion flags, predicate subjects and narrowed type trees")
    mode.add_argument("--jsdoc-types", dest="label", action="store_const", const="JSDoc type", help="Compare JSDoc type nodes embedded in TypeScript syntax")
    mode.add_argument("--function-types", dest="label", action="store_const", const="function type", help="Compare function types in declarations and annotations")
    mode.add_argument("--object-markers", dest="label", action="store_const", const="marked property", help="Compare object literal properties with question or exclamation tokens")
    mode.add_argument("--private-names", dest="label", action="store_const", const="private name", help="Compare private identifiers and their declaration or expression nodes")
    mode.add_argument("--declarations", dest="label", action="store_const", const="declaration list", help="Compare variable declaration kinds, binding patterns, markers and initializer presence")
    mode.add_argument("--chain-continuations", dest="label", action="store_const", const="chain continuation", help="Compare optional chain continuations and operations on assertions or instantiations")
    mode.add_argument("--module-bindings", dest="label", action="store_const", const="module bindings", help="Compare import and re-export clause names, aliases, sources and type-only markers")
    mode.add_argument("--jumps", dest="label", action="store_const", const="jump", help="Compare jump labels, labeled bodies, and switch clause boundaries")
    mode.add_argument("--regexps", dest="label", action="store_const", const="regexp", help="Compare literal text, flag errors and pattern validity with the compiler regex scanner")
    mode.add_argument("--templates", dest="label", action="store_const", const="template spelling", help="Compare template spelling, cooked values, tails and substitutions")
    mode.add_argument("--jsx", dest="label", action="store_const", const="JSX", help="Compare JSX tags, attributes, type arguments and child order")
    mode.add_argument("--iteration", dest="label", action="store_const", const="iteration", help="Compare for-in/of targets, sources and body kinds")
    mode.add_argument("--rest-bindings", dest="label", action="store_const", const="rest binding", help="Compare rest binding targets, positions, aliases, defaults and trailing commas")
    mode.add_argument("--definite-fields", dest="label", action="store_const", const="definite field", help="Compare class fields with definite assignment assertions")
    mode.add_argument("--generator-signatures", dest="label", action="store_const", const="generator signature", help="Compare bodyless generator function and class method signatures")
    mode.add_argument("--bodyless-object-members", dest="label", action="store_const", const="bodyless object member", help="Compare object method and accessor signatures without bodies")
    mode.add_argument("--accessors", dest="label", action="store_const", const="accessor", help="Compare accessor containers, keys, signatures and body presence")
    mode.add_argument("--meta", dest="label", action="store_const", const="meta property", help="Compare meta-property names")
    mode.add_argument("--tags", dest="label", action="store_const", const="template tag", help="Compare tags, optional chains, type arguments and template segments")
    mode.add_argument("--updates", dest="label", action="store_const", const="update", help="Compare prefix/postfix operators and operand structure")
    mode.add_argument("--assignments", dest="label", action="store_const", const="assignment", help="Compare assignment operators and their children")
    mode.add_argument("--references", dest="label", action="store_const", const="source references", help="Compare leading triple-slash references and AMD directives")
    mode.add_argument("--namespace-enums", dest="label", action="store_const", const="namespace and enum", help="Compare module nesting and enum member initializers")
    mode.add_argument("--class-members", dest="label", action="store_const", const="class members", help="Compare ordered class member kinds, keys and modifiers")
    mode.add_argument("--class-keyword-members", dest="label", action="store_const", const="class keyword members", help="Compare class members with decorator and modifier order")
    mode.add_argument("--class-member-modifiers", dest="label", action="store_const", const="class member modifiers", help="Compare class members with const and async modifiers")
    mode.add_argument("--decorated-parameters", dest="label", action="store_const", const="decorated parameter", help="Compare parameter annotations, decorators, initializers and modifier order")
    mode.add_argument("--declaration-modifiers", dest="label", action="store_const", const="declaration modifiers", help="Compare declaration kind, name and ordered modifier/decorator sequence")
    mode.add_argument("--await-expressions", dest="label", action="store_const", const="await expression", help="Compare await nodes and operands in source traversal order")
    mode.add_argument("--import-diagnostics", dest="label", action="store_const", const="import diagnostics", help="Compare dynamic import grammar diagnostic codes and spans")
    mode.add_argument("--generic-diagnostics", dest="label", action="store_const", const="generic diagnostics", help="Compare generic and heritage list grammar diagnostic codes and spans")
    mode.add_argument("--parameter-diagnostics", dest="label", action="store_const", const="parameter diagnostics", help="Compare parameter-list grammar diagnostic codes and spans")
    mode.add_argument("--parameter-lists", dest="label", action="store_const", const="parameter lists", help="Compare signature parameter counts, rest positions and trailing commas")
    mode.add_argument("--literal-lists", dest="label", action="store_const", const="literal and binding lists", help="Compare array and object list lengths, elisions and trailing commas")
    mode.add_argument("--calls", dest="label", action="store_const", const="call expression", help="Compare call and dynamic-import operands and trailing commas")
    mode.add_argument("--new-expressions", dest="label", action="store_const", const="new expression", help="Compare constructor callees, type arguments and argument lists")
    mode.add_argument("--heritage", dest="label", action="store_const", const="heritage", help="Compare ordered extends/implements clauses, base expressions and type arguments")
    mode.add_argument("--empty-lists", dest="label", action="store_const", const="empty type list", help="Compare the owners of explicitly empty generic lists")
    mode.add_argument("--arrows", dest="label", action="store_const", const="arrow signature", help="Compare arrow function signatures and body forms")
    mode.add_argument("--property-initializers", dest="label", action="store_const", const="property initializer", help="Compare initialized property signatures and their expression children")
    mode.add_argument("--members", dest="label", action="store_const", const="type member list", help="Compare ordered interface and type-literal members and their modifiers")
    mode.add_argument("--indexes", dest="label", action="store_const", const="index signature", help="Compare index signatures")
    mode.add_argument("--imports", dest="label", action="store_const", const="import type", help="Compare import types in every syntactic position")
    args = cli.parse_args()
    label = args.label or "alias"
    check_pin(args.compiler, COMPILER_SHA)
    check_pin(args.source, SOURCE_SHA)
    corpus = args.compiler if args.selection in {"lib", "compiler-api"} else args.source
    cases = list(source_cases(corpus, args.selection))
    if not cases:
        cli.error(f"no TypeScript sources for selection {args.selection!r}")
    for case in cases:
        case["projection"] = label
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    if label in {"parameter diagnostics", "generic diagnostics", "import diagnostics"}:
        oracle = Path(__file__).with_name("ts_grammar_diagnostics.cjs").read_text() + oracle
    total = invalid = failures = 0
    for case, ref in zip(cases, run_compiler(args.compiler, oracle, cases), strict=True):
        try:
            tree = TypeScriptPipeline(case["name"]).parse(case["source"])
        except ValueError as exc:
            if ref.get("invalid"):
                invalid += 1
                continue
            failures += 1
            print(case["file"], str(exc))
            continue
        if "trees" not in ref:
            failures += 1
            print(case["file"], ref)
            continue
        try:
            actual = project_trees(tree, label)
        except ValueError as exc:
            failures += 1
            print(case["file"], str(exc))
            continue
        total += sum(a == e for a, e in zip(actual, ref["trees"]))
        if actual != ref["trees"]:
            failures += 1
            for a, e in zip(actual, ref["trees"]):
                if a != e:
                    print(case["file"], "Orion", a, "TypeScript", e)
            if len(actual) != len(ref["trees"]):
                print(case["file"], f"{label} counts", len(actual), len(ref["trees"]))
                if label in {"parameter diagnostics", "generic diagnostics"}:
                    print(case["file"], "Orion", actual, "TypeScript", ref["trees"])
    unit = label if label in {"parameter lists", "parameter diagnostics", "generic diagnostics", "import diagnostics"} else label + " trees"
    print(f"{total} {unit}; {invalid} jointly rejected files; {failures} differing files")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
