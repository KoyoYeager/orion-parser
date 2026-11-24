"""Compare complete C++20 CLI units with Clang 18.1.8 on the pinned target."""
import argparse
import csv
import hashlib
import json
from itertools import permutations, product
from pathlib import Path
from urllib.request import urlopen
import re
import subprocess
import sys
import tempfile

from ply_trace import capture_reductions
from orionparser.registry import get_pipeline
from orionparser.languages.cpp.lexer import CppSource
from orionparser.languages.cpp.pipeline import ParameterClauseGrammar, TypeIdGrammar
from check_c17 import ROOT, check_version


FLAGS = ["-target", "x86_64-unknown-linux-gnu", "-std=c++20", "-pedantic-errors"]
FIXTURES = ROOT / "tests/languages/cpp/fixtures"


def cli(path, *options):
    run = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json", *options],
                         capture_output=True, text=True)
    if run.returncode:
        raise ValueError(f"{path}: {run.stderr}")
    return json.loads(run.stdout)


def parameter_spelling(p):
    if p["type"] == "Ellipsis":
        return "..."
    return type_name(p["parameterType"], parameter=not p.get("pack")) + ("..." if p.get("pack") else "")


def type_name(node, outer=(), *, parameter=False, written=False):
    if node["type"] in {"NameExpression", "Literal"}:
        return node.get("name", node.get("raw"))
    if node["type"] in {"ClassDeclaration", "EnumDeclaration"}:
        key = node["key"] if node["type"] == "ClassDeclaration" else "enum"
        return key + " " + (node["name"] or "(unnamed)")
    if node["type"] == "ElaboratedType":
        args = "<" + ", ".join(type_name(a, written=written) for a in node["arguments"]) + ">" if "arguments" in node else ""
        return node["key"] + " " + node["name"] + args
    if node["type"] == "BuiltinIntegerSequence":
        return "__make_integer_seq<" + ", ".join(type_name(node[k]) for k in ("template", "elementType", "length")) + ">"
    if node["type"] == "BuiltinPackElement":
        arguments = [type_name(node["index"]), *map(type_name, node["operands"])]
        return "__type_pack_element<" + ", ".join(arguments) + ">"
    if node["type"] == "BuiltinTypeTransform":
        return node["name"] + "(" + type_name(node["operand"]) + ")"
    if node["type"] == "GnuTypeof":
        operand = node["operand"]
        return ("typeof(" if operand["type"] == "Type" else "typeof (") + type_name(operand) + ")"
    if node["type"] == "Decltype":
        operand = node["operand"]
        return "decltype(" + (operand if isinstance(operand, str) else type_name(operand)) + ")"
    if node["type"] == "QualifiedMemberExpression":
        return type_name(node["owner"]) + "::" + node["name"]
    if node["type"] == "QualifiedType":
        args = "<" + ", ".join(map(type_name, node["arguments"])) + ">" if "arguments" in node else ""
        return type_name(node["qualifier"]) + "::" + ("template " if node.get("template") else "") + node["name"] + args
    if node["type"] == "SubscriptExpression":
        return type_name(node["base"]) + "[" + type_name(node["index"]) + "]"
    if node["type"] == "UnaryExpression" and node["prefix"]:
        if node["operator"] in {"sizeof", "alignof"} and node["operand"]["type"] == "Type":
            return node["operator"] + "(" + type_name(node["operand"]) + ")"
        return node["operator"] + type_name(node["operand"])
    if node["type"] == "TypeConstruction" and node["initializer"]["type"] == "Arguments":
        args = ", ".join(map(type_name, node["initializer"]["values"]))
        return type_name(node["target"]) + "(" + args + ")"
    if node["type"] == "CallExpression":
        return type_name(node["callee"]) + "(" + ", ".join(map(type_name, node["arguments"])) + ")"
    if node["type"] == "BinaryExpression":
        return f"{type_name(node['left'])} {node['operator']} {type_name(node['right'])}"
    if node["type"] == "ParenthesizedExpression":
        return "(" + type_name(node["expression"]) + ")"
    if node["type"] == "ConstrainedPlaceholder":
        constraint = node["constraint"]
        args = ", ".join(map(type_name, constraint.get("arguments", [])))
        return constraint["name"] + ("<" + args + ">" if "arguments" in constraint else "") + " " + node["placeholder"]
    if node["type"] == "DependentType":
        segments = []
        for segment in node["segments"]:
            if "decltype" in segment:
                segments.append(type_name(segment["decltype"]))
                continue
            name = ("template " if segment.get("template") else "") + segment["name"]
            if "arguments" in segment:
                name += "<" + ", ".join(map(type_name, segment["arguments"])) + ">"
            segments.append(name)
        return "typename " + ("::" if node["absolute"] else "") + "::".join(segments)
    if node["type"] == "DependentTemplateName":
        return type_name(node["owner"]) + "::template " + node["name"]
    if node["type"] == "DependentTemplateId":
        return node["qualifier"] + "::template " + node["name"] + "<" + ", ".join(map(type_name, node["arguments"])) + ">"
    if node["type"] == "PackExpansion":
        return type_name(node["pattern"]) + "..."
    if node["type"] in {"TypeName", "TemplateId", "TemplateName"}:
        args = ", ".join(type_name(arg, written=written) for arg in node.get("arguments", []))
        return ("typename " if node.get("implicitTypename") else "") + node["name"] + ("<" + args + ">" if "arguments" in node else "")
    words = [type_name(t, written=written) if isinstance(t, dict) else t for t in node["specifiers"]
             if not (isinstance(t, dict) and t["type"] == "GnuAttributeSpecifier") and t not in ("constexpr", "consteval", "constinit", "thread_local", "mutable", "static", "inline", "__inline", "__inline__", "extern", "virtual", "friend", "explicit")]
    words = ["signed" if w in {"__signed", "__signed__"} else w for w in words]
    cv = [q for q in ("const", "volatile") if q in words] if not written else []
    words = [word for word in words if word not in cv]
    if not written and words in (["signed"], ["signed", "int"], ["int", "signed"]):
        words = ["int"]
    if not written and words == ["unsigned"]:
        words.append("int")
    words = [*cv, *words]
    operators = list(outer)
    if "declarator" in node:
        operators.extend(node["declarator"])
    else:
        for ptr in reversed(node["indirections"]):
            operators.append({"type": "PointerOperator", **(ptr if isinstance(ptr, dict) else {"operator": ptr})})
    if parameter and operators:
        if operators[0]["type"] == "ArrayOperator":
            operators[0] = {"type": "PointerOperator", "operator": "*"}
        elif operators[0]["type"] == "FunctionOperator":
            operators.insert(0, {"type": "PointerOperator", "operator": "*"})
    declarator = ""
    prefix = False
    for op in operators:
        kind = op["type"]
        if kind == "PointerOperator":
            quals = " ".join("__restrict" if q == "__restrict__" else q for q in op.get("qualifiers", []))
            spacing = " " if quals and declarator.startswith(("*", "&")) else ""
            owner = op["class"] + "::" if "class" in op else ""
            declarator = owner + op["operator"] + quals + spacing + declarator
            prefix = True
        else:
            if prefix:
                declarator = "(" + declarator + ")"
            if kind == "ArrayOperator":
                size = op["size"]
                declarator += "[" + (type_name(size) if size is not None else "") + "]"
            elif kind == "FunctionOperator":
                declarator += "(" + ", ".join(map(parameter_spelling, op["parameters"])) + ")"
                for q in op["qualifiers"]:
                    declarator += " " + {"bitand": "&", "and": "&&"}.get(q, q)
                if op["noexcept"] is True:
                    declarator += " noexcept"
                elif op["noexcept"] == {"type": "EmptyThrowSpecification"}:
                    declarator += " throw()"
                elif op["noexcept"]:
                    declarator += " noexcept(" + type_name(op["noexcept"]) + ")"
                if op.get("trailingReturnType"):
                    declarator += " -> " + type_name(op["trailingReturnType"])
            else:
                raise ValueError("unmapped declarator operator " + kind)
            prefix = False
    separator = " " if declarator and not declarator.startswith("[") else ""
    return " ".join(words) + separator + declarator


def declaration_nodes(nodes):
    for node in nodes:
        first = node["declarations"][0] if node["type"] == "DeclarationGroup" else node
        target = first.get("variableType") or first.get("target")
        if isinstance(target, dict):
            for spec in target.get("specifiers", []):
                if isinstance(spec, dict) and spec["type"] in {"ClassDeclaration", "EnumDeclaration"}:
                    yield orion(spec)
        if node["type"] in {"DeclarationGroup", "UsingDeclarationGroup"}:
            yield from map(orion, node["declarations"])
        else:
            yield orion(node)
            if node["type"] == "ClassDeclaration":
                aliases = node.get("typedefs", [])
                tag = node["name"] or next((alias["name"] for alias in aliases if not alias["declarator"]), "(unnamed)")
                for alias in aliases:
                    base = {"type": "Type", "specifiers": [*node.get("declarationSpecifiers", []), node["key"], tag],
                            "declarator": alias["declarator"]}
                    yield ["typedef", alias["name"], type_name(base)]
                for decl in node.get("declarators", []):
                    dims = [{"type": "ArrayOperator", "size": d} for d in decl["dimensions"]]
                    specifiers = node.get("declarationSpecifiers", [])
                    cv = [q for q in ("const", "volatile") if q in specifiers or (q == "const" and "constexpr" in specifiers)]
                    base = {"type": "Type", "specifiers": [*cv, node["key"], node["name"] or "(unnamed)"],
                            "declarator": [*dims, *decl.get("declarator", [])]}
                    spelling = type_name(base)
                    yield ["var", decl["name"], spelling, orion(decl["initializer"])]


def control_initializer(node):
    return [["init", orion(node["init"])]] if "init" in node else []


def written_explicit(prefix):
    match = re.search(rb"\bexplicit\b\s*", prefix)
    if not match:
        return False
    suffix = prefix[match.end():]
    if not suffix.startswith(b"("):
        return True
    level = 1
    for i, char in enumerate(suffix[1:], 1):
        level += (char == 40) - (char == 41)
        if not level:
            return re.sub(rb"\s+", b"", suffix[1:i]).decode()
    raise ValueError("incomplete explicit specifier in reference")


def explicit_value(value):
    return re.sub(r"\s+", "", type_name(value)) if isinstance(value, dict) else value


def conversion_name(owner, target):
    tokens = r"::|&&|\w+|[^\s]"
    return ["conversion-id", re.findall(tokens, owner or ""), re.findall(tokens, target)]


def orion(node):
    if node is None:
        return None
    kind = node["type"]
    if kind == "TranslationUnit":
        children = []
        for part in [node["globalModuleFragment"], node, node["privateModuleFragment"]]:
            if part is not None:
                children.extend(declaration_nodes(part["declarations"]))
        return ["unit", *children]
    if kind == "ExportDeclaration":
        return ["export", *declaration_nodes(node["declarations"])]
    if kind == "LinkageSpecification":
        parts = []
        for literal in node["language"]:
            raw = re.fullmatch(r'(?:u8|[uUL])?R"([^()]*)\((.*)\)\1"', literal, re.S)
            parts.append(raw[2] if raw else json.loads(literal[literal.index('"'):]))
        return ["linkage", "".join(parts), node["block"], *declaration_nodes(node["declarations"])]
    if kind == "EmptyDeclaration":
        return ["empty"]
    if kind == "NamespaceDefinition":
        children = list(declaration_nodes(node["declarations"]))
        for part in reversed(node["path"] or [{"name": None, "inline": node.get("inline", False)}]):
            children = [["namespace", part["name"], part["inline"], *children]]
        return children[0]
    if kind == "ConceptDefinition":
        return ["concept", node["name"], orion(node["constraint"])]
    if kind in {"ConceptId", "TypeConstraint"}:
        return ["concept-id", node["name"], list(map(type_name, node.get("arguments", [])))]
    if kind == "RequiresExpression":
        params = [[type_name(p["parameterType"]), p["name"]] for p in node["parameters"] or []]
        return ["requires", params, *map(orion, node["requirements"])]
    if kind == "SimpleRequirement":
        return ["simple", orion(node["expression"])]
    if kind == "TypeRequirement":
        return ["type-requirement", type_name(node["target"]).removeprefix("typename ")]
    if kind == "CompoundRequirement":
        return ["compound", orion(node["expression"]), node["noexcept"], orion(node["constraint"])]
    if kind == "NestedRequirement":
        return ["nested", orion(node["constraint"])]
    if kind == "EnumDeclaration":
        return ["enum", node["name"], node["scoped"], type_name(node["underlying"]) if node["underlying"] else ("int" if node["scoped"] else None),
                *map(orion, node["enumerators"] or [])]
    if kind == "Enumerator":
        return ["enumerator", node["name"], orion(node["value"])]
    if kind == "AsmDeclaration":
        return ["asm", node["parts"]]
    if kind == "NamespaceAlias":
        return ["namespace_alias", node["name"], node["target"]]
    if kind == "GnuExtensionDeclaration":
        return orion(node["declaration"])
    if kind == "UsingDeclaration":
        return [kind, node["target"], node.get("typename", False), node.get("pack", False)]
    if kind in {"UsingDirective", "UsingEnumDeclaration"}:
        return [kind, node["target"]]
    if kind == "LambdaExpression":
        captures = []
        for capture in node["captures"]:
            init = capture["initializer"]
            if not init:
                value = ["name", capture["name"]]
            elif init["type"] == "CopyInitializer":
                value = orion(init["value"])
            else:
                value = orion(init)
            captures.append([capture["name"], capture["mode"], value])
        params = [[parameter_spelling(p), p["name"]] for p in node["parameters"] or []]
        return ["lambda", node["captureDefault"], captures, list(map(orion, node["templateParameters"])),
                params, "mutable" in node["specifiers"], orion(node["templateRequires"]), orion(node["requires"]), orion(node["body"])]
    if kind == "NewExpression":
        allocated = node["allocatedType"]
        dimensions = list(node["dimensions"])
        operators = list(allocated.get("declarator", []))
        while operators and operators[0]["type"] == "ArrayOperator":
            dimensions.append(operators.pop(0)["size"])
        if "declarator" in allocated:
            allocated = {**allocated, "declarator": operators}
        result = [{"type": "PointerOperator", "operator": "*"}]
        result.extend({"type": "ArrayOperator", "size": d} for d in dimensions[1:])
        init = node["initializer"]
        initializer = None
        if init:
            initializer = (["call", *map(orion, init["arguments"])] if init["type"] == "DirectInitializer"
                           else ["list", *map(orion, init["elements"])])
        return ["new", node["global"], type_name(allocated, result), bool(dimensions),
                orion(dimensions[0]) if dimensions else None, initializer, list(map(orion, node["placement"]))]
    if kind == "DeleteExpression":
        return ["delete", node["global"], node["array"], orion(node["operand"])]
    if kind == "GnuExtensionExpression":
        return ["prefix", "__extension__", orion(node["operand"])]
    if kind == "BuiltinBitCast":
        return ["builtin-bit-cast", type_name(node["target"]), orion(node["operand"])]
    if kind == "DeductionGuide":
        params = [[parameter_spelling(p), p["name"]] for p in node["parameters"] if p["type"] != "Ellipsis"]
        return ["guide", node["name"], params, type_name(node["target"]), explicit_value(node["explicit"])]
    if kind == "CastExpression":
        return [node["cast"], type_name(node["target"]), orion(node["operand"])]
    if kind == "AliasDeclaration":
        return [node["syntax"], node["name"], type_name(node["target"])]
    if kind == "ExplicitInstantiation" and "target" in node:
        return ["class-instantiation", node["extern"], node["key"], type_name(node["target"])]
    if kind == "ExplicitSpecialization" and node["declaration"]["type"] == "FunctionDeclaration":
        decl = node["declaration"]
        name = type_name(decl["specialization"]) if "specialization" in decl else decl["name"]
        return ["function-specialization", name, orion(decl)]
    if kind == "ExplicitSpecialization":
        return ["explicit-specialization", orion(node["declaration"])]
    if kind == "ClassDeclaration":
        bases = [[type_name(b["target"]), b["access"], b["virtual"], b.get("pack", False)] for b in node["bases"]]
        name = type_name(node["specialization"]) if "specialization" in node else node["name"]
        return [node["key"], name, node["final"], bases, *declaration_nodes(node["members"] or [])]
    if kind == "FriendTypeDeclaration":
        spelling = type_name(node["target"])
        return ["friend", (node["key"] + " " if node["key"] else "") + spelling]
    if kind == "AccessSpecifier":
        return ["access", node["access"]]
    if kind == "ConversionFunctionDeclaration":
        fn = {"type": "FunctionOperator", "parameters": [], "qualifiers": node["qualifiers"], "noexcept": node["noexcept"]}
        return ["conversion", node["qualifier"], type_name(node["target"], [fn]), "explicit" in node["specifiers"], orion(node["body"]), orion(node.get("requires"))]
    if kind in {"ConstructorDeclaration", "DestructorDeclaration"}:
        params = [[parameter_spelling(p), p["name"]] for p in node["parameters"] if p["type"] != "Ellipsis"]
        inits = []
        for item in node["initializers"]:
            target = item["target"]
            init = item["initializer"]
            inits.append([target if isinstance(target, str) else type_name(target), init["type"] == "InitializerList",
                          [orion(v) for v in init.get("values", init.get("elements", []))]])
        condition = next((s["condition"] for s in node["specifiers"] if isinstance(s, dict) and s["type"] == "ExplicitSpecifier"), None)
        return [kind, node["name"], params, explicit_value(condition) if condition is not None else "explicit" in node["specifiers"], "virtual" in node["specifiers"],
                node.get("functionSpecifier"), sorted(node["virtSpecifiers"]), inits, orion(node["body"]), orion(node.get("requires"))]
    if kind == "QualifiedMemberExpression":
        return ["name", type_name(node["owner"]) + "::" + node["name"]]
    if kind == "TemplateDeclaration" and node["declaration"].get("owner"):
        decl = node["declaration"]
        return ["member-definition", list(map(orion, node["parameters"])), type_name(decl["owner"]), orion(decl)]
    if kind == "TemplateDeclaration":
        return ["template", list(map(orion, node["parameters"])), orion(node.get("requires")), orion(node["declaration"])]
    if kind == "TypeTemplateParameter":
        return [node.get("key") or orion(node["constraint"]), node["name"], node.get("pack", False), type_name(node["default"]) if node.get("default") else None]
    if kind == "TemplateTemplateParameter":
        return ["template-parameter", node["name"], node.get("pack", False), list(map(orion, node["parameters"])), node.get("default")]
    if kind == "NonTypeTemplateParameter":
        return [type_name(node["parameterType"], parameter=True), node["name"], node.get("pack", False), orion(node.get("default"))]
    if kind == "FunctionDeclaration":
        params = [[parameter_spelling(p), p["name"]] for p in node["parameters"] if p["type"] != "Ellipsis"]
        fn = {"type": "FunctionOperator", "parameters": node["parameters"], "qualifiers": node["qualifiers"],
              "noexcept": node["noexcept"]}
        # Deallocation functions have a nonthrowing implicit exception specification.
        if node["name"].split("::")[-1] in {"operator delete", "operator delete[]"} and node["noexcept"] is False:
            fn["noexcept"] = True
        fn["trailingReturnType"] = node.get("trailingReturnType")
        signature = type_name(node["returnType"], [fn])
        specs = [s for s in node["returnType"]["specifiers"] if isinstance(s, dict) and s["type"] == "GnuAttributeSpecifier"]
        gnu = [item["name"].strip("_") for spec in [*specs, *node.get("gnuAttributes", [])] for item in spec["items"]]
        return ["function", node["name"], sorted(gnu), signature, params, any(s in ("constexpr", "consteval") for s in node["returnType"]["specifiers"]), orion(node["body"]),
                "virtual" in node["returnType"]["specifiers"], node.get("functionSpecifier"), sorted(node.get("virtSpecifiers", [])), orion(node.get("requires")),
                *([["asm-label", "".join(json.loads(part) for part in node["asmLabel"]["parts"])]] if "asmLabel" in node else [])]
    if kind == "DeclarationGroup":
        return ["group", *declaration_nodes([node])]
    if kind == "StructuredBinding":
        init = node.get("initializer")
        style = {"CopyInitializer": "c", "DirectInitializer": "call", "InitializerList": "list"}[init["type"]] if init else None
        target = node["variableType"]
        return ["binding", " ".join(target["specifiers"] + target["indirections"]), node["names"], style, orion(init)]
    if kind == "AttributeDeclaration":
        return ["empty"]
    if kind == "CopyInitializer":
        return orion(node["value"])
    if kind == "VariableDeclaration":
        t = type_name(node["variableType"], [{"type": "ArrayOperator", "size": dim} for dim in node["dimensions"]])
        if "constexpr" in node["variableType"]["specifiers"] and "const" not in node["variableType"]["specifiers"] and not t.endswith("&"):
            t = "const " + t
        if "bitWidth" in node:
            return ["bit-field", node["name"], t, orion(node["bitWidth"]), orion(node["initializer"])]
        return ["var", type_name(node["specialization"]) if "specialization" in node else node["name"], t, orion(node["initializer"])]
    if kind in {"NameExpression", "TemplateId", "DependentTemplateId"}:
        return ["name", type_name(node)]
    if kind == "FoldExpression":
        return ["fold", node["operator"], orion(node["left"]), orion(node["right"])]
    if kind == "ThisExpression":
        return ["this"]
    if kind == "PackExpansion":
        return ["pack-expansion", orion(node["pattern"])]
    if kind == "SizeofPack":
        return ["sizeof...", node["name"]]
    if kind == "StringLiteral":
        return ["string", node["parts"], node.get("userDefined", {}).get("suffix"), node.get("encodingPrefix", "")]
    if kind == "Literal":
        if node.get("userDefined", {}).get("kind") == "character":
            return ["character-udl", node["raw"], node["userDefined"]["suffix"]]
        return ["literal", node["raw"]]
    if kind in {"BinaryExpression", "AssignmentExpression"}:
        return [node["operator"], orion(node["left"]), orion(node["right"])]
    if kind == "ConditionalExpression":
        return ["?:", orion(node["test"]), orion(node["then"]), orion(node["else"])]
    if kind == "UnaryExpression":
        return ["prefix" if node["prefix"] else "postfix", "__alignof" if node["operator"] == "__alignof__" else node["operator"], orion(node["operand"])]
    if kind == "CallExpression":
        return ["call", orion(node["callee"]), *map(orion, node["arguments"])]
    if kind == "Type":
        return ["type", type_name(node)]
    if kind == "TypeidExpression":
        return ["typeid", orion(node["operand"])]
    if kind == "NoexceptExpression":
        return ["noexcept", orion(node["expression"])]
    if kind == "ParenthesizedExpression":
        return ["paren", orion(node["expression"])]
    if kind == "CommaExpression":
        return [",", orion(node["left"]), orion(node["right"])]
    if kind == "ConversionFunctionId":
        return conversion_name(node["qualifier"], type_name(node["target"], written=True))
    if kind == "MemberExpression":
        if "conversionType" in node:
            owner = type_name(node["qualifier"]) if "qualifier" in node else None
            return [node["operator"], orion(node["base"]), conversion_name(owner, type_name(node["conversionType"], written=True))]
        if "arguments" in node and node["member"].startswith("operator"):
            owner = type_name(node["qualifier"], written=True) + "::" if "qualifier" in node else ""
            keyword = "template " if node["template"] else ""
            args = ",".join(type_name(arg, written=True) for arg in node["arguments"])
            spelling = owner + keyword + node["member"] + "<" + args + ">"
            return ["member-operator-template", node["operator"], orion(node["base"]), re.findall(r"->|::|\w+|[^\s]", spelling)]
        if "qualifier" in node and "arguments" in node:
            args = ",".join(type_name(arg, written=True) for arg in node["arguments"])
            keyword = "template " if node["template"] else ""
            member = f"{type_name(node['qualifier'], written=True)}::{keyword}{node['member']}<{args}>"
            return ["qualified-member-template", node["operator"], orion(node["base"]), re.findall(r"::|\w+|[^\s]", member)]
        if node.get("template"):
            return ["member-template", node["operator"], orion(node["base"]), node["member"], list(map(type_name, node["arguments"]))]
        if "arguments" in node:
            spelling = node["member"] + "<" + ",".join(map(type_name, node["arguments"])) + ">"
            return ["member-template-id", node["operator"], orion(node["base"]), re.sub(r"\s+", "", spelling)]
        member = type_name(node["qualifier"]) + "::" + node["member"] if "qualifier" in node else node["member"]
        return [node["operator"], orion(node["base"]), member]
    if kind == "SubscriptExpression":
        return ["subscript", orion(node["base"]), orion(node["index"])]
    if kind == "TryBlock":
        return ["try", orion(node["body"]), *map(orion, node["handlers"])]
    if kind == "CatchHandler":
        param = node["parameter"]
        return ["catch", [type_name(param["exceptionType"]), param["name"]] if param else None, orion(node["body"])]
    if kind in {"AwaitExpression", "YieldExpression", "CoroutineReturnStatement"}:
        return [kind, orion(node["operand"])]
    if kind == "ThrowExpression":
        return ["throw", orion(node["operand"])]
    if kind == "CompoundStatement":
        statements = []
        for stmt in node["statements"]:
            if stmt["type"] in {"ClassDeclaration", "AliasDeclaration", "VariableDeclaration"}:
                parts = list(declaration_nodes([stmt]))
                statements.append(parts[0] if len(parts) == 1 else ["group", *parts])
            else:
                statements.append(orion(stmt))
        return ["block", *statements]
    if kind == "DirectInitializer" and len(node["arguments"]) == 1:
        return orion(node["arguments"][0])
    if kind == "TypeConstruction":
        init = node["initializer"]
        if init["type"] == "Arguments":
            return ["functional-cast", type_name(node["target"]), *map(orion, init["values"])]
        return ["list-cast", type_name(node["target"]), orion(init)]
    if kind == "BuiltinTypeTraitExpression":
        spelling = node["name"] + "(" + ",".join(map(type_name, node["operands"])) + ")"
        return ["builtin-type-trait", re.sub(r"\s+", "", spelling)]
    if kind == "RangeForStatement":
        binding = [orion(node["binding"])] if "binding" in node else [type_name(node["variableType"]), node["name"]]
        return ["range-for", *control_initializer(node), *binding, orion(node["range"]), orion(node["body"])]
    if kind == "DesignatedInitializer":
        return ["designator", node["member"], node["form"], orion(node["value"])]
    if kind == "InitializerList" and "trailingComma" in node:
        return ["designated-list", node["trailingComma"], *map(orion, node["elements"])]
    if kind == "InitializerList":
        return ["initializer", *map(orion, node["elements"])]
    if kind in {"SwitchStatement", "WhileStatement"}:
        return [kind, *control_initializer(node), orion(node["test"]), orion(node["body"])]
    if kind == "DoWhileStatement":
        return [kind, orion(node["body"]), orion(node["test"])]
    if kind in {"BreakStatement", "ContinueStatement"}:
        return [kind]
    if kind == "CaseStatement":
        return ["case", orion(node["value"]), orion(node["statement"])]
    if kind == "LabeledStatement":
        return ["label", node["label"], orion(node["statement"])]
    if kind == "GotoStatement":
        return ["goto", node["label"]]
    if kind == "IfStatement":
        return ["if", node.get("constexpr", False), *control_initializer(node), orion(node["test"]), orion(node["then"]), orion(node["else"])]
    if kind == "ForStatement":
        return ["for", *[orion(node[k]) for k in ("init", "test", "update", "body")]]
    if kind == "ReturnStatement":
        return ["return", orion(node["expression"])]
    if kind == "ExpressionStatement":
        return orion(node["expression"])
    if kind == "StaticAssertion":
        return ["assert", orion(node["test"]), node["message"]]
    raise ValueError("unmapped C++ node " + kind)


def qualify_definitions(unit, source):
    owners = {}
    def visit(node, scope, friend=False):
        if node.get("isImplicit"):
            return
        name = node.get("name", "")
        parent = owners.get(node.get("parentDeclContextId"))
        if friend and parent:
            # A hidden friend belongs to the namespace but has an unqualified written name.
            before = source[node["range"]["begin"]["offset"]:node["loc"]["offset"]]
            if not before.rstrip().endswith(b"::"):
                parent = None
        if parent and name:
            relative = parent[len(scope):] if parent[:len(scope)] == scope else parent
            node["name"] = "::".join([*relative, name])
        if node.get("kind") in {"NamespaceDecl", "CXXRecordDecl", "ClassTemplateSpecializationDecl", "ClassTemplatePartialSpecializationDecl"}:
            scope = (*(parent or scope), name)
            owners[node["id"]] = scope
        for child in node.get("inner", []):
            visit(child, scope, node.get("kind") == "FriendDecl")
    visit(unit, ())


def clang_binding(node, source, *, range_variable=False):
    # The deduced type omits auto; the location points to the opening bracket.
    written = source[node["range"]["begin"]["offset"]:node["loc"]["offset"]].decode()
    target = " ".join(re.findall(r"\w+|&&|&", written))
    values = node.get("inner", [])
    names = [c["name"] for c in values if c["kind"] == "BindingDecl"]
    return ["binding", target, names, None if range_variable else node["init"], None if range_variable else clang(values[0], source)]


def string_encoding(node):
    element_type = node["type"]["qualType"].partition("[")[0].removeprefix("const ")
    return {"char": "", "wchar_t": "L", "char8_t": "u8", "char16_t": "u", "char32_t": "U"}[element_type]


def written_strings(source):
    text = source.strip().decode()
    suffix = r"(?:(?:[^\W\d]|\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8})(?:\w|\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8})*)?"
    token = re.compile(r'\s*(?:u8|[uUL])?(?:R"([^ ()\\\s]{0,16})\(.*?\)\1"|"(?:\\.|[^"\\])*")' + suffix, re.DOTALL)
    pos, parts = 0, []
    while pos < len(text):
        part = token.match(text, pos)
        if part is None:
            raise ValueError(f"unexpected string literal sequence {text!r}")
        parts.append(part[0].lstrip())
        pos = part.end()
    return parts


def clang(node, source, *, member_body=False):
    k = node.get("kind")
    inner = [c for c in node.get("inner", []) if not c.get("isImplicit")]
    if k in {"CallExpr", "CXXMemberCallExpr", "CXXOperatorCallExpr"}:
        inner = [c for c in inner if c["kind"] != "CXXDefaultArgExpr"]
    if k == "CXXMemberCallExpr" and len(inner) == 1 and inner[0]["kind"] == "MemberExpr":
        member = inner[0]
        if member.get("name", "").startswith("operator ") and member.get("inner"):
            receiver = member["inner"][0]
            if receiver.get("range") == node.get("range"):
                return clang(receiver, source)
    if k in {"TranslationUnitDecl", "NamespaceDecl", "CXXRecordDecl"}:
        # A concrete variable instantiation repeats its primary/partial source range.
        inner = [c for c in inner if c["kind"] != "VarTemplateSpecializationDecl"
                 or not re.match(rb"template\s*<\s*[^>\s]", source[c["range"]["begin"]["offset"]:])]
    if k == "PackExpansionExpr":
        pattern, = inner
        return ["pack-expansion", clang(pattern, source)]
    if k == "CoawaitExpr":
        return ["AwaitExpression", clang(inner[0], source)]
    if k == "CoyieldExpr":
        call = inner[0]
        if call["kind"] != "CXXMemberCallExpr" or call["inner"][0].get("name") != "yield_value":
            raise ValueError("unexpected coroutine yield lowering")
        return ["YieldExpression", clang(call["inner"][1], source)]
    if k == "CoreturnStmt":
        return ["CoroutineReturnStatement", clang(inner[0], source)]
    if not k:
        return None
    if k == "FunctionDecl" and not member_body and any(c.get("kind") == "TemplateArgument" for c in inner):
        start = node["range"]["begin"]["offset"]
        if re.match(rb"template\s*<\s*>", source[start:]):
            loc = node["loc"]
            name = node["name"]
            if source[loc["offset"]+loc["tokLen"]:].lstrip().startswith(b"<"):
                args = [c["type"]["qualType"] for c in inner if c.get("kind") == "TemplateArgument"]
                name += "<" + ", ".join(args) + ">"
            return ["function-specialization", name, clang(node, source, member_body=True)]
    if k in {"CXXDestructorDecl", "CXXConstructorDecl", "CXXMethodDecl"} and not member_body:
        if re.match(rb"template\s*<\s*>", source[node["range"]["begin"]["offset"]:]):
            definition = clang(node, source, member_body=True)
            return ["function-specialization", node["name"], definition] if k == "CXXMethodDecl" else ["explicit-specialization", definition]
    if node.get("parentDeclContextId") and not member_body and "loc" in node:
        # JSON omits the enclosing class template header on out-of-class members.
        method = next((c for c in inner if c["kind"] == "CXXMethodDecl"), None) if k == "FunctionTemplateDecl" else None
        start = method["range"]["begin"]["offset"] if method else node["range"]["begin"]["offset"]
        prefix = source[start:node["loc"]["offset"]].decode()
        header = re.match(r"template\s*<([^<>]+)>", prefix)
        if header:
            declarator = prefix[header.end():].lstrip()
            headers = [header[1]]
            if not method:
                while following := re.match(r"template\s*<([^<>]+)>", declarator):
                    headers.append(following[1])
                    declarator = declarator[following.end():].lstrip()
            if method:
                declarator = re.sub(r"^template\s*<[^<>]+>", "", declarator)
            owner = re.search(r"((?:\w+::)*\w+<.*>(?:::\w+)*)\s*::\s*$", declarator)
            if not owner:
                raise ValueError(f"unmapped member definition {prefix}")
            parameters = []
            for parameter in header[1].split(","):
                kind, name = parameter.strip().rsplit(None, 1)
                parameters.append([kind, name, False, None])
            if method:
                method_params = [clang(c, source) for c in inner if c["kind"] in {
                    "TemplateTypeParmDecl", "NonTypeTemplateParmDecl", "TemplateTemplateParmDecl"}]
                definition = ["member-definition", method_params, owner[1], clang(method, source, member_body=True)]
                return ["template", parameters, None, definition]
            groups = [parameters]
            for group in headers[1:]:
                groups.append([[*part.strip().rsplit(None, 1), False, None] for part in group.split(",")])
            definition = ["member-definition", groups[-1], owner[1], clang(node, source, member_body=True)]
            for group in reversed(groups[:-1]):
                definition = ["template", group, None, definition]
            return definition
    if k == "EmptyDecl":
        return ["empty"]
    if k == "LinkageSpecDecl":
        return ["linkage", node["language"], node.get("hasBraces", False), *[clang(c, source) for c in inner]]
    if k == "AttributedStmt":
        return clang(inner[-1], source)
    if k in {"VarDecl", "FieldDecl", "NamespaceDecl", "EnumDecl", "EnumConstantDecl"}:
        inner = [c for c in inner if not c["kind"].endswith("Attr")]
    if k == "LabelStmt":
        return ["label", node["name"], clang(inner[0], source)]
    if k == "GotoStmt":
        end = node["range"]["end"]
        return ["goto", source[end["offset"]:end["offset"]+end["tokLen"]].decode()]
    if k in {"CaseStmt", "DefaultStmt"}:
        return ["case", clang(inner[0], source) if k == "CaseStmt" else None, clang(inner[-1], source)]
    if k == "CXXCatchStmt":
        param, body = inner
        return ["catch", [param["type"]["qualType"], param.get("name")] if param.get("kind") else None, clang(body, source)]
    if k == "CXXTryStmt":
        return ["try", *[clang(c, source) for c in inner]]
    if k == "CXXThrowExpr":
        return ["throw", clang(inner[0], source) if inner else None]
    if k == "TranslationUnitDecl":
        qualify_definitions(node, source)
    if k == "NamespaceDecl":
        inline = node.get("isInline", False)
        if inline:
            # Clang inherits inline on a reopening; Orion records the written specifier.
            begin = node["range"]["begin"]["offset"]
            inline = source[begin:begin+6] == b"inline"
        return ["namespace", node.get("name"), inline, *[clang(c, source) for c in inner]]
    if k in {"FileScopeAsmDecl", "GCCAsmStmt"}:
        # Clang omits the operand from GCCAsmStmt's JSON. The range covers asm(...).
        begin, end = node["range"]["begin"], node["range"]["end"]
        written = source[begin["offset"] + begin["tokLen"]:end["offset"]].strip()
        return ["asm", written_strings(written[1:])]
    if k == "StaticAssertDecl" and len(inner) == 2 and inner[1].get("kind") == "StringLiteral":
        span = inner[1]["range"]
        end = span["end"]
        return ["assert", clang(inner[0], source), written_strings(source[span["begin"]["offset"]:end["offset"] + end["tokLen"]])]
    if k == "EnumDecl":
        return ["enum", node.get("name"), "scopedEnumTag" in node, node.get("fixedUnderlyingType", {}).get("qualType"),
                *[clang(c, source) for c in inner]]
    if k == "EnumConstantDecl":
        return ["enumerator", node["name"], clang(inner[0], source) if inner else None]
    if k in {"UnresolvedUsingValueDecl", "UnresolvedUsingTypenameDecl"}:
        begin, end = node["range"]["begin"]["offset"], node["range"]["end"]
        stop = end["offset"] + end["tokLen"]
        target = source[begin:stop].decode().removeprefix("using").strip().removeprefix("typename").strip()
        return ["UsingDeclaration", target, k == "UnresolvedUsingTypenameDecl", source[stop:].lstrip().startswith(b"...")]
    if k in {"UsingDirectiveDecl", "UsingDecl", "UsingEnumDecl", "NamespaceAliasDecl"}:
        r = node["range"]
        raw = source[r["begin"]["offset"]:r["end"]["offset"] + r["end"]["tokLen"]].decode()
        if k == "NamespaceAliasDecl":
            return ["namespace_alias", node["name"], raw.split("=")[-1].strip()]
        if k == "UsingDecl":
            return ["UsingDeclaration", node["name"], False, False]
        return ["UsingEnumDeclaration" if k == "UsingEnumDecl" else "UsingDirective", raw.split()[-1]]
    if k == "CXXFoldExpr":
        # Clang 18 JSON retains operand slots and ranges but omits the opcode.
        _, left, right = node["inner"]
        start = left["range"]["end"] if left else node["range"]["begin"]
        end = right["range"]["begin"] if right else node["range"]["end"]
        middle = source[start["offset"] + start["tokLen"]:end["offset"]].decode()
        before, after = (part.strip() for part in middle.split("..."))
        if before and after and before != after:
            raise ValueError(f"unexpected reference fold operators {middle!r}")
        return ["fold", before or after, clang(left, source), clang(right, source)]
    if k == "SizeOfPackExpr":
        return ["sizeof...", node["name"]]
    if k == "CXXTypeidExpr":
        operand = ["type", node["typeArg"]["qualType"]] if "typeArg" in node else clang(inner[0], source)
        return ["typeid", operand]
    if k == "LambdaExpr":
        record, *values, body = node["inner"]
        call = next(c for c in record["inner"] if c.get("name") == "operator()")
        templates = []
        head_constraint = None
        if call["kind"] == "FunctionTemplateDecl":
            templates = [clang(c, source) for c in call["inner"] if c["kind"].endswith("ParmDecl") and not c.get("isImplicit")]
            head_constraint = next((clang(c, source) for c in call["inner"] if c["kind"].endswith(("Expr", "Operator"))), None)
            call = next(c for c in call["inner"] if c["kind"] == "CXXMethodDecl")
        default = re.match(rb"\[\s*([=&]|bitand\b)\s*(?=[],])", source[node["range"]["begin"]["offset"]:])
        fields = [c for c in record["inner"] if c["kind"] == "FieldDecl"]
        captures = []
        for field, value in zip(fields, values, strict=True):
            offset = field["loc"]["offset"]
            if offset >= body["range"]["begin"]["offset"]:
                continue  # Clang stores implicit captures alongside the written ones.
            name = source[offset:offset+field["loc"]["tokLen"]].decode()
            mode = "&" if field["type"]["qualType"].removesuffix("...").rstrip().endswith("&") else "="
            if name in {"this", "*"}:
                captures.append(["this", "*" if name == "*" else "=", ["name", "this"]])
            else:
                if value["kind"] == "ParenListExpr" and len(value["inner"]) == 1:
                    value, = value["inner"]
                captures.append([name, mode, clang(value, source)])
        params = [[c["type"]["qualType"], c.get("name")] for c in call["inner"] if c["kind"] == "ParmVarDecl"]
        trailing = next((clang(c, source) for c in call["inner"] if c["kind"].endswith(("Expr", "Operator"))), None)
        return ["lambda", ("&" if default[1] == b"bitand" else default[1].decode()) if default else None, captures, templates, params,
                ") const" not in call["type"]["qualType"], head_constraint, trailing, clang(body, source)]
    if k == "CXXOperatorCallExpr":
        callee = inner[0]
        while callee["kind"] == "ImplicitCastExpr":
            callee, = callee["inner"]
        operator = callee["referencedDecl"]["name"]
        if operator in {"operator++", "operator--"}:
            return ["prefix" if len(inner) == 2 else "postfix", operator[8:], clang(inner[1], source)]
        if operator in {"operator*", "operator&", "operator+", "operator-", "operator!", "operator~"} and len(inner) == 2:
            return ["prefix", operator.removeprefix("operator"), clang(inner[1], source)]
        if operator == "operator()":
            return ["call", *[clang(c, source) for c in inner[1:]]]
        if operator in {"operator->*", "operator+", "operator-", "operator*", "operator/", "operator%", "operator<<", "operator>>",
                        "operator&", "operator^", "operator|", "operator==", "operator!=", "operator<", "operator>",
                        "operator<=", "operator>=", "operator<=>", "operator&&", "operator||", "operator,", "operator=", "operator*=", "operator/=", "operator%=", "operator+=",
                        "operator-=", "operator>>=", "operator<<=", "operator&=", "operator^=", "operator|="} and len(inner) == 3:
            return [operator.removeprefix("operator"), clang(inner[1], source), clang(inner[2], source)]
        if operator == "operator[]" and len(inner) == 3:
            return ["subscript", clang(inner[1], source), clang(inner[2], source)]
        raise ValueError("unmapped overloaded call " + operator)
    if k == "CXXNewExpr":
        bound = None
        written_type = node["type"]["qualType"]
        written_array = node.get("isArray", False)
        if node.get("isArray"):
            size = inner.pop(0)
            # For an inferred bound Clang synthesizes a literal at the type name.
            begin = size["range"]["begin"]
            token = source[begin["offset"]:begin["offset"] + begin["tokLen"]]
            after = source[begin["offset"] + begin["tokLen"]:]
            inferred_bound = size["kind"] == "IntegerLiteral" and re.match(rb"\s*\[\s*\]", after)
            if size["kind"] == "IntegerLiteral" and re.fullmatch(rb"[A-Za-z_]\w*", token) and not inferred_bound:
                # For new A::Row the synthesized bound points at Row; use the complete written alias.
                prefix = source[node["range"]["begin"]["offset"]:begin["offset"] + begin["tokLen"]]
                alias = re.search(rb"(?:::)?[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*$", prefix)
                written_type = re.sub(rb"\s+", b"", alias[0]).decode() + " *"
                written_array = False
            elif not inferred_bound:
                bound = clang(size, source)
        initializer = None
        if style := node.get("initStyle"):
            value = inner.pop(0)
            if value["kind"] == "InitListExpr":
                args = value.get("inner", value.get("array_filler", [])[1:])
            elif value["kind"] == "ImplicitValueInitExpr":
                args = []
            else:
                args = [value]
            initializer = [style, *[clang(arg, source) for arg in args]]
        elif inner and inner[0]["kind"] == "CXXConstructExpr":
            ctor = inner[0]
            if not ctor.get("inner") and ctor["range"]["begin"] == ctor["range"]["end"]:
                inner.pop(0)  # Implicit default construction at the allocated type.
        return ["new", node.get("isGlobal", False), written_type, written_array,
                bound, initializer, [clang(arg, source) for arg in inner]]
    if k == "CXXDeleteExpr":
        return ["delete", node.get("isGlobal", False), node.get("isArrayAsWritten", False), clang(inner[0], source)]
    if k == "UnaryExprOrTypeTraitExpr":
        operand = ["type", node["argType"]["qualType"]] if "argType" in node else clang(inner[0], source)
        return ["prefix", node["name"], operand]
    if k == "CXXNoexceptExpr":
        return ["noexcept", clang(inner[0], source)]
    cast_names = {"CStyleCastExpr": "c-style", "CXXStaticCastExpr": "static_cast", "CXXConstCastExpr": "const_cast",
                  "CXXDynamicCastExpr": "dynamic_cast", "CXXReinterpretCastExpr": "reinterpret_cast"}
    if k in cast_names:
        target = node["type"]["qualType"]
        if node["valueCategory"] != "prvalue":
            target += " &" if node["valueCategory"] == "lvalue" else " &&"
        return [cast_names[k], target, clang(inner[0], source)]
    if k in {"TypedefDecl", "TypeAliasDecl"}:
        spelling = node["type"]["qualType"]
        if k == "TypeAliasDecl" and "<template " in spelling:
            # Clang's display string drops the owner of a dependent template name.
            end = node["range"]["end"]
            written = source[node["loc"]["offset"]:end["offset"]+end["tokLen"]].decode()
            spelling = written.split("=", 1)[1].strip()
        elif k == "TypeAliasDecl" and "::" in spelling:
            end = node["range"]["end"]
            written = source[node["loc"]["offset"]:end["offset"]+end["tokLen"]].decode().partition("=")[2].strip()
            if "::template " in written and written.replace("::template ", "::") == spelling:
                spelling = written
        return ["using" if k == "TypeAliasDecl" else "typedef", node["name"], spelling]
    if k in {"ClassTemplateSpecializationDecl", "ClassTemplatePartialSpecializationDecl",
             "VarTemplateSpecializationDecl", "VarTemplatePartialSpecializationDecl"}:
        params = [c for c in inner if c["kind"] in {"TemplateTypeParmDecl", "NonTypeTemplateParmDecl", "TemplateTemplateParmDecl"}]
        arguments = []
        for arg in (c for c in inner if c["kind"] == "TemplateArgument"):
            for item in arg.get("inner", []) if arg.get("isPack") else [arg]:
                if "type" in item:
                    spelling = item["type"]["qualType"]
                    for param in params:
                        spelling = spelling.replace(f"type-parameter-{param['depth']}-{param['index']}", param["name"])
                elif item.get("isExpr"):
                    span = item["inner"][0]["range"]
                    spelling = source[span["begin"]["offset"]:span["end"]["offset"] + span["end"]["tokLen"]].decode()
                else:
                    spelling = str(item["value"])
                arguments.append(spelling)
        if k == "ClassTemplateSpecializationDecl":
            start = node["range"]["begin"]["offset"]
            head = re.match(rb"(extern\s+)?template\s+(class|struct|union)\s+([\w:]+)\s*<", source[start:])
            if head:
                return ["class-instantiation", bool(head[1]), head[2].decode(),
                        head[3].decode() + "<" + ", ".join(arguments) + ">"]
        record = {**node, "kind": "VarDecl" if k.startswith("VarTemplate") else "CXXRecordDecl", "name": node["name"] + "<" + ", ".join(arguments) + ">",
                  "inner": [c for c in inner if c["kind"] != "TemplateArgument" and c not in params]}
        definition = clang(record, source)
        return (["template", [clang(c, source) for c in params], None, definition] if params
                else ["explicit-specialization", definition])
    if k == "CXXRecordDecl":
        bases = [[b["type"]["qualType"], None if b["writtenAccess"] == "none" else b["writtenAccess"], b.get("isVirtual", False), b.get("isPackExpansion", False)]
                 for b in node.get("bases", [])]
        return [node["tagUsed"], node.get("name"), any(c["kind"] == "FinalAttr" for c in inner), bases,
                *[clang(c, source) for c in inner if not c["kind"].endswith("Attr")]]
    if k == "FriendDecl":
        if "type" in node:
            spelling = node["type"]["qualType"]
            begin, end = node["range"]["begin"], node["range"]["end"]
            written = source[begin["offset"]:end["offset"] + end["tokLen"]].decode().removeprefix("friend ").strip()
            if "::template " in written and written.replace("::template ", "::") == spelling:
                spelling = written
            return ["friend", spelling]
        template, = inner
        if template["kind"] == "FunctionDecl":
            return clang(template, source)
        params = [clang(c, source) for c in template["inner"] if c["kind"].endswith("ParmDecl")]
        record = next(c for c in template["inner"] if c["kind"] == "CXXRecordDecl")
        return ["template", params, None, ["friend", record["tagUsed"] + " " + record["name"]]]
    if k == "AccessSpecDecl":
        return ["access", node["access"]]
    if k == "ConceptDecl":
        return ["template", [clang(c, source) for c in inner[:-1]], None,
                ["concept", node["name"], clang(inner[-1], source)]]
    if k == "ConceptSpecializationExpr":
        span = node["range"]
        begin, end = span["begin"]["offset"], span["end"]["offset"] + span["end"]["tokLen"]
        name = source[begin:end].decode().split("<", 1)[0].strip()
        args = [c["type"]["qualType"] for c in inner if c["kind"] == "TemplateArgument" and
                begin <= c.get("range", {}).get("begin", {}).get("offset", -1) < end and b"<" in source[begin:end]]
        return ["concept-id", name, args]
    if k == "RequiresExpr":
        params = [[c["type"]["qualType"], c.get("name")] for c in inner if c["kind"] == "ParmVarDecl"]
        return ["requires", params, *[clang(c, source) for c in inner if c["kind"] != "ParmVarDecl"]]
    if k == "SimpleRequirement":
        return ["simple", clang(inner[0], source)]
    if k == "TypeRequirement":
        return ["type-requirement", inner[0]["type"]["qualType"].removeprefix("typename ")]
    if k == "CompoundRequirement":
        return ["compound", clang(inner[0], source), node.get("noexcept", False), clang(inner[1], source) if len(inner) == 2 else None]
    if k == "NestedRequirement":
        return ["nested", clang(inner[0], source)]
    if k in {"ClassTemplateDecl", "FunctionTemplateDecl", "TypeAliasTemplateDecl", "VarTemplateDecl"}:
        params = [clang(c, source) for c in inner if c["kind"] in {"TemplateTypeParmDecl", "NonTypeTemplateParmDecl", "TemplateTemplateParmDecl"}]
        definition = next(c for c in inner if c["kind"] in {"CXXRecordDecl", "FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl", "CXXDeductionGuideDecl", "TypeAliasDecl", "VarDecl"}
                          and not any(i["kind"] == "TemplateArgument" for i in c.get("inner", [])))
        if not params and any(c.get("isImplicit") and c["kind"] == "TemplateTypeParmDecl" for c in node["inner"]):
            return clang(definition, source)
        constraints = [c for c in inner[:inner.index(definition)] if c["kind"] not in {
            "TemplateTypeParmDecl", "NonTypeTemplateParmDecl", "TemplateTemplateParmDecl"}]
        return ["template", params, clang(constraints[0], source) if constraints else None, clang(definition, source)]
    if k == "TemplateTypeParmDecl":
        constraint = next((c for c in inner if c["kind"] == "ConceptSpecializationExpr"), None)
        key = clang(constraint, source) if constraint else node["tagUsed"]
        default = node.get("defaultArg", {})
        written = default.get("type", {}).get("qualType") if "inherited from" not in default else None
        return [key, node.get("name"), node.get("isParameterPack", False), written]
    if k == "TemplateTemplateParmDecl":
        params = [clang(c, source) for c in inner if c["kind"].endswith("TemplateParmDecl") or c["kind"] == "TemplateTypeParmDecl"]
        default = None
        if "defaultArg" in node:
            argument = next(c for c in inner if c["kind"] == "TemplateArgument")
            span = argument["range"]
            default = source[span["begin"]["offset"]:span["end"]["offset"] + span["end"]["tokLen"]].decode()
        return ["template-parameter", node.get("name"), node.get("isParameterPack", False), params, default]
    if k == "NonTypeTemplateParmDecl":
        return [node["type"]["qualType"], node.get("name"), node.get("isParameterPack", False),
                clang(inner[-1]["inner"][0], source) if node.get("defaultArg") and "inherited from" not in node["defaultArg"] else None]
    if k == "BuiltinBitCastExpr":
        return ["builtin-bit-cast", node["type"]["qualType"], clang(inner[0], source)]
    if k == "CXXDeductionGuideDecl":
        params = [[c["type"]["qualType"], c.get("name")] for c in inner if c["kind"] == "ParmVarDecl"]
        prefix = source[node["range"]["begin"]["offset"]:node["loc"]["offset"]]
        return ["guide", node["name"].removeprefix("<deduction guide for ").removesuffix(">"), params,
                node["type"]["qualType"].rsplit(" -> ", 1)[1], written_explicit(prefix)]
    if k == "CXXConversionDecl":
        begin = node["range"]["begin"]["offset"]
        explicit = b"explicit" in source[begin:node["loc"]["offset"]].split()
        body = next((c for c in inner if c["kind"] in {"CompoundStmt", "CXXTryStmt"}), {})
        constraint = next((c for c in inner if c["kind"].endswith(("Expr", "Operator"))), {})
        return ["conversion", node["name"].partition("operator ")[0].removesuffix("::") or None, node["type"]["qualType"], explicit, clang(body, source), clang(constraint, source)]
    if k in {"FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl", "CXXDestructorDecl"}:
        params = [[c["type"]["qualType"], c.get("name")] for c in inner if c["kind"] == "ParmVarDecl"]
        body = next((c for c in inner if c["kind"] in {"CompoundStmt", "CXXTryStmt"}), {})
        specifier = node.get("explicitlyDefaulted")
        if node.get("explicitlyDeleted"):
            specifier = "delete"
        if node.get("pure"):
            specifier = "pure"
        attributes = sorted(c["kind"].removesuffix("Attr").lower() for c in inner
                            if c["kind"] in {"OverrideAttr", "FinalAttr"} and not c.get("inherited"))
        if k in {"CXXConstructorDecl", "CXXDestructorDecl"}:
            start = node["loc"]["offset"]
            before_name = source[node["range"]["begin"]["offset"]:start]
            inits = []
            for init in (c for c in inner if c["kind"] == "CXXCtorInitializer"):
                value, = init["inner"]
                if value["range"]["begin"]["offset"] == start:
                    continue  # implicit default initialization of an omitted base/member
                if init.get("anyInit"):
                    target = init["anyInit"]["name"]
                else:
                    target = (init.get("baseInit") or init["delegatingInit"])["qualType"]
                args = value.get("inner", []) if value["kind"] in {"CXXConstructExpr", "InitListExpr", "ParenListExpr"} else [value]
                inits.append([target, value.get("list", False) or value["kind"] == "InitListExpr", [clang(c, source) for c in args]])
            tag = "ConstructorDeclaration" if k == "CXXConstructorDecl" else "DestructorDeclaration"
            constraint = next((c for c in inner if c["kind"].endswith(("Expr", "Operator"))), {})
            return [tag, re.sub(r"<[^<>]*>$", "", node["name"]), params, written_explicit(before_name), node.get("virtual", False),
                    specifier, attributes, inits, None if specifier else clang(body, source), clang(constraint, source)]
        constraints = [c for c in inner if c["kind"] not in {"ParmVarDecl", "CompoundStmt", "CXXTryStmt", "TemplateArgument"}
                       and not c["kind"].endswith("Attr")]
        signature = node["type"]["qualType"]
        if signature.startswith("(lambda at ") and source[node["range"]["begin"]["offset"]:node["loc"]["offset"]].strip() == b"auto":
            signature = re.sub(r"^\(lambda at .*?:\d+:\d+\)", "auto", signature)
        gnu_names = {"ColdAttr": "cold", "AlwaysInlineAttr": "always_inline", "AbiTagAttr": "abi_tag"}
        gnu = [gnu_names[c["kind"]] for c in inner if c["kind"] in gnu_names]
        if " __attribute__((noreturn))" in signature:
            signature = signature.replace(" __attribute__((noreturn))", "")
            gnu.append("noreturn")
        return ["function", node["name"], sorted(gnu), signature, params, node.get("constexpr", False),
                clang(body, source), node.get("virtual", False), specifier, attributes,
                clang(constraints[0], source) if constraints else None,
                *([["asm-label", node["mangledName"]]] if any(c["kind"] == "AsmLabelAttr" for c in inner) else [])]
    if k == "FieldDecl" and node.get("isBitfield"):
        return ["bit-field", node.get("name"), node["type"]["qualType"], clang(inner[0], source),
                clang(inner[1], source) if len(inner) > 1 else None]
    if k in {"VarDecl", "FieldDecl"}:
        spelling = re.sub(r"\(unnamed (struct|class|union|enum) at [^\n]+?:\d+:\d+\)", "(unnamed)", node["type"]["qualType"])
        spelling = re.sub(r" \((&{1,2}|\*)\)$", r" \1", spelling)
        if k == "VarDecl":
            # Recover a written placeholder from the declarator prefix before comparing types.
            prefix = source[node["range"]["begin"]["offset"]:node["loc"]["offset"]].decode()
            if re.fullmatch(r"\s*decltype\s*\(\s*auto\s*\)\s*", prefix):
                spelling = "decltype(auto)"
            elif re.fullmatch(r"\s*(?:(?:const|volatile|constexpr|static|inline)\s+)*auto(?:\s*(?:const|volatile|&&|[&*]))*\s*", prefix):
                words = re.findall(r"\w+|&&|[&*]", prefix)
                spelling = " ".join("const" if w == "constexpr" else w for w in words if w not in {"static", "inline"})
        init = inner[-1] if inner else None
        # An implicitly invoked default constructor spans only the variable name.
        if init and init["kind"] == "CXXConstructExpr" and all(
            loc.get("offset") == node["loc"]["offset"] for loc in init["range"].values()
        ):
            init = None
        return ["var", node["name"], spelling, clang(init, source) if init else None]
    if k in {"MemberExpr", "CXXDependentScopeMemberExpr", "UnresolvedMemberExpr"} and inner:
        receiver = inner[0]
        start, end = receiver["range"]["end"], node["range"]["end"]
        spelling = source[start["offset"] + start["tokLen"]:end["offset"] + end["tokLen"]].decode().strip()
        tokens = re.findall(r"->|::|\w+|[^\s]", spelling)
        op_name = node.get("name", node.get("member", ""))
        if (tokens and tokens[0] in {".", "->"} and tokens[-1] == ">" and "operator" in tokens
                and (re.match(r"operator[^\w\s]", op_name) or op_name in {"operator new", "operator new[]", "operator delete", "operator delete[]", "operator co_await"})):
            return ["member-operator-template", tokens[0], clang(receiver, source), tokens[1:]]
        if tokens and tokens[0] in {".", "->"} and tokens[-1] == ">" and "::" in tokens:
            # Locate the outermost argument list, skipping qualifiers inside its arguments.
            depth = 0
            for i in range(len(tokens)-1, 1, -1):
                depth += (tokens[i] == ">") - (tokens[i] == "<")
                if not depth:
                    owner_end = i-3 if tokens[i-2] == "template" else i-2
                    if owner_end > 0 and tokens[owner_end] == "::":
                        return ["qualified-member-template", tokens[0], clang(receiver, source), tokens[1:]]
                    break
    if (k in {"MemberExpr", "CXXDependentScopeMemberExpr"} and node.get("name", node.get("member", "")).startswith("operator ")
            or k == "DeclRefExpr" and node.get("referencedDecl", {}).get("kind") == "CXXConversionDecl"):
        start, end = node["range"]["begin"], node["range"]["end"]
        receiver = inner[0] if inner else None
        if receiver and not receiver.get("implicit"):
            loc = receiver["range"]["end"]
            offset = loc["offset"] + loc["tokLen"]
        else:
            offset = start["offset"]
        written = source[offset:end["offset"] + end["tokLen"]].decode().strip()
        match = re.fullmatch(r"(?:(->|\.)\s*)?(?:(.+?)::\s*)?operator\s+(.+)", written, re.S)
        if match and not re.match(r'(?:new|delete|co_await)\b|"', match[3]):
            ident = conversion_name(match[2], match[3])
            return [match[1], clang(receiver, source), ident] if match[1] else ident
    if k in {"UnresolvedMemberExpr", "MemberExpr"} and inner:
        # The JSON dump omits the written template arguments on an unresolved
        # nondependent receiver. Its range ends at the closing angle bracket.
        start = inner[0]["range"]["end"]
        end = node["range"]["end"]
        suffix = source[start["offset"]+start["tokLen"]:end["offset"]+end["tokLen"]].decode().strip()
        if k == "MemberExpr" and node.get("name", "").startswith("~"):
            op = "->" if node["isArrow"] else "."
            return [op, clang(inner[0], source), suffix.removeprefix(op).strip()]
        match = re.fullmatch(r"(->|\.)\s*(\w+\s*<.*>)", suffix, re.S)
        if match:
            return ["member-template-id", match[1], clang(inner[0], source), re.sub(r"\s+", "", match[2])]
        qualified = re.fullmatch(r"(->|\.)\s*((?:\w+::)+\w+)", suffix)
        if qualified and k == "MemberExpr":
            return [qualified[1], clang(inner[0], source), qualified[2]]
    if k in {"StringLiteral", "UserDefinedLiteral"}:
        span = node["range"]
        end = span["end"]
        text = source[span["begin"]["offset"]:end["offset"] + end["tokLen"]]
        if k == "StringLiteral":
            return ["string", written_strings(text), None, string_encoding(node)]
        if re.match(rb"""(?:u8|[uUL])?(?:R?"|')""", text):
            callee = inner[0]
            while callee["kind"] == "ImplicitCastExpr":
                callee, = callee["inner"]
            suffix = callee["referencedDecl"]["name"].removeprefix('operator""')
            if re.match(rb"(?:u8|[uUL])?'", text):
                return ["character-udl", text.decode(), suffix]
            operand = inner[1]
            while operand["kind"] == "ImplicitCastExpr":
                operand, = operand["inner"]
            return ["string", written_strings(text), suffix, string_encoding(operand)]
    if k in {"DeclRefExpr", "DependentScopeDeclRefExpr", "UnresolvedLookupExpr", "UnresolvedMemberExpr", "IntegerLiteral", "FloatingLiteral", "CharacterLiteral", "CXXNullPtrLiteralExpr", "CXXBoolLiteralExpr", "UserDefinedLiteral"}:
        r = node["range"]
        raw = source[r["begin"]["offset"]:r["end"]["offset"] + r["end"]["tokLen"]].decode()
        return ["name" if k in {"DeclRefExpr", "DependentScopeDeclRefExpr", "UnresolvedLookupExpr", "UnresolvedMemberExpr"} else "literal", raw]
    if k == "CXXPseudoDestructorExpr":
        receiver, = inner
        start, end = receiver["range"]["end"], node["range"]["end"]
        suffix = source[start["offset"]+start["tokLen"]:end["offset"]+end["tokLen"]].decode().strip()
        op = "->" if suffix.startswith("->") else "."
        return [op, clang(receiver, source), suffix.removeprefix(op).strip()]
    if k == "CXXThisExpr":
        return ["this"]
    if k == "CXXDependentScopeMemberExpr" and not node.get("hasTemplateKeyword"):
        op = "->" if node["isArrow"] else "."
        receiver = inner[0]
        start, end = receiver["range"]["end"], node["range"]["end"]
        written = source[start["offset"]+start["tokLen"]:end["offset"]+end["tokLen"]].decode().strip()
        member = written.removeprefix(op).strip() if "::" in written else node["member"]
        return [op, clang(receiver, source), member]
    if k == "CXXDependentScopeMemberExpr" and node.get("hasTemplateKeyword"):
        args = [arg["type"]["qualType"] for arg in node.get("explicitTemplateArgs", [])]
        return ["member-template", "->" if node["isArrow"] else ".", clang(inner[0], source), node["member"], args]
    if k == "MemberExpr":
        receiver = inner[0]
        while receiver["kind"] == "ImplicitCastExpr":
            receiver, = receiver["inner"]
        if ((receiver.get("referencedDecl", {}).get("name") == "" or receiver.get("kind") == "MemberExpr" and receiver.get("name") == "")
                and "(anonymous union at " in receiver["type"]["qualType"]):
            return ["name", node["name"]]
        if receiver.get("implicit") and receiver["kind"] == "CXXThisExpr":
            span = node["range"]
            end = span["end"]
            written = source[span["begin"]["offset"]:end["offset"]+end["tokLen"]].decode()
            return ["name", written if written.endswith(">") else node["name"]]
        return ["->" if node["isArrow"] else ".", clang(inner[0], source), node["name"]]
    if k == "DecompositionDecl":
        return clang_binding(node, source)
    if k == "CXXForRangeStmt":
        range_decl = inner[1]["inner"][0]
        loop_var = inner[-2]["inner"][0]
        init = [["init", clang(inner[0], source)]] if inner[0].get("kind") else []
        binding = ([clang_binding(loop_var, source, range_variable=True)] if loop_var["kind"] == "DecompositionDecl"
                   else [loop_var["type"]["qualType"], loop_var["name"]])
        return ["range-for", *init, *binding, clang(range_decl["inner"][0], source),
                clang(inner[-1], source)]
    if k in {"IfStmt", "WhileStmt", "SwitchStmt"}:
        tag = {"IfStmt": "if", "WhileStmt": "WhileStatement", "SwitchStmt": "SwitchStatement"}[k]
        result = [tag, node.get("isConstexpr", False)] if k == "IfStmt" else [tag]
        if node.get("hasInit"):
            result.append(["init", clang(inner.pop(0), source)])
        result.append(clang(inner.pop(0), source))
        if node.get("hasVar"):
            inner.pop(0)  # implicit conversion of the declared condition variable
        result.extend(clang(c, source) for c in inner)
        if k == "IfStmt" and not node.get("hasElse"):
            result.append(None)
        return result
    if (k == "InitListExpr" and "offset" in node["range"]["begin"]
            and re.compile(rb"\{\s*\.").match(source, node["range"]["begin"]["offset"])):
        # For a known aggregate Clang drops the field labels and fills omitted fields.
        # For a dependent aggregate it retains DesignatedInitExpr nodes.
        pos = node["range"]["begin"]["offset"] + 1
        values = []
        for child in inner:
            value = child["inner"][0] if child["kind"] == "DesignatedInitExpr" else child
            span = value.get("range", {})
            if "offset" not in span.get("begin", {}):
                continue
            prefix = source[pos:span["begin"]["offset"]].decode()
            field = re.fullmatch(r"\s*,?\s*\.\s*(\w+)\s*(=?)\s*", prefix)
            if not field:
                raise ValueError(f"unexpected field initializer prefix {prefix!r}")
            values.append(["designator", field[1], field[2] or "{}", clang(value, source)])
            pos = span["end"]["offset"] + span["end"]["tokLen"]
        trailing = source[pos:node["range"]["end"]["offset"]].strip() == b","
        return ["designated-list", trailing, *values]
    if k == "NullStmt":
        return None
    children = [clang(c, source) for c in inner]
    if k == "TypeTraitExpr":
        # Clang JSON exposes the source range but omits the trait and its type operands.
        begin, end = node["range"]["begin"], node["range"]["end"]
        spelling = source[begin["offset"]:end["offset"] + end["tokLen"]].decode()
        return ["builtin-type-trait", re.sub(r"\s+", "", spelling)]
    if k == "CXXUnresolvedConstructExpr":
        return ["list-cast" if node.get("list") else "functional-cast", node["type"]["qualType"], *children]
    if k == "CXXConstructExpr" and len(children) == 1 and not node.get("list"):
        return children[0]
    if k == "CXXTemporaryObjectExpr":
        if node.get("list"):
            return ["list-cast", node["type"]["qualType"], ["initializer", *children]]
        return ["functional-cast", node["type"]["qualType"], *children]
    if k == "CXXScalarValueInitExpr":
        return ["functional-cast", node["type"]["qualType"]]
    if k == "CXXFunctionalCastExpr":
        return ["functional-cast", node["type"]["qualType"], *children]
    if k == "ParenExpr":
        return ["paren", *children]
    if k == "DeclStmt" and len(children) > 1:
        return ["group", *children]
    if k in {"DeclStmt", "ImplicitCastExpr", "ConstantExpr", "ExprWithCleanups", "MaterializeTemporaryExpr"}:
        if len(children) != 1:
            raise ValueError(f"unexpected {k} arity {len(children)}")
        return children[0]
    if k in {"BinaryOperator", "CompoundAssignOperator"}:
        return [node["opcode"], *children]
    if k == "UnaryOperator":
        return ["postfix" if node["isPostfix"] else "prefix", node["opcode"], *children]
    if k == "ForStmt":
        return ["for", children[0], children[1] if inner[1].get("kind") else children[2], *children[3:]]
    kinds = {"TranslationUnitDecl": "unit", "ExportDecl": "export", "CompoundStmt": "block",
             "ConditionalOperator": "?:", "ReturnStmt": "return", "CallExpr": "call", "CXXMemberCallExpr": "call", "InitListExpr": "initializer",
             "ArraySubscriptExpr": "subscript", "StaticAssertDecl": "assert", "WhileStmt": "WhileStatement",
             "SwitchStmt": "SwitchStatement", "DoStmt": "DoWhileStatement", "BreakStmt": "BreakStatement",
             "ContinueStmt": "ContinueStatement"}
    if k not in kinds:
        raise ValueError("unmapped Clang C++ node " + k)
    return [kinds[k], *children]


def check_character_widths(ast, reference):
    values = {n["name"]: n["inner"][-1] for n in reference["inner"] if n["kind"] == "VarDecl"}
    prefixes = {"char8_t": "u8", "char16_t": "u", "char32_t": "U", "wchar_t": "L"}
    for decl in ast["declarations"]:
        literal = decl["initializer"]
        ref = values[decl["name"]]
        prefix = prefixes.get(ref["type"]["qualType"])
        if ref["kind"] != "CharacterLiteral" or prefix != literal.get("encodingPrefix"):
            raise ValueError(f"{decl['name']}: character literal type differs")
        if prefix and literal["codeUnit"] != ref["value"]:
            raise ValueError(f"{decl['name']}: character code unit differs")


def check_numeric_suffixes(ast, reference):
    declarations = {n["name"]: n for n in reference["inner"] if n["kind"] == "VarDecl"}
    for node in ast["declarations"]:
        if node["type"] != "VariableDeclaration":
            continue
        literal = node["initializer"]
        ref = declarations[node["name"]]["inner"][-1]
        ud = literal.get("userDefined")
        if ref["kind"] != "UserDefinedLiteral":
            if ud:
                raise ValueError(f"{node['name']}: ordinary literal acquired a user-defined suffix")
            continue
        callee, operand = ref["inner"]
        while callee["kind"] == "ImplicitCastExpr":
            callee, = callee["inner"]
        kind = {"IntegerLiteral": "integer", "FloatingLiteral": "floating"}[operand["kind"]]
        if not ud or ud["kind"] != kind or callee["referencedDecl"]["name"] != 'operator""' + ud["suffix"]:
            raise ValueError(f"{node['name']}: literal kind or operator differs")
        number = ud["number"].replace("'", "")
        if kind == "integer":
            base = 8 if re.fullmatch(r"0[0-7]*", number) else 0
            equal = int(number, base) == int(operand["value"])
        else:
            # The fixture uses exactly representable binary floating-point values.
            value = float.fromhex(number) if number.lower().startswith("0x") else float(number)
            equal = value == float(operand["value"])
        if not equal:
            raise ValueError(f"{node['name']}: numeric part differs from Clang's cooked operand")


def check_attribute_owners(ast, reference, source):
    # Clang discards unknown and empty attributes. Compare the retained ones
    # by owner and argument; the CLI tests cover the complete written lists.
    names = {"WarnUnusedResultAttr": "nodiscard", "UnusedAttr": "maybe_unused",
             "AlignedAttr": "alignas", "LikelyAttr": "likely", "DeprecatedAttr": "deprecated", "AbiTagAttr": "__abi_tag__"}
    actual, expected = [], []

    def visit_orion(node):
        if isinstance(node, list):
            for item in node:
                visit_orion(item)
        elif isinstance(node, dict):
            owner = node.get("name") or node.get("type")
            if node.get("type") == "NamespaceDefinition" and node["path"]:
                owner = node["path"][-1]["name"]
            for spec in [*node.get("attributes", []), *node.get("declaratorAttributes", []), *node.get("gnuAttributes", [])]:
                if spec["type"] == "AlignmentSpecifier":
                    actual.append((owner, "alignas", type_name(spec["operand"]) + ("..." if spec["pack"] else "")))
                else:
                    for item in spec["items"]:
                        if item and not item["namespace"] and not spec.get("usingNamespace") and item["name"] in names.values():
                            actual.append((owner, item["name"], "".join(item["arguments"] or [])))
            for item in node.values():
                visit_orion(item)

    def visit_clang(node):
        if node.get("isImplicit"):
            return
        for child in node.get("inner", []):
            kind = child.get("kind")
            if kind in names:
                if child.get("inherited"):
                    continue
                offset = child["range"]["begin"]["offset"]
                owner = node.get("name") if node["kind"] != "AttributedStmt" else node["inner"][-1]["kind"].removesuffix("Stmt") + "Statement"
                if kind == "AlignedAttr":
                    arg = re.match(rb"alignas\s*\(\s*([^()]*)\)", source[offset:])[1].strip().decode()
                else:
                    end = child["range"]["end"]
                    spelling = source[offset:end["offset"] + end["tokLen"]].decode()
                    arg = spelling.partition("(")[2].removesuffix(")").strip()
                expected.append((owner, names[kind], arg))
            else:
                visit_clang(child)

    visit_orion(ast)
    visit_clang(reference)
    if sorted(actual) != sorted(expected):
        raise ValueError(f"attribute owners or arguments differ: {actual} vs {expected}")


def check_preprocessing_imports(stage, compiler):
    header = stage / "HeaderUnit.hpp"
    header.write_bytes((FIXTURES / header.name).read_bytes())
    header_bmi = stage / "HeaderUnit.pcm"
    module_bmi = stage / "Scale.pcm"
    subprocess.run([*compiler, "-x", "c++-header", "-fmodule-header=user", header, "-o", header_bmi], check=True)
    subprocess.run([*compiler, "-x", "c++-module", "--precompile", FIXTURES / "Scale.cppm", "-o", module_bmi], check=True)
    cases = [
        ("", '"HeaderUnit.hpp"', '"HeaderUnit.hpp"', "header"),
        ('#define H "HeaderUnit.hpp"\n', "H", '"HeaderUnit.hpp"', "header"),
        ("#define H <HeaderUnit.hpp>\n", "H", "<HeaderUnit.hpp>", "header"),
        ("#define NAME sample.scale\n", "NAME", "sample.scale", "module"),
    ]
    source = stage / "use.cpp"
    expected = stage / "use.ii"
    for directives, operand, target, kind in cases:
        assertion = ("static_assert(header_value == 3);" if kind == "header" else
                     "static_assert(sample::math::scaled(2, sample::math::Mode::add) == 5);")
        source.write_text(f"{directives}import {operand};\n{assertion}\n")
        expected.write_text(f"import {target};\n{assertion}\n")
        includes = ["-I", str(stage)]
        bmi = str(header_bmi) if kind == "header" else "sample.scale=" + str(module_bmi)
        # Clang's -E emits a resolved header path without delimiters for a loaded header unit.
        # Compile the original import against its BMI and require the imported value in static_assert.
        subprocess.run([*compiler, *includes, "-Wno-experimental-header-units", "-fmodule-file=" + bmi,
                        "-fsyntax-only", source], check=True)
        expanded = get_pipeline(source, c_includes=[str(stage)]).preprocess_file(source)
        if [t.spelling for t in CppSource(expanded).tokens()] != [t.spelling for t in CppSource(expected.read_text()).tokens()]:
            raise ValueError(f"preprocessing import {operand}: unexpected expansion {expanded}")
        ast = cli(source, *includes)
        if (ast != cli(expected) or ast["declarations"][0] != {"type": "ImportDeclaration", "kind": kind, "target": target}
                or ast["declarations"][1]["type"] != "StaticAssertion"):
            raise ValueError(f"preprocessing import {operand}: {ast}")
    return {("control-line", "2"), ("pp-import", "1"), ("pp-import", "2"), ("pp-import", "3")}


def check_preprocessing(stage, compiler):
    docs = ROOT / "docs/conformance"
    with (docs / "cpp20.tsv").open() as stream:
        inventory = {(r["rule"], r["alternative"]) for r in csv.DictReader(stream, delimiter="\t")}
    cases = json.loads((docs / "cpp20-preprocessing.json").read_text())
    seen, checked = set(), 0
    for index, case in enumerate(cases):
        folder = stage / f"pp-case-{index}"
        folder.mkdir()
        include = folder / "include"
        include.mkdir()
        for name, text in case.get("headers", {}).items():
            header = include / name
            header.parent.mkdir(exist_ok=True, parents=True)
            header.write_text(text)
        source = folder / "case.cpp"
        source.write_text(case["source"])
        for variant in case["variants"]:
            defines = variant.get("defines", [])
            options = ["-I", str(include), *["-D" + d for d in defines]]
            ref = subprocess.run([*compiler, "-E", "-P", *options, source], capture_output=True)
            if "diagnostic" in variant:
                run = subprocess.run([sys.executable, "-m", "orionparser", "parse", source, "--json", *options], capture_output=True)
                for result, column_key in ((ref, "clang_column"), (run, "cli_column")):
                    stderr = result.stderr.decode()
                    first = re.search(rf"{re.escape(str(source))}:(\d+):(\d+): (?:fatal )?error: ([^\n]+)", stderr)
                    if (not result.returncode or first is None or int(first[1]) != variant["line"]
                            or column_key in variant and int(first[2]) != variant[column_key]
                            or variant["diagnostic"] not in first[3]):
                        raise ValueError(f"{case['case']}: {stderr}")
                if json.loads(run.stdout) is not None:
                    raise ValueError(f"{case['case']}: preprocessing error produced an AST")
            else:
                ref.check_returncode()
                reference = folder / "reference.ii"
                reference.write_bytes(ref.stdout)
                expected = folder / "expected.ii"
                expected.write_text(variant["expanded"])
                expanded = get_pipeline(source, c_includes=[str(include)], c_defines=defines).preprocess_file(source)
                spellings = [tuple(t.spelling for t in CppSource(text).tokens())
                             for text in (variant["expanded"], expanded, ref.stdout.decode())]
                if len(set(spellings)) != 1:
                    raise ValueError(f"{case['case']} {defines}: expanded tokens differ: {spellings}")
                dump = subprocess.check_output([*compiler, "-x", "c++-cpp-output", "-fsyntax-only", "-Xclang", "-ast-dump=json", reference])
                tree = clang(json.loads(dump), ref.stdout)
                for path, args in ((source, options), (reference, []), (expected, [])):
                    if orion(cli(path, *args)) != tree:
                        raise ValueError(f"{case['case']} {defines}: {path.name} AST differs")
            checked += 1
        seen.update(tuple(rule.rsplit(".", 1)) for rule in case["rules"])
    seen.update(check_preprocessing_imports(stage, compiler))
    if seen - inventory:
        raise ValueError(f"unindexed preprocessing alternatives: {seen - inventory}")
    print(f"{checked} preprocessing configurations and four import cases verified, covering {len(seen)} N4861 alternatives")
    return seen


def check_reserved_keywords(stage, compiler):
    # N4861 Table [lex.key]. Module/import have their own contextual productions.
    keywords = """
        alignas alignof asm auto bool break case catch char char8_t char16_t char32_t class concept const
        consteval constexpr constinit const_cast continue co_await co_return co_yield decltype default
        delete do double dynamic_cast else enum explicit export extern false float for friend goto if
        inline int long mutable namespace new noexcept nullptr operator private protected public register
        reinterpret_cast requires return short signed sizeof static static_assert static_cast struct
        switch template this thread_local throw true try typedef typeid typename union unsigned using
        virtual void volatile wchar_t while
    """.split()
    source = " ".join(keywords)
    tokens = list(CppSource(source).tokens())
    ref = subprocess.run([*compiler, "-x", "c++", "-Xclang", "-dump-tokens", "-fsyntax-only", "-"],
                         input=source, text=True, capture_output=True, check=True)
    if [(t.spelling, t.type != "IDENT") for t in tokens] != [(w, True) for w in keywords]:
        raise ValueError("reserved keyword tokenized as an identifier")
    if re.findall(r"^(\w+) '([^']+)'\t", ref.stderr, re.M) != [(w, w) for w in keywords]:
        raise ValueError("unexpected Clang keyword tokens")
    path = stage / "Label.ii"
    pipeline = get_pipeline(path)
    for word in [*keywords, "module", "import", "final", "override"]:
        path.write_text(f"void f() {{ goto {word}; {word}: ; }}\n")
        accepted = word not in keywords
        result = pipeline.analyze_file(path)
        ref = subprocess.run([*compiler, "-fsyntax-only", path], capture_output=True)
        if result.success != accepted or (ref.returncode == 0) != accepted:
            raise ValueError(f"keyword as label: {word}: {result.errors}, {ref.stderr!r}")
    print(f"{len(keywords)} reserved keywords and four contextual label names matched Clang")
    return {("keyword", "1")}


def check_punctuators(compiler):
    with (ROOT / "docs/conformance/cpp20-punctuators.tsv").open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    by_spelling = {r["spelling"]: r for r in rows}
    sequences = [(" ".join(by_spelling), list(by_spelling)), ("<::", ["<", "::"]),
                 ("<::>", ["<:", ":>"]), ("<:::", ["<:", "::"]), ("->*.*...", ["->*", ".*", "..."]),
                 ("<<=>>=<=>", ["<<=", ">>=", "<=>"]), ("++++=", ["++", "++", "="])]
    for source, spellings in sequences:
        ref = subprocess.run([*compiler, "-x", "c++", "-Xclang", "-dump-tokens", "-fsyntax-only", "-"],
                             input=source + "\n", text=True, capture_output=True, check=True)
        clang_tokens = re.findall(r"^(\w+) '([^']+)'\s+.*Loc=<<stdin>:1:(\d+)>", ref.stderr, re.M)
        tokens = list(CppSource(source).tokens())
        if [t.spelling for t in tokens] != spellings or [s for _, s, _ in clang_tokens] != spellings:
            raise ValueError(f"unexpected token boundaries for {source}: {tokens}, {clang_tokens}")
        for t, (kind, _, column) in zip(tokens, clang_tokens, strict=True):
            row = by_spelling[t.spelling]
            canonical, = CppSource(row["canonical"]).tokens()
            if (t.value != row["canonical"] or t.type != canonical.type or kind != row["clang_kind"]
                    or t.lexpos != int(column) - 1 or t.endlexpos != t.lexpos + len(t.spelling)):
                raise ValueError(f"unexpected token classification at {t.lexpos} in {source}: {t}, {row}")
    print(f"{len(rows)} operator and punctuator spellings and {len(sequences)-1} adjacent sequences matched Clang")
    return {("operator-or-punctuator", r["alternative"]) for r in rows} | {("preprocessing-op-or-punc", "2")}


def check_witnesses(preprocessing=()):
    with (ROOT / "docs/conformance/cpp20.tsv").open() as stream:
        inventory = {(r["rule"], r["alternative"]) for r in csv.DictReader(stream, delimiter="\t")}
    with (ROOT / "docs/conformance/cpp20-examples.tsv").open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    seen, inputs = set(preprocessing), {}
    if seen - inventory:
        raise ValueError(f"unindexed preprocessing or lexical alternatives: {seen - inventory}")
    for row in rows:
        key = row["rule"], row["alternative"]
        path = FIXTURES / row["fixture"]
        if path not in inputs:
            result, actions = capture_reductions(lambda: get_pipeline(path).analyze_file(path), "orionparser.languages.cpp.",
                                                exclude=(ParameterClauseGrammar, TypeIdGrammar))
            if not result.success:
                raise ValueError(f"{path}: {result.errors}")
            inputs[path] = result.ast, actions
        value, actions = inputs[path]
        if key not in inventory or row["production"] not in actions:
            raise ValueError(f"{key}: unindexed alternative or unobserved reduction {row['production']}")
        for part in row["path"].split("."):
            if isinstance(value, list) and part.startswith("@"):
                value, = [item for item in value if item.get("name") == part[1:]]
            else:
                value = value[int(part)] if isinstance(value, list) else value[part]
        if value != json.loads(row["expected_json"]):
            raise ValueError(f"{key}: unexpected AST at {row['path']}: {value!r}")
        seen.add(key)
    return len(seen), len(inventory)


def check_context_audit(ast, ref):
    slot = next(n for n in ref["inner"] if n.get("name") == "Slot")
    operator_id = next(n["id"] for n in slot["inner"] if n.get("name") == "operator new[]")
    create = next(n for n in ref["inner"] if n.get("name") == "create")
    allocation = next(n for n in create["inner"] if n["kind"] == "CompoundStmt")["inner"][0]["inner"][0]
    if allocation["operatorNewDecl"]["id"] != operator_id:
        raise ValueError("expected the class-specific array allocation function")
    func = next(n for n in ast["declarations"] if n.get("name") == "create")
    expr = func["body"]["statements"][0]["expression"]
    names = [[(item["namespace"], item["name"]) for spec in specs for item in spec["items"]]
             for specs in expr["dimensionAttributes"]]
    if expr["global"] or names != [[("vendor", "count")], [("vendor", "inner")]]:
        raise ValueError(f"unexpected new-array attribute owners: {names}")


def check_empty_member(stage, compiler):
    source = FIXTURES / "EmptyMember.cpp"
    expanded = stage / "EmptyMember.ii"
    expanded.write_bytes(subprocess.check_output([*compiler, "-E", "-P", source]))
    for path in (source, expanded):
        strict = subprocess.run([*compiler, "-fsyntax-only", path], capture_output=True)
        if strict.returncode == 0 or b"-Wextra-semi" not in strict.stderr:
            raise ValueError(f"{path}: unexpected strict-mode diagnostic: {strict.stderr!r}")
        dump = subprocess.check_output([*compiler, "-Wno-extra-semi", "-fsyntax-only", "-Xclang", "-ast-dump=json", path])
        tree = cli(path)
        members = tree["declarations"][0]["members"]
        if members.pop(0) != {"type": "EmptyDeclaration"}:
            raise ValueError(f"{path}: missing empty member")
        # Clang omits the empty member; the following field still has to match.
        if orion(tree) != clang(json.loads(dump), path.read_bytes()):
            raise ValueError(f"{path}: declarations following the empty member differ")


def check_declaration_specifiers(ast, reference):
    actual = {n.get("name"): n for n in ast["declarations"]}
    ref = {n.get("name"): n for n in reference["inner"]}
    for name, qualifier, key in (("per_thread", "thread_local", "tls"), ("external_value", "extern", "storageClass"),
                                ("seed", "inline", "inline"), ("initial", "consteval", "immediate")):
        decl = actual[name]
        if qualifier not in (decl.get("variableType") or decl["returnType"])["specifiers"] or not ref[name].get(key):
            raise ValueError(f"{name}: missing {qualifier} or Clang {key}")
    if ("constinit" not in actual["seed"]["variableType"]["specifiers"]
            or not any(n["kind"] == "ConstInitAttr" for n in ref["seed"]["inner"])):
        raise ValueError("missing constinit on seed")
    field, = (n for n in ref["Cell"]["inner"] if n["kind"] == "FieldDecl")
    if not field.get("mutable") or "mutable" not in actual["Cell"]["members"][0]["variableType"]["specifiers"]:
        raise ValueError("missing mutable on Cell::data")


def check_deduced_placeholder(actual, expected):
    var = next(n for n in actual if n[:2] == ["var", "object"])
    ref = next(n for n in expected if n[:2] == ["var", "object"])
    if var[2] != "Box" or ref[2] != "Box<int>":
        raise ValueError(f"unexpected placeholder or deduced type: {var}, {ref}")
    var[2] = ref[2]


def check_nested_module(stage, compiler):
    path = FIXTURES / "NestedModule.cppm"
    bmi = stage / "nested.pcm"
    subprocess.run([*compiler, "--precompile", path, "-o", bmi], check=True)
    client = stage / "nested-client.cpp"
    client.write_text("import inventory.names.deep;\nstatic_assert(depth == 3);\n")
    subprocess.run([*compiler, "-fmodule-file=inventory.names.deep=" + str(bmi), "-fsyntax-only", client], check=True)
    if cli(client)["declarations"][0] != {"type": "ImportDeclaration", "kind": "module", "target": "inventory.names.deep"}:
        raise ValueError("unexpected three-component module import")


def check_attribute_packs(stage, compiler):
    path = FIXTURES / "AttributePacks.cpp"
    expanded = stage / "AttributePacks.ii"
    expanded.write_bytes(subprocess.check_output([*compiler, "-E", "-P", path]))
    for source in (path, expanded):
        run = subprocess.run([*compiler, "-fsyntax-only", source], capture_output=True, text=True)
        errors = re.findall(r":(\d+:\d+): error: ([^\n]+)", run.stderr)
        diagnostic = "attribute 'types' cannot be used as an attribute pack"
        if run.returncode == 0 or errors != [("1:50", diagnostic), ("2:66", diagnostic)]:
            raise ValueError(f"unexpected attribute pack diagnostics: {errors}")
        groups = [d["declaration"]["attributes"][0]["items"] for d in cli(source)["declarations"]]
        actual = [[(item["name"], item.get("pack", False), item["arguments"]) for item in group] for group in groups]
        if actual != [[("types", True, ["T"])], [("marker", False, None), ("types", True, ["T"])]]:
            raise ValueError(f"unexpected attribute pack AST: {actual}")


def check_constant_array_bounds(actual, expected):
    # Clang prints folded extents; Orion retains their source expressions.
    local = next(n for n in actual if n[:2] == ["namespace", "local"])
    ref = next(n for n in expected if n[:2] == ["namespace", "local"])
    for name, bound, folded in (("Row", "width", 2), ("Block", "cells", 8)):
        written = next(n for n in local[3:] if n[:2] == ["using", name])
        canonical = next(n for n in ref[3:] if n[:2] == ["using", name])
        if written[2] != f"int[{bound}]" or canonical[2] != f"int[{folded}]":
            raise ValueError(f"{name}: unexpected written or canonical extent: {written}, {canonical}")
        written[2] = canonical[2]


def check_inferred_array_bounds(stage, compiler):
    source = FIXTURES / "InferredArrayBounds.cpp"
    expanded = stage / "InferredArrayBounds.ii"
    expanded.write_bytes(subprocess.check_output([*compiler, "-E", "-P", source]))
    result = subprocess.check_output([*compiler, "-Wno-braced-scalar-init", "-fsyntax-only", "-Xclang", "-ast-dump=json", expanded])
    namespace = next(n for n in json.loads(result)["inner"] if n.get("name") == "sizes")
    extents = {n["name"]: int(re.search(r"\[(\d+)\]", n["type"]["qualType"])[1])
               for n in namespace["inner"] if n["kind"] == "VarDecl"}
    if extents != {"flat": 4, "mixed": 3, "cube": 2, "direct": 3, "text": 5, "wide": 4,
                   "scalar": 2, "pointers": 2, "grid": 2, "paren_text": 4, "octets": 3, "handles": 2, "slots": 3, "callbacks": 3, "fields": 2, "methods": 2}:
        raise ValueError(f"unexpected inferred array extents: {extents}")
    for path in (source, expanded):
        sizes, inferred, expected, _, accept = cli(path)["declarations"]
        omitted = {n["name"] for n in sizes["declarations"] if n.get("dimensions", [])[:1] == [None]}
        params = [p["parameterType"]["specifiers"][0]["name"] for p in accept["parameters"]]
        refs = ["both::" + a["name"] for a in inferred["declarations"]]
        if omitted != set(extents) or params != refs or set(refs) != {"both::" + a["name"] for a in expected["declarations"]}:
            raise ValueError(f"{path}: missing array declaration or merged alias")
        if not all(a["target"]["declarator"][0]["size"].get("operator") == "sizeof" for a in inferred["declarations"]):
            raise ValueError(f"{path}: lost a written sizeof expression")
    print(f"{len(extents)} initializer-inferred array extents verified on source and preprocessed input")


def check_instantiated_declarators(ast, reference):
    # Clang associates these declarations with the primary template's location.
    # Match the instantiated signatures and whether a definition was generated.
    expected = []
    for decl in reference["inner"]:
        if decl["kind"] == "FunctionTemplateDecl":
            for fn in decl["inner"]:
                inner = fn.get("inner", [])
                if fn["kind"] == "FunctionDecl" and any(c["kind"] == "TemplateArgument" for c in inner):
                    expected.append((fn["name"], fn["type"]["qualType"], not any(c["kind"] == "CompoundStmt" for c in inner)))
        elif decl["kind"] == "VarTemplateSpecializationDecl":
            expected.append((decl["name"], decl["type"]["qualType"], "init" not in decl))
    actual = []
    for node in ast["declarations"]:
        if node["type"] != "ExplicitInstantiation":
            continue
        decl = node["declaration"]
        if decl["type"] == "FunctionDeclaration":
            function = {"type": "FunctionOperator", "parameters": decl["parameters"], "qualifiers": decl["qualifiers"],
                        "noexcept": decl["noexcept"]}
            signature = type_name(decl["returnType"], [function])
        else:
            signature = type_name(decl["variableType"])
        actual.append((decl["name"], signature, node["extern"]))
    if sorted(actual) != sorted(expected) or not actual:
        raise ValueError(f"instantiated signatures differ: {actual} / {expected}")


def check_alias_chains(stage, compiler):
    # Retain reference collapsing and cv placement across each alias boundary.
    path = stage / "AliasEquivalence.ii"
    pipeline = get_pipeline(path)
    pairs = [
        ("int", "signed int", True), ("unsigned", "int unsigned", True),
        ("long long", "signed long long int", True), ("char", "signed char", False),
        ("unsigned short", "short", False), ("const int", "int volatile", False),
        ("const BasePtr", "Base *const", True), ("const BasePtr", "const Base *", False),
        ("const BasePtr *", "Base *const *", True), ("BasePtr *const", "Base *const *", False),
        ("LRef &&", "Base &", True), ("RRef &", "Base &", True), ("RRef &&", "Base &&", True),
        ("const LRef", "Base &", True), ("RRef", "LRef", False),
        ("Row", "signed int[0x4u]", True), ("Row", "int[5]", False),
        ("Row[2]", "int[2][4]", True), ("Row[2]", "int[4][2]", False),
        ("Row *", "int (*)[4]", True), ("Row *", "int *[4]", False),
        ("const PtrRow", "int *const[4]", True), ("const PtrRow", "const int *[4]", False),
        ("Row &", "int (&)[4]", True), ("int[]", "int[4]", False),
        ("Row", "int[2+2]", True), ("Row", "int[(1+1)*3-2]", True),
        ("Row", "int[9u/2]", True), ("Row", "int[9u%5]", True),
        ("Row", "int[(5&7)^1]", True), ("Row", "int[1|4]", False),
        ("Row", "int[2+2*2]", False),
        ("Row", "int[::width]", True), ("Row", "int[bounds::width]", False),
        ("int[bounds::cells]", "int[8]", True), ("int[bounds::small]", "int[3]", True),
        ("int[bounds::flag]", "int[1]", True), ("Row", "int[bounds::wrapped]", True),
        ("int[bounds::enabled]", "int[true]", True),
        ("Row", "int[bounds::next]", True), ("Row", "int[bounds::Limits::next]", True),
        ("int[bounds::twice]", "int[8]", True), ("Row", "int[bounds::first]", False),
        ("Deduced<'A'>", "Deduced<65>", False), ("Size<'A'>", "Size<65>", True),
        ("Deduced<u'A'>", "Deduced<U'A'>", False), ("Deduced<+'A'>", "Deduced<65>", True),
        ("Size<'\\xff'>", "Size<-1>", True), ("Size<L'A'>", "Size<65>", True),
        ("Transform<>", "Transform<&identity<int>>", True), ("Handler<identity>", "Handler<&identity<int>>", True),
        ("Handler<both_fn>", "Handler<both_fn<int>>", False), ("Deduced<&identity<int>>", "Deduced<identity<int>>", True),
        ("Deduced<identity<long>>", "Deduced<identity<int>>", False), ("Handler<pair_fn<int>>", "Handler<pair_fn<int,int>>", True),
        ("PtrHandler<load>", "PtrHandler<&load<int>>", True), ("ForIdentity<long>", "ForIdentity<long,&identity<long>>", True),
        ("RecordFn<>", "RecordFn<&make_holder>", True), ("Variadic<>", "Variadic<&many>", True),
        ("Arrays<>", "Arrays<adjusted>", True), ("FunctionFn<>", "FunctionFn<&invoke>", True),
        ("Ordered<>", "Ordered<&read<int>>", True), ("Ordered<>", "Ordered<&read<int *>>", False),
        ("OrderedTwice<>", "OrderedTwice<&read<int>>", True),
        ("OrderedTwice<>", "OrderedTwice<&read<int **>>", False),
        ("ForType<int>", "ForType<int, &overloaded>", True), ("ForType<long>", "ForType<long, overloaded>", True),
        ("ForType<int>", "ForType<int, apply>", False), ("Handler<saved_callback>", "Handler<overloaded>", True),
        ("Handler<>", "Handler<&apply>", True), ("Handler<apply>", "Handler<second_fn>", False),
        ("Handler<&overloaded>", "Handler<overloaded>", True), ("Handler<overloaded>", "Handler<apply>", False),
        ("Handler<fnames::apply>", "Handler<apply>", False), ("LongHandler<overloaded>", "LongHandler<&overloaded>", True),
        ("RefHandler<apply>", "RefHandler<apply>", True), ("Deduced<apply>", "Deduced<&apply>", True),
        ("Handler<nothrow_fn>", "Handler<&nothrow_fn>", True), ("Handler<nullptr>", "Handler<apply>", False),
        ("FnMember<>", "FnMember<&Holder::read>", True), ("Deduced<&Holder::read>", "Deduced<&Holder::read>", True),
        ("RecordAddr<hptr>", "RecordAddr<&holder>", True), ("RecordAddr<&href>", "RecordAddr<&holder>", True),
        ("RecordAddr<>", "RecordAddr<&holder>", True), ("RecordAddr<>", "RecordAddr<&second_holder>", False),
        ("Deduced<&holder>", "Deduced<&second_holder>", False),
        ("Field<>", "Field<&Holder::datum>", True), ("Field<>", "Field<&Holder::other>", False),
        ("Field<nullptr>", "Field<&Holder::datum>", False),
        ("Deduced<&Holder::datum>", "Deduced<&Holder::other>", False),
        ("Addr<(objects::array + 1)>", "Addr<&objects::array[1]>", True),
        ("Addr<(1 + objects::array)>", "Addr<&objects::array[0]>", False),
        ("Addr<(&objects::array[1] - 1)>", "Addr<objects::array>", True),
        ("Addr<((&objects::value + 1) - 1)>", "Addr<&objects::value>", True),
        ("Addr<objects::ptr>", "Addr<&objects::value>", True), ("Deduced<objects::ptr>", "Deduced<&objects::value>", True),
        ("Addr<&objects::ref>", "Addr<&objects::value>", True), ("ObjectRef<objects::ref>", "ObjectRef<objects::value>", True),
        ("Addr<objects::array>", "Addr<&objects::array[0]>", True),
        ("Addr<&objects::array[0]>", "Addr<&objects::array[1]>", False),
        ("Deduced<&objects::array>", "Deduced<objects::array>", False),
        ("Deduced<objects::null>", "Deduced<nullptr>", True),
        ("Addr<>", "Addr<&objects::value>", True), ("Addr<>", "Addr<&other::value>", False),
        ("Addr<&imported_object::value>", "Addr<&objects::value>", True),
        ("Addr<&synonym::value>", "Addr<&::objects::value>", True),
        ("Deduced<&objects::value>", "Deduced<&other::value>", False),
        ("Addr<nullptr>", "Addr<&objects::value>", False), ("Deduced<nullptr>", "Deduced<nullptr>", True),
        ("ObjectRef<objects::value>", "ObjectRef<imported_object::value>", True),
        ("RepeatedPtr<&objects::value>", "RepeatedPtr<&objects::value,&imported_object::value>", True),
        ("Deduced<label>", "Deduced<4u>", True), ("Deduced<label>", "Deduced<4>", False),
        ("Deduced<label + 2>", "Deduced<6u>", True),
        ("Nested<short>", "Nested<short,Value<short,4,5>>", True),
        ("Nested<short>", "Nested<short,Value<short,5,6>>", False),
        ("Value<>", "Value<int,4,5>", True), ("Value<short>", "Value<short,4,5>", True),
        ("Value<int,8>", "Value<int,8,9>", True), ("Value<unsigned>", "Value<int,4,5>", False),
        ("Step<>", "Step<3,4>", True), ("Step<5>", "Step<5,4>", False),
        ("Deduced<4 + 1u>", "Deduced<5u>", True), ("Deduced<4 + 1u>", "Deduced<5>", False),
        ("Deduced<0u - 1u>", "Deduced<0xffffffffu>", True), ("Deduced<(-5 % 2)>", "Deduced<-1>", True),
        ("Deduced<(-3 / 2)>", "Deduced<-1>", True), ("Deduced<(1 < 2)>", "Deduced<true>", True),
        ("Deduced<(1u << 31)>", "Deduced<0x80000000>", True),
        ("Size<>", "Size<4>", True), ("Size<>", "Size<5>", False),
        ("Size<2+2>", "Size<04u>", True), ("Size<4>", "Size<4L>", True),
        ("Deduced<4>", "Deduced<4u>", False), ("Deduced<0x4>", "Deduced<04>", True),
        ("Deduced<true>", "Deduced<1>", False), ("Deduced<4L>", "Deduced<4LL>", False),
        ("Deduced<0xffffffff>", "Deduced<4294967295u>", True),
        ("Deduced<4294967295>", "Deduced<4294967295u>", False),
        ("Repeat<3>", "Repeat<3,3>", True), ("Repeat<3>", "Repeat<3,2>", False),
        ("Numbers<1,2>", "Numbers<1u,2u>", True), ("Typed<int,4>", "Typed<int,4u>", True),
        ("Default<>", "Default<int>", True), ("Default<>", "Default<long>", False),
        ("Pair<int>", "Pair<int,int *>", True), ("Pair<int>", "Pair<int,const int *>", False),
        ("Pair<BasePtr>", "Pair<int *,int **>", True), ("Chain<int>", "Chain<int,Box<int>,Box<int> &>", True),
        ("Forward<>", "Forward<short,long>", True), ("Forward<int>", "Forward<int,long>", True),
        ("library::Local<>", "library::Local<short>", True), ("library::Local<>", "library::Local<int>", False),
        ("Box<int>", "Box<signed int>", True), ("Box<int>", "Box<long>", False),
        ("Box<OpaquePtr> *", "Box<Opaque *> *", True), ("Box<Opaque *> *", "Box<Holder *> *", False),
        ("Box<Box<short>>", "Box<Box<signed short>>", True), ("Box<int *> &", "Box<const int *> &", False),
        ("Box<first::Item>", "Box<second::Item>", False), ("Box<first::Item>", "Box<first::Item>", True),
        ("Opaque *", "struct Opaque *", True), ("OpaquePtr", "Opaque *", True),
        ("const OpaquePtr", "Opaque *const", True), ("const OpaquePtr", "const Opaque *", False),
        ("Opaque *", "Holder *", False), ("OpaquePtr[2]", "Opaque *[2]", True),
        ("OpaquePtr[2]", "Opaque *[3]", False), ("Opaque *&", "OpaquePtr &", True),
        ("Opaque *&&", "OpaquePtr &", False), ("const Opaque", "Opaque", False),
        ("int[8]", "int[sizeof(int Holder::*)]", True), ("int[16]", "int[sizeof(Method)]", True),
        ("int[8]", "int[alignof(Method)]", True), ("int[32]", "int[sizeof(Method[2])]", True),
        ("int[16]", "int[sizeof(&Holder::read)]", True), ("int[8]", "int[sizeof(&Holder::datum)]", True),
        ("int[4]", "int[sizeof(holder.datum)]", True), ("int[8]", "int[sizeof(holder.callback)]", True),
        ("int[8]", "int[sizeof(&ordinary)]", True), ("int[8]", "int[sizeof(&Holder::callback)]", True), ("int[8]", "int[sizeof(Method *)]", True),
        ("int[8]", "int[sizeof(Method)]", False),
        ("int[8]", "int[sizeof(int (*)(int))]", True), ("int[24]", "int[sizeof(int (*[3])(int))]", True),
        ("int[8]", "int[sizeof(Opaque *)]", True), ("int[8]", "int[sizeof(OpaquePtr)]", True),
        ("int[24]", "int[sizeof(OpaquePtr[3])]", True), ("int[8]", "int[sizeof(opaque_ptr)]", True),
        ("int[4]", "int[sizeof(opaque_ptr)]", False),
        ("Row", "int[sizeof(bounds::values[0])]", True), ("int[16]", "int[sizeof(*bounds::ptr)]", True),
        ("int[8]", "int[sizeof(&bounds::values)]", True), ("int[16]", "int[sizeof(*&bounds::values)]", True),
        ("int[4]", 'int[sizeof("abc")]', True), ("int[2]", 'int[sizeof(u"abc"[1])]', True),
        ("int[8]", "int[sizeof(bounds::values[0])]", False),
        ("int[16]", "int[sizeof(bounds::values)]", True), ("Row", "int[sizeof(bounds::empty)]", False),
        ("int[8]", "int[sizeof(bounds::ptr)]", True), ("int[2]", "int[sizeof(bounds::small)]", True),
        ("Row", "int[bounds::bytes]", True), ("Row", "int[sizeof(unsigned int)]", True),
        ("int[16]", "int[sizeof(Row)]", True), ("int[32]", "int[sizeof(Row[2])]", True),
        ("int[16]", "int[sizeof(Row &)]", True), ("int[8]", "int[sizeof(Row *)]", True),
        ("int[8]", "int[sizeof(void *)]", True), ("int[4]", "int[alignof(Row)]", True),
        ("int[16]", "int[alignof(long double)]", True), ("int[2]", "int[sizeof(char16_t)]", True),
        ("int[8]", "int[sizeof(long unsigned)]", True), ("Row", "int[sizeof(short)]", False),
        ("int[1]", "int[bounds::one]", True), ("Row", "int[bounds::E::next]", True), ("Row", "int[imported::next]", True),
    ]
    for left, right, accepted in pairs:
        path.write_text("using Base=int; using BasePtr=Base*; using LRef=Base&; using RRef=Base&&; using Row=Base[4]; using PtrRow=BasePtr[4];\n"
                        "struct Holder { int datum, other; int read(int) const; int (*callback)(int); }; using Method=int (Holder::*)(int) const; Holder holder, second_holder; constexpr auto hptr=&holder; constexpr Holder &href=holder; template<Holder *P=&holder> struct RecordAddr {}; template<int Holder::* M=&Holder::datum> struct Field {}; int ordinary(int);\n"
                        "int apply(int); int second_fn(int); int overloaded(int); long overloaded(long); int nothrow_fn(int) noexcept; "
                        "Holder *make_holder(int); int many(int,...); int adjusted(const int vals[3]); int invoke(int fn(int)); "
                        "template<Holder *(*F)(int)=make_holder> struct RecordFn {}; template<int (*F)(int,...)=many> struct Variadic {}; "
                        "template<int (*F)(const int *)=adjusted> struct Arrays {}; template<int (*F)(int (*)(int))=invoke> struct FunctionFn {}; "
                        "template<class T> T identity(T); template<class T> T both_fn(T); int both_fn(int); template<class T,class U=T> T pair_fn(U); "
                        "template<class T> T load(const T *); template<int (*P)(const int *)> struct PtrHandler {}; "
                        "template<int (*F)(int)=identity> struct Transform {}; template<class T,T (*F)(T)=identity> struct ForIdentity {}; "
                        "template<class T> int read(T); template<class T> int read(T *); template<class T> int read(T **); "
                        "template<int (*F)(int *)=read> struct Ordered {}; template<int (*F)(int **)=read> struct OrderedTwice {}; "
                        "namespace fnames { int apply(int); } constexpr int (*saved_callback)(int)=overloaded; template<class T,T (*F)(T)=overloaded> struct ForType {}; template<int (*F)(int)=apply> struct Handler {}; "
                        "template<long (*F)(long)> struct LongHandler {}; template<int (&F)(int)> struct RefHandler {}; "
                        "template<int (Holder::*F)(int) const=&Holder::read> struct FnMember {};\n"
                        "template<class T> struct Box {}; namespace first{struct Item{};} namespace second{struct Item{};}\n"
                        "namespace objects { inline int value, array[2]; constexpr int &ref=value; constexpr auto ptr=&ref; constexpr auto null=nullptr; } namespace other { inline int value; } "
                        "namespace imported_object { using objects::value; } namespace synonym=objects; "
                        "template<int *P=&objects::value> struct Addr {}; template<int &R> struct ObjectRef {}; "
                        "template<int *P,int *Q=P> struct RepeatedPtr {};\n"
                        "constexpr auto label=4u; template<int N=3,int M=N+1> struct Step {}; template<int N=4> struct Size {}; template<auto N> struct Deduced {}; "
                        "template<int N,int M=N> struct Repeat {}; template<int... V> struct Numbers {}; "
                        "template<class T,T N> struct Typed {}; template<class T=int,T N=4,T M=N+1> struct Value {}; template<class T,class U=Value<T>> struct Nested {};\n"
                        "template<class T=int> struct Default {}; template<class T,class U=T *> struct Pair {}; "
                        "template<class T,class U=Box<T>,class V=U &> struct Chain {}; "
                        "template<class X,class Y=long> struct Forward; template<class T=short,class U> struct Forward {}; "
                        "namespace library { using Base=short; template<class T=Base> struct Local {}; }\n"
                        "struct Opaque; using OpaquePtr = Opaque *; OpaquePtr opaque_ptr;\n"
                        "constexpr int width=4; namespace bounds{ Row values; char empty; Row *ptr; constexpr auto bytes=sizeof(int); constexpr int width{2}; constexpr int cells=width * ::width; "
                        "const unsigned short small(3); constexpr bool flag=2, enabled=true; constexpr unsigned char wrapped=260; enum Counts { minus=-1, zero, one }; enum Limits { first=3, next, twice=next*2 }; using E=Limits; } namespace imported { using enum bounds::Limits; }\n"
                        f"namespace A{{using Inner={left};using T=Inner;}}\n"
                        f"namespace B{{using Inner={right};using T=Inner;}}\n"
                        "namespace C{using namespace A;using namespace B;} void consume(C::T);\n")
        result = pipeline.analyze_file(path)
        ref = subprocess.run([*compiler, "-x", "c++", "-fsyntax-only", path], capture_output=True)
        if result.success != accepted or (ref.returncode == 0) != accepted:
            raise ValueError(f"alias identity {left} / {right}: {result.errors}, {ref.stderr.decode()}")
    print(f"{len(pairs)} namespace alias-equivalence cases matched Clang")


def check_builtin_spellings(stage, compiler):
    # Table [dcl.type.simple] permits each multiset in any order, including
    # decl-specifiers interleaved between the type keywords.
    groups = {
        "int": ["signed", "signed int", "int"],
        "unsigned int": ["unsigned", "unsigned int"],
        "char": ["char"], "signed char": ["signed char"], "unsigned char": ["unsigned char"],
        "long double": ["long double"],
    }
    for width in ("short", "long", "long long"):
        groups[width] = [width, width + " int", "signed " + width, "signed " + width + " int"]
        groups["unsigned " + width] = ["unsigned " + width, "unsigned " + width + " int"]
    aliases = {}
    for canonical, spellings in groups.items():
        for spelling in spellings:
            for words in sorted(set(permutations(spelling.split()))):
                aliases["S" + str(len(aliases))] = (words, canonical)
    path = stage / "BuiltinPermutations.ii"
    path.write_text("".join(f"using {name} = {' '.join(words)};\n" for name, (words, _) in aliases.items())
                    + "using Interleaved = unsigned const long volatile int;\n")
    expected = {name: canonical for name, (_, canonical) in aliases.items()}
    expected["Interleaved"] = "const volatile unsigned long"
    ref = json.loads(subprocess.check_output([*compiler, "-x", "c++", "-fsyntax-only", "-Xclang", "-ast-dump=json", path]))
    canonical = {d["name"]: d["type"]["qualType"] for d in ref["inner"] if d["kind"] == "TypeAliasDecl"}
    written = {d["name"]: d["target"]["specifiers"] for d in cli(path)["declarations"]}
    source_words = {name: list(words) for name, (words, _) in aliases.items()}
    source_words["Interleaved"] = ["unsigned", "const", "long", "volatile", "int"]
    if canonical != expected or written != source_words:
        raise ValueError("builtin specifier permutations changed the canonical type or written tokens")
    print(f"{len(written)} builtin spellings verified against Clang canonical types and CLI specifier order")

    # Check every ordered pair separately so Clang recovery in one invalid
    # declaration cannot mask another. The public CLI covers complete units above.
    words = "char char8_t char16_t char32_t wchar_t bool short int long signed unsigned float double void".split()
    pair_path = stage / "BuiltinPair.ii"
    pipeline = get_pipeline(pair_path)
    accepted = 0
    for first, second in product(words, repeat=2):
        pair_path.write_text(f"using Pair = {first} {second};\n")
        ref = subprocess.run([*compiler, "-x", "c++", "-fsyntax-only", pair_path], capture_output=True)
        result = pipeline.analyze_file(pair_path)
        if result.success != (ref.returncode == 0):
            raise ValueError(f"builtin pair {first} {second}: {result.errors}, {ref.stderr.decode()}")
        accepted += result.success
    print(f"{len(words)**2} ordered builtin keyword pairs matched Clang ({accepted} accepted)")



def check_line_splices(stage, compiler):
    physical = FIXTURES / "LineSplices.ii"
    logical = stage / "LineSplices.ii"
    data = subprocess.check_output([*compiler, "-x", "c++", "-E", "-P", physical])
    logical.write_bytes(data)
    reference = json.loads(subprocess.check_output([*compiler, "-x", "c++-cpp-output", "-fsyntax-only",
                                                    "-Xclang", "-ast-dump=json", logical]))
    expected = clang(reference, data)
    for path in (physical, logical):
        if orion(cli(path)) != expected:
            raise ValueError(f"{path}: phase-2 splice or raw literal differs")
    # Move a single splice through every boundary of the same valid declaration sequence.
    sample = "template<class T> constexpr int half(T x){return x>>1;} constexpr int n=half<int>(0b10'01);"
    pieces, originals = [], []
    for i in range(len(sample)+1):
        namespace = f"namespace split{i} {{"
        pieces.append(namespace + sample[:i] + "\\\n" + sample[i:] + "}\n")
        originals.append(namespace + sample + "}\n")
    variants = stage / "SpliceBoundaries.ii"
    variants.write_text("".join(pieces))
    subprocess.run([*compiler, "-x", "c++-cpp-output", "-fsyntax-only", variants], check=True)
    baseline = "".join(originals).encode()
    reference = json.loads(subprocess.check_output([*compiler, "-x", "c++", "-fsyntax-only", "-Xclang",
                                                    "-ast-dump=json", "-"], input=baseline))
    if orion(cli(variants)) != clang(reference, baseline):
        raise ValueError("splice placement changed a declaration or expression")
    print(f"{len(pieces)} single-splice boundaries preserved the Clang declaration trees")
    print("physical and spliced translation units matched Clang, including the raw string body")


def check_character_boundaries(stage, compiler):
    # Compare every prefix at the same encoding and numeric-escape boundaries.
    contents = ["ab", r"\377", r"\400", r"\xFF", r"\x100", r"\xFFFF", r"\x10000",
                r"\xFFFFFFFF", r"\x100000000", r"\u007F", r"\u0080", r"\uD7FF",
                r"\uD800", r"\uE000", r"\U00010000", r"\U0010FFFF", r"\U00110000", "é", "🙂"]
    path = stage / "CharacterBoundary.ii"
    pipeline = get_pipeline(path)
    accepted = 0
    for prefix, content in product(("", "u8", "u", "U", "L"), contents):
        literal = f"{prefix}'{content}'"
        path.write_text(f"constexpr auto sample = {literal};\n")
        result = pipeline.analyze_file(path)
        ref = subprocess.run([*compiler, "-x", "c++", "-fsyntax-only", "-Xclang", "-ast-dump=json", path],
                             capture_output=True)
        if result.success != (ref.returncode == 0):
            raise ValueError(f"character {literal}: {result.errors}, {ref.stderr.decode()}")
        if result.success:
            check_character_widths(result.ast, json.loads(ref.stdout))
            accepted += 1
    print(f"{5 * len(contents)} character boundary cases matched Clang ({accepted} accepted)")


def check_string_boundaries(stage, compiler):
    path = stage / "StringBoundary.ii"
    pipeline = get_pipeline(path)
    cases = []
    for prefix, escape in product(("", "u8", "u", "U", "L"), (r"\377", r"\400", r"\xFF", r"\x100", r"\xFFFF", r"\x10000", r"\xFFFFFFFF", r"\x100000000")):
        cases.extend((f'{prefix}"{escape}"', f'"{escape}" {prefix}""', f'{prefix}"" "{escape}"',
                      f'{prefix}R"({escape})"'))
    # Sweep every printable ASCII delimiter byte in C++20 mode.
    cases.extend(f'R"{chr(code)}(x){chr(code)}"' for code in range(32, 127))
    cases.extend(f'R"{d}(x){d}"' for d in ("", "a"*16, "a"*17))
    accepted = 0
    for text in cases:
        path.write_text(f"auto value = {text};\n")
        actual = pipeline.analyze_file(path)
        ref = subprocess.run([*compiler, "-x", "c++", "-fsyntax-only", path], capture_output=True)
        if actual.success != (ref.returncode == 0):
            raise ValueError(f"{text!r}: {actual.errors}, {ref.stderr.decode()}")
        accepted += actual.success
    print(f"{len(cases)} string escape and delimiter cases matched Clang ({accepted} accepted)")


def check_number_spellings(stage, compiler):
    suffixes = {"", "u", "U"}
    for length in ("l", "L", "ll", "LL"):
        suffixes.add(length)
        for sign in ("u", "U"):
            suffixes.update((length + sign, sign + length))
    integer_bodies = ("1'2", "0'14", "0xC", "0Xc", "0b1'100", "0B1100")
    floats = ("1.5", ".5", "1.", "2e1", "2E+1", "2e-1", "0x1.8p1", "0X.8P+2", "0x1.P-2", "0x1p1'0")
    cases = [(body, suffix, "integer") for body, suffix in product(integer_bodies, sorted(suffixes | {"_v"}))]
    cases.extend((body, suffix, "floating") for body, suffix in product(floats, ("", "f", "F", "l", "L", "_v")))
    path = stage / "NumericSpellings.ii"
    path.write_text('constexpr auto operator""_v(unsigned long long x){return x;}\n'
                    'constexpr auto operator""_v(long double x){return x;}\n' +
                    "".join(f"constexpr auto v{i} = {body}{suffix};\n" for i, (body, suffix, _) in enumerate(cases)))
    reference = json.loads(subprocess.check_output([*compiler, "-x", "c++", "-fsyntax-only", "-Xclang", "-ast-dump=json", path]))
    ast = cli(path)
    check_numeric_suffixes(ast, reference)
    variables = {d["name"]: d["initializer"] for d in ast["declarations"] if d["type"] == "VariableDeclaration"}
    refs = {d["name"]: d["inner"][-1] for d in reference["inner"] if d["kind"] == "VarDecl"}
    for i, (body, suffix, kind) in enumerate(cases):
        name = f"v{i}"
        literal = variables[name]
        expected = {"kind": kind, "number": body, "suffix": suffix} if suffix == "_v" else None
        clang_kind = "UserDefinedLiteral" if expected else ("IntegerLiteral" if kind == "integer" else "FloatingLiteral")
        if literal["raw"] != body + suffix or literal.get("userDefined") != expected or refs[name]["kind"] != clang_kind:
            raise ValueError(f"{name}: numeric literal boundary differs for {body}{suffix}")
    print(f"{len(cases)} numeric spellings matched Clang's literal categories and CLI boundaries")


def check_coroutines(stage, compiler):
    src = FIXTURES / "Coroutines.cpp"
    expanded = stage / "Coroutines.ii"
    with expanded.open("wb") as out:
        subprocess.run(["g++", "-std=c++20", "-E", "-P", src], stdout=out, check=True)
    dump = subprocess.check_output([*compiler, "-Xclang", "-ast-dump=json", "-Xclang",
                                    "-ast-dump-filter=coro_case_", "-fsyntax-only", src]).decode().strip()
    expected = {}
    while dump:
        fn, end = json.JSONDecoder().raw_decode(dump)
        dump = dump[end:].lstrip()
        body = next(n for n in fn["inner"] if n["kind"] == "CoroutineBodyStmt")
        # The first child represents the written body, before implicit promise and suspend operations.
        expected[fn["name"]] = clang(body["inner"][0], src.read_bytes())
    for path in (src, expanded):
        actual = {}
        pending = list(cli(path)["declarations"])
        while pending:
            decl = pending.pop()
            if (decl.get("name") or "").startswith("coro_case_"):
                actual[decl["name"]] = orion(decl["body"])
            pending.extend(decl.get("members") or [])
        if actual != expected or len(actual) != 4:
            raise ValueError(f"coroutine body difference for {path}: {actual} vs {expected}")
    print("4 coroutine bodies matched Clang on source and preprocessed inputs")


def check_rejections(stage, compiler):
    with (ROOT / "docs/conformance/cpp20-rejections.tsv").open() as stream:
        cases = list(csv.DictReader(stream, delimiter="\t"))
    path = stage / "invalid.ii"
    for case in cases:
        text = json.loads(case["source_json"])
        path.write_text(text)
        result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                                capture_output=True, text=True)
        line, col = case["orion"].split(":")
        if result.returncode == 0 or json.loads(result.stdout) is not None or f"line {line}, column {col}:" not in result.stderr:
            raise ValueError(f"{case['case']}: unexpected Orion result: {result.stderr}")
        ref = subprocess.run([*compiler, "-x", "c++", "-fsyntax-only", "-ferror-limit=1", "-"],
                             input=text, capture_output=True, text=True)
        error = re.search(r"<stdin>:(\d+:\d+): error:", ref.stderr)
        if not ref.returncode or not error or error[1] != case["clang"]:
            raise ValueError(f"{case['case']}: unexpected Clang result: {ref.stderr}")
    print(f"{len(cases)} malformed translation units rejected with positions by the CLI and Clang")


def check_public_lambda_declarations(path, compiler):
    # The upstream negative L0 precedes these C++20 positives. L8 and L12 use C++23 syntax.
    expected = {f"L{i}" for i in (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 13, 14)}
    selected = {}
    for line in path.read_text().splitlines():
        match = re.match(r"auto (L\d+) = ", line)
        if match and match[1] in expected:
            selected[match[1]] = line
    if selected.keys() != expected:
        raise ValueError("missing or unexpected upstream lambda declarations")
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "upstream_lambdas.cpp"
        source.write_text("\n".join(selected.values()) + "\n")
        expanded = source.with_suffix(".ii")
        expanded.write_bytes(subprocess.check_output([*compiler, "-E", "-P", source]))
        reference = json.loads(subprocess.check_output([*compiler, "-Xclang", "-ast-dump=json", "-fsyntax-only", expanded]))
        projected = clang(reference, expanded.read_bytes())
        for unit in (source, expanded):
            if orion(cli(unit)) != projected:
                raise ValueError(f"{unit.name}: upstream lambda trees differ")
    print(f"{len(selected)} upstream C++20 lambda declarations matched on both input paths")


def check_public_inline_reopenings(path, compiler):
    lines = [s for s in path.read_text().splitlines() if s.startswith("namespace valid1::")]
    if len(lines) != 3:
        raise ValueError("unexpected upstream nested namespace examples")
    with tempfile.TemporaryDirectory() as d:
        source = Path(d) / "InlineReopenings.cpp"
        source.write_text("\n".join(lines) + "\n")
        expanded = source.with_suffix(".ii")
        expanded.write_bytes(subprocess.check_output([*compiler, "-E", "-P", source]))
        dump = subprocess.check_output([*compiler, "-Wno-inline-namespace-reopened-noninline",
                                        "-Xclang", "-ast-dump=json", "-fsyntax-only", expanded])
        expected = clang(json.loads(dump), expanded.read_bytes())
        for unit in (source, expanded):
            if orion(cli(unit)) != expected:
                raise ValueError("written inline status differs in nested namespace reopenings")
    print("3 upstream inline namespace reopenings matched Clang on source and preprocessed inputs")


def check_public(directory, compiler, fetch):
    with (ROOT / "docs/conformance/cpp20-clang-tests.tsv").open() as stream:
        cases = list(csv.DictReader(stream, delimiter="\t"))
    for case in cases:
        filename = case["file"]
        path = directory / filename
        if fetch and not path.exists():
            base = "https://raw.githubusercontent.com/llvm/llvm-project/3b5b5c1ec4a3095ab096dd780e84d7ab81f3d7ff/clang/test/Parser/"
            with urlopen(base + filename, timeout=30) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != case["sha256"]:
                raise ValueError(f"{filename}: unexpected downloaded fixture")
            directory.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if hashlib.sha256(path.read_bytes()).hexdigest() != case["sha256"]:
            raise ValueError(f"{filename}: unexpected fixture digest")
        defines = [case["define"]] if case["define"] else []
        flags = ["-D" + d for d in defines]
        result = get_pipeline(path, c_defines=defines).analyze_file(path)
        ref = subprocess.run([*compiler, *flags, "-x", "c++", "-fsyntax-only", "-ferror-limit=1", path],
                             capture_output=True, text=True)
        if case["clang"] != "accept":
            expected = f":{case['clang']}: error: {case['diagnostic']}"
            if not ref.returncode or expected not in ref.stderr:
                raise ValueError(f"{filename}: unexpected Clang result {ref.stderr}")
        if case["orion"] == "accept":
            if not result.success or (case["clang"] == "accept" and ref.returncode):
                raise ValueError(f"{filename}: {result.errors}, {ref.stderr}")
            if filename == "cxx2a-designated-init.cpp":
                # Upstream checks copy-initialization of an explicit constructor
                # and narrowing. Its four declarations are syntactically valid.
                fields = [(d["name"], d["initializer"]["elements"][0]["form"]) for d in result.ast["declarations"]
                          if d["type"] == "VariableDeclaration"]
                if fields != [("b1", "="), ("b2", "{}"), ("d1", "="), ("d2", "{}")]:
                    raise ValueError(f"{filename}: designated member initializers differ")
            elif filename.endswith(".cppm"):
                if result.ast["module"]["name"] != "foo" or not result.ast["module"]["exported"]:
                    raise ValueError(f"{filename}: module mismatch")
            else:
                data = subprocess.check_output([*compiler, *flags, "-x", "c++", "-E", "-P", path])
                dump = subprocess.check_output([*compiler, "-x", "c++-cpp-output", "-fsyntax-only", "-Xclang", "-ast-dump=json", "-"], input=data)
                if orion(result.ast) != clang(json.loads(dump), data):
                    raise ValueError(f"{filename}: function trees differ")
        else:
            if result.success or not any(f":{case['orion']}:" in e for e in result.errors):
                raise ValueError(f"{filename}: unexpected Orion result {result.errors}")
        if filename == "cxx2a-template-lambdas.cpp":
            check_public_lambda_declarations(path, compiler)
        if filename == "cxx2a-inline-nested-namespace-definition.cpp":
            check_public_inline_reopenings(path, compiler)
    print(f"{len(cases)} pinned LLVM parser configurations checked")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clang", default="clang-18")
    parser.add_argument("--clang-tests", type=Path, help="pinned LLVM C++ Parser inputs")
    parser.add_argument("--fetch", action="store_true", help="download missing pinned LLVM inputs")
    parser.add_argument("--preprocessing-only", action="store_true", help="check the C++20 preprocessing witnesses")
    parser.add_argument("--punctuators-only", action="store_true", help="compare C++20 punctuator tokenization with Clang")
    parser.add_argument("--inventory-only", action="store_true", help="verify all indexed parser, preprocessing and lexical witnesses")
    parser.add_argument("--array-bounds-only", action="store_true", help="compare array bounds and alias identity with Clang")
    args = parser.parse_args()
    check_version(args.clang)
    compiler = [args.clang, *FLAGS]
    if args.array_bounds_only:
        with tempfile.TemporaryDirectory() as folder:
            check_inferred_array_bounds(Path(folder), compiler)
            check_alias_chains(Path(folder), compiler)
        return
    if args.punctuators_only:
        check_punctuators(compiler)
        return
    with tempfile.TemporaryDirectory() as folder:
        preprocessing = check_preprocessing(Path(folder), compiler)
    if args.preprocessing_only:
        return
    with tempfile.TemporaryDirectory() as folder:
        lexical = check_punctuators(compiler) | check_reserved_keywords(Path(folder), compiler)
    seen, total = check_witnesses(preprocessing | lexical)
    if seen != total:
        raise ValueError(f"C++20 grammar inventory incomplete: {seen}/{total}")
    print(f"{seen}/{total} C++20 alternatives with parser, preprocessing or lexical witnesses")
    if args.inventory_only:
        return
    if args.clang_tests:
        check_public(args.clang_tests, compiler, args.fetch)
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        for name in ("Scale.cppm", "Fold.cpp", "Namespaces.cpp", "Declarators.cpp", "Hierarchy.cpp", "Packs.cpp", "MemberPointers.cpp", "Operators.cpp", "Dependent.cpp", "FoldExpressions.cpp", "FoldOperators.cpp", "Operands.cpp", "Constraints.cpp", "Delete.cpp", "Allocation.cpp", "Lambdas.cpp", "LambdaScopes.cpp", "Exceptions.cpp", "Control.cpp", "Conditions.cpp", "Bindings.cpp", "Attributes.cpp", "QualifiedOwners.cpp", "Linkage.cpp", "Specializations.cpp", "DependentBases.cpp", "NonTypeParameters.cpp", "BuiltinTraits.cpp", "UsingMembers.cpp", "AnonymousAndVariableTemplates.cpp", "TemplateNameArguments.cpp", "VariableSpecializations.cpp", "FriendTypes.cpp", "DeductionGuides.cpp", "RecordAliases.cpp", "ClassAliasLookup.cpp", "ExplicitInstantiation.cpp", "CompleteClass.cpp", "InstantiatedDeclarators.cpp", "MemberAttributes.cpp", "KnownMembers.cpp", "QualifiedCalls.cpp", "SystemDeclarations.cpp", "IntegerSequences.cpp", "Designated.cpp", "GroupedPacks.cpp", "PackSuffixes.cpp", "ArrayAttributes.cpp", "PointerAttributes.cpp", "BuiltinSpecifiers.cpp", "EnumDeclarations.cpp", "EnumObjects.cpp", "RecordObjects.cpp", "Asm.cpp", "DestructorCalls.cpp", "ConversionCalls.cpp", "QualifiedMemberTemplates.cpp", "MemberOperatorTemplates.cpp", "LambdaOperatorCalls.cpp", "ClosureAliases.cpp", "ClosureResults.cpp", "ClosureTemporaries.cpp", "SubscriptReceivers.cpp", "AllocatedReceivers.cpp", "ConditionalReceivers.cpp", "CommaReceivers.cpp", "AssignmentReceivers.cpp", "IncrementReceivers.cpp", "UnaryReceivers.cpp", "AdditiveReceivers.cpp", "BinaryOperatorReceivers.cpp", "MemberPointerReceivers.cpp", "NumericSuffixes.cpp", "QuotedSuffixes.cpp", "CharacterWidths.cpp", "StringEscapeWidths.cpp", "UnnamedNamespaces.cpp", "NamespaceDirectives.cpp", "ImportedTypes.cpp", "AliasChains.cpp", "ArrayAliasIdentity.cpp", "IdentifierSpellings.cpp", "ConstantArrayBounds.cpp", "MemberForms.cpp", "PreprocessingNumbers.cpp", "AlternativeTokens.cpp", "IntegerSpellings.cpp", "DeclarationSpecifiers.cpp", "TemplateNames.cpp", "DeducedPlaceholder.cpp", "NestedModule.cppm", "RecordAliasIdentity.cpp", "DefaultTemplateTypes.cpp", "IntegralTemplateArguments.cpp", "AddressTemplateArguments.cpp", "FunctionAddressArguments.cpp", "FunctionTemplateAddresses.cpp", "OrderedFunctionTemplates.cpp", "RankedClosureResults.cpp", "ContextAudit.cpp", "AssociatedNamespaces.cpp"):
            path = FIXTURES / name
            output = subprocess.check_output([*compiler, "-x", "c++", "-E", "-P", str(path)])
            expanded = stage / (path.stem + ".ii")
            expanded.write_bytes(output)
            reference = json.loads(subprocess.check_output([*compiler, "-x", "c++-cpp-output", "-fsyntax-only",
                                                            "-Xclang", "-ast-dump=json", str(expanded)]))
            if name == "InstantiatedDeclarators.cpp":
                for input_path in (path, expanded):
                    check_instantiated_declarators(cli(input_path), reference)
                print(f"{name}: source and preprocessed explicit instantiations matched")
                continue
            expected = clang(reference, output)
            for input_path in (path, expanded):
                ast = cli(input_path)
                if name in {"Attributes.cpp", "UsingMembers.cpp", "FriendTypes.cpp", "ArrayAttributes.cpp", "EnumDeclarations.cpp"}:
                    check_attribute_owners(ast, reference, output)
                if name == "ContextAudit.cpp":
                    check_context_audit(ast, reference)
                if name == "DeclarationSpecifiers.cpp":
                    check_declaration_specifiers(ast, reference)
                if name == "CharacterWidths.cpp":
                    check_character_widths(ast, reference)
                if name == "NumericSuffixes.cpp":
                    check_numeric_suffixes(ast, reference)
                actual = orion(ast)
                if name == "DeducedPlaceholder.cpp":
                    check_deduced_placeholder(actual, expected)
                if name == "ConstantArrayBounds.cpp":
                    check_constant_array_bounds(actual, expected)
                if actual != expected:
                    raise ValueError(f"{input_path.name}: Orion {actual!r}, Clang {expected!r}")
            print(f"{name}: source and preprocessed declaration and expression trees matched")
        bmi = stage / "sample.scale.pcm"
        subprocess.run([*compiler, "-x", "c++-module", "--precompile", str(FIXTURES / "Scale.cppm"), "-o", bmi], check=True)
        client = FIXTURES / "Use.cpp"
        subprocess.run([*compiler, "-fmodule-file=sample.scale=" + str(bmi), "-fsyntax-only", client], check=True)
        imported = cli(client)["declarations"][0]
        if imported != {"type": "ImportDeclaration", "kind": "module", "target": "sample.scale"}:
            raise ValueError(f"unexpected module import: {imported}")
        print("sample.scale imported and its exported constexpr function checked by Clang")
        partition = stage / "support.pcm"
        subprocess.run([*compiler, "-x", "c++-module", "--precompile", FIXTURES / "Support.cppm", "-o", partition], check=True)
        subprocess.run([*compiler, "-x", "c++-module", "-fmodule-file=example.core:support=" + str(partition),
                        "-fsyntax-only", FIXTURES / "Primary.cppm"], check=True)
        header = stage / "header.pcm"
        subprocess.run([*compiler, "-x", "c++-header", "-fmodule-header=user", FIXTURES / "HeaderUnit.hpp", "-o", header], check=True)
        subprocess.run([*compiler, "-Wno-experimental-header-units", "-fmodule-file=" + str(header),
                        "-fsyntax-only", FIXTURES / "HeaderUse.cpp"], check=True)
        print("partition re-export and quoted header-unit import verified by Clang")
        system = [args.clang, "-std=c++20", "-pedantic-errors"]
        typeinfo = stage / "typeinfo.pcm"
        subprocess.run([*system, "-Wno-pragma-system-header-outside-header", "-x", "c++-system-header",
                        "-fmodule-header=system", "typeinfo", "-o", typeinfo], check=True)
        query = FIXTURES / "TypeQueries.cpp"
        expanded = stage / "TypeQueries.ii"
        expanded.write_bytes(subprocess.check_output(["g++", "-std=c++20", "-E", "-P", query]))
        for path in (query, expanded):
            dump = subprocess.check_output([*system, "-x", "c++", "-Wno-experimental-header-units", "-fmodule-file=" + str(typeinfo),
                                            "-fsyntax-only", "-Xclang", "-ast-dump=json", "-Xclang",
                                            "-ast-dump-filter=same_type", path])
            expected = clang(json.loads(dump), path.read_bytes())
            actual = orion(cli(path)["declarations"][-1])
            if actual != expected:
                raise ValueError(f"{path.name}: typeid operands differ: {actual} vs {expected}")
        print("typeid type and expression operands matched using the system typeinfo header unit")
        check_alias_chains(stage, compiler)
        check_inferred_array_bounds(stage, compiler)
        check_empty_member(stage, compiler)
        check_attribute_packs(stage, compiler)
        check_nested_module(stage, compiler)
        check_builtin_spellings(stage, compiler)
        check_number_spellings(stage, compiler)
        check_line_splices(stage, compiler)
        check_character_boundaries(stage, compiler)
        check_string_boundaries(stage, compiler)
        check_coroutines(stage, system)
        check_rejections(stage, compiler)



if __name__ == "__main__":
    main()
