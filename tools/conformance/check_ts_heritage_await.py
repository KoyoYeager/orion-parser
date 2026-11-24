"""Compare await in class heritage under export, ambient, and function contexts."""
import argparse
from pathlib import Path

from orionparser.languages.javascript.pipeline import SourceSyntaxError
from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler


def examples():
    for name in ("heritage.ts", "heritage.d.ts", "heritage.mts", "heritage.d.cts"):
        for prefix, suffix in (("", ""), ("export ", ""), ("export default ", ""),
                               ("export declare ", ""), ("export {}; ", ""), ("export {}; declare ", ""),
                               ("namespace N {export ", "}"), ("async function f(){", "}")):
            for clause in ("extends await", "implements Base, await", "extends (await x)",
                           "extends (await)", "extends obj.await", "extends f(await)", "extends (x=>await)", "extends obj[await]", "extends f(async()=>await x)",
                           "extends f(function(){return await})", "extends (await X).Base", "extends await.Base"):
                yield {"name": name, "source": prefix + "class C " + clause + " {}" + suffix,
                       "projection": "heritage source", "diagnosticSpans": True, "compilerModuleDetection": True}
        for source in (
            "export declare class C<T> extends Base<T>, await {x:1};",
            "export default abstract class C extends await {method(){return x}}",
            "export class Outer { field=class Inner extends f(function(){return await}){}; }",
            "class C extends Base<await> {}",
            "export class C extends await {}; next;",
            "namespace N { declare class C extends await {} }",
            "export {}; namespace N { class C extends await {} }",
        ):
            yield {"name": name, "source": source, "projection": "heritage source",
                   "diagnosticSpans": True, "compilerModuleDetection": True}
        for argument in ("await", "A, await", "(await)", "F<await>", "await[]"):
            yield {"name": name, "source": f"export declare class C extends Base<{argument}> {{}}",
                   "projection": "heritage source", "diagnosticSpans": True, "compilerModuleDetection": True}


def repeated_reference_statement(case, ref, actual):
    if case["source"] not in {"export declare class C<T> extends Base<T>, await {x:1};",
                              "export class C extends await {}; next;"}:
        return False
    trees = ref.get("trees", [])
    spans = ref.get("statementSpans", [])
    if len(spans) < 3 or spans[-1][0] < spans[-2][0] or spans[-1][1] != spans[-2][1]:
        return False
    return [trees[0][:-1], *trees[1:]] == actual


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    args = cli.parse_args()
    archive = args.compiler
    check_pin(archive, COMPILER_SHA)
    cases = list(examples())
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    accepted = rejected = overlaps = failures = 0
    for c, ref in zip(cases, run_compiler(archive, oracle, cases), strict=True):
        try:
            tree = TypeScriptPipeline(c["name"]).parse(c["source"])
        except SourceSyntaxError as exc:
            code = 1109 if "TS1109" in str(exc) else 1005 if "TS1005" in str(exc) else None
            if ref.get("invalid") and 0 <= exc.offset <= len(c["source"]) and (
                    code is None or any(d[:2] == [code, exc.offset] for d in ref["diagnostics"])):
                rejected += 1
                continue
            actual = str(exc)
        else:
            actual = project_trees(tree, "heritage source")
            if actual and actual == ref.get("trees"):
                accepted += 1
                continue
            if repeated_reference_statement(c, ref, actual):
                overlaps += 1
                continue
        print(c["name"], repr(c["source"]), actual, ref)
        failures += 1
    print(f"{accepted} matching heritage trees, {rejected} joint rejections, {overlaps} known overlapping reference statements, {failures} unexplained differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
