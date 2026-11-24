"""Expand syntax-relevant TypeScript test directives against real virtual package boundaries."""
import argparse
import itertools
import json
from pathlib import Path
import posixpath
import re
import tempfile

from check_typescript import (COMPILER_SHA, SOURCE_SHA, _ORACLE, check_pin, fixture_sources,
                              run_compiler, statement_shape)
from orionparser.languages.typescript.options import SyntaxOptions
from orionparser.registry import get_pipeline

_KEYS = {key.lower(): key for key in ("target", "module", "moduleResolution", "moduleDetection", "jsx",
                                      "alwaysStrict", "strict", "isolatedModules", "verbatimModuleSyntax",
                                      "experimentalDecorators")}
_DIRECTIVE = re.compile(r"^//[ \t]*@(\w+)[ \t]*:[ \t]*([^\r\n]*)", re.M)


_DOMAINS = """
const ts = require(process.argv[1]);
const result = {};
for (const option of ts.optionDeclarations) {
    if (option.type instanceof Map) result[option.name] = Object.fromEntries(option.type);
    else if (option.type === 'boolean') result[option.name] = {true: 1, false: 0};
}
process.stdout.write(JSON.stringify(result));
"""


def options_for_fixture(text, domains):
    axes = {}
    for key, raw in _DIRECTIVE.findall(text):
        key = _KEYS.get(key.lower())
        if not key:
            continue
        # Match the pinned harness' splitVaryBySettingValue: explicit values
        # first, then '*' expansion, then exclusions; aliases share a value.
        domain = domains[key]
        parts = [v.strip().lower() for v in raw.split(",") if v.strip()]
        values = [v for v in parts if v != "*" and not v.startswith(("-", "!"))]
        if "*" in parts:
            values.extend(domain)
        excluded = {domain.get(v[1:], v[1:]) for v in parts if v.startswith(("-", "!"))}
        unique = {}
        for value in values:
            canonical = domain.get(value, value)
            if canonical not in excluded:
                unique.setdefault(canonical, {"true": True, "false": False}.get(value, value))
        if not unique:
            raise ValueError(f"No variants in @{key}: {raw}")
        axes[key] = list(unique.values())
    for combination in itertools.product(*axes.values()):
        yield dict(zip(axes, combination, strict=True))


def make_cases(archive, selection, root, domains):
    for index, (fixture, text, files) in enumerate(fixture_sources(archive, selection)):
        project = root / str(index)
        # Absolute and parent-relative virtual paths remain inside this fixture.
        paths = {}
        project.mkdir()
        for name, _ in files:
            virtual = re.sub(r"^[A-Za-z]:", "", name.replace("\\", "/"))
            path = project / posixpath.normpath("/" + virtual).lstrip("/")
            if not path.resolve().is_relative_to(project):
                raise ValueError(f"Invalid virtual file path: {name}")
            path.parent.mkdir(parents=True, exist_ok=True)
            paths[name] = path
        # Terminate package lookup inside the virtual project. The fixture's
        # real package.json, when present, replaces this empty package record.
        (project / "package.json").write_text("{}", encoding="utf-8")
        for name, source in files:
            path = paths[name]
            if path.name == "package.json":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")
        for options in options_for_fixture(text, domains):
            for name, source in files:
                if not name.lower().endswith((".ts", ".tsx", ".cts", ".mts")):
                    continue
                yield {"file": fixture, "name": name, "source": source, "options": options,
                       "matrixPath": str(paths[name])}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    cli.add_argument("source", type=Path)
    cli.add_argument("selection", nargs="?", default=".")
    cli.add_argument("--report", required=True, type=Path)
    args = cli.parse_args()
    check_pin(args.compiler, COMPILER_SHA)
    check_pin(args.source, SOURCE_SHA)
    counts = {"options": 0, "acceptance": 0, "internal": 0, "goal": 0, "structure": 0}
    accepted = jointly_rejected = 0
    with tempfile.TemporaryDirectory() as tmp, args.report.open("w", encoding="utf-8") as report:
        domains = run_compiler(args.compiler, _DOMAINS, [])
        cases = list(make_cases(args.source, args.selection, Path(tmp), domains))
        references = run_compiler(args.compiler, _ORACLE, cases)
        for case, reference in zip(cases, references, strict=True):
            row = {k: case[k] for k in ("file", "name", "options")}
            if reference.get("optionErrors"):
                row.update(category="options", codes=reference["optionErrors"])
            else:
                try:
                    config = SyntaxOptions.from_compiler_options(case["options"])
                    pipeline = get_pipeline(Path(case["matrixPath"]), typescript_options=config)
                    ast = pipeline.parse(case["source"])
                except ValueError as error:
                    ast = None
                    row["detail"] = str(error)
                except Exception as error:
                    ast = None
                    row.update(category="internal", detail=f"{type(error).__name__}: {error}")
                if "category" not in row:
                    if (ast is None) != bool(reference["diagnostics"]):
                        row.update(category="acceptance", referenceDiagnostics=reference["diagnostics"], orion=ast is not None)
                    elif ast is None:
                        jointly_rejected += 1
                        continue
                    elif ast["sourceType"] != reference["sourceType"]:
                        row.update(category="goal", reference=reference["sourceType"], orion=ast["sourceType"])
                    elif [statement_shape(n) for n in ast["body"]] != reference["statements"]:
                        row.update(category="structure")
                    else:
                        accepted += 1
                        continue
            counts[row["category"]] += 1
            report.write(json.dumps(row) + "\n")
    print(f"{len(cases)} configured cases: {accepted} jointly accepted with matching goal and top-level structure, "
          f"{jointly_rejected} jointly rejected; differences {counts}")
    return int(not cases or any(counts.values()))


if __name__ == "__main__":
    raise SystemExit(main())
