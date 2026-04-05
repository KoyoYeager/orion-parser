"""Test ALL graph types in GUI — calltree, dataflow, flowchart, class diagram."""

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

SS = Path(__file__).parent / "screenshots" / "all_types"
SS.mkdir(parents=True, exist_ok=True)

issues: list[str] = []


def check(name, cond, msg=""):
    if not cond:
        issues.append(f"{name}: {msg}")
        print(f"  FAIL: {name} - {msg}")
    else:
        print(f"  OK: {name}")


# Setup - load symbols.py (has classes + functions)
p = Path("src/orionparser/analysis/symbols.py")
result = get_pipeline(p).analyze_file(p)
source = read_file(p)

win = MainWindow()
win.resize(1280, 800)
win.show()
QTest.qWaitForWindowExposed(win)
win._on_file_loaded(result, source, str(p))
QTest.qWait(300)
win._switch_mode(1)
QTest.qWait(200)

selector = win._graph_view._selector

# === Test each graph type ===
graph_types = {
    "call_tree": "コールツリー",
    "data_flow": "データフロー",
    "flowchart": "フローチャート",
    "class_diagram": "クラス図",
}

for gid, name in graph_types.items():
    print(f"\n--- {name} ({gid}) ---")

    # Find and select
    found = False
    for i in range(selector.count()):
        item = selector.item(i)
        if item and item.data(Qt.ItemDataRole.UserRole) == gid:
            selector.setCurrentRow(i)
            QTest.qWait(300)
            found = True
            break
    check(f"{gid}_found", found, "not in selector")

    # Check nodes
    canvas = win._graph_view.canvas
    nodes = len(canvas._node_items)
    check(f"{gid}_has_nodes", nodes > 0, f"0 nodes")
    print(f"    Nodes: {nodes}")

    # Check active panel
    panel = win._graph_view._active_panel()
    check(f"{gid}_panel", panel is not None and panel.graph_id == gid,
          f"panel={type(panel).__name__ if panel else 'None'}")

    # Screenshot
    win.grab().save(str(SS / f"{gid}.png"))

    # Export test
    out = SS / f"{gid}_export.png"
    ok = canvas.export_png_from_scene(str(out))
    check(f"{gid}_export", ok, "export failed")

    # If flowchart, check function switching
    if gid == "flowchart":
        combo = win._graph_view._focus_combo
        func_count = combo.count()
        check(f"{gid}_functions", func_count >= 3, f"only {func_count}")
        print(f"    Functions: {func_count}")

        # Switch to a different function
        for i in range(combo.count()):
            if combo.itemData(i) and "extract" in str(combo.itemData(i)):
                combo.setCurrentIndex(i)
                win._graph_view._on_focus_selected(i)
                QTest.qWait(200)
                new_nodes = len(canvas._node_items)
                check(f"{gid}_func_switch", new_nodes > 0, f"0 nodes after switch")
                print(f"    After switch: {new_nodes} nodes")
                win.grab().save(str(SS / f"{gid}_func_switch.png"))
                break

    # If class diagram, check detail panel
    if gid == "class_diagram" and nodes > 0:
        first_nid = next(iter(canvas._node_items))
        canvas.node_selected.emit(first_nid)
        QTest.qWait(100)
        detail = win._graph_view._detail.toPlainText()
        check(f"{gid}_detail", len(detail) > 10, "detail too short")
        print(f"    Detail: {detail[:60]}...")

# === Mode switching round-trip ===
print("\n--- Round trip ---")
for gid in graph_types:
    for i in range(selector.count()):
        item = selector.item(i)
        if item and item.data(Qt.ItemDataRole.UserRole) == gid:
            selector.setCurrentRow(i)
            QTest.qWait(200)
            nodes = len(canvas._node_items)
            check(f"roundtrip_{gid}", nodes > 0, f"0 nodes")
            break

# === Code mode still works ===
print("\n--- Code mode ---")
win._switch_mode(0)
QTest.qWait(100)
src = win._code_view.source_viewer.toPlainText()
check("code_preserved", "Symbol" in src, "source lost")

print("\n" + "=" * 50)
if issues:
    print(f"ISSUES: {len(issues)}")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")
    sys.exit(1)
else:
    print("ALL GRAPH TYPE CHECKS PASSED")
    sys.exit(0)
