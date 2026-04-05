"""Theme manager — QSS stylesheet generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ThemeColors:
    bg: str
    secondary_bg: str
    text: str
    accent: str
    border: str
    error: str
    success: str
    warning: str
    highlight: str


THEMES: dict[str, ThemeColors] = {
    "light": ThemeColors(
        bg="#FFFFFF",
        secondary_bg="#F3F3F3",
        text="#1E1E1E",
        accent="#0078D4",
        border="#D1D1D1",
        error="#E81123",
        success="#107C10",
        warning="#FF8C00",
        highlight="#CCE5FF",
    ),
    "dark": ThemeColors(
        bg="#1E1E1E",
        secondary_bg="#252526",
        text="#D4D4D4",
        accent="#569CD6",
        border="#3F3F46",
        error="#F44747",
        success="#6A9955",
        warning="#CE9178",
        highlight="#264F78",
    ),
}


def get_stylesheet(theme_name: str = "light") -> str:
    """Generate QSS stylesheet for the given theme."""
    c = THEMES.get(theme_name, THEMES["light"])
    return f"""
    /* === Global === */
    QWidget {{
        font-family: "Segoe UI", "Yu Gothic UI", "Meiryo", sans-serif;
        font-size: 13px;
        color: {c.text};
        background-color: {c.bg};
    }}

    /* === Main Window === */
    QMainWindow {{
        background-color: {c.bg};
    }}

    /* === Menu Bar === */
    QMenuBar {{
        background-color: {c.secondary_bg};
        border-bottom: 1px solid {c.border};
        padding: 2px;
    }}
    QMenuBar::item {{
        padding: 4px 10px;
        border-radius: 3px;
    }}
    QMenuBar::item:selected {{
        background-color: {c.highlight};
    }}
    QMenu {{
        background-color: {c.bg};
        border: 1px solid {c.border};
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px;
        border-radius: 3px;
    }}
    QMenu::item:selected {{
        background-color: {c.highlight};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {c.border};
        margin: 4px 8px;
    }}

    /* === Toolbar === */
    QToolBar {{
        background-color: {c.secondary_bg};
        border-bottom: 1px solid {c.border};
        spacing: 4px;
        padding: 3px 6px;
    }}
    QToolBar QToolButton {{
        padding: 4px 10px;
        border-radius: 3px;
        border: none;
    }}
    QToolBar QToolButton:hover {{
        background-color: {c.highlight};
    }}

    /* === Tab Bar (Mode Tabs) === */
    QTabBar {{
        background-color: {c.secondary_bg};
    }}
    QTabBar::tab {{
        padding: 10px 24px;
        border: none;
        border-bottom: 2px solid transparent;
        font-size: 14px;
        font-weight: 500;
    }}
    QTabBar::tab:selected {{
        background-color: {c.bg};
        border-bottom: 2px solid {c.accent};
        color: {c.accent};
        font-weight: 600;
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {c.highlight};
    }}

    /* === Inner Tab Widget (Sub-tabs) === */
    QTabWidget::pane {{
        border: 1px solid {c.border};
        border-top: none;
    }}
    QTabWidget > QTabBar::tab {{
        padding: 6px 16px;
        font-size: 12px;
    }}

    /* === Splitter === */
    QSplitter::handle {{
        background-color: {c.border};
    }}
    QSplitter::handle:horizontal {{
        width: 2px;
    }}
    QSplitter::handle:vertical {{
        height: 2px;
    }}

    /* === Tree Widget === */
    QTreeWidget {{
        border: 1px solid {c.border};
        alternate-background-color: {c.secondary_bg};
        outline: none;
    }}
    QTreeWidget::item {{
        padding: 3px 4px;
    }}
    QTreeWidget::item:selected {{
        background-color: {c.highlight};
        color: {c.text};
    }}
    QTreeWidget::item:hover {{
        background-color: {c.highlight};
    }}
    QHeaderView::section {{
        background-color: {c.secondary_bg};
        padding: 4px 8px;
        border: none;
        border-right: 1px solid {c.border};
        border-bottom: 1px solid {c.border};
        font-weight: 600;
    }}

    /* === Table Widget === */
    QTableWidget {{
        border: 1px solid {c.border};
        alternate-background-color: {c.secondary_bg};
        gridline-color: {c.border};
        outline: none;
    }}
    QTableWidget::item {{
        padding: 2px 6px;
    }}
    QTableWidget::item:selected {{
        background-color: {c.highlight};
        color: {c.text};
    }}

    /* === Source Viewer / Plain Text === */
    QPlainTextEdit {{
        font-family: "Consolas", "Courier New", monospace;
        font-size: 13px;
        border: 1px solid {c.border};
        selection-background-color: {c.highlight};
    }}

    /* === List Widget (Graph Selector) === */
    QListWidget {{
        border: 1px solid {c.border};
        outline: none;
        font-size: 11px;
    }}
    QListWidget::item {{
        padding: 8px 6px;
        border-bottom: 1px solid {c.border};
    }}
    QListWidget::item:selected {{
        background-color: {c.highlight};
        color: {c.accent};
        font-weight: 600;
    }}
    QListWidget::item:disabled {{
        color: #AAAAAA;
        font-style: italic;
    }}

    /* === Status Bar === */
    QStatusBar {{
        background-color: {c.secondary_bg};
        border-top: 1px solid {c.border};
        font-size: 12px;
    }}

    /* === Search / Line Edit === */
    QLineEdit {{
        border: 1px solid {c.border};
        border-radius: 3px;
        padding: 4px 8px;
        background-color: {c.bg};
    }}
    QLineEdit:focus {{
        border-color: {c.accent};
    }}

    /* === Combo Box === */
    QComboBox {{
        border: 1px solid {c.border};
        border-radius: 3px;
        padding: 4px 8px;
        background-color: {c.bg};
        min-width: 80px;
    }}
    QComboBox:focus {{
        border-color: {c.accent};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        border: 1px solid {c.border};
        background-color: {c.bg};
        selection-background-color: {c.highlight};
    }}

    /* === Scroll Bar === */
    QScrollBar:vertical {{
        background-color: {c.bg};
        width: 10px;
    }}
    QScrollBar::handle:vertical {{
        background-color: {c.border};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {c.accent};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background-color: {c.bg};
        height: 10px;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {c.border};
        border-radius: 4px;
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {c.accent};
    }}
    """
