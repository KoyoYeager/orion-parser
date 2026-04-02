"""CLI entry point for OrionParser."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from orionparser.registry import get_pipeline, supported_extensions


def cmd_parse(args: argparse.Namespace) -> None:
    """Parse a file and display the AST."""
    path = Path(args.file)
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    pipeline = get_pipeline(path)
    result = pipeline.analyze_file(path)

    if args.json:
        print(json.dumps(result.ast, indent=2, ensure_ascii=False))
    else:
        _print_result(result)


def cmd_tokens(args: argparse.Namespace) -> None:
    """Tokenize a file and display tokens."""
    path = Path(args.file)
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    pipeline = get_pipeline(path)
    source = path.read_text(encoding="utf-8")
    preprocessed = pipeline.preprocess(source)
    tokens = pipeline.tokenize(preprocessed)

    if args.json:
        print(json.dumps(tokens, indent=2, ensure_ascii=False))
    else:
        for tok in tokens:
            print(f"{tok.get('type', '?'):20s} {tok.get('value', '')!r}")


def cmd_analyze(args: argparse.Namespace) -> None:
    """Analyze a file: call tree, data flow."""
    path = Path(args.file)
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    pipeline = get_pipeline(path)
    result = pipeline.analyze_file(path)
    if not result.ast:
        print("Parse failed, cannot analyze", file=sys.stderr)
        sys.exit(1)

    output: dict[str, Any] = {}

    if args.call_tree or args.all:
        from orionparser.analysis.call_tree import extract_call_tree
        ct = extract_call_tree(result.ast)
        output["call_tree"] = {"functions": ct["functions"], "calls": ct["calls"]}

    if args.data_flow or args.all:
        from orionparser.analysis.data_flow import extract_data_flow
        df = extract_data_flow(result.ast)
        output["data_flow"] = {"variables": df["variables"], "flows": df["flows"]}

    if args.symbols or args.all:
        from orionparser.analysis.symbols import extract_symbols
        st = extract_symbols(result.ast)
        output["symbols"] = st.to_dict()

    if not output:
        # Default to all
        from orionparser.analysis.call_tree import extract_call_tree
        from orionparser.analysis.data_flow import extract_data_flow
        from orionparser.analysis.symbols import extract_symbols
        ct = extract_call_tree(result.ast)
        df = extract_data_flow(result.ast)
        st = extract_symbols(result.ast)
        output["call_tree"] = {"functions": ct["functions"], "calls": ct["calls"]}
        output["data_flow"] = {"variables": df["variables"], "flows": df["flows"]}
        output["symbols"] = st.to_dict()

    print(json.dumps(output, indent=2, ensure_ascii=False))


def cmd_langs(args: argparse.Namespace) -> None:
    """List supported languages."""
    for ext in supported_extensions():
        print(ext)


def _print_result(result) -> None:
    """Pretty-print a ParseResult."""
    status = "OK" if result.success else "FAIL"
    print(f"[{status}] {result.file_path}")
    if result.errors:
        for err in result.errors:
            print(f"  ERROR: {err}")
    if result.ast:
        print(json.dumps(result.ast, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="orion-parser",
        description="OrionParser — Multi-language source code analysis engine",
    )
    sub = parser.add_subparsers(dest="command")

    # parse
    p_parse = sub.add_parser("parse", help="Parse a file into AST")
    p_parse.add_argument("file", help="Source file to parse")
    p_parse.add_argument("--json", action="store_true", help="JSON output")
    p_parse.set_defaults(func=cmd_parse)

    # tokens
    p_tokens = sub.add_parser("tokens", help="Tokenize a file")
    p_tokens.add_argument("file", help="Source file to tokenize")
    p_tokens.add_argument("--json", action="store_true", help="JSON output")
    p_tokens.set_defaults(func=cmd_tokens)

    # analyze
    p_analyze = sub.add_parser("analyze", help="Analyze call tree and data flow")
    p_analyze.add_argument("file", help="Source file to analyze")
    p_analyze.add_argument("--call-tree", action="store_true", help="Extract call tree")
    p_analyze.add_argument("--data-flow", action="store_true", help="Extract data flow")
    p_analyze.add_argument("--symbols", action="store_true", help="Extract symbols")
    p_analyze.add_argument("--all", action="store_true", help="All analyses")
    p_analyze.set_defaults(func=cmd_analyze)

    # langs
    p_langs = sub.add_parser("langs", help="List supported languages")
    p_langs.set_defaults(func=cmd_langs)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)
