"""Massive flowchart tests — every pattern, every edge case, real code bulk.

Tests are organized by:
1. Atomic patterns (each control structure in isolation)
2. Combination patterns (2+ structures combined)
3. Real codebase bulk (every function in orion-parser source)
4. Structural invariants (graph properties that must always hold)
"""

from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from orionparser.analysis.control_flow import extract_control_flow


def _cfg(source: str, func_name: str | None = None) -> dict:
    p = Path(f"_mass_{abs(hash(source)) % 99999}.py")
    p.write_text(source, encoding="utf-8")
    try:
        from orionparser.registry import get_pipeline
        result = get_pipeline(p).analyze_file(p)
    finally:
        p.unlink(missing_ok=True)
    cf = extract_control_flow(result.ast)
    funcs = cf["functions"]
    if func_name:
        return funcs[func_name]
    return funcs[next(iter(funcs))] if funcs else {"nodes": [], "edges": []}


def _types(cfg: dict) -> list[str]:
    return [n["type"] for n in cfg["nodes"]]


def _labels(cfg: dict) -> list[str]:
    return [n["label"] for n in cfg["nodes"]]


def _edge_labels(cfg: dict) -> list[str]:
    return [e["label"] for e in cfg["edges"] if e["label"]]


def _count_type(cfg: dict, t: str) -> int:
    return sum(1 for n in cfg["nodes"] if n["type"] == t)


def _reachable_from_start(cfg: dict) -> set[str]:
    adj: dict[str, list[str]] = {}
    for e in cfg["edges"]:
        adj.setdefault(e["from"], []).append(e["to"])
    start = cfg["nodes"][0]["id"]
    visited: set[str] = set()
    q = [start]
    while q:
        n = q.pop(0)
        if n in visited:
            continue
        visited.add(n)
        for c in adj.get(n, []):
            q.append(c)
    return visited


# ============================================================
# 1. Atomic patterns — each construct in isolation
# ============================================================

class TestAtomicPass:
    def test_pass_only(self):
        cfg = _cfg("def f():\n    pass\n")
        assert _types(cfg) == ["start", "process", "end"]

    def test_pass_label(self):
        cfg = _cfg("def f():\n    pass\n")
        assert any("pass" in l for l in _labels(cfg))


class TestAtomicAssign:
    def test_single_assign(self):
        cfg = _cfg("def f():\n    x = 1\n")
        assert _count_type(cfg, "process") == 1
        assert any("x = 1" in l for l in _labels(cfg))

    def test_multiple_assign(self):
        cfg = _cfg("def f():\n    x = 1\n    y = 2\n    z = 3\n")
        assert _count_type(cfg, "process") == 3

    def test_augmented_assign(self):
        cfg = _cfg("def f():\n    x = 0\n    x += 1\n")
        assert _count_type(cfg, "process") >= 2

    def test_tuple_unpack(self):
        cfg = _cfg("def f():\n    a, b = 1, 2\n")
        assert _count_type(cfg, "process") >= 1


class TestAtomicReturn:
    def test_return_none(self):
        cfg = _cfg("def f():\n    return\n")
        assert _count_type(cfg, "return") == 1

    def test_return_value(self):
        cfg = _cfg("def f():\n    return 42\n")
        assert any("42" in l for l in _labels(cfg))

    def test_return_expr(self):
        cfg = _cfg("def f():\n    return 1 + 2\n")
        assert _count_type(cfg, "return") == 1

    def test_implicit_return(self):
        cfg = _cfg("def f():\n    x = 1\n")
        # No explicit return, should still have end
        assert _types(cfg)[-1] == "end"


class TestAtomicIfOnly:
    def test_if_no_else(self):
        cfg = _cfg("def f(x):\n    if x:\n        print(x)\n")
        assert _count_type(cfg, "decision") == 1
        assert "True" in _edge_labels(cfg)
        assert "False" in _edge_labels(cfg)

    def test_if_with_else(self):
        cfg = _cfg("def f(x):\n    if x:\n        y = 1\n    else:\n        y = 0\n")
        assert _count_type(cfg, "decision") == 1
        assert _count_type(cfg, "process") >= 2

    def test_elif(self):
        cfg = _cfg("def f(x):\n    if x > 0:\n        y = 1\n    elif x < 0:\n        y = -1\n    else:\n        y = 0\n")
        assert _count_type(cfg, "decision") >= 2

    def test_if_condition_gt(self):
        cfg = _cfg("def f(x):\n    if x > 10:\n        pass\n")
        decisions = [n for n in cfg["nodes"] if n["type"] == "decision"]
        assert any("x" in d["label"] and "10" in d["label"] for d in decisions)

    def test_if_condition_eq(self):
        cfg = _cfg("def f(x):\n    if x == 0:\n        pass\n")
        decisions = [n for n in cfg["nodes"] if n["type"] == "decision"]
        assert len(decisions) == 1

    def test_if_condition_and(self):
        cfg = _cfg("def f(x, y):\n    if x and y:\n        pass\n")
        assert _count_type(cfg, "decision") >= 1

    def test_if_condition_not(self):
        cfg = _cfg("def f(x):\n    if not x:\n        pass\n")
        assert _count_type(cfg, "decision") == 1


class TestAtomicForLoop:
    def test_for_range(self):
        cfg = _cfg("def f():\n    for i in range(5):\n        pass\n")
        assert _count_type(cfg, "loop_start") == 1
        assert _count_type(cfg, "loop_end") == 1

    def test_for_list(self):
        cfg = _cfg("def f():\n    for x in [1,2,3]:\n        pass\n")
        assert _count_type(cfg, "loop_start") == 1

    def test_for_with_body(self):
        cfg = _cfg("def f():\n    for i in range(3):\n        x = i * 2\n        print(x)\n")
        assert _count_type(cfg, "loop_start") == 1
        assert _count_type(cfg, "io") == 1
        assert _count_type(cfg, "process") >= 1

    def test_for_label_content(self):
        cfg = _cfg("def f():\n    for item in data:\n        pass\n")
        starts = [n for n in cfg["nodes"] if n["type"] == "loop_start"]
        assert any("item" in s["label"] for s in starts)

    def test_for_enumerate(self):
        cfg = _cfg("def f():\n    for i, v in enumerate(lst):\n        pass\n")
        assert _count_type(cfg, "loop_start") == 1

    def test_for_start_before_end(self):
        cfg = _cfg("def f():\n    for i in x:\n        pass\n")
        types = _types(cfg)
        assert types.index("loop_start") < types.index("loop_end")


class TestAtomicWhileLoop:
    def test_while_basic(self):
        cfg = _cfg("def f():\n    while True:\n        break\n")
        assert _count_type(cfg, "loop_start") == 1
        assert _count_type(cfg, "loop_end") == 1

    def test_while_condition(self):
        cfg = _cfg("def f(n):\n    while n > 0:\n        n -= 1\n")
        starts = [n for n in cfg["nodes"] if n["type"] == "loop_start"]
        assert any("n" in s["label"] and "0" in s["label"] for s in starts)

    def test_while_with_body(self):
        cfg = _cfg("def f():\n    x = 10\n    while x > 0:\n        x -= 1\n        print(x)\n")
        assert _count_type(cfg, "loop_start") == 1
        assert _count_type(cfg, "io") == 1


class TestAtomicIO:
    def test_print_simple(self):
        cfg = _cfg("def f():\n    print('hello')\n")
        assert _count_type(cfg, "io") == 1

    def test_print_multiple(self):
        cfg = _cfg("def f():\n    print('a')\n    print('b')\n    print('c')\n")
        assert _count_type(cfg, "io") == 3

    def test_input(self):
        cfg = _cfg("def f():\n    x = input()\n")
        # input() inside assign is process, not io
        assert _count_type(cfg, "process") >= 1

    def test_bare_input(self):
        cfg = _cfg("def f():\n    input('prompt')\n")
        assert _count_type(cfg, "io") == 1

    def test_print_with_args(self):
        cfg = _cfg("def f():\n    print(1, 2, 3)\n")
        io = [n for n in cfg["nodes"] if n["type"] == "io"]
        assert len(io) == 1
        assert "print" in io[0]["label"]


class TestAtomicTryExcept:
    def test_try_except_basic(self):
        cfg = _cfg("def f():\n    try:\n        x = 1\n    except:\n        x = 0\n")
        labels = _labels(cfg)
        assert any("try" in l for l in labels)
        assert any("except" in l for l in labels)

    def test_try_except_typed(self):
        cfg = _cfg("def f():\n    try:\n        x = 1\n    except ValueError:\n        x = 0\n")
        labels = _labels(cfg)
        assert any("except" in l for l in labels)

    def test_try_finally(self):
        cfg = _cfg("def f():\n    try:\n        x = 1\n    finally:\n        x = 0\n")
        labels = _labels(cfg)
        assert any("finally" in l for l in labels)

    def test_try_multiple_except(self):
        cfg = _cfg("def f():\n    try:\n        x = 1\n    except TypeError:\n        pass\n    except ValueError:\n        pass\n")
        excepts = [n for n in cfg["nodes"] if "except" in n.get("label", "")]
        assert len(excepts) >= 2


# ============================================================
# 2. Combination patterns
# ============================================================

class TestComboIfInFor:
    def test_if_in_for(self):
        cfg = _cfg("def f():\n    for i in range(10):\n        if i > 5:\n            print(i)\n")
        assert _count_type(cfg, "loop_start") == 1
        assert _count_type(cfg, "decision") == 1
        assert _count_type(cfg, "io") == 1

    def test_loop_wraps_decision(self):
        cfg = _cfg("def f():\n    for i in x:\n        if i:\n            pass\n")
        t = _types(cfg)
        assert t.index("loop_start") < t.index("decision") < t.index("loop_end")


class TestComboForInIf:
    def test_for_in_if(self):
        cfg = _cfg("def f(x):\n    if x:\n        for i in range(x):\n            print(i)\n")
        assert _count_type(cfg, "decision") == 1
        assert _count_type(cfg, "loop_start") == 1

    def test_for_in_else(self):
        cfg = _cfg("def f(x):\n    if x > 0:\n        pass\n    else:\n        for i in range(3):\n            print(i)\n")
        assert _count_type(cfg, "loop_start") == 1


class TestComboNestedLoops:
    def test_for_in_for(self):
        cfg = _cfg("def f():\n    for i in range(3):\n        for j in range(3):\n            print(i, j)\n")
        assert _count_type(cfg, "loop_start") == 2
        assert _count_type(cfg, "loop_end") == 2

    def test_while_in_for(self):
        cfg = _cfg("def f():\n    for i in range(5):\n        x = i\n        while x > 0:\n            x -= 1\n")
        assert _count_type(cfg, "loop_start") == 2


class TestComboNestedIfs:
    def test_if_in_if(self):
        cfg = _cfg("def f(x):\n    if x > 0:\n        if x > 10:\n            print('big')\n")
        assert _count_type(cfg, "decision") == 2

    def test_three_level_if(self):
        cfg = _cfg("def f(x):\n    if x > 0:\n        if x > 10:\n            if x > 100:\n                print('huge')\n")
        assert _count_type(cfg, "decision") == 3

    def test_if_elif_else(self):
        cfg = _cfg("def f(x):\n    if x > 0:\n        y = 1\n    elif x == 0:\n        y = 0\n    else:\n        y = -1\n")
        assert _count_type(cfg, "decision") >= 2


class TestComboReturnInBranch:
    def test_early_return_in_if(self):
        cfg = _cfg("def f(x):\n    if not x:\n        return None\n    return x\n")
        assert _count_type(cfg, "return") == 2
        assert _count_type(cfg, "decision") == 1

    def test_return_in_both_branches(self):
        cfg = _cfg("def f(x):\n    if x:\n        return 1\n    else:\n        return 0\n")
        assert _count_type(cfg, "return") == 2

    def test_return_in_loop(self):
        cfg = _cfg("def f():\n    for i in range(10):\n        if i == 5:\n            return i\n    return -1\n")
        assert _count_type(cfg, "return") == 2


class TestComboBreakContinue:
    def test_break(self):
        cfg = _cfg("def f():\n    for i in range(10):\n        if i == 5:\n            break\n")
        assert any("break" in l for l in _labels(cfg))

    def test_continue(self):
        cfg = _cfg("def f():\n    for i in range(10):\n        if i % 2 == 0:\n            continue\n        print(i)\n")
        assert any("continue" in l for l in _labels(cfg))


class TestComboTryInLoop:
    def test_try_in_for(self):
        cfg = _cfg("def f():\n    for i in range(5):\n        try:\n            x = 1 / i\n        except:\n            x = 0\n")
        assert _count_type(cfg, "loop_start") == 1
        assert any("try" in l for l in _labels(cfg))


class TestComboWithStatement:
    def test_with(self):
        cfg = _cfg("def f():\n    with open('f') as fh:\n        data = fh.read()\n")
        assert _count_type(cfg, "process") >= 2  # with + read


class TestComboComplex:
    def test_guard_clause_pattern(self):
        """Common pattern: early returns for validation."""
        cfg = _cfg(
            "def f(x):\n"
            "    if x is None:\n        return None\n"
            "    if x < 0:\n        return 0\n"
            "    return x * 2\n"
        )
        assert _count_type(cfg, "decision") == 2
        assert _count_type(cfg, "return") == 3

    def test_accumulator_pattern(self):
        cfg = _cfg(
            "def f(items):\n"
            "    result = []\n"
            "    for item in items:\n"
            "        if item > 0:\n"
            "            result.append(item)\n"
            "    return result\n"
        )
        assert _count_type(cfg, "loop_start") == 1
        assert _count_type(cfg, "decision") == 1
        assert _count_type(cfg, "return") == 1


# ============================================================
# 3. Real codebase bulk — test every function in analysis/
# ============================================================

class TestRealCodeBulk:
    """Test every function in orion-parser's analysis/ directory."""

    @pytest.fixture(scope="class")
    def all_cfgs(self):
        from orionparser.registry import get_pipeline
        analysis_dir = Path("src/orionparser/analysis")
        all_functions: dict[str, dict] = {}
        for f in sorted(analysis_dir.glob("*.py")):
            if f.name == "__init__.py":
                continue
            result = get_pipeline(f).analyze_file(f)
            if result.ast:
                cf = extract_control_flow(result.ast)
                for fname, cfg in cf["functions"].items():
                    all_functions[f"{f.stem}::{fname}"] = cfg
        return all_functions

    def test_found_functions(self, all_cfgs):
        assert len(all_cfgs) >= 10, f"Expected 10+ functions, got {len(all_cfgs)}"
        print(f"  Found {len(all_cfgs)} functions")

    def test_all_have_start_and_end(self, all_cfgs):
        for name, cfg in all_cfgs.items():
            types = _types(cfg)
            assert types[0] == "start", f"{name}: first node is {types[0]}, expected start"
            assert types[-1] == "end", f"{name}: last node is {types[-1]}, expected end"

    def test_all_nodes_reachable(self, all_cfgs):
        for name, cfg in all_cfgs.items():
            reachable = _reachable_from_start(cfg)
            all_ids = {n["id"] for n in cfg["nodes"]}
            unreachable = all_ids - reachable
            assert len(unreachable) == 0, f"{name}: unreachable nodes {unreachable}"

    def test_no_orphan_edges(self, all_cfgs):
        for name, cfg in all_cfgs.items():
            node_ids = {n["id"] for n in cfg["nodes"]}
            for e in cfg["edges"]:
                assert e["from"] in node_ids, f"{name}: edge from unknown {e['from']}"
                assert e["to"] in node_ids, f"{name}: edge to unknown {e['to']}"

    def test_all_have_at_least_2_nodes(self, all_cfgs):
        for name, cfg in all_cfgs.items():
            assert len(cfg["nodes"]) >= 2, f"{name}: only {len(cfg['nodes'])} nodes"

    def test_edge_count_reasonable(self, all_cfgs):
        for name, cfg in all_cfgs.items():
            n = len(cfg["nodes"])
            e = len(cfg["edges"])
            assert e >= n - 1, f"{name}: too few edges ({e}) for {n} nodes"
            assert e <= n * 3, f"{name}: too many edges ({e}) for {n} nodes"

    def test_decision_always_has_true_edge(self, all_cfgs):
        for name, cfg in all_cfgs.items():
            for node in cfg["nodes"]:
                if node["type"] == "decision":
                    out_labels = {e["label"] for e in cfg["edges"] if e["from"] == node["id"]}
                    assert "True" in out_labels, f"{name}: decision {node['id']} missing True edge"

    def test_loop_start_always_has_matching_end(self, all_cfgs):
        for name, cfg in all_cfgs.items():
            starts = _count_type(cfg, "loop_start")
            ends = _count_type(cfg, "loop_end")
            assert starts == ends, f"{name}: {starts} loop_starts but {ends} loop_ends"


# ============================================================
# 4. Real codebase bulk — test every function in gui/panels/
# ============================================================

class TestRealCodeGUI:
    @pytest.fixture(scope="class")
    def gui_cfgs(self):
        from orionparser.registry import get_pipeline
        panels_dir = Path("src/orionparser/gui/panels")
        all_functions: dict[str, dict] = {}
        for f in sorted(panels_dir.rglob("*.py")):
            if f.name == "__init__.py":
                continue
            result = get_pipeline(f).analyze_file(f)
            if result.ast:
                cf = extract_control_flow(result.ast)
                for fname, cfg in cf["functions"].items():
                    all_functions[f"{f.stem}::{fname}"] = cfg
        return all_functions

    def test_found_gui_functions(self, gui_cfgs):
        assert len(gui_cfgs) >= 1, f"Expected at least 1 function, got {len(gui_cfgs)}"
        print(f"  Found {len(gui_cfgs)} GUI panel functions")

    def test_all_start_end(self, gui_cfgs):
        for name, cfg in gui_cfgs.items():
            t = _types(cfg)
            assert t[0] == "start" and t[-1] == "end", f"{name}: bad start/end"

    def test_all_reachable(self, gui_cfgs):
        for name, cfg in gui_cfgs.items():
            r = _reachable_from_start(cfg)
            assert len(r) == len(cfg["nodes"]), f"{name}: unreachable nodes"


# ============================================================
# 5. Structural invariants
# ============================================================

class TestInvariants:
    """Properties that must hold for ANY valid source code."""

    SOURCES = [
        "def f(): pass",
        "def f(): return 1",
        "def f(x):\n    if x: return 1\n    return 0",
        "def f():\n    for i in range(3): print(i)",
        "def f():\n    while True: break",
        "def f():\n    x = 1\n    y = 2\n    z = x + y\n    return z",
        "def f(x):\n    if x > 0:\n        for i in range(x):\n            if i % 2:\n                print(i)\n    return x",
        "def f():\n    try:\n        x = 1\n    except:\n        x = 0\n    return x",
        "def f():\n    for i in range(3):\n        for j in range(3):\n            for k in range(3):\n                pass",
        "def f(a,b,c):\n    if a:\n        if b:\n            if c:\n                return 1\n    return 0",
    ]

    @pytest.mark.parametrize("source", SOURCES, ids=[f"src_{i}" for i in range(len(SOURCES))])
    def test_starts_with_start(self, source):
        cfg = _cfg(source)
        assert cfg["nodes"][0]["type"] == "start"

    @pytest.mark.parametrize("source", SOURCES, ids=[f"src_{i}" for i in range(len(SOURCES))])
    def test_ends_with_end(self, source):
        cfg = _cfg(source)
        assert cfg["nodes"][-1]["type"] == "end"

    @pytest.mark.parametrize("source", SOURCES, ids=[f"src_{i}" for i in range(len(SOURCES))])
    def test_all_reachable(self, source):
        cfg = _cfg(source)
        r = _reachable_from_start(cfg)
        assert len(r) == len(cfg["nodes"])

    @pytest.mark.parametrize("source", SOURCES, ids=[f"src_{i}" for i in range(len(SOURCES))])
    def test_no_self_loops(self, source):
        cfg = _cfg(source)
        for e in cfg["edges"]:
            assert e["from"] != e["to"], f"Self-loop: {e}"

    @pytest.mark.parametrize("source", SOURCES, ids=[f"src_{i}" for i in range(len(SOURCES))])
    def test_loop_pairs_match(self, source):
        cfg = _cfg(source)
        assert _count_type(cfg, "loop_start") == _count_type(cfg, "loop_end")

    @pytest.mark.parametrize("source", SOURCES, ids=[f"src_{i}" for i in range(len(SOURCES))])
    def test_at_least_2_nodes(self, source):
        cfg = _cfg(source)
        assert len(cfg["nodes"]) >= 2
