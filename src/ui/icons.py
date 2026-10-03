"""
icons.py – Zentrale SVG-Icon-Loader (lucide-Stil).

Ermöglicht einheitliche, theme-farbige Icons für QPushButton/QLabel.
SVGs liegen in assets/icons/ und verwenden stroke="currentColor";
diese Funktion ersetzt das beim Laden durch die gewünschte Farbe.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache

from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap, QPainter
from PyQt6.QtSvg import QSvgRenderer


def _icons_root() -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "assets", "icons")
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "assets", "icons"
    )


@lru_cache(maxsize=256)
def _svg_bytes(name: str, color: str) -> bytes:
    path = os.path.join(_icons_root(), f"{name}.svg")
    with open(path, "r", encoding="utf-8") as f:
        svg = f.read()
    # currentColor → konkrete Farbe
    svg = svg.replace("currentColor", color)
    return svg.encode("utf-8")


def svg_file(name: str, color: str, directory: str) -> str:
    """Write the icon in `color` to `directory` for a stylesheet url(); returns its path."""
    path = os.path.join(directory, f"{name}-{color.lstrip('#')}.svg")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(_svg_bytes(name, color))
    return path.replace("\\", "/")


def icon(name: str, color: str = "#aab4c4", size: int = 18) -> QIcon:
    """SVG-Icon als QIcon in gewünschter Farbe/Größe."""
    data = _svg_bytes(name, color)
    renderer = QSvgRenderer(QByteArray(data))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()
    return QIcon(pm)


def pixmap(name: str, color: str = "#aab4c4", size: int = 18, dpr: float = 1.0) -> QPixmap:
    """SVG als QPixmap (für QLabel). dpr > 1 renders sharper for HiDPI
    screens; the pixmap keeps the logical size *size*."""
    data = _svg_bytes(name, color)
    renderer = QSvgRenderer(QByteArray(data))
    px = max(1, round(size * dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def pixmap_with_text(
    name: str, color: str, size: int, text: str, *, center_y: float = 0.5625
) -> QPixmap:
    """SVG als QPixmap mit kurzem Text darin, z. B. "FTP" im Ordner.

    center_y ist die vertikale Textmitte relativ zur Icongröße; der Standard
    trifft die Mitte des Ordnerkörpers (y 6..21 in der 24er-ViewBox).
    """
    pm = pixmap(name, color, size)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(6, round(size * 0.28)))
    painter.setFont(font)
    painter.setPen(QColor(color))
    band = size * 0.5
    painter.drawText(
        QRectF(0, size * center_y - band / 2, size, band),
        Qt.AlignmentFlag.AlignCenter,
        text,
    )
    painter.end()
    return pm
