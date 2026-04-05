"""Main window — 2-mode layout with file list, welcome page and theming."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from orionparser.gui.theme import get_stylesheet
from orionparser.gui.viewmodel import AnalysisViewModel
from orionparser.gui.views.code_analysis import CodeAnalysisView
from orionparser.gui.views.graph_analysis import GraphAnalysisView


class MainWindow(QMainWindow):
    """OrionParser main window with Code Analysis / Graph Analysis modes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OrionParser")
        self.resize(1280, 800)
        self.setMinimumSize(800, 600)
        self.setAcceptDrops(True)

        self._viewmodel = AnalysisViewModel(self)
        self._theme = "light"

        self._setup_menu()
        self._setup_toolbar()
        self._setup_central()
        self._setup_statusbar()
        self._connect_signals()
        self._apply_theme()

    # --- Setup ---

    def _setup_menu(self) -> None:
        menu = self.menuBar()

        file_menu = menu.addMenu("ファイル(&F)")
        self._action_open = QAction("ファイルを開く(&O)", self)
        self._action_open.setShortcut(QKeySequence("Ctrl+O"))
        self._action_open.triggered.connect(self._open_file_dialog)
        file_menu.addAction(self._action_open)

        self._action_open_dir = QAction("フォルダを開く(&D)", self)
        self._action_open_dir.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self._action_open_dir.triggered.connect(self._open_folder_dialog)
        file_menu.addAction(self._action_open_dir)

        file_menu.addSeparator()

        self._action_reload = QAction("再解析(&R)", self)
        self._action_reload.setShortcut(QKeySequence("F5"))
        self._action_reload.triggered.connect(self._viewmodel.reload)
        self._action_reload.setEnabled(False)
        file_menu.addAction(self._action_reload)

        file_menu.addSeparator()

        action_quit = QAction("終了(&Q)", self)
        action_quit.setShortcut(QKeySequence("Ctrl+Q"))
        action_quit.triggered.connect(self.close)
        file_menu.addAction(action_quit)

        view_menu = menu.addMenu("表示(&V)")
        self._action_code_mode = QAction("コード解析(&1)", self)
        self._action_code_mode.setShortcut(QKeySequence("Ctrl+1"))
        self._action_code_mode.triggered.connect(lambda: self._switch_mode(0))
        view_menu.addAction(self._action_code_mode)

        self._action_graph_mode = QAction("グラフ解析(&2)", self)
        self._action_graph_mode.setShortcut(QKeySequence("Ctrl+2"))
        self._action_graph_mode.triggered.connect(lambda: self._switch_mode(1))
        view_menu.addAction(self._action_graph_mode)

        view_menu.addSeparator()

        theme_menu = view_menu.addMenu("テーマ")
        action_light = QAction("ライト", self)
        action_light.triggered.connect(lambda: self._set_theme("light"))
        theme_menu.addAction(action_light)
        action_dark = QAction("ダーク", self)
        action_dark.triggered.connect(lambda: self._set_theme("dark"))
        theme_menu.addAction(action_dark)

        help_menu = menu.addMenu("ヘルプ(&H)")
        action_about = QAction("バージョン情報", self)
        action_about.triggered.connect(self._show_about)
        help_menu.addAction(action_about)

    def _setup_toolbar(self) -> None:
        toolbar = QToolBar("メイン")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addAction(self._action_open)
        toolbar.addAction(self._action_open_dir)
        toolbar.addSeparator()
        toolbar.addAction(self._action_reload)
        toolbar.addSeparator()

        self._lang_label = QLabel("  言語: —  ")
        toolbar.addWidget(self._lang_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(200)
        self._progress_bar.setVisible(False)
        toolbar.addWidget(self._progress_bar)

    def _setup_central(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Mode tab bar
        self._mode_bar = QTabBar()
        self._mode_bar.addTab("  \U0001f4dd コード解析  ")
        self._mode_bar.addTab("  \U0001f517 グラフ解析  ")
        self._mode_bar.currentChanged.connect(self._switch_mode)
        layout.addWidget(self._mode_bar)

        # Outer stack: welcome page (0) vs analysis views (1)
        self._outer_stack = QStackedWidget()

        # Welcome page
        self._welcome = self._build_welcome()
        self._outer_stack.addWidget(self._welcome)

        # Analysis area: file list (left, collapsible) + mode views (right)
        self._analysis_splitter = QSplitter(Qt.Orientation.Horizontal)

        # File list (for directory mode) — in a container with header
        file_panel = QWidget()
        file_layout = QVBoxLayout(file_panel)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(0)

        self._file_header = QLabel("  ファイル一覧")
        self._file_header.setStyleSheet("font-weight: bold; padding: 4px; background: #E8E8E8;")
        file_layout.addWidget(self._file_header)

        self._file_list = QListWidget()
        self._file_list.currentRowChanged.connect(self._on_file_list_selection)
        file_layout.addWidget(self._file_list)

        file_panel.setVisible(False)
        self._file_panel = file_panel
        self._analysis_splitter.addWidget(file_panel)

        # Mode views stack
        self._stack = QStackedWidget()
        self._code_view = CodeAnalysisView()
        self._graph_view = GraphAnalysisView()
        self._stack.addWidget(self._code_view)
        self._stack.addWidget(self._graph_view)
        self._analysis_splitter.addWidget(self._stack)

        self._analysis_splitter.setSizes([200, 1080])
        self._analysis_splitter.setCollapsible(0, True)
        self._analysis_splitter.setCollapsible(1, False)

        self._outer_stack.addWidget(self._analysis_splitter)

        layout.addWidget(self._outer_stack)
        self.setCentralWidget(central)

    def _build_welcome(self) -> QWidget:
        """Build the welcome / empty state page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("OrionParser")
        title.setStyleSheet("font-size: 32px; font-weight: 700; color: #0078D4; margin-bottom: 4px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("ソースコードの構造を解析・可視化")
        subtitle.setStyleSheet("font-size: 15px; color: #666666; margin-bottom: 24px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        shortcuts_text = (
            "<table style='font-size:13px; color:#444;'>"
            "<tr><td style='padding:6px 16px;'><b style='color:#0078D4;'>Ctrl+O</b></td>"
            "<td>ファイルを開く</td></tr>"
            "<tr><td style='padding:6px 16px;'><b style='color:#0078D4;'>Ctrl+Shift+O</b></td>"
            "<td>フォルダを開く</td></tr>"
            "<tr><td style='padding:6px 16px;'><b style='color:#0078D4;'>F5</b></td>"
            "<td>再解析</td></tr>"
            "</table>"
            "<br>"
            "<p style='font-size:12px; color:#999;'>ファイルをドラッグ&ドロップすることもできます</p>"
        )
        shortcuts = QLabel(shortcuts_text)
        shortcuts.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(shortcuts)

        return page

    def _setup_statusbar(self) -> None:
        self._status_label = QLabel("  準備完了")
        self.statusBar().addWidget(self._status_label, 1)

    def _connect_signals(self) -> None:
        vm = self._viewmodel
        vm.file_loaded.connect(self._on_file_loaded)
        vm.directory_loaded.connect(self._on_directory_loaded)
        vm.file_selected.connect(self._on_file_selected)
        vm.analysis_started.connect(self._on_analysis_started)
        vm.analysis_progress.connect(self._on_analysis_progress)
        vm.analysis_error.connect(self._on_analysis_error)

    # --- Theme ---

    def _apply_theme(self) -> None:
        self.setStyleSheet(get_stylesheet(self._theme))

    def _set_theme(self, name: str) -> None:
        self._theme = name
        self._apply_theme()

    # --- Public API ---

    def open_path(self, path: str) -> None:
        """Open a file or directory."""
        p = Path(path)
        if p.is_file():
            self._file_panel.setVisible(False)
            self._viewmodel.load_file(str(p))
        elif p.is_dir():
            self._viewmodel.load_directory(str(p))

    # --- Slots ---

    def _on_file_loaded(self, result: object, source: str, path: str) -> None:
        """Single file loaded."""
        self._outer_stack.setCurrentIndex(1)
        self._show_file(result, source, path)

    def _on_directory_loaded(self, results: list, dir_path: str) -> None:
        """All files in directory analyzed."""
        self._outer_stack.setCurrentIndex(1)
        self._progress_bar.setVisible(False)

        # Populate file list
        self._file_list.clear()
        self._file_panel.setVisible(True)
        dir_p = Path(dir_path)
        for result, source, fpath in results:
            try:
                rel = Path(fpath).relative_to(dir_p)
            except ValueError:
                rel = Path(fpath).name
            success = getattr(result, "success", False)
            icon = "\u2705" if success else "\u274c"
            item = QListWidgetItem(f"{icon} {rel}")
            self._file_list.addItem(item)

        self._action_reload.setEnabled(True)
        total = len(results)
        ok = sum(1 for r, _, _ in results if getattr(r, "success", False))
        self._status_label.setText(f"  {dir_p.name}  |  {ok}/{total} files  |  解析完了")
        self.setWindowTitle(f"OrionParser — {dir_p.name}/")

        # Feed all results to graph analysis for cross-file call tree
        self._graph_view.set_directory_data(results)

    def _on_file_selected(self, result: object, source: str, path: str) -> None:
        """File selected from directory results."""
        self._show_file(result, source, path)

    def _on_file_list_selection(self, row: int) -> None:
        """User clicked a file in the list."""
        self._viewmodel.select_file(row)
        # Sync graph analysis file filter
        if 0 <= row < len(self._viewmodel.dir_results):
            from pathlib import Path as P
            fname = P(self._viewmodel.dir_results[row][2]).stem
            for i in range(self._graph_view._focus_file.count()):
                if self._graph_view._focus_file.itemData(i) == fname:
                    self._graph_view._focus_file.setCurrentIndex(i)
                    break

    def _show_file(self, result: object, source: str, path: str) -> None:
        """Display a single file's analysis. In directory mode, graph keeps cross-file view."""
        self._code_view.set_data(result, source)
        if not self._viewmodel.is_directory:
            self._graph_view.set_data(result, source)
        else:
            # Update flowchart's current result for per-file display
            self._graph_view._current_result = result
            from orionparser.gui.panels.graph_panels.flowchart_panel import FlowchartPanel
            from orionparser.gui.panels.graph_panels.dfd_panel import DFDPanel
            if isinstance(self._graph_view._active_panel(), (FlowchartPanel, DFDPanel)):
                self._graph_view._build_full_graph()
                self._graph_view._update_focus_list()
                self._graph_view._render_current()
        self._action_reload.setEnabled(True)

        name = Path(path).name
        success = getattr(result, "success", False)

        from orionparser.analysis.symbols import extract_symbols

        ast = getattr(result, "ast", None)
        stats = ""
        if ast is not None:
            table = extract_symbols(ast)
            stats = (
                f"関数: {len(table.functions)}  "
                f"クラス: {len(table.classes)}  "
                f"変数: {len(table.variables)}  "
                f"import: {len(table.imports)}"
            )

        status = f"  {name}  |  {stats}" if success else f"  {name}  |  解析失敗"
        self._status_label.setText(status)
        self._lang_label.setText("  言語: Python  ")
        if not self._viewmodel.is_directory:
            self.setWindowTitle(f"OrionParser — {name}")

    def _on_analysis_started(self, path: str) -> None:
        p = Path(path)
        if p.is_dir():
            self._status_label.setText(f"  解析中: {p.name}/ ...")
            self._progress_bar.setVisible(True)
            self._progress_bar.setValue(0)
        else:
            self._status_label.setText(f"  解析中: {p.name}...")

    def _on_analysis_progress(self, current: int, total: int) -> None:
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        self._status_label.setText(f"  解析中: {current}/{total} files...")

    def _on_analysis_error(self, message: str) -> None:
        self._status_label.setText(f"  エラー: {message}")
        self._progress_bar.setVisible(False)

    def _switch_mode(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._mode_bar.setCurrentIndex(index)

    def _open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "ファイルを開く", "", "Python Files (*.py);;All Files (*)"
        )
        if path:
            self.open_path(path)

    def _open_folder_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "フォルダを開く")
        if path:
            self.open_path(path)

    def _show_about(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.about(
            self, "OrionParser",
            "OrionParser v0.1.0\n\n"
            "Multi-language source code analysis engine\n"
            "ソースコードの構造を解析・可視化するツール",
        )

    # --- Drag & Drop ---

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.open_path(path)
