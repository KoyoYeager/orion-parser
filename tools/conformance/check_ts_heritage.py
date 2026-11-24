"""Compare class/interface heritage-clause boundaries and trees with TS 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, _STATEMENT_SHAPE, TypeScriptPipeline, check_pin, run_compiler


def cases():
    clauses = (
        "", "extends", "implements", "extends A", "implements A.B<T>", "extends A, B", "extends A,",
        "extends A implements B", "implements A extends B", "extends A extends B", "extends extends",
        "implements implements", "extends A implements B extends C", "extends A, B implements C, D,",
        "extends {}", "extends {}, A", "extends {x:1}", "extends implements.X", "extends implements, B",
        "extends f<T>()", "extends foo?.bar", "extends A<>", "extends string<>", "extends (#p)",
        "extends #p", "extends A, #p()", "implements A.<T>", "extends A,,B", "extends A+B",
    )
    for owner in ("class C", "class", "interface I", "const C = class"):
        for clause in clauses:
            yield {"source": f"{owner} {clause} {{}}", "name": "heritage.ts", "projection": "heritage"}

    for owner in ("class implements", "const C=class implements", "export default class", "interface implements"):
        for clause in ("", "I", "extends A", "implements B", "extends A<T>, B", "extends factory<T>(v)"):
            yield {"source": f"{owner} {clause} {{}}", "name": "heritage.ts", "projection": "heritage"}

    for owner in ("namespace A", "module A", "declare namespace A", "export namespace A"):
        for suffix in ("", ".B", ".default.C", ".#p", "."):
            yield {"source": f"{owner}{suffix} {{enum E {{A=1, B=A+2,}}}}", "name": "module.ts",
                   "projection": "namespace and enum"}
    for prefix, end in [("", ""), ("async function f(){", "}"), ("function* f(){", "}")]:
        for member in ("A=await", "B=yield", "A=await value", "B=yield value", "[key()]=f(1), next,",
                       '"k"=0, #private=2', "name=1; next", "name="):
            yield {"source": prefix + "enum E{" + member + "}" + end, "name": "enum.ts", "projection": "namespace and enum"}
    for source in ['module "pkg";', 'declare module "pkg" {export const v:T}', 'global\n{}', 'enum\nE {}',
                   'namespace A;', 'namespace "str"{}', 'module A..B{}']:
        yield {"source": source, "name": "module.ts", "projection": "namespace and enum"}


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
            actual = project_trees(root, case["projection"])
            if actual == ref.get("trees"):
                matched += 1
                continue
        print(case["source"], "Orion", actual, "TypeScript", ref)
        failures += 1
    print(f"{matched} matching heritage/namespace/enum cases, {rejected} jointly rejected inputs, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
