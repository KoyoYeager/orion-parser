"""Check all C17 standard library headers on a hosted implementation."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from check_c17 import FLAGS, check_version
from orionparser.registry import get_pipeline


HEADERS = (
    "assert", "complex", "ctype", "errno", "fenv", "float", "inttypes", "iso646", "limits", "locale",
    "math", "setjmp", "signal", "stdalign", "stdarg", "stdatomic", "stdbool", "stddef", "stdint", "stdio",
    "stdlib", "stdnoreturn", "string", "tgmath", "threads", "time", "uchar", "wchar", "wctype",
)


MACRO_BODIES = {
    "stdatomic": "int probe(atomic_int *p) { atomic_store(p, 1); return atomic_load(p); }",
    "complex": "double complex probe(void) { return 1.0 + 2.0 * I; }",
    "tgmath": "double probe(double x) { return sin(x); }",
    "math": "int probe(double x) { return isfinite(x) && signbit(x); }",
    "assert": "int probe(int x) { assert(x); return x; }",
    "inttypes": "const char *format = PRIdMAX;",
    "setjmp": "int probe(jmp_buf b) { return setjmp(b); }",
}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--clang", default="clang-18")
    compiler = cli.parse_args().clang
    check_version(compiler)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "include.c"
        for header in HEADERS:
            body = MACRO_BODIES.get(header, "")
            path.write_text(f"#include <{header}.h>\n{body}\nint main(void) {{ return 0; }}\n")
            subprocess.run([compiler, *FLAGS, "-fsyntax-only", str(path)], check=True)
            result = get_pipeline(path).analyze_file(path)
            if not result.success:
                raise ValueError(f"{header}.h: {result.errors}")
            main_function = result.ast["declarations"][-1]
            if (main_function["type"] != "FunctionDefinition" or
                    main_function["declarator"]["declarator"]["name"] != "main" or
                    main_function["body"]["items"][0]["expression"]["raw"] != "0"):
                raise ValueError(f"{header}.h: missing function after header")
    print(f"{len(HEADERS)} hosted C17 headers and {len(MACRO_BODIES)} macro examples accepted by Clang and Orion")


if __name__ == "__main__":
    main()
