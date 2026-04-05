"""Usability audit — launch GUI, interact with every feature, report issues."""

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])

from orionparser.gui.main_window import MainWindow

SCREENSHOT_DIR = Path(__file__).parent / "screenshots" / "usability"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

issues: list[str] = []


def grab(win, name):
    win.grab().save(str(SCREENSHOT_DIR / f"{name}.png"))


# --- Setup ---
source = (
    "import os\nimport sys\nfrom pathlib import Path\n\n"
    "def validate(data):\n    if not data:\n        raise ValueError('empty')\n    return True\n\n"
    "def transform(items):\n    result = []\n    for item in items:\n        validate(item)\n        result.append(item.upper())\n    return result\n\n"
    "def load_config(path):\n    with open(path) as f:\n        return f.read()\n\n"
    "def save_output(data, path):\n    with open(path, 'w') as f:\n        f.write(data)\n\n"
    "def process(input_path, output_path):\n    config = load_config(input_path)\n"
    "    items = config.split('\\n')\n    transformed = transform(items)\n"
    "    save_output('\\n'.join(transformed), output_path)\n\n"
    "def main():\n    process('input.txt', 'output.txt')\n    print('done')\n\n"
    "main()\n"
)

p = Path("_usability_test.py")
p.write_text(source, encoding="utf-8")

from orionparser.registry import get_pipeline

pipeline = get_pipeline(p)
result = pipeline.analyze_file(p)

win = MainWindow()
win.show()
QTest.qWaitForWindowExposed(win)
win._on_file_loaded(result, source, str(p))
QTest.qWait(300)

# === 1. Code Analysis Mode ===
print("=== CODE ANALYSIS ===")

# Check symbols panel
panel = win._code_view.symbols_panel
total_syms = sum(panel._tree.topLevelItem(i).childCount() for i in range(panel._tree.topLevelItemCount()))
print(f"  Symbols: {total_syms} items in {panel._tree.topLevelItemCount()} sections")
grab(win, "01_symbols")

# Click a symbol — does source highlight?
func_sec = panel._sections.get("function")
if func_sec and func_sec.childCount() > 0:
    child = func_sec.child(0)
    panel._tree.itemClicked.emit(child, 0)
    QTest.qWait(100)
    hl = win._code_view.source_viewer._highlighted_line
    print(f"  Symbol click -> highlighted line: {hl}")
    if hl is None:
        issues.append("Symbol click did not highlight source line")
    grab(win, "02_symbol_click")

# Switch to tokens
win._code_view._tabs.setCurrentIndex(1)
QTest.qWait(100)
tp = win._code_view.tokens_panel
print(f"  Tokens: {tp._table.rowCount()} rows")
# Click first meaningful token
for i in range(tp._table.rowCount()):
    tok = tp._tokens[i] if i < len(tp._tokens) else {}
    if tok.get("type") not in ("NEWLINE", "INDENT", "DEDENT", "ENDMARKER", None) and tok.get("value"):
        tp._table.cellClicked.emit(i, 0)
        QTest.qWait(100)
        sels = win._code_view.source_viewer.extraSelections()
        print(f"  Token click (row {i}, {tok['type']}={tok['value']!r}) -> {len(sels)} selections")
        if len(sels) < 2:
            issues.append(f"Token click produced {len(sels)} selections, expected 2")
        grab(win, "03_token_click")
        break

# Switch to AST
win._code_view._tabs.setCurrentIndex(2)
QTest.qWait(100)
ap = win._code_view.ast_panel
print(f"  AST: {ap._tree.topLevelItemCount()} root items")
grab(win, "04_ast")

# === 2. Graph Analysis Mode ===
print("\n=== GRAPH ANALYSIS ===")
win._switch_mode(1)
QTest.qWait(200)

canvas = win._graph_view.canvas
node_count = len(canvas._node_items)
print(f"  Call tree nodes: {node_count}")
print(f"  Node names: {list(canvas._node_items.keys())}")
grab(win, "05_call_tree")

if node_count == 0:
    issues.append("Call tree has 0 nodes")

# Check hierarchy headers
from PySide6.QtWidgets import QGraphicsSimpleTextItem
headers = [item for item in canvas._scene.items()
           if isinstance(item, QGraphicsSimpleTextItem) and "階層" in item.text()]
print(f"  Hierarchy headers: {len(headers)}")

# Check focus UI exists
focus_combo = win._graph_view._focus_combo
func_items = [focus_combo.itemText(i) for i in range(focus_combo.count())]
print(f"  Focus combo items: {len(func_items)} ({func_items[:5]}...)")
if len(func_items) < 2:
    issues.append("Focus combo has too few items")

# Test that combo is editable (searchable)
print(f"  Combo editable: {focus_combo.isEditable()}")
if not focus_combo.isEditable():
    issues.append("Focus combo is not editable (not searchable)")

# Test focus selection
for i in range(focus_combo.count()):
    if focus_combo.itemData(i) == "process":
        focus_combo.setCurrentIndex(i)
        win._graph_view._on_focus_selected(i)
        QTest.qWait(200)
        break
focused_count = len(canvas._node_items)
print(f"  Focus 'process' -> {focused_count} nodes")
grab(win, "06_focus_process")
if focused_count >= node_count:
    issues.append(f"Focus did not reduce nodes: {focused_count} >= {node_count}")

# Reset
focus_combo.setCurrentIndex(0)
win._graph_view._on_focus_selected(0)
QTest.qWait(200)
reset_count = len(canvas._node_items)
print(f"  Reset -> {reset_count} nodes")
if reset_count != node_count:
    issues.append(f"Reset did not restore nodes: {reset_count} != {node_count}")

# Test graph type switch
win._graph_view._selector.setCurrentRow(1)  # data flow
QTest.qWait(200)
df_count = len(canvas._node_items)
print(f"  Data flow nodes: {df_count}")
grab(win, "07_data_flow")

# Switch back
win._graph_view._selector.setCurrentRow(0)
QTest.qWait(200)

# Test export dropdown
export_combo = win._graph_view._export_combo
export_count = export_combo.count()
print(f"  Export formats: {export_count}")
grab(win, "08_export_options")

# === 3. Layout check ===
print("\n=== LAYOUT CHECKS ===")
# Check nodes don't overlap
positions = {}
for nid, item in canvas._node_items.items():
    x, y = round(item.pos().x()), round(item.pos().y())
    if (x, y) in positions:
        issues.append(f"Nodes overlap at ({x},{y}): {nid} and {positions[(x,y)]}")
    positions[(x, y)] = nid
print(f"  Node positions: {len(positions)} unique (of {len(canvas._node_items)})")

# Check L-shape connectors exist
from PySide6.QtWidgets import QGraphicsPathItem
path_items = [item for item in canvas._scene.items() if isinstance(item, QGraphicsPathItem)]
print(f"  Connector paths: {len(path_items)}")
# Check connectors have >= 3 elements (L-shape)
for pi in path_items:
    if pi.path().elementCount() < 3:
        issues.append(f"Connector has only {pi.path().elementCount()} elements (not L-shaped)")
        break

# === 4. Status bar ===
print("\n=== STATUS BAR ===")
status = win._status_label.text()
print(f"  Status: {status}")
if "関数:" not in status:
    issues.append(f"Status bar missing function count: {status}")

# === Report ===
p.unlink(missing_ok=True)

print("\n" + "=" * 50)
if issues:
    print(f"ISSUES FOUND: {len(issues)}")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")
    sys.exit(1)
else:
    print("NO ISSUES FOUND")
    sys.exit(0)
