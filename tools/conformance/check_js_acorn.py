"""Parse the distributed JavaScript sources of Acorn 8.14.1 without executing them."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tarfile

from check_js_exponentiation import reference_accepts
from orionparser.languages.javascript.pipeline import JavaScriptModulePipeline, JavaScriptPipeline


DIGEST = "e9ca7f9939683a07d74565636ab8cc29f5fbc886a3e7a54af22c2f9e0f59930f"
SOURCES = ("package/bin/acorn", "package/dist/bin.js", "package/dist/acorn.js", "package/dist/acorn.mjs")


def main():
    archive = Path(sys.argv[1])
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != DIGEST:
            raise SystemExit("Expected the Acorn 8.14.1 npm tarball")
    if subprocess.check_output(["node", "--version"], text=True).strip() != "v24.20.0":
        raise SystemExit("Expected Node.js 24.20.0")
    failures = 0
    with tarfile.open(archive) as package:
        for path in SOURCES:
            source = package.extractfile(path).read().decode("utf-8")
            module = path.endswith(".mjs")
            if not reference_accepts(source, "module" if module else "script"):
                raise RuntimeError(f"Reference rejected {path}")
            try:
                ast = (JavaScriptModulePipeline() if module else JavaScriptPipeline()).parse(source)
                if module:
                    functions = {n["id"]["name"] for n in ast["body"] if n["type"] == "FunctionDeclaration"}
                    exports = {(s["local"]["name"], s["exported"]["name"]) for n in ast["body"]
                               if n["type"] == "ExportNamedDeclaration" for s in n["specifiers"]}
                    if not {"parse", "getLineInfo", "parseExpressionAt", "tokenizer"} <= functions:
                        raise ValueError("missing public parser function declaration")
                    if not {("parse", "parse"), ("types", "tokContexts")} <= exports:
                        raise ValueError("missing public export")
                print(f"{path}: accepted, {len(ast['body'])} top-level items")
            except ValueError as error:
                print(f"{path}: {error}")
                failures += 1
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
