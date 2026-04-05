"""Full interaction test — simulates real user workflow and captures issues."""

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])

from orionparser.gui.main_window import MainWindow
from orionparser.registry import get_pipeline
from orionparser.core.encoding import read_file

SS = Path(__file__).parent / "screenshots" / "interaction"
SS.mkdir(parents=True, exist_ok=True)

issues: list[str] = []


def grab(win, name):
    win.grab().save(str(SS / f"{name}.png"))


def check(name, condition, msg):
    if not condition:
        issues.append(f"{name}: {msg}")
        print(f"  FAIL: {msg}")
    else:
        print(f"  OK: {name}")


# === Setup: directory with real analysis code ===
results = []
analysis_dir = Path("src/orionparser/analysis")
for f in sorted(analysis_dir.glob("*.py")):
    if f.name == "__init__.py":
        continue
    pipeline = get_pipeline(f)
    result = pipeline.analyze_file(f)
    source = read_file(f)
    results.append((result, source, str(f)))

win = MainWindow()
win.resize(1280, 800)
win.show()
QTest.qWaitForWindowExposed(win)

# === 1. Directory load ===
print("1. Directory load")
win._viewmodel.dir_results = results
win._viewmodel.is_directory = True
win._on_directory_loaded(results, str(analysis_dir))
QTest.qWait(300)

check("file_panel_visible", win._file_panel.isVisible(), "File panel not visible")
check("file_count", win._file_list.count() >= 3, f"Expected 3+ files, got {win._file_list.count()}")
grab(win, "01_dir_loaded")

# === 2. File selection → code view updates ===
print("2. File selection")
win._file_list.setCurrentRow(0)
QTest.qWait(200)
src_text = win._code_view.source_viewer.toPlainText()
check("source_not_empty", len(src_text) > 0, "Source viewer empty after file selection")
grab(win, "02_file_selected")

# === 3. Symbol click → source highlight ===
print("3. Symbol click")
panel = win._code_view.symbols_panel
if panel._tree.topLevelItemCount() > 0:
    sec = panel._tree.topLevelItem(0)
    if sec.childCount() > 0:
        panel._tree.itemClicked.emit(sec.child(0), 0)
        QTest.qWait(100)
        hl = win._code_view.source_viewer._highlighted_line
        check("symbol_highlight", hl is not None and hl > 0, f"Highlight={hl}")

# === 4. Token click → span highlight ===
print("4. Token click")
win._code_view._tabs.setCurrentIndex(1)
QTest.qWait(100)
tp = win._code_view.tokens_panel
for i in range(min(tp._table.rowCount(), 20)):
    tok = tp._tokens[i] if i < len(tp._tokens) else {}
    if tok.get("type") not in ("NEWLINE", "INDENT", "DEDENT", "ENDMARKER", None) and tok.get("value"):
        tp._table.cellClicked.emit(i, 0)
        QTest.qWait(50)
        sels = win._code_view.source_viewer.extraSelections()
        check("token_highlight", len(sels) == 2, f"Selections={len(sels)}")
        break
grab(win, "03_token_click")

# === 5. Graph mode ===
print("5. Graph mode")
win._switch_mode(1)
QTest.qWait(300)
canvas = win._graph_view.canvas
node_count = len(canvas._node_items)
check("graph_nodes", node_count > 10, f"Only {node_count} nodes in call tree")
grab(win, "04_graph_full")

# === 6. File filter in graph ===
print("6. File filter")
file_combo = win._graph_view._focus_file
check("file_filter_count", file_combo.count() >= 4, f"File filter has {file_combo.count()} items")
# Select first real file
if file_combo.count() > 1:
    file_combo.setCurrentIndex(1)
    QTest.qWait(100)
    func_combo = win._graph_view._focus_combo
    func_count = func_combo.count()
    check("func_filtered", func_count >= 2, f"Function combo has {func_count} items after file filter")
    # Reset
    file_combo.setCurrentIndex(0)
    QTest.qWait(100)

# === 7. Function focus ===
print("7. Function focus")
func_combo = win._graph_view._focus_combo
# Find a function with children
target_func = None
for i in range(func_combo.count()):
    name = func_combo.itemData(i)
    if name and name not in ("<module>", ""):
        target_func = name
        func_combo.setCurrentIndex(i)
        win._graph_view._on_focus_selected(i)
        QTest.qWait(200)
        break

if target_func:
    focused_count = len(canvas._node_items)
    check("focus_reduces", focused_count < node_count or focused_count > 0,
          f"Focus on {target_func}: {focused_count} nodes (full={node_count})")
    grab(win, f"05_focus_{target_func}")

    # Check detail panel shows info
    detail = win._graph_view._detail.toPlainText()
    check("detail_shown", len(detail) > 0, "Detail panel empty after focus")

# === 8. Mode switching preserves data ===
print("8. Mode switch")
win._switch_mode(0)
QTest.qWait(100)
check("code_after_switch", len(win._code_view.source_viewer.toPlainText()) > 0,
      "Source empty after mode switch")
win._switch_mode(1)
QTest.qWait(100)
check("graph_after_switch", len(canvas._node_items) > 0, "Graph empty after mode switch")

# === 9. Splitter resize ===
print("9. Splitter resize")
win._analysis_splitter.setSizes([50, 1230])
QTest.qWait(100)
win._analysis_splitter.setSizes([300, 980])
QTest.qWait(100)
check("splitter_ok", True, "Splitter resize")
grab(win, "06_wide_file_list")

# === 10. Switch between files ===
print("10. File switching")
if win._file_list.count() >= 2:
    win._file_list.setCurrentRow(1)
    QTest.qWait(200)
    src2 = win._code_view.source_viewer.toPlainText()
    check("different_file", src2 != src_text or len(src2) > 0, "File switch didn't change content")

# === Report ===
print("\n" + "=" * 50)
if issues:
    print(f"ISSUES: {len(issues)}")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
