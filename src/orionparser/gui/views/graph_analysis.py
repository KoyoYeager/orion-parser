"""Graph Analysis mode — graph type selector + canvas + detail + export."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from orionparser.gui.panels.graph_panels.base_graph import BaseGraphPanel
from orionparser.gui.panels.graph_panels.call_tree_panel import CallTreePanel
from orionparser.gui.panels.graph_panels.data_flow_panel import DataFlowPanel
from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel
from orionparser.gui.panels.graph_panels.class_diagram_panel import ClassDiagramPanel
from orionparser.gui.panels.graph_panels.dfd_panel import DFDPanel
from orionparser.gui.widgets.graph_canvas import GraphCanvas


class GraphAnalysisView(QWidget):
    """Graph type selector + toolbar + canvas + detail panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # --- Toolbar ---
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._layout_combo = QComboBox()
        self._layout_combo.addItem("階層 (dot)", "dot")
        self._layout_combo.addItem("力学モデル", "spring")
        self._layout_combo.addItem("円形", "circular")
        self._layout_combo.addItem("カマダ・カワイ", "kamada_kawai")
        self._layout_combo.currentIndexChanged.connect(self._on_layout_changed)
        toolbar.addWidget(QLabel("レイアウト:"))
        toolbar.addWidget(self._layout_combo)

        toolbar.addWidget(QLabel("  表示:"))
        self._display_mode = QComboBox()
        self._display_mode.addItem("関数名", "func_name")
        self._display_mode.addItem("コメント (なければ関数名)", "docstring")
        self._display_mode.setToolTip("ノードに表示するテキストを切り替えます")
        self._display_mode.currentIndexChanged.connect(self._on_display_mode_changed)
        toolbar.addWidget(self._display_mode)

        toolbar.addStretch()

        btn_fit = QPushButton("フィット")
        btn_fit.setMaximumWidth(80)
        btn_fit.clicked.connect(self._on_fit)
        toolbar.addWidget(btn_fit)

        toolbar.addWidget(QLabel("  エクスポート:"))
        self._export_combo = QComboBox()
        self._export_combo.setMinimumWidth(200)
        _sep = "---"

        # 画像ファイル
        self._export_combo.addItem("--- 画像ファイル ---", "")
        self._export_combo.addItem("  PNG画像 (.png)", "png")
        self._export_combo.addItem("  SVG画像 (.svg)", "svg")
        self._export_combo.addItem("  JPEG画像 (.jpg)", "jpg")
        self._export_combo.addItem("  PDF文書 (.pdf)", "pdf")
        self._export_combo.addItem("  BMP (.bmp)", "bmp")
        self._export_combo.addItem("  WebP (.webp)", "webp")
        self._export_combo.addItem("  TIFF (.tif)", "tif")
        self._export_combo.addItem("  GIF (.gif)", "gif")
        self._export_combo.addItem("  EPS (.eps)", "eps")

        # ビジネス向け
        self._export_combo.addItem("--- ビジネス向け ---", "")
        self._export_combo.addItem("  Excel ワークブック (.xlsx)", "xlsx")
        self._export_combo.addItem("  Visio フローチャート (.vsdx)", "vsdx")

        # 開発者向け
        self._export_combo.addItem("--- 開発者向け ---", "")
        self._export_combo.addItem("  Graphviz DOT (.dot)", "dot")
        self._export_combo.addItem("  Mermaid記法 (.md)", "mermaid")
        self._export_combo.addItem("  PlantUML図 (.puml)", "plantuml")
        self._export_combo.addItem("  Draw.io XML (.drawio)", "drawio")

        # データ形式
        self._export_combo.addItem("--- データ形式 ---", "")
        self._export_combo.addItem("  JSON データ (.json)", "json")
        self._export_combo.addItem("  XML データ (.xml)", "xml")
        self._export_combo.addItem("  YAML データ (.yaml)", "yaml")

        # Web形式
        self._export_combo.addItem("--- Web形式 ---", "")
        self._export_combo.addItem("  HTML (インタラクティブ) (.html)", "html")

        # Disable category headers
        from PySide6.QtGui import QStandardItemModel
        model = self._export_combo.model()
        for i in range(self._export_combo.count()):
            if not self._export_combo.itemData(i):
                item = model.item(i)
                item.setEnabled(False)

        self._export_combo.setCurrentIndex(1)  # Default to PNG
        toolbar.addWidget(self._export_combo)

        btn_export = QPushButton("保存")
        btn_export.setMaximumWidth(60)
        btn_export.clicked.connect(self._on_export)
        toolbar.addWidget(btn_export)

        layout.addLayout(toolbar)

        # --- Focus bar: file selector -> function selector -> mode ---
        focus_bar = QHBoxLayout()
        focus_bar.setSpacing(8)

        # File filter
        focus_bar.addWidget(QLabel("ファイル:"))
        self._focus_file = QComboBox()
        self._focus_file.setMinimumWidth(140)
        self._focus_file.addItem("(すべてのファイル)", "")
        self._focus_file.setToolTip("ファイルを選ぶと、そのファイルの関数だけが右に表示されます")
        self._focus_file.currentIndexChanged.connect(self._on_focus_file_changed)
        focus_bar.addWidget(self._focus_file)

        # Function filter (populated based on file selection)
        focus_bar.addWidget(QLabel("関数:"))
        self._focus_combo = QComboBox()
        self._focus_combo.setEditable(True)
        self._focus_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._focus_combo.setMinimumWidth(180)
        self._focus_combo.lineEdit().setPlaceholderText("関数名を入力...")
        self._focus_combo.addItem("(全体を表示)", "")
        self._focus_combo.setToolTip("プルダウンから選択、または関数名を入力して絞り込み")
        self._focus_combo.activated.connect(self._on_focus_selected)
        from PySide6.QtCore import QStringListModel
        self._focus_completer = QCompleter()
        self._focus_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._focus_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._focus_combo.setCompleter(self._focus_completer)
        self._focus_completer.activated.connect(self._on_completer_activated)
        focus_bar.addWidget(self._focus_combo)

        # Mode
        focus_bar.addWidget(QLabel("範囲:"))
        self._focus_mode = QComboBox()
        self._focus_mode.addItem("呼び出し先のみ", "descendants")
        self._focus_mode.addItem("経路 + 呼び出し先", "ancestors_descendants")
        self._focus_mode.addItem("兄弟も含む", "ancestors_siblings")
        self._focus_mode.addItem("ルートから全部", "full_ancestor")
        self._focus_mode.setCurrentIndex(1)
        self._focus_mode.setToolTip(
            "呼び出し先のみ: 選択関数から呼ばれるものだけ\n"
            "経路 + 呼び出し先: ルートからの経路 + 呼び出し先\n"
            "兄弟も含む: 同じ親から呼ばれている関数も表示\n"
            "ルートから全部: 最上位からすべて表示"
        )
        self._focus_mode.currentIndexChanged.connect(self._on_focus_mode_changed)
        focus_bar.addWidget(self._focus_mode)

        focus_bar.addStretch()
        layout.addLayout(focus_bar)

        # --- Main area ---
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(v_splitter)

        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        v_splitter.addWidget(h_splitter)

        # Left: graph type selector
        self._selector = QListWidget()
        self._selector.setMaximumWidth(100)
        self._selector.setMinimumWidth(80)

        self._graph_panels: list[BaseGraphPanel] = [CallTreePanel(), DataFlowPanel(), FlowchartPanel(), ClassDiagramPanel(), DFDPanel()]
        for gp in self._graph_panels:
            item = QListWidgetItem(gp.graph_name)
            item.setData(Qt.ItemDataRole.UserRole, gp.graph_id)
            self._selector.addItem(item)

        for name in ["依存関係", "メトリクス", "セキュリティ"]:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            item.setToolTip("今後のバージョンで追加予定")
            self._selector.addItem(item)

        self._selector.setCurrentRow(0)
        self._selector.currentRowChanged.connect(self._on_type_changed)
        h_splitter.addWidget(self._selector)

        # Center: graph canvas
        self.canvas = GraphCanvas()
        h_splitter.addWidget(self.canvas)
        h_splitter.setSizes([80, 900])

        # Bottom: detail panel
        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(120)
        self._detail.setPlaceholderText("ノードをクリックして詳細を表示")
        v_splitter.addWidget(self._detail)
        v_splitter.setSizes([600, 120])

        self.canvas.node_selected.connect(self._on_node_selected)

        self._current_result: object | None = None
        self._current_graph = None
        self._full_graph = None  # unfiltered graph for focus operations
        self._dir_results: list[tuple[object, str, str]] | None = None

    def set_data(self, result: object, source: str) -> None:
        """Set data from a single file. Clears directory mode."""
        self._current_result = result
        self._dir_results = None
        self._build_full_graph()
        self._update_focus_list()
        self._render_current()

    def set_directory_data(self, results: list[tuple[object, str, str]]) -> None:
        """Set data from all files in a directory for cross-file analysis."""
        self._dir_results = results
        self._current_result = results[0][0] if results else None
        self._detail.setPlainText("グラフを構築中...")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        self._build_full_graph()
        self._update_focus_list()
        self._render_current()
        self._detail.setPlainText("")

    def clear(self) -> None:
        self.canvas.clear_graph()
        self._detail.clear()
        self._current_result = None
        self._current_graph = None
        self._full_graph = None
        self._dir_results = None

    def _active_panel(self) -> BaseGraphPanel | None:
        row = self._selector.currentRow()
        if row < 0:
            return None
        item = self._selector.item(row)
        if item is None:
            return None
        gid = item.data(Qt.ItemDataRole.UserRole)
        for panel in self._graph_panels:
            if panel.graph_id == gid:
                return panel
        return None

    def _current_layout(self) -> str:
        return self._layout_combo.currentData() or "dot"

    def _build_full_graph(self) -> None:
        """Build the full (unfiltered) graph from current data."""
        panel = self._active_panel()
        if panel is None:
            self._full_graph = None
            return

        # Flowchart/DFD: always uses single-file (current selection)
        if isinstance(panel, (FlowchartPanel, DFDPanel)):
            if self._current_result is not None:
                self._full_graph = panel.build_graph(self._current_result)
            elif self._dir_results:
                self._full_graph = panel.build_graph(self._dir_results[0][0])
            else:
                self._full_graph = None
            return

        if self._dir_results is not None and hasattr(panel, "build_graph_multi"):
            self._full_graph = panel.build_graph_multi(self._dir_results)
        elif self._current_result is not None:
            self._full_graph = panel.build_graph(self._current_result)
        else:
            self._full_graph = None

    def _update_focus_list(self) -> None:
        """Populate file and function dropdowns from current graph."""
        self._file_funcs: dict[str, list[str]] = {}
        all_names: list[str] = []

        # Flowchart: get function names from the panel itself
        panel = self._active_panel()
        if isinstance(panel, (FlowchartPanel, DFDPanel)):
            all_names = panel.get_function_names()
            self._focus_file.blockSignals(True)
            self._focus_file.clear()
            self._focus_file.addItem("(すべてのファイル)", "")
            self._focus_file.blockSignals(False)
            self._populate_func_combo(all_names)
            return

        if self._full_graph is not None:
            seen: set[str] = set()
            for n in self._full_graph.nodes:
                func = self._full_graph.nodes[n].get("func_name", str(n))
                ffile = self._full_graph.nodes[n].get("file", "")
                if func != "<module>" and func not in seen:
                    seen.add(func)
                    all_names = all_names + [func]
                    if ffile:
                        if ffile not in self._file_funcs:
                            self._file_funcs[ffile] = []
                        if func not in self._file_funcs[ffile]:
                            self._file_funcs[ffile] = self._file_funcs[ffile] + [func]
            all_names.sort()
            for ffile in self._file_funcs:
                self._file_funcs[ffile].sort()

        # Update file dropdown
        self._focus_file.blockSignals(True)
        self._focus_file.clear()
        self._focus_file.addItem("(すべてのファイル)", "")
        for ffile in sorted(self._file_funcs.keys()):
            count = len(self._file_funcs[ffile])
            self._focus_file.addItem(f"{ffile} ({count}関数)", ffile)
        self._focus_file.blockSignals(False)

        # Populate function combo with all names
        self._populate_func_combo(all_names)

    def _populate_func_combo(self, names: list[str]) -> None:
        """Fill the function combo with given names."""
        self._focus_combo.blockSignals(True)
        self._focus_combo.clear()
        self._focus_combo.addItem("(全体を表示)", "")
        for name in names:
            self._focus_combo.addItem(name, name)
        from PySide6.QtCore import QStringListModel
        self._focus_completer.setModel(QStringListModel(names))
        self._focus_combo.blockSignals(False)

    def _on_focus_file_changed(self, index: int) -> None:
        """File selection changed -> update function list for that file."""
        ffile = self._focus_file.currentData()
        if ffile and ffile in self._file_funcs:
            self._populate_func_combo(self._file_funcs[ffile])
        else:
            # All files
            all_names: list[str] = []
            seen: set[str] = set()
            if self._full_graph is not None:
                for n in self._full_graph.nodes:
                    func = self._full_graph.nodes[n].get("func_name", str(n))
                    if func != "<module>" and func not in seen:
                        seen.add(func)
                        all_names = all_names + [func]
            all_names.sort()
            self._populate_func_combo(all_names)
        # Reset graph to full view
        self._render_current()
        self._detail.setPlainText("")

    def _on_focus_selected(self, index: int) -> None:
        """User selected a function from the dropdown."""
        func_name = self._focus_combo.currentData()
        if not func_name:
            self._render_current()
            self._detail.setPlainText("")
            return

        # For flowchart/DFD: switch to that function
        panel = self._active_panel()
        if isinstance(panel, DFDPanel) and self._current_result is not None:
            graph = panel.build_for_function(func_name)
            if graph is not None:
                self._current_graph = graph
                colors = panel.get_node_colors(graph)
                self.canvas.set_graph(graph, layout="dfd", node_colors=colors)
                self.canvas.fit_to_view()
                self._detail.setPlainText(f"DFD: {func_name}")
                return

        if isinstance(panel, FlowchartPanel) and self._current_result is not None:
            graph = panel.build_for_function(func_name)
            if graph is not None:
                self._current_graph = graph
                colors = panel.get_node_colors(graph)
                self.canvas.set_graph(graph, layout="flowchart", node_colors=colors)
                self.canvas.fit_to_view()
                self._detail.setPlainText(f"フローチャート: {func_name}")
                return

        self._apply_focus(func_name)

    def _on_completer_activated(self, text: str) -> None:
        """User selected from completer popup (typed + selected)."""
        if text:
            self._apply_focus(text)

    def _render_current(self) -> None:
        graph = self._full_graph
        self._current_graph = graph
        panel = self._active_panel()
        if graph is not None and panel is not None:
            colors = panel.get_node_colors(graph)
            if isinstance(panel, FlowchartPanel):
                layout = "flowchart"
            elif isinstance(panel, ClassDiagramPanel):
                layout = "class_diagram"
            elif isinstance(panel, DFDPanel):
                layout = "dfd"
            else:
                layout = self._current_layout()
            self.canvas.set_graph(graph, layout=layout, node_colors=colors)
            self.canvas.fit_to_view()
        else:
            self.canvas.clear_graph()

    def _on_type_changed(self, row: int) -> None:
        self._detail.setPlainText("読み込み中...")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        self._build_full_graph()
        self._update_focus_list()
        self._render_current()
        if not self._detail.toPlainText().startswith("フォーカス"):
            self._detail.clear()

    def _on_layout_changed(self, index: int) -> None:
        self._render_current()

    def _on_display_mode_changed(self, index: int) -> None:
        """Switch node labels between func_name and docstring."""
        mode = self._display_mode.currentData() or "func_name"
        graph = self._current_graph
        if graph is None:
            return
        for node_id, item in self.canvas._node_items.items():
            nd = graph.nodes.get(node_id, {})
            func_name = nd.get("func_name", str(node_id))
            doc = nd.get("docstring", "")
            cc = nd.get("call_count", 0)

            if mode == "docstring" and doc:
                # Show first line of docstring, truncated
                first_line = doc.split("\n")[0].strip()
                label = first_line[:30] + ("..." if len(first_line) > 30 else "")
            else:
                label = func_name

            if cc > 1:
                label = f"{label} (x{cc})"

            item.set_label(label)

    def _on_focus_mode_changed(self, index: int) -> None:
        """Re-apply focus when mode changes."""
        func_name = self._focus_combo.currentData()
        if func_name:
            self._apply_focus(func_name)

    def _apply_focus(self, func_name: str) -> None:
        """Apply focus filter to the graph for the given function name."""
        if not func_name or self._full_graph is None:
            self._render_current()
            self._detail.setPlainText("")
            return

        import networkx as nx
        graph = self._full_graph
        mode = self._focus_mode.currentData() or "ancestors_descendants"

        # Find all nodes with this func_name
        target_nodes = {n for n in graph.nodes if graph.nodes[n].get("func_name") == func_name}
        if not target_nodes:
            self._render_current()
            return

        # Collect nodes to display based on mode
        display_nodes: set[str] = set()

        for target in target_nodes:
            if mode == "descendants":
                display_nodes.add(target)
                display_nodes.update(nx.descendants(graph, target))

            elif mode == "ancestors_descendants":
                display_nodes.update(nx.ancestors(graph, target))
                display_nodes.add(target)
                display_nodes.update(nx.descendants(graph, target))

            elif mode == "ancestors_siblings":
                ancestors = nx.ancestors(graph, target)
                display_nodes.update(ancestors)
                display_nodes.add(target)
                display_nodes.update(nx.descendants(graph, target))
                # Add siblings (children of each ancestor)
                for anc in ancestors:
                    display_nodes.update(graph.successors(anc))

            elif mode == "full_ancestor":
                # Find the highest ancestor, then show all its descendants
                highest = target
                while True:
                    preds = list(graph.predecessors(highest))
                    if not preds:
                        break
                    highest = preds[0]
                display_nodes.add(highest)
                display_nodes.update(nx.descendants(graph, highest))

        if not display_nodes:
            self._render_current()
            return

        # Build subgraph preserving node_order
        sub = graph.subgraph(display_nodes).copy()
        original_order = graph.graph.get("node_order", [])
        sub.graph["node_order"] = [n for n in original_order if n in display_nodes]

        # Recalculate depths from roots of the subgraph
        sub_roots = [n for n in sub.nodes if sub.in_degree(n) == 0]
        if sub_roots:
            visited: set[str] = set()
            queue = [(r, 0) for r in sub_roots]
            while queue:
                node, depth = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                sub.nodes[node]["depth"] = depth
                for child in sub.successors(node):
                    queue = queue + [(child, depth + 1)]

        panel = self._active_panel()
        self._current_graph = sub
        if panel is not None:
            colors = panel.get_node_colors(sub)
            self.canvas.set_graph(sub, layout=self._current_layout(), node_colors=colors)
            self.canvas.fit_to_view()
            mode_label = self._focus_mode.currentText()
            self._detail.setPlainText(f"フォーカス: {func_name} ({mode_label})\nノード数: {len(sub.nodes)}")

    def _on_fit(self) -> None:
        self.canvas.fit_to_view()

    def _on_node_selected(self, node_id: str) -> None:
        panel = self._active_panel()
        if panel is not None and self._current_graph is not None:
            text = panel.get_detail_text(node_id, self._current_graph)
            self._detail.setPlainText(text)

    def _on_export(self) -> None:
        """Export graph to the selected format."""
        fmt = self._export_combo.currentData() or "svg"

        _EXT = {
            "mermaid": "md", "plantuml": "puml", "drawio": "drawio",
            "yaml": "yaml", "xml": "xml", "vsdx": "vsdx",
        }
        ext = _EXT.get(fmt, fmt)

        # Default filename based on active graph type
        panel = self._active_panel()
        if isinstance(panel, FlowchartPanel):
            base_name = "flowchart"
        elif isinstance(panel, DFDPanel):
            base_name = "dfd"
        elif isinstance(panel, ClassDiagramPanel):
            base_name = "class_diagram"
        else:
            base_name = "call_tree"
        # Include function name if available
        func_name = self._focus_combo.currentData()
        if func_name:
            base_name = f"{base_name}_{func_name}"

        _FILTERS = {
            "svg": "SVG (*.svg)", "png": "PNG (*.png)", "pdf": "PDF (*.pdf)",
            "jpg": "JPEG (*.jpg)", "bmp": "BMP (*.bmp)", "webp": "WebP (*.webp)",
            "tif": "TIFF (*.tif)", "gif": "GIF (*.gif)", "eps": "EPS (*.eps)",
            "xlsx": "Excel (*.xlsx)", "vsdx": "Visio (*.vsdx)", "html": "HTML (*.html)",
            "dot": "DOT (*.dot)", "json": "JSON (*.json)",
            "mermaid": "Mermaid (*.md)", "plantuml": "PlantUML (*.puml)",
            "drawio": "Draw.io (*.drawio)", "xml": "XML (*.xml)", "yaml": "YAML (*.yaml)",
        }

        path, _ = QFileDialog.getSaveFileName(
            self,
            f"グラフを {fmt.upper()} で保存",
            f"{base_name}.{ext}",
            _FILTERS.get(fmt, "All Files (*)"),
        )
        if not path:
            return

        # For image formats: save GUIの見た目をそのまま保存
        if fmt in ("png", "jpg", "bmp", "webp", "tif", "gif"):
            success = self.canvas.export_png_from_scene(path)
            if success:
                QMessageBox.information(self, "エクスポート完了", f"保存しました:\n{path}")
            else:
                QMessageBox.warning(self, "エクスポート失敗", "画像の保存に失敗しました。")
            return

        try:
            success = self.canvas.export_file(path, fmt)
        except ImportError as exc:
            QMessageBox.warning(self, "ライブラリ不足", str(exc))
            return
        except RuntimeError as exc:
            QMessageBox.warning(self, "エクスポート失敗", str(exc))
            return

        # Fallback for image formats
        if not success and fmt in ("png", "jpg", "bmp", "webp", "tif", "gif"):
            success = self.canvas.export_png_from_scene(path)

        if success:
            QMessageBox.information(self, "エクスポート完了", f"保存しました:\n{path}")
        else:
            QMessageBox.warning(
                self, "エクスポート失敗",
                f"{fmt.upper()} の保存に失敗しました。\n"
                "必要なソフトウェアがインストールされているか確認してください。\n\n"
                "Visio: Microsoft Visio + pip install pywin32\n"
                "画像: Graphviz (https://graphviz.org/)",
            )
