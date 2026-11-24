"""Compare TS string escapes, JSX trees and tag diagnostics against TypeScript 5.9.3."""
import argparse
from pathlib import Path

from check_ts_alias_shapes import project_trees
from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler
from orionparser.languages.javascript.pipeline import SourceSyntaxError


def examples():
    gaps = ("", " ", "\r\n", "\u200b", "/*c*/", "//𐐀\u2028")
    values = (r'"\x41"', r"'a\'b'", r"'\8'", r'"\u{10400}"', '"a\nb"', '"a\\\r\nb"', '"&amp;"',
              "{value}", "<B/>")
    for gap in gaps:
        for value in values:
            yield f"<A data-x={gap}{value}/>;"
        for after_slash in gaps:
            yield f"<><A<T>{gap}/{after_slash}><B x='v'/></>;"
    yield "<A/ /* never closed >"
    yield "<A>text\n<<<<<<< HEAD\nrest</A>"


def mismatched_tags():
    for opening in ("<A>", "<>"):
        for star in ("*", "**", "*=", "**="):
            yield f"{opening}</{star}>"
    for gap in ("", " ", "/*𐐀*/", "\r\n"):
        yield f"<A<T>></{gap}>"
        for fragment_name in ("Foo", "dashed-name", "ns:tag", "𐐀.X"):
            yield f"<></{gap}{fragment_name}>"
        for name in ("Other", "𐐀", "Pkg . View", "ns : tag"):
            for args in ("", "<T>"):
                yield f"<Root{args}></{gap}{name} /* end */>"
                yield f"<Root{args}><{gap}{name}{args}></Root>"
                yield f"<Root{args}><Inner></{gap}{name}></Root>"


def escaped_names():
    for literal in ("1__2", "0x_1", "1e+_2", "1.0__9", "0b1_", "077", "09.2"):
        yield f"<A x={literal}/>"
    for literal in (".1x", ".12foo", ".1e+", ".1e-", ".1n", ".23e1n", ".1𐐀name"):
        for source in (f"<A{literal}/>", f"<Root></A{literal}>", f"<A x={literal}/>"):
            yield source
    for name in ("ns:A.B", "ns:A.B-c", "ns:A.12e2", "ns:A..B", "ns:A...B", "ns:A:B", "A::B",
                 "A..B", "A.1", "a-b.C:Q", "A:1", "A.", "ns:", "A . /*𐐀*/ .B"):
        for source in (f"<{name}/>", f"<Root></{name}>", f"<Root {name}/>"):
            yield source
    for value in ("foo", "foo-bar", "ns:part", "+", "+=", "==", "??=", "/q", "@", "0xff", "10n"):
        yield f"<C data-x= {value}/>"
    for source in ("<C x==y/>", "<C x===y/>", "<C x=>y/>"):
        yield source
    for punctuation in (".", ".25", ":", "...", "123"):
        yield f"<></{punctuation}>"
        yield f"<C p={punctuation}/>"
    for name in (r"a\u{61", r"\u{61", r"a\u{30", r"a-\u{30", r"\u0030", r"a\u002d",
                 r"a\u{110000}", r"a-\u{61z", "♞"):
        for src in ("<" + name + "/>", "+<" + name + "/>", "<C." + name + "/>", "<C " + name + "/>",
                    "<C></" + name + ">", "<C><" + name + "/></C>", "<C child=<" + name + "/>/>"):
            yield src
    for component in ("B-c", "B--c", "B-=c", "𐐀-a"):
        for root in ("A", "this.UI", "a-b.C"):
            yield f"<{root}.{component}/>"
            yield f"<R></{root}.{component}>"
    for name in (r"\u0041", r"\u{10400}", r"x\u0061", r"tag-\u0061", r"\u0074his", r"a\u0062-z"):
        yield f"<{name}/>"
        yield f"<ns:{name}/>"
        yield f"<R {name}/>"
        yield f"<R ns:{name}/>"
        yield f"<R></ /*trivia*/ {name}>"
    for name in (r"\u0041", r"x\u0061", r"a\u0062-z"):
        yield f"<Root.{name}/>"
    for name in (r"\u0030", r"A\u002d", r"tag-\u002d"):
        yield f"<R {name}/>"


def text_errors():
    for parent in ("<A>", "<>", "<UI.A<T>>"):
        for text in ("before𐐀", "{x}\n", "<Inner/>", " "):
            for char in (">", "}"):
                yield parent + text + char + "</A>"
        yield parent + "text\n<<<<<<< HEAD\n</A>"


def unfinished_tags():
    for gap in ("", " ", "/*𐐀*/"):
        for tail in ("", "\\", "\\\\", "\r\n", "\\\n", "\u2028"):
            yield '<A value=' + gap + '"unfinished' + tail
    for prefix in ("", "const x = ", "<Outer>", "<Outer x="):
        for partial in ("<", "<A", "<A.B", "<A.", "<ns:", "<X<T>", "<A x=", "<A /", '<A x="abc'):
            for gap in ("", "  "):
                yield prefix + partial + gap
    for prefix in ("", "const elem = /*𐐀*/ ", "(", "<Outer>"):
        for opening in ("<>", "<  >", "<  Foo . Bar<T>>", "<ns:tag>", "<𐐀>"):
            for content in ("", "\n ", "{x}", "<Inner/>", "<Leaf>body</Leaf>"):
                yield prefix + opening + content
    for opening in ("<A>", "<>"):
        for gap in ("", " /*c*/", "\r\n"):
            yield opening + "</" + gap
    for name in ("A", "A.x", "ns:x", "A.", "ns:"):
        for gap in ("", " /*𐐀*/"):
            yield "<A></" + name + gap


def escape_cases():
    escapes = (r"\x", r"\x0", r"\xZ", r"\u", r"\u1", r"\u12X", r"\u123Z",
               r"\u{}", r"\u{_ff}", r"\u{1_2}", r"\u{1G}", r"\u{110000}", r"\u{000FfffffffX}",
               r"\08", r"\1", r"\1234", r"\377", r"\400", r"\777", r"\8", r"\99",
               r"\x41", r"\u0041", r"\u{00010ffff}", r"\0")
    for escape in escapes:
        for quote in ("'", '"'):
            literal = quote + "𐐀" + escape + quote
            for gap in ("", " ", "/*gap*/"):
                yield {"name": "escape.tsx", "source": "<A x=" + gap + literal + "/>", "projection": "JSX"}
            yield {"name": "escape.ts", "source": literal + ";", "projection": "target expression"}
    for escape in (r"\x", r"\u12", r"\u{", r"\u{123", r"\u{110000"):
        yield {"name": "escape.tsx", "source": '<A x= "' + escape, "projection": "JSX"}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    cases = [{"source": s, "name": "attributes.tsx", "projection": "JSX"} for s in examples()]
    cases.extend({"source": s, "name": "closing.tsx", "projection": "JSX", "diagnosticSpans": True}
                 for s in mismatched_tags())
    cases.extend({"source": s, "name": "eof.tsx", "projection": "JSX", "diagnosticSpans": True}
                 for s in unfinished_tags())
    cases.extend({"source": s, "name": "text.tsx", "projection": "JSX", "diagnosticSpans": True}
                 for s in text_errors())
    cases.extend({"source": s, "name": "names.tsx", "projection": "JSX", "diagnosticSpans": True}
                 for s in escaped_names())
    cases.extend({**case, "diagnosticSpans": True} for case in escape_cases())
    refs = run_compiler(archive, _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text(), cases)
    pipelines = {kind: TypeScriptPipeline("attributes." + kind) for kind in ("ts", "tsx")}
    accepted = rejected = exact = failures = 0
    for case, ref in zip(cases, refs, strict=True):
        try:
            tree = pipelines[case["name"].rsplit(".", 1)[1]].parse(case["source"])
        except SourceSyntaxError as error:
            if case.get("diagnosticSpans"):
                diagnostics = ref.get("diagnostics", [])
                if case["name"] in {"eof.tsx", "text.tsx", "names.tsx", "escape.ts", "escape.tsx"}:
                    diagnostics = diagnostics[:1]
                if [error.code, error.offset, error.length] in diagnostics:
                    exact += 1
                    continue
            elif ref.get("invalid") and 0 <= error.offset <= len(case["source"]):
                rejected += 1
                continue
        else:
            actual = project_trees(tree, case["projection"])
            if actual and actual == ref.get("trees"):
                accepted += 1
                continue
        print(repr(case["source"]), ref)
        failures += 1
    print(f"{accepted} matching trees, {rejected} jointly rejected, {exact} exact diagnostics, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
