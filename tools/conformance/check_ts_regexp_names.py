"""Compare capture, backreference and Unicode property diagnostics against TypeScript 5.9.3."""
import argparse
from pathlib import Path

from check_typescript import COMPILER_SHA, TypeScriptPipeline, check_pin, run_compiler
from orionparser.languages.typescript.options import SyntaxOptions
from orionparser.languages.javascript.unicode_properties import BINARY, STRINGS, GENERAL_CATEGORY, SCRIPT


def examples():
    for flags in ("", "u", "v"):
        for pattern in (r"\k", r"\k<>", r"\k<none>", r"\k<before>(?<before>x)", r"(?<x>a)\k<x>",
                        r"(?<a>x)(?<a>y)", r"(?<a>x)|(?<a>y)", r"(?<a>x(?<a>y))", r"(?<a>x)\k<missing",
                        r"(?<>x)", r"(?<1>x)", r"(?<x.x)", r"(?<\u0061>x)", r"(?<a\u0062>x)\k<ab>",
                        r"(?<alpha>x)(?<alphi>y)\k<alph>", r"(?<Hello>x)\k<hello>\k<helo>",
                        r"(?<𐐀name>x)\k<𐐀nam>", r"(?<a\uD801\uDC00>x)", r"(?<a\u{10400}>x)\k<a𐐀>",
                        r"(?:(?<n>x))(?<n>y)", r"(?<n>x|(?<n>y))", r"(?<n>x)|(?<n>y)\k<n>",
                        r"(?<a>x)\k<A>", r"(?<x>x)\k<y>", r"(?<a\u{62}c\u{64}>x)\k<abcd>", r"(?<a\u{62}c\u{64}>x)\k<abd>",
                        r"(?<a\u0062c\u{64}>x)(?<abd>y)", r"(?<abd>.)\k<a\u{62}c\u{64}>", r"(?<a\u{62X>x)\k<abX>", r"(?<a\u{62>x)\k<a\u{62>",
                        r"(?<a\u{}>z)", r"(?<a\u{62_x}>z)", r"(?<a-b>x)", r"\k<foo.bad>", r"(?<name>x", r"(?<", r"(?<n>(a", r"(?<n>a))?", r"\k<x>(?<y>x",
                        r"\1", r"\2(a)", r"\2(a)(b)", r"(?<foo>a)\10", r"\9\k<missing>\3",
                        r"\01", r"\08", r"\09", r"\q", r"[\k]", r"(?<x>y)[\k]"):
            for target in ("ES5", "ES2018", "ESNext"):
                yield {"literal": f"/{pattern}/{flags}", "target": target}
    for names in (("alpha", "apple", "apply"), ("colour", "color"), ("foo", "fob"), ("foo", "Foo"),
                  ("x", "X"), ("𐐀", "𐐀name"), ("Éclair", "eclair")):
        groups = "".join(f"(?<{name}>.)" for name in names)
        for reference in ("alph", "APlY", "colr", "coloUr", "fop", "fO", "x", "𐐀nam", "Éclai", "faraway"):
            yield {"literal": "/" + groups + "\\k<" + reference + ">/u", "target": "ESNext"}


def property_examples():
    for name in (*BINARY, *GENERAL_CATEGORY, *STRINGS):
        yield {"literal": "/\\p{" + name + "}/v", "target": "ESNext"}
    for name in SCRIPT:
        yield {"literal": "/\\p{sc=" + name + "}/u", "target": "ESNext"}
    for flag in ("", "u", "v"):
        for prefix in ("p", "P"):
            for body in ("", "{}", "{=Ll}", "{gc=}", "{GC=Ll}", "{script=latin}", "{Script=Lati}",
                         "{Script_Extension=Latn}", "{WhiteSpace}", "{RGI_Emoji}", "{RGI_Emoj}", "{L!",
                         "{sc=Latin", "{ASCII}", "{123}", "{Binary=Yes}", "{ Lower}", "{Ascii}"):
                yield {"literal": "/" + chr(92) + prefix + body + "/" + flag, "target": "ESNext"}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    captures = list(examples())
    properties = list(property_examples())
    cases = captures + properties
    oracle = """
    const ts = require(process.argv[1]);
    const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
    process.stdout.write(JSON.stringify(cases.map(({literal, target}) => {
        const issues = [];
        const scanner = ts.createScanner(ts.ScriptTarget[target], true, ts.LanguageVariant.Standard, literal, (d, length, arg) => {
            const pos = scanner.getTextPos();
            issues.push([d.code, Array.from(literal.slice(0, pos)).length, Array.from(literal.slice(pos, pos+length)).length,
                         d.code === 1369 ? arg : null]);
        });
        scanner.scan();
        scanner.reScanSlashToken(true);
        return issues;
    })));
    """
    pipeline = TypeScriptPipeline("names.ts")
    prefix = "/*𐐀*/ "
    failures = 0
    for c, expected in zip(cases, run_compiler(archive, oracle, cases), strict=True):
        pipeline.syntax_options = SyntaxOptions(target=c["target"].lower())
        node = pipeline.parse(prefix + c["literal"])["body"][0]["expression"]
        actual = [[d.get("code"), d["offset"] - len(prefix), d.get("length"), d.get("suggestion")]
                  for d in node.get("diagnostics", [])]
        if actual != expected or node["alternatives"] is None:
            print(c, actual, expected)
            failures += 1
    print(f"{len(captures)} capture/reference and {len(properties)} Unicode property comparisons, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
