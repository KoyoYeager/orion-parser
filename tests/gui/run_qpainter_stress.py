"""Stress test for QPainter — edge cases that trigger paint on zero-size widgets."""

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])

from orionparser.gui.main_window import MainWindow

errors_found = 0

def test_case(name):
    print(f"  {name}...", end=" ", flush=True)

def ok():
    print("OK", flush=True)

# --- 1. Open window without loading any file ---
test_case("1. Empty window show/resize")
win = MainWindow()
win.show()
QTest.qWaitForWindowExposed(win)
win.resize(400, 300)
QTest.qWait(50)
win.resize(1, 1)      # extreme small
QTest.qWait(50)
win.resize(1280, 800)  # back to normal
QTest.qWait(50)
ok()

# --- 2. Load empty file ---
test_case("2. Empty file")
p = Path("_stress_empty.py")
p.write_text("", encoding="utf-8")
from orionparser.registry import get_pipeline
pipeline = get_pipeline(p)
result = pipeline.analyze_file(p)
win._on_file_loaded(result, "", str(p))
QTest.qWait(100)
p.unlink(missing_ok=True)
ok()

# --- 3. Rapid tab switching ---
test_case("3. Rapid tab switching")
p2 = Path("_stress_code.py")
p2.write_text("def f(): pass\nf()\n", encoding="utf-8")
pipeline2 = get_pipeline(p2)
result2 = pipeline2.analyze_file(p2)
source2 = p2.read_text(encoding="utf-8")
win._on_file_loaded(result2, source2, str(p2))
QTest.qWait(50)

for _ in range(10):
    win._code_view._tabs.setCurrentIndex(0)
    QTest.qWait(10)
    win._code_view._tabs.setCurrentIndex(1)
    QTest.qWait(10)
    win._code_view._tabs.setCurrentIndex(2)
    QTest.qWait(10)
ok()

# --- 4. Rapid mode switching ---
test_case("4. Rapid mode switching")
for _ in range(10):
    win._switch_mode(0)
    QTest.qWait(10)
    win._switch_mode(1)
    QTest.qWait(10)
ok()

# --- 5. Minimize-sized window with data ---
test_case("5. Tiny window with data")
win.resize(50, 50)
QTest.qWait(100)
win._code_view._tabs.setCurrentIndex(0)
QTest.qWait(50)
win._code_view._tabs.setCurrentIndex(1)
QTest.qWait(50)
win._switch_mode(1)
QTest.qWait(50)
win.resize(1280, 800)
QTest.qWait(100)
ok()

# --- 6. Load file then immediately resize ---
test_case("6. Load + immediate resize")
win._on_file_loaded(result2, source2, str(p2))
win.resize(200, 100)
QTest.qWait(50)
win.resize(1280, 800)
QTest.qWait(100)
ok()

# --- 7. Source viewer highlight on zero-height ---
test_case("7. Highlight on tiny viewer")
win.resize(100, 30)
QTest.qWait(50)
win._code_view.source_viewer.highlight_line(1)
QTest.qWait(50)
win._code_view.source_viewer.highlight_span(0, 3)
QTest.qWait(50)
win.resize(1280, 800)
QTest.qWait(100)
ok()

# --- 8. Graph canvas with no data ---
test_case("8. Graph canvas fit_to_view on empty")
win._graph_view.canvas.clear_graph()
win._graph_view.canvas.fit_to_view()
QTest.qWait(50)
ok()

# --- 9. Screenshot capture (grab) ---
test_case("9. Screenshot grab")
win._code_view._tabs.setCurrentIndex(0)
QTest.qWait(50)
pixmap = win.grab()
assert not pixmap.isNull()
ok()

p2.unlink(missing_ok=True)
print("ALL STRESS TESTS PASSED", flush=True)
sys.exit(0)
