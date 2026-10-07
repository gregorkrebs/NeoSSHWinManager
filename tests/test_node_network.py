"""
tests/test_node_network.py – The network of linked nodes in the free space of
the empty overview, the user management and the profile.
"""

import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)


@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("mirrored", [False, True])
def test_area_for_box_puts_the_node_centres_on_the_box(mirrored):
    from PyQt6.QtCore import QRectF
    from src.ui.node_network import NODES, area_for_box
    box = QRectF(40, 30, 180, 135)
    area = area_for_box(box, mirrored=mirrored)
    xs = [area.x() + (1 - fx if mirrored else fx) * area.width() for fx, _ in NODES]
    ys = [area.y() + fy * area.height() for _, fy in NODES]
    assert min(xs) == pytest.approx(box.left()) and max(xs) == pytest.approx(box.right())
    assert min(ys) == pytest.approx(box.top()) and max(ys) == pytest.approx(box.bottom())


def _fill(app, w, h, corners=("top", "bottom"), rtl=False):
    from PyQt6.QtCore import Qt
    from src.ui.node_network import NodeNetworkFill
    fill = NodeNetworkFill(False, corners)
    if rtl:
        fill.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    fill.resize(w, h)
    return fill


def _painted_pixels(fill):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QImage, QRegion
    from PyQt6.QtWidgets import QWidget
    img = QImage(fill.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    # without the window background: only what the widget paints itself
    fill.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return [(x, y) for y in range(img.height()) for x in range(img.width()) if img.pixelColor(x, y).alpha()]


def test_left_out_where_there_is_no_room(app):
    fill = _fill(app, 900, 60)
    assert fill.network_boxes() == []
    assert _painted_pixels(fill) == []


def test_top_on_the_trailing_side_bottom_on_the_leading_side(app):
    fill = _fill(app, 900, 400)
    (top, top_mirrored), (bottom, bottom_mirrored) = fill.network_boxes()
    assert top.center().x() > 450 and not top_mirrored
    assert bottom.center().x() < 450 and bottom_mirrored
    # staggered rather than side by side at the same height
    assert bottom.top() > top.top()
    assert top.width() <= fill.MAX_WIDTH


def test_right_to_left_mirrors_the_sides(app):
    fill = _fill(app, 900, 400, rtl=True)
    (top, top_mirrored), (bottom, bottom_mirrored) = fill.network_boxes()
    assert top.center().x() < 450 and top_mirrored
    assert bottom.center().x() > 450 and not bottom_mirrored


def test_draws_only_inside_its_own_space(app):
    fill = _fill(app, 600, 260, corners=("top",))
    pixels = _painted_pixels(fill)
    assert pixels
    assert all(x >= 300 for x, _ in pixels)  # only the trailing side
