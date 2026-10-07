"""
node_network.py – The faint network of linked nodes, a nod to the remote
hosts the app connects to. Drawn in the About banner, on the login screen and
in the free space of the empty overview, user management and profile.
"""

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from src.ui.theme import current_accent

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


def area_for_box(box: QRectF, *, mirrored: bool = False) -> QRectF:
    """The rect to hand to paint_node_network so that the node centres
    span exactly *box*."""
    xs = [x for x, _ in NODES]
    ys = [y for _, y in NODES]
    w = box.width() / (max(xs) - min(xs))
    h = box.height() / (max(ys) - min(ys))
    x0 = box.left() - (1 - max(xs)) * w if mirrored else box.left() - min(xs) * w
    return QRectF(x0, box.top() - min(ys) * h, w, h)


class NodeNetworkFill(QWidget):
    """Takes the free space at the end of a layout, in place of a stretch,
    and draws the network into it, as on the login screen: "top" puts one on
    the trailing side at the top, "bottom" one on the leading side at the
    bottom. Left out where the space is too small for it."""

    MAX_WIDTH = 200       # of the network itself
    MIN_HEIGHT = 70
    _ASPECT = 0.75        # height : width, as in the About banner
    _INSET = 6            # keeps the outer dots off the edge

    def __init__(self, light: bool, corners: tuple[str, ...] = ("top", "bottom"),
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("nodeNetworkFill")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._light = light
        self._corners = corners

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 0)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 0)

    def network_boxes(self) -> list[tuple[QRectF, bool]]:
        """(box of the node centres, mirrored) for each network that fits."""
        inner = QRectF(self.rect()).adjusted(self._INSET, self._INSET, -self._INSET, -self._INSET)
        box_w = min(0.3 * inner.width(), self.MAX_WIDTH)
        # Two networks are staggered, as on the login screen, rather than
        # facing each other at the same height.
        box_h = min(box_w * self._ASPECT, inner.height() / (1.4 if len(self._corners) > 1 else 1))
        if box_h < self.MIN_HEIGHT:
            return []
        box_w = box_h / self._ASPECT
        rtl = self.isRightToLeft()
        boxes = []
        for corner in self._corners:
            top = corner == "top"
            # "top" sits on the trailing side, "bottom" on the leading side.
            on_right = top != rtl
            x = inner.right() - box_w if on_right else inner.left()
            y = inner.top() if top else inner.bottom() - box_h
            boxes.append((QRectF(x, y, box_w, box_h), not on_right))
        return boxes

    def paintEvent(self, event):  # noqa: N802
        boxes = self.network_boxes()
        if not boxes:
            return
        color = QColor(current_accent())
        alphas = dict(line_alpha=55, dot_alphas=(140, 90)) if self._light \
            else dict(line_alpha=70, dot_alphas=(175, 110))
        p = QPainter(self)
        for box, mirrored in boxes:
            paint_node_network(p, area_for_box(box, mirrored=mirrored), color,
                               mirrored=mirrored, glow_alpha=0, **alphas)
        p.end()
