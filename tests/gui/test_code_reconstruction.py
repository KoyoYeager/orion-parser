"""Code reconstruction test — verify flowchart + call tree contain enough info
to reconstruct the original code.

For each function in the test project, we verify:
1. Function name and signature (parameters with defaults)
2. All assignments with exact variable names and values
3. All function calls with exact arguments
4. All control flow structures (if/for/while with conditions)
5. All return values
6. Call relationships between functions
7. Import relationships
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from orionparser.analysis.control_flow import extract_control_flow
from orionparser.analysis.call_tree import extract_call_tree


TEST_DIR = Path("C:/tmp/fc_test")


@pytest.fixture(scope="module")
def all_results():
    from orionparser.registry import get_pipeline
    results = {}
    for f in sorted(TEST_DIR.glob("*.py")):
        pipeline = get_pipeline(f)
        results[f.name] = pipeline.analyze_file(f)
    return results


@pytest.fixture(scope="module")
def all_cfgs(all_results):
    cfgs = {}
    for fname, result in all_results.items():
        cf = extract_control_flow(result.ast)
        for func_name, cfg in cf["functions"].items():
            cfgs[f"{fname}::{func_name}"] = cfg
    return cfgs


@pytest.fixture(scope="module")
def all_calls(all_results):
    calls = {}
    for fname, result in all_results.items():
        ct = extract_call_tree(result.ast)
        calls[fname] = ct
    return calls


def _labels(cfg: dict) -> list[str]:
    return [n["label"] for n in cfg["nodes"]]


def _has(cfg: dict, pattern: str) -> bool:
    return any(pattern in l for l in _labels(cfg))


# ============================================================
# main.py::main
# ============================================================

class TestMainFunction:
    def test_signature(self, all_cfgs):
        assert _has(all_cfgs["main.py::main"], "main()")

    def test_data_assignment(self, all_cfgs):
        assert _has(all_cfgs["main.py::main"], "data = [10, -5, 0")

    def test_process_data_call(self, all_cfgs):
        assert _has(all_cfgs["main.py::main"], "process_data(data, threshold=10)")

    def test_generate_report_call(self, all_cfgs):
        assert _has(all_cfgs["main.py::main"], "generate_report(results)")

    def test_print_call(self, all_cfgs):
        assert _has(all_cfgs["main.py::main"], "print(report)")

    def test_return_zero(self, all_cfgs):
        assert _has(all_cfgs["main.py::main"], "return 0")

    def test_call_tree_edges(self, all_calls):
        calls = {(c, e) for c, e in all_calls["main.py"]["calls"]}
        assert ("main", "process_data") in calls
        assert ("main", "generate_report") in calls
        assert ("main", "print") in calls


# ============================================================
# processor.py::validate
# ============================================================

class TestValidateFunction:
    def test_signature(self, all_cfgs):
        assert _has(all_cfgs["processor.py::validate"], "validate(item)")

    def test_none_check(self, all_cfgs):
        assert _has(all_cfgs["processor.py::validate"], "item is None")

    def test_isinstance_check(self, all_cfgs):
        assert _has(all_cfgs["processor.py::validate"], "isinstance(item")

    def test_return_false_twice(self, all_cfgs):
        cfg = all_cfgs["processor.py::validate"]
        false_returns = [l for l in _labels(cfg) if "return False" in l]
        assert len(false_returns) == 2

    def test_return_true(self, all_cfgs):
        assert _has(all_cfgs["processor.py::validate"], "return True")


# ============================================================
# processor.py::transform
# ============================================================

class TestTransformFunction:
    def test_signature(self, all_cfgs):
        assert _has(all_cfgs["processor.py::transform"], "transform(value, multiplier=2)")

    def test_positive_condition(self, all_cfgs):
        assert _has(all_cfgs["processor.py::transform"], "value > 0")

    def test_negative_condition(self, all_cfgs):
        assert _has(all_cfgs["processor.py::transform"], "value < 0")

    def test_positive_result(self, all_cfgs):
        assert _has(all_cfgs["processor.py::transform"], "result = value * multiplier")

    def test_negative_result(self, all_cfgs):
        assert _has(all_cfgs["processor.py::transform"], "result = abs(value)")

    def test_zero_result(self, all_cfgs):
        assert _has(all_cfgs["processor.py::transform"], "result = 0")

    def test_return_result(self, all_cfgs):
        assert _has(all_cfgs["processor.py::transform"], "return result")


# ============================================================
# processor.py::process_data
# ============================================================

class TestProcessDataFunction:
    def test_signature(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "process_data(items, threshold=0)")

    def test_output_init(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "output = []")

    def test_error_count_init(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "error_count = 0")

    def test_for_loop(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "for item in items")

    def test_validate_call(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "validate(item)")

    def test_error_increment(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "error_count += 1")

    def test_continue(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "continue")

    def test_transform_call(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "transform(item)")

    def test_threshold_check(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "transformed >= threshold")

    def test_append(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "output.append(transformed)")

    def test_error_check(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "error_count > 0")

    def test_print_skipped(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "print(")

    def test_return_output(self, all_cfgs):
        assert _has(all_cfgs["processor.py::process_data"], "return output")

    def test_call_tree(self, all_calls):
        calls = {(c, e) for c, e in all_calls["processor.py"]["calls"]}
        assert ("process_data", "validate") in calls
        assert ("process_data", "transform") in calls


# ============================================================
# reporter.py::calculate_stats
# ============================================================

class TestCalculateStatsFunction:
    def test_signature(self, all_cfgs):
        assert _has(all_cfgs["reporter.py::calculate_stats"], "calculate_stats(data)")

    def test_empty_check(self, all_cfgs):
        assert _has(all_cfgs["reporter.py::calculate_stats"], "not data")

    def test_empty_return(self, all_cfgs):
        cfg = all_cfgs["reporter.py::calculate_stats"]
        assert any("count" in l and "0" in l and "return" in l for l in _labels(cfg))

    def test_sum(self, all_cfgs):
        assert _has(all_cfgs["reporter.py::calculate_stats"], "total = sum(data)")

    def test_len(self, all_cfgs):
        assert _has(all_cfgs["reporter.py::calculate_stats"], "count = len(data)")

    def test_avg(self, all_cfgs):
        assert _has(all_cfgs["reporter.py::calculate_stats"], "avg = total / count")

    def test_return_dict(self, all_cfgs):
        cfg = all_cfgs["reporter.py::calculate_stats"]
        assert any("count" in l and "total" in l and "return" in l for l in _labels(cfg))


# ============================================================
# reporter.py::generate_report
# ============================================================

class TestGenerateReportFunction:
    def test_signature(self, all_cfgs):
        assert _has(all_cfgs["reporter.py::generate_report"], "generate_report(data)")

    def test_lines_init(self, all_cfgs):
        assert _has(all_cfgs["reporter.py::generate_report"], "lines = [")

    def test_stats_call(self, all_cfgs):
        assert _has(all_cfgs["reporter.py::generate_report"], "calculate_stats(data)")

    def test_for_enumerate(self, all_cfgs):
        assert _has(all_cfgs["reporter.py::generate_report"], "enumerate(data)")

    def test_format_item_call(self, all_cfgs):
        assert _has(all_cfgs["reporter.py::generate_report"], "format_item(item, i)")

    def test_return_join(self, all_cfgs):
        assert _has(all_cfgs["reporter.py::generate_report"], "join(lines)")

    def test_call_tree(self, all_calls):
        calls = {(c, e) for c, e in all_calls["reporter.py"]["calls"]}
        assert ("generate_report", "calculate_stats") in calls
        assert ("generate_report", "format_item") in calls


# ============================================================
# Cross-file call tree
# ============================================================

class TestCrossFileRelations:
    def test_main_calls_process_data(self, all_calls):
        calls = {(c, e) for c, e in all_calls["main.py"]["calls"]}
        assert ("main", "process_data") in calls

    def test_main_calls_generate_report(self, all_calls):
        calls = {(c, e) for c, e in all_calls["main.py"]["calls"]}
        assert ("main", "generate_report") in calls
