"""Check indexed lexical alternatives against the C token stream and Clang 18.1.8."""
import argparse
import csv
import hashlib
import re
import string
import subprocess

from check_c17 import FLAGS, ROOT, check_version
from orionparser.languages.c.pipeline import CPipeline


def witnesses():
    keywords = {
        "TYPE": "char double float int long short signed unsigned void _Bool _Complex _Imaginary",
        "QUALIFIER": "const restrict volatile",
        "STORAGE": "auto extern register typedef _Thread_local",
        "FUNCTION_SPEC": "inline _Noreturn",
    }
    direct = ("break case continue default do else enum for goto if return sizeof static struct "
              "switch union while _Alignas _Alignof _Atomic _Generic _Static_assert")
    for word in direct.split():
        yield "keyword", word, word, word.upper(), word
    for kind, words in keywords.items():
        for word in words.split():
            yield "keyword", word, word, kind, word
    for char in "_" + string.ascii_letters:
        yield "nondigit", char, char, "NAME", "identifier"
    for rule, chars, prefix in [
        ("digit", string.digits, "3"), ("nonzero-digit", "123456789", ""),
        ("octal-digit", "01234567", "0"), ("hexadecimal-digit", string.hexdigits, "0x"),
        ("unsigned-suffix", "uU", "42"), ("long-suffix", "lL", "42"),
        ("long-long-suffix", ["ll", "LL"], "42"), ("floating-suffix", "flFL", "1."),
    ]:
        for char in chars:
            yield rule, char, prefix + char, "NUMBER", "numeric_constant"
    # Clang exposes a separate token kind for each operator.
    for spellings, orion, clang in [
        ("[ <:","[","l_square"), ("] :>","]","r_square"), ("(","(","l_paren"), (")",")","r_paren"),
        ("{ <%","{","l_brace"), ("} %>","}","r_brace"), (".",".","period"), ("->","ARROW","arrow"),
        ("++","INC","plusplus"), ("--","DEC","minusminus"), ("&","&","amp"), ("*","*","star"),
        ("+","+","plus"), ("-","-","minus"), ("~","~","tilde"), ("!","!","exclaim"), ("/","/","slash"),
        ("%","%","percent"), ("<<","SHIFT","lessless"), (">>","SHIFT","greatergreater"),
        ("<","<","less"), (">",">","greater"), ("<=","COMPARE","lessequal"), (">=","COMPARE","greaterequal"),
        ("==","EQUAL","equalequal"), ("!=","EQUAL","exclaimequal"), ("^","^","caret"), ("|","|","pipe"),
        ("&&","AND","ampamp"), ("||","OR","pipepipe"), ("?","?","question"), (":",":","colon"),
        (";",";","semi"), ("...","ELLIPSIS","ellipsis"), ("=","=","equal"), (",",",","comma"),
    ]:
        for spelling in spellings.split():
            yield "punctuator", spelling, spelling, orion, clang
    for spelling, kind in zip("*= /= %= += -= <<= >>= &= ^= |=".split(),
                              "star slash percent plus minus lessless greatergreater amp caret pipe".split(), strict=True):
        yield "punctuator", spelling, spelling, "ASSIGN_OP", kind + "equal"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--clang", default="clang-18")
    compiler = cli.parse_args().clang
    check_version(compiler)
    with (ROOT / "docs/conformance/c17.tsv").open() as stream:
        inventory = {(r["rule"], r["rhs_sha256"]): r["alternative"] for r in csv.DictReader(stream, delimiter="\t")}
    rows = list(witnesses())
    source = "\n".join(row[2] for row in rows) + "\n"
    tokens = CPipeline().tokenize(source)
    reference = subprocess.run([compiler, *FLAGS, "-x", "cpp-output", "-fsyntax-only", "-Xclang", "-dump-tokens", "-"],
                               input=source, text=True, capture_output=True, check=True)
    clang_tokens = re.findall(r"^(\w+) '([^'\n]*)'\s+.*?Loc=<<stdin>:(\d+):1>", reference.stderr, re.M)
    clang_tokens = [token for token in clang_tokens if token[0] != "eof"]
    seen = set()
    for line, (row, token, clang) in enumerate(zip(rows, tokens, clang_tokens, strict=True), start=1):
        rule, rhs, spelling, kind, clang_kind = row
        key = (rule, hashlib.sha256(rhs.encode()).hexdigest())
        if key not in inventory or key in seen:
            raise ValueError(f"{rule}: unindexed or duplicated {rhs!r}")
        if (token["type"], token["value"], token["line"]) != (kind, spelling, line):
            raise ValueError(f"{rule}: unexpected token {token}")
        if clang != (clang_kind, spelling, str(line)):
            raise ValueError(f"{rule}: unexpected Clang token {clang}")
        seen.add(key)
    print(f"{len(seen)} distinct indexed lexical alternatives checked against Clang tokens")
    return {(rule, inventory[rule, digest]) for rule, digest in seen}


if __name__ == "__main__":
    main()
