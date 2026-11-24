"""Compare presence, owner, length and trailing comma of generic lists against TS 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, _STATEMENT_SHAPE, TypeScriptPipeline, check_pin, run_compiler


def cases():
    forms = [
        "class C@ {}", "interface I@ {}", "type A@ = T", "function f@() {}", "class C { m@(): T; }",
        "type F = @() => T", "const f = @() => x", "const f = async @() => x",
        "type A = Box@", "type A = ns.Box.@", "type A = typeof ns.Box@", 'type A = import("m").Box@',
        "interface I extends Box@ {}", "class C extends Box@ {}", "class C implements string@ {}",
        "const x = fn@", "fn@()", "new C@()", "f?.@()", "tag@`x`", 'import@("m")',
    ]
    for suffix in ("ts", "tsx", "mts", "cts", "d.ts", "d.mts", "d.cts"):
        patterns = forms + (["const x = <C@ a={} />", "const x = <C@></C>"] if suffix == "tsx" else [])
        for form in patterns:
            for args in ("", "<>", "<T>", "<T,>", "<,>"):
                yield {"name": "list." + suffix, "source": form.replace("@", args), "projection": "type list"}

    for prefix in ("", "private readonly ", "in out in ", "public ", "const ", "static\n"):
        for bound in ("", " extends U", " extends -1", " extends -x", " extends +v", " extends ++v",
                      " extends ((~v))", " extends /re/.test(s)", " extends super.x", " extends #x",
                      " extends class {}", " extends void x", " extends U + V"):
            for default in ("", " = R"):
                source = f"type A<{prefix}T{bound}{default}> = T;"
                yield {"name": "bounds.ts", "source": source, "projection": "alias"}
    for outer in ("async function f()", "function* f()"):
        for bound in ("await", "yield", "await x", "yield x", "(await)", "(yield)", "(await x)", "(yield x)"):
            source = f"{outer} {{ type A<T extends {bound}> = T }}"
            yield {"name": "bounds.ts", "source": source, "projection": "alias"}

    for parameter in ("this", "this:C", "v:T,this:C", "this:C,...v:T[]", "...this:C", "private this:C",
                      "@d this:C", "public readonly this:C", "@d public this:C", "this?:C", "this:C=v"):
        for source, label in [
            ("type Fn=(" + parameter + ")=>T;", "alias"),
            ("(function(" + parameter + "):T{return value;});", "target expression"),
            ("({m(" + parameter + "):T{return value;}});", "target expression"),
        ]:
            yield {"name": "receivers.ts", "source": source, "projection": label}

    for name in ("key", "readonly", "out", "this", "true", "typeof", "import", "new", "class", "default", "in", "#this", '"k"'):
        for prefix in ("", "..."):
            for optional in ("", "?"):
                source = f"type Tuple=[{prefix}{name}{optional}: Value];"
                yield {"name": "tuple.ts", "source": source, "projection": "alias"}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    inputs = list(cases())
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    matched = invalid = failures = 0
    for case, ref in zip(inputs, run_compiler(archive, oracle, inputs), strict=True):
        try:
            root = TypeScriptPipeline(case["name"]).parse(case["source"])
        except ValueError as exc:
            if ref.get("invalid"):
                invalid += 1
                continue
            actual = str(exc)
        else:
            actual = project_trees(root, case["projection"])
            if actual == ref.get("trees"):
                matched += 1
                continue
        print(case["name"], case["source"], "Orion", actual, "TypeScript", ref)
        failures += 1
    print(f"{matched} matching generic-list and parameter cases, {invalid} jointly rejected inputs, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
