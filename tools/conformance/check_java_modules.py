"""Compare pinned OpenJDK source files through the file pipeline and JavacTask.parse."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import tempfile
from zipfile import ZipFile

from orionparser.registry import get_pipeline


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ZIP_SHA = "5928a04d650cb2c0a8e6a001bb0401d77045c0ab828dba7bf63c549baabdbd86"


def source_archive(jdk, explicit=None):
    archive = explicit or jdk / "lib/src.zip"
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SOURCE_ZIP_SHA:
            raise ValueError("unexpected OpenJDK src.zip digest")
    return archive


def project(directive):
    kind = directive["type"]
    result = [kind, directive["name"]]
    if kind == "Requires":
        result.extend([m in directive["modifiers"] for m in ("static", "transitive")])
    elif kind in {"Opens", "Exports"}:
        result.append(directive["targets"])
    elif kind == "Provides":
        result.append(directive["implementations"])
    return result


ORDINARY = {
    f"java.base/java/lang/{name}.java" for name in (
        "Runnable", "AutoCloseable", "IllegalArgumentException", "Exception", "Cloneable",
        "ArithmeticException", "IndexOutOfBoundsException",
    )
} | {
    "java.base/java/lang/constant/ConstantDesc.java", "java.base/java/lang/constant/ModuleDesc.java",
    "java.base/java/lang/constant/ModuleDescImpl.java", "java.base/java/lang/constant/PackageDesc.java",
    "java.base/java/lang/constant/PackageDescImpl.java", "java.base/jdk/internal/foreign/abi/VMStorage.java",
    "java.base/jdk/internal/classfile/instruction/SwitchCase.java",
    "java.base/jdk/internal/classfile/impl/StackCounter.java",
    "java.base/jdk/internal/classfile/impl/ChainedClassBuilder.java",
    "java.base/jdk/internal/classfile/impl/ChainedMethodBuilder.java",
    "java.base/java/lang/constant/DynamicConstantDesc.java", "java.base/java/lang/invoke/InvokerBytecodeGenerator.java",
    "java.base/java/util/stream/Nodes.java", "java.base/java/util/stream/SliceOps.java",
    "java.base/jdk/internal/classfile/impl/ClassRemapperImpl.java",
    "java.base/java/lang/CharacterData.java", "java.base/java/lang/Math.java", "java.base/java/time/Ser.java",
    "java.base/java/lang/constant/DirectMethodHandleDescImpl.java", "java.base/java/lang/constant/MethodHandleDesc.java",
    "java.base/java/lang/Comparable.java", "java.base/java/util/function/Supplier.java",
    "java.base/java/util/function/IntFunction.java", "java.base/java/util/function/ToIntFunction.java",
    "java.base/java/util/concurrent/Callable.java", "java.base/java/lang/reflect/GenericDeclaration.java",
    "java.base/java/lang/reflect/ParameterizedType.java",
} | {
    f"java.base/java/lang/annotation/{name}.java" for name in
    ("ElementType", "RetentionPolicy", "Documented", "Inherited", "Native", "Repeatable", "Retention", "Target")
} | {
    f"java.base/java/lang/{name}.java" for name in
    ("Deprecated", "FunctionalInterface", "Override", "SafeVarargs", "SuppressWarnings",
     "reflect/ClassFileFormatVersion", "invoke/InjectedProfile")
} | {
    f"java.base/java/time/{name}.java" for name in
    ("chrono/IsoEra", "chrono/MinguoEra", "chrono/ThaiBuddhistEra", "format/FormatStyle", "format/ResolverStyle",
     "format/SignStyle", "format/TextStyle", "temporal/ChronoField", "temporal/ChronoUnit")
} | {
    "java.base/java/util/concurrent/TimeUnit.java", "java.desktop/sun/awt/PlatformGraphicsInfo.java",
    "jdk.jfr/jdk/jfr/internal/jfc/model/XmlConfiguration.java", "jdk.jfr/jdk/jfr/internal/jfc/model/XmlControl.java",
} | {
    f"java.base/java/io/{name}.java" for name in (
        "ByteArrayInputStream", "ByteArrayOutputStream", "FilterInputStream", "Closeable", "BufferedOutputStream",
        "PipedInputStream", "StringReader", "CharArrayReader", "FileReader", "DataInputStream", "SequenceInputStream",
        "InputStream", "OutputStream", "FileInputStream", "BufferedReader", "PrintStream",
    )
} | {
    f"java.base/{name}.java" for name in (
        "sun/security/util/UntrustedCertificates", "sun/nio/fs/LinuxNativeDispatcher", "jdk/internal/platform/CgroupUtil",
        "sun/util/resources/BreakIteratorResourceBundle", "jdk/internal/jimage/decompressor/Decompressor",
        "jdk/internal/jrtfs/JrtFileAttributes", "sun/security/util/AnchorCertificates", "sun/net/NetProperties",
    )
}


def annotation_value(node):
    kind = node["type"]
    if kind == "Literal":
        return node["raw"]
    if kind == "NameExpression":
        return node["name"]
    if kind == "ElementValueArrayInitializer":
        return "{" + ", ".join(map(annotation_value, node["values"])) + "}"
    if kind == "ClassLiteral":
        return node["name"] + "[]" * node["dimensions"] + ".class"
    if kind.endswith("Annotation"):
        return annotation_name(node)
    raise ValueError(f"unmapped annotation expression {kind}")


def annotation_name(annotation):
    name = "@" + annotation["name"]
    if annotation["type"] == "SingleElementAnnotation":
        return name + "(" + annotation_value(annotation["value"]) + ")"
    elements = annotation.get("elements", [])
    if elements:
        return name + "(" + ", ".join(e["name"] + " = " + annotation_value(e["value"]) for e in elements) + ")"
    return name


def annotation_prefix(node):
    annotations = node.get("annotations", [])
    return " ".join(map(annotation_name, annotations)) + " " if annotations else ""


def type_name(t, extra_dims=0, extra_annotations=None):
    if isinstance(t, str):
        t = {"type": "Type", "name": t}
    prefix = annotation_prefix(t)
    if t["type"] == "Wildcard":
        return prefix + ("?" if t["bound"] is None else f"? {t['boundKind']} {type_name(t['bound'])}")
    if "segments" in t:
        parts = []
        for segment in t["segments"]:
            arguments = ", ".join(map(type_name, segment["arguments"]))
            parts.append(annotation_prefix(segment) + segment["name"] + (f"<{arguments}>" if arguments else ""))
        name = ".".join(parts)
    else:
        name = t["name"]
    dimensions = (extra_annotations or [[]] * extra_dims) + t.get("dimensionAnnotations", [[]] * t.get("dimensions", 0))
    for annotations in dimensions:
        name += " " + " ".join(map(annotation_name, annotations)) + " []" if annotations else "[]"
    return prefix + name


def parameter_type(p):
    annotations = [p.get("varargAnnotations", [])] if p["variadic"] else p.get("dimensionAnnotations")
    return type_name(p["parameterType"], p["dimensions"] + p["variadic"], annotations)


def type_params(decl):
    return [annotation_prefix(p) + p["name"] + (" extends " + " & ".join(map(type_name, p["bounds"])) if p["bounds"] else "")
            for p in decl["typeParameters"]]


def member_list(decl):
    components = [[c["name"], parameter_type(c)] for c in decl.get("components", [])]
    members = [["field", *component] for component in components]
    for c in decl.get("constants", []):
        body = None if c["body"] is None else member_list({"members": c["body"]})
        members.append(["constant", c["name"], [a["name"] for a in c["annotations"]], len(c["arguments"] or []), body])
    statements = {"ReturnStatement": "RETURN", "ThrowStatement": "THROW", "Block": "BLOCK",
                  "TryStatement": "TRY", "EnumDeclaration": "ENUM", "ClassDeclaration": "CLASS", "InterfaceDeclaration": "INTERFACE", "SwitchStatement": "SWITCH", "YieldStatement": "YIELD", "RecordDeclaration": "RECORD", "EmptyStatement": "EMPTY_STATEMENT", "ConstructorInvocation": "EXPRESSION_STATEMENT",
                  "ExpressionStatement": "EXPRESSION_STATEMENT", "IfStatement": "IF", "WhileStatement": "WHILE_LOOP",
                  "EnhancedForStatement": "ENHANCED_FOR_LOOP", "ForStatement": "FOR_LOOP", "DoWhileStatement": "DO_WHILE_LOOP",
                  "LabeledStatement": "LABELED_STATEMENT", "ContinueStatement": "CONTINUE", "BreakStatement": "BREAK",
                  "AssertStatement": "ASSERT", "SynchronizedStatement": "SYNCHRONIZED"}
    for member in decl["members"]:
        kind = member["type"]
        if kind == "FieldDeclaration":
            for var in member["variables"]:
                members.append(["field", var["name"], type_name(member["fieldType"], var["dimensions"], var.get("dimensionAnnotations"))])
        elif kind in {"ConstructorDeclaration", "CompactConstructorDeclaration", "MethodDeclaration"}:
            constructor = kind != "MethodDeclaration"
            params = [[p["name"], parameter_type(p)] for p in member.get("parameters", [])]
            if kind == "CompactConstructorDeclaration":
                params = components
            body = None
            if member["body"] is not None:
                body = []
                for stmt in member["body"]["statements"]:
                    if stmt["type"] == "LocalVariableDeclaration":
                        body.extend("VARIABLE" for _ in stmt["variables"])
                    else:
                        body.append(statements[stmt["type"]])
            receiver = member.get("receiverParameter")
            receiver_shape = None
            if receiver is not None:
                name = ((receiver["qualifier"] + ".") if receiver["qualifier"] else "") + "this"
                receiver_shape = [name, type_name(receiver["receiverType"]), [a["name"] for a in receiver["annotations"]]]
            method_annotations = [m["name"] for m in member["modifiers"] if isinstance(m, dict)]
            method_annotations.extend(a["name"] for a in member.get("resultAnnotations", []))
            members.append(["<init>" if constructor else member["name"],
                            None if constructor else type_name(member["returnType"], member.get("dimensions", 0), member.get("dimensionAnnotations")), params, list(map(type_name, member.get("throws", []))), body, type_params(member) if "typeParameters" in member else [], receiver_shape, method_annotations])
        elif kind == "AnnotationElement":
            default = member["default"]
            default_kind = None if default is None else root_kind(default)
            members.append(["element", member["name"], type_name(member["elementType"], member["dimensions"], member.get("dimensionAnnotations")), default_kind])
        elif kind in {"ClassDeclaration", "InterfaceDeclaration", "RecordDeclaration", "EnumDeclaration", "AnnotationInterfaceDeclaration"}:
            members.append(member_shape(member))
        elif kind == "Initializer":
            members.append(["BLOCK", member["static"]])
        elif kind != "EmptyDeclaration":
            raise ValueError(f"unmapped class member {kind}")
    return members


def member_shape(decl):
    interface = decl["type"] in {"InterfaceDeclaration", "AnnotationInterfaceDeclaration"}
    superclass = None if interface or not decl["extends"] else type_name(decl["extends"][0])
    kind = "ANNOTATION_TYPE" if decl["type"] == "AnnotationInterfaceDeclaration" else decl["type"].removesuffix("Declaration").upper()
    return [kind, decl["name"], superclass,
            list(map(type_name, decl["extends"] if interface else decl["implements"])), member_list(decl), type_params(decl),
            decl.get("permits", []), "sealed" in decl["modifiers"], "non-sealed" in decl["modifiers"]]


def ast_nodes(tree):
    if isinstance(tree, dict):
        if "type" in tree:
            yield tree
        for value in tree.values():
            yield from ast_nodes(value)
    elif isinstance(tree, list):
        for item in tree:
            yield from ast_nodes(item)


def text_block_values(unit):
    return [n["value"] for n in ast_nodes(unit) if n["type"] == "Literal" and "value" in n]


def resource_and_array_shapes(unit):
    tries, arrays = [], []
    initialized = set()
    for node in ast_nodes(unit):
        kind = node["type"]
        if kind == "TryStatement":
            resources = []
            for r in node["resources"]:
                if r["type"] == "LocalVariableDeclaration":
                    var, = r["variables"]
                    resources.append(["variable", var["name"], type_name(r["variableType"], var["dimensions"])])
                else:
                    resources.append(["access", root_kind(r)])
            catches = []
            for clause in node["catches"]:
                param = clause["parameter"]
                catches.append([param["name"], " | ".join(map(type_name, param["types"])) + "[]" * param["dimensions"]])
            tries.append([resources, catches, node["finally"] is not None])
        elif kind == "NewArray":
            sizes = [root_kind(dim["size"]) for dim in node["dimensions"] if dim["size"] is not None]
            init = node["initializer"]
            trailing = len(node["dimensions"]) - len(sizes)
            if init is not None:
                initialized.add(id(init))
                trailing -= 1
            arrays.append([type_name(node["elementType"]), trailing, sizes, None if init is None else len(init["values"])])
        elif kind in {"ArrayInitializer", "ElementValueArrayInitializer"} and id(node) not in initialized:
            arrays.append([None, 0, [], len(node["values"])])
    return tries, arrays


def pattern_shape(node):
    if node["type"] == "RecordPattern":
        return ["record", type_name(node["recordType"]), list(map(pattern_shape, node["components"]))]
    if node["type"] == "TypePattern":
        variable = node["variable"]
        return ["binding", type_name(variable["parameterType"], variable["dimensions"]), variable["name"]]
    return type_name(node)


def instance_tests(unit):
    return [pattern_shape(n["test"]) for n in ast_nodes(unit) if n["type"] == "InstanceOfExpression"]


_OPERATORS = {
    "+": "PLUS", "-": "MINUS", "*": "MULTIPLY", "/": "DIVIDE", "%": "REMAINDER", "&&": "CONDITIONAL_AND",
    "||": "CONDITIONAL_OR", "&": "AND", "|": "OR", "^": "XOR", ">=": "GREATER_THAN_EQUAL", "<=": "LESS_THAN_EQUAL",
    "==": "EQUAL_TO", "!=": "NOT_EQUAL_TO", "<": "LESS_THAN", ">": "GREATER_THAN", "<<": "LEFT_SHIFT",
    ">>": "RIGHT_SHIFT", ">>>": "UNSIGNED_RIGHT_SHIFT",
}


def root_kind(node):
    k = node["type"]
    if k == "BinaryExpression":
        return _OPERATORS[node["operator"]]
    if k in {"ThisExpression", "SuperExpression"}:
        return "MEMBER_SELECT" if node.get("qualifier") else "IDENTIFIER"
    if k == "NameExpression":
        return "MEMBER_SELECT" if "." in node["name"] else "IDENTIFIER"
    if k == "UnaryExpression":
        op = node["operator"]
        if op == "-" and node["operand"]["type"] == "Literal" and re.fullmatch(r"[1-9][0-9_]*[lL]?", node["operand"]["raw"]):
            return root_kind(node["operand"])
        return {"!": "LOGICAL_COMPLEMENT", "~": "BITWISE_COMPLEMENT", "+": "UNARY_PLUS", "-": "UNARY_MINUS",
                "++": "PREFIX_INCREMENT" if node["prefix"] else "POSTFIX_INCREMENT",
                "--": "PREFIX_DECREMENT" if node["prefix"] else "POSTFIX_DECREMENT"}[op]
    if k == "Literal":
        raw = node["raw"]
        if raw.startswith('"'):
            return "STRING_LITERAL"
        if raw.startswith("'"):
            return "CHAR_LITERAL"
        if raw in {"true", "false"}:
            return "BOOLEAN_LITERAL"
        if raw == "null":
            return "NULL_LITERAL"
        if raw.lower().endswith("l"):
            return "LONG_LITERAL"
        if "." in raw or (not raw.lower().startswith("0x") and any(c in raw.lower() for c in "efd")) or "p" in raw.lower():
            return "FLOAT_LITERAL" if raw.lower().endswith("f") else "DOUBLE_LITERAL"
        return "INT_LITERAL"
    if k == "AssignmentExpression":
        op = node["operator"]
        return "ASSIGNMENT" if op == "=" else _OPERATORS[op[:-1]] + "_ASSIGNMENT"
    return {"AssertStatement": "ASSERT", "ForStatement": "FOR_LOOP", "EnhancedForStatement": "ENHANCED_FOR_LOOP",
            "LabeledStatement": "LABELED_STATEMENT", "WhileStatement": "WHILE_LOOP", "DoWhileStatement": "DO_WHILE_LOOP",
            "SynchronizedStatement": "SYNCHRONIZED", "Block": "BLOCK", "MethodInvocation": "METHOD_INVOCATION", "ConditionalExpression": "CONDITIONAL_EXPRESSION",
            "LambdaExpression": "LAMBDA_EXPRESSION", "MethodReference": "MEMBER_REFERENCE", "ArrayAccess": "ARRAY_ACCESS",
            "ClassLiteral": "MEMBER_SELECT", "TryStatement": "TRY", "NewArray": "NEW_ARRAY", "CastExpression": "TYPE_CAST", "ParenthesizedExpression": "PARENTHESIZED", "MemberAccess": "MEMBER_SELECT",
            "ThrowStatement": "THROW", "ReturnStatement": "RETURN", "NewClass": "NEW_CLASS", "SwitchExpression": "SWITCH_EXPRESSION",
            "ElementValueArrayInitializer": "NEW_ARRAY", "NormalAnnotation": "ANNOTATION",
            "MarkerAnnotation": "ANNOTATION", "SingleElementAnnotation": "ANNOTATION",
            "ExpressionStatement": "EXPRESSION_STATEMENT", "BreakStatement": "BREAK", "YieldStatement": "YIELD",
            "ContinueStatement": "CONTINUE", "IfStatement": "IF", "SwitchStatement": "SWITCH", "EmptyStatement": "EMPTY_STATEMENT",
            "InstanceOfExpression": "INSTANCE_OF", "LocalVariableDeclaration": "VARIABLE"}[k]


def case_constant(node):
    kind = root_kind(node)
    if kind in {"INT_LITERAL", "LONG_LITERAL"}:
        # javac folds unary minus on nonzero decimal integer literals, and
        # prints all integral case values in decimal, regardless of radix.
        folded = node["type"] == "UnaryExpression"
        raw = (node["operand"] if folded else node)["raw"].rstrip("lL").replace("_", "").lower()
        base = 16 if raw.startswith("0x") else 2 if raw.startswith("0b") else 8 if raw.startswith("0") else 10
        bits = 64 if kind == "LONG_LITERAL" else 32
        value = int(raw, base)
        if folded:
            value = -value
        elif base != 10 and value >= 1 << (bits-1):
            value -= 1 << bits
        return "literal:" + str(value) + ("L" if bits == 64 else "")
    if node["type"] == "Literal":
        return "literal:" + node["raw"]
    return node["name"] if node["type"] == "NameExpression" else kind


def switch_shapes(unit):
    switches = []
    for node in ast_nodes(unit):
        if node["type"] not in {"SwitchExpression", "SwitchStatement"}:
            continue
        arms = []
        for entry in node["body"]["entries"]:
            rule = entry["type"] == "SwitchRule"
            labels = [entry["label"]] if rule else entry["labels"]
            for idx, label in enumerate(labels):
                values = []
                if label["type"] == "DefaultLabel":
                    values.append("default")
                elif label["type"] == "CasePattern":
                    values.append(pattern_shape(label["pattern"]))
                else:
                    values.extend(map(case_constant, label["values"]))
                    if label["includesDefault"]:
                        values.append("default")
                statements = []
                if not rule and idx == len(labels)-1:
                    for stmt in entry["statements"]:
                        count = len(stmt["variables"]) if stmt["type"] == "LocalVariableDeclaration" else 1
                        statements.extend([root_kind(stmt)] * count)
                arms.append([values, label.get("guard") is not None, statements, root_kind(entry["body"]) if rule else None])
        switches.append([root_kind(node), arms])
    return switches


def qualifier_name(node):
    if node is None:
        return None
    kind = node["type"]
    if kind == "NameExpression":
        return node["name"]
    if kind in {"SuperExpression", "ThisExpression"}:
        prefix = node.get("qualifier")
        return ((prefix + ".") if prefix else "") + ("super" if kind == "SuperExpression" else "this")
    if kind == "MemberAccess" and (prefix := qualifier_name(node["receiver"])) is not None:
        return prefix + "." + node["name"]
    return None


def invocation_shapes(unit):
    result = []
    for node in ast_nodes(unit):
        if node["type"] == "ConstructorInvocation":
            name, receiver = node["target"], node.get("qualifier")
        elif node["type"] == "MethodInvocation" and node.get("typeArguments"):
            name, receiver = node["name"], node["receiver"]
        else:
            continue
        qname = qualifier_name(receiver)
        kind = None if receiver is None else root_kind(receiver)
        result.append([name, kind, qname, list(map(type_name, node.get("typeArguments", []))), len(node["arguments"])])
    return result


def functional_shapes(tree):
    result = []
    for node in ast_nodes(tree):
        if node["type"] == "MethodReference":
            result.append(["reference", node["name"], list(map(type_name, node["typeArguments"]))])
        elif node["type"] == "LambdaExpression":
            params = []
            for p in node["parameters"]:
                t = p.get("parameterType")
                spelling = None if t is None or t["name"] == "var" else type_name(t, p["dimensions"] + p["variadic"])
                params.append([p["name"], spelling])
            body = node["body"]
            kind = root_kind(body)
            calls = [n["name"].split(".")[-1] for n in ast_nodes(body) if n["type"] == "MethodInvocation"]
            result.append(["lambda", params, kind, calls])
    return result


def reference_results(jdk, stage, paths):
    subprocess.run([jdk / "bin/javac", "-d", stage, ROOT / "tools/conformance/JavaParseOracle.java"], check=True)
    return read_reference(jdk, stage, paths)


def read_reference(jdk, stage, paths, *, surface=False):
    flags = ["--surface"] if surface else []
    output = subprocess.check_output([jdk / "bin/java", "-cp", stage, "JavaParseOracle", *flags, *paths], text=True)
    refs = [json.loads(line) for line in output.splitlines()]
    if [r["file"] for r in refs] != [str(p) for p in paths]:
        raise ValueError("unexpected javac output order")
    return refs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jdk", type=Path, default=ROOT / ".venv/toolchains/jdk-21.0.2")
    parser.add_argument("--source-zip", type=Path, help="pinned OpenJDK source archive for an alternate JDK installation")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        paths = []
        ordinary = set(ORDINARY)
        with ZipFile(source_archive(args.jdk, args.source_zip)) as source:
            functions = {n for n in source.namelist() if n.startswith("java.base/java/util/function/") and n.endswith(".java")}
            if len(functions) != 44:
                raise ValueError("unexpected java.util.function source inventory")
            ordinary.update(functions)
            for name in sorted(source.namelist()):
                if name.endswith("/module-info.java") or name in ordinary:
                    path = stage / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(source.read(name))
                    paths.append(path)
        if len(paths) != 69 + len(ordinary):
            raise ValueError(f"unexpected number of OpenJDK descriptors: {len(paths)}")
        count = function_count = switch_count = 0
        enum_count = annotation_count = block_count = 0
        try_count = resource_count = array_count = 0
        for path, ref in zip(paths, reference_results(args.jdk, stage, paths), strict=True):
            result = get_pipeline(path).analyze_file(path)
            if not result.success or not ref["accepted"] or ref["file"] != str(path):
                raise ValueError(f"{path.parent.name}: unexpected parse result {ref['errors']} {result.errors}")
            unit = result.ast
            if path.name != "module-info.java":
                if instance_tests(unit) != ref["instances"]:
                    raise ValueError(f"{path.name}: instanceof targets differ from javac")
                enum_count += sum(n["type"] == "EnumDeclaration" for n in ast_nodes(unit))
                annotation_count += sum(n["type"] == "AnnotationInterfaceDeclaration" for n in ast_nodes(unit))
                block_count += len(ref["textBlocks"])
                tries, arrays = resource_and_array_shapes(unit)
                try_count += len(tries)
                resource_count += sum(len(entry[0]) for entry in tries)
                array_count += len(arrays)
                if (tries, arrays) != (ref["tries"], ref["arrays"]):
                    raise ValueError(f"{path.name}: try or array structure differs from javac: {tries}, {arrays} vs {ref['tries']}, {ref['arrays']}")
                if text_block_values(unit) != ref["textBlocks"]:
                    raise ValueError(f"{path.name}: decoded text blocks differ from javac")
                switches = switch_shapes(unit)
                if switches != ref["switches"]:
                    raise ValueError(f"{path.name}: {switches} vs javac {ref['switches']}")
                switch_count += len(switches)
                if invocation_shapes(unit) != ref["invocations"]:
                    raise ValueError(f"{path.name}: invocation structure differs: {invocation_shapes(unit)} vs {ref['invocations']}")
                functional = functional_shapes(unit)
                if functional != ref["functional"]:
                    raise ValueError(f"{path.name}: {functional!r} vs javac {ref['functional']!r}")
                function_count += len(functional)
                if unit["package"]["name"] != ref["package"] or [member_shape(d) for d in unit["declarations"]] != ref["shapes"]:
                    raise ValueError(f"{path.name}: ordinary-unit structure differs from javac")
                continue
            module = unit["module"]
            got = {
                "package": unit["package"], "types": unit["declarations"], "module": module["name"],
                "open": module["open"], "annotations": [a["name"] for a in module["annotations"]],
                "imports": [[i["static"], i["name"] + (".*" if i["onDemand"] else "")] for i in unit["imports"]],
                "directives": [project(d) for d in module["directives"]],
            }
            for field, value in got.items():
                if value != ref[field]:
                    raise ValueError(f"{path.parent.name} {field}: Orion {value!r}, javac {ref[field]!r}")
            count += len(module["directives"])
        print(f"{len(paths)-len(ordinary)} OpenJDK descriptors, {count} module directives and "
              f"{len(ordinary)} ordinary compilation units ({function_count} lambdas/references, {switch_count} switches, "
              f"{enum_count} enums, {annotation_count} annotation interfaces, {block_count} text blocks, "
              f"{try_count} try statements, {resource_count} resources and {array_count} array nodes) matched javac 21.0.2+13")


if __name__ == "__main__":
    main()
