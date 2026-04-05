"""AST panel — interactive tree view of the syntax tree."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from orionparser.gui.panels.base_panel import BasePanel

_TYPE_ICONS = {
    "Module": "\U0001f4c4",
    "FunctionDef": "\U0001f527",
    "AsyncFunctionDef": "\u26a1",
    "ClassDef": "\U0001f4e6",
    "Assign": "\U0001f4dd",
    "AnnAssign": "\U0001f4dd",
    "Import": "\U0001f4e5",
    "ImportFrom": "\U0001f4e5",
    "Call": "\U0001f4de",
    "If": "\u2753",
    "For": "\U0001f501",
    "While": "\U0001f504",
    "Return": "\u21a9\ufe0f",
    "Try": "\U0001f6e1\ufe0f",
}


class ASTPanel(BasePanel):
    """Interactive AST tree view with detail pane."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["ノード"])
        self._tree.setAlternatingRowColors(True)
        self._tree.itemClicked.connect(self._on_item_clicked)
        splitter.addWidget(self._tree)

        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        splitter.addWidget(self._detail)

        splitter.setSizes([300, 200])
        self._ast: dict[str, Any] | None = None

    def set_data(self, result: object, source: str) -> None:
        ast_dict = getattr(result, "ast", None)
        self._ast = ast_dict
        self._tree.clear()
        self._detail.clear()
        if ast_dict is None:
            return
        root = self._build_item(ast_dict)
        if root is not None:
            self._tree.addTopLevelItem(root)
            self._tree.expandToDepth(1)

    def highlight_for_line(self, line: int) -> None:
        self._find_and_select(self._tree.invisibleRootItem(), line)

    def clear(self) -> None:
        self._tree.clear()
        self._detail.clear()
        self._ast = None

    def _build_item(self, node: Any, key: str = "") -> QTreeWidgetItem | None:
        if isinstance(node, dict):
            node_type = node.get("type", "")
            icon = _TYPE_ICONS.get(node_type, "\U0001f4cc")
            name = node.get("name", "")
            line = node.get("_line", "")

            label_parts = []
            if key:
                label_parts = label_parts + [f"{key}:"]
            label_parts = label_parts + [f"{icon} {node_type}"]
            if name:
                label_parts = label_parts + [f'"{name}"']
            if line:
                label_parts = label_parts + [f"L:{line}"]
            label = " ".join(label_parts)

            item = QTreeWidgetItem([label])
            item.setData(0, Qt.ItemDataRole.UserRole, node.get("_line"))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, node)

            for k, v in node.items():
                if k in ("type", "_line"):
                    continue
                if isinstance(v, (dict, list)):
                    child = self._build_item(v, key=k)
                    if child is not None:
                        item.addChild(child)
                else:
                    leaf = QTreeWidgetItem([f"{k}: {v!r}"])
                    item.addChild(leaf)
            return item

        if isinstance(node, list):
            label = f"{key}: [{len(node)} items]" if key else f"[{len(node)} items]"
            item = QTreeWidgetItem([label])
            for i, elem in enumerate(node):
                child = self._build_item(elem, key=str(i))
                if child is not None:
                    item.addChild(child)
            return item

        return None

    def _on_item_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        line = item.data(0, Qt.ItemDataRole.UserRole)
        if line is not None and isinstance(line, int) and line > 0:
            self.source_line_requested.emit(line)

        node = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if isinstance(node, dict):
            import json
            self._detail.setPlainText(json.dumps(node, indent=2, default=str)[:5000])
        else:
            self._detail.clear()

    def _find_and_select(self, parent: QTreeWidgetItem, line: int) -> bool:
        for i in range(parent.childCount()):
            child = parent.child(i)
            child_line = child.data(0, Qt.ItemDataRole.UserRole)
            if child_line == line:
                self._tree.setCurrentItem(child)
                self._tree.scrollToItem(child)
                return True
            if self._find_and_select(child, line):
                return True
        return False
