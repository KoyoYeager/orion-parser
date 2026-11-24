"""Compare rest binding recognition and structure with the TypeScript 5.9.3 parser."""
import argparse
from pathlib import Path
import tempfile

from check_ts_alias_shapes import project_trees
from check_ts_options import _ORACLE as OPTIONS_ORACLE
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler


def cases():
    for pattern in ["[...r]", "[...r=make(1)]", "[...r,]", "[,...r,,next]", "[...r,...s=2]",
                    "[...{x}, [a,...b],]", "{...r=make(1)}", "{...a, next, ...b,}",
                    "{...x:y}", "{...[key()]:[a,...b]=value}", "{...r:{x}}", "{...r:}", "{...42}",
                    "{...[x]}", "{...x.y}", "[...x: y]", "[...x += 1]", "{......x}"]:
        for form in ["let @=xs;", "try{}catch(@){}", "function f(@:T){}", "const f=(arg, @:T):R=>x;",
                     "async (@)=>x;", "const f=<T,>(@:T)=>x;", "type F=(@:T)=>R;"]:
            for filename in ("patterns.ts", "patterns.tsx"):
                yield {"name": filename, "source": form.replace("@", pattern), "projection": "rest binding"}


def check_reference_diagnostics(archive):
    examples = [
        ("let [...r=seed]=xs", [(1186, "=")]),
        ("let [...r,]=xs", [(1013, ",")]),
        ("let [...r, a]=xs", [(2462, "r")]),
        ("let {...p:q}=xs", [(2566, "q")]),
        ("let {...r=seed}=xs", [(1186, "=")]),
        ("let {...[key()]:r,}=xs", [(2566, "r"), (1013, ",")]),
        ("const f=({ ...r, x })=>x", [(2462, "r")]),
    ]
    with tempfile.TemporaryDirectory() as directory:
        programs = []
        for i, (source, _) in enumerate(examples):
            path = Path(directory) / f"binding{i}.ts"
            path.write_text(source, encoding="utf-8")
            programs.append({"name": str(path), "options": {}, "codes": [1013, 1186, 2462, 2566]})
        results = run_compiler(archive, OPTIONS_ORACLE, programs)
    differences = 0
    for (source, expected), result in zip(examples, results, strict=True):
        locations = sorted((code, source.index(text)) for code, text in expected)
        if result["parse"] or sorted(map(tuple, result["located"])) != locations:
            print(source, result, locations)
            differences += 1
    print(f"{len(examples)} reference checker cases, {differences} differences")
    return differences


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    inputs = list(cases())
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    matched = invalid = differences = 0
    for case, ref in zip(inputs, run_compiler(archive, oracle, inputs), strict=True):
        try:
            tree = TypeScriptPipeline(case["name"]).parse(case["source"])
        except ValueError as exc:
            if ref.get("invalid"):
                invalid += 1
                continue
            actual = str(exc)
        else:
            actual = project_trees(tree, case["projection"])
            if actual == ref.get("trees"):
                matched += 1
                continue
        print(case["source"], "Orion", actual, "TypeScript", ref)
        differences += 1
    print(f"{matched} matching binding cases, {invalid} jointly rejected inputs, {differences} differences")
    return int(bool(differences + check_reference_diagnostics(archive)))


if __name__ == "__main__":
    raise SystemExit(main())
