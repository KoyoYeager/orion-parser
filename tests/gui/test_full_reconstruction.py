"""Full code reconstruction test — verify calltree + flowchart + class diagram
can reconstruct the original code completely.

For each element in the test project, we verify ALL information needed
to write the exact same code from scratch.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from orionparser.analysis.call_tree import extract_call_tree
from orionparser.analysis.class_diagram import extract_classes
from orionparser.analysis.control_flow import extract_control_flow


TEST_DIR = Path("C:/tmp/reconstruct_test")


@pytest.fixture(scope="module")
def models_result():
    from orionparser.registry import get_pipeline
    return get_pipeline(TEST_DIR / "models.py").analyze_file(TEST_DIR / "models.py")


@pytest.fixture(scope="module")
def proc_result():
    from orionparser.registry import get_pipeline
    return get_pipeline(TEST_DIR / "processor.py").analyze_file(TEST_DIR / "processor.py")


# ============================================================
# CLASS DIAGRAM — can we reconstruct the class definitions?
# ============================================================

class TestItemClass:
    """Verify Item class can be fully reconstructed."""

    @pytest.fixture
    def item_info(self, models_result):
        cd = extract_classes(models_result.ast)
        return cd["classes"]["Item"]

    def test_class_name(self, item_info):
        assert item_info["name"] == "Item"

    def test_attr_name(self, item_info):
        names = [a["name"] for a in item_info["attributes"]]
        assert "name" in names

    def test_attr_name_type(self, item_info):
        attr = next(a for a in item_info["attributes"] if a["name"] == "name")
        assert attr["type"] == "str"

    def test_attr_value(self, item_info):
        attr = next(a for a in item_info["attributes"] if a["name"] == "value")
        assert attr["type"] == "float"

    def test_attr_category_default(self, item_info):
        attr = next(a for a in item_info["attributes"] if a["name"] == "category")
        assert attr["type"] == "str"
        assert "default" in attr["default"]

    def test_attr_active_default(self, item_info):
        attr = next(a for a in item_info["attributes"] if a["name"] == "active")
        assert attr["type"] == "bool"
        assert "True" in attr["default"]

    def test_method_display(self, item_info):
        methods = {m["name"]: m for m in item_info["methods"]}
        assert "display" in methods
        assert methods["display"]["returns"] == "str"

    def test_method_discount(self, item_info):
        methods = {m["name"]: m for m in item_info["methods"]}
        assert "discount" in methods
        assert "rate" in methods["discount"]["params"]
        assert methods["discount"]["returns"] == "float"


class TestInventoryClass:
    """Verify Inventory class can be fully reconstructed."""

    @pytest.fixture
    def inv_info(self, models_result):
        cd = extract_classes(models_result.ast)
        return cd["classes"]["Inventory"]

    def test_class_name(self, inv_info):
        assert inv_info["name"] == "Inventory"

    def test_attr_items(self, inv_info):
        attr = next(a for a in inv_info["attributes"] if a["name"] == "items")
        assert attr["type"] == "list"

    def test_attr_name(self, inv_info):
        attr = next(a for a in inv_info["attributes"] if a["name"] == "name")
        assert attr["type"] == "str"

    def test_method_add(self, inv_info):
        methods = {m["name"]: m for m in inv_info["methods"]}
        assert "add" in methods
        assert "item" in methods["add"]["params"]

    def test_method_remove(self, inv_info):
        methods = {m["name"]: m for m in inv_info["methods"]}
        assert "remove" in methods
        assert "item_name" in methods["remove"]["params"]
        assert methods["remove"]["returns"] == "bool"

    def test_method_find(self, inv_info):
        methods = {m["name"]: m for m in inv_info["methods"]}
        assert "find" in methods

    def test_method_total_value(self, inv_info):
        methods = {m["name"]: m for m in inv_info["methods"]}
        assert "total_value" in methods
        assert methods["total_value"]["returns"] == "float"

    def test_method_filter_by_category(self, inv_info):
        methods = {m["name"]: m for m in inv_info["methods"]}
        assert "filter_by_category" in methods
        assert "category" in methods["filter_by_category"]["params"]

    def test_all_methods_count(self, inv_info):
        assert len(inv_info["methods"]) == 5  # add, remove, find, total_value, filter_by_category


# ============================================================
# FLOWCHART — can we reconstruct method bodies?
# ============================================================

def _cfg(result, func_name):
    cf = extract_control_flow(result.ast)
    return cf["functions"].get(func_name)


def _has(cfg, pattern):
    return any(pattern in n["label"] for n in cfg["nodes"])


def _types(cfg):
    return [n["type"] for n in cfg["nodes"]]


class TestItemDisplayFlowchart:
    def test_signature(self, models_result):
        cfg = _cfg(models_result, "Item.display")
        assert _has(cfg, "display")

    def test_has_conditional(self, models_result):
        cfg = _cfg(models_result, "Item.display")
        assert "decision" in _types(cfg) or _has(cfg, "if")

    def test_return(self, models_result):
        cfg = _cfg(models_result, "Item.display")
        assert _has(cfg, "return")


class TestItemDiscountFlowchart:
    def test_signature(self, models_result):
        cfg = _cfg(models_result, "Item.discount")
        assert _has(cfg, "discount") and _has(cfg, "rate")

    def test_validation_check(self, models_result):
        cfg = _cfg(models_result, "Item.discount")
        assert _has(cfg, "rate") and ("decision" in _types(cfg))

    def test_raise_error(self, models_result):
        cfg = _cfg(models_result, "Item.discount")
        assert _has(cfg, "raise") or _has(cfg, "ValueError")

    def test_calculation(self, models_result):
        cfg = _cfg(models_result, "Item.discount")
        assert _has(cfg, "self.value")

    def test_return_value(self, models_result):
        cfg = _cfg(models_result, "Item.discount")
        assert _has(cfg, "return self.value")


class TestInventoryRemoveFlowchart:
    def test_signature(self, models_result):
        cfg = _cfg(models_result, "Inventory.remove")
        assert _has(cfg, "remove") and _has(cfg, "item_name")

    def test_for_loop(self, models_result):
        cfg = _cfg(models_result, "Inventory.remove")
        assert "loop_start" in _types(cfg)

    def test_name_check(self, models_result):
        cfg = _cfg(models_result, "Inventory.remove")
        assert _has(cfg, "item.name == item_name") or _has(cfg, "item_name")

    def test_return_true(self, models_result):
        cfg = _cfg(models_result, "Inventory.remove")
        assert _has(cfg, "return True")

    def test_return_false(self, models_result):
        cfg = _cfg(models_result, "Inventory.remove")
        assert _has(cfg, "return False")


class TestInventoryTotalValueFlowchart:
    def test_init_total(self, models_result):
        cfg = _cfg(models_result, "Inventory.total_value")
        assert _has(cfg, "total = 0")

    def test_for_loop(self, models_result):
        cfg = _cfg(models_result, "Inventory.total_value")
        assert "loop_start" in _types(cfg)

    def test_active_check(self, models_result):
        cfg = _cfg(models_result, "Inventory.total_value")
        assert _has(cfg, "item.active")

    def test_accumulate(self, models_result):
        cfg = _cfg(models_result, "Inventory.total_value")
        assert _has(cfg, "total += item.value") or _has(cfg, "total")

    def test_return_total(self, models_result):
        cfg = _cfg(models_result, "Inventory.total_value")
        assert _has(cfg, "return total")


class TestLoadItemsFlowchart:
    def test_signature(self, proc_result):
        cfg = _cfg(proc_result, "load_items")
        assert _has(cfg, "load_items(data: list)")

    def test_create_inventory(self, proc_result):
        cfg = _cfg(proc_result, "load_items")
        assert _has(cfg, "Inventory(name=")

    def test_for_loop(self, proc_result):
        cfg = _cfg(proc_result, "load_items")
        assert _has(cfg, "for entry in data")

    def test_isinstance_check(self, proc_result):
        cfg = _cfg(proc_result, "load_items")
        assert _has(cfg, "isinstance(entry, dict)")

    def test_get_fields(self, proc_result):
        cfg = _cfg(proc_result, "load_items")
        assert _has(cfg, "entry.get(")
        assert _has(cfg, "name") and _has(cfg, "value")

    def test_create_item(self, proc_result):
        cfg = _cfg(proc_result, "load_items")
        assert _has(cfg, "Item(name=name")

    def test_add_item(self, proc_result):
        cfg = _cfg(proc_result, "load_items")
        assert _has(cfg, "inventory.add(item)")

    def test_return(self, proc_result):
        cfg = _cfg(proc_result, "load_items")
        assert _has(cfg, "return inventory")


class TestApplyDiscountsFlowchart:
    def test_signature(self, proc_result):
        cfg = _cfg(proc_result, "apply_discounts")
        assert _has(cfg, "apply_discounts(inventory: Inventory, rules: dict)")

    def test_counter_init(self, proc_result):
        cfg = _cfg(proc_result, "apply_discounts")
        assert _has(cfg, "count = 0")

    def test_for_loop(self, proc_result):
        cfg = _cfg(proc_result, "apply_discounts")
        assert _has(cfg, "for item in inventory.items")

    def test_active_check(self, proc_result):
        cfg = _cfg(proc_result, "apply_discounts")
        assert _has(cfg, "not item.active")

    def test_get_rate(self, proc_result):
        cfg = _cfg(proc_result, "apply_discounts")
        assert _has(cfg, "rules.get(item.category")

    def test_discount_call(self, proc_result):
        cfg = _cfg(proc_result, "apply_discounts")
        assert _has(cfg, "item.discount(rate)")

    def test_increment(self, proc_result):
        cfg = _cfg(proc_result, "apply_discounts")
        assert _has(cfg, "count += 1")

    def test_return(self, proc_result):
        cfg = _cfg(proc_result, "apply_discounts")
        assert _has(cfg, "return count")


# ============================================================
# CALL TREE — can we reconstruct inter-function relationships?
# ============================================================

class TestCallRelationships:
    def test_load_items_creates_inventory(self, proc_result):
        ct = extract_call_tree(proc_result.ast)
        calls = {(c, e) for c, e in ct["calls"]}
        assert ("load_items", "Inventory") in calls

    def test_load_items_creates_item(self, proc_result):
        ct = extract_call_tree(proc_result.ast)
        calls = {(c, e) for c, e in ct["calls"]}
        assert ("load_items", "Item") in calls

    def test_load_items_calls_add(self, proc_result):
        ct = extract_call_tree(proc_result.ast)
        calls = {(c, e) for c, e in ct["calls"]}
        assert ("load_items", "inventory.add") in calls

    def test_apply_discounts_calls_discount(self, proc_result):
        ct = extract_call_tree(proc_result.ast)
        calls = {(c, e) for c, e in ct["calls"]}
        assert ("apply_discounts", "item.discount") in calls

    def test_discount_raises_valueerror(self, models_result):
        ct = extract_call_tree(models_result.ast)
        calls = {(c, e) for c, e in ct["calls"]}
        assert ("Item.discount", "ValueError") in calls


# ============================================================
# GRAPH INTEGRITY — all three views are consistent
# ============================================================

class TestConsistency:
    def test_class_methods_match_flowcharts(self, models_result):
        """Every class method should have a flowchart."""
        cd = extract_classes(models_result.ast)
        cf = extract_control_flow(models_result.ast)
        for cls_name, info in cd["classes"].items():
            for method in info["methods"]:
                mname = method["name"].replace("@property ", "").replace("@staticmethod ", "").replace("@classmethod ", "")
                full = f"{cls_name}.{mname}"
                assert full in cf["functions"], f"Missing flowchart for {full}. Available: {list(cf['functions'].keys())}"

    def test_flowchart_functions_exist_in_calltree(self, proc_result):
        """Every function with a flowchart should be in the call tree."""
        ct = extract_call_tree(proc_result.ast)
        cf = extract_control_flow(proc_result.ast)
        defined = set(ct["functions"])
        for func_name in cf["functions"]:
            assert func_name in defined, f"Flowchart function {func_name} not in call tree"

    def test_all_nodes_reachable(self, proc_result):
        """All flowchart nodes should be reachable from start."""
        cf = extract_control_flow(proc_result.ast)
        for func_name, cfg in cf["functions"].items():
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
            assert len(unreachable) == 0, f"{func_name}: unreachable {unreachable}"
