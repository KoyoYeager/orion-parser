"""ViewModel and background worker for analysis state management."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal


class AnalysisWorker(QThread):
    """Run file analysis in a background thread."""

    finished = Signal(object, str, str)  # (ParseResult, source_text, file_path)
    error = Signal(str)  # error message

    def __init__(self, path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        try:
            p = Path(self._path)
            from orionparser.core.encoding import read_file

            source = read_file(p)

            from orionparser.registry import get_pipeline

            pipeline = get_pipeline(p)
            result = pipeline.analyze_file(p)
            self.finished.emit(result, source, self._path)
        except Exception as exc:
            self.error.emit(str(exc))


class DirectoryWorker(QThread):
    """Analyze all files in a directory recursively."""

    file_analyzed = Signal(object, str, str)  # (ParseResult, source, path) per file
    progress = Signal(int, int)  # (current, total)
    all_finished = Signal(list, str)  # (all_results, dir_path)
    error = Signal(str)

    def __init__(self, dir_path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dir_path = dir_path

    def run(self) -> None:
        try:
            from orionparser.registry import get_pipeline, supported_extensions

            p = Path(self._dir_path)
            exts = supported_extensions()
            files = sorted(f for f in p.rglob("*") if f.suffix in exts and f.is_file())

            results: list[tuple[object, str, str]] = []
            total = len(files)

            for i, f in enumerate(files):
                try:
                    from orionparser.core.encoding import read_file

                    source = read_file(f)
                    pipeline = get_pipeline(f)
                    result = pipeline.analyze_file(f)
                    self.file_analyzed.emit(result, source, str(f))
                    results = results + [(result, source, str(f))]
                except Exception:
                    pass  # skip unparseable files
                self.progress.emit(i + 1, total)

            self.all_finished.emit(results, self._dir_path)
        except Exception as exc:
            self.error.emit(str(exc))


class AnalysisViewModel(QObject):
    """Central state manager shared by all views."""

    file_loaded = Signal(object, str, str)  # (ParseResult, source, path)
    directory_loaded = Signal(list, str)  # (results, dir_path)
    file_selected = Signal(object, str, str)  # tree selection in dir mode
    analysis_started = Signal(str)  # path
    analysis_progress = Signal(int, int)  # (current, total)
    analysis_error = Signal(str)  # error message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.current_path: str | None = None
        self.current_result: object | None = None
        self.current_source: str = ""
        self.is_directory: bool = False
        self.dir_results: list[tuple[object, str, str]] = []  # (result, source, path)
        self._worker: AnalysisWorker | None = None
        self._dir_worker: DirectoryWorker | None = None

    def load_file(self, path: str) -> None:
        """Start background analysis for a single file."""
        self.current_path = path
        self.is_directory = False
        self.analysis_started.emit(path)

        self._stop_workers()
        self._worker = AnalysisWorker(path, self)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def load_directory(self, path: str) -> None:
        """Start background analysis for all files in a directory."""
        self.current_path = path
        self.is_directory = True
        self.dir_results = []
        self.analysis_started.emit(path)

        self._stop_workers()
        self._dir_worker = DirectoryWorker(path, self)
        self._dir_worker.file_analyzed.connect(self._on_dir_file_analyzed)
        self._dir_worker.progress.connect(self._on_dir_progress)
        self._dir_worker.all_finished.connect(self._on_dir_finished)
        self._dir_worker.error.connect(self._on_error)
        self._dir_worker.start()

    def select_file(self, index: int) -> None:
        """Select a file from directory results by index."""
        if 0 <= index < len(self.dir_results):
            result, source, path = self.dir_results[index]
            self.current_result = result
            self.current_source = source
            self.file_selected.emit(result, source, path)

    def reload(self) -> None:
        """Re-analyze the current target."""
        if self.current_path is not None:
            if self.is_directory:
                self.load_directory(self.current_path)
            else:
                self.load_file(self.current_path)

    def _stop_workers(self) -> None:
        for w in (self._worker, self._dir_worker):
            if w is not None and w.isRunning():
                w.terminate()
                w.wait()

    def _on_finished(self, result: object, source: str, path: str) -> None:
        self.current_result = result
        self.current_source = source
        self.file_loaded.emit(result, source, path)

    def _on_dir_file_analyzed(self, result: object, source: str, path: str) -> None:
        self.dir_results = self.dir_results + [(result, source, path)]

    def _on_dir_progress(self, current: int, total: int) -> None:
        self.analysis_progress.emit(current, total)

    def _on_dir_finished(self, results: list, dir_path: str) -> None:
        self.dir_results = results
        self.directory_loaded.emit(results, dir_path)
        # Auto-select first file
        if results:
            self.select_file(0)

    def _on_error(self, message: str) -> None:
        self.analysis_error.emit(message)
