"""Compare C17 translation-unit function bodies with the pinned Clang AST."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

from orionparser.languages.c.lexer import CParseError
from orionparser.languages.c.pipeline import CPipeline
from orionparser.registry import get_pipeline


ROOT = Path(__file__).resolve().parents[2]
ZLIB = "zlib-51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf"
ZLIB_SHA = "d9e270d46252734aa49770fbc544125391617956266f220bd63216c834f3a522"
SOLO_SOURCES = ("adler32", "compress", "crc32", "deflate", "infback", "inffast",
                "inflate", "inftrees", "trees", "uncompr", "zutil")
FLAGS = ["-target", "x86_64-unknown-linux-gnu", "-std=c17", "-pedantic-errors"]


def c_type(node):
    words = []
    for spec in node["specifiers"]:
        if isinstance(spec, str):
            words.append(spec)
        elif spec["type"] == "TypedefName":
            words.append(spec["name"])
        else:
            words.extend([{"StructSpecifier": "struct", "UnionSpecifier": "union", "EnumSpecifier": "enum"}[spec["type"]], spec["tag"] or "<anonymous>"])
    qualifiers = [word for word in ("const", "volatile", "restrict") if word in words]
    words = [word for word in words if word not in qualifiers]
    if words == ["unsigned"]:
        words.append("int")
    words = qualifiers + words
    abstract = abstract_spelling(node["declarator"])
    separator = " " if abstract and not abstract.startswith("[") else ""
    return " ".join(words) + separator + abstract


def abstract_spelling(decl):
    if decl is None:
        return ""
    inner = abstract_spelling(decl["declarator"])
    if decl["type"] == "PointerDeclarator":
        quals = " ".join(decl["qualifiers"])
        return "*" + quals + (" " if quals and inner else "") + inner
    if decl["type"] == "ArrayDeclarator":
        if inner.startswith("*"):
            inner = "(" + inner + ")"
        size = decl["size"]
        return inner + "[" + (size["raw"] if size is not None else "") + "]"
    raise ValueError("unmapped type operand " + decl["type"])


def name(decl):
    while decl and decl["type"] != "Identifier":
        decl = decl["declarator"]
    return decl["name"] if decl else None


def orion(node):
    if node is None:
        return None
    k = node["type"]
    if k == "Declaration":
        tags = []
        for spec in node["specifiers"]:
            if isinstance(spec, dict) and spec["type"] in {"StructSpecifier", "UnionSpecifier"} and spec["members"] is not None:
                fields = [name(field["declarator"]) for member in spec["members"] for field in member.get("members", [])]
                tags.append(["tag", spec["tag"], fields])
        return ["decl", *tags, *[[name(item["declarator"]), orion(item["initializer"])] for item in node["declarators"]]]
    if k == "ExpressionStatement":
        return orion(node["expression"]) if node["expression"] else ["empty"]
    if k == "CompoundStatement":
        return ["block", *map(orion, node["items"])]
    if k in {"BinaryExpression", "AssignmentExpression", "CommaExpression"}:
        return [node.get("operator", ","), orion(node["left"]), orion(node["right"])]
    if k == "UnaryExpression":
        return ["pre" if node["prefix"] else "post", node["operator"], orion(node["operand"])]
    if k == "Identifier":
        return ["id", node["name"]]
    if k in {"NumericLiteral", "CharacterLiteral"}:
        return ["literal", node["raw"]]
    if k == "StringLiteral":
        return ["string", node["parts"]]
    if k == "TypeName":
        return ["type", c_type(node)]
    if k == "CastExpression":
        return ["cast", c_type(node["target"]), orion(node["operand"])]
    if k == "CallExpression":
        return ["call", orion(node["callee"]), *map(orion, node["arguments"])]
    if k == "SubscriptExpression":
        return ["index", orion(node["base"]), orion(node["index"])]
    if k == "MemberExpression":
        return [node["operator"], orion(node["base"]), node["member"]]
    if k == "CompoundLiteral":
        return ["compound", c_type(node["target"]), ["init", *map(orion, node["elements"])]]
    if k == "InitializerList":
        return ["init", *map(orion, node["elements"])]
    if k == "ReturnStatement":
        return ["return", orion(node["expression"])]
    if k in {"BreakStatement", "ContinueStatement"}:
        return [k.removesuffix("Statement").lower()]
    if k == "GotoStatement":
        return ["goto", node["label"]]
    if k == "LabeledStatement":
        return ["label", node["label"], orion(node["body"])]
    if k == "CaseStatement":
        return ["case", orion(node["test"]), orion(node["body"])]
    if k in {"IfStatement", "ConditionalExpression"}:
        return ["if" if k == "IfStatement" else "?:", orion(node["test"]), orion(node["consequent"]), orion(node["alternate"])]
    if k in {"SwitchStatement", "WhileStatement", "DoWhileStatement"}:
        return [k.removesuffix("Statement").lower(), orion(node["test"]), orion(node["body"])]
    if k == "ForStatement":
        return ["for", *[orion(node[f]) for f in ("init", "test", "update", "body")]]
    raise ValueError("unmapped Orion node " + k)


def clang(node, source, labels):
    if not node:
        return None
    k = node["kind"]
    if k == "RecordDecl":
        return ["tag", node.get("name"), [field.get("name") for field in node.get("inner", []) if field["kind"] == "FieldDecl"]]
    children = [clang(child, source, labels) for child in node.get("inner", [])]
    if k in {"ImplicitCastExpr", "ConstantExpr", "ParenExpr"}:
        return children[0]
    if k == "VarDecl":
        return [node["name"], children[-1] if node.get("init") else None]
    if k in {"UnaryExprOrTypeTraitExpr", "UnaryOperator"}:
        if k == "UnaryOperator":
            return ["post" if node["isPostfix"] else "pre", node["opcode"], children[0]]
        if "argType" in node:
            qual = re.sub(r"\(unnamed (?:enum|struct|union) at .*?\)", "<anonymous>", node["argType"]["qualType"])
            arg = ["type", qual]
        else:
            arg = children[0]
        return ["pre", node["name"], arg]
    if k in {"BinaryOperator", "CompoundAssignOperator"}:
        return [node["opcode"], *children]
    if k == "CompoundLiteralExpr":
        # Clang fills the bound of an explicitly unsized array from its initializer.
        begin = node["range"]["begin"]["offset"]
        end = node["inner"][0]["range"]["begin"]["offset"]
        qual = re.sub(r" \(\*\)$", " *", node["type"]["qualType"])
        if re.search(rb"\[\s*\]", source[begin:end]):
            qual = re.sub(r"\[\d+\]", "[]", qual, count=1)
        return ["compound", qual, children[0]]
    if k == "CStyleCastExpr":
        return ["cast", node["type"]["qualType"], children[0]]
    if k == "DeclRefExpr":
        return ["id", node["referencedDecl"]["name"]]
    if k in {"IntegerLiteral", "FloatingLiteral", "CharacterLiteral", "StringLiteral"}:
        loc = node["range"]
        raw = source[loc["begin"]["offset"]:loc["end"]["offset"] + loc["end"]["tokLen"]].decode()
        return ["string", re.findall(r'(?:u8|[LuU])?"(?:[^"\\]|\\.)*"', raw)] if k == "StringLiteral" else ["literal", raw]
    if k == "MemberExpr":
        return ["->" if node["isArrow"] else ".", children[0], node["name"]]
    if k == "IfStmt":
        return ["if", *children] if len(children) == 3 else ["if", *children, None]
    if k == "DoStmt":
        return ["dowhile", children[1], children[0]]
    if k == "ReturnStmt":
        return ["return", children[0] if children else None]
    if k == "ForStmt":
        if children[1] is not None:
            raise ValueError("unexpected Clang condition declaration")
        return ["for", children[0], *children[2:]]
    if k == "DefaultStmt":
        return ["case", None, *children]
    if k == "GotoStmt":
        return ["goto", labels[node["targetLabelDeclId"]]]
    if k == "LabelStmt":
        return ["label", node["name"], children[0]]
    kinds = {"CompoundStmt": "block", "DeclStmt": "decl", "CallExpr": "call", "ArraySubscriptExpr": "index",
             "InitListExpr": "init", "WhileStmt": "while", "SwitchStmt": "switch", "CaseStmt": "case",
             "NullStmt": "empty", "ConditionalOperator": "?:", "BreakStmt": "break", "ContinueStmt": "continue"}
    if k not in kinds:
        raise ValueError("unmapped Clang node " + k)
    return [kinds[k], *children]


def compare(source, compiler, unit=None, *, line_markers=False, compare_host_intmax=False):
    marker_flags = ["-Wno-gnu-line-marker"] if line_markers else []
    result = subprocess.run([compiler, *FLAGS, *marker_flags, "-x", "cpp-output", "-fsyntax-only", "-Xclang", "-ast-dump=json", "-"],
                            input=source, capture_output=True)
    if result.returncode:
        raise ValueError(result.stderr.decode())
    reference = json.loads(result.stdout)
    if unit is None:
        unit = CPipeline().parse(source.decode())
    expected = []
    for decl in reference["inner"]:
        if decl["kind"] != "FunctionDecl":
            continue
        items = decl.get("inner", [])
        body = next((n for n in items if n["kind"] == "CompoundStmt"), None)
        if body is None:
            continue
        labels, stack = {}, [body]
        while stack:
            item = stack.pop()
            if item.get("kind") == "LabelStmt":
                labels[item["declId"]] = item["name"]
            stack.extend(item.get("inner", []))
        expected.append([decl["name"], [p.get("name") for p in items if p["kind"] == "ParmVarDecl"],
                         decl.get("variadic", False), clang(body, source, labels)])
    actual = []
    for decl in unit["declarations"]:
        if decl["type"] != "FunctionDefinition":
            continue
        d = decl["declarator"]
        while d["declarator"]["type"] != "Identifier":
            d = d["declarator"]
        parameters = d["parameters"]
        variadic = bool(parameters and parameters[-1]["type"] == "Ellipsis")
        params = []
        for param in parameters:
            if param["type"] == "Identifier":
                params.append(param["name"])
            elif param["type"] == "Parameter" and param["declarator"] is not None:
                params.append(name(param["declarator"]))
        actual.append([name(d), params, variadic, orion(decl["body"])])
    if len(expected) != len(actual) or not expected:
        raise ValueError(f"function counts: Clang {len(expected)}, Orion {len(actual)}")
    for want, got in zip(expected, actual, strict=True):
        if compare_host_intmax and want[0] == got[0] == "gz_intmax":
            # limits.h spells INT_MAX differently in Clang and GNU cpp on this target.
            clang_body = ["block", ["return", ["literal", "2147483647"]]]
            gnu_body = ["block", ["return", ["literal", "0x7fffffff"]]]
            if want[3] == clang_body and got[3] == gnu_body:
                got = [*got[:3], clang_body]
        difference = first_difference(want, got)
        if difference:
            raise ValueError(f"{want[0]}: {difference}")
    return len(actual)


def first_difference(want, got):
    if isinstance(want, list) and isinstance(got, list):
        if len(want) != len(got):
            return f"arity {len(want)} vs {len(got)} (Clang {str(want)[:130]}, Orion {str(got)[:130]})"
        for i, (left, right) in enumerate(zip(want, got)):
            diff = first_difference(left, right)
            if diff:
                return f"[{i}]{diff}"
    elif want != got:
        return f" Clang {want!r}, Orion {got!r}"
    return None


def check_version(compiler):
    version = subprocess.check_output([compiler, "--version"], text=True).splitlines()[0]
    if not re.search(r"\bclang version 18\.1\.8\b", version):
        raise ValueError(f"expected Clang 18.1.8, found {version}")


def compare_parser_tests(directory, compiler):
    manifest = ROOT / "docs/conformance/c17-clang-tests.tsv"
    pipeline = CPipeline()
    with manifest.open() as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            filename = row["file"]
            source = (directory / filename).read_bytes()
            if hashlib.sha256(source).hexdigest() != row["sha256"]:
                raise ValueError(f"{filename}: unexpected LLVM fixture digest")
            clang_result = subprocess.run(
                [compiler, *FLAGS, "-Wno-strict-prototypes", "-Wno-deprecated-non-prototype",
                 "-ferror-limit=1", "-x", "c", "-fsyntax-only", "-"],
                input=source, capture_output=True,
            )
            clang_status = "accept"
            if clang_result.returncode:
                diagnostics = clang_result.stderr.decode()
                error = re.search(r"<stdin>:(\d+:\d+): error:", diagnostics)
                if not error:
                    raise ValueError(diagnostics)
                clang_status = error[1]
                if row["clang_reason"] and row["clang_reason"] not in diagnostics:
                    raise ValueError(diagnostics)
            orion_status = "accept"
            try:
                unit = pipeline.parse(source.decode())
            except CParseError as error:
                orion_status = f"{error.line}:{error.column}"
            if (clang_status, orion_status) != (row["clang_first_error"], row["orion_first_error"]):
                raise ValueError(f"{filename}: unexpected Clang {clang_status}, Orion {orion_status}")
            if clang_status == orion_status == "accept" and any(
                decl["type"] == "FunctionDefinition" for decl in unit["declarations"]
            ):
                count = compare(source, compiler, unit)
                print(f"{filename}: {count} function bodies match")
            else:
                print(f"{filename}: Clang {clang_status}, Orion {orion_status}")


def compare_expression_pairs(compiler):
    binary = "* / % + - << >> < <= > >= == != & ^ | && || ,".split()
    assignment = "= *= /= %= += -= <<= >>= &= ^= |=".split()
    expressions = [f"a {first} b {second} c" for first in binary for second in binary]
    expressions.extend(f"a {first} b {second} c" for first in assignment for second in assignment)
    for operator in binary:
        expressions.extend((f"a ? b {operator} c : d", f"a ? b : c {operator} d",
                            f"a {operator} b ? c : d", f"a = b {operator} c"))
    expressions.extend(("a ? b ? c : d : a", "a ? b : c ? d : a", "a ? b = c : d",
                        "a = b ? c : d", "a , b = c", "a = (b , c)", "++a + b--",
                        "sizeof (int) * a", "sizeof (int) {1}", "(unsigned) -a * ~b"))
    source = "".join(f"unsigned e{i}(unsigned a,unsigned b,unsigned c,unsigned d){{return {expr};}}\n"
                     for i, expr in enumerate(expressions))
    return compare(source.encode(), compiler)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--clang", default="clang-18")
    cli.add_argument("--zlib", type=Path, help="pinned zlib 1.3.1 source archive")
    cli.add_argument("--clang-tests", type=Path, help="directory of pinned LLVM Parser fixtures")
    cli.add_argument("--expressions", action="store_true", help="compare precedence and associativity of operator pairs")
    args = cli.parse_args()
    check_version(args.clang)
    total = compare((ROOT / "tests/languages/c/sum.i").read_bytes(), args.clang)
    print(f"acceptance fixture: {total} matching functions")
    if args.expressions:
        print(f"{compare_expression_pairs(args.clang)} expression trees matched")
    if args.clang_tests:
        compare_parser_tests(args.clang_tests, args.clang)
    if args.zlib:
        if hashlib.sha256(args.zlib.read_bytes()).hexdigest() != ZLIB_SHA:
            cli.error("unexpected zlib source archive digest")
        with tempfile.TemporaryDirectory() as directory, tarfile.open(args.zlib) as archive:
            archive.extractall(directory, filter="data")
            for stem in SOLO_SOURCES:
                path = Path(directory) / ZLIB / (stem + ".c")
                source = subprocess.check_output([args.clang, *FLAGS, "-nostdinc", "-DZ_SOLO", "-E", "-P", str(path)])
                count = compare(source, args.clang)
                c_result = get_pipeline(path, c_defines=["Z_SOLO"]).analyze_file(path)
                if not c_result.success:
                    raise ValueError(f"{path.name}: {c_result.errors}")
                compare(source, args.clang, c_result.ast)
                total += count
                print(f"{path.name}: {count} matching functions via .i and .c")
            defines = ["HAVE_UNISTD_H", "_POSIX_C_SOURCE=200809L"]
            for stem in (*SOLO_SOURCES, "gzclose", "gzlib", "gzread", "gzwrite"):
                path = Path(directory) / ZLIB / (stem + ".c")
                source = subprocess.check_output([args.clang, *FLAGS, *["-D" + d for d in defines], "-E", str(path)])
                count = compare(source, args.clang, line_markers=True)
                result = get_pipeline(path, c_defines=defines).analyze_file(path)
                if not result.success:
                    raise ValueError(f"{path.name}: {result.errors}")
                compare(source, args.clang, result.ast, line_markers=True, compare_host_intmax=stem == "gzlib")
                total += count
                print(f"{path.name}: {count} matching hosted functions via .i and .c")
    print(f"{total} function body trees matched")


if __name__ == "__main__":
    main()
