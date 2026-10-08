"""
node_network.py – The faint network of linked nodes, a nod to the remote
hosts the app connects to. Drawn in the About banner and on the login screen,
and as a field of node clusters behind the empty overview, the user
management and the profile.
"""

import math
import random
import zlib

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from src.ui.theme import current_accent

# Whether the networks in the background are shown at all (a setting; the
# About banner keeps its network either way).
_background_enabled = True


def set_background_enabled(on: bool) -> None:
    global _background_enabled
    _background_enabled = bool(on)


def background_enabled() -> bool:
    return _background_enabled


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


# ---------------------------------------------------------------------------
# Node field: clusters that grow in from the corners and edges of a page
# ---------------------------------------------------------------------------

# Corner -> (x, y as fractions of the page, inward direction)
_CORNERS = {"tl": (0, 0, 1, 1), "tr": (1, 0, -1, 1), "bl": (0, 1, 1, -1), "br": (1, 1, -1, -1)}
_OPPOSITE = {"tl": "br", "tr": "bl"}
_MIN_GAP = 30          # px between two nodes of a cluster

# A cluster's nodes are (inward, sideways, radius, hub): px offsets from its
# anchor, inward from the page edge (negative = beyond it) and along it.


def _spanning_tree(pts: list[tuple[float, float]]) -> list[tuple[int, int]]:
    """Links of the shortest tree through all points (Prim)."""
    if len(pts) < 2:
        return []
    inside, links = {0}, []
    while len(inside) < len(pts):
        a, b = min(((i, j) for i in inside for j in range(len(pts)) if j not in inside),
                   key=lambda ij: math.dist(pts[ij[0]], pts[ij[1]]))
        inside.add(b)
        links.append((a, b))
    return links


def _node(rng: random.Random, x: float, y: float, hub_chance: float = 0.18) -> tuple:
    hub = rng.random() < hub_chance
    return (x, y, rng.uniform(3.4, 4.6) if hub else rng.uniform(1.4, 2.8), hub)


def _mesh(rng: random.Random, corner: bool) -> tuple[list, list]:
    """Scattered nodes, knitted together with a few loops."""
    radius = rng.uniform(210, 310) if corner else rng.uniform(120, 180)
    # Corners spread around the diagonal, edges around the normal; both reach
    # a little past the edge, so some links run out of the page.
    spread = math.radians(64 if corner else 100)
    nodes: list[tuple] = []
    for _ in range(rng.randint(9, 13) if corner else rng.randint(5, 8)):
        for _attempt in range(40):
            phi = rng.uniform(-spread, spread)
            dist = radius * (0.08 + 0.92 * rng.random() ** 0.8)
            pt = (dist * math.cos(phi), dist * math.sin(phi))
            if all(math.dist(pt, n[:2]) >= _MIN_GAP for n in nodes):
                nodes.append(_node(rng, *pt))
                break
    pts = [n[:2] for n in nodes]
    links = _spanning_tree(pts)
    if links:
        known = {frozenset(link) for link in links}
        limit = sorted(math.dist(pts[a], pts[b]) for a, b in links)[len(links) // 2] * 1.7
        for i in range(len(pts)):
            for j in sorted((j for j in range(len(pts)) if j != i), key=lambda j: math.dist(pts[i], pts[j]))[1:3]:
                if (rng.random() < 0.45 and math.dist(pts[i], pts[j]) < limit
                        and frozenset((i, j)) not in known):
                    known.add(frozenset((i, j)))
                    links.append((i, j))
    return nodes, links


def _star(rng: random.Random, corner: bool) -> tuple[list, list]:
    """A hub with spokes, some of them reaching past the edge."""
    reach = rng.uniform(150, 210) if corner else rng.uniform(100, 140)
    cx, cy = rng.uniform(0.45, 0.7) * reach, rng.uniform(-0.3, 0.3) * reach
    nodes = [(cx, cy, rng.uniform(4.3, 5.0), True)]
    count = rng.randint(6, 9)
    turn = rng.uniform(0, 2 * math.pi)
    for i in range(count):
        angle = turn + 2 * math.pi * i / count + rng.uniform(-0.25, 0.25)
        dist = rng.uniform(0.45, 1.0) * reach
        nodes.append(_node(rng, cx + dist * math.cos(angle), cy + dist * math.sin(angle), 0.1))
    links = [(0, i) for i in range(1, count + 1)]
    links += [(i, i % count + 1) for i in range(1, count + 1) if rng.random() < 0.35]
    return nodes, links


def _chain(rng: random.Random, corner: bool) -> tuple[list, list]:
    """A winding route that comes in from beyond the edge, with side shoots."""
    x, y = -rng.uniform(20, 50), rng.uniform(-60, 60)
    heading = rng.uniform(-0.7, 0.7)
    nodes, links = [(x, y, 2.0, False)], []
    main = 0
    for _ in range(rng.randint(6, 9) if corner else rng.randint(4, 6)):
        heading = max(-1.25, min(1.25, heading + rng.uniform(-0.5, 0.5)))
        step = rng.uniform(44, 74)
        x, y = x + step * math.cos(heading), y + step * math.sin(heading)
        nodes.append(_node(rng, x, y, 0.2))
        links.append((main, len(nodes) - 1))
        main = len(nodes) - 1
        if rng.random() < 0.35:
            side = heading + rng.choice((-1, 1)) * rng.uniform(0.9, 1.5)
            length = rng.uniform(30, 56)
            nodes.append(_node(rng, x + length * math.cos(side), y + length * math.sin(side), 0.0))
            links.append((main, len(nodes) - 1))
    return nodes, links


_STYLES = {"mesh": _mesh, "star": _star, "chain": _chain}


def _pattern(seed: str) -> tuple[list, list, list]:
    """The size-independent part of a field: its clusters as (anchor, nodes,
    links, far, shaded), the long links between clusters and loose dots. Each
    cluster has a style of its own; "far" clusters are smaller and paler, as
    if further away. The same seed always gives the same pattern."""
    rng = random.Random(zlib.crc32(seed.encode("utf-8")))
    first = rng.choice(("tl", "tr"))
    plan: list = [(first, False), (_OPPOSITE[first], False)]
    for edge in rng.sample(("left", "right", "bottom"), rng.choice((1, 2, 2))):
        plan.append(((edge, rng.uniform(0.3, 0.7)), False))
    plan += [(c, True) for c in _CORNERS if c not in (first, _OPPOSITE[first]) and rng.random() < 0.7]

    styles = []
    for anchor, far in plan:
        if far:
            styles.append(rng.choice(("mesh", "chain")))
        elif isinstance(anchor, str):
            styles.append(rng.choice(("mesh", "mesh", "star", "chain")))
        else:
            styles.append(rng.choice(("star", "chain", "mesh")))
    near = [i for i, (_, far) in enumerate(plan) if not far]
    if len({styles[i] for i in near}) == 1:
        # never all alike
        styles[near[-1]] = rng.choice([s for s in _STYLES if s != styles[near[0]]])

    clusters = []
    for (anchor, far), style in zip(plan, styles):
        nodes, links = _STYLES[style](rng, isinstance(anchor, str))
        if far:
            nodes = [(x * 0.65, y * 0.65, r * 0.75, hub) for x, y, r, hub in nodes]
        # Only meshes get their triangles shaded; on a star they read as a fan.
        clusters.append((anchor, nodes, links, far, style == "mesh"))

    # Long, dashed links from the innermost node of one cluster to another.
    bridges = []
    for i in near:
        for j in near:
            if i < j and clusters[i][1] and clusters[j][1] and rng.random() < 0.4 and len(bridges) < 2:
                inner = [max(range(len(c[1])), key=lambda k, c=c: c[1][k][0]) for c in (clusters[i], clusters[j])]
                bridges.append(((i, inner[0]), (j, inner[1])))
    # Loose single dots near the edges, as fractions of the page.
    dust = []
    for _ in range(rng.randint(14, 22)):
        along, depth = rng.random(), rng.random() ** 2 * 0.25
        edge = rng.choice(("left", "right", "top", "bottom"))
        dust.append({"left": (depth, along), "right": (1 - depth, along),
                     "top": (along, depth), "bottom": (along, 1 - depth)}[edge] + (rng.uniform(0.9, 1.6),))
    return clusters, bridges, dust


def node_field(w: float, h: float, seed: str, *, rtl: bool = False):
    """The field for a page of *w* × *h* px: nodes as (x, y, radius, hub,
    kind) with kind "node", "far" or "dust", links as (a, b, dashed) and
    the shaded triangles that three linked nodes of a mesh enclose, as
    (a, b, c). Clusters keep their shape at any size; only their anchors
    move with the page."""
    clusters, bridges, dust = _pattern(seed)
    nodes, links, triangles, first_index = [], [], [], []
    for anchor, cluster_nodes, cluster_links, far, shaded in clusters:
        if isinstance(anchor, str):
            fx, fy, sx, sy = _CORNERS[anchor]
            origin = (fx * w, fy * h)
            inward = (sx / math.sqrt(2), sy / math.sqrt(2))
            side = (-inward[1], inward[0])
        else:
            edge, t = anchor
            origin, inward, side = {
                "left": ((0, t * h), (1, 0), (0, 1)),
                "right": ((w, t * h), (-1, 0), (0, 1)),
                "bottom": ((t * w, h), (0, -1), (1, 0)),
            }[edge]
        first_index.append(len(nodes))
        for a, b, radius, hub in cluster_nodes:
            nodes.append((origin[0] + a * inward[0] + b * side[0],
                          origin[1] + a * inward[1] + b * side[1], radius, hub, "far" if far else "node"))
        links += [(first_index[-1] + a, first_index[-1] + b, False) for a, b in cluster_links]
        if shaded:
            linked = {frozenset(link) for link in cluster_links}
            triangles += [(first_index[-1] + a, first_index[-1] + b, first_index[-1] + c)
                          for a, b in sorted(tuple(sorted(e)) for e in linked)
                          for c in range(b + 1, len(cluster_nodes))
                          if frozenset((a, c)) in linked and frozenset((b, c)) in linked]
    links += [(first_index[ci] + ni, first_index[cj] + nj, True) for (ci, ni), (cj, nj) in bridges]
    nodes += [(fx * w, fy * h, radius, False, "dust") for fx, fy, radius in dust]
    if rtl:
        nodes = [(w - x, y, *rest) for x, y, *rest in nodes]
    return nodes, links, triangles


def _crosses(rect: QRectF, x1: float, y1: float, x2: float, y2: float) -> bool:
    """True if the segment touches *rect* (Liang-Barsky clipping)."""
    t0, t1 = 0.0, 1.0
    dx, dy = x2 - x1, y2 - y1
    for p, q in ((-dx, x1 - rect.left()), (dx, rect.right() - x1),
                 (-dy, y1 - rect.top()), (dy, rect.bottom() - y1)):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


class NodeFieldBackdrop(QWidget):
    """The node field behind the content of *host*, following its size.
    It sits below the host's other children, so cards and texts lie on top
    and the field runs on behind them. Its clusters come in from the
    corners and edges and fade out towards the middle; around *quiet*, a
    widget such as a centred text, the field steps back further."""

    def __init__(self, host: QWidget, seed: str = "", light: bool = False,
                 quiet: QWidget | None = None):
        super().__init__(host)
        self.setObjectName("nodeFieldBackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._host = host
        self._seed = seed
        self._light = light
        self._quiet = quiet
        self._cache: tuple | None = None
        host.installEventFilter(self)
        self.setGeometry(host.rect())
        self.lower()
        self.show()       # a child added to a shown host would stay hidden

    def show_field(self, seed: str, light: bool, quiet: QWidget | None = None) -> None:
        """Show the field of page *seed*; *quiet* as in the constructor."""
        self._seed, self._light, self._quiet, self._cache = seed, light, quiet, None
        self.setGeometry(self._host.rect())
        self.lower()
        self.show()
        self.update()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self._host and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._host.rect())
        return False

    def _field(self):
        key = (self.width(), self.height(), self._seed, self.isRightToLeft())
        if self._cache is None or self._cache[0] != key:
            self._cache = (key, node_field(self.width(), self.height(), self._seed, rtl=key[3]))
        return self._cache[1]

    def _quiet_rect(self) -> QRectF | None:
        quiet = self._quiet
        try:
            if quiet is None or not quiet.isVisible():
                return None
        except RuntimeError:        # deleted with the page it belonged to
            self._quiet = None
            return None
        top_left = self.mapFromGlobal(quiet.mapToGlobal(QPoint(0, 0)))
        return QRectF(top_left.x(), top_left.y(), quiet.width(), quiet.height()).adjusted(-24, -24, 24, 24)

    def paintEvent(self, event):  # noqa: N802
        w, h = self.width(), self.height()
        if w < 80 or h < 80 or not _background_enabled:
            return
        nodes, links, triangles = self._field()
        quiet = self._quiet_rect()
        reach = min(max(0.55 * min(w, h), 220), 460)

        def fade(x: float, y: float) -> float:
            """1 at the edge of the page, down to a trace in the middle."""
            depth = min(x, y, w - x, h - y)
            f = 1.0 if depth <= 0 else 0.08 + 0.92 * max(0.0, 1 - depth / reach) ** 1.4
            if quiet is not None:
                dx = max(quiet.left() - x, 0, x - quiet.right())
                dy = max(quiet.top() - y, 0, y - quiet.bottom())
                f *= min(1.0, math.hypot(dx, dy) / 90)
            return f

        accent = QColor(current_accent())
        line_alpha, hub_alpha, dot_alpha, glow_alpha = (80, 165, 115, 45) if self._light else (110, 210, 150, 70)

        def tint(alpha: float) -> QColor:
            c = QColor(accent)
            c.setAlpha(max(0, min(255, int(alpha))))
            return c

        # far clusters are paler, as if further away
        weight = [fade(x, y) * (0.5 if kind == "far" else 1.0) for x, y, _r, _hub, kind in nodes]

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for tri in triangles:
            if quiet is not None and any(_crosses(quiet, *nodes[a][:2], *nodes[b][:2])
                                         for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0]))):
                continue
            p.setBrush(tint((16 if self._light else 18) * sum(weight[i] for i in tri) / 3))
            p.drawPolygon([QPointF(*nodes[i][:2]) for i in tri])
        for a, b, dashed in links:
            (x1, y1), (x2, y2) = nodes[a][:2], nodes[b][:2]
            f1, f2 = weight[a], weight[b]
            if (f1 < 0.02 and f2 < 0.02) or (quiet is not None and _crosses(quiet, x1, y1, x2, y2)):
                continue
            scale = 0.55 if dashed else 1.0
            grad = QLinearGradient(x1, y1, x2, y2)
            grad.setColorAt(0, tint(line_alpha * scale * f1))
            grad.setColorAt(1, tint(line_alpha * scale * f2))
            pen = QPen(QBrush(grad), 1.0 if dashed else 1.2)
            if dashed:
                pen.setDashPattern([3, 5])
            p.setPen(pen)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        p.setPen(Qt.PenStyle.NoPen)
        for (x, y, radius, hub, kind), f in zip(nodes, weight):
            if f < 0.02:
                continue
            centre = QPointF(x, y)
            if hub:
                glow = QRadialGradient(centre, radius * 5)
                glow.setColorAt(0, tint(glow_alpha * f))
                glow.setColorAt(1, tint(0))
                p.setBrush(QBrush(glow))
                p.drawEllipse(centre, radius * 5, radius * 5)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(tint(hub_alpha * 0.45 * f), 1.0))
                p.drawEllipse(centre, radius * 2.3, radius * 2.3)
                if radius > 4.0:
                    # the bigger hubs send out a second, fainter ring
                    p.setPen(QPen(tint(hub_alpha * 0.2 * f), 1.0))
                    p.drawEllipse(centre, radius * 3.8, radius * 3.8)
                p.setPen(Qt.PenStyle.NoPen)
            alpha = hub_alpha if hub else dot_alpha * (0.6 if kind == "dust" else 1.0)
            p.setBrush(tint(alpha * f))
            p.drawEllipse(centre, radius, radius)
        p.end()
