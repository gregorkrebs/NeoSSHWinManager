"""
dialog_utils.py – Hilfsfunktionen für Dialoge.
"""

from PyQt6.QtWidgets import QDialog, QWidget, QApplication, QPushButton, QLabel
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor
from src.ui.icons import icon as svg_icon, pixmap as svg_pixmap


# Message types → icon (own SVGs in assets/icons).
MESSAGE_ICONS = {
    "info": "circle-info",
    "warning": "alert-triangle",
    "error": "circle-x",
    "question": "circle-help",
}


def message_color(mode: str, theme: str = "dark") -> str:
    """Colour of a message type: accent for info/question, amber, red."""
    from src.ui.theme import current_accent, is_light
    light = is_light(theme)
    if mode == "warning":
        return "#d97706" if light else "#f59e0b"
    if mode == "error":
        return "#dc2626" if light else "#ef4444"
    return current_accent()


def dialog_icon(name: str, color: str, box: int = 48, glyph: int = 26) -> QLabel:
    """Dialog icon: the SVG *name* in *color* on a tinted rounded tile."""
    lbl = QLabel()
    lbl.setObjectName("dialogIconTile")
    lbl.setFixedSize(box, box)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    screen = QApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    lbl.setPixmap(svg_pixmap(name, color, glyph, dpr))
    c = QColor(color)
    lbl.setStyleSheet(
        f"QLabel#dialogIconTile {{ background-color: rgba({c.red()}, {c.green()}, {c.blue()}, 0.13);"
        f" border: 1px solid rgba({c.red()}, {c.green()}, {c.blue()}, 0.32);"
        f" border-radius: {box // 4}px; }}"
    )
    return lbl


def match_parent_height(dialog: QDialog, parent: QWidget | None, max_fraction: float = 0.95) -> None:
    """
    Startet den Dialog kompakt (sizeHint des Inhalts), gedeckelt auf einen
    Anteil der Bildschirmhöhe. Großer Content scrollt dann intern.
    Der User kann über den Maximize-Button jederzeit auf volle Höhe springen.
    """
    screen = QApplication.primaryScreen()
    max_h = None
    if screen is not None:
        max_h = int(screen.availableGeometry().height() * max_fraction)

    content_h = dialog.sizeHint().height()
    if content_h <= 0:
        return
    target_h = min(content_h, max_h) if max_h else content_h
    dialog.resize(dialog.width() or dialog.sizeHint().width(), target_h)


def make_maximize_button(dialog: QDialog) -> QPushButton:
    """
    Liefert einen Button, der den Dialog auf die verfügbare Bildschirmhöhe
    aufzieht bzw. zurück auf sizeHint klappt (Toggle). Der Button wird
    typischerweise links in der fixen Button-Leiste platziert.
    """
    btn = QPushButton()
    btn.setObjectName("dialogMaximizeBtn")
    btn.setFixedSize(32, 32)
    btn.setIcon(svg_icon("maximize", "#aab4c4", 16))
    btn.setIconSize(QSize(16, 16))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip("Auf volle Höhe / zurück (Toggle)")
    btn.setCheckable(True)

    # Merke den ursprünglichen Min-Wert, um beim Toggle-off wiederherzustellen.
    original_min_h = {"v": None}

    def _toggle(checked: bool):
        screen = QApplication.primaryScreen()
        if checked and screen is not None:
            h = int(screen.availableGeometry().height() * 0.95)
            y = screen.availableGeometry().y() + 10
            if original_min_h["v"] is None:
                original_min_h["v"] = dialog.minimumHeight()
            # setMinimumHeight verhindert, dass Layout-Updates (z.B. beim
            # Aktivieren einer Checkbox) die Höhe auf sizeHint zurückspringen lassen.
            dialog.setMinimumHeight(h)
            dialog.resize(dialog.width(), h)
            dialog.move(dialog.x(), y)
            btn.setToolTip("Zurück auf kompakte Höhe")
        else:
            if original_min_h["v"] is not None:
                dialog.setMinimumHeight(original_min_h["v"])
                original_min_h["v"] = None
            dialog.resize(dialog.width(), dialog.sizeHint().height())
            btn.setToolTip("Auf volle Höhe ziehen")

    btn.toggled.connect(_toggle)
    return btn
