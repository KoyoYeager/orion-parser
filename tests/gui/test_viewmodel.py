"""Tests for AnalysisViewModel, AnalysisWorker, DirectoryWorker."""

from __future__ import annotations

import pytest


class TestDirectoryWorker:
    def test_directory_analyzes_all_files(self, qtbot, sample_dir):
        from orionparser.gui.viewmodel import DirectoryWorker

        worker = DirectoryWorker(str(sample_dir))
        with qtbot.waitSignal(worker.all_finished, timeout=15000) as blocker:
            worker.start()

        worker.wait()
        results, dir_path = blocker.args
        assert len(results) == 3  # main.py, utils.py, sub/deep.py
        assert str(sample_dir) == dir_path

    def test_directory_emits_progress(self, qtbot, sample_dir):
        from orionparser.gui.viewmodel import DirectoryWorker

        worker = DirectoryWorker(str(sample_dir))
        progress_values = []
        worker.progress.connect(lambda cur, tot: progress_values.append((cur, tot)))

        with qtbot.waitSignal(worker.all_finished, timeout=15000):
            worker.start()

        worker.wait()
        assert len(progress_values) == 3
        assert progress_values[-1] == (3, 3)


class TestAnalysisWorker:
    def test_worker_success(self, qtbot, sample_file):
        from orionparser.gui.viewmodel import AnalysisWorker

        worker = AnalysisWorker(str(sample_file))
        with qtbot.waitSignal(worker.finished, timeout=10000) as blocker:
            worker.start()

        worker.wait()  # ensure thread finishes

        result, source, path = blocker.args
        assert result.success is True
        assert result.ast is not None
        assert len(result.tokens) > 0
        assert "def main" in source
        assert str(sample_file) == path

    def test_worker_error(self, qtbot, tmp_path):
        from orionparser.gui.viewmodel import AnalysisWorker

        worker = AnalysisWorker(str(tmp_path / "nonexistent.py"))
        with qtbot.waitSignal(worker.error, timeout=10000) as blocker:
            worker.start()

        worker.wait()
        assert len(blocker.args[0]) > 0


class TestAnalysisViewModel:
    def test_load_file_emits_file_loaded(self, qtbot, sample_file):
        from orionparser.gui.viewmodel import AnalysisViewModel

        vm = AnalysisViewModel()

        with qtbot.waitSignal(vm.file_loaded, timeout=10000) as blocker:
            vm.load_file(str(sample_file))

        if vm._worker:
            vm._worker.wait()

        result, source, path = blocker.args
        assert result.success is True
        assert "def main" in source

    def test_load_file_emits_started(self, qtbot, sample_file):
        from orionparser.gui.viewmodel import AnalysisViewModel

        vm = AnalysisViewModel()

        with qtbot.waitSignal(vm.analysis_started, timeout=5000):
            vm.load_file(str(sample_file))

        if vm._worker:
            vm._worker.wait()

    def test_load_nonexistent_emits_error(self, qtbot, tmp_path):
        from orionparser.gui.viewmodel import AnalysisViewModel

        vm = AnalysisViewModel()

        with qtbot.waitSignal(vm.analysis_error, timeout=10000):
            vm.load_file(str(tmp_path / "no_such_file.py"))

        if vm._worker:
            vm._worker.wait()

    def test_reload(self, qtbot, sample_file):
        from orionparser.gui.viewmodel import AnalysisViewModel

        vm = AnalysisViewModel()

        with qtbot.waitSignal(vm.file_loaded, timeout=10000):
            vm.load_file(str(sample_file))

        if vm._worker:
            vm._worker.wait()

        with qtbot.waitSignal(vm.file_loaded, timeout=10000):
            vm.reload()

        if vm._worker:
            vm._worker.wait()

    def test_load_directory_emits_directory_loaded(self, qtbot, sample_dir):
        from orionparser.gui.viewmodel import AnalysisViewModel

        vm = AnalysisViewModel()

        with qtbot.waitSignal(vm.directory_loaded, timeout=15000) as blocker:
            vm.load_directory(str(sample_dir))

        if vm._dir_worker:
            vm._dir_worker.wait()

        results, dir_path = blocker.args
        assert len(results) == 3
        assert vm.is_directory is True

    def test_load_directory_auto_selects_first(self, qtbot, sample_dir):
        from orionparser.gui.viewmodel import AnalysisViewModel

        vm = AnalysisViewModel()

        with qtbot.waitSignal(vm.file_selected, timeout=15000) as blocker:
            vm.load_directory(str(sample_dir))

        if vm._dir_worker:
            vm._dir_worker.wait()

        result, source, path = blocker.args
        assert getattr(result, "success", False) is True

    def test_select_file_from_directory(self, qtbot, sample_dir):
        from orionparser.gui.viewmodel import AnalysisViewModel

        vm = AnalysisViewModel()

        with qtbot.waitSignal(vm.directory_loaded, timeout=15000):
            vm.load_directory(str(sample_dir))

        if vm._dir_worker:
            vm._dir_worker.wait()

        # Select second file
        with qtbot.waitSignal(vm.file_selected, timeout=5000) as blocker:
            vm.select_file(1)

        result, source, path = blocker.args
        assert getattr(result, "success", False) is True
