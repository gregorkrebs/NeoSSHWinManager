"""
The main window's side of the file browser: the browser is a page of the main
window for all hosts, hosts become tabs, an open host is only brought to the
front, the main window's own shortcuts step aside on that page, "terminal
here" goes back to the connections page, and quitting disconnects everything.
Runs the real MainWindow methods on a stand-in object and the real browser
against the local SFTP test server.
"""

import os
import time
import types
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtGui import QKeySequence, QShortcut  # noqa: E402
from PyQt6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget  # noqa: E402

from src.config import Connection  # noqa: E402
from src.filebrowser.fs import SftpFS  # noqa: E402
from src.filebrowser.settings import MemoryStore, SettingsManager  # noqa: E402
from src.filebrowser.ui import session as session_mod  # noqa: E402
from src.ui import main_window as mw  # noqa: E402
from tests.sftp_test_server import SftpTestServer  # noqa: E402


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _pump(app, seconds, until=None):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until is None


class _Main(QWidget):
    """Stand-in for MainWindow: a real widget (show/raise, and a parent for the page)."""


def _fake_main(conns: dict, manager):
    fake = _Main()
    stack = QStackedWidget(fake)
    home, fullscreen, files = QWidget(), QWidget(), QWidget()
    layout = QVBoxLayout(files)
    layout.setContentsMargins(0, 0, 0, 0)
    for page in (home, fullscreen, files):
        stack.addWidget(page)
    fake.__dict__.update(
        _mgr=SimpleNamespace(get_by_id=conns.get, get_connections=lambda: list(conns.values()),
                             get_settings=lambda: SimpleNamespace(theme="dark")),
        _cards={cid: SimpleNamespace(is_mounted=True, set_info_active=Mock()) for cid in conns},
        _file_browser=None,
        _fb_settings=manager,
        _main_stack=stack,
        _files_page=files,
        _panel_mode=mw._PANEL_NONE,
        _panel_conn_id=None,
        _shortcuts=[QShortcut(QKeySequence(k), fake) for k in ("F2", "Delete", "Esc")],
        _guard_leave_form=Mock(return_value=True),
        _clear_fs_content=Mock(),
        _set_fullscreen_header=Mock(),
        _set_sidebar_active=Mock(),
        _nav_home=Mock(),
        _set_status=Mock(),
        _terminal_conn_tabs={},
        _open_terminal_panel=Mock(),
        _add_terminal_session=Mock(),
    )
    stack.currentChanged.connect(lambda i: mw.MainWindow._on_main_page_changed(fake, i))
    fake.auth_parents = []

    def prepare(conn, parent=None):              # stored password: nothing to ask
        fake.auth_parents.append(parent)
        return conn
    fake._prepare_auth = prepare
    for name in ("_open_sftp_browser", "_file_browser_settings", "_ensure_file_browser",
                 "_on_file_browser", "_show_file_browser_page", "_leave_file_browser_page",
                 "_confirm_quit_with_transfers", "_close_file_browser", "_open_terminal_at"):
        setattr(fake, name, types.MethodType(getattr(mw.MainWindow, name), fake))
    return fake


def _shortcuts_on(main) -> list:
    return [s.isEnabled() for s in main._shortcuts]


def test_file_browser_page_for_all_hosts(app, tmp_path, monkeypatch):
    (tmp_path / "srv" / "data").mkdir(parents=True)
    with SftpTestServer(str(tmp_path / "srv")) as server:
        monkeypatch.setattr(session_mod.HostSession, "open_fs",
                            lambda self: SftpFS(server.connect(), reconnect=server.connect))
        a = Connection(id="a", name="Alpha", host="127.0.0.1", user="user", password="pass",
                       port=server.port, remote_path="/")
        b = Connection(id="b", name="Beta", host="127.0.0.1", user="user", password="pass",
                       port=server.port, remote_path="/")
        main = _fake_main({"a": a, "b": b}, SettingsManager(MemoryStore()))
        main.resize(1200, 700)

        # Sidebar button: the page, empty until a host is connected.
        main._on_file_browser()
        browser = main._file_browser
        assert browser is not None and browser.parent() is main._files_page
        assert main._main_stack.currentWidget() is main._files_page
        assert main._panel_mode == mw._PANEL_FILES and main.isVisible()
        main._set_sidebar_active.assert_called_with("files")
        assert browser.tabs.count() == 0 and browser._center.currentIndex() == 0
        assert _shortcuts_on(main) == [False, False, False]      # the browser's F2/Del/Esc win

        main._open_sftp_browser("a", mounted_only=False)
        assert main._file_browser is browser and browser.tabs.count() == 1
        assert _pump(app, 5, lambda: browser.remote_pane() and browser.remote_pane().entries())
        assert main.auth_parents == [main]

        main._open_sftp_browser("a", mounted_only=False)       # open already: its tab only
        assert browser.tabs.count() == 1 and main.auth_parents == [main]

        main._open_sftp_browser("b", mounted_only=False)       # second host: new tab, same page
        assert browser.tabs.count() == 2 and browser.conn.id == "b"

        # The browser's own "Connect" menu reads the same saved connections.
        assert [c.id for c in browser._hosts.connections()] == ["a", "b"]
        assert browser._hosts.prepare("a").id == "a" and main.auth_parents[-1] is main

        # Back on the connections page the main window's shortcuts work again,
        # and the hosts stay connected in the background.
        main._leave_file_browser_page()
        assert main._main_stack.currentIndex() == 0 and _shortcuts_on(main) == [True] * 3
        assert main._panel_mode == mw._PANEL_NONE
        assert _pump(app, 5, lambda: [s.connected for s in browser.sessions] == [True, True])
        main._open_sftp_browser("a", mounted_only=False)
        assert main._main_stack.currentWidget() is main._files_page
        assert browser.conn.id == "a" and browser.tabs.count() == 2

        # "Open terminal here" switches to the connections page first.
        main._open_terminal_at("a", "cd /data\r")
        assert main._main_stack.currentIndex() == 0 and _shortcuts_on(main) == [True] * 3
        main._open_terminal_panel.assert_called_once_with("a", initial_input="cd /data\r")

        assert main._confirm_quit_with_transfers()             # nothing running: no question
        main._close_file_browser()
        assert browser.closed and browser.sessions == [] and main._file_browser is None
        _pump(app, 0.3)
        main.close()
