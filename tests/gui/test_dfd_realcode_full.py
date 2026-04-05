"""Comprehensive DFD real code tests — every analysis/ file, every function."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from orionparser.analysis.dfd import extract_dfd

ANALYSIS_DIR = Path("src/orionparser/analysis")


@pytest.fixture(scope="module")
def all_dfds():
    from orionparser.registry import get_pipeline
    results = {}
    for f in sorted(ANALYSIS_DIR.glob("*.py")):
        if f.name == "__init__.py":
            continue
        result = get_pipeline(f).analyze_file(f)
        results[f.stem] = extract_dfd(result.ast)
    return results


# ============================================================
# symbols.py
# ============================================================

class TestSymbolsDFD:
    @pytest.fixture
    def dfd(self, all_dfds):
        return all_dfds["symbols"]

    def test_extract_symbols_param_ast(self, dfd):
        assert "ast" in dfd["functions"]["extract_symbols"]["params"]

    def test_extract_symbols_var_table(self, dfd):
        assert "table" in dfd["functions"]["extract_symbols"]["variables"]

    def test_extract_symbols_table_from_symboltable(self, dfd):
        v = dfd["functions"]["extract_symbols"]["variables"]["table"]
        assert any("SymbolTable" in d["expr"] for d in v["defined_at"])

    def test_extract_symbols_returns_table(self, dfd):
        assert "table" in dfd["functions"]["extract_symbols"]["returns"]

    def test_extract_symbols_calls_walk(self, dfd):
        assert any("_walk" in c["func"] for c in dfd["functions"]["extract_symbols"]["calls"])

    def test_extract_symbols_table_passed_to_walk(self, dfd):
        v = dfd["functions"]["extract_symbols"]["variables"]["table"]
        assert any("_walk" in p["func"] for p in v["passed_to"])

    def test_walk_params(self, dfd):
        p = dfd["functions"]["_walk"]["params"]
        assert set(p) >= {"body", "table", "scope"}

    def test_walk_has_node_type(self, dfd):
        assert "node_type" in dfd["functions"]["_walk"]["variables"]

    def test_walk_has_name(self, dfd):
        assert "name" in dfd["functions"]["_walk"]["variables"]

    def test_walk_has_var_name(self, dfd):
        assert "var_name" in dfd["functions"]["_walk"]["variables"]

    def test_walk_calls_extract_target(self, dfd):
        assert any("_extract_target_name" in c["func"] for c in dfd["functions"]["_walk"]["calls"])

    def test_walk_recursive(self, dfd):
        assert any("_walk" in c["func"] for c in dfd["functions"]["_walk"]["calls"])

    def test_sym_dict_param_s(self, dfd):
        assert "s" in dfd["functions"]["_sym_dict"]["params"]

    def test_sym_dict_var_d(self, dfd):
        assert "d" in dfd["functions"]["_sym_dict"]["variables"]

    def test_sym_dict_returns_d(self, dfd):
        assert "d" in dfd["functions"]["_sym_dict"]["returns"]

    def test_extract_target_param(self, dfd):
        assert "target" in dfd["functions"]["_extract_target_name"]["params"]

    def test_extract_target_vars(self, dfd):
        v = dfd["functions"]["_extract_target_name"]["variables"]
        assert "obj" in v
        assert "attr" in v

    def test_extract_target_recursive(self, dfd):
        assert any("_extract_target_name" in c["func"]
                    for c in dfd["functions"]["_extract_target_name"]["calls"])

    def test_cross_flows_exist(self, dfd):
        assert len(dfd["cross_function_flows"]) > 0

    def test_cross_flow_extract_to_walk(self, dfd):
        assert any(f["from_func"] == "extract_symbols" and f["to_func"] == "_walk"
                    for f in dfd["cross_function_flows"])


# ============================================================
# call_tree.py
# ============================================================

class TestCallTreeDFD:
    @pytest.fixture
    def dfd(self, all_dfds):
        return all_dfds["call_tree"]

    def test_extract_call_tree_param(self, dfd):
        assert "ast" in dfd["functions"]["extract_call_tree"]["params"]

    def test_extract_call_tree_returns_result(self, dfd):
        assert "result" in dfd["functions"]["extract_call_tree"]["returns"]

    def test_extract_call_tree_calls_walk_module(self, dfd):
        assert any("_walk_module" in c["func"]
                    for c in dfd["functions"]["extract_call_tree"]["calls"])

    def test_walk_module_params(self, dfd):
        p = dfd["functions"]["_walk_module"]["params"]
        assert set(p) >= {"node", "functions", "calls", "scope"}

    def test_walk_module_has_node_type(self, dfd):
        assert "node_type" in dfd["functions"]["_walk_module"]["variables"]

    def test_walk_module_has_name(self, dfd):
        assert "name" in dfd["functions"]["_walk_module"]["variables"]

    def test_walk_module_recursive(self, dfd):
        assert any("_walk_module" in c["func"]
                    for c in dfd["functions"]["_walk_module"]["calls"])

    def test_resolve_callee_param(self, dfd):
        assert "func_node" in dfd["functions"]["_resolve_callee"]["params"]

    def test_resolve_callee_vars(self, dfd):
        v = dfd["functions"]["_resolve_callee"]["variables"]
        assert "obj" in v or "attr" in v

    def test_resolve_callee_recursive(self, dfd):
        assert any("_resolve_callee" in c["func"]
                    for c in dfd["functions"]["_resolve_callee"]["calls"])

    def test_cross_flows(self, dfd):
        assert len(dfd["cross_function_flows"]) > 0


# ============================================================
# control_flow.py
# ============================================================

class TestControlFlowDFD:
    @pytest.fixture
    def dfd(self, all_dfds):
        return all_dfds["control_flow"]

    def test_extract_cf_returns_result(self, dfd):
        assert "result" in dfd["functions"]["extract_control_flow"]["returns"]

    def test_extract_cf_calls_walk_for_functions(self, dfd):
        assert any("_walk_for_functions" in c["func"]
                    for c in dfd["functions"]["extract_control_flow"]["calls"])

    def test_walk_for_functions_params(self, dfd):
        p = dfd["functions"]["_walk_for_functions"]["params"]
        assert set(p) >= {"body", "result", "prefix"}

    def test_walk_for_functions_calls_build_cfg(self, dfd):
        assert any("_build_cfg" in c["func"]
                    for c in dfd["functions"]["_walk_for_functions"]["calls"])

    def test_build_cfg_params(self, dfd):
        p = dfd["functions"]["_build_cfg"]["params"]
        assert "func_name" in p
        assert "body" in p

    def test_build_cfg_creates_builder(self, dfd):
        v = dfd["functions"]["_build_cfg"]["variables"]
        assert "builder" in v

    def test_build_cfg_calls_cfgbuilder(self, dfd):
        assert any("_CfgBuilder" in c["func"]
                    for c in dfd["functions"]["_build_cfg"]["calls"])

    def test_process_body_params(self, dfd):
        p = dfd["functions"]["_CfgBuilder.process_body"]["params"]
        assert "body" in p
        assert "entry_id" in p

    def test_process_body_has_prev(self, dfd):
        assert "prev" in dfd["functions"]["_CfgBuilder.process_body"]["variables"]

    def test_process_body_returns_prev(self, dfd):
        assert "prev" in dfd["functions"]["_CfgBuilder.process_body"]["returns"]

    def test_process_if_params(self, dfd):
        p = dfd["functions"]["_CfgBuilder._process_if"]["params"]
        assert set(p) >= {"node", "prev", "line"}

    def test_process_if_has_cond(self, dfd):
        assert "cond" in dfd["functions"]["_CfgBuilder._process_if"]["variables"]

    def test_process_if_has_dec_id(self, dfd):
        assert "dec_id" in dfd["functions"]["_CfgBuilder._process_if"]["variables"]

    def test_process_for_params(self, dfd):
        p = dfd["functions"]["_CfgBuilder._process_for"]["params"]
        assert set(p) >= {"node", "prev", "line"}

    def test_process_for_has_label(self, dfd):
        assert "label" in dfd["functions"]["_CfgBuilder._process_for"]["variables"]

    def test_expr_param(self, dfd):
        assert "node" in dfd["functions"]["_expr"]["params"]

    def test_expr_has_t(self, dfd):
        assert "t" in dfd["functions"]["_expr"]["variables"]

    def test_call_args_param(self, dfd):
        assert "node" in dfd["functions"]["_call_args"]["params"]

    def test_call_args_has_parts(self, dfd):
        assert "parts" in dfd["functions"]["_call_args"]["variables"]

    def test_func_signature_param(self, dfd):
        assert "node" in dfd["functions"]["_func_signature"]["params"]

    def test_cross_flows(self, dfd):
        assert len(dfd["cross_function_flows"]) > 10


# ============================================================
# data_flow.py
# ============================================================

class TestDataFlowDFD:
    @pytest.fixture
    def dfd(self, all_dfds):
        return all_dfds["data_flow"]

    def test_extract_data_flow_param(self, dfd):
        assert "ast" in dfd["functions"]["extract_data_flow"]["params"]

    def test_extract_data_flow_returns(self, dfd):
        assert "result" in dfd["functions"]["extract_data_flow"]["returns"]

    def test_extract_data_flow_calls_walk(self, dfd):
        assert any("_walk" in c["func"]
                    for c in dfd["functions"]["extract_data_flow"]["calls"])

    def test_walk_params(self, dfd):
        p = dfd["functions"]["_walk"]["params"]
        assert set(p) >= {"node", "variables", "flows", "scope"}

    def test_walk_has_node_type(self, dfd):
        assert "node_type" in dfd["functions"]["_walk"]["variables"]

    def test_collect_names_param(self, dfd):
        assert "node" in dfd["functions"]["_collect_names"]["params"]

    def test_collect_names_has_names(self, dfd):
        assert "names" in dfd["functions"]["_collect_names"]["variables"]


# ============================================================
# dfd.py (self-referential test)
# ============================================================

class TestDfdSelfDFD:
    @pytest.fixture
    def dfd(self, all_dfds):
        return all_dfds["dfd"]

    def test_extract_dfd_returns(self, dfd):
        assert "result" in dfd["functions"]["extract_dfd"]["returns"]

    def test_extract_dfd_calls_walk_module(self, dfd):
        assert any("_walk_module" in c["func"]
                    for c in dfd["functions"]["extract_dfd"]["calls"])

    def test_analyze_function_param(self, dfd):
        assert "func_node" in dfd["functions"]["_analyze_function"]["params"]

    def test_walk_body_params(self, dfd):
        p = dfd["functions"]["_walk_body"]["params"]
        assert set(p) >= {"body", "variables", "calls"}

    def test_compute_cross_flows_param(self, dfd):
        assert "result" in dfd["functions"]["_compute_cross_flows"]["params"]

    def test_target_name_recursive(self, dfd):
        assert any("_target_name" in c["func"]
                    for c in dfd["functions"]["_target_name"]["calls"])

    def test_expr_str_param(self, dfd):
        assert "node" in dfd["functions"]["_expr_str"]["params"]


# ============================================================
# Structural invariants across ALL files
# ============================================================

class TestDFDInvariants:
    def test_all_functions_have_params_list(self, all_dfds):
        for file_name, dfd in all_dfds.items():
            for fname, finfo in dfd["functions"].items():
                assert isinstance(finfo["params"], list), f"{file_name}::{fname}: params not list"

    def test_all_functions_have_returns_list(self, all_dfds):
        for file_name, dfd in all_dfds.items():
            for fname, finfo in dfd["functions"].items():
                assert isinstance(finfo["returns"], list), f"{file_name}::{fname}: returns not list"

    def test_all_variables_have_defined_used(self, all_dfds):
        for file_name, dfd in all_dfds.items():
            for fname, finfo in dfd["functions"].items():
                for vname, vinfo in finfo["variables"].items():
                    assert "defined_at" in vinfo, f"{file_name}::{fname}::{vname}: no defined_at"
                    assert "used_at" in vinfo, f"{file_name}::{fname}::{vname}: no used_at"
                    assert "passed_to" in vinfo, f"{file_name}::{fname}::{vname}: no passed_to"

    def test_all_calls_have_func_and_args(self, all_dfds):
        for file_name, dfd in all_dfds.items():
            for fname, finfo in dfd["functions"].items():
                for call in finfo["calls"]:
                    assert "func" in call, f"{file_name}::{fname}: call missing func"
                    assert "args" in call, f"{file_name}::{fname}: call missing args"

    def test_cross_flows_have_required_fields(self, all_dfds):
        for file_name, dfd in all_dfds.items():
            for flow in dfd["cross_function_flows"]:
                assert "from_func" in flow
                assert "from_var" in flow
                assert "to_func" in flow
                assert "to_param" in flow

    def test_total_functions_reasonable(self, all_dfds):
        total = sum(len(d["functions"]) for d in all_dfds.values())
        assert total >= 20, f"Expected 20+ functions across all files, got {total}"

    def test_total_cross_flows_reasonable(self, all_dfds):
        total = sum(len(d["cross_function_flows"]) for d in all_dfds.values())
        assert total >= 50, f"Expected 50+ cross flows, got {total}"


# ============================================================
# GUI rendering for ALL analysis files
# ============================================================

class TestDFDGUIAllFiles:
    def test_render_all_analysis_files(self, qtbot):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.dfd_panel import DFDPanel
        from orionparser.registry import get_pipeline

        rendered = 0
        for f in sorted(ANALYSIS_DIR.glob("*.py")):
            if f.name == "__init__.py":
                continue
            result = get_pipeline(f).analyze_file(f)
            panel = DFDPanel()
            graph = panel.build_graph(result)
            if graph is None:
                continue
            colors = panel.get_node_colors(graph)
            canvas = GraphCanvas()
            qtbot.addWidget(canvas)
            canvas.set_graph(graph, layout="dfd", node_colors=colors)
            rendered += 1

        assert rendered >= 4, f"Only rendered {rendered} files"

    def test_export_all_functions(self, qtbot, tmp_path):
        from orionparser.gui.widgets.graph_canvas import GraphCanvas
        from orionparser.gui.panels.graph_panels.dfd_panel import DFDPanel
        from orionparser.registry import get_pipeline

        # Use symbols.py
        result = get_pipeline(ANALYSIS_DIR / "symbols.py").analyze_file(ANALYSIS_DIR / "symbols.py")
        panel = DFDPanel()
        panel.build_graph(result)

        exported = 0
        for fname in panel.get_function_names():
            graph = panel.build_for_function(fname)
            if graph is None or len(graph.nodes) == 0:
                continue
            colors = panel.get_node_colors(graph)
            canvas = GraphCanvas()
            qtbot.addWidget(canvas)
            canvas.set_graph(graph, layout="dfd", node_colors=colors)
            out = tmp_path / f"dfd_{fname.replace('.', '_')}.png"
            ok = canvas.export_png_from_scene(str(out))
            if ok:
                exported += 1

        assert exported >= 3, f"Only exported {exported} functions"
