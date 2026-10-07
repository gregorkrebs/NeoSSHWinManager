"""
tests/test_no_flashing_windows.py – Building the UI never shows a widget as a
window of its own.

A widget made visible before it has a parent becomes a top-level window for
the moment until a layout adopts it. One such button per connection card
made a small window flash up for every host right after the login.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def shown_windows(app):
    """Names of the widgets that were shown as windows while the test ran."""
    from PyQt6.QtCore import QEvent, QObject
    from PyQt6.QtWidgets import QWidget

    shown = []

    class Spy(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
                shown.append(f"{type(obj).__name__}#{obj.objectName()}")
            return False

    spy = Spy()
    app.installEventFilter(spy)
    yield shown
    app.removeEventFilter(spy)


@pytest.mark.parametrize("protocol, mounted", [("sftp", False), ("sftp", True), ("ftp", False)])
def test_connection_card_shows_no_window(app, shown_windows, protocol, mounted):
    from src.config import Connection
    from src.ui.connection_card import ConnectionCard
    card = ConnectionCard(Connection(name="web", host="example.org", user="root", protocol=protocol),
                          mounted=mounted)
    card.set_letter_warning(True)
    card.update_mount_state(not mounted)
    assert shown_windows == []
