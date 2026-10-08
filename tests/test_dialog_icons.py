"""
tests/test_dialog_icons.py – Popups show SVG icons, not emoji.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _labels(widget):
    from PyQt6.QtWidgets import QLabel
    return widget.findChildren(QLabel)


@pytest.mark.parametrize("mode", ["info", "warning", "error", "question", "unknown"])
def test_message_box_uses_svg_icon(app, mode):
    from src.ui.dialogs.styled_message_box import StyledMessageBox
    dlg = StyledMessageBox(None, "Title", "Body", mode)
    tiles = [l for l in _labels(dlg) if l.objectName() == "dialogIconTile"]
    assert len(tiles) == 1 and not tiles[0].pixmap().isNull()
    assert not any(_EMOJI.search(l.text() or "") for l in _labels(dlg))


def test_logout_dialog_uses_svg_icon(app):
    from src.ui.dialogs.logout_dialog import LogoutConfirmDialog
    dlg = LogoutConfirmDialog()
    assert any(l.objectName() == "dialogIconTile" for l in _labels(dlg))
    assert not any(_EMOJI.search(l.text() or "") for l in _labels(dlg))


def test_message_colors_follow_type_and_accent(app):
    from src.ui import theme
    from src.ui.dialog_utils import message_color
    theme.set_current_accent("#8b5cf6")
    try:
        assert message_color("info") == "#8b5cf6"
        assert message_color("question") == "#8b5cf6"
        assert message_color("error") == "#ef4444"
        assert message_color("error", "light") == "#dc2626"
        assert message_color("warning") == "#f59e0b"
    finally:
        theme.set_current_accent(theme.DEFAULT_ACCENT)


@pytest.mark.parametrize("name", [
    "alert-triangle", "circle-x", "circle-help", "circle-info", "door", "lock",
    "hourglass", "key-off", "globe", "file-text",
])
def test_new_icons_render(app, name):
    from src.ui.icons import pixmap
    pm = pixmap(name, "#ff0000", 24, 2.0)
    assert not pm.isNull() and pm.width() == 48 and pm.devicePixelRatio() == 2.0
