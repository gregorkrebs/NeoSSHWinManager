"""
Smoke test of the real file browser against the local SFTP test server.

Any exception raised inside a Qt callback (slot, event filter, paint, …) is
captured through sys.excepthook and fails the test. Without that hook PyQt
would abort the whole process via qFatal.
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.config import Connection  # noqa: E402
from src.filebrowser.fs import SftpFS  # noqa: E402
from src.filebrowser.model import KEEP_BOTH, ConflictInfo, FileEntry  # noqa: E402
from src.filebrowser.settings import MemoryStore, SettingsManager  # noqa: E402
from src.filebrowser.ui import dialogs  # noqa: E402
from src.filebrowser.ui import session as session_mod  # noqa: E402
from src.filebrowser.ui import view as view_mod  # noqa: E402
from tests.sftp_test_server import SftpTestServer  # noqa: E402


@pytest.fixture
def qt_errors(monkeypatch):
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda t, e, tb: errors.append(e))
    return errors


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _serve(monkeypatch, *servers):
    """Host sessions log in to the local test server(s) (picked by port)."""
    by_port = {srv.port: srv for srv in servers}

    def open_fs(session):
        srv = by_port[session.conn.port]
        return SftpFS(srv.connect(), reconnect=srv.connect)
    monkeypatch.setattr(session_mod.HostSession, "open_fs", open_fs)


def _pump(app, seconds, until=None):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until is None


def test_breadcrumbs_fold_into_menu_when_narrow(app, qt_errors):
    from src.filebrowser.ui.pane import Breadcrumbs, CrumbButton

    crumbs = Breadcrumbs(local=False)
    crumbs.resize(900, 28)
    crumbs.show()
    crumbs.set_path("/var/www/vhosts/example.com/httpdocs/wp-content/uploads")

    def shown():
        _pump(app, 0.1)
        return [b.target for b in crumbs.findChildren(CrumbButton) if b.parent() is not None]

    wide = shown()
    crumbs.resize(170, 28)
    narrow = shown()
    assert narrow[-1] == "/var/www/vhosts/example.com/httpdocs/wp-content/uploads"
    assert 1 <= len(narrow) < len(wide)
    assert crumbs.minimumWidth() == Breadcrumbs.MIN_WIDTH       # never the whole path
    crumbs.resize(900, 28)
    assert shown() == wide
    crumbs.close()
    assert not qt_errors, qt_errors


def test_up_row_leads_one_level_up(app, qt_errors, tmp_path, monkeypatch):
    from PyQt6.QtCore import Qt
    from src.filebrowser.ui.models import COL_NAME, COL_SIZE, ENTRY_ROLE

    remote = tmp_path / "remote"
    (remote / "site" / "css").mkdir(parents=True)
    (remote / "site" / "a.txt").write_text("a")
    (remote / "site" / ".env").write_text("hidden")
    with SftpTestServer(str(remote)) as server:
        _serve(monkeypatch, server)
        win = view_mod.FileBrowserView(
            Connection(name="U", host="127.0.0.1", user="user", password="pass", port=server.port,
                       remote_path="/site"),
            SettingsManager(MemoryStore()), theme="dark")
        win.show()
        try:
            assert _pump(app, 5, lambda: win.remote_pane() and win.remote_pane().entries())
            pane = win.remote_pane()
            proxy = pane._proxy

            def first():
                return proxy.index(0, COL_NAME).data(ENTRY_ROLE)

            assert first().is_up and first().path == "/" and proxy.index(0, COL_NAME).data() == "..."
            assert not any(e.is_up for e in pane.entries())
            pane.view.sortByColumn(COL_SIZE, Qt.SortOrder.DescendingOrder)
            assert first().is_up                                   # stays on top
            pane._filter.setText("no such file")
            assert proxy.rowCount() == 1 and first().is_up         # never filtered away
            pane._filter.clear()
            from src.i18n import tr
            assert pane.status_text() == tr("fb.status.items", count=2)   # css, a.txt (.env hidden)
            pane.view.selectAll()
            assert sorted(e.name for e in pane.selected_entries()) == ["a.txt", "css"]
            pane.view.clearSelection()

            pane._on_double_click(proxy.index(0, COL_NAME))
            assert _pump(app, 5, lambda: pane.current_dir == "/")
            assert pane.current_entry() is not None and pane.current_entry().name == "site"
            assert not pane._model.has_up                          # nothing above "/"

            pane.navigate("/site")
            assert _pump(app, 5, lambda: pane.current_dir == "/site")
            pane.view.setCurrentIndex(proxy.index(0, COL_NAME))
            assert pane.current_entry() is None                    # "..." is no file
            pane._open_selection()                                 # Enter on "..."
            assert _pump(app, 5, lambda: pane.current_dir == "/")
        finally:
            win.shutdown()
            _pump(app, 0.3)
    assert not qt_errors, qt_errors


def test_local_up_row_reaches_the_drive_list(app, qt_errors):
    from types import SimpleNamespace
    from src.filebrowser.fs import LocalFS
    from src.filebrowser.ui.pane import FilePane

    manager = SettingsManager(MemoryStore({"show_tree": False}))
    pane = FilePane(SimpleNamespace(show_error=lambda *_a: None), LocalFS(), "local",
                    manager, "c1", "#aab4c4")
    pane.navigate("C:\\")
    assert _pump(app, 5, lambda: pane.current_dir == "C:\\")
    assert pane._model.has_up and pane._model.rows[0].path == ""  # "..." -> This PC
    pane.go_up()
    assert _pump(app, 5, lambda: pane.current_dir == "")
    assert not pane._model.has_up
    assert not qt_errors, qt_errors


def test_column_widths_and_sort_are_remembered(app, qt_errors):
    from types import SimpleNamespace
    from PyQt6.QtCore import Qt
    from src.filebrowser.fs import LocalFS
    from src.filebrowser.ui.models import COL_MTIME, COL_SIZE
    from src.filebrowser.ui.pane import FilePane

    manager = SettingsManager(MemoryStore({"show_tree": False}))
    ctl = SimpleNamespace(show_error=lambda *_a: None)
    first = FilePane(ctl, LocalFS(), "local", manager, "c1", "#aab4c4")
    first.view.header().resizeSection(COL_SIZE, 150)
    first.view.sortByColumn(COL_MTIME, Qt.SortOrder.DescendingOrder)

    second = FilePane(ctl, LocalFS(), "local", manager, "c1", "#aab4c4")
    hdr = second.view.header()
    assert hdr.sectionSize(COL_SIZE) == 150
    assert hdr.sortIndicatorSection() == COL_MTIME
    assert hdr.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    assert not qt_errors, qt_errors


def test_drop_on_path_bar_moves_after_confirmation_and_undo_redo(app, qt_errors, tmp_path,
                                                                 monkeypatch):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QDropEvent
    from PyQt6.QtWidgets import QDialog
    from src.filebrowser.ui.models import make_mime
    from src.filebrowser.ui.pane import CrumbButton

    remote = tmp_path / "remote"
    (remote / "site" / "sub" / "deep").mkdir(parents=True)
    (remote / "site" / "sub" / "deep" / "page.html").write_text("x")

    with SftpTestServer(str(remote)) as server:
        _serve(monkeypatch, server)
        asked = []

        def confirm(dlg):
            asked.append(dlg.windowTitle())
            dlg._dont_ask.setChecked(True)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(dialogs.MoveConfirmDialog, "exec", confirm)
        manager = SettingsManager(MemoryStore({"show_tree": True}))
        conn = Connection(name="T", host="127.0.0.1", user="user", password="pass", port=server.port,
                          remote_path="/site/sub")
        win = view_mod.FileBrowserView(conn, manager, theme="dark")
        win.resize(1200, 700)
        win.show()
        try:
            assert _pump(app, 5, lambda: win.remote_pane() and win.remote_pane().entries())
            pane = win.remote_pane()
            deep = pane.entries()[0]
            assert deep.name == "deep" and not win.can_undo()

            # A second tab sits inside the folder that is about to move.
            win.new_tab()
            inside = win.remote_pane()
            inside.navigate("/site/sub/deep")
            assert _pump(app, 5, lambda: inside.current_dir == "/site/sub/deep")

            mime = make_mime("remote", [deep], win.drag_origin)
            assert pane.plan_drop(mime, "/site")
            assert pane.plan_drop(mime, "/site/sub") is None               # already there
            assert pane.plan_drop(mime, "/site/sub/deep") is None          # into itself
            assert pane.plan_drop(make_mime("remote", [deep], "other window"), "/site") is None
            root = FileEntry(name="/", path="/", is_dir=True)
            assert pane.plan_drop(make_mime("remote", [root], win.drag_origin), "/site") is None
            assert pane.tree.drop_plan == pane.plan_drop

            crumb = next(b for b in pane.findChildren(CrumbButton) if b.target == "/site")
            event = QDropEvent(QPointF(4, 4), Qt.DropAction.CopyAction, mime,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            crumb.dropEvent(event)
            assert event.isAccepted()
            assert _pump(app, 5, lambda: (remote / "site" / "deep" / "page.html").exists())
            assert not (remote / "site" / "sub" / "deep").exists()
            assert len(asked) == 1 and manager.settings.confirm_move is False
            assert _pump(app, 5, lambda: inside.current_dir == "/site/deep")    # followed
            assert win.can_undo() and "deep" in win.undo_label()
            labels = [a.text() for a in win.build_context_menu(pane, []).actions()]
            assert any(win.undo_label() in text for text in labels)

            win.undo()
            assert _pump(app, 5, lambda: (remote / "site" / "sub" / "deep" / "page.html").exists())
            assert _pump(app, 5, lambda: inside.current_dir == "/site/sub/deep")
            assert _pump(app, 2, lambda: win.can_redo()) and not win.can_undo()

            win.redo()
            assert _pump(app, 5, lambda: (remote / "site" / "deep").exists())
            assert _pump(app, 2, lambda: win.can_undo())

            # "Don't ask again": the next move runs without a question.
            win.undo()
            assert _pump(app, 5, lambda: (remote / "site" / "sub" / "deep").exists())
            assert _pump(app, 2, lambda: win.can_redo())
            win.handle_drop(pane, "remote", [deep], "/site")
            assert _pump(app, 5, lambda: (remote / "site" / "deep").exists())
            assert len(asked) == 1

            # New folder, then undo removes it again.
            monkeypatch.setattr(view_mod.StyledInputDialog, "get_text",
                                classmethod(lambda cls, *a, **k: ("fresh", True)))
            win.new_folder(pane)
            assert _pump(app, 5, lambda: (remote / "site" / "sub" / "fresh").is_dir())
            assert _pump(app, 2, lambda: "fresh" in win.undo_label())
            win.undo()
            assert _pump(app, 5, lambda: not (remote / "site" / "sub" / "fresh").exists())
        finally:
            win.shutdown()
            _pump(app, 0.3)
    assert not qt_errors, qt_errors


def test_drop_on_file_list_and_tree_uploads(app, qt_errors, tmp_path, monkeypatch):
    """Files dropped from the PC side (e.g. a mounted SSHFS drive) or from
    Explorer onto the server's file list or folder tree are uploaded."""
    from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PyQt6.QtGui import QDropEvent
    from src.filebrowser.ui.models import make_mime

    remote = tmp_path / "remote"
    (remote / "site" / "css").mkdir(parents=True)
    drive = tmp_path / "drive"                  # stands in for a mounted drive letter
    drive.mkdir()
    for name in ("list.txt", "explorer.txt", "tree.txt"):
        (drive / name).write_text(name)

    def drop(widget, mime, pos):
        event = QDropEvent(QPointF(pos), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        widget.dropEvent(event)
        return event

    def local(name):
        path = drive / name
        return make_mime("local", [FileEntry(name=name, path=str(path), is_dir=False,
                                             size=path.stat().st_size)])

    with SftpTestServer(str(remote)) as server:
        _serve(monkeypatch, server)
        manager = SettingsManager(MemoryStore({"show_tree": True}))
        conn = Connection(name="T", host="127.0.0.1", user="user", password="pass", port=server.port,
                          remote_path="/site")
        win = view_mod.FileBrowserView(conn, manager, theme="dark")
        win.resize(1200, 700)
        win.show()
        try:
            assert _pump(app, 5, lambda: win.remote_pane() and win.remote_pane().entries())
            pane = win.remote_pane()
            below_rows = QPointF(pane.view.viewport().width() / 2,
                                 pane.view.viewport().height() - 4)

            # PC side -> free area of the file list = the current folder
            event = drop(pane.view, local("list.txt"), below_rows)
            assert event.isAccepted() and event.dropAction() == Qt.DropAction.CopyAction
            assert _pump(app, 5, lambda: (remote / "site" / "list.txt").exists())

            # Explorer (plain file URLs) -> the file list
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(drive / "explorer.txt"))])
            assert drop(pane.view, mime, below_rows).isAccepted()
            assert _pump(app, 5, lambda: (remote / "site" / "explorer.txt").exists())

            # PC side -> a folder in the tree
            assert _pump(app, 5, lambda: pane.tree._find_loaded("/site/css") is not None)
            item = pane.tree._find_loaded("/site/css")
            event = drop(pane.tree, local("tree.txt"),
                         pane.tree.visualItemRect(item).center())
            assert event.isAccepted()
            assert _pump(app, 5, lambda: (remote / "site" / "css" / "tree.txt").exists())
            assert (remote / "site" / "css" / "tree.txt").read_text() == "tree.txt"
            assert (drive / "tree.txt").exists()          # a copy: the source stays
        finally:
            win.shutdown()
            _pump(app, 0.3)
    assert not qt_errors, qt_errors


@pytest.mark.parametrize("configured, server_home", [
    ("/home/user1", "/"),               # the path entered for the connection
    ("/", "/home/user1"),               # nothing entered: the login folder
])
def test_server_tree_starts_at_the_home_path(app, qt_errors, tmp_path, monkeypatch,
                                             configured, server_home):
    remote = tmp_path / "remote"
    (remote / "home" / "user1" / "www" / "site").mkdir(parents=True)
    (remote / "home" / "other").mkdir()
    # Like many hosting accounts: "/" and "/home" may not be listed.
    with SftpTestServer(str(remote), home=server_home, deny_list=("/", "/home")) as server:
        _serve(monkeypatch, server)
        monkeypatch.setattr(view_mod.StyledMessageBox, "critical",
                            classmethod(lambda cls, *a, **k: None))
        manager = SettingsManager(MemoryStore({"show_tree": True}))
        conn = Connection(name="H", host="127.0.0.1", user="user", password="pass",
                          port=server.port, remote_path=configured)
        win = view_mod.FileBrowserView(conn, manager, theme="dark")
        win.resize(1200, 700)
        win.show()
        try:
            assert _pump(app, 5, lambda: win.remote_pane() and win.remote_pane().entries())
            pane = win.remote_pane()
            tree = pane.tree
            assert pane.current_dir == "/home/user1"
            top = tree.topLevelItem(0)
            assert tree.topLevelItemCount() == 1 and top.text(0) == "/home/user1"
            assert _pump(app, 5, lambda: top.childCount() and top.child(0).text(0) == "www")

            pane.navigate("/home/user1/www/site")
            assert _pump(app, 5, lambda: tree.currentItem() is not None
                         and tree.currentItem().text(0) == "site")

            manager.settings.tree_from_root = True           # setting: from "/"
            manager.save()
            assert tree.topLevelItem(0).text(0) == "/"
            manager.settings.tree_from_root = False
            manager.save()
            assert tree.topLevelItem(0).text(0) == "/home/user1"
            assert _pump(app, 5, lambda: tree.currentItem() is not None
                         and tree.currentItem().text(0) == "site")
        finally:
            win.shutdown()
            _pump(app, 0.3)
    assert not qt_errors, qt_errors


def test_windows_server_root_is_no_drop_target(app, qt_errors, tmp_path, monkeypatch):
    from src.filebrowser.ui.models import make_mime

    remote = tmp_path / "remote"
    (remote / "C_drive" / "Users" / "test" / "docs").mkdir(parents=True)
    with SftpTestServer(str(remote), windows_home="/C:/Users/test") as server:
        _serve(monkeypatch, server)
        conn = Connection(name="W", host="127.0.0.1", user="user", password="pass",
                          port=server.port, remote_path="/")
        win = view_mod.FileBrowserView(conn, SettingsManager(MemoryStore()), theme="light")
        win.show()
        try:
            assert _pump(app, 5, lambda: win.remote_pane() and win.remote_pane().entries())
            pane = win.remote_pane()
            assert win.fs.is_windows and pane.current_dir == "/C:/Users/test"
            docs = pane.entries()[0]
            mime = make_mime("remote", [docs], win.drag_origin)
            assert pane.plan_drop(mime, "/C:/Users")
            assert pane.plan_drop(mime, "/") is None          # the drive list
            drive = FileEntry(name="C:", path="/C:", is_dir=True)
            assert pane.plan_drop(make_mime("remote", [drive], win.drag_origin), "/C:/Users") is None
        finally:
            win.shutdown()
            _pump(app, 0.3)
    assert not qt_errors, qt_errors


def test_further_hosts_open_in_their_own_tabs(app, qt_errors, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.filebrowser.ui.models import make_mime
    from src.filebrowser.ui.transfer_panel import C_HOST
    from src.i18n import tr

    (tmp_path / "a" / "alpha-site").mkdir(parents=True)
    (tmp_path / "b" / "beta-site").mkdir(parents=True)
    upload = tmp_path / "upload.txt"
    upload.write_text("for beta")
    with SftpTestServer(str(tmp_path / "a")) as sa, SftpTestServer(str(tmp_path / "b")) as sb:
        _serve(monkeypatch, sa, sb)
        conn_a = Connection(id="a", name="Alpha", host="127.0.0.1", user="user", password="pass",
                            port=sa.port, remote_path="/")
        conn_b = Connection(id="b", name="Beta", host="127.0.0.1", user="user", password="pass",
                            port=sb.port, remote_path="/")
        prepared = []
        hosts = SimpleNamespace(
            connections=lambda: [conn_a, conn_b],
            prepare=lambda cid: prepared.append(cid) or {"a": conn_a, "b": conn_b}[cid])
        win = view_mod.FileBrowserView(conn_a, SettingsManager(MemoryStore()), theme="dark",
                                       hosts=hosts)
        win.resize(1200, 700)
        win.show()
        try:
            assert _pump(app, 5, lambda: win.remote_pane() and win.remote_pane().entries())
            pane_a = win.remote_pane()
            assert [e.name for e in pane_a.entries()] == ["alpha-site"]

            win._fill_hosts_menu()                       # "Connect" menu: every saved host
            acts = win._hosts_menu.actions()
            assert [a.text().split("\t")[0] for a in acts] == ["Alpha", "Beta"]
            assert [a.font().bold() for a in acts] == [True, False]   # Alpha is open

            win.connect_host("b")
            assert prepared == ["b"] and win.tabs.count() == 2
            assert _pump(app, 5, lambda: win.remote_pane() and win.remote_pane().entries())
            pane_b = win.remote_pane()
            assert win.conn is conn_b and "Beta" in win.windowTitle()
            assert [e.name for e in pane_b.entries()] == ["beta-site"]

            # Transfers go to the tab's own host and show it in the list.
            win.queue.upload([str(upload)], "/")
            assert _pump(app, 5, lambda: (tmp_path / "b" / "upload.txt").exists())
            assert not (tmp_path / "a" / "upload.txt").exists()
            assert win._panel.jobs.topLevelItem(0).text(C_HOST) == "Beta"

            # Undo belongs to the host: Beta's new folder is not undoable in Alpha's tab.
            monkeypatch.setattr(view_mod.StyledInputDialog, "get_text",
                                classmethod(lambda cls, *a, **k: ("made-on-beta", True)))
            win.new_folder(pane_b)
            assert _pump(app, 5, lambda: win.can_undo())
            win.connect_host("a")                        # open already: just its tab
            assert win.tabs.count() == 2 and win.conn is conn_a and prepared == ["b"]
            assert not win.can_undo()

            # A server folder of Alpha cannot be dropped into Beta's pane.
            mime = make_mime("remote", pane_a.entries(), pane_a._origin)
            assert pane_b.plan_drop(mime, "/beta-site") is None
            assert pane_a.plan_drop(mime, "/") is None and pane_a._origin != pane_b._origin

            # Ctrl+T: another tab of the same host shares its connection.
            win.new_tab()
            assert win.tabs.count() == 3 and len(win.sessions) == 2
            assert win.workspace().session is win.sessions[0]

            # Closing Beta's only tab logs out of Beta; closing everything leaves an empty window.
            beta_tab = next(i for i in range(win.tabs.count())
                            if win.tabs.widget(i).session.conn is conn_b)
            win.close_tab(beta_tab)
            assert [s.conn for s in win.sessions] == [conn_a]
            while win.tabs.count():
                win.close_tab(0)
            assert win.session() is None and not win.sessions
            assert win.windowTitle() == tr("fb.window.title_empty")
            assert win._center.currentIndex() == 0
            win.connect_host("b")
            assert _pump(app, 5, lambda: win.remote_pane() and win.remote_pane().entries())
            assert win.conn is conn_b
        finally:
            win.shutdown()
            _pump(app, 0.3)
    assert not qt_errors, qt_errors


def test_theme_switch_keeps_the_hosts_connected(app, qt_errors, tmp_path, monkeypatch):
    from PyQt6.QtGui import QColor, QImage
    from PyQt6.QtWidgets import QToolButton
    from src.filebrowser.ui import style

    def drawn_in(btn, color: str) -> bool:
        """Every clearly visible pixel of the icon has this colour (antialiasing aside)."""
        want = QColor(color)
        # Not premultiplied, or half-transparent edge pixels look darker.
        img = btn.icon().pixmap(16, 16).toImage().convertToFormat(QImage.Format.Format_ARGB32)
        pixels = [QColor.fromRgba(img.pixel(x, y)) for x in range(img.width())
                  for y in range(img.height())]
        pixels = [c for c in pixels if c.alpha() >= 96]
        return bool(pixels) and all(
            max(abs(c.red() - want.red()), abs(c.green() - want.green()),
                abs(c.blue() - want.blue())) <= 12 for c in pixels)

    (tmp_path / "srv" / "docs").mkdir(parents=True)
    with SftpTestServer(str(tmp_path / "srv")) as server:
        _serve(monkeypatch, server)
        conn = Connection(name="T", host="127.0.0.1", user="user", password="pass",
                          port=server.port, remote_path="/")
        win = view_mod.FileBrowserView(conn, SettingsManager(MemoryStore()), theme="dark")
        win.resize(1200, 700)
        win.show()
        try:
            assert _pump(app, 5, lambda: win.remote_pane() and win.remote_pane().entries())
            session, pane = win.session(), win.remote_pane()
            assert drawn_in(win._b_upload, style.DARK.icon)

            win.set_theme("light")
            assert win.palette is style.LIGHT and win.theme == "light"
            assert style.LIGHT.bg in win._root.styleSheet()
            themed = [b for b in win.findChildren(QToolButton) if b.property("fbIcon")]
            odd = [b.property("fbIcon") for b in themed
                   if b is not pane._btn_bookmark and not drawn_in(b, style.LIGHT.icon)]
            assert len(themed) > 20 and not odd, odd
            assert pane._icon_color == style.LIGHT.icon and win._panel._p is style.LIGHT
            assert win.session() is session and session.connected      # nothing reconnected
            assert [e.name for e in win.remote_pane().entries()] == ["docs"]
        finally:
            win.shutdown()
            _pump(app, 0.3)
    assert not qt_errors, qt_errors


def test_failed_host_shows_retry_in_its_tab(app, qt_errors, tmp_path, monkeypatch):
    (tmp_path / "r" / "docs").mkdir(parents=True)
    shown = []
    monkeypatch.setattr(view_mod.StyledMessageBox, "critical",
                        classmethod(lambda cls, parent, title, text, **k: shown.append(text)))
    with SftpTestServer(str(tmp_path / "r")) as server:
        attempts = []

        def open_fs(session):
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionRefusedError("host unreachable")
            return SftpFS(server.connect(), reconnect=server.connect)

        monkeypatch.setattr(session_mod.HostSession, "open_fs", open_fs)
        conn = Connection(name="Flaky", host="127.0.0.1", user="user", password="pass",
                          port=server.port, remote_path="/")
        win = view_mod.FileBrowserView(conn, SettingsManager(MemoryStore()), theme="dark")
        win.show()
        try:
            ws = win.workspace()
            assert _pump(app, 5, lambda: shown)
            assert "host unreachable" in shown[0] and not ws.attached
            assert ws._retry.isVisibleTo(ws) and "host unreachable" in ws._message.text()
            assert not win._b_upload.isEnabled()
            ws._retry.click()
            assert _pump(app, 5, lambda: win.remote_pane() and win.remote_pane().entries())
            assert win._b_upload.isEnabled() and len(attempts) == 2
        finally:
            win.shutdown()
            _pump(app, 0.3)
    assert not qt_errors, qt_errors


def test_window_split_upload_conflict_and_dialogs(app, qt_errors, tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    (remote / "site" / "css").mkdir(parents=True)
    (remote / "site" / "index.html").write_text("<h1>old</h1>")
    local = tmp_path / "local"
    local.mkdir()
    (local / "index.html").write_text("<h1>new</h1>")
    (local / "logo.png").write_bytes(os.urandom(2048))

    with SftpTestServer(str(remote)) as server:
        _serve(monkeypatch, server)
        manager = SettingsManager(MemoryStore({"last_local": str(local)}))
        conn = Connection(name="T", host="127.0.0.1", user="user", password="pass", port=server.port,
                          remote_path="/site")
        win = view_mod.FileBrowserView(conn, manager, theme="dark")
        win.resize(1300, 800)
        win.show()
        try:
            assert win.parent() is None                      # independent top-level window
            assert _pump(app, 5, lambda: win.remote_pane() and win.remote_pane().entries())
            assert [e.name for e in win.remote_pane().entries()] == ["css", "index.html"]

            win.toggle_split()
            ws = win.workspace()
            assert _pump(app, 5, lambda: ws.local.entries())
            assert {e.name for e in ws.local.entries()} == {"index.html", "logo.png"}

            # The long local temp path must not make the PC side wider than the server side.
            mins = [ws.local.minimumSizeHint().width(), ws.remote.minimumSizeHint().width()]
            assert abs(mins[0] - mins[1]) <= 50 and max(mins) < 450, mins
            # The divider goes all the way to either edge.
            total = sum(ws.splitter.sizes())
            ws.splitter.setSizes([0, total])
            assert ws.splitter.sizes()[0] == 0
            ws.splitter.setSizes([total, 0])
            assert ws.splitter.sizes()[1] == 0
            ws.set_split(False)                          # server side folded away: back to full width
            assert ws.splitter.sizes()[1] > 0
            ws.set_split(True)
            assert min(ws.splitter.sizes()) > 0

            asked = []
            win.queue._resolver = lambda info: (asked.append(info.source.name) or (KEEP_BOTH, True))
            win.transfer_to_other(ws.local, ws.local.entries())
            assert _pump(app, 10, lambda: len(win.queue.jobs) == 2 and not win.queue.active_count())
            _pump(app, 1)                                    # debounced pane refresh
            assert asked == ["index.html"]
            assert (remote / "site" / "index_1.html").read_text() == "<h1>new</h1>"
            assert (remote / "site" / "index.html").read_text() == "<h1>old</h1>"
            assert "index_1.html" in {e.name for e in ws.remote.entries()}

            menu = win.build_context_menu(ws.remote, ws.remote.entries()[:1])
            assert menu.actions()

            src = FileEntry("a.txt", str(local / "index.html"), False, 12, time.time())
            dst = FileEntry("a.txt", "/site/index.html", False, 12, 0)
            for dlg in (
                dialogs.ConflictDialog(win, ConflictInfo(src, dst, "up"), "dark"),
                dialogs.CompareDialog(win, "dark", win.palette, "L", src, src.path,
                                      "R", dst, str(remote / "site" / "index.html")),
                dialogs.SettingsDialog(win, manager, "dark"),
                dialogs.UrlDialog(win, "dark", "/site", True),
                dialogs.PropertiesDialog(win, "dark", win.fs, ws.remote.entries()),
                dialogs.ShortcutsDialog(win, "dark"),
                dialogs.OpenWithDialog(win, "txt", "dark"),
                dialogs.MoveConfirmDialog(win, "dark", ["a", "b"], "/site"),
            ):
                dlg.show()
                _pump(app, 0.2)
                dlg.close()
        finally:
            win.shutdown()
            _pump(app, 0.3)
    assert not qt_errors, qt_errors
