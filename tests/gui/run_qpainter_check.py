"""Standalone script to check for QPainter errors at C-level stderr."""

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])

from orionparser.gui.main_window import MainWindow

win = MainWindow()
win.show()
QTest.qWaitForWindowExposed(win)

# Create test file
p = Path("_qp_test_file.py")
p.write_text(
    "import os\nimport sys\n\n"
    "def main():\n    x = 1\n    print(x)\n\n"
    "class Config:\n    name = 'app'\n\nmain()\n",
    encoding="utf-8",
)

# Load file
from orionparser.registry import get_pipeline

pipeline = get_pipeline(p)
result = pipeline.analyze_file(p)
source = p.read_text(encoding="utf-8")

print("1. Loading file...", flush=True)
win._on_file_loaded(result, source, str(p))
QTest.qWait(200)

print("2. Symbols tab...", flush=True)
win._code_view._tabs.setCurrentIndex(0)
QTest.qWait(100)

# Click symbol
panel = win._code_view.symbols_panel
if panel._tree.topLevelItemCount() > 0:
    sec = panel._tree.topLevelItem(0)
    if sec.childCount() > 0:
        panel._tree.itemClicked.emit(sec.child(0), 0)
        QTest.qWait(100)

print("3. Tokens tab...", flush=True)
win._code_view._tabs.setCurrentIndex(1)
QTest.qWait(100)

# Click token
tp = win._code_view.tokens_panel
if tp._table.rowCount() > 0:
    tp._table.cellClicked.emit(0, 0)
    QTest.qWait(100)

print("4. AST tab...", flush=True)
win._code_view._tabs.setCurrentIndex(2)
QTest.qWait(100)

print("5. Graph mode...", flush=True)
win._switch_mode(1)
QTest.qWait(200)

print("6. Data flow...", flush=True)
win._graph_view._selector.setCurrentRow(1)
QTest.qWait(200)

print("7. Back to code...", flush=True)
win._switch_mode(0)
QTest.qWait(100)

print("8. Resize window...", flush=True)
win.resize(800, 600)
QTest.qWait(200)
win.resize(1280, 800)
QTest.qWait(200)

p.unlink(missing_ok=True)
print("ALL DONE", flush=True)
sys.exit(0)
