"""VSCode extension bridge — JSON interface for analysis results.

Usage:
    python -m orionparser.vscode_bridge <command> <file_or_dir> [options]

Commands:
    symbols <file>      Extract symbols (functions, classes, variables, imports)
    calltree <path>     Extract call tree (file or directory)
    flowchart <file>    Extract control flow (per-function flowcharts)
    dfd <file>          Extract data flow diagram
    classdiagram <file> Extract class diagram
    tokens <file>       Extract tokens
    ast <file>          Extract AST
    all <file>          All analyses at once
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _get_result(file_path: str):
    """Parse a file and return ParseResult."""
    p = Path(file_path)
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from orionparser.registry import get_pipeline
    pipeline = get_pipeline(p)
    return pipeline.analyze_file(p)


def cmd_symbols(file_path: str) -> dict:
    from orionparser.analysis.symbols import extract_symbols
    result = _get_result(file_path)
    if not result.ast:
        return {"error": "Parse failed", "errors": result.errors}
    table = extract_symbols(result.ast)
    return {"success": True, "symbols": table.to_dict()}


def cmd_calltree(path: str) -> dict:
    from orionparser.analysis.call_tree import extract_call_tree
    p = Path(path)
    if p.is_file():
        result = _get_result(path)
        if not result.ast:
            return {"error": "Parse failed"}
        ct = extract_call_tree(result.ast)
        return {"success": True, "functions": ct["functions"],
                "calls": ct["calls"]}
    elif p.is_dir():
        from orionparser.registry import get_pipeline, supported_extensions
        all_funcs: list[str] = []
        all_calls: list[list[str]] = []
        exts = supported_extensions()
        for f in sorted(p.rglob("*")):
            if f.suffix in exts:
                r = get_pipeline(f).analyze_file(f)
                if r.ast:
                    ct = extract_call_tree(r.ast)
                    all_funcs.extend(ct["functions"])
                    all_calls.extend(ct["calls"])
        return {"success": True, "functions": list(set(all_funcs)),
                "calls": all_calls}
    return {"error": f"Path not found: {path}"}


def cmd_flowchart(file_path: str) -> dict:
    from orionparser.analysis.control_flow import extract_control_flow
    result = _get_result(file_path)
    if not result.ast:
        return {"error": "Parse failed"}
    cf = extract_control_flow(result.ast)
    return {"success": True, "functions": cf["functions"]}


def cmd_dfd(file_path: str) -> dict:
    from orionparser.analysis.dfd import extract_dfd
    result = _get_result(file_path)
    if not result.ast:
        return {"error": "Parse failed"}
    dfd = extract_dfd(result.ast)
    return {"success": True, **dfd}


def cmd_classdiagram(file_path: str) -> dict:
    from orionparser.analysis.class_diagram import extract_classes
    result = _get_result(file_path)
    if not result.ast:
        return {"error": "Parse failed"}
    cd = extract_classes(result.ast)
    return {"success": True, **cd}


def cmd_tokens(file_path: str) -> dict:
    result = _get_result(file_path)
    return {"success": True, "tokens": result.tokens}


def cmd_ast(file_path: str) -> dict:
    result = _get_result(file_path)
    if not result.ast:
        return {"error": "Parse failed"}
    return {"success": True, "ast": result.ast}


def cmd_all(file_path: str) -> dict:
    """All analyses at once."""
    result = _get_result(file_path)
    if not result.ast:
        return {"error": "Parse failed", "errors": result.errors}

    from orionparser.analysis.symbols import extract_symbols
    from orionparser.analysis.call_tree import extract_call_tree
    from orionparser.analysis.control_flow import extract_control_flow
    from orionparser.analysis.dfd import extract_dfd
    from orionparser.analysis.class_diagram import extract_classes

    table = extract_symbols(result.ast)
    ct = extract_call_tree(result.ast)
    cf = extract_control_flow(result.ast)
    dfd = extract_dfd(result.ast)
    cd = extract_classes(result.ast)

    return {
        "success": True,
        "file": file_path,
        "symbols": table.to_dict(),
        "calltree": {"functions": ct["functions"], "calls": ct["calls"]},
        "flowchart": cf["functions"],
        "dfd": dfd,
        "classdiagram": cd,
        "tokens": result.tokens,
    }


def main() -> None:
    # Windows cp932 問題を回避 — stdout を UTF-8 に強制
    import io, os
    if os.name == 'nt':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: vscode_bridge <command> <file>"}))
        sys.exit(1)

    command = sys.argv[1]
    target = sys.argv[2]

    commands = {
        "symbols": cmd_symbols,
        "calltree": cmd_calltree,
        "flowchart": cmd_flowchart,
        "dfd": cmd_dfd,
        "classdiagram": cmd_classdiagram,
        "tokens": cmd_tokens,
        "ast": cmd_ast,
        "all": cmd_all,
    }

    func = commands.get(command)
    if not func:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        sys.exit(1)

    try:
        result = func(target)
        print(json.dumps(result, default=str, ensure_ascii=True))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
