"""Compare pinned fmt 10.2.1 implementation units on the native C++20 header configuration."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from check_cpp20 import FIXTURES, check_version, type_name


DIGEST = "0768f9039efac3b645302511ec58a0bf381e6bc1fc261f00bbdc05dc920e336a"
# The default format.cc explicitly instantiates these eleven library entries.
TARGETS = {"dragonbox::to_decimal": 2, "locale_ref::locale_ref": 1, "locale_ref::get": 1,
           "thousands_sep_impl": 2, "decimal_point_impl": 2, "buffer::append": 2, "vformat_to": 1}


def check_tree(tree):
    digest = hashlib.sha256()
    for path in sorted([*tree.glob("include/fmt/*.h"), *tree.glob("src/*.cc")]):
        digest.update(path.relative_to(tree).as_posix().encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    if digest.hexdigest() != DIGEST:
        raise ValueError("unexpected fmt headers or sources; expected commit e69e5f977d458f2650bb346dadf2ad30c5320281")


def reference_nodes(compiler, src, query):
    dump = subprocess.check_output([*compiler, "-fsyntax-only", "-Xclang", "-ast-dump=json",
                                    "-Xclang", "-ast-dump-filter=" + query, src]).decode()
    decoder = json.JSONDecoder()
    index = 0
    while index < len(dump):
        if dump[index].isspace():
            index += 1
            continue
        node, index = decoder.raw_decode(dump, index)
        yield node


def reference_signatures(compiler, src, name):
    # append's concrete methods are dumped under the specializations of buffer.
    query = "buffer" if name == "buffer::append" else name
    result = set()

    def visit(node, owner):
        if node["kind"] == "ClassTemplateSpecializationDecl":
            args = [c["type"]["qualType"] for c in node.get("inner", []) if c["kind"] == "TemplateArgument" and "type" in c]
            owner = node.get("name", "") + "<" + ", ".join(args) + ">"
        if node.get("mangledName") and node.get("name") == name.split("::")[-1]:
            children = node.get("inner", [])
            if any(c["kind"] == "CompoundStmt" for c in children):
                scope = owner if name == "buffer::append" else None
                result.add((scope, node["type"]["qualType"]))
        for child in node.get("inner", []):
            visit(child, owner)

    for node in reference_nodes(compiler, src, "fmt::detail::" + query):
        visit(node, None)
    return result


def check_definitions(ast, compiler, src):
    last = ast["declarations"][-1]
    for name in ("fmt", "v10", "detail"):
        if last["type"] != "NamespaceDefinition" or [p["name"] for p in last["path"]] != [name]:
            raise ValueError(f"missing final namespace {name}")
        if name != "detail":
            last, = last["declarations"]

    actual = Counter()
    checked = {}
    for entry in last["declarations"]:
        if entry["type"] != "ExplicitInstantiation" or entry["extern"]:
            raise ValueError("unexpected declaration in final fmt namespace")
        decl = entry["declaration"]
        name = decl["name"]
        fn = {"type": "FunctionOperator", "parameters": decl["parameters"], "qualifiers": decl.get("qualifiers", []),
              "noexcept": decl["noexcept"], "trailingReturnType": decl.get("trailingReturnType")}
        ret = decl.get("returnType", {"type": "Type", "specifiers": ["void"], "indirections": []})
        signature = type_name(ret, [fn])
        # Clang prints these names in their declaration contexts and expands
        # the string_view alias and the default char argument of vformat_args.
        if name == "dragonbox::to_decimal":
            signature = signature.replace("dragonbox::decimal_fp", "decimal_fp")
        if name == "vformat_to":
            signature = signature.replace("string_view,", "basic_string_view<char>,").replace("vformat_args<>", "vformat_args<char>")
        owner = type_name(decl["owner"]) if "owner" in decl else None
        if name not in TARGETS or (owner, signature) in checked.setdefault(name, set()):
            raise ValueError(f"unexpected or duplicate instantiation: {name} {signature}")
        checked[name].add((owner, signature))
        actual[name] += 1
    if actual != TARGETS:
        raise ValueError(f"unexpected fmt instantiation counts: {actual}")
    for name, signatures in checked.items():
        missing = signatures - reference_signatures(compiler, src, name)
        if missing:
            raise ValueError(f"Clang definition missing for {name}: {missing}")
    return ast["declarations"][-1:]


def check_os(ast, compiler, src):
    actual, expected = Counter(), Counter()
    clang_kinds = {"IfStmt": "IfStatement", "DoStmt": "DoWhileStatement", "ReturnStmt": "ReturnStatement"}
    decl_kinds = {"VarDecl": "VariableDeclaration", "TypeAliasDecl": "AliasDeclaration", "StaticAssertDecl": "StaticAssertion"}

    def collect(node, scope):
        kind = node["type"]
        if kind == "NamespaceDefinition":
            path = [p["name"] for p in node["path"] if p["name"] != "v10"]
            for child in node["declarations"]:
                collect(child, scope + path)
        elif "parameters" in node:
            op = {"type": "FunctionOperator", "parameters": node["parameters"], "qualifiers": node.get("qualifiers", []),
                  "noexcept": node.get("noexcept") or kind == "DestructorDeclaration"}
            result = node.get("returnType", {"type": "Type", "specifiers": ["void"], "indirections": []})
            body = (node.get("body") or {}).get("statements", [])
            actual[("::".join([*scope, node["name"]]), type_name(result, [op]), node.get("functionSpecifier"),
                    tuple(stmt["type"] for stmt in body))] += 1

    for node in ast["declarations"][-2:]:
        collect(node, [])
    for query, prefix in (("convert_rwcount", ""), ("fmt::buffered_file::", "fmt::buffered_file::"),
                          ("fmt::file::", "fmt::file::"), ("fmt::getpagesize", "fmt::"),
                          ("fmt::detail::file_buffer::", "fmt::detail::file_buffer::"), ("fmt::ostream::~ostream", "fmt::ostream::")):
        for node in reference_nodes(compiler, src, query):
            if node.get("loc", {}).get("file") != str(src):
                continue
            block = next((c for c in node.get("inner", []) if c["kind"] == "CompoundStmt"), None)
            if block is None and not node.get("explicitlyDefaulted"):
                continue
            body = []
            for stmt in (block or {}).get("inner", []):
                kind = stmt["kind"]
                if kind == "DeclStmt":
                    child, = stmt["inner"]
                    body.append(decl_kinds[child["kind"]])
                elif kind.endswith(("Expr", "Operator")) or kind == "ExprWithCleanups":
                    body.append("ExpressionStatement")
                else:
                    body.append(clang_kinds[kind])
            expected[(prefix + node["name"], node["type"]["qualType"], node.get("explicitlyDefaulted"), tuple(body))] += 1
    if actual != expected or actual.total() != 22:
        raise ValueError(f"os.cc function differences: Orion {actual - expected}, Clang {expected - actual}")
    return ast["declarations"][-2:]


def check_module_layout(ast, sections, *, clang_input):
    if not (ast.get("globalModuleFragment") or {}).get("declarations"):
        raise ValueError("missing declarations from the global module fragment")
    if ast.get("module") != {"type": "ModuleDeclaration", "name": "fmt", "exported": True, "partition": None}:
        raise ValueError("expected the fmt module interface")
    private = ast["privateModuleFragment"]
    if (private is not None) != clang_input:
        raise ValueError("module fragment layout differs from the selected fmt compiler configuration")

    exported = set()
    def collect(node, public=False):
        public = public or node["type"] == "ExportDeclaration"
        if public:
            name = node.get("declaration", node).get("name")
            if name:
                exported.add(name)
        for child in node.get("declarations", []):
            collect(child, public)
    for node in ast["declarations"]:
        collect(node)
    required = {"format", "format_to", "print", "vformat", "ostream", "file", "memory_buffer"}
    if required - exported:
        raise ValueError(f"missing module exports: {required - exported}")

    def without_offsets(node):
        if isinstance(node, dict):
            return {k: without_offsets(v) for k, v in node.items() if k not in {"startOffset", "endOffset"}}
        if isinstance(node, list):
            return [without_offsets(v) for v in node]
        return node

    if without_offsets((private or ast)["declarations"][-len(sections):]) != without_offsets(sections):
        raise ValueError("included implementation sections differ from the two standalone translation units")


def check_module_import(compiler, src, directory):
    bmi = directory / "fmt.pcm"
    subprocess.run([*compiler, "-Wno-include-angled-in-module-purview", "-x", "c++-module",
                    "--precompile", src, "-o", bmi], check=True)
    consumer = directory / "consumer.cpp"
    consumer.write_text('#include <string>\nimport fmt;\nstd::string check() { return fmt::format("{}", 42); }\n')
    subprocess.run([*compiler, "-fmodule-file=fmt=" + str(bmi), "-fsyntax-only", consumer], check=True)


def check_paths(src, include, compiler, directory, compare):
    expanded, output = directory / (src.stem + ".ii"), directory / "output.json"
    results = {}
    source_digest = None
    for mode in ("source", "gnu", "clang"):
        path = src if mode == "source" else expanded
        if mode != "source":
            if mode == "gnu":
                command = ["g++", "-std=c++20", "-pedantic-errors", "-I" + str(include), "-x", "c++"]
            else:
                dialect = "c++-module" if src.name == "fmt.cc" else "c++"
                command = [*compiler, "-Wno-include-angled-in-module-purview", "-x", dialect]
            with expanded.open("wb") as stream:
                subprocess.run([*command, "-E", src], stdout=stream, check=True)
        with output.open("wb") as stream:
            subprocess.run([sys.executable, "-m", "orionparser", "parse", path, "-I", include, "--json"],
                           stdout=stream, check=True)
        if mode != "clang":
            with output.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").digest()
            if mode == "source":
                source_digest = digest
                continue
            if digest != source_digest:
                raise ValueError(f"{src.name}: source and GNU-preprocessed CLI JSON differ")
        with output.open() as stream:
            results[mode] = compare(json.load(stream), mode)
    return results


def check_clients(include, compiler, directory):
    def find(node, kind):
        if node["kind"] == kind:
            return node
        for child in node.get("inner", []):
            match = find(child, kind)
            if match is not None:
                return match

    for header in ("chrono", "ranges", "std"):
        src = FIXTURES / "fmt" / (header + ".cpp")
        text = src.read_bytes()
        main, = (n for n in reference_nodes(compiler, src, "main")
                 if n.get("name") == "main" and n.get("loc", {}).get("file") == str(src))
        condition, yes, no = find(main, "ConditionalOperator")["inner"]
        op, lhs, rhs = condition["inner"]
        callee, fmt, value = find(lhs, "CallExpr")["inner"]
        def spelling(node):
            begin, end = node["range"]["begin"], node["range"]["end"]
            return text[begin["offset"]:end["offset"] + end["tokLen"]].decode()
        reference = (find(op, "DeclRefExpr")["referencedDecl"]["name"], spelling(callee), spelling(fmt),
                     spelling(value), spelling(rhs), yes["value"], no["value"])

        def compare(tree, mode):
            func = tree["declarations"][-1]
            stmt = func["body"]["statements"][-1]
            expr = stmt["expression"]
            test = expr["test"]
            call = test["left"]
            fmt_arg, arg = call["arguments"]
            if func["name"] != "main" or stmt["type"] != "ReturnStatement" or expr["type"] != "ConditionalExpression":
                raise ValueError(f"{src.name}: missing main return conditional")
            if arg["type"] == "TypeConstruction":
                literal, = arg["initializer"]["elements"]
                argument = type_name(arg["target"]) + "{" + literal["raw"] + "}"
            else:
                argument = arg["name"]
            actual = ("operator" + test["operator"], call["callee"]["name"], fmt_arg["parts"][0],
                      argument, test["right"]["parts"][0], expr["then"]["raw"], expr["else"]["raw"])
            if actual != reference:
                raise ValueError(f"{src.name} {mode}: Orion {actual!r}, Clang {reference!r}")

        check_paths(src, include, compiler, directory, compare)
        print(f"fmt 10.2.1 {header}.h client: source and expanded input matched the Clang call and return expression")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tree", type=Path)
    parser.add_argument("--clang", default="clang-18")
    parser.add_argument("--clients-only", action="store_true", help="verify the three public-header clients")
    args = parser.parse_args()
    tree = args.tree.resolve()
    check_tree(tree)
    check_version(args.clang)
    include = tree / "include"
    compiler = [args.clang, "-std=c++20", "-pedantic-errors", "-I" + str(include)]
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        check_clients(include, compiler, directory)
        if args.clients_only:
            return
        sections = {"gnu": [], "clang": []}
        for name, compare in (("format.cc", check_definitions), ("os.cc", check_os)):
            src = tree / "src" / name
            results = check_paths(src, include, compiler, directory, lambda ast, mode: compare(ast, compiler, src))
            for mode, nodes in results.items():
                sections[mode].extend(nodes)
            print(f"fmt 10.2.1 {name}: identical source/GNU JSON; both preprocessor configurations matched Clang definitions")
        module = tree / "src/fmt.cc"
        check_paths(module, include, compiler, directory,
                    lambda ast, mode: check_module_layout(ast, sections[mode], clang_input=mode == "clang"))
        check_module_import(compiler, module, directory)
        print("fmt 10.2.1 fmt.cc: exports and implementation sections matched for both module layouts; Clang import verified")


if __name__ == "__main__":
    main()
