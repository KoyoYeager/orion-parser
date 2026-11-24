"""Compare contextual import names and their AST bindings with the pinned TS compiler."""
import argparse
from pathlib import Path
import tempfile

from check_ts_alias_shapes import project_trees
from check_ts_options import _ORACLE as OPTIONS_ORACLE
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler


def cases():
    names = ("X", "await", "yield", "eval", "arguments", "let", "static", "public", "private",
             "protected", "interface", "package", "implements", "type", "from", "as", "default",
             "class", "enum", "null", "if", '"quoted"')
    clauses = ("{}", "* as {}", "{{ {} }}", "{{ x as {} }}", "{{ {} as x }}",
               "type {{ {} }}", "{{ type {} }}", "{{ type {} as x }}")
    for suffix in ("ts", "tsx", "mts", "cts", "d.ts", "d.mts", "d.cts"):
        for name in names:
            for clause in clauses:
                source = f'import {clause.format(name)} from "m";'
                yield {"source": source, "name": f"imports.{suffix}", "projection": "module bindings"}
        for head in ("defer foo", "defer from", "defer {x as y}", r"d\u0065fer * as d",
                     "defer defaultName, {type T}", "defer, {x}", "defer", r"t\u0079pe {X}",
                     "{type as as}", "{type as as x}", "{type as as as}", "{type as as as x}"):
            yield {"name": f"phases.{suffix}", "source": f'export import {head} from "pkg";',
                   "projection": "module bindings"}
        for source in ('import true, next;', 'import new C();', 'import function(){};', 'import typeof value;',
                       'import this.key;', 'import class{};', 'import 42;', 'import [item];', 'import (42);',
                       'import defer (factory());', 'import defer [a,b];', 'import defer /rx/;', 'import defer 42;',
                       'import defer true with {type: "json"};', 'import defer `m`;', 'import defer {};',
                       'import defer d;', 'import defer () => 3;', 'import "side" with {"mode": setting};'):
            yield {"name": f"source.{suffix}", "source": source, "projection": "module bindings"}
        for expression in ('"pkg"', "x", "resolve(x)", "a,b", '("p")+suffix', '"p"+suffix'):
            for template in ["import A = require(%s);", "export * from %s;", "import {x} from %s;"]:
                yield {"name": f"sources.{suffix}", "source": template % expression, "projection": "module bindings"}


def check_source_diagnostics(archive):
    examples = [
        ("import true, next;", [(1141, 7)]),
        ("import defer (factory());", [(1141, 13)]),
        ("import defer 42;", [(1141, 13)]),
        ('import defer true with {type:"json"};', [(1141, 13)]),
        ('import "pkg";', []),
        ('import defer d from "pkg";', [(18058, 7)]),
        ('import defer {a} from "pkg";', [(18059, 7)]),
    ]
    with tempfile.TemporaryDirectory() as directory:
        cases = []
        for i, (source, _) in enumerate(examples):
            path = Path(directory) / f"case{i}.ts"
            path.write_text(source, encoding="utf-8")
            cases.append({"name": str(path), "options": {"module": "esnext"}, "codes": [1141, 18058, 18059]})
        rows = run_compiler(archive, OPTIONS_ORACLE, cases)
    failures = 0
    for (source, expected), row in zip(examples, rows, strict=True):
        if row["parse"] or list(map(tuple, row["located"])) != expected:
            failures += 1
            print(source, row, expected)
    print(f"{len(rows)} reference checker cases, {failures} differences")
    return failures


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    inputs = list(cases())
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    accepted = rejected = failures = 0
    for case, ref in zip(inputs, run_compiler(archive, oracle, inputs), strict=True):
        try:
            tree = TypeScriptPipeline(case["name"]).parse(case["source"])
        except ValueError as exc:
            if ref.get("invalid"):
                rejected += 1
                continue
            detail = str(exc)
        else:
            actual = project_trees(tree, "module bindings")
            if actual == ref.get("trees"):
                accepted += 1
                continue
            detail = actual
        print(case["name"], case["source"], "Orion", detail, "TypeScript", ref)
        failures += 1
    print(f"{accepted} matching import trees, {rejected} jointly rejected inputs, {failures} differences")
    return int(bool(failures + check_source_diagnostics(archive)))


if __name__ == "__main__":
    raise SystemExit(main())
