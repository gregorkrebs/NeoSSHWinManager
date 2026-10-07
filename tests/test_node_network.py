"""
tests/test_node_network.py – The field of linked nodes behind the empty
overview, the user management and the profile.
"""

import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

SEEDS = ("overview", "users", "profile")


@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_every_page_has_its_own_stable_pattern():
    from src.ui.node_network import node_field
    fields = {seed: node_field(1000, 600, seed) for seed in SEEDS}
    assert all(node_field(1000, 600, seed) == fields[seed] for seed in SEEDS)
    assert len({str(f) for f in fields.values()}) == len(SEEDS)


@pytest.mark.parametrize("seed", SEEDS)
def test_links_run_in_from_beyond_the_edge(seed):
    from src.ui.node_network import node_field
    w, h = 1000, 600
    nodes, links, _triangles = node_field(w, h, seed)

    def inside(i):
        x, y = nodes[i][:2]
        return 0 <= x <= w and 0 <= y <= h

    assert sum(1 for a, b, _dashed in links if inside(a) != inside(b)) >= 3


@pytest.mark.parametrize("seed", SEEDS)
def test_clusters_keep_their_shape_when_the_page_grows(seed):
    from src.ui.node_network import _pattern, node_field
    small, _, _ = node_field(900, 500, seed)
    large, _, _ = node_field(1600, 1000, seed)
    start = 0
    for _anchor, cluster_nodes, *_rest in _pattern(seed)[0]:
        for i in range(start + 1, start + len(cluster_nodes)):
            gap_small = (small[i][0] - small[start][0], small[i][1] - small[start][1])
            gap_large = (large[i][0] - large[start][0], large[i][1] - large[start][1])
            assert gap_small == pytest.approx(gap_large)
        start += len(cluster_nodes)


def test_right_to_left_mirrors_the_field():
    from src.ui.node_network import node_field
    ltr, links, triangles = node_field(1000, 600, "users")
    rtl, rtl_links, rtl_triangles = node_field(1000, 600, "users", rtl=True)
    assert [(1000 - x, y) for x, y, *_ in ltr] == pytest.approx([(x, y) for x, y, *_ in rtl])
    assert (links, triangles) == (rtl_links, rtl_triangles)


def _painted(widget):
    """Alpha of every pixel the widget paints itself, without any background."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QImage, QRegion
    from PyQt6.QtWidgets import QWidget
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    widget.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return img


def test_backdrop_follows_the_host_and_stays_behind_its_content(app):
    from PyQt6.QtWidgets import QFrame, QWidget
    from src.ui.node_network import NodeFieldBackdrop
    host = QWidget()
    card = QFrame(host)
    backdrop = NodeFieldBackdrop(host, "users")
    assert host.children().index(backdrop) < host.children().index(card)
    host.resize(900, 500)
    host.show()     # a hidden widget gets its resize event when it is shown
    assert backdrop.geometry() == host.rect()
    host.resize(1200, 700)
    assert backdrop.geometry() == host.rect()


def test_strongest_at_the_edges_and_quiet_in_the_middle(app):
    from PyQt6.QtWidgets import QLabel, QWidget
    from src.ui.node_network import NodeFieldBackdrop
    host = QWidget()
    host.resize(800, 600)
    text = QLabel("Ready for the next step", host)
    text.setGeometry(250, 260, 300, 80)
    host.show()
    backdrop = NodeFieldBackdrop(host, "overview", quiet=text)
    img = _painted(backdrop)

    def alpha(x0, y0, x1, y1):
        return sum(img.pixelColor(x, y).alpha() for y in range(y0, y1, 2) for x in range(x0, x1, 2))

    band = alpha(0, 0, 800, 60) + alpha(0, 540, 800, 600)
    middle = alpha(200, 200, 600, 400)
    assert band > 4 * middle
    assert alpha(250, 260, 550, 340) == 0      # nothing over the text


def test_too_small_to_draw(app):
    from PyQt6.QtWidgets import QWidget
    from src.ui.node_network import NodeFieldBackdrop
    host = QWidget()
    host.resize(60, 60)
    img = _painted(NodeFieldBackdrop(host, "users"))
    assert all(img.pixelColor(x, y).alpha() == 0 for y in range(60) for x in range(60))
