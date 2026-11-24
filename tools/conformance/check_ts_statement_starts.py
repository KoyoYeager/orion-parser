"""Compare contextual statement starts and line breaks across statement lists and embedded statements."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler
from orionparser.languages.javascript.pipeline import SourceSyntaxError


def examples():
    keywords = "public private protected static readonly accessor async declare defer module type interface global namespace using let"
    for before, after in (("", ";"), ("if (ok) ", ";"), ("{", ";}"), ("class C{m(){", ";}}"),
                          ("switch(k){case 1: ", ";}"), ("label: ", ";")):
        for head in keywords.split():
            for gap in (" ", "\n"):
                for tail in ("x", "x = 1", "class C{}", "function f(){}", "interface I{}", "+x",
                             "in obj", "as T", "satisfies T", "instanceof X", "123", "#x"):
                    yield dict(name="statement.ts", source=before + head + gap + tail + after, projection="branch statement", diagnosticSpans=True)
    for head in ("foo", "defer", "letvar", "ifelse", "fuction", "constvariable", "new𐐀x", "retturn", "numbber", "is"):
        for gap in (" ", " /*𐐀*/ ", "\r\n"):
            for tail in ("x", '"value"', "123", "as T", "+z"):
                yield dict(name="statement.ts", source=head + gap + tail + ";", projection="branch statement", diagnosticSpans=True)
    for head in ("interface", "namespace", "module", "type"):
        for tail in ("{}", "if;", '"pkg";', "123;", r"\u0063lass;", " = T;"):
            yield dict(name="statement.ts", source=head + " " + tail, projection="branch statement", diagnosticSpans=True)
    for keyword in ("declare", "async", "export", "abstract", "readonly", "accessor", "public", "private"):
        escaped = keyword[0] + (r"\u%04x" % ord(keyword[1])) + keyword[2:]
        for suffix in (" class C{}", " x;", " in obj;", "\nclass C{}"):
            yield dict(name="statement.ts", source=escaped + suffix, projection="branch statement", diagnosticSpans=True)
    for name in ("statement.mts", "statement.d.ts", "statement.tsx"):
        for keyword in ("public", "protected", "readonly", "static", "private", "accessor"):
            for source in (f"{keyword} /*𐐀*/ in x;", f"if(ok) {keyword} /*𐐀*/ in x;",
                           f"if(ok) {keyword} x;", f"switch(k){{case 1: {keyword} x;}}",
                           f"{keyword} /*\r\n*/ x;", f"let x = {keyword} in obj;"):
                yield dict(name=name, source=source, projection="branch statement",
                           diagnosticSpans=True, compilerModuleDetection=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases = list(examples())
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    accepted = rejected = positioned = failures = 0
    pipelines = {name: TypeScriptPipeline(name) for name in {case["name"] for case in cases}}
    for case, ref in zip(cases, run_compiler(archive, oracle, cases), strict=True):
        try:
            root = pipelines[case["name"]].parse(case["source"])
        except SourceSyntaxError as error:
            diagnostics = ref.get("diagnostics", [])
            code = diagnostics[0][0] if diagnostics else None
            check_position = code in {1128, 1129, 1228, 1260, 1434, 1435, 1437, 1438, 1440, 2427, 2457, 2819}
            suggestion = ref.get("firstMessage", "").partition("Did you mean '")[2].partition("'?")[0]
            if (ref.get("invalid") and 0 <= error.offset <= len(case["source"]) and
                    (not check_position or (diagnostics[0] == [error.code, error.offset, error.length])) and
                    (code != 1435 or f"'{suggestion}'" in str(error))):
                positioned += int(check_position)
                rejected += 1
                continue
            actual = str(error)
        else:
            actual = project_trees(root, "branch statement")
            if actual and actual == ref.get("trees"):
                accepted += 1
                continue
        print(repr(case["source"]), actual, ref)
        failures += 1
    print(f"{accepted} matching statement trees, {rejected} jointly rejected files ({positioned} contextual diagnostics checked), {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
