"""Compare PLY acceptance to TypeScript 5.9.3 createSourceFile parse diagnostics."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

from orionparser.languages.typescript.pipeline import TypeScriptPipeline

COMPILER_SHA = "10e108c9cf7d5f2879053dff18515fb405abf2ccef63eaaf017d9c571687a1d3"
SOURCE_SHA = "d371a2430d6305290d1bddaf195fdd629d1a8708cda08f4a72fc923b65d36c4a"
_TEST_OPTION = re.compile(r"^//\s*@(\w+)\s*:\s*([^\r\n]*)")
_STATEMENT_SHAPE = """
function statementShape(node) {
    const kind = [
        ['Block','BlockStatement'], ['DoStatement','DoWhileStatement'], ['DebuggerStatement','DebuggerStatement'],
        ['VariableStatement','VariableDeclaration'], ['ModuleDeclaration','TSModuleDeclaration'],
        ['InterfaceDeclaration','TSInterfaceDeclaration'], ['TypeAliasDeclaration','TSTypeAliasDeclaration'],
        ['EnumDeclaration','TSEnumDeclaration'], ['ImportEqualsDeclaration','TSImportEqualsDeclaration'],
        ['ExportDeclaration','ExportDeclaration'], ['ExportAssignment','ExportAssignment'],
        ['NamespaceExportDeclaration','TSNamespaceExportDeclaration']
    ].find(([tsKind]) => ts.SyntaxKind[tsKind] === node.kind)?.[1] || ts.SyntaxKind[node.kind];
    return [kind, node.name?.text ?? null];
}
"""
_ORACLE = _STATEMENT_SHAPE + """
const ts = require(process.argv[1]);
if (ts.version !== '5.9.3') throw new Error('Unexpected compiler version');
const cases = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(({name, source, matrixPath, options}) => {
    let file;
    if (matrixPath) {
        const parsed = ts.convertCompilerOptionsFromJson(options, require('node:path').dirname(matrixPath));
        if (parsed.errors.length) return {optionErrors: parsed.errors.map(d => d.code)};
        const opts = parsed.options;
        const format = ts.getImpliedNodeFormatForFile(matrixPath, undefined, ts.sys, opts);
        file = ts.createSourceFile(matrixPath, source, {
            languageVersion: ts.getEmitScriptTarget(opts),
            impliedNodeFormat: format,
            setExternalModuleIndicator: ts.getSetExternalModuleIndicator(opts)
        }, true);
    } else {
        file = ts.createSourceFile(name, source, ts.ScriptTarget.ESNext, true);
    }
    return {sourceType: ts.isExternalModule(file) ? 'module' : 'script', statements: file.statements.map(statementShape), diagnostics: file.parseDiagnostics.map(d => ({
        code: d.code, offset: d.start, message: ts.flattenDiagnosticMessageText(d.messageText, ' ')
    }))};
})));
"""


_CHECKER = """
const ts = require(process.argv[1]);
const cases = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const result = cases.map(({source, name, line}) => {
    const fileName = '/' + name.split('/').pop();
    const options = {target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext,
                     jsx: ts.JsxEmit.Preserve, noLib: true, noEmit: true, noResolve: true};
    const file = ts.createSourceFile(fileName, source, options.target, true);
    const host = ts.createCompilerHost(options);
    host.getSourceFile = name => name === fileName ? file : undefined;
    host.fileExists = name => name === fileName;
    host.readFile = name => name === fileName ? source : undefined;
    const program = ts.createProgram([fileName], options, host);
    return program.getSemanticDiagnostics(file)
        .filter(d => d.start !== undefined && file.getLineAndCharacterOfPosition(d.start).line + 1 === line)
        .map(d => [d.code, ts.flattenDiagnosticMessageText(d.messageText, ' ')]);
});
process.stdout.write(JSON.stringify(result));
"""


def run_compiler(archive, oracle, cases):
    with tempfile.TemporaryDirectory() as directory, tarfile.open(archive) as tar:
        ts = Path(directory) / "typescript.cjs"
        ts.write_bytes(tar.extractfile("package/lib/typescript.js").read())
        output = subprocess.check_output(["node", "-e", oracle, str(ts)], input=json.dumps(cases), text=True)
    return json.loads(output)


def check_pin(path, digest):
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError(f"Unexpected archive digest: {path}")


def test_units(text, relative):
    """Split conformance fixtures as makeUnitsFromTest does in harnessIO.ts."""
    name, lines = None, []
    units = []
    for line in re.split(r"\r\n|\n|\r", text):
        directive = _TEST_OPTION.match(line)
        if directive:
            if directive[1].lower() == "filename":
                if name is not None:
                    units.append((name, "\n".join(lines)))
                name, lines = directive[2].strip(), []
            continue
        # The upstream builder collapses initial empty content in each file.
        if lines or line:
            lines.append(line)
    units.append((name or Path(relative).name, "\n".join(lines)))
    return units


def fixture_sources(archive, selection):
    prefix = "TypeScript-5.9.3/tests/cases/conformance/" + selection.rstrip("/") + "/"
    if selection == ".":
        prefix = "TypeScript-5.9.3/tests/cases/conformance/"
    elif selection == "compiler-tests":
        prefix = "TypeScript-5.9.3/tests/cases/compiler/"
    elif selection == "compiler":
        prefix = "TypeScript-5.9.3/src/compiler/"
    if selection in {"lib", "compiler-api"}:
        prefix = "package/lib/"
    with tarfile.open(archive) as tar:
        for member in tar:
            if not member.isfile() or not member.name.startswith(prefix) or not member.name.endswith((".ts", ".tsx", ".cts", ".mts")):
                continue
            relative = member.name.removeprefix(prefix)
            if selection == "compiler-api" and relative != "typescript.d.ts":
                continue
            if selection == "lib" and not (relative.startswith("lib.") and relative.endswith(".d.ts")):
                continue
            data = tar.extractfile(member).read()
            if data.startswith((b"\xff\xfe", b"\xfe\xff")):
                text = data.decode("utf-16", errors="replace")
            else:
                # The Node-hosted TS reader replaces malformed UTF-8; the
                # compiler regression corpus includes deliberately corrupt files.
                text = data.decode("utf-8-sig", errors="replace")
            if selection in {"compiler", "lib", "compiler-api"}:
                virtual = [(relative, text)]
            else:
                virtual = test_units(text, relative)
            yield relative, text, virtual


def source_cases(archive, selection):
    for fixture, _, virtual in fixture_sources(archive, selection):
        for name, source in virtual:
            if name.endswith((".ts", ".tsx", ".cts", ".mts")):
                yield {"file": fixture, "name": name, "source": source}


def statement_shape(node):
    kind = node["type"]
    if kind == "ExportNamedDeclaration":
        if node["declaration"]:
            return statement_shape(node["declaration"])
        kind = "ExportDeclaration"
    elif kind == "ExportAllDeclaration":
        kind = "ExportDeclaration"
    elif kind == "ExportDefaultDeclaration":
        decl = node["declaration"]
        if decl["type"].endswith("Declaration") or decl["type"] == "TSDeclareFunction":
            return statement_shape(decl)
        return ["ExportAssignment", None]
    elif kind == "TSExportAssignment":
        kind = "ExportAssignment"
    elif kind == "TSDeclareFunction":
        kind = "FunctionDeclaration"
    ident = node.get("id") or {}
    return [kind, ident.get("name", ident.get("value"))]


def library_shape_matches(name, body):
    """Check nested declarations from the pinned compiler's standard libraries."""
    if name == "lib.es5.d.ts":
        alias = next((n for n in body if n.get("id", {}).get("name") == "ThisParameterType"), None)
        if not alias:
            return False
        conditional = alias.get("typeAnnotation", {})
        bound = conditional.get("extendsType", {})
        params = bound.get("params", [])
        return (conditional.get("type") == "TSConditionalType" and bound.get("type") == "TSFunctionType"
                and len(params) == 2 and params[0].get("name") == "this"
                and params[0]["typeAnnotation"]["typeAnnotation"]["type"] == "TSInferType")
    owner, member = {"lib.dom.d.ts": ("Attr", "textContent"),
                     "lib.es2024.arraybuffer.d.ts": ("ArrayBuffer", "maxByteLength")}[name]
    elements = [m for n in body if n["type"] == "TSInterfaceDeclaration" and n["id"]["name"] == owner
                for m in n["body"]["body"] if m.get("key", {}).get("name") == member]
    if name == "lib.dom.d.ts":
        return [m.get("kind") for m in elements] == ["get", "set"] and len(elements[1]["params"]) == 1
    return any(m.get("kind") == "get" and m["returnType"]["typeAnnotation"]["type"] == "TSNumberKeyword"
               for m in elements)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler_archive", type=Path)
    cli.add_argument("source_archive", type=Path)
    cli.add_argument("selection", nargs="?", default="types/typeAliases",
                     help="conformance directory, compiler regression cases (compiler-tests), compiler sources (compiler), bundled libraries (lib), or public API declaration file (compiler-api)")
    cli.add_argument("--checker", action="store_true",
                     help="Also show isolated checker diagnostics on lines rejected only by Orion")
    cli.add_argument("--report", type=Path, help="Write source-level mismatches as JSON lines")
    args = cli.parse_args()
    check_pin(args.compiler_archive, COMPILER_SHA)
    check_pin(args.source_archive, SOURCE_SHA)
    cases = list(source_cases(args.compiler_archive if args.selection in {"lib", "compiler-api"} else args.source_archive, args.selection))
    oracle = run_compiler(args.compiler_archive, _ORACLE, cases)
    checker_cases = []
    mismatches = shape_differences = library_checks = library_failures = 0
    records = []
    for case, reference in zip(cases, oracle, strict=True):
        diagnostics = reference["diagnostics"]
        try:
            ast = TypeScriptPipeline(case["name"]).parse(case["source"])
            accepted, detail = True, "Orion accepted"
        except ValueError as error:
            accepted, detail = False, str(error)
        except Exception as error:
            accepted, detail = None, f"internal {type(error).__name__}: {error}"
        if accepted is None or accepted == bool(diagnostics):
            mismatches += 1
            print(case["file"], case["name"], "ts=" + str(diagnostics[:1]), detail)
            records.append({"fixture": case["file"], "name": case["name"], "category": "acceptance",
                            "referenceDiagnostics": diagnostics, "orion": accepted, "detail": detail})
            if args.checker and not accepted and not diagnostics:
                match = re.match(r"line (\d+), column ", detail)
                if match:
                    checker_cases.append({**case, "line": int(match[1]), "record": records[-1]})
        elif accepted:
            actual = [statement_shape(stmt) for stmt in ast["body"]]
            if actual != reference["statements"]:
                shape_differences += 1
                print(case["file"], case["name"], "top-level statement kind/name difference")
                records.append({"fixture": case["file"], "name": case["name"], "category": "structure",
                                "reference": reference["statements"], "orion": actual})
            if args.selection == "lib" and case["name"] in {"lib.es5.d.ts", "lib.dom.d.ts", "lib.es2024.arraybuffer.d.ts"}:
                library_checks += 1
                if not library_shape_matches(case["name"], ast["body"]):
                    library_failures += 1
                    print(case["file"], "nested library declaration differs")
    if args.selection == "lib":
        if library_checks != 3:
            raise ValueError(f"Expected 3 accepted library structure fixtures, checked {library_checks}")
        print(f"{library_checks} nested library AST checks, {library_failures} differences")
    if checker_cases:
        for case, messages in zip(checker_cases, run_compiler(args.compiler_archive, _CHECKER, checker_cases), strict=True):
            case["record"]["checkerDiagnosticsOnLine"] = messages
            if messages:
                print("checker", case["file"], case["name"], "line", case["line"], messages)
    if args.report:
        with args.report.open("w", encoding="utf-8") as report:
            for record in records:
                report.write(json.dumps(record) + "\n")
    print(f"{len(cases)} source files, {mismatches} parse-acceptance differences, "
          f"{shape_differences} top-level structure differences among jointly accepted files")
    return int(not cases or bool(mismatches or shape_differences or library_failures))


if __name__ == "__main__":
    raise SystemExit(main())
