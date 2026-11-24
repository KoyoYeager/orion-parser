"""Compare TypeScript merge-marker recognition, rejection offsets and surrounding expressions."""
import argparse
from pathlib import Path

from orionparser.languages.javascript.pipeline import SourceSyntaxError
from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler


def examples():
    for char in "<>|=":
        for count in (6, 7, 8):
            for suffix in ("", " ", "\tname", "\nnext", " label"):
                yield "case.ts", char * count + suffix
        marker = char * 7 + " label"
        for separator in ("", " ", "\n", "\r", "\r\n", "\u2028", "\u2029", "\u0085", "\n "):
            yield "case.ts", "/*𐐀*/a;" + separator + marker
        for wrapper in ("/*\n@\n*/ x;", "`text\n@\n`;", '"@";', "// @\nx;"):
            yield "case.ts", wrapper.replace("@", marker)
        for wrapper in ("<A>text\n@\n</A>;", '<A v="text\n@\n"/>;', "<A\n@\n/>;", "<A>{x;\n@\n}</A>;"):
            yield "case.tsx", wrapper.replace("@", marker)
    yield "case.ts", "a;\n||||||| base\nb;\n=======\nc;\n>>>>>>> theirs"
    yield "case.ts", "a;\n<<<<<<< HEAD\nb;\n=======\nc;\n>>>>>>> theirs"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases = [{"name": name, "source": src, "projection": "target expression", "diagnosticSpans": True}
             for name, src in examples()]
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    accepted = markers = other_errors = failures = 0
    for case, ref in zip(cases, run_compiler(archive, oracle, cases), strict=True):
        try:
            root = TypeScriptPipeline(case["name"]).parse(case["source"])
        except SourceSyntaxError as exc:
            diagnostics = ref.get("diagnostics", [])
            marker_offsets = [offset for code, offset, length in diagnostics if code == 1185 and length == 7]
            if "TS1185" in str(exc):
                if marker_offsets and exc.offset == marker_offsets[0]:
                    markers += 1
                    continue
            elif diagnostics and (not marker_offsets or exc.offset < marker_offsets[0]):
                other_errors += 1
                continue
            actual = str(exc)
        else:
            actual = project_trees(root, "target expression")
            if actual == ref.get("trees"):
                accepted += 1
                continue
        failures += 1
        print(repr(case["source"]), actual, ref)
    print(f"{accepted} matching ASTs, {markers} matching marker offsets, {other_errors} other joint rejections, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
