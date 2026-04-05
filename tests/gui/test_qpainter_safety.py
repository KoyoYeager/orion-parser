"""Verify no QPainter errors under edge conditions.

Runs the stress test script as a subprocess and checks C-level stderr
for QPainter/Paint device warnings.
"""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).parent / "run_qpainter_stress.py")


def test_no_qpainter_errors():
    """Full GUI stress test produces zero QPainter errors."""
    r = subprocess.run(
        [sys.executable, SCRIPT],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"Script failed:\n{r.stdout}\n{r.stderr}"

    qp_errors = [
        line for line in r.stderr.splitlines()
        if "QPainter" in line or "Paint device" in line
    ]
    assert len(qp_errors) == 0, (
        f"QPainter errors found ({len(qp_errors)}):\n" + "\n".join(qp_errors)
    )
    assert "ALL STRESS TESTS PASSED" in r.stdout
