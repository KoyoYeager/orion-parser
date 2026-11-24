"""Compare JSDoc-style type precedence, tuple boundaries and signatures against TS 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, _STATEMENT_SHAPE, TypeScriptPipeline, check_pin, run_compiler


def cases():
    types = [
        "*", "?", "!T", "T!", "?T", "T?", "T? extends U ? A : B", "??T", "!!T",
        "!T[]", "(!T)[]", "?T[]", "(?T)[]", "Box<this is X>", "asserts a is T", "asserts this\nis X", "a is T", "!T[K]", "?T[K]", "A | ?B | C", "?A & B",
        "A? | B", "?T extends U ? A : B", "A extends B ? ?C : !D", "A extends ?B ? C : D",
        "Array<?>", "Array<??>", "Array<*>", "Array<?T>", "Array<T?>",
        "{a: ?}", "{a?: T}", "[T?]", "[T | U?]", "[...T?]", "[?T]", "[name?: T]",
        "[name: T?]", "[...name?: ...T]", "[A extends B ? C : D]", "[?]",
        "function", "function()", "function(this:T, ?, ...X=): Y", "function(new: T, *): T",
        "function(number, string): ?R | X", "function(T is U): R", "function(??T)", "function(T=,)", "function(*=)", "function(* =)", "function(this:*=)",
        "function(module:path/to.name#field, *)", "function(module.path, T)", "function(module:path )", "function(module:path , T)",
        "function(module , T)", "function(module:pkg/sub#name, T=)", "function(this: *=, ...?T): T?",
        "(function():T)[]", "function(function(A):B):C", "function(x:T):R", "function(new X):R",
        "T extends U ? function() : V", "number?[]", "T!\n[]", "T\n!", "?;",
    ]
    for term in ("T?", "?T", "!T", "T!", "function(A):B", "this is A", "asserts x is A"):
        types.extend(form.replace("@", term) for form in (
            "(@)[]", "Array<@>", "A | @", "@ | A", "A & @", "@ extends A ? X : Y",
            "C extends U ? @ : V", "[@]", "[...@]", "[name: @]",
        ))
    for name in ("types.ts", "types.tsx"):
        for t in types:
            yield {"name": name, "source": "type Result = " + t + ";", "projection": "alias"}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    inputs = list(cases())
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    matched = rejected = failures = 0
    for case, ref in zip(inputs, run_compiler(archive, oracle, inputs), strict=True):
        try:
            root = TypeScriptPipeline(case["name"]).parse(case["source"])
        except ValueError as exc:
            if ref.get("invalid"):
                rejected += 1
                continue
            actual = str(exc)
        else:
            actual = project_trees(root, "alias")
            if actual == ref.get("trees"):
                matched += 1
                continue
        print(case["source"], "Orion", actual, "TypeScript", ref)
        failures += 1
    print(f"{matched} matching type trees, {rejected} jointly rejected cases, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
