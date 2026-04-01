"""CLI entry point for OrionParser."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
        prog="orion",
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

    # langs
    p_langs = sub.add_parser("langs", help="List supported languages")
    p_langs.set_defaults(func=cmd_langs)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)
