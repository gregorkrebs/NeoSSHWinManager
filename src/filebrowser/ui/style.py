"""
style.py – Colours and the widget stylesheet of the file browser.

Selectors are scoped by object name ("fb…") so they never leak into the rest
of the application, which has its own global stylesheet.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    raised: str
    text: str
    text_dim: str
    accent: str
    border: str
    alt_row: str
    hover: str
    selection_text: str
    icon: str
    ok: str
    warn: str
    error: str


DARK = Palette(
    bg="#0d0d12", surface="#0D1117", raised="#121a24", text="#c8d6e5", text_dim="#6a7a8a",
    accent="#0077b6", border="#1a2535", alt_row="#0a0e14", hover="rgba(0,119,182,0.12)",
    selection_text="#ffffff", icon="#aab4c4", ok="#00d464", warn="#f59e0b", error="#ef4444",
)
LIGHT = Palette(
    bg="#f0f2f5", surface="#ffffff", raised="#f7f9fb", text="#1a2332", text_dim="#6a7a8a",
    accent="#0077b6", border="#dde2e8", alt_row="#f8fafc", hover="rgba(0,119,182,0.08)",
    selection_text="#ffffff", icon="#4a5a6a", ok="#007a3d", warn="#d97706", error="#dc2626",
)


def palette(theme: str) -> Palette:
    return LIGHT if theme == "light" else DARK


def stylesheet(p: Palette, close_icon: str = "", close_icon_hover: str = "") -> str:
    """close_icon(_hover): SVG files for the tab close buttons (see icons.svg_file)."""
    tabs = ""
    if close_icon:
        # Qt puts the close button flush against the tab's right edge and
        # ignores the tab padding there; a wider button (CloseButton is Qt's
        # class for it) with a right margin gives the X room to breathe.
        tabs = f"""
    QTabBar CloseButton {{ min-width: 28px; max-width: 28px; }}
    QTabBar::close-button {{
        image: url("{close_icon}"); subcontrol-position: right; border: none;
        padding: 1px; margin-left: 2px; margin-right: 9px; border-radius: 3px;
    }}
    QTabBar::close-button:hover {{
        image: url("{close_icon_hover or close_icon}"); background: rgba(239, 68, 68, 0.15);
    }}"""
    return tabs + f"""
    QWidget#fbRoot {{ background-color: {p.bg}; color: {p.text}; }}
    QWidget#fbToolbar, QWidget#fbPaneHeader {{
        background-color: {p.bg};
        border-bottom: 1px solid {p.border};
    }}
    QWidget#fbPane {{ background-color: {p.surface}; }}
    QWidget#fbPane[active="true"] QWidget#fbPaneHeader {{ border-bottom: 2px solid {p.accent}; }}
    QToolButton#fbTool {{
        background: transparent; color: {p.text}; border: 1px solid transparent;
        border-radius: 5px; padding: 4px 6px; font-size: 12px;
    }}
    QToolButton#fbTool:hover {{ background-color: {p.hover}; border-color: {p.border}; }}
    QToolButton#fbTool:checked {{ background-color: {p.hover}; border-color: {p.accent}; }}
    QToolButton#fbTool:disabled {{ color: {p.text_dim}; }}
    QToolButton#fbTool::menu-indicator {{ image: none; width: 0; }}
    QFrame#fbSep {{ background-color: {p.border}; border: none; max-width: 1px; }}
    QLineEdit#fbPath, QLineEdit#fbFilter {{
        background-color: {p.surface}; color: {p.text}; border: 1px solid {p.border};
        border-radius: 5px; padding: 3px 8px; font-size: 12px;
    }}
    QLineEdit#fbPath:focus, QLineEdit#fbFilter:focus {{ border-color: {p.accent}; }}
    QWidget#fbCrumbs {{
        background-color: {p.surface}; border: 1px solid {p.border}; border-radius: 5px;
    }}
    QToolButton#fbCrumb {{
        background: transparent; color: {p.text}; border: none; padding: 2px 4px; font-size: 12px;
    }}
    QToolButton#fbCrumb:hover {{ color: {p.accent}; text-decoration: underline; }}
    QToolButton#fbCrumb[dropTarget="true"] {{
        background-color: {p.accent}; color: {p.selection_text}; border-radius: 4px;
        text-decoration: none;
    }}
    QLabel#fbCrumbSep {{ color: {p.text_dim}; padding: 0 1px; }}
    QTreeView#fbTable, QTreeWidget#fbTree, QTreeWidget#fbJobs, QTreeWidget#fbLog {{
        background-color: {p.surface}; alternate-background-color: {p.alt_row};
        color: {p.text}; border: none; font-size: 12px; outline: none;
    }}
    QTreeView#fbTable::item:selected, QTreeWidget#fbTree::item:selected,
    QTreeWidget#fbJobs::item:selected, QTreeWidget#fbLog::item:selected {{
        background-color: {p.accent}; color: {p.selection_text};
    }}
    QTreeView#fbTable::item:hover, QTreeWidget#fbTree::item:hover {{ background-color: {p.hover}; }}
    QTableWidget, QTreeWidget {{
        background-color: {p.surface}; alternate-background-color: {p.alt_row};
        color: {p.text}; border: 1px solid {p.border}; gridline-color: {p.border};
        font-size: 12px;
    }}
    QTableWidget::item:selected, QTreeWidget::item:selected {{
        background-color: {p.accent}; color: {p.selection_text};
    }}
    QTableCornerButton::section {{ background-color: {p.bg}; border: none; }}
    QTreeWidget#fbTree {{ border-left: 1px solid {p.border}; border-right: 1px solid {p.border}; }}
    QHeaderView::section {{
        background-color: {p.bg}; color: {p.text}; border: none;
        border-bottom: 1px solid {p.border}; border-right: 1px solid {p.border};
        padding: 4px 6px; font-size: 11px; font-weight: 600;
    }}
    QTabWidget#fbTabs::pane, QTabWidget#fbBottom::pane {{ border: none; }}
    QTabBar::tab {{
        background: {p.bg}; color: {p.text_dim}; border: 1px solid {p.border};
        border-bottom: none; padding: 5px 12px; margin-right: 2px;
        border-top-left-radius: 5px; border-top-right-radius: 5px; font-size: 12px;
    }}
    QTabBar::tab:selected {{ background: {p.surface}; color: {p.text}; border-color: {p.accent}; }}
    QLabel#fbStatus {{
        background-color: {p.bg}; color: {p.text_dim}; font-size: 11px;
        border-top: 1px solid {p.border}; padding: 3px 8px;
    }}
    QLabel#fbNotice {{
        background-color: {p.bg}; color: {p.accent}; font-size: 11px; font-weight: 600;
        border-top: 1px solid {p.border}; padding: 3px 8px;
    }}
    QLabel#fbConn[state="reconnecting"] {{ color: {p.warn}; }}
    QLabel#fbConn[state="ok"] {{ color: {p.ok}; }}
    QLabel#fbConn[state="error"] {{ color: {p.error}; }}
    QSplitter::handle {{ background-color: {p.border}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}
    QLabel#fbHint {{ color: {p.text_dim}; font-size: 11px; }}
    QLabel#fbMetaTitle {{ color: {p.text}; font-weight: 700; font-size: 12px; }}
    QLabel#fbMeta {{ color: {p.text_dim}; font-size: 11px; }}
    QPlainTextEdit#fbCompare {{
        background-color: {p.surface}; color: {p.text}; border: 1px solid {p.border};
        font-family: Consolas, "Cascadia Mono", monospace; font-size: 12px;
    }}
    """
