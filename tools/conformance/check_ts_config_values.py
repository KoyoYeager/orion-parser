"""Compare project-file values and syntax acceptance with TypeScript 5.9.3."""
import argparse
import itertools
import json
import tempfile
from pathlib import Path

from check_typescript import COMPILER_SHA, check_pin, run_compiler
from orionparser.languages.typescript.config import parse_config
from orionparser.languages.typescript.options import SyntaxOptions
from orionparser.languages.typescript.version_range import matches_compiler_version


def examples():
    for gap in ("", " ", "\t", "\v", "\f", "\r\n", "\u0085", "\u00a0", "\u1680", "\u200b",
                "\u2028", "\u2029", "\u202f", "\u3000", "\ufeff", "/*𐐀*/", "//x\u2028", "//x\u2029"):
        yield gap + "{" + gap + '"compilerOptions"' + gap + ":" + gap + '{"target":"es5",},}'
        yield '{"value":["//", "/*ok*/", ' + gap + "true," + gap + "]}"
        yield '{"value":"a' + gap + 'b"}'
    for value in ('"escaped\\\"quote"', r'"\x41"', r'"\u{10400}"', r'"\0"', r'"\01"', r'"\8"', r'"\xZ"',
                  "'single'", "0xff", "-0o11", "1_2.3e+2", ".5", "1.", "1n", "NaN", "Infinity", "01",
                  "true", "null", "[]", "[,]", "[1,,2]", '{"nested":1,}', "/*unterminated"):
        yield '{"value":' + value + "}"
    yield from ("", "/*comment only*/", "#!project\n{}", "[]", "null", "{}{}", "{};", "{x:1}", '{"a":1,"a":2}')


def check_version_conditions(archive):
    versions = ("4", "5", "6", "5.8", "5.9", "5.10", "5.9.2", "5.9.3", "5.9.4", "5.9.3-rc.1",
                "5.9.3+dist", "X", "*", "5.x", "5.9.*", "x.2.1", "0.1", "0.0.1", "05", "v5", "")
    cases = [op + v for op, v in itertools.product(("", "=", "<", ">", "<=", ">=", "^", "~"), versions)]
    cases.extend(left + op + right for left, op, right in itertools.product(
        versions, (" - ", " || ", " "), versions))
    cases.extend(("5 || || 6", "5||", "||", "5\u00856", "\ufeff5.9.3", "^ 5", ">5.8\u2028<6"))
    oracle = """
    const ts = require(process.argv[1]);
    const ranges = JSON.parse(require("fs").readFileSync(0, "utf8"));
    process.stdout.write(JSON.stringify(ranges.map(r => ts.VersionRange.tryParse(r)?.test(ts.version) ?? false)));
    """
    failures = 0
    for spec, expected in zip(cases, run_compiler(archive, oracle, cases), strict=True):
        if matches_compiler_version(spec) != expected:
            print("version range mismatch", repr(spec), expected)
            failures += 1
    print(f"{len(cases)} version range comparisons, {failures} differences")
    return failures


def check_projects(archive):
    projects = [({"extends": "./base"}, True), ({"extends": "./base", "compilerOptions": None}, True),
                ({"extends": "./base", "compilerOptions": [1]}, True),
                ({"extends": "./base", "compilerOptions": {"target": None, "alwaysStrict": None, "strict": True}}, True),
                ({"extends": ["./base", "./override.json"]}, True),
                ({"extends": ".\\sub\\parent"}, True), ({"extends": "./sub"}, False),
                ({"extends": ""}, False), ({"extends": [None]}, False)]
    exports = {".": {"import": "./legacy.json", "require": "./mapped/base.json"},
               "./strict": "./mapped/base.json", "./*": "./mapped/*.json",
               "./m*.config": "./mapped/*.json", "./blocked": None,
               "./choice": ["./missing.json", "./mapped/base.json"],
               "./node": {"node": "./mapped/base.json", "default": "./legacy.json"},
               "./types": {"types": "./mapped/base.json"}, "./noext": "./mapped/base"}
    for name, valid in [("", True), ("/strict", True), ("/base", True), ("/mbase.config", True),
                        ("/blocked", False), ("/private", False), ("/choice", True),
                        ("/node", True), ("/types", True), ("/noext", False)]:
        projects.append(({"extends": "@scope/pkg" + name}, valid))
    for index, spec in enumerate(("", "*", "x", "5", "5.9.x", "5.8", "5.9.3", "5.9.4",
                                  "5.9.3-beta", "5.9.3+build", ">=5.9.3", ">5.9", "<6", "<=5",
                                  "^5.8", "^6", "^0.9", "~5.8", "~5.9.2", "5.8 - 5.9",
                                  "5.9.4 - 6", ">=5.9 <6", "5.8 || 5.9", "v5", "bad || 5.9",
                                  "> 5", "05.9", "<*", ">x", "5.x.3")):
        key = f"version{index}"
        exports["./" + key] = {"types@" + spec: "./mapped/base.json", "default": "./legacy.json"}
        projects.append(({"extends": "@scope/pkg/" + key}, True))
    self_exports = {".": "./override.json", "./strict": "./sub/parent.json"}
    self_cases = [
        ("@scope/pkg", self_exports, None, True),
        ("@scope/pkg/strict", self_exports, None, True),
        ("@scope/pkg/base", self_exports, None, True),
        ("@scope/pkg/missing", self_exports, None, False),
        ("@scope/pkg/strict", self_exports, {"name": "inner"}, True),
        ("@scope/pkg/strict", self_exports, "{invalid", True),
        ("@scope/pkg/strict", self_exports, '["inner"]', True),
        ("@scope/pkg", None, None, True),
        ("local", "./override.json", None, True),
        ("local/strict", {"./*": "./sub/*.json"}, None, False),
        ("local/parent", {"./*": "./sub/*.json"}, None, True),
    ]
    imports = {"#base": "./override.json", "#conditional": {"import": "./base.json", "node": "./override.json"},
               "#parent/*": "./sub/*.json", "#dep": "@scope/pkg/strict", "#chain": "#dep",
               "#plain": "plain", "#plain-file": "plain/config.json", "#file": "./base",
               "#dir/": "./sub/", "#dir/*": "./mapped/*.json", "#null": None, "#/bad": "./base.json", "#": "./base.json"}
    for alias, valid in [("#base", True), ("#conditional", True), ("#parent/parent", True), ("#dep", True),
                         ("#chain", True), ("#dir/parent.json", False), ("#plain", False), ("#plain-file", True), ("#file", False),
                         ("#null", False), ("#/bad", False), ("#", False), ("#unknown", False)]:
        self_cases.append((alias, None, None, valid))
    first_self = len(projects)
    projects.extend(({"extends": name}, valid) for name, _, _, valid in self_cases)
    version_projects = [
        ("base", {">=5.9": {"*": ["mapped/*"]}}, {}, True),
        ("base", {">=6": {"*": ["legacy.json"]}, "*": {"base": ["mapped/base.json"]}}, {}, True),
        ("base", {"*": {"*": ["legacy.json"]}, ">=5": {"*": ["mapped/base"]}}, {}, True),
        ("base", {"*": {"*": ["legacy.json"]}, "5": {"base": ["mapped/base"]}}, {}, True),
        ("base", {"*": {"base": ["mapped/base.js"]}}, {}, True),
        ("base", {"*": {"base": ["mapped/base.d.ts"]}}, {}, True),
        ("base", {"*": {"base": ["mapped/alias.ts"]}}, {}, True),
        ("alias.ts", {"*": {"*": ["mapped/*"]}}, {}, False),
        ("base", {"*": {"base": ["mapped/dir"]}}, {}, True),
        ("base", {"*": {"base": ["mapped/unknown"]}}, {}, False),
        ("", {}, {"tsconfig": "mapped/dir"}, True),
        ("nested", {"*": {"nested": ["legacy.json"]}}, {}, True),
        ("", {"*": {"mapped/dir": ["missing", "legacy.json"]}}, {"tsconfig": "mapped/dir"}, True),
        ("base", {"*": {"*": ["legacy.json"], "ba*": ["mapped/ba*"]}}, {}, True),
        ("base", {"*": {"*": ["legacy.json"], "base": ["missing", "mapped/base"]}}, {}, True),
        ("legacy", {"*": {"legacy": ["missing"]}}, {}, False),
        ("legacy", {"*": {"absent": ["missing"]}}, {}, True),
        ("", {"*": {"tsconfig": ["mapped/base"]}}, {}, True),
        ("", {"*": {"legacy.json": ["mapped/base"]}}, {"tsconfig": "./legacy.json"}, True),
        ("", {"*": {"legacy.json": ["missing"]}}, {"tsconfig": "./legacy.json"}, False),
        ("base", {"*": {"base": ["mapped/base"]}}, {"exports": {"./base": "./legacy.json"}}, True),
    ]
    first_version = len(projects)
    projects.extend(({"extends": "@scope/pkg" + ("/" + name if name else "")}, valid)
                    for name, _, _, valid in version_projects)
    oracle = """
    const ts = require(process.argv[1]);
    const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
    process.stdout.write(JSON.stringify(cases.map(file => {
        const result = ts.getParsedCommandLineOfConfigFile(file, {}, {...ts.sys, onUnRecoverableConfigFileDiagnostic() {}});
        if (!result || result.errors.length) return null;
        return [ts.ScriptTarget[ts.getEmitScriptTarget(result.options)].toLowerCase(), ts.getStrictOptionValue(result.options, "alwaysStrict")];
    })));
    """
    with tempfile.TemporaryDirectory() as temp:
        paths = []
        for index, (project, _) in enumerate(projects):
            directory = Path(temp) / str(index)
            (directory / "sub").mkdir(parents=True)
            (directory / "base.json").write_text('{// base target\u2028"compilerOptions":{"target":"es2015","alwaysStrict":false}}')
            (directory / "override.json").write_text('{"compilerOptions":{"target":"es2017","alwaysStrict":true}}')
            (directory / "sub/parent.json").write_text('{"compilerOptions":{"target":"es2018"}}')
            (directory / "sub/tsconfig.json").write_text('{"compilerOptions":{"target":"es2022"}}')
            package = directory / "node_modules/@scope/pkg"
            (package / "mapped").mkdir(parents=True)
            (package / "package.json").write_text(json.dumps({"exports": exports, "tsconfig": "legacy.json"}))
            (package / "mapped/base.json").write_text('{"compilerOptions":{"target":"es2015"}}')
            (package / "legacy.json").write_text('{"compilerOptions":{"target":"es5"}}')
            for name in ("private", "blocked"):
                (package / (name + ".json")).write_text("{}")
            if index >= first_version:
                (package / "mapped/dir").mkdir()
                (package / "mapped/dir/tsconfig.json").write_text('{"compilerOptions":{"target":"es2022"}}')
                (package / "nested").mkdir()
                (package / "nested/package.json").write_text('{"tsconfig":"../mapped/base.json"}')
                (package / "mapped/alias.ts").write_text('{"compilerOptions":{"target":"es2018"}}')
                _, versions, fields, _ = version_projects[index - first_version]
                (package / "package.json").write_text(json.dumps({"typesVersions": versions, **fields}))
            elif index >= first_self:
                name, mapping, inner, _ = self_cases[index - first_self]
                manifest = {"name": "@scope/pkg" if name.startswith("@") else "local"}
                if name.startswith("#"):
                    manifest["imports"] = imports
                    plain = directory / "node_modules/plain"
                    plain.mkdir()
                    (plain / "package.json").write_text('{"tsconfig":"config.json"}')
                    (plain / "config.json").write_text('{"compilerOptions":{"target":"es2019"}}')
                if mapping is not None:
                    manifest["exports"] = mapping
                (directory / "package.json").write_text("// local package scope\n" + json.dumps(manifest))
                directory = directory / "project"
                directory.mkdir()
                if inner is not None:
                    (directory / "package.json").write_text(inner if isinstance(inner, str) else json.dumps(inner))
            path = directory / "tsconfig.json"
            path.write_text(json.dumps({**project, "files": ["x.ts"]}))
            paths.append(str(path))
        failures = 0
        for (project, valid), path, ref in zip(projects, paths, run_compiler(archive, oracle, paths), strict=True):
            try:
                options = SyntaxOptions.from_project(path)
                actual = [options.target, options.always_strict]
            except ValueError:
                actual = None
            if actual != ref or (actual is not None) != valid:
                print(project, actual, ref)
                failures += 1
    print(f"{len(paths)} project-resolution comparisons, {failures} differences")
    return failures


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases = list(examples())
    oracle = """
    const ts = require(process.argv[1]);
    const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
    process.stdout.write(JSON.stringify(cases.map(text => {
        const parsed = ts.parseConfigFileTextToJson("tsconfig.json", text);
        return parsed.error ? {error: parsed.error.code} : {config: parsed.config};
    })));
    """
    accepted = rejected = failures = 0
    for source, ref in zip(cases, run_compiler(archive, oracle, cases), strict=True):
        try:
            actual = parse_config(source)
        except ValueError as error:
            if "error" in ref:
                rejected += 1
                continue
            actual = str(error)
        else:
            if actual == ref.get("config"):
                accepted += 1
                continue
        print(repr(source), actual, ref)
        failures += 1
    print(f"{accepted} matching project values, {rejected} joint syntax rejections, {failures} differences")
    return int(bool(check_projects(archive) + check_version_conditions(archive) + failures))


if __name__ == "__main__":
    raise SystemExit(main())
