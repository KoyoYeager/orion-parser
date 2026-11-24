"""Check initialized member trees and distinguish reference checker errors from parse errors."""
import argparse
from pathlib import Path
import tempfile

from check_ts_alias_shapes import project_trees
from check_ts_options import _ORACLE as OPTIONS_ORACLE
from check_typescript import COMPILER_SHA, _STATEMENT_SHAPE, TypeScriptPipeline, check_pin, run_compiler


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases, programs, expected = [], [], []
    with tempfile.TemporaryDirectory() as directory:
        for container, code in [("interface I {%s}", 1246), ("type I = {%s}", 1247)]:
            for head in ["a:T", "a?", "readonly a?:T", "get", "set", "['key']", "a\n", "a/*\n*/", "a",
                         "readonly a", '"plain"', "2", "new", "public a:T", "[dynamic()]:T"]:
                for expr in ["42", "make(x + 1)", "({k:[v]})", "(a,b)", "class Named{}", "v satisfies T"]:
                    source = container % (head + " = /*𐐀*/ " + expr)
                    path = Path(directory) / f"{len(cases)}.ts"
                    path.write_text(source, encoding="utf-8")
                    cases.append({"name": str(path), "source": source, "projection": "type member list"})
                    programs.append({"name": str(path), "options": {}, "codes": [1246, 1247]})
                    anchor = "Named" if expr.startswith("class") else "satisfies" if "satisfies" in expr else expr
                    expected.append([] if head in {"public a:T", "[dynamic()]:T"} else [[code, source.index(anchor)]])
        located = run_compiler(archive, OPTIONS_ORACLE, programs)
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    accepted = rejected = failures = 0
    for case, ref, checks, spans in zip(cases, run_compiler(archive, oracle, cases), located, expected, strict=True):
        try:
            tree = TypeScriptPipeline(case["name"]).parse(case["source"])
        except ValueError as exc:
            if ref.get("invalid") and checks["parse"]:
                rejected += 1
                continue
            trees = str(exc)
        else:
            trees = project_trees(tree, case["projection"])
        if trees == ref.get("trees") and not checks["parse"] and checks["located"] == spans:
            accepted += 1
        else:
            print(case["source"], trees, ref, checks["located"], spans)
            failures += 1
    print(f"{accepted} matching member trees and checker locations, {rejected} jointly rejected, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
