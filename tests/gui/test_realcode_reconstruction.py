"""Real code reconstruction test — verify symbols.py can be fully reconstructed
from calltree + flowchart + class diagram output."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from orionparser.analysis.call_tree import extract_call_tree
from orionparser.analysis.class_diagram import extract_classes
from orionparser.analysis.control_flow import extract_control_flow

SRC = Path("src/orionparser/analysis/symbols.py")


@pytest.fixture(scope="module")
def result():
    from orionparser.registry import get_pipeline
    return get_pipeline(SRC).analyze_file(SRC)


# ============================================================
# CLASS DIAGRAM
# ============================================================

class TestSymbolDataclass:
    @pytest.fixture
    def info(self, result):
        return extract_classes(result.ast)["classes"]["Symbol"]

    def test_name(self, info):
        assert info["name"] == "Symbol"

    def test_docstring(self, info):
        assert "extracted symbol" in info["docstring"].lower()

    def test_attr_name_str(self, info):
        a = next(x for x in info["attributes"] if x["name"] == "name")
        assert a["type"] == "str"

    def test_attr_kind_str(self, info):
        a = next(x for x in info["attributes"] if x["name"] == "kind")
        assert a["type"] == "str"

    def test_attr_scope_str(self, info):
        a = next(x for x in info["attributes"] if x["name"] == "scope")
        assert a["type"] == "str"

    def test_attr_line_int_default0(self, info):
        a = next(x for x in info["attributes"] if x["name"] == "line")
        assert a["type"] == "int"
        assert "0" in a["default"]

    def test_attr_docstring_optional(self, info):
        a = next(x for x in info["attributes"] if x["name"] == "docstring")
        assert "None" in a["default"]

    def test_attr_count(self, info):
        assert len(info["attributes"]) == 5


class TestSymbolTableDataclass:
    @pytest.fixture
    def info(self, result):
        return extract_classes(result.ast)["classes"]["SymbolTable"]

    def test_name(self, info):
        assert info["name"] == "SymbolTable"

    def test_docstring(self, info):
        assert "symbols" in info["docstring"].lower()

    def test_attr_functions(self, info):
        a = next(x for x in info["attributes"] if x["name"] == "functions")
        assert "list" in a["type"].lower()

    def test_attr_classes(self, info):
        a = next(x for x in info["attributes"] if x["name"] == "classes")
        assert "list" in a["type"].lower()

    def test_attr_variables(self, info):
        assert any(x["name"] == "variables" for x in info["attributes"])

    def test_attr_imports(self, info):
        assert any(x["name"] == "imports" for x in info["attributes"])

    def test_method_all_property(self, info):
        m = next(x for x in info["methods"] if "all" in x["name"])
        assert "property" in m["name"] or m["returns"]

    def test_method_function_names(self, info):
        assert any("function_names" in m["name"] for m in info["methods"])

    def test_method_class_names(self, info):
        assert any("class_names" in m["name"] for m in info["methods"])

    def test_method_variable_names(self, info):
        m = next(x for x in info["methods"] if "variable_names" in x["name"])
        assert "scope" in m["params"]

    def test_method_import_names(self, info):
        assert any("import_names" in m["name"] for m in info["methods"])

    def test_method_to_dict(self, info):
        m = next(x for x in info["methods"] if "to_dict" in x["name"])
        assert "dict" in m["returns"]


# ============================================================
# FLOWCHARTS — key functions
# ============================================================

def _cfg(result, name):
    cf = extract_control_flow(result.ast)
    return cf["functions"].get(name)


def _has(cfg, pattern):
    return any(pattern in n["label"] for n in cfg["nodes"])


def _types(cfg):
    return [n["type"] for n in cfg["nodes"]]


class TestExtractSymbolsFlowchart:
    def test_exists(self, result):
        assert _cfg(result, "extract_symbols") is not None

    def test_signature(self, result):
        assert _has(_cfg(result, "extract_symbols"), "extract_symbols")

    def test_creates_table(self, result):
        assert _has(_cfg(result, "extract_symbols"), "table = SymbolTable()")

    def test_calls_walk(self, result):
        assert _has(_cfg(result, "extract_symbols"), "_walk(")

    def test_returns_table(self, result):
        assert _has(_cfg(result, "extract_symbols"), "return table")

    def test_is_sequential(self, result):
        """extract_symbols has no branches or loops."""
        types = _types(_cfg(result, "extract_symbols"))
        assert "decision" not in types
        assert "loop_start" not in types


class TestWalkFlowchart:
    def test_exists(self, result):
        assert _cfg(result, "_walk") is not None

    def test_has_for_loop(self, result):
        assert "loop_start" in _types(_cfg(result, "_walk"))

    def test_isinstance_check(self, result):
        assert _has(_cfg(result, "_walk"), "isinstance(node, dict)")

    def test_continue(self, result):
        assert _has(_cfg(result, "_walk"), "continue")

    def test_checks_functiondef(self, result):
        assert _has(_cfg(result, "_walk"), "FunctionDef")

    def test_checks_classdef(self, result):
        assert _has(_cfg(result, "_walk"), "ClassDef")

    def test_checks_assign(self, result):
        assert _has(_cfg(result, "_walk"), "Assign")

    def test_checks_import(self, result):
        assert _has(_cfg(result, "_walk"), "Import")

    def test_checks_importfrom(self, result):
        assert _has(_cfg(result, "_walk"), "ImportFrom")

    def test_recursive_walk(self, result):
        assert _has(_cfg(result, "_walk"), "_walk(")

    def test_calls_extract_target_name(self, result):
        assert _has(_cfg(result, "_walk"), "_extract_target_name")

    def test_creates_symbol(self, result):
        assert _has(_cfg(result, "_walk"), "Symbol(")

    def test_decision_count(self, result):
        """_walk has many if/elif checks."""
        decisions = [n for n in _cfg(result, "_walk")["nodes"] if n["type"] == "decision"]
        assert len(decisions) >= 8  # isinstance, FunctionDef, ClassDef, Assign, AnnAssign, Import, ImportFrom, If/While/For, Try


class TestExtractTargetNameFlowchart:
    def test_exists(self, result):
        assert _cfg(result, "_extract_target_name") is not None

    def test_isinstance_check(self, result):
        assert _has(_cfg(result, "_extract_target_name"), "isinstance(target, dict)")

    def test_checks_name_type(self, result):
        cfg = _cfg(result, "_extract_target_name")
        assert _has(cfg, "Name")

    def test_checks_attribute_type(self, result):
        cfg = _cfg(result, "_extract_target_name")
        assert _has(cfg, "Attribute")

    def test_recursive_call(self, result):
        assert _has(_cfg(result, "_extract_target_name"), "_extract_target_name(")

    def test_multiple_returns(self, result):
        returns = [n for n in _cfg(result, "_extract_target_name")["nodes"] if n["type"] == "return"]
        assert len(returns) >= 3  # return id, return f"{obj}.{attr}", return attr, return None

    def test_all_reachable(self, result):
        cfg = _cfg(result, "_extract_target_name")
        adj = {}
        for e in cfg["edges"]:
            adj.setdefault(e["from"], []).append(e["to"])
        start = cfg["nodes"][0]["id"]
        visited = set()
        q = [start]
        while q:
            n = q.pop(0)
            if n in visited:
                continue
            visited.add(n)
            for c in adj.get(n, []):
                q.append(c)
        assert len(visited) == len(cfg["nodes"])


class TestSymDictFlowchart:
    def test_exists(self, result):
        assert _cfg(result, "_sym_dict") is not None

    def test_creates_dict(self, result):
        cfg = _cfg(result, "_sym_dict")
        assert _has(cfg, "d = {")
        assert _has(cfg, "name")
        assert _has(cfg, "kind")
        assert _has(cfg, "scope")

    def test_docstring_check(self, result):
        cfg = _cfg(result, "_sym_dict")
        assert _has(cfg, "s.docstring is not None")

    def test_docstring_assign(self, result):
        cfg = _cfg(result, "_sym_dict")
        assert _has(cfg, "docstring")

    def test_return_d(self, result):
        assert _has(_cfg(result, "_sym_dict"), "return d")


# ============================================================
# CALL TREE
# ============================================================

class TestCallTreeRelationships:
    @pytest.fixture
    def calls(self, result):
        return {(c, e) for c, e in extract_call_tree(result.ast)["calls"]}

    def test_extract_symbols_creates_table(self, calls):
        assert ("extract_symbols", "SymbolTable") in calls

    def test_extract_symbols_calls_walk(self, calls):
        assert ("extract_symbols", "_walk") in calls

    def test_walk_calls_itself(self, calls):
        assert ("_walk", "_walk") in calls

    def test_walk_calls_extract_target(self, calls):
        assert ("_walk", "_extract_target_name") in calls

    def test_extract_target_calls_itself(self, calls):
        assert ("_extract_target_name", "_extract_target_name") in calls

    def test_walk_checks_isinstance(self, calls):
        assert ("_walk", "isinstance") in calls


# ============================================================
# CONSISTENCY
# ============================================================

class TestConsistencyRealCode:
    def test_all_class_methods_have_flowcharts(self, result):
        cd = extract_classes(result.ast)
        cf = extract_control_flow(result.ast)
        for cls_name, info in cd["classes"].items():
            for method in info["methods"]:
                mname = method["name"].replace("@property ", "")
                full = f"{cls_name}.{mname}"
                assert full in cf["functions"], f"Missing flowchart: {full}"

    def test_all_flowcharts_start_end(self, result):
        cf = extract_control_flow(result.ast)
        for name, cfg in cf["functions"].items():
            types = _types(cfg)
            assert types[0] == "start", f"{name}: no start"
            assert types[-1] == "end", f"{name}: no end"

    def test_all_flowcharts_reachable(self, result):
        cf = extract_control_flow(result.ast)
        for name, cfg in cf["functions"].items():
            adj = {}
            for e in cfg["edges"]:
                adj.setdefault(e["from"], []).append(e["to"])
            start = cfg["nodes"][0]["id"]
            visited = set()
            q = [start]
            while q:
                n = q.pop(0)
                if n in visited:
                    continue
                visited.add(n)
                for c in adj.get(n, []):
                    q.append(c)
            all_ids = {n["id"] for n in cfg["nodes"]}
            unreachable = all_ids - visited
            assert len(unreachable) == 0, f"{name}: unreachable {unreachable}"

    def test_function_count(self, result):
        cf = extract_control_flow(result.ast)
        # symbols.py has: 6 SymbolTable methods + _sym_dict + extract_symbols + _walk + _extract_target_name = 10
        assert len(cf["functions"]) == 10
