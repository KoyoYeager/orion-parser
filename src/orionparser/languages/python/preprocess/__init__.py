"""Python preprocessing pipeline.

Each stage is a pure function: (source, logs) = stage(source)
Stages are composed in order by run_pipeline().

Comment extraction runs last and returns the comment map separately.
"""

from __future__ import annotations

from orionparser.languages.python.preprocess.normalize_lines import normalize_lines
from orionparser.languages.python.preprocess.remove_bom import remove_bom
from orionparser.languages.python.preprocess.remove_encoding_decl import remove_encoding_declaration
from orionparser.languages.python.preprocess.merge_backslash_lines import merge_backslash_lines
from orionparser.languages.python.preprocess.extract_comments import Comment, extract_comments

STAGES = [
    remove_bom,
    normalize_lines,
    remove_encoding_declaration,
    merge_backslash_lines,
]


def run_pipeline(source: str) -> tuple[str, list[str], list[Comment]]:
    """Run all preprocessing stages in order.

    Returns (processed_source, all_logs, comments).
    Comments are extracted last so line numbers are stable.
    """
    all_logs: list[str] = []
    for stage in STAGES:
        source, logs = stage(source)
        all_logs = all_logs + logs

    # Extract comments after all other preprocessing
    source, comments = extract_comments(source)
    if comments:
        all_logs = all_logs + [
            f"[Preprocessing: ExtractComments] Extracted {len(comments)} comment(s)"
        ]

    return source, all_logs, comments
