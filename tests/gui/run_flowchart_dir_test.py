"""Test flowchart in directory mode — file selection, function switching."""

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])

from orionparser.gui.main_window import MainWindow
from orionparser.gui.widgets.graph_canvas import _FlowchartNodeItem
from orionparser.registry import get_pipeline
from orionparser.core.encoding import read_file

SS = Path(__file__).parent / "screenshots" / "flowchart_dir"
SS.mkdir(parents=True, exist_ok=True)

issues: list[str] = []


def grab(win, name):
    win.grab().save(str(SS / f"{name}.png"))


def check(name, cond, msg=""):
    if not cond:
        issues.append(f"{name}: {msg}")
        print(f"  FAIL: {name} - {msg}")
    else:
        print(f"  OK: {name}")


# === Load directory ===
print("1. Load directory")
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
win._viewmodel.dir_results = results
win._viewmodel.is_directory = True
win._on_directory_loaded(results, str(analysis_dir))
QTest.qWait(300)

check("files_loaded", win._file_list.count() == len(results), f"got {win._file_list.count()}")
grab(win, "01_dir_loaded")

# === 2. Switch to graph mode ===
print("2. Graph mode")
win._switch_mode(1)
QTest.qWait(200)

# === 3. Select flowchart ===
print("3. Select flowchart")
selector = win._graph_view._selector
fc_row = -1
for i in range(selector.count()):
    item = selector.item(i)
    if item and item.data(Qt.ItemDataRole.UserRole) == "flowchart":
        fc_row = i
        break
check("flowchart_enabled", fc_row >= 0, f"row={fc_row}")
selector.setCurrentRow(fc_row)
QTest.qWait(300)

# === 4. Verify function list populated ===
print("4. Function list")
combo = win._graph_view._focus_combo
func_count = combo.count()
func_names = [combo.itemText(i) for i in range(func_count)]
print(f"    Functions ({func_count}): {func_names[:8]}...")
check("has_functions", func_count >= 2, f"only {func_count}")
check("has_nodes", len(win._graph_view.canvas._node_items) > 0,
      f"nodes={len(win._graph_view.canvas._node_items)}")
grab(win, "02_flowchart_selected")

# === 5. Switch to each function and verify ===
print("5. Switch functions")
for i in range(combo.count()):
    fname = combo.itemData(i)
    if not fname:
        continue
    combo.setCurrentIndex(i)
    win._graph_view._on_focus_selected(i)
    QTest.qWait(200)
    nodes = len(win._graph_view.canvas._node_items)
    check(f"func_{fname}", nodes > 0, f"0 nodes for {fname}")
    print(f"    {fname}: {nodes} nodes")
    grab(win, f"03_func_{fname}")

# === 6. Select different file from file list ===
print("6. File switching")
if win._file_list.count() >= 2:
    win._file_list.setCurrentRow(1)
    QTest.qWait(300)
    # Flowchart should update for new file
    new_combo_count = combo.count()
    check("file_switch_updates_funcs", new_combo_count >= 2,
          f"combo has {new_combo_count} after file switch")
    new_nodes = len(win._graph_view.canvas._node_items)
    check("file_switch_has_nodes", new_nodes > 0, f"nodes={new_nodes}")
    grab(win, "04_file_switched")

    # Select a function in the new file
    for i in range(combo.count()):
        fname = combo.itemData(i)
        if fname:
            combo.setCurrentIndex(i)
            win._graph_view._on_focus_selected(i)
            QTest.qWait(200)
            fn = len(win._graph_view.canvas._node_items)
            check(f"new_file_func_{fname}", fn > 0, f"0 nodes")
            grab(win, f"05_new_file_{fname}")
            break

# === 7. Switch back to call tree and back ===
print("7. Round trip")
selector.setCurrentRow(0)
QTest.qWait(200)
ct_nodes = len(win._graph_view.canvas._node_items)
check("calltree_works", ct_nodes > 0, f"nodes={ct_nodes}")

selector.setCurrentRow(fc_row)
QTest.qWait(300)
fc_nodes = len(win._graph_view.canvas._node_items)
check("flowchart_restored", fc_nodes > 0, f"nodes={fc_nodes}")

# === 8. Position check ===
print("8. Positions")
for nid, item in win._graph_view.canvas._node_items.items():
    x = item.pos().x() - item._width / 2
    if x < -5:
        check(f"pos_{nid}", False, f"x={x:.0f}")
        break
else:
    check("all_positions_ok", True)

# === 9. No QPainter should happen ===
print("9. Final screenshot")
grab(win, "06_final")

print("\n" + "=" * 50)
if issues:
    print(f"ISSUES: {len(issues)}")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")
    sys.exit(1)
else:
    print("ALL DIRECTORY FLOWCHART CHECKS PASSED")
    sys.exit(0)
