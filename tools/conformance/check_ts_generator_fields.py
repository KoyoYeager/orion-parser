"""Compare generator overload and definite class field trees with TypeScript 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler


def cases():
    for prefix in ("function* f", "declare function* f", "export default function*", "export default function* f",
                   "export async function* f", "export default async function*"):
        for params in ("()", "<T>(x:T)", "(...x:T[])", "(x:)"):
            for tail in (";", ": Iterator<T>;", ": R", ": R {yield x}"):
                yield prefix + params + tail, "generator signature"
    for prefix in ("*", "static *", "async *", "static async *"):
        for name in ("key", "#key", "[key]", '"constructor"', "key?"):
            for params in ("()", "<T>(x:T):T", "(x:)"):
                yield f"class C {{{prefix}{name}{params};}}", "generator signature"
    for key in ("x", "#x", "static x", "static [key]", '"constructor"'):
        for tail in ("!", "!:T", "! = 1 + 2", "!:T=make()", "\n!:T", "!?", "?!", "!(){}"):
            yield f"class C {{{key}{tail}}}", "definite field"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    inputs = [{"name": "case.ts", "source": source, "projection": label} for source, label in cases()]
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    matched = invalid = failures = 0
    for case, expected in zip(inputs, run_compiler(archive, oracle, inputs), strict=True):
        try:
            tree = TypeScriptPipeline(case["name"]).parse(case["source"])
        except ValueError as exc:
            if expected.get("invalid"):
                invalid += 1
                continue
            actual = str(exc)
        else:
            actual = project_trees(tree, case["projection"])
            if actual == expected.get("trees"):
                matched += 1
                continue
        failures += 1
        print(case["source"], "Orion", actual, "TypeScript", expected)
    print(f"{matched} matching cases, {invalid} jointly rejected inputs, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
