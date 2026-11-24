"""Compare Java 21 lexical witnesses to javac's scanner and Character tables."""
import argparse
import base64
import csv
from dataclasses import dataclass
import hashlib
from pathlib import Path
import string
import subprocess
import tempfile

from check_java_modules import ROOT
from orionparser.languages.java.lexer import JavaSource, identifier_class


@dataclass
class Example:
    source: str
    tokens: list
    rules: tuple


def token(source, orion, javac, *rules, value=None):
    return Example(source, [(orion, source if value is None else value, javac)], rules)


def numeric_examples():
    groups = [
        ("INTLITERAL", "0", "DecimalNumeral.1 Digit.1"),
        ("INTLITERAL", "17", "Literal.1 IntegerLiteral.1 DecimalIntegerLiteral.1 DecimalNumeral.2 Digit.2"),
        ("INTLITERAL", "1__2_34", "DecimalNumeral.3 Digits.2 DigitsAndUnderscores.1 DigitOrUnderscore.1 DigitOrUnderscore.2 Underscores.1"),
        ("INTLITERAL", "0xA", "IntegerLiteral.2 HexIntegerLiteral.1 HexNumeral.1 HexDigits.1"),
        ("INTLITERAL", "0XA_B0_1", "HexNumeral.2 HexDigits.2 HexDigitsAndUnderscores.1 HexDigitOrUnderscore.1 HexDigitOrUnderscore.2"),
        ("INTLITERAL", "07", "IntegerLiteral.3 OctalIntegerLiteral.1 OctalNumeral.1 OctalDigits.1"),
        ("INTLITERAL", "0__7_2_3", "OctalNumeral.2 OctalDigits.2 OctalDigitsAndUnderscores.1 OctalDigitOrUnderscore.1 OctalDigitOrUnderscore.2"),
        ("INTLITERAL", "0b0", "IntegerLiteral.4 BinaryIntegerLiteral.1 BinaryNumeral.1 BinaryDigits.1 BinaryDigit.1"),
        ("INTLITERAL", "0B1_0_1", "BinaryNumeral.2 BinaryDigits.2 BinaryDigitsAndUnderscores.1 BinaryDigitOrUnderscore.1 BinaryDigitOrUnderscore.2 BinaryDigit.2"),
        ("LONGLITERAL", "1l", "IntegerTypeSuffix.1"),
        ("LONGLITERAL", "0xFFL", "IntegerTypeSuffix.2"),
        ("DOUBLELITERAL", "12.", "Literal.2 FloatingPointLiteral.1 DecimalFloatingPointLiteral.1"),
        ("FLOATLITERAL", ".1E+2f", "DecimalFloatingPointLiteral.2 Digits.1 ExponentPart.1 ExponentIndicator.2 SignedInteger.1 Sign.1 FloatTypeSuffix.1"),
        ("DOUBLELITERAL", "12e-3", "DecimalFloatingPointLiteral.3 ExponentIndicator.1 Sign.2"),
        ("FLOATLITERAL", "6F", "DecimalFloatingPointLiteral.4 FloatTypeSuffix.2"),
        ("DOUBLELITERAL", "0xA.p0d", "FloatingPointLiteral.2 HexadecimalFloatingPointLiteral.1 HexSignificand.1 BinaryExponent.1 BinaryExponentIndicator.1 FloatTypeSuffix.3"),
        ("DOUBLELITERAL", "0x.4P1D", "HexSignificand.2 BinaryExponentIndicator.2 FloatTypeSuffix.4"),
        ("DOUBLELITERAL", "0X1.8p2", "HexSignificand.3"),
    ]
    for kind, source, rules in groups:
        yield token(source, "NUMBER", kind, *rules.split())
    for rule, chars, prefix in [("NonZeroDigit", "123456789", ""), ("OctalDigit", "01234567", "0"),
                                ("HexDigit", string.hexdigits, "0x")]:
        for i, char in enumerate(chars, 1):
            yield token(prefix + char, "NUMBER", "INTLITERAL", f"{rule}.{i}")


def trivia_examples():
    def between(middle, *rules):
        return Example("a" + middle + "b", [("IDENT", "a", "IDENTIFIER"), ("IDENT", "b", "IDENTIFIER")], rules)

    for i, newline in enumerate(["\n", "\r", "\r\n"], 1):
        yield between(newline, f"LineTerminator.{i}", "WhiteSpace.4", "InputElement.1")
    for i, space in enumerate([" ", "\t", "\f"], 1):
        yield between(space, f"WhiteSpace.{i}")
    yield between("/**/", "InputElement.2", "Comment.1", "TraditionalComment.1", "CommentTail.1", "CommentTailStar.1")
    yield between("/***x*y*/", "CommentTailStar.2", "CommentTailStar.3", "NotStarNotSlash.1")
    yield between("/*a\n*\nb*/", "CommentTail.2", "NotStar.1", "NotStar.2", "NotStarNotSlash.2")
    yield between("//abc\r\n", "Comment.2", "EndOfLineComment.1")
    yield between(r"//abc\u000a", "UnicodeInputCharacter.1", "UnicodeEscape.1")
    yield Example("a \x1a", [("IDENT", "a", "IDENTIFIER")], ("Input.1", "Sub.1"))
    yield token(r"\uuuu03B1", "IDENT", "IDENTIFIER", "UnicodeMarker.1", value="α")
    yield token("𐐀α8", "IDENT", "IDENTIFIER", "UnicodeInputCharacter.2", "RawInputCharacter.1", "InputCharacter.1",
                "InputElement.3", "Token.1", "Identifier.1", "IdentifierChars.1", "JavaLetter.1", "JavaLetterOrDigit.1")
    yield token(r"x\u0000y", "IDENT", "IDENTIFIER", value="xy")
    yield token(r"\uD801\uDC00", "IDENT", "IDENTIFIER", value="𐐀")


def literal_examples():
    yield token("true", "TRUE", "TRUE", "Literal.3", "BooleanLiteral.1")
    yield token("false", "FALSE", "FALSE", "BooleanLiteral.2")
    yield token("null", "NULL", "NULL", "Literal.7", "NullLiteral.1")
    yield token("'a'", "CHARACTER", "CHARLITERAL", "Literal.4", "CharacterLiteral.1", "SingleCharacter.1")
    yield token(r"'\7'", "CHARACTER", "CHARLITERAL", "CharacterLiteral.2", "OctalEscape.1")
    yield token(r"'\07'", "CHARACTER", "CHARLITERAL", "OctalEscape.2")
    for i in range(4):
        yield token(f"'\\{i}07'", "CHARACTER", "CHARLITERAL", "OctalEscape.3", f"ZeroToThree.{i+1}")
    yield token(r'"a\t"', "STRING", "STRINGLITERAL", "Token.3", "Literal.5", "StringLiteral.1", "StringCharacter.1", "StringCharacter.2")


def fixed_examples(inventory):
    by_digest = {(r["rule"], r["rhs_sha256"]): r["alternative"] for r in inventory}
    keywords = """abstract assert boolean break byte case catch char class const continue default do double else enum
                  extends final finally float for goto if implements import instanceof int interface long native new
                  package private protected public return short static strictfp super switch synchronized this throw
                  throws transient try void volatile while _""".split()
    separators = list(zip("(){}[];,.", "LPAREN RPAREN LBRACE RBRACE LBRACKET RBRACKET SEMI COMMA DOT".split(), strict=True))
    separators += [("...", "ELLIPSIS"), ("@", "MONKEYS_AT"), ("::", "COLCOL")]
    operators = list(zip("= > < ! ~ ? : -> == >= <= != && || ++ -- + - * / & | ^ % << >> >>> += -= *= /= &= |= ^= %= <<= >>= >>>=".split(),
                         "EQ GT LT BANG TILDE QUES COLON ARROW EQEQ GTEQ LTEQ BANGEQ AMPAMP BARBAR PLUSPLUS SUBSUB PLUS SUB STAR SLASH AMP BAR CARET PERCENT LTLT GTGT GTGTGT PLUSEQ SUBEQ STAREQ SLASHEQ AMPEQ BAREQ CARETEQ PERCENTEQ LTLTEQ GTGTEQ GTGTGTEQ".split(), strict=True))
    kinds = {"...": "ELLIPSIS", "::": "COLONS", "->": "ARROW", "==": "EQ", "!=": "EQ", ">=": "REL", "<=": "REL",
             "&&": "AND", "||": "OR", "++": "INC", "--": "DEC", "<<": "SHIFT", ">>": "SHIFT", ">>>": "SHIFT"}
    for rule, pairs, other in [("ReservedKeyword", [(s, "UNDERSCORE" if s == "_" else s.upper()) for s in keywords], ("Token.2", "Keyword.1")),
                               ("Separator", separators, ("Token.4",)), ("Operator", operators, ("Token.5",))]:
        for spelling, javac in pairs:
            index = by_digest[rule, hashlib.sha256(spelling.encode()).hexdigest()]
            if rule == "ReservedKeyword":
                kind = "PRIMITIVE" if spelling in "boolean byte char double float int long short".split() else spelling.upper()
            else:
                kind = kinds.get(spelling, "ASSIGN_OP" if len(spelling) > 1 else spelling)
            yield token(spelling, kind, javac, f"{rule}.{index}", *other)
    yield Example("08 09L 0b12", [("NUMBER", "0", "INTLITERAL"), ("NUMBER", "8", "INTLITERAL"),
                                 ("NUMBER", "0", "INTLITERAL"), ("NUMBER", "9L", "LONGLITERAL"),
                                 ("NUMBER", "0b1", "INTLITERAL"), ("NUMBER", "2", "INTLITERAL")], ())
    yield Example("1f_ 0x12L_", [("NUMBER", "1f", "FLOATLITERAL"), ("_", "_", "UNDERSCORE"),
                                 ("NUMBER", "0x12L", "LONGLITERAL"), ("_", "_", "UNDERSCORE")], ())
    yield Example("x>>>=2.5F+0x1p-1", [("IDENT", "x", "IDENTIFIER"), ("ASSIGN_OP", ">>>=", "GTGTGTEQ"),
                                       ("NUMBER", "2.5F", "FLOATLITERAL"), ("+", "+", "PLUS"),
                                       ("NUMBER", "0x1p-1", "DOUBLELITERAL")], ())


MALFORMED = [
    ("0x", "invalid.hex.number", 0), ("0xG", "invalid.hex.number", 0), ("0x.p1", "invalid.hex.number", 0),
    ("0x_FF", "illegal.underscore", 2), ("0b", "invalid.binary.number", 0), ("0b2", "invalid.binary.number", 0),
    ("0b_1", "illegal.underscore", 2), ("0b1_2", "illegal.underscore", 3), ("0__", "illegal.underscore", 1),
    ("1_", "illegal.underscore", 1), ("1__a", "illegal.underscore", 2), ("1_l", "illegal.underscore", 1),
    ("1_.", "illegal.underscore", 1), ("1._0", "illegal.underscore", 2), ("1e", "malformed.fp.lit", 0),
    ("1e+", "malformed.fp.lit", 0), ("1e_2", "illegal.underscore", 2), ("1e+_2", "illegal.underscore", 3),
    ("0x1.", "malformed.fp.lit", 0), ("0x1.g", "malformed.fp.lit", 0), ("0x1.p", "malformed.fp.lit", 0),
    ("0x1p+", "malformed.fp.lit", 0), ("0x1_p1", "illegal.underscore", 3), ("0x1.0_p-1", "illegal.underscore", 5),
    (".2_", "illegal.underscore", 2), ("..", "illegal.dot", 1), ("x..y", "illegal.dot", 2),
]


def encoded_inputs(sources):
    return "".join(base64.b64encode(s.encode()).decode() + "\n" for s in sources)


def run(jdk):
    with (ROOT / "docs/conformance/java-se21.tsv").open() as stream:
        inventory = list(csv.DictReader(stream, delimiter="\t"))
    examples = [*numeric_examples(), *trivia_examples(), *literal_examples(), *fixed_examples(inventory)]
    opts = ["--add-exports", "jdk.compiler/com.sun.tools.javac.parser=ALL-UNNAMED",
            "--add-exports", "jdk.compiler/com.sun.tools.javac.util=ALL-UNNAMED"]
    with tempfile.TemporaryDirectory() as directory:
        subprocess.run([jdk/"bin/javac", *opts, "-d", directory, ROOT/"tools/conformance/JavaLexOracle.java"], check=True)
        command = [jdk/"bin/java", *opts, "-cp", directory, "JavaLexOracle"]
        ranges = subprocess.check_output([*command, "characters"], text=True)
        if ranges != (ROOT/"src/orionparser/languages/java/identifier-classes.txt").read_text():
            raise ValueError("identifier data differs from pinned JDK")
        rows = [tuple(line.split()) for line in ranges.splitlines()]
        for (start, kind), (end, _) in zip(rows, [*rows[1:], ("110000", "")], strict=True):
            for cp in range(int(start, 16), int(end, 16)):
                if identifier_class(chr(cp)) != int(kind):
                    raise ValueError(f"identifier class mismatch at U+{cp:04X}")
        source = encoded_inputs(e.source for e in examples)
        output = subprocess.check_output(command, input=source, text=True).splitlines()
        diagnostics = subprocess.check_output([*command, "errors"], input=encoded_inputs(m[0] for m in MALFORMED),
                                              text=True).splitlines()
    for (source, code, offset), messages in zip(MALFORMED, diagnostics, strict=True):
        if messages.split()[:1] != [f"compiler.err.{code}:{offset}"]:
            raise ValueError(f"{source!r}: unexpected javac diagnostic {messages!r}")
        try:
            list(JavaSource(source).tokens())
        except ValueError as exc:
            if not str(exc).startswith(f"line 1, column {offset+1}:"):
                raise ValueError(f"{source!r}: unexpected Orion location {exc}") from exc
        else:
            raise ValueError(f"Orion accepted malformed token {source!r}")
    seen = set()
    for case, line in zip(examples, output, strict=True):
        tokens = list(JavaSource(case.source).tokens())
        if [(t.type, t.value) for t in tokens] != [(k,v) for k,v,_ in case.tokens]:
            raise ValueError(f"unexpected Orion tokens in {case.source!r}: {tokens}")
        def utf16(index):
            return len(case.source[:index].encode("utf-16-le")) // 2
        reference = [f"{kind}:{utf16(t.lexpos)}:{utf16(t.endlexpos)}" for t, (_,_,kind) in zip(tokens, case.tokens)]
        if line.split() != reference:
            raise ValueError(f"{case.source!r}: javac {line}, expected {reference}")
        seen.update(tuple(r.rsplit(".", 1)) for r in case.rules)
    known = {(r["rule"], r["alternative"]) for r in inventory}
    if seen - known:
        raise ValueError(f"unknown lexical alternatives {seen-known}")
    print(f"{len(examples)} javac token streams, {len(MALFORMED)} positioned lexical rejections, {len(seen)} lexical alternatives, 1,114,112 identifier classes matched")
    return seen


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--jdk", type=Path, default=ROOT / ".venv/toolchains/jdk-21.0.2")
    run(cli.parse_args().jdk)
