"""GUI flowchart interaction test via pytest — runs the full interaction script."""

import subprocess
import sys
from pathlib import Path

SCRIPT = str(Path(__file__).parent / "run_flowchart_gui_test.py")


def test_flowchart_gui_all_checks():
    r = subprocess.run(
        [sys.executable, SCRIPT],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"Script failed:\n{r.stdout}\n{r.stderr}"
    assert "ALL GUI FLOWCHART CHECKS PASSED" in r.stdout

    qp = [l for l in r.stderr.splitlines() if "QPainter" in l]
    assert len(qp) == 0, f"QPainter errors: {qp}"
