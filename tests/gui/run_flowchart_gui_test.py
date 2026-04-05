"""Full GUI flowchart interaction test — launch, click, switch functions, verify."""

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])

from orionparser.gui.main_window import MainWindow
from orionparser.gui.widgets.graph_canvas import _FlowchartNodeItem
from orionparser.registry import get_pipeline
from orionparser.core.encoding import read_file

SS = Path(__file__).parent / "screenshots" / "flowchart_gui"
SS.mkdir(parents=True, exist_ok=True)

issues: list[str] = []


def grab(win, name):
    win.grab().save(str(SS / f"{name}.png"))


def check(name, cond, msg=""):
    if not cond:
        issues.append(f"{name}: {msg}")
        print(f"  FAIL: {name} — {msg}")
    else:
        print(f"  OK: {name}")


# === Setup: load a file with multiple functions ===
source = (
    "def validate(data):\n"
    '    """Validate input data."""\n'
    "    if not data:\n"
    '        raise ValueError("empty")\n'
    "    return True\n"
    "\n"
    "def transform(items):\n"
    "    result = []\n"
    "    for item in items:\n"
    "        if item > 0:\n"
    "            result.append(item)\n"
    "        else:\n"
    '            print("skip")\n'
    "    return result\n"
    "\n"
    "def process(path):\n"
    "    data = open(path).read()\n"
    "    items = data.split('\\n')\n"
    "    valid = validate(items)\n"
    "    if valid:\n"
    "        output = transform(items)\n"
    "        print(output)\n"
    "    return output\n"
)

p = Path("_fc_gui_test.py")
p.write_text(source, encoding="utf-8")
pipeline = get_pipeline(p)
result = pipeline.analyze_file(p)
src_text = read_file(p)

win = MainWindow()
win.resize(1280, 800)
win.show()
QTest.qWaitForWindowExposed(win)
win._on_file_loaded(result, src_text, str(p))
QTest.qWait(300)

# === 1. Switch to graph mode ===
print("1. Switch to graph mode")
win._switch_mode(1)
QTest.qWait(200)
grab(win, "01_graph_mode")

# === 2. Select flowchart from graph type selector ===
print("2. Select flowchart")
selector = win._graph_view._selector
# Find flowchart item
fc_row = -1
for i in range(selector.count()):
    if selector.item(i).text() == "フローチャート":
        fc_row = i
        break
check("flowchart_in_selector", fc_row >= 0, f"row={fc_row}")
if fc_row >= 0:
    selector.setCurrentRow(fc_row)
    QTest.qWait(300)
grab(win, "02_flowchart_selected")

# === 3. Verify flowchart nodes exist ===
print("3. Verify nodes")
canvas = win._graph_view.canvas
node_count = len(canvas._node_items)
check("has_nodes", node_count > 0, f"got {node_count}")
print(f"    Node count: {node_count}")

# Check for JIS shapes
shape_types = set()
for item in canvas._node_items.values():
    if isinstance(item, _FlowchartNodeItem):
        shape_types.add(item._shape_type)
print(f"    Shape types: {shape_types}")
check("has_start_shape", "rounded" in shape_types, f"shapes={shape_types}")
check("has_rect_shape", "rect" in shape_types or "process" in shape_types, f"shapes={shape_types}")

# === 4. Verify function selector has functions ===
print("4. Function selector")
func_combo = win._graph_view._focus_combo
func_count = func_combo.count()
func_names = [func_combo.itemText(i) for i in range(func_count)]
print(f"    Functions: {func_names}")
check("has_functions", func_count >= 4, f"count={func_count}")
check("has_validate", any("validate" in f for f in func_names), str(func_names))
check("has_transform", any("transform" in f for f in func_names), str(func_names))
check("has_process", any("process" in f for f in func_names), str(func_names))

# === 5. Switch to 'transform' function ===
print("5. Switch to transform")
for i in range(func_combo.count()):
    if func_combo.itemData(i) == "transform":
        func_combo.setCurrentIndex(i)
        win._graph_view._on_focus_selected(i)
        QTest.qWait(300)
        break
grab(win, "03_transform_flowchart")

transform_nodes = len(canvas._node_items)
print(f"    Transform nodes: {transform_nodes}")
check("transform_has_nodes", transform_nodes > 0, f"got {transform_nodes}")

# Check transform has loop + decision
t_shapes = set()
for item in canvas._node_items.values():
    if isinstance(item, _FlowchartNodeItem):
        t_shapes.add(item._shape_type)
print(f"    Transform shapes: {t_shapes}")
check("transform_has_loop", "trap_top" in t_shapes, f"shapes={t_shapes}")
check("transform_has_decision", "diamond" in t_shapes, f"shapes={t_shapes}")
check("transform_has_io", "parallelogram" in t_shapes, f"shapes={t_shapes}")

# === 6. Switch to 'validate' function ===
print("6. Switch to validate")
for i in range(func_combo.count()):
    if func_combo.itemData(i) == "validate":
        func_combo.setCurrentIndex(i)
        win._graph_view._on_focus_selected(i)
        QTest.qWait(300)
        break
grab(win, "04_validate_flowchart")

v_nodes = len(canvas._node_items)
print(f"    Validate nodes: {v_nodes}")
check("validate_has_decision", any(
    isinstance(item, _FlowchartNodeItem) and item._shape_type == "diamond"
    for item in canvas._node_items.values()
), "no diamond")

# === 7. Switch to 'process' function ===
print("7. Switch to process")
for i in range(func_combo.count()):
    if func_combo.itemData(i) == "process":
        func_combo.setCurrentIndex(i)
        win._graph_view._on_focus_selected(i)
        QTest.qWait(300)
        break
grab(win, "05_process_flowchart")

pr_nodes = len(canvas._node_items)
print(f"    Process nodes: {pr_nodes}")

# === 8. Node positions — all x >= 0 ===
print("8. Position check")
for nid, item in canvas._node_items.items():
    x = item.pos().x() - item._width / 2
    check(f"x_pos_{nid}", x >= -5, f"x={x:.0f}")

# === 9. Click a node — detail panel updates ===
print("9. Node click")
detail = win._graph_view._detail
if canvas._node_items:
    first_nid = next(iter(canvas._node_items))
    canvas.node_selected.emit(first_nid)
    QTest.qWait(100)
    detail_text = detail.toPlainText()
    check("detail_updated", len(detail_text) > 0, "detail empty after click")
    print(f"    Detail: {detail_text[:60]}...")

# === 10. Switch back to call tree, then back to flowchart ===
print("10. Mode round trip")
selector.setCurrentRow(0)  # call tree
QTest.qWait(200)
ct_nodes = len(canvas._node_items)
check("calltree_has_nodes", ct_nodes > 0, f"got {ct_nodes}")

selector.setCurrentRow(fc_row)  # flowchart
QTest.qWait(200)
fc_nodes2 = len(canvas._node_items)
check("flowchart_restored", fc_nodes2 > 0, f"got {fc_nodes2}")
grab(win, "06_round_trip")

# === 11. Switch back to code mode and verify source still there ===
print("11. Code mode check")
win._switch_mode(0)
QTest.qWait(100)
src = win._code_view.source_viewer.toPlainText()
check("source_preserved", "def validate" in src, "source lost")

# === 12. Real code test ===
print("12. Real code test")
real_p = Path("src/orionparser/analysis/symbols.py")
if real_p.exists():
    real_result = get_pipeline(real_p).analyze_file(real_p)
    real_src = read_file(real_p)
    win._on_file_loaded(real_result, real_src, str(real_p))
    QTest.qWait(300)
    win._switch_mode(1)
    QTest.qWait(200)
    selector.setCurrentRow(fc_row)
    QTest.qWait(300)
    real_nodes = len(canvas._node_items)
    print(f"    Real code nodes: {real_nodes}")
    check("real_code_has_nodes", real_nodes > 3, f"got {real_nodes}")
    grab(win, "07_real_code_flowchart")

    # Switch functions
    for i in range(func_combo.count()):
        fname = func_combo.itemData(i)
        if fname and fname not in ("", "(全体を表示)"):
            func_combo.setCurrentIndex(i)
            win._graph_view._on_focus_selected(i)
            QTest.qWait(200)
            fn = len(canvas._node_items)
            check(f"func_{fname}", fn > 0, f"{fname}: {fn} nodes")
            grab(win, f"08_func_{fname}")

p.unlink(missing_ok=True)

print("\n" + "=" * 50)
if issues:
    print(f"ISSUES: {len(issues)}")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")
    sys.exit(1)
else:
    print("ALL GUI FLOWCHART CHECKS PASSED")
    sys.exit(0)
