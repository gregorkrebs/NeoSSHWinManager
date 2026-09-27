import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from src.config import Connection, PROTOCOL_FTPS  # noqa: E402
from src.ui import main_window as mw  # noqa: E402

_LEFT = SimpleNamespace(button=lambda: Qt.MouseButton.LeftButton)
_RIGHT = SimpleNamespace(button=lambda: Qt.MouseButton.RightButton)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _fake_window(mounted: bool, panel_mode=mw._PANEL_INFO, guard=True):
    fake = SimpleNamespace(
        _cards={"c1": SimpleNamespace(is_mounted=mounted)},
        _panel_mode=panel_mode,
        _guard_leave_form=Mock(return_value=guard),
        _on_open_explorer=Mock(),
        _on_mount=Mock(),
        _open_sftp_browser=Mock(),
    )
    fake._on_status_folder_clicked = (
        lambda cid: mw.MainWindow._on_status_folder_clicked(fake, cid)
    )
    return fake


def _widgets(layout):
    """All widgets of a layout, depth-first, in visual order."""
    found = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is not None:
            found.append(item.widget())
        elif item.layout() is not None:
            found.extend(_widgets(item.layout()))
    return found


def _row(qapp, fake, conn, mounted):
    row = mw.MainWindow._build_status_row(fake, conn, mounted, "dark")
    host = QWidget()        # keeps the row's widgets alive
    host.setLayout(row)
    return host, _widgets(row)


def _sftp_conn():
    return Connection(id="c1", name="Win", host="h", user="u", drive_letter="W:")


def test_mounted_folder_opens_explorer():
    fake = _fake_window(mounted=True)
    mw.MainWindow._on_status_folder_clicked(fake, "c1")
    fake._on_open_explorer.assert_called_once_with("c1")
    fake._on_mount.assert_not_called()


def test_unmounted_folder_mounts():
    fake = _fake_window(mounted=False)
    mw.MainWindow._on_status_folder_clicked(fake, "c1")
    fake._on_mount.assert_called_once_with("c1")
    fake._on_open_explorer.assert_not_called()


def test_unmounted_folder_in_edit_form_respects_unsaved_changes():
    fake = _fake_window(mounted=False, panel_mode=mw._PANEL_EDIT, guard=False)
    mw.MainWindow._on_status_folder_clicked(fake, "c1")
    fake._guard_leave_form.assert_called_once()
    fake._on_mount.assert_not_called()


def test_mounted_row_status_and_both_folders(qapp):
    fake = _fake_window(mounted=True)
    host, widgets = _row(qapp, fake, _sftp_conn(), mounted=True)
    status, explorer, browser = widgets[0], widgets[-2], widgets[-1]

    status.mousePressEvent(_LEFT)
    explorer.mousePressEvent(_LEFT)
    assert fake._on_open_explorer.call_count == 2

    browser.mousePressEvent(_LEFT)
    fake._open_sftp_browser.assert_called_once_with("c1", mounted_only=False)


def test_unmounted_row_folder_mounts_and_browser_still_works(qapp):
    fake = _fake_window(mounted=False)
    host, widgets = _row(qapp, fake, _sftp_conn(), mounted=False)
    explorer, browser = widgets[-2], widgets[-1]

    explorer.mousePressEvent(_RIGHT)          # only left clicks act
    fake._on_mount.assert_not_called()
    explorer.mousePressEvent(_LEFT)
    fake._on_mount.assert_called_once_with("c1")

    browser.mousePressEvent(_LEFT)
    fake._open_sftp_browser.assert_called_once_with("c1", mounted_only=False)


def test_ftp_connection_has_only_the_browser_folder(qapp):
    fake = _fake_window(mounted=False)
    conn = Connection(id="c1", name="Shop", host="h", user="u", protocol=PROTOCOL_FTPS)
    host, widgets = _row(qapp, fake, conn, mounted=False)

    folders = [w for w in widgets if w.toolTip() and w is not widgets[0]]
    assert len(folders) == 1
    folders[0].mousePressEvent(_LEFT)
    fake._open_sftp_browser.assert_called_once_with("c1", mounted_only=False)
