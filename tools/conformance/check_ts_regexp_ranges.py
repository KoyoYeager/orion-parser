"""Compare ESNext diagnostic codes and spans for character class ranges and UnicodeSets complements."""
import argparse
from itertools import product
from pathlib import Path

from check_typescript import COMPILER_SHA, TypeScriptPipeline, check_pin, run_compiler


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    endpoints = ("a", "z", "-", r"\-", r"\x66", r"\u007A", r"\d", r"\s", "𐐀", r"\uD801\uDC00")
    patterns = [f"/[^{left}-{right}]/{flags}" for flags in ("", "u") for left in endpoints for right in endpoints]
    patterns += [r"/[\d-\sZ-A]/u", r"/[z-a9-0]/", r"/[a-]/u", r"/[\w-]/u", "/[]/", r"/[\p{L}-\d]/u"]
    set_endpoints = (r"\-", "z", r"\u{10400}", r"\d", r"\p{L}", "[a]", "[a&&b]", r"\q{x}", r"\q{xy|z}")
    patterns += [f"/[{prefix}{left}-{right}]/v" for prefix in ("", "^") for left in set_endpoints for right in set_endpoints]
    patterns += ["/[a-]/v", "/[ab-]/v", r"/[^\q{abc}-]/v", "/[[a]-]/v"]
    operands = ("a", r"\d", r"\p{RGI_Emoji}", r"\q{x}", r"\q{ab|c}", r"[\q{ab}]",
                r"[a\q{ab}]", r"[\q{ab}a]", r"[a-\q{ab}]")
    patterns += [f"/[^{left}{operator}{right}]/v" for left in operands for right in operands
                 for operator in ("", "&&", "--")]
    patterns += [r"/[^\q{ab}x-\q{cd}]/v", r"/[^\q{ab}&&\q{x|yz}&&\p{RGI_Emoji}]/v",
                 r"/[^\q{ab}--[^\q{xy}]]/v", r"/[^\q{ab}[^\q{cd}]]/v"]
    strings = ("", "x", "𐐀", "a|b", "||", r"\q", r"\d", r"\c", r"\c1", r"\cA", r"\c𐐀", r"\k", r"\_", r"\𐐀", r"\|", r"\b", r"\x41",
               "a-b", "(x)", "a/b", "a{", *[ch * 2 for ch in "&!#$%*+,.:;<=>?@^`~"])
    patterns += [f"/[{neg}\\q{{{part}}}]/v" for neg in ("", "^") for part in strings]
    patterns += [r"/[\q]/v", r"/[a-\q]/v", r"/[\q-\d]/v", r"/[\q\q{ab}]/v"]
    for escape in (r"\0", r"\01", r"\08", r"\9", r"\111", r"\400"):
        patterns.extend(f"/[a-{escape}]/{flag}" for flag in ("", "u", "v"))
        patterns.append(f"/[^\\q{{{escape}}}]/v")
    for escape in (r"\x", r"\x4", r"\xZ", r"\u", r"\u00", r"\u00Z", r"\u{}", r"\u{110000}",
                   r"\u{123", r"\u{fZ}", r"\u{Z}", r"\u{11_2}", r"\u{", r"\u{0000110000}", r"\uD800\uZ"):
        for flag in ("", "u", "v"):
            patterns.extend((f"/{escape}/{flag}", f"/[a-{escape}]/{flag}", f"/[{escape}-z]/{flag}"))
        patterns.append(f"/[^\\q{{{escape}}}]/v")
    for first in ("&&", "--"):
        for following in ("&&", "--"):
            for a, b in (("a", "b"), ("[a]", r"\p{L}"), (r"\q{ab}", r"\q{xy}")):
                for prefix in ("", "^"):
                    patterns.append(f"/[{prefix}{a}{first}{b}{following}z]/v")
                    patterns.append(f"/[{prefix}{a}{first}{b}{following}]/v")
        patterns.extend((f"/[{first}a]/v", f"/[a{first}]/v", f"/[{first}]/v"))
    patterns += [f"/[{body}]/v" for body in ("ab&&c", "ab--c", "a-b&&", "ab&&&c", "a&&&b",
                                              "&&&", "a&&b&&&c", "a--b&&&c", "[a]b--[c]&&d")]
    for operator in ("&&", "--"):
        for right in ("c", "cd", r"c\q", "[x]", "[x&&y]", r"\q{ab}", r"\d", r"\q", r"[\d-\s]"):
            for prefix in ("", "^"):
                patterns.append(f"/[{prefix}a{operator}b{right}]/v")
    patterns += ["/[a&&b--cd]/v", r"/[^\q{aa}&&\q{bb}\q{cc}]/v"]
    patterns += [f"/[{body}]/v" for body in ("&", "&x", "a&b", "ab&c", "a&-", "a&-b", "a-b&c",
                 "a-bc&d", "a&b&c", "a&&b-c", "a--b-c", "a&&b-", "a--b&c", "a&&b&", "ab&&c&d")]
    patterns += ["/[" + "".join(parts) + "]/v" for size in range(1, 9) for parts in product("a-&", repeat=size)]
    for char in "!#$%*+,.:;<=>?@^`~":
        double = char * 2
        for content in (double, "a-" + double, double + "-z", "a&&" + double, "a&&b" + double):
            patterns.append("/[" + content + "]/v")
    patterns = list(dict.fromkeys(patterns))
    oracle = """
    const ts = require(process.argv[1]);
    const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
    process.stdout.write(JSON.stringify(cases.map(literal => {
        const diagnostics = [];
        const scanner = ts.createScanner(ts.ScriptTarget.ESNext, true, ts.LanguageVariant.Standard, literal, (d, length) => {
            let start = scanner.getTextPos(), end = start + length;
            // A legacy range may begin or end inside an astral source character.
            // Compare the smallest code-point span covering the UTF-16 diagnostic.
            function splitsPair(pos) {
                return literal.charCodeAt(pos - 1) >= 0xd800 && literal.charCodeAt(pos - 1) <= 0xdbff &&
                    literal.charCodeAt(pos) >= 0xdc00 && literal.charCodeAt(pos) <= 0xdfff;
            }
            if (splitsPair(start)) --start;
            if (splitsPair(end)) ++end;
            diagnostics.push([d.code, Array.from(literal.slice(0, start)).length,
                Array.from(literal.slice(start, end)).length]);
        });
        scanner.scan();
        scanner.reScanSlashToken(true);
        return diagnostics;
    })));
    """
    pipeline = TypeScriptPipeline("range.ts")
    prefix = "/*𐐀*/ "
    failures = 0
    for literal, expected in zip(patterns, run_compiler(archive, oracle, patterns), strict=True):
        node = pipeline.parse(prefix + literal)["body"][0]["expression"]
        actual = [[d.get("code"), d["offset"] - len(prefix), d.get("length")] for d in node.get("diagnostics", [])]
        if actual != expected or node["alternatives"] is None:
            print(literal, actual, expected)
            failures += 1
    print(f"{len(patterns)} character-class comparisons, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
