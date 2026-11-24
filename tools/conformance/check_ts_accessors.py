"""Compare accessor syntax and signature trees in four TS member contexts."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, _STATEMENT_SHAPE, TypeScriptPipeline, check_pin, run_compiler


def cases():
    for container in ("class C { %s }", "interface I { %s }", "type A = { %s }", "const o = { %s }"):
        body = " {}" if container.startswith(("class", "const")) else ";"
        for kind in ("get", "set"):
            for name in ("member", "[key]", '"literal"'):
                for types in ("", "<T>"):
                    for args in ("", "this: C", "value?: T", "a:T, b:U", "...r:T[]", "this:C, v:T=initial"):
                        member = f"{kind} {name}{types}({args}): Result" + body
                        yield {"name": "accessors.ts", "source": container % member, "projection": "accessor"}
            if container.startswith(("interface", "type")):
                for head in ("x()", "[key]<T>(v:T)", "x():{n:T}", 'x()\n'):
                    for tail in ("", " next:T", " get next(){}", ";", ", next:T"):
                        for prefix in (kind + " ", "readonly " + kind + " ", "readonly " + kind + "\n"):
                            member = f"{prefix}{head} {{ return value; }}" + tail
                            yield {"name": "body.ts", "source": container % member, "projection": "accessor"}
            for invalid in ("item?()", "item!(x)", "item(x:)", "item<T(x)"):
                yield {"name": "invalid.ts", "source": container % (kind + " " + invalid + body), "projection": "accessor"}

    for head in ("method()", "method?<T>(x:T):T", "*f(v)", "async f()", "async *f<T>(x:T)",
                 "get foo():T", "set [key](v:T)", "get foo<T>()", "async get foo()"):
        for tail in ("", ";", ";, next:1", "\n, next:1", ", next:1", "; next:1", " next:1", " {}"):
            yield {"name": "object.ts", "source": "const o={" + head + tail + "}", "projection": "bodyless object member"}


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
            actual = str(exc)
        else:
            actual = project_trees(tree, case["projection"])
            if actual == ref.get("trees"):
                accepted += 1
                continue
        print(case["source"], "Orion", actual, "TypeScript", ref)
        failures += 1
    print(f"{accepted} matching accessor/object-member cases, {rejected} jointly rejected inputs, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
