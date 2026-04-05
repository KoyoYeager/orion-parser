"""Call tree graph panel — shows only defined functions with docstring tooltips."""

from __future__ import annotations

from typing import Any

from orionparser.gui.panels.graph_panels.base_graph import BaseGraphPanel

try:
    import networkx as nx

    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


class CallTreePanel(BaseGraphPanel):
    """Builds a call tree of defined functions only (no builtins/method calls)."""

    graph_id = "call_tree"
    graph_name = "コールツリー"
    default_layout = "tree"

    def _build_tree_from_calls(
        self,
        functions: list[str],
        calls: list[tuple[str, str]],
        docstrings: dict[str, str] | None = None,
        file_map: dict[str, str] | None = None,
        multi_file: bool = False,
    ) -> Any:
        if not HAS_NETWORKX:
            return None

        defined = set(functions) | {"<module>"}
        docs = docstrings or {}

        # Filter: only keep edges where BOTH caller and callee are defined functions
        filtered_calls = [(c, e) for c, e in calls if c in defined and e in defined]

        # Count calls
        call_count: dict[str, int] = {}
        for _, callee in filtered_calls:
            call_count[callee] = call_count.get(callee, 0) + 1

        # Adjacency (deduplicated per parent, preserving order)
        children: dict[str, list[str]] = {}
        for caller, callee in filtered_calls:
            if caller not in children:
                children[caller] = []
            children[caller] = children[caller] + [callee]
        for parent in children:
            seen_set: set[str] = set()
            deduped: list[str] = []
            for c in children[parent]:
                if c not in seen_set:
                    seen_set.add(c)
                    deduped = deduped + [c]
            children[parent] = deduped

        # Ensure all defined functions are reachable from <module>
        reachable: set[str] = set()

        def _mark(name: str, visited: set[str]) -> None:
            if name in visited:
                return
            visited.add(name)
            reachable.add(name)
            for child in children.get(name, []):
                _mark(child, visited)

        _mark("<module>", set())

        for func in functions:
            if func not in reachable:
                if "<module>" not in children:
                    children["<module>"] = []
                children["<module>"] = children["<module>"] + [func]

        # Build expanded tree
        tree = nx.DiGraph()
        node_counter: dict[str, int] = {}
        node_order: list[str] = []
        MAX_DEPTH = 20

        def _uid(name: str) -> str:
            node_counter[name] = node_counter.get(name, 0) + 1
            count = node_counter[name]
            return name if count == 1 else f"{name} #{count}"

        def _expand(func_name: str, depth: int, ancestors: frozenset[str]) -> str:
            uid = _uid(func_name)
            cc = call_count.get(func_name, 0)
            ffile = (file_map or {}).get(func_name, "")
            doc = docs.get(func_name, "")

            # Label: just the function name
            label = func_name
            if cc > 1:
                label = f"{func_name} (x{cc})"

            tree.add_node(uid, label=label, func_name=func_name,
                          depth=depth, call_count=cc, file=ffile, docstring=doc)
            node_order.append(uid)

            if depth < MAX_DEPTH and func_name not in ancestors:
                new_ancestors = ancestors | {func_name}
                for child_name in children.get(func_name, []):
                    child_uid = _expand(child_name, depth + 1, new_ancestors)
                    tree.add_edge(uid, child_uid)
            return uid

        _expand("<module>", 0, frozenset())

        tree.graph["node_order"] = node_order
        return tree

    @staticmethod
    def _extract_docstrings(ast: dict) -> dict[str, str]:
        """Extract function_name -> docstring from AST."""
        docs: dict[str, str] = {}
        if ast is None:
            return docs

        def _walk(body: list, scope: str = "") -> None:
            for node in body:
                if not isinstance(node, dict):
                    continue
                ntype = node.get("type", "")
                if ntype in ("FunctionDef", "AsyncFunctionDef"):
                    name = node.get("name", "")
                    full = f"{scope}.{name}" if scope else name
                    ds = node.get("docstring", "")
                    if ds:
                        docs[full] = ds
                        docs[name] = ds  # also store short name
                    _walk(node.get("body", []), full)
                elif ntype == "ClassDef":
                    cname = node.get("name", "")
                    _walk(node.get("body", []), cname)

        _walk(ast.get("body", []))
        return docs

    def build_graph(self, result: Any) -> Any:
        ast = getattr(result, "ast", None)
        if ast is None:
            return None

        from orionparser.analysis.call_tree import extract_call_tree

        ct = extract_call_tree(ast)
        functions = ct.get("functions", [])
        calls = ct.get("calls", [])

        if not functions and not calls:
            return None

        docs = self._extract_docstrings(ast)
        return self._build_tree_from_calls(functions, calls, docstrings=docs)

    def build_graph_multi(self, results: list[tuple[Any, str, str]]) -> Any:
        if not HAS_NETWORKX:
            return None

        from pathlib import Path
        from orionparser.analysis.call_tree import extract_call_tree

        all_functions: list[str] = []
        all_calls: list[tuple[str, str]] = []
        file_map: dict[str, str] = {}
        all_docs: dict[str, str] = {}

        for parse_result, source, file_path in results:
            ast = getattr(parse_result, "ast", None)
            if ast is None:
                continue
            fname = Path(file_path).stem
            ct = extract_call_tree(ast)

            for func in ct.get("functions", []):
                if func not in file_map:
                    file_map[func] = fname
                all_functions = all_functions + [func]

            for caller, callee in ct.get("calls", []):
                all_calls = all_calls + [(caller, callee)]

            all_docs.update(self._extract_docstrings(ast))

        if not all_functions and not all_calls:
            return None

        unique_functions = list(dict.fromkeys(all_functions))
        return self._build_tree_from_calls(
            unique_functions, all_calls, docstrings=all_docs,
            file_map=file_map, multi_file=True,
        )

    # 階層別カラーパレット — 20色
    DEPTH_COLORS = [
        "#B3D9FF", "#85C1E9", "#82E0AA", "#F9E79F", "#F5CBA7",
        "#F1948A", "#D7BDE2", "#76D7C4", "#F7DC6F", "#E59866",
        "#7FB3D8", "#73C6B6", "#F0B27A", "#C39BD3", "#7DCEA0",
        "#F5B041", "#85929E", "#F1C40F", "#E74C3C", "#3498DB",
    ]

    def get_node_colors(self, graph: Any) -> dict[str, str]:
        if not HAS_NETWORKX or graph is None:
            return {}
        palette = self.DEPTH_COLORS
        return {node: palette[graph.nodes[node].get("depth", 0) % len(palette)]
                for node in graph.nodes}

    def get_detail_text(self, node_id: str, graph: Any) -> str:
        if not HAS_NETWORKX or graph is None:
            return node_id
        data = graph.nodes.get(node_id, {})
        func = data.get("func_name", node_id)
        cc = data.get("call_count", 0)
        depth = data.get("depth", 0)
        ffile = data.get("file", "")
        doc = data.get("docstring", "")

        lines = [func]
        if ffile:
            lines = lines + [f"  ファイル: {ffile}"]
        lines = lines + [f"  階層: {depth + 1}"]
        if doc:
            lines = lines + [f"  説明: {doc[:100]}"]
        if cc > 1:
            lines = lines + [f"  呼び出し回数: {cc}"]

        callees = [str(graph.nodes[c].get("func_name", c)) for c in graph.successors(node_id)]
        if callees:
            lines = lines + [f"  呼び出し先 ({len(callees)}): {', '.join(callees)}"]

        callers = [str(graph.nodes[c].get("func_name", c)) for c in graph.predecessors(node_id)]
        if callers:
            lines = lines + [f"  呼び出し元: {', '.join(callers)}"]

        return "\n".join(lines)
