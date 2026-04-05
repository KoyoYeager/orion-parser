"""Base class for graph analysis panels."""

from __future__ import annotations

from typing import Any


class BaseGraphPanel:
    """Common interface for graph type panels."""

    graph_id: str = ""
    graph_name: str = ""
    default_layout: str = "dot"

    def build_graph(self, result: Any) -> Any:
        """Build and return a networkx DiGraph from a single parse result."""
        return None

    def build_graph_multi(self, results: list[tuple[Any, str, str]]) -> Any:
        """Build a combined graph from multiple file results.

        Args:
            results: list of (ParseResult, source, file_path)

        Default: merges individual build_graph results.
        """
        return None

    def get_node_colors(self, graph: Any) -> dict[str, str]:
        """Return node_id -> color mapping."""
        return {}

    def get_detail_text(self, node_id: str, graph: Any) -> str:
        """Return detail text for a selected node."""
        return node_id
