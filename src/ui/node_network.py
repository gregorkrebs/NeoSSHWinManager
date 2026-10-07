"""
node_network.py – The faint network of linked nodes, a nod to the remote
hosts the app connects to. Drawn in the About banner and on the login screen.
"""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen

# Node positions as fractions of the area, and the links between them. The
# network fills the trailing third of the area.
NODES = ((0.73, 0.11), (0.85, 0.19), (0.97, 0.07), (0.985, 0.52),
         (0.93, 0.85), (0.81, 0.93), (0.69, 0.86))
LINKS = ((0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (1, 3))
_BIG_NODES = (1, 4)


def paint_node_network(p: QPainter, rect: QRectF, color: QColor, *, mirrored: bool = False,
                       line_alpha: int = 46, dot_alphas: tuple[int, int] = (110, 70),
                       glow_alpha: int = 14) -> None:
    """Draw the network into *rect* in *color*. *mirrored* puts it on the
    leading third instead (right-to-left layouts, the other side of a header).
    *glow_alpha* 0 leaves out the two large soft circles behind it."""
    x0, y0, w, h = rect.x(), rect.y(), rect.width(), rect.height()

    def at(fx: float, fy: float) -> QPointF:
        return QPointF(x0 + (1 - fx if mirrored else fx) * w, y0 + fy * h)

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if glow_alpha:
        glow = QColor(color)
        glow.setAlpha(glow_alpha)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(at(0.92, 0.05), h * 0.95, h * 0.95)
        p.drawEllipse(at(0.62, 1.10), h * 0.55, h * 0.55)

    pts = [at(x, y) for x, y in NODES]
    line = QColor(color)
    line.setAlpha(line_alpha)
    p.setPen(QPen(line, 1.3))
    for a, b in LINKS:
        p.drawLine(pts[a], pts[b])
    p.setPen(Qt.PenStyle.NoPen)
    for i, pt in enumerate(pts):
        dot = QColor(color)
        dot.setAlpha(dot_alphas[0] if i in _BIG_NODES else dot_alphas[1])
        p.setBrush(dot)
        radius = 4.5 if i in _BIG_NODES else 3.0
        p.drawEllipse(pt, radius, radius)
    p.restore()
