"""Application entry point for OrionParser GUI."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def launch(path: str | None = None) -> int:
    """Launch the OrionParser GUI application.

    Args:
        path: Optional file or directory to open on startup.

    Returns:
        Application exit code.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName("OrionParser")
    app.setOrganizationName("OrionParser")

    from orionparser.gui.main_window import MainWindow

    window = MainWindow()
    window.show()

    if path is not None:
        window.open_path(path)

    return app.exec()
