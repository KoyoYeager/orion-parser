"""Rebuild the new PLY tables and fail on unresolved LALR conflicts."""
import io
import sys

from ply import yacc

from orionparser.languages.c.pipeline import CGrammar
from orionparser.languages.cpp.pipeline import CppGrammar, ParameterClauseGrammar, TypeIdGrammar
from orionparser.languages.java.pipeline import JavaGrammar
from orionparser.languages.javascript.pipeline import Grammar
from orionparser.languages.javascript.regexp import PatternGrammar
from orionparser.languages.javascript.regexp_sets import SetGrammar
from orionparser.languages.typescript.config import ConfigGrammar
from orionparser.languages.typescript.pipeline import BindingProbe, InferBoundProbe, ArrowHeadProbe, ReturnArmProbe, TsxArrowHeadProbe, TsxGrammar, TypeArgumentProbe, TypeScriptGrammar


def main():
    failed = False
    for label, grammar in [("C17", CGrammar()), ("Java SE 21", JavaGrammar()), ("C++20", CppGrammar()), ("C++ parameter-clause lookahead", ParameterClauseGrammar()), ("C++ type-id lookahead", TypeIdGrammar()), ("JavaScript", Grammar("")), ("RegExp", PatternGrammar()), ("UnicodeSets", SetGrammar()),
                           ("TypeScript project JSONC", ConfigGrammar("", "module")), ("TypeScript", TypeScriptGrammar("")), ("TSX", TsxGrammar("")),
                           ("TS type-argument lookahead", TypeArgumentProbe("")), ("TS arrow head lookahead", ArrowHeadProbe("")),
                           ("TSX arrow head lookahead", TsxArrowHeadProbe("")),
                           ("TS conditional arm lookahead", ReturnArmProbe("")), ("TS infer bound lookahead", InferBoundProbe("")),
                           ("TS signature binding lookahead", BindingProbe(""))]:
        output = io.StringIO()
        parser = yacc.yacc(module=grammar, debug=True, write_tables=False, tabmodule="_orion_conformance_tables",
                           debuglog=yacc.NullLogger(), errorlog=yacc.PlyLogger(output))
        messages = [line for line in output.getvalue().splitlines() if line != "Generating LALR tables"]
        print(f"{label}: {len(parser.productions) - 1} PLY productions, {len(parser.action)} states")
        for line in messages:
            if label in {"C++ parameter-clause lookahead", "C++ type-id lookahead"} and any(word in line for word in ("unreachable", "unused", "not used")):
                continue
            print(line)
            if "conflict" in line or line.startswith("ERROR"):
                failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
