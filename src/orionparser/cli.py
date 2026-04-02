"""CLI entry point for OrionParser."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from orionparser.registry import get_pipeline, supported_extensions


def _collect_files(path: Path) -> list[Path]:
    """Resolve path to a list of parseable files."""
    if path.is_file():
        return [path]
    if path.is_dir():
        exts = supported_extensions()
        return sorted(f for f in path.rglob("*") if f.suffix in exts)
    print(f"Error: {path} not found", file=sys.stderr)
    sys.exit(1)


def cmd_parse(args: argparse.Namespace) -> None:
    """Parse file(s) and display the AST."""
    files = _collect_files(Path(args.path))

    if args.json and len(files) > 1:
        # Multi-file JSON: array of results
        results = []
        for f in files:
            pipeline = get_pipeline(f)
            result = pipeline.analyze_file(f)
            results.append({
                "file": str(f),
                "success": result.success,
                "ast": result.ast,
            })
        print(json.dumps(results, indent=2))
    elif args.json:
        pipeline = get_pipeline(files[0])
        result = pipeline.analyze_file(files[0])
        print(json.dumps(result.ast, indent=2))
    else:
        ok = fail = 0
        for f in files:
            pipeline = get_pipeline(f)
            result = pipeline.analyze_file(f)
            _print_result(result)
            if result.success:
                ok += 1
            else:
                fail += 1
        if len(files) > 1:
            print(f"\n{ok}/{ok + fail} files parsed successfully")


def cmd_tokens(args: argparse.Namespace) -> None:
    """Tokenize file(s) and display tokens."""
    files = _collect_files(Path(args.path))

    for f in files:
        pipeline = get_pipeline(f)
        source = f.read_text(encoding="utf-8")
        preprocessed = pipeline.preprocess(source)
        tokens = pipeline.tokenize(preprocessed)

        if len(files) > 1:
            print(f"--- {f} ---")

        if args.json:
            print(json.dumps(tokens, indent=2))
        else:
            for tok in tokens:
                print(f"{tok.get('type', '?'):20s} {tok.get('value', '')!r}")


def cmd_analyze(args: argparse.Namespace) -> None:
    """Analyze file(s): call tree, data flow, symbols."""
    files = _collect_files(Path(args.path))

    all_output: list[dict[str, Any]] = []
    for f in files:
        pipeline = get_pipeline(f)
        result = pipeline.analyze_file(f)
        if not result.ast:
            print(f"[FAIL] {f}: parse failed", file=sys.stderr)
            continue

        output: dict[str, Any] = {"file": str(f)}

        if args.call_tree or args.all or not (args.call_tree or args.data_flow or args.symbols):
            from orionparser.analysis.call_tree import extract_call_tree
            ct = extract_call_tree(result.ast)
            output["call_tree"] = {"functions": ct["functions"], "calls": ct["calls"]}

        if args.data_flow or args.all or not (args.call_tree or args.data_flow or args.symbols):
            from orionparser.analysis.data_flow import extract_data_flow
            df = extract_data_flow(result.ast)
            output["data_flow"] = {"variables": df["variables"], "flows": df["flows"]}

        if args.symbols or args.all or not (args.call_tree or args.data_flow or args.symbols):
            from orionparser.analysis.symbols import extract_symbols
            st = extract_symbols(result.ast)
            output["symbols"] = st.to_dict()

        all_output.append(output)

    if len(all_output) == 1:
        # Single file: output without wrapping array
        print(json.dumps(all_output[0], indent=2))
    else:
        print(json.dumps(all_output, indent=2))


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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="orion-parser",
        description="OrionParser — Multi-language source code analysis engine",
    )
    sub = parser.add_subparsers(dest="command")

    # parse
    p_parse = sub.add_parser("parse", help="Parse file or directory into AST")
    p_parse.add_argument("path", help="Source file or directory")
    p_parse.add_argument("--json", action="store_true", help="JSON output")
    p_parse.set_defaults(func=cmd_parse)

    # tokens
    p_tokens = sub.add_parser("tokens", help="Tokenize file or directory")
    p_tokens.add_argument("path", help="Source file or directory")
    p_tokens.add_argument("--json", action="store_true", help="JSON output")
    p_tokens.set_defaults(func=cmd_tokens)

    # analyze
    p_analyze = sub.add_parser("analyze", help="Analyze call tree, data flow, symbols")
    p_analyze.add_argument("path", help="Source file or directory")
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
