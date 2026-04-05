"""Symbols panel — functions, classes, variables, imports."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from orionparser.gui.panels.base_panel import BasePanel
from orionparser.gui.widgets.search_bar import SearchBar

_ICONS = {"function": "\U0001f527", "class": "\U0001f4e6", "variable": "\U0001f4dd", "import": "\U0001f4e5"}
_LABELS = {"function": "関数", "class": "クラス", "variable": "変数", "import": "インポート"}


class SymbolsPanel(BasePanel):
    """Categorised symbol table with filter."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._search = SearchBar(
            placeholder="名前で検索...",
            categories=["関数", "クラス", "変数", "インポート"],
        )
        self._search.filter_changed.connect(self._apply_filter)
        layout.addWidget(self._search)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["名前", "スコープ", "行", "docstring"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree)

        self._sections: dict[str, QTreeWidgetItem] = {}
        self._all_symbols: list[dict[str, Any]] = []

    def set_data(self, result: object, source: str) -> None:
        from orionparser.analysis.symbols import extract_symbols

        ast = getattr(result, "ast", None)
        if ast is None:
            self.clear()
            return

        table = extract_symbols(ast)
        self._all_symbols = []
        for sym in table.all:
            self._all_symbols = self._all_symbols + [{
                "name": sym.name,
                "kind": sym.kind,
                "scope": sym.scope,
                "line": sym.line,
                "docstring": sym.docstring or "",
            }]
        self._rebuild()

    def highlight_for_line(self, line: int) -> None:
        for i in range(self._tree.topLevelItemCount()):
            section = self._tree.topLevelItem(i)
            for j in range(section.childCount()):
                child = section.child(j)
                if child.data(0, Qt.ItemDataRole.UserRole) == line:
                    self._tree.setCurrentItem(child)
                    self._tree.scrollToItem(child)
                    return

    def clear(self) -> None:
        self._tree.clear()
        self._sections.clear()
        self._all_symbols = []

    def _rebuild(self) -> None:
        self._tree.clear()
        self._sections.clear()

        text = self._search.text.lower()
        cat = self._search.category
        cat_kind_map = {"関数": "function", "クラス": "class", "変数": "variable", "インポート": "import"}

        for sym in self._all_symbols:
            if text and text not in sym["name"].lower():
                continue
            if cat != "all" and sym["kind"] != cat_kind_map.get(cat, cat):
                continue
            self._add_symbol(sym)

        self._tree.expandAll()

    def _add_symbol(self, sym: dict[str, Any]) -> None:
        kind = sym["kind"]
        if kind not in self._sections:
            section = QTreeWidgetItem(self._tree, [f"{_ICONS.get(kind, '')} {_LABELS.get(kind, kind)}"])
            section.setFlags(section.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._sections[kind] = section

        parent = self._sections[kind]
        item = QTreeWidgetItem(parent, [
            f"{_ICONS.get(kind, '')} {sym['name']}",
            sym["scope"],
            str(sym["line"]),
            sym["docstring"][:60],
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, sym["line"])

        count = parent.childCount()
        parent.setText(0, f"{_ICONS.get(kind, '')} {_LABELS.get(kind, kind)} ({count})")

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        line = item.data(0, Qt.ItemDataRole.UserRole)
        if line is not None:
            self.source_line_requested.emit(line)

    def _apply_filter(self, text: str, category: str) -> None:
        self._rebuild()
