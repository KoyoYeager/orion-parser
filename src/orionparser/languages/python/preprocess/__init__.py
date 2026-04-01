"""Python preprocessing pipeline.

Each stage is a pure function: (source, logs) = stage(source)
Stages are composed in order by run_pipeline().
"""

from orionparser.languages.python.preprocess.normalize_lines import normalize_lines
from orionparser.languages.python.preprocess.remove_bom import remove_bom
from orionparser.languages.python.preprocess.remove_encoding_decl import remove_encoding_declaration
from orionparser.languages.python.preprocess.merge_backslash_lines import merge_backslash_lines

STAGES = [
    remove_bom,
    normalize_lines,
    remove_encoding_declaration,
    merge_backslash_lines,
]


def run_pipeline(source: str) -> tuple[str, list[str]]:
    """Run all preprocessing stages in order.

    Returns (processed_source, all_logs).
    """
    all_logs: list[str] = []
    for stage in STAGES:
        source, logs = stage(source)
        all_logs = all_logs + logs
    return source, all_logs
