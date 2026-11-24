"""Compare syntax acceptance for a pinned Test262 language directory or the entire language suite."""
import argparse
import hashlib
import json
from contextlib import ExitStack, contextmanager
from pathlib import Path
import subprocess
import sys
import tarfile

import yaml

from orionparser.languages.javascript.pipeline import JavaScriptModulePipeline, JavaScriptPipeline


REVISION = "d2596e265142410a6cb7a01d0ae4bc2fce84ce8b"
ARCHIVE_HASH = "562bc1c60d66dbde6e4e128a99007ac91dc3ca0587d5e232d7a12d3fda75d9ec"


def variants(source, metadata):
    flags = metadata.get("flags", [])
    if "module" in flags:
        yield "module", source
    elif "raw" in flags:
        yield "script", source
    else:
        if "onlyStrict" not in flags:
            yield "script", source
        if "noStrict" not in flags:
            yield "strict", '"use strict";\n' + source


_ORACLE = """
const vm = require("node:vm");
const lines = require("node:readline").createInterface({ input: process.stdin });
lines.on("line", line => {
    const [mode, src] = JSON.parse(line);
    try {
        if (mode === "module") new vm.SourceTextModule(src);
        else new vm.Script(src);
        process.stdout.write("accepted\\n");
    } catch (error) {
        if (!(error instanceof SyntaxError)) throw error;
        process.stdout.write("rejected\\n");
    }
});
"""


@contextmanager
def node_reference():
    with subprocess.Popen(["node", "--no-warnings", "--experimental-vm-modules", "-e", _ORACLE],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as oracle:
        def accepts(source, mode):
            oracle.stdin.write(json.dumps([mode, source]) + "\n")
            oracle.stdin.flush()
            result = oracle.stdout.readline().strip()
            if result not in {"accepted", "rejected"}:
                raise RuntimeError(f"Node reference protocol failed: {result!r}")
            return result == "accepted"

        try:
            yield accepts
        finally:
            oracle.stdin.close()


def reference_accepts(source, mode):
    with node_reference() as accepts:
        return accepts(source, mode)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("archive", type=Path)
    cli.add_argument("directory", nargs="?", default="expressions/exponentiation")
    cli.add_argument("--variants", action="store_true", help="Apply Test262 flags and check expected parse outcomes")
    cli.add_argument("--annex-b", action="store_true", help="Use the Annex B language suite")
    cli.add_argument("--mismatch-report", type=Path, metavar="FILE", help="Write one JSON object per mismatch")
    args = cli.parse_args()
    archive = args.archive
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != ARCHIVE_HASH:
            raise SystemExit("Test262 archive does not match the recorded SHA-256")
    if subprocess.check_output(["node", "--version"], text=True).strip() != "v24.20.0":
        raise SystemExit("Expected Node.js 24.20.0")
    suite = "annexB/language" if args.annex_b else "language"
    prefix = f"test262-{REVISION}/test/{suite}/"
    if args.directory != ".":
        prefix += args.directory.strip("/") + "/"
    mismatches = files = cases = 0
    script, module = JavaScriptPipeline(), JavaScriptModulePipeline()
    with ExitStack() as stack:
        corpus = stack.enter_context(tarfile.open(archive))
        accepts = stack.enter_context(node_reference())
        report = stack.enter_context(args.mismatch_report.open("w", encoding="utf-8")) if args.mismatch_report else None
        for member in corpus:
            if not (member.isfile() and member.name.startswith(prefix) and member.name.endswith(".js")):
                continue
            if member.name.endswith("_FIXTURE.js"):
                continue
            source = corpus.extractfile(member).read().decode("utf-8")
            modes = [("script", source)]
            expected = None
            metadata = {}
            if args.variants:
                metadata = yaml.safe_load(source.split("/*---", 1)[1].split("---*/", 1)[0])
                modes = variants(source, metadata)
                expected = metadata.get("negative", {}).get("phase") not in {"parse", "early"}
            files += 1
            for mode, program in modes:
                reference = accepts(program, mode)
                try:
                    (module if mode == "module" else script).parse(program)
                    actual, error = True, ""
                except ValueError as exc:
                    actual, error = False, str(exc)
                except Exception as exc:
                    # An internal parser failure is always a mismatch, including for parse-negative cases.
                    actual, error = None, f"internal {type(exc).__name__}: {exc}"
                if actual != reference or (expected is not None and reference != expected):
                    print(member.name.removeprefix(prefix), mode, f"expected={expected} node={reference}",
                          error or "Orion accepted")
                    if report:
                        record = {"file": member.name.split("/test/", 1)[1], "mode": mode,
                                  "features": metadata.get("features", []), "expected": expected,
                                  "node": reference, "orion": actual, "error": error}
                        report.write(json.dumps(record, ensure_ascii=True) + "\n")
                    mismatches += 1
                cases += 1
    print(f"{files} files, {cases} cases, {mismatches} mismatches")
    return int(not cases or bool(mismatches))


if __name__ == "__main__":
    sys.exit(main())
