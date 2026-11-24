"""Check TS regex token boundaries, scoped flags, and inner diagnostics against TS 5.9.3."""
import argparse
from itertools import permutations
from pathlib import Path

from orionparser.languages.typescript.options import SyntaxOptions

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler


def cases():
    flag_sets = [""] + ["".join(p) for n in range(1, 4) for p in permutations("ims", n)]
    for enabled in flag_sets:
        for disabled in flag_sets:
            modifiers = enabled + "-" + disabled
            yield f"/(?{modifiers}:(x|y)+)/u", (enabled, disabled)
        if enabled:
            yield f"/(?{enabled}:(x|y)+)/", (enabled, "")
    for literal in (
        "/(?:x)/", "/(?ii:x)/", "/(?g:a)/", "/(?i-i:a)/", "/(?foo)/", "/[^/]+/g",
        r"/\u{110000}/u", r"/\u{10_ffff}/u", r"/\x_F/u", r"/\xzz/", r"/\8/",
        r"/(?<n>x)|(?<n>y)\k<n>/u", r"/(?<n>x)(?<n>y)/u", r"/(?:(?<n>x))(?<n>y)/u",
        "/x/gig", "/x/uv", "/x/vu", "/x/𝒈", "/𝒙/𝒈g𝒎g", "/(?𝒊:x)/", "/x/visualstudiocode", "/[/]/v",
        r"/[^\p{Emoji}\p{RGI_Emoji}]/v", r"/[^\p{RGI_Emoji}]/v", r"/[^\q{ab}]/v",
        "/[abc/", "/missing", "/a\nb/", "/abc\\", "/*missing/",
    ):
        yield literal, None


def check_targets(archive):
    targets = ("ES5", "ES2015", "ES2017", "ES2018", "ES2021", "ES2022", "ES2023", "ES2024", "ESNext")
    literals = ("/a/gim", "/a/uy", "/a/dsu", "/a/v", "/a/vu", "/a/dd", "/a/yv",
                "/(?s:x)/", "/(?i-s:x)/", "/(?<name>x)/", "/(?<n>a)|(?<n>b)/", "/(?<=a)b/s")
    inputs = [{"literal": literal, "target": target} for target in targets for literal in literals]
    oracle = """
    const ts = require(process.argv[1]);
    const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
    process.stdout.write(JSON.stringify(cases.map(({literal, target}) => {
        const spans = [];
        const scanner = ts.createScanner(ts.ScriptTarget[target], true, ts.LanguageVariant.Standard, literal, (d, len) => {
            if (d.code === 1501 || d.code === 1503) {
                const start = scanner.getTextPos();
                spans.push([d.code, Array.from(literal.slice(0, start)).length, Array.from(literal.slice(start, start + len)).length]);
            }
        });
        scanner.scan();
        scanner.reScanSlashToken(true);
        return spans;
    })));
    """
    prefix = "/*𐐀*/ "
    failures = 0
    for case, expected in zip(inputs, run_compiler(archive, oracle, inputs), strict=True):
        pipeline = TypeScriptPipeline("targets.ts")
        pipeline.syntax_options = SyntaxOptions(target=case["target"].lower())
        node = pipeline.parse(prefix + case["literal"])["body"][0]["expression"]
        actual = [[d["code"], d["offset"] - len(prefix), d["length"]] for d in node.get("diagnostics", [])
                  if d.get("code") in (1501, 1503)]
        if actual != expected or node["alternatives"] is None:
            print(case, "Orion", actual, "TypeScript", expected)
            failures += 1
    print(f"{len(inputs)} target/literal comparisons, {failures} differences")
    return failures


def check_quantifiers(archive):
    spellings = ("{0}", "{2,}", "{3,1}", "{0003,02}", "{,2}", "{,}", "{2", "{,2", "{4,1x", "{word}",
                 "{,z}", "{9007199254740993,9007199254740992}", "{9007199254740994,9007199254740992}")
    cases = [f"/a{quantifier}{lazy}/{flag}" for quantifier in spellings for lazy in ("", "?") for flag in ("", "u", "v")]
    oracle = """
    const ts = require(process.argv[1]);
    const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
    process.stdout.write(JSON.stringify(cases.map(literal => {
        const issues = [];
        const scanner = ts.createScanner(ts.ScriptTarget.ESNext, true, ts.LanguageVariant.Standard, literal,
            (error, length) => issues.push([error.code, scanner.getTextPos(), length]));
        scanner.scan();
        scanner.reScanSlashToken(true);
        return issues;
    })));
    """
    failed = 0
    pipeline = TypeScriptPipeline("quantifier.ts")
    cases.extend(f"/{spelling}/{flag}" for flag in ("", "u", "v")
                 for spelling in ("a**?", "a*??", "(?<=x)+", "(?=x)+", "^+?", r"\b{2}", "(?:+|x){2}", "{,2}", "{3,1}?"))
    cases.extend(("/(?foo)/", "/(?ss:x)/u", "/(?g:a)/v", "/(?i-i:x)/", "/(?-:x)/", "/(?ii-zz:x)/",
                  "/(?i x)/", "/(?i)/", "/(?g-g:x)/", "/(?-i:x)/", "/(?i--s:x)/", "/x/uv", "/x/quu"))
    for literal, ref in zip(cases, run_compiler(archive, oracle, cases), strict=True):
        node = pipeline.parse(literal)["body"][0]["expression"]
        actual = [[d.get("code"), d["offset"], d.get("length")] for d in node.get("diagnostics", [])]
        if actual != ref or node["alternatives"] is None:
            failed += 1
            print(literal, actual, ref)
    print(f"{len(cases)} quantifier and flag comparisons, {failed} differences")
    return failed


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    fixtures = list(cases())
    inputs = [{"name": "patterns.ts", "source": f"const value = {literal};", "projection": "regexp"}
              for literal, _ in fixtures]
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    valid = diagnosed = rejected = failed = 0
    for (literal, flags), case, ref in zip(fixtures, inputs, run_compiler(archive, oracle, inputs), strict=True):
        try:
            tree = TypeScriptPipeline(case["name"]).parse(case["source"])
        except ValueError as exc:
            if ref.get("invalid"):
                rejected += 1
                continue
            actual = str(exc)
        else:
            actual = project_trees(tree, "regexp")
            if actual == ref.get("trees") and len(actual) == 1:
                regex = tree["body"][0]["declarations"][0]["init"]
                if regex.get("diagnostics"):
                    diagnosed += 1
                    continue
                if flags is not None:
                    group, = regex["alternatives"][0]
                    quantified, = group["alternatives"][0]
                    capture = quantified["atom"]
                    if (group.get("modifiers") != {"enable": flags[0], "disable": flags[1]}
                            or quantified.get("quantifier") != "+" or capture.get("index") != 1
                            or [a[0]["value"] for a in capture["alternatives"]] != ["x", "y"]):
                        raise AssertionError((literal, regex))
                valid += 1
                continue
        failed += 1
        print(literal, "Orion", actual, "TypeScript", ref)
    print(f"{valid} valid literals, {diagnosed} literals with validation diagnostics, {rejected} source rejections, {failed} differences")
    return int(bool(check_targets(archive) + check_quantifiers(archive) + failed))


if __name__ == "__main__":
    raise SystemExit(main())
