"""
view.py – The file browser, a page of the main window.

The browser is not tied to one host: every tab belongs to a host session
(session.py), "Connect" opens further hosts in new tabs, and tabs of the same
host share its session. Each tab is a workspace with the server pane and, in
split mode, a local pane next to it. Leaving the page only hides it:
connections and transfers keep running until shutdown().

The view is the controller for everything the panes ask for: opening files
with the chosen program, transfers, conflicts, archives, sync, properties,
undo/redo, the terminal hand-off and its settings. Actions always use the
session of the pane they come from; toolbar actions use the current tab's.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from typing import Callable, Optional, Protocol

from PyQt6.QtCore import QEventLoop, QFileSystemWatcher, Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMenu, QProgressDialog, QSplitter,
    QStackedLayout, QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from src.app_logger import logger
from src.filebrowser import commands
from src.filebrowser.fs import FsError, LocalFS
from src.filebrowser.history import (
    MKDIR, MKFILE, MOVE, RENAME, Modified, NotEmpty, UndoOp, apply_op,
)
from src.filebrowser.model import (
    CANCEL, OVERWRITE, FileEntry, keep_both_name, rebase_path, rjoin, rname, same_path,
    split_name,
)
from src.filebrowser.settings import OPEN_WITH_SYSTEM
from src.filebrowser.threads import MainThreadInvoker, TaskRunner
from src.filebrowser.transfers import DONE, TransferJob, TransferQueue
from src.filebrowser.ui.dialogs import (
    COMPARE, CompareDialog, ConflictDialog, MoveConfirmDialog, OpenWithDialog, PackDialog,
    PropertiesDialog, SettingsDialog, ShortcutsDialog, SyncDialog, UrlDialog,
)
from src.filebrowser.ui.pane import FilePane, tool_button
from src.filebrowser.ui.session import CONNECTED, FAILED, RECONNECTING, HostSession
from src.filebrowser.ui.style import palette, stylesheet
from src.filebrowser.ui.transfer_panel import TransferPanel
from src.i18n import tr
from src.ui.dialogs.styled_message_box import StyledInputDialog, StyledMessageBox
from src.ui.icons import icon as svg_icon


class HostDirectory(Protocol):
    """What the browser needs from the app to open further hosts."""

    def connections(self) -> list: ...                  # the saved connections, in list order
    def prepare(self, conn_id: str): ...                # connection with credentials, or None


# ── Workspace (one tab) ──────────────────────────────────────────────────────

class Workspace(QWidget):
    """One tab: a host session's server pane plus, in split mode, a local pane."""

    def __init__(self, win: "FileBrowserView", session: HostSession,
                 remote_path: Optional[str], local_path: str, split: bool) -> None:
        super().__init__()
        self.win = win
        self.session = session
        self.remote: Optional[FilePane] = None
        self.local: Optional[FilePane] = None
        self.splitter: Optional[QSplitter] = None
        self.split = split
        self._remote_path = remote_path
        self._local_path = local_path
        self._local_loaded = False
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._build_placeholder())
        self.show_state()

    def _build_placeholder(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.addStretch()
        self._message = QLabel()
        self._message.setObjectName("fbHint")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        v.addWidget(self._message)
        self._retry = tool_button("refresh", tr("fb.session.retry"), self.win.palette.icon,
                                  tr("fb.session.retry"))
        self._retry.clicked.connect(lambda: self.win.reconnect_session(self.session))
        v.addWidget(self._retry, 0, Qt.AlignmentFlag.AlignCenter)
        v.addStretch()
        return page

    @property
    def attached(self) -> bool:
        return self.remote is not None

    def show_state(self) -> None:
        s = self.session
        failed = s.state == FAILED
        text = tr("fb.session.failed", name=s.name) if failed else tr("fb.session.connecting", name=s.name)
        if failed and s.error_text():
            text += "\n\n" + s.error_text()
        self._message.setText(text)
        self._retry.setVisible(failed)

    def attach(self) -> None:
        """The session is connected: build the panes."""
        if self.attached:
            return
        s, win = self.session, self.win
        c = win.palette.icon
        self.remote = FilePane(win, s.fs, "remote", win.manager, s.conn.id, c,
                               tree_root=s.tree_root(), origin=s.id)
        self.local = FilePane(win, win.local_fs, "local", win.manager, s.conn.id, c, origin=s.id)
        for pane in (self.local, self.remote):
            pane.session = s
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        # The divider can go all the way to either edge: dragged past a pane's
        # minimum width, that pane folds away (drag the edge back to restore;
        # F9 twice restores the half/half split).
        self.splitter.setChildrenCollapsible(True)
        self.splitter.addWidget(self.local)
        self.splitter.addWidget(self.remote)
        self._stack.addWidget(self.splitter)
        self._stack.setCurrentWidget(self.splitter)
        self.set_split(self.split)
        self.remote.navigate(self._remote_path or s.start_path)

    def set_split(self, on: bool) -> None:
        self.split = on
        if not self.attached:
            return
        self.local.setVisible(on)
        if on and not self._local_loaded:
            self._local_loaded = True
            self.local.navigate(self._local_path)
        total = sum(self.splitter.sizes()) or 1200
        if on:
            self.splitter.setSizes([total // 2, total - total // 2])
        else:
            self.splitter.setSizes([0, total])   # the server side may have been folded away

    def panes(self) -> list[FilePane]:
        if not self.attached:
            return []
        return [self.local, self.remote] if self.split else [self.remote]

    def all_panes(self) -> list[FilePane]:
        return [self.local, self.remote] if self.attached else []


# ── The browser ──────────────────────────────────────────────────────────────

class FileBrowserView(QWidget):
    def __init__(self, conn=None, manager=None, theme: str = "dark",
                 terminal_opener: Optional[Callable[[str, str], None]] = None,
                 hosts: Optional[HostDirectory] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.theme = theme
        self.palette = palette(theme)
        self._terminal_opener = terminal_opener
        self._hosts = hosts
        self.sessions: list[HostSession] = []
        self.local_fs = LocalFS()
        self._tasks = TaskRunner(self)
        self._invoker = MainThreadInvoker(self)
        self._temp_dir = tempfile.mkdtemp(prefix="neossh_fb_")
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_edited_file_changed)
        self._edits: dict[str, dict] = {}   # local temp path -> {session, remote, size, mtime}
        self._edit_timers: dict[str, QTimer] = {}
        self._active_pane: Optional[FilePane] = None
        self._closed = False
        self._build()
        self.manager.add_listener(self._on_settings_changed)
        self._update_session_ui()
        if conn is not None:
            self.open_host(conn)

    # ── the current tab's session (shortcuts used by tests and the toolbar) ──

    def session(self) -> Optional[HostSession]:
        ws = self.workspace()
        return ws.session if ws is not None else None

    @property
    def fs(self):
        s = self.session()
        return s.fs if s else None

    @property
    def queue(self) -> Optional[TransferQueue]:
        s = self.session()
        return s.queue if s else None

    @property
    def conn(self):
        s = self.session()
        return s.conn if s else None

    @property
    def drag_origin(self) -> str:
        s = self.session()
        return s.id if s else ""

    # ── skeleton ─────────────────────────────────────────────────────────────

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        root = QWidget()
        root.setObjectName("fbRoot")
        self._root = root
        self._apply_stylesheet()
        outer.addWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self._hosts_menu = QMenu(self)
        self._hosts_menu.aboutToShow.connect(self._fill_hosts_menu)
        v.addWidget(self._build_toolbar())

        self.tabs = QTabWidget()
        self.tabs.setObjectName("fbTabs")
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)       # Qt's base line is white in both themes
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        add = tool_button("plus", tr("fb.tabs.new") + "  (Ctrl+T)", self.palette.icon)
        add.clicked.connect(self.new_tab)
        if self._hosts is not None:
            add.setMenu(self._hosts_menu)
            add.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.tabs.setCornerWidget(add, Qt.Corner.TopRightCorner)

        self._center = QStackedWidget()
        self._center.addWidget(self._build_empty())
        self._center.addWidget(self.tabs)

        self._panel = TransferPanel(self.palette)
        self._vsplit = QSplitter(Qt.Orientation.Vertical)
        self._vsplit.setChildrenCollapsible(False)
        self._vsplit.addWidget(self._center)
        self._vsplit.addWidget(self._panel)
        self._vsplit.setStretchFactor(0, 1)
        state = self.manager.settings.window
        self._vsplit.setSizes(state.get("panel") or [600, 180])
        v.addWidget(self._vsplit, 1)

        status = QWidget()
        s = QHBoxLayout(status)
        s.setContentsMargins(0, 0, 0, 0)
        s.setSpacing(0)
        self._status = QLabel("")
        self._status.setObjectName("fbStatus")
        # Short confirmations ("3 items moved – Ctrl+Z undoes it"); the
        # status label itself is rewritten on every selection change.
        self._notice = QLabel("")
        self._notice.setObjectName("fbNotice")
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.setInterval(8000)
        self._notice_timer.timeout.connect(self._notice.clear)
        self._speed = QLabel("")
        self._speed.setObjectName("fbStatus")
        self._conn_lbl = QLabel("")
        self._conn_lbl.setObjectName("fbStatus")
        s.addWidget(self._status, 1)
        s.addWidget(self._notice)
        s.addWidget(self._speed)
        s.addWidget(self._conn_lbl)
        v.addWidget(status)

        self._speed_timer = QTimer(self)
        self._speed_timer.setInterval(1000)
        self._speed_timer.timeout.connect(self._update_speed)
        self._speed_timer.start()
        self._window_shortcuts()

    def _build_empty(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.addStretch()
        text = QLabel(tr("fb.empty.text"))
        text.setObjectName("fbHint")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setWordWrap(True)
        v.addWidget(text)
        if self._hosts is not None:
            btn = tool_button("cloud", tr("fb.tb.connect_tip"), self.palette.icon, tr("fb.tb.connect"))
            btn.setMenu(self._hosts_menu)
            btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            v.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
        v.addStretch()
        return page

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("fbToolbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 5, 8, 5)
        h.setSpacing(3)
        c = self.palette.icon

        def sep():
            f = QFrame()
            f.setObjectName("fbSep")
            f.setFrameShape(QFrame.Shape.VLine)
            f.setFixedWidth(1)
            h.addSpacing(4)
            h.addWidget(f)
            h.addSpacing(4)

        self._b_connect = tool_button("cloud", tr("fb.tb.connect_tip") + "  (Ctrl+Shift+O)", c,
                                      tr("fb.tb.connect"))
        self._b_connect.setMenu(self._hosts_menu)
        self._b_connect.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._b_connect.setVisible(self._hosts is not None)
        h.addWidget(self._b_connect)
        if self._hosts is not None:
            sep()

        self._b_split = tool_button("columns", tr("fb.tb.split_tip") + "  (F9)", c,
                                    tr("fb.tb.split"), checkable=True)
        self._b_split.clicked.connect(self.toggle_split)
        self._b_tree = tool_button("list-tree", tr("fb.tb.tree_tip"), c, checkable=True)
        self._b_tree.setChecked(self.manager.settings.show_tree)
        self._b_tree.clicked.connect(self.toggle_tree)
        h.addWidget(self._b_split)
        h.addWidget(self._b_tree)
        sep()

        self._b_upload = tool_button("upload", tr("fb.tb.upload") + "  (Ctrl+U)", c, tr("fb.tb.upload"))
        self._upload_menu = QMenu(self._b_upload)
        self._upload_menu.addAction(tr("fb.tb.upload_files") + "\tCtrl+U", self.upload_files)
        self._upload_menu.addAction(tr("fb.tb.upload_folder") + "\tCtrl+Shift+U", self.upload_folder)
        self._upload_menu.addAction(tr("fb.tb.upload_url") + "\tCtrl+Shift+L", self.upload_url)
        self._act_archive_up = self._upload_menu.addAction(tr("fb.tb.upload_archive"),
                                                           self.upload_folder_as_archive)
        self._b_upload.setMenu(self._upload_menu)
        self._b_upload.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._b_upload.clicked.connect(self.upload_files)
        self._b_download = tool_button("download", tr("fb.tb.download") + "  (Ctrl+Shift+D)", c,
                                       tr("fb.tb.download"))
        self._b_download.clicked.connect(lambda: self.download_entries(
            self.remote_pane(), self.remote_pane().selected_entries() if self.remote_pane() else []))
        h.addWidget(self._b_upload)
        h.addWidget(self._b_download)
        sep()

        self._b_undo = tool_button("undo", tr("fb.undo.nothing"), c)
        self._b_undo.clicked.connect(self.undo)
        self._b_redo = tool_button("redo", tr("fb.redo.nothing"), c)
        self._b_redo.clicked.connect(self.redo)
        h.addWidget(self._b_undo)
        h.addWidget(self._b_redo)
        sep()

        self._file_buttons = []
        for icon, tip, fn in (
            ("folder-plus", tr("fb.tb.new_folder") + "  (F7)", lambda: self.new_folder(self.active_pane())),
            ("file-plus", tr("fb.tb.new_file") + "  (Shift+F4)", lambda: self.new_file(self.active_pane())),
            ("edit", tr("fb.tb.rename") + "  (F2)", lambda: self._on_active(
                lambda p: self.rename_entry(p, p.current_entry()))),
            ("trash", tr("fb.tb.delete") + "  (Del)", lambda: self._on_active(
                lambda p: self.delete_entries(p, p.selected_entries()))),
            ("info", tr("fb.tb.properties") + "  (Alt+Enter)", lambda: self._on_active(
                lambda p: self.properties(p, p.selected_entries()))),
        ):
            b = tool_button(icon, tip, c)
            b.clicked.connect(fn)
            h.addWidget(b)
            self._file_buttons.append(b)
        sep()
        self._b_sync = tool_button("sync", tr("fb.tb.sync") + "  (Ctrl+Shift+S)", c, tr("fb.tb.sync"))
        self._b_sync.clicked.connect(self.sync_dialog)
        self._b_terminal = tool_button("terminal", tr("fb.tb.terminal") + "  (Ctrl+Shift+T)", c)
        self._b_terminal.clicked.connect(lambda: self._on_active(self.terminal_here, remote=True))
        h.addWidget(self._b_sync)
        h.addWidget(self._b_terminal)
        h.addStretch()
        keys = tool_button("keyboard", tr("fb.keys.title") + "  (F1)", c)
        keys.clicked.connect(lambda: ShortcutsDialog(self, self.theme).exec())
        settings = tool_button("settings", tr("fb.settings.title") + "  (Ctrl+,)", c,
                               tr("fb.tb.settings"))
        settings.clicked.connect(self.settings_dialog)
        h.addWidget(keys)
        h.addWidget(settings)
        self._toolbar_buttons = [self._b_split, self._b_upload, self._b_download, self._b_sync,
                                 self._b_terminal] + self._file_buttons
        return bar

    def _window_shortcuts(self) -> None:
        def sc(seq, fn):
            QShortcut(QKeySequence(seq), self, fn, context=Qt.ShortcutContext.WindowShortcut)
        sc("F9", self.toggle_split)
        sc("Ctrl+T", self.new_tab)
        sc("Ctrl+W", lambda: self.close_tab(self.tabs.currentIndex()))
        sc("Ctrl+Tab", lambda: self._cycle_tab(1))
        sc("Ctrl+Shift+Tab", lambda: self._cycle_tab(-1))
        sc("Ctrl+Shift+O", self._show_hosts_menu)
        sc("Ctrl+U", self.upload_files)
        sc("Ctrl+Shift+U", self.upload_folder)
        sc("Ctrl+Shift+L", self.upload_url)
        sc("Ctrl+Shift+D", lambda: self.remote_pane() and self.download_entries(
            self.remote_pane(), self.remote_pane().selected_entries()))
        sc("Ctrl+Shift+S", self.sync_dialog)
        sc("Ctrl+Shift+T", lambda: self._on_active(self.terminal_here, remote=True))
        sc("Ctrl+,", self.settings_dialog)
        sc("F1", lambda: ShortcutsDialog(self, self.theme).exec())
        # Text fields (filter, path) keep their own Ctrl+Z: Qt offers the key
        # to the focused line edit first.
        sc("Ctrl+Z", self.undo)
        sc("Ctrl+Y", self.redo)
        sc("Ctrl+Shift+Z", self.redo)

    # ── theme ────────────────────────────────────────────────────────────────

    def _apply_stylesheet(self) -> None:
        from src.ui.icons import svg_file
        # Every tab can be closed, so its button is always visible: draw it
        # in the theme's colours instead of Qt's grey default square.
        try:
            close_icons = (svg_file("x", self.palette.text_dim, self._temp_dir),
                           svg_file("x", self.palette.error, self._temp_dir))
        except OSError:
            close_icons = ("", "")
        self._root.setStyleSheet(stylesheet(self.palette, *close_icons))

    def set_theme(self, theme: str) -> None:
        """Switch theme or accent while hosts stay connected."""
        new_palette = palette(theme)
        if theme == self.theme and new_palette == self.palette:
            return
        self.theme = theme
        self.palette = new_palette
        self._apply_stylesheet()
        c = self.palette.icon
        for btn in self.findChildren(QToolButton):
            name = btn.property("fbIcon")
            if name:
                btn.setIcon(svg_icon(name, c, btn.iconSize().width() or 16))
        for pane in self._all_panes():
            pane.set_icon_color(c)
            pane.set_drop_color(self.palette.accent)
        self._panel.set_palette(self.palette)
        self._update_session_ui()

    # ── hosts & sessions ─────────────────────────────────────────────────────

    def session_for(self, conn_id: str) -> Optional[HostSession]:
        return next((s for s in self.sessions if s.conn.id == conn_id), None)

    def has_session(self, conn_id: str) -> bool:
        return self.session_for(conn_id) is not None

    def open_host(self, conn) -> HostSession:
        """Open conn in a new tab, or switch to the host's tab if it is open already."""
        session = self.session_for(conn.id)
        if session is not None:
            self.focus_session(session)
            if session.state == FAILED:
                self.reconnect_session(session)
            return session
        session = HostSession(conn, self.manager, self._tofu, self)
        session.state_changed.connect(self._on_session_state)
        self.sessions.append(session)
        self._add_workspace(session, None, bool(self.manager.settings.window.get("split", False)))
        session.connect()
        return session

    def focus_host(self, conn_id: str) -> bool:
        """Main window: show the host's tab (retrying a failed connection)."""
        session = self.session_for(conn_id)
        if session is None:
            return False
        self.focus_session(session)
        if session.state == FAILED:
            self.reconnect_session(session)
        return True

    def focus_session(self, session: HostSession) -> None:
        for i in range(self.tabs.count()):
            if self.tabs.widget(i).session is session:
                self.tabs.setCurrentIndex(i)
                return

    def connect_host(self, conn_id: str) -> None:
        """From the "Connect" menu: new tab for the host (or switch to it)."""
        if self.focus_host(conn_id):
            return
        conn = self._hosts.prepare(conn_id) if self._hosts is not None else None
        if conn is not None:
            self.open_host(conn)

    def reconnect_session(self, session: HostSession) -> None:
        session.connect()

    def _show_hosts_menu(self) -> None:
        if self._hosts is None:
            return
        if self._b_connect.isVisible():
            self._b_connect.showMenu()
        else:
            self._hosts_menu.exec(self.mapToGlobal(self.rect().center()))

    def _fill_hosts_menu(self) -> None:
        menu = self._hosts_menu
        menu.clear()
        try:
            conns = list(self._hosts.connections()) if self._hosts is not None else []
        except Exception as e:
            logger.warning("filebrowser: could not list connections: %s", e)
            conns = []
        if not conns:
            empty = menu.addAction(tr("fb.hosts.none"))
            empty.setEnabled(False)
            return
        open_ids = {s.conn.id for s in self.sessions}
        for c in conns:
            user = getattr(c, "user", "") or ""
            where = f"{user}@{c.host}" if user else c.host
            if c.is_ftp:
                where += f"  ({c.protocol_label})"
            is_open = c.id in open_ids               # open hosts: green and bold
            icon = svg_icon("folder", self.palette.ok if is_open else self.palette.icon, 14)
            act = menu.addAction(icon, f"{c.name or c.host}\t{where}")
            if is_open:
                font = act.font()
                font.setBold(True)
                act.setFont(font)
            act.triggered.connect(lambda _checked=False, cid=c.id: self.connect_host(cid))

    def _on_session_state(self, session: HostSession) -> None:
        if session.closed:
            return
        if session.state == CONNECTED and session.queue is None:
            self._attach_queue(session)
        for ws in self._workspaces(session):
            if session.connected:
                self._attach_workspace(ws)
            else:
                ws.show_state()
        if session is self.session():
            self._update_session_ui()
        if session.state == FAILED:
            self.focus_session(session)
            StyledMessageBox.critical(self, tr("sftp.error.connect_title"),
                                      f"{session.name}\n\n{session.error_text()}")

    def _attach_queue(self, session: HostSession) -> None:
        queue = TransferQueue(session.fs, self.manager,
                              lambda info, s=session: self._resolve_conflict(s, info),
                              self.local_fs, self)
        queue.target_changed.connect(
            lambda side, directory, s=session: self._on_target_changed(side, directory, s))
        queue.message.connect(lambda msg: self.show_error(tr("fb.error.transfer_title"), msg))
        queue.activity_changed.connect(self._update_speed)
        session.queue = queue
        self._panel.add_queue(queue, session.name)

    def _close_session(self, session: HostSession) -> None:
        if session.queue is not None:
            self._panel.remove_queue(session.queue)
        session.close()
        if session in self.sessions:
            self.sessions.remove(session)

    def _update_session_ui(self) -> None:
        """Title, connection state and toolbar for the current tab's host."""
        s = self.session()
        ws = self.workspace()
        if s is None:
            self.setWindowTitle(tr("fb.window.title_empty"))
            self._conn_lbl.setText("")
            self._status.setText("")
        else:
            self.setWindowTitle(tr("fb.window.title", name=s.name, proto=s.conn.protocol_label))
            self._show_conn_state(s.state)
        ready = s is not None and s.connected and ws is not None and ws.attached
        for b in self._toolbar_buttons:
            b.setEnabled(ready)
        can_exec = ready and bool(getattr(s.fs, "can_exec", False))
        self._b_terminal.setEnabled(can_exec and self._terminal_opener is not None)
        self._act_archive_up.setEnabled(can_exec)
        self._b_split.setChecked(bool(ws and ws.split))
        self._update_history_actions()

    def _show_conn_state(self, state: str) -> None:
        text = {CONNECTED: tr("fb.status.connected"), RECONNECTING: tr("fb.status.reconnecting"),
                FAILED: tr("fb.status.connect_failed")}.get(state, tr("fb.status.connecting"))
        self._conn_lbl.setText("● " + text)
        self._conn_lbl.setProperty("state", state)
        color = {CONNECTED: self.palette.ok, RECONNECTING: self.palette.warn,
                 FAILED: self.palette.error}.get(state, self.palette.text_dim)
        self._conn_lbl.setStyleSheet(f"color: {color};")

    def _tofu(self, host: str, port: int, fingerprint: str) -> bool:
        return bool(self._invoker.call(lambda: StyledMessageBox.question(
            self, tr("sftp.tofu.title"), tr("sftp.tofu.body", host=host, fingerprint=fingerprint),
            yes_text=tr("dialog.yes"), no_text=tr("dialog.no")), default=False))

    # ── tabs & panes ─────────────────────────────────────────────────────────

    def _local_start(self) -> str:
        s = self.manager.settings
        for path in (s.last_local, s.local_start, "C:\\", os.path.expanduser("~")):
            if path and os.path.isdir(path):
                return path
        return ""

    def _add_workspace(self, session: HostSession, remote_path: Optional[str],
                       split: bool) -> Workspace:
        ws = Workspace(self, session, remote_path, self._local_start(), split)
        idx = self.tabs.addTab(ws, session.name)
        self.tabs.setTabToolTip(idx, f"{session.name} ({session.conn.host})")
        self._center.setCurrentWidget(self.tabs)
        if session.connected:
            self._attach_workspace(ws)
        self.tabs.setCurrentIndex(idx)
        return ws

    def _attach_workspace(self, ws: Workspace) -> None:
        if ws.attached:
            return
        ws.attach()
        for pane in ws.all_panes():
            pane.activated.connect(self._set_active)
            pane.status_changed.connect(self._on_pane_status)
            pane.path_changed.connect(self._on_path_changed)
        if ws is self.workspace():
            self._active_pane = None
            self._set_active(ws.remote)
            self._update_session_ui()

    def _workspaces(self, session: Optional[HostSession] = None) -> list[Workspace]:
        spaces = [self.tabs.widget(i) for i in range(self.tabs.count())]
        return [ws for ws in spaces if session is None or ws.session is session]

    def workspace(self) -> Optional[Workspace]:
        return self.tabs.currentWidget()

    def remote_pane(self) -> Optional[FilePane]:
        ws = self.workspace()
        return ws.remote if ws is not None and ws.attached else None

    def active_pane(self) -> Optional[FilePane]:
        ws = self.workspace()
        if ws is None or not ws.attached:
            return None
        if self._active_pane in ws.panes():
            return self._active_pane
        return ws.remote

    def focus_current(self) -> None:
        """The page was shown: keyboard focus into the active file list."""
        pane = self.active_pane()
        if pane is not None:
            pane.view.setFocus()

    def _on_active(self, fn, remote: bool = False) -> None:
        pane = self.remote_pane() if remote else self.active_pane()
        if pane is not None:
            fn(pane)

    def _set_active(self, pane: FilePane) -> None:
        if self._active_pane is pane:
            return
        try:
            if self._active_pane is not None:
                self._active_pane.set_active(False)
        except RuntimeError:
            pass
        self._active_pane = pane
        pane.set_active(True)
        self._on_pane_status(pane)

    def _on_pane_status(self, pane: FilePane) -> None:
        if pane is self.active_pane():
            self._status.setText(pane.status_text())

    def _on_path_changed(self, pane: FilePane) -> None:
        s = self.manager.settings
        if pane.local:
            s.last_local = pane.current_dir
            return
        session = pane.session
        s.last_remote[session.conn.id] = pane.current_dir
        for ws in self._workspaces(session):
            if ws.remote is pane:
                idx = self.tabs.indexOf(ws)
                self.tabs.setTabText(idx, f"{session.name} · {rname(pane.current_dir) or '/'}")
                self.tabs.setTabToolTip(idx, f"{session.name} ({session.conn.host})\n"
                                             f"{pane.display_path(pane.current_dir)}")

    def new_tab(self) -> None:
        """Another tab for the current host (same connection)."""
        ws = self.workspace()
        if ws is None or not ws.session.connected:
            return
        pane = ws.remote
        self._add_workspace(ws.session, pane.current_dir if pane else None, ws.split)

    def close_tab(self, index: int) -> None:
        if index < 0 or index >= self.tabs.count():
            return
        ws = self.tabs.widget(index)
        session = ws.session
        last_of_host = len(self._workspaces(session)) == 1
        if last_of_host and session.active_transfers() and not StyledMessageBox.question(
                self, tr("fb.close.title"),
                tr("fb.close.session_text", name=session.name, count=session.active_transfers()),
                yes_text=tr("fb.close.yes"), no_text=tr("dialog.cancel")):
            return
        self.tabs.removeTab(index)
        if self._active_pane in ws.all_panes():
            self._active_pane = None
        ws.deleteLater()
        if last_of_host:
            self._close_session(session)
        if not self.tabs.count():
            self._center.setCurrentIndex(0)
        self._on_tab_changed(self.tabs.currentIndex())

    def _cycle_tab(self, step: int) -> None:
        if self.tabs.count():
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % self.tabs.count())

    def _on_tab_changed(self, _index: int) -> None:
        ws = self.workspace()
        self._active_pane = None
        if ws is not None and ws.attached:
            self._set_active(ws.remote)
        self._update_session_ui()

    def toggle_split(self) -> None:
        ws = self.workspace()
        if ws is None or not ws.attached:
            return
        ws.set_split(not ws.split)
        self._b_split.setChecked(ws.split)
        self.manager.settings.window["split"] = ws.split
        (ws.local if ws.split else ws.remote).view.setFocus()

    def toggle_tree(self) -> None:
        self.manager.settings.show_tree = not self.manager.settings.show_tree
        self.manager.save()

    def focus_other_pane(self, pane: FilePane) -> None:
        ws = self.workspace()
        if ws and ws.attached and ws.split:
            (ws.remote if pane is ws.local else ws.local).view.setFocus()

    def _all_panes(self, session: Optional[HostSession] = None) -> list[FilePane]:
        """All panes; with a session: its server panes and every local pane."""
        panes = []
        for ws in self._workspaces():
            for pane in ws.all_panes():
                if session is None or pane.local or ws.session is session:
                    panes.append(pane)
        return panes

    def _on_target_changed(self, side: str, directory: str,
                           session: Optional[HostSession] = None) -> None:
        for pane in self._all_panes(session):
            if pane.side != side or pane.current_dir is None:
                continue
            if same_path(pane.current_dir, directory, pane.local):
                self._schedule_refresh(pane)
            if not pane.tree.isHidden():         # also while the page is in the background
                pane.tree.refresh_folder(directory)

    def _schedule_refresh(self, pane: FilePane) -> None:
        # Many small uploads finish in quick succession: refresh once.
        timer = getattr(pane, "_refresh_timer", None)
        if timer is None:
            timer = QTimer(pane)
            timer.setSingleShot(True)
            timer.setInterval(400)
            timer.timeout.connect(pane.refresh)
            pane._refresh_timer = timer
        timer.start()

    def _on_settings_changed(self, settings) -> None:
        for session in self.sessions:
            if session.queue:
                session.queue.apply_settings()
        self._b_tree.setChecked(settings.show_tree)
        for pane in self._all_panes():
            pane.apply_settings(settings)
            if not pane.local:
                pane.set_tree_root(pane.session.tree_root())

    def active_transfer_count(self) -> int:
        return sum(s.active_transfers() for s in self.sessions)

    def _update_speed(self) -> None:
        from src.filebrowser.model import fmt_speed
        queues = [s.queue for s in self.sessions if s.queue]
        up = sum(q.total_speed("up") for q in queues)
        down = sum(q.total_speed("down") for q in queues)
        active = sum(q.active_count() for q in queues)
        parts = []
        if active:
            parts.append(tr("fb.status.transfers", count=active))
        if up:
            parts.append("↑ " + fmt_speed(up))
        if down:
            parts.append("↓ " + fmt_speed(down))
        self._speed.setText("   ".join(parts))

    # ── errors / helpers ─────────────────────────────────────────────────────

    def show_error(self, title: str, message: str) -> None:
        StyledMessageBox.critical(self, title, message)

    def _run(self, fn, done=None, error_title: Optional[str] = None, busy: str = "") -> None:
        if busy:
            self._status.setText(busy)

        def failed(e):
            self.show_error(error_title or tr("fb.error.generic_title"), str(e))
            pane = self.active_pane()
            if pane:
                self._on_pane_status(pane)
        self._tasks.run(fn, done, failed)

    def _other_pane(self, pane: FilePane) -> Optional[FilePane]:
        ws = self.workspace()
        if not ws or not ws.attached or not ws.split:
            return None
        return ws.remote if pane is ws.local else ws.local

    @staticmethod
    def _usable(session: Optional[HostSession]) -> bool:
        return session is not None and not session.closed and session.queue is not None

    # ── activation / opening ─────────────────────────────────────────────────

    def activate_entry(self, pane: FilePane, entry: FileEntry) -> None:
        if entry.is_up:
            pane.go_up()
        elif entry.is_dir:
            pane.navigate(entry.path)
        elif pane.local:
            self._launch_local(entry.path, None)
        elif self.manager.settings.double_click == "download":
            self.download_entries(pane, [entry])
        else:
            self.open_entry(pane, entry)

    def open_entries(self, pane: FilePane, entries: list[FileEntry]) -> None:
        for entry in entries[:10]:
            self.open_entry(pane, entry)

    def open_entry(self, pane: FilePane, entry: FileEntry) -> None:
        if entry is None or entry.is_dir:
            return
        if pane.local:
            self._launch_local(entry.path, None)
        else:
            self._open_remote(pane.session, entry, None)

    def open_with(self, pane: FilePane, entry: Optional[FileEntry], choose: bool = True) -> None:
        if entry is None or entry.is_dir:
            return
        ext = entry.extension
        program = OpenWithDialog.choose(self, ext, self.theme, self.manager.settings.program_for(ext))
        if not program:
            return
        self.manager.settings.open_with[ext] = program
        self.manager.save()
        if pane.local:
            self._launch_local(entry.path, program)
        else:
            self._open_remote(pane.session, entry, program)

    def _program_for(self, ext: str) -> Optional[str]:
        """The remembered program; asks once per extension."""
        program = self.manager.settings.program_for(ext)
        if program:
            return program
        program = OpenWithDialog.choose(self, ext, self.theme)
        if program:
            self.manager.settings.open_with[ext] = program
            self.manager.save()
        return program

    def _open_remote(self, session: HostSession, entry: FileEntry, program: Optional[str]) -> None:
        if not self._usable(session):
            return
        program = program or self._program_for(entry.extension)
        if not program:
            return
        local = os.path.join(self._temp_dir, uuid.uuid4().hex[:8], entry.name)

        def downloaded(job: TransferJob) -> None:
            if job.state != DONE:
                if job.error:
                    self.show_error(tr("fb.error.open_title"), job.error)
                return
            self._edits[local] = {"session": session, "remote": entry.path,
                                  "size": job.size, "mtime": job.mtime}
            self._watcher.addPath(local)
            self._launch_local(local, program)

        self._status.setText(tr("fb.status.opening", name=entry.name))
        session.queue.download_to(entry, local, decision=OVERWRITE, on_done=downloaded)

    def _launch_local(self, path: str, program: Optional[str]) -> None:
        try:
            if program and program != OPEN_WITH_SYSTEM:
                subprocess.Popen([program, path], close_fds=True)
            else:
                os.startfile(path)
        except OSError as e:
            if program in (None, OPEN_WITH_SYSTEM):
                # No Windows association: let the user pick a program instead.
                ext = split_name(os.path.basename(path))[1].lstrip(".").lower()
                chosen = OpenWithDialog.choose(self, ext, self.theme)
                if chosen and chosen != OPEN_WITH_SYSTEM:
                    self.manager.settings.open_with[ext] = chosen
                    self.manager.save()
                    self._launch_local(path, chosen)
                return
            self.show_error(tr("fb.error.open_title"), f"{program}\n\n{e}")

    # edit & save back
    def _on_edited_file_changed(self, local: str) -> None:
        if local not in self._edits:
            return
        if local not in self._watcher.files() and os.path.exists(local):
            self._watcher.addPath(local)          # editors that replace the file on save
        timer = self._edit_timers.get(local)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(700)
            timer.timeout.connect(lambda l=local: self._upload_edit(l))
            self._edit_timers[local] = timer
        timer.start()

    def _upload_edit(self, local: str) -> None:
        info = self._edits.get(local)
        if not info or not os.path.exists(local):
            return
        session: HostSession = info["session"]
        if not self._usable(session):
            self.show_error(tr("fb.error.transfer_title"),
                            tr("fb.edit.session_closed", name=session.name, file=rname(info["remote"])))
            return
        remote = info["remote"]
        fs = session.fs

        def check():
            # Off the UI thread: current server state plus the sibling names
            # needed for a "keep both" name.
            parent = fs.parent(remote)
            return fs.stat(remote), {e.name for e in fs.listdir(parent)}

        def upload(result) -> None:
            current, names = result
            changed = current is not None and (
                current.size != info["size"] or abs(current.mtime - info["mtime"]) > 2)
            target = remote
            if changed:
                overwrite = StyledMessageBox.question(
                    self, tr("fb.edit.changed_title"),
                    tr("fb.edit.changed_text", name=rname(remote)),
                    yes_text=tr("fb.conflict.overwrite"), no_text=tr("fb.conflict.keep_both"))
                if not overwrite:
                    target = rjoin(fs.parent(remote), keep_both_name(rname(remote), names.__contains__))

            def remember(entry: Optional[FileEntry]) -> None:
                if entry:
                    info["size"], info["mtime"] = entry.size, entry.mtime

            def saved(job: TransferJob) -> None:
                if job.state == DONE:
                    info["remote"] = target
                    self._tasks.run(lambda: fs.stat(target), remember)
                    self._status.setText(tr("fb.status.saved", name=rname(target)))
                elif job.error:
                    self.show_error(tr("fb.error.transfer_title"), job.error)
            if self._usable(session):
                session.queue.upload_to(local, target, decision=OVERWRITE, on_done=saved)

        self._run(check, upload, tr("fb.error.transfer_title"))

    # ── transfers ────────────────────────────────────────────────────────────

    def _choose_download_dir(self, pane: FilePane) -> Optional[str]:
        other = self._other_pane(pane)
        if other is not None and other.local and other.current_dir:
            return other.current_dir
        start = self.manager.settings.window.get("download_dir") or os.path.join(
            os.path.expanduser("~"), "Downloads")
        path = QFileDialog.getExistingDirectory(self, tr("fb.tb.download"), start)
        if path:
            self.manager.settings.window["download_dir"] = path
            return os.path.normpath(path)
        return None

    def download_entries(self, pane: Optional[FilePane], entries: list[FileEntry]) -> None:
        if pane is None or pane.local or not entries or not self._usable(pane.session):
            return
        target = self._choose_download_dir(pane)
        if target:
            pane.session.queue.download(entries, target)

    def upload_files(self) -> None:
        pane = self.remote_pane()
        if pane is None or not self._usable(pane.session):
            return
        paths, _ = QFileDialog.getOpenFileNames(self, tr("fb.tb.upload_files"),
                                                self.manager.settings.last_local or "")
        if paths:
            pane.session.queue.upload([os.path.normpath(p) for p in paths], pane.current_dir)

    def upload_folder(self) -> None:
        pane = self.remote_pane()
        if pane is None or not self._usable(pane.session):
            return
        path = QFileDialog.getExistingDirectory(self, tr("fb.tb.upload_folder"),
                                                self.manager.settings.last_local or "")
        if path:
            pane.session.queue.upload([os.path.normpath(path)], pane.current_dir)

    def upload_folder_as_archive(self) -> None:
        pane = self.remote_pane()
        if pane is None or not self._usable(pane.session) or not pane.session.fs.can_exec:
            return
        path = QFileDialog.getExistingDirectory(self, tr("fb.tb.upload_archive"),
                                                self.manager.settings.last_local or "")
        if not path:
            return
        if StyledMessageBox.question(self, tr("fb.tb.upload_archive"),
                                     tr("fb.archive.upload_confirm",
                                        folder=os.path.basename(path),
                                        target=pane.display_path(pane.current_dir)),
                                     yes_text=tr("fb.archive.start"), no_text=tr("dialog.cancel")):
            pane.session.queue.upload_folder_as_archive(os.path.normpath(path), pane.current_dir)

    def upload_url(self) -> None:
        pane = self.remote_pane()
        if pane is None or not self._usable(pane.session):
            return
        dlg = UrlDialog(self, self.theme, pane.display_path(pane.current_dir),
                        pane.session.fs.can_exec)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result:
            url, name, via_server = dlg.result
            pane.session.queue.upload_url(url, rjoin(pane.current_dir, name), via_server)

    def transfer_to_other(self, pane: FilePane, entries: list[FileEntry]) -> None:
        other = self._other_pane(pane)
        if other is None or not entries or not self._usable(pane.session):
            return
        queue = pane.session.queue
        if pane.local and other.current_dir is not None:
            queue.upload([e.path for e in entries], other.current_dir)
        elif other.local and other.current_dir:
            queue.download(entries, other.current_dir)

    def handle_drop(self, pane: FilePane, side: str, entries: list[FileEntry], target: str) -> None:
        """A checked drop (FilePane.plan_drop) onto the list, the tree or the path bar."""
        if not self._usable(pane.session):
            return
        # Handled after the drop event returns: a dialog inside it would keep
        # the drag source (possibly Explorer) waiting.
        QTimer.singleShot(0, lambda: self._handle_drop(pane, side, entries, target))

    def _handle_drop(self, pane: FilePane, side: str, entries: list[FileEntry], target: str) -> None:
        if not self._usable(pane.session):
            return
        queue = pane.session.queue
        if side == pane.side:
            self.move_entries(pane, entries, target)
        elif not pane.local:
            queue.upload([e.path for e in entries], target)
        elif side == "remote" and target:
            queue.download(entries, target)

    def move_entries(self, pane: FilePane, entries: list[FileEntry], target: str) -> None:
        """Move within one side (drag & drop); asks first unless switched off."""
        if not entries:
            return
        settings = self.manager.settings
        if settings.confirm_move:
            dlg = MoveConfirmDialog(self, self.theme, [e.name for e in entries],
                                    pane.display_path(target))
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            if dlg.dont_ask:
                settings.confirm_move = False
                self.manager.save()
        fs, side, session = pane.fs, pane.side, pane.session

        def work():
            done, errors = [], []
            for e in entries:
                new = fs.join(target, e.name)
                try:
                    fs.move(e.path, new)
                    done.append((e.path, new))
                except FsError as ex:
                    errors.append(f"{e.name}: {ex}")
            return done, errors

        def finished(result) -> None:
            done, errors = result
            if done:
                op = UndoOp(MOVE, side, done)
                session.history.push(op)
                self._after_op(session, op, undone=False)
                self.notify(tr("fb.status.moved", count=len(done)))
            self._update_history_actions()
            if errors:
                self.show_error(tr("fb.error.move_title"), "\n".join(errors))

        self._run(work, finished, tr("fb.error.move_title"),
                  busy=tr("fb.status.moving", count=len(entries)))

    # ── undo / redo (per host; the current tab's host) ───────────────────────

    def _fs_for(self, session: HostSession, side: str):
        return self.local_fs if side == "local" else session.fs

    def describe_op(self, session: HostSession, op: UndoOp) -> str:
        fs = self._fs_for(session, op.side) or self.local_fs
        first = op.items[0]
        if op.kind == MOVE:
            if len(op.items) == 1:
                return tr("fb.op.move_one", name=fs.basename(first[0]))
            return tr("fb.op.move_many", count=len(op.items))
        if op.kind == RENAME:
            return tr("fb.op.rename", old=fs.basename(first[0]), new=fs.basename(first[1]))
        if op.kind == MKDIR:
            return tr("fb.op.mkdir", name=fs.basename(first))
        return tr("fb.op.mkfile", name=fs.basename(first))

    def undo_label(self) -> str:
        s = self.session()
        op = s.history.peek_undo() if s else None
        return tr("fb.undo.action", action=self.describe_op(s, op)) if op else tr("fb.undo.nothing")

    def redo_label(self) -> str:
        s = self.session()
        op = s.history.peek_redo() if s else None
        return tr("fb.redo.action", action=self.describe_op(s, op)) if op else tr("fb.redo.nothing")

    def can_undo(self) -> bool:
        s = self.session()
        return bool(s and s.connected and not s.history_busy and s.history.peek_undo() is not None)

    def can_redo(self) -> bool:
        s = self.session()
        return bool(s and s.connected and not s.history_busy and s.history.peek_redo() is not None)

    def _update_history_actions(self) -> None:
        self._b_undo.setEnabled(self.can_undo())
        self._b_redo.setEnabled(self.can_redo())
        self._b_undo.setToolTip(self.undo_label() + "  (Ctrl+Z)")
        self._b_redo.setToolTip(self.redo_label() + "  (Ctrl+Y)")

    def _record(self, session: HostSession, op: UndoOp) -> None:
        session.history.push(op)
        self._update_history_actions()

    def undo(self) -> None:
        self._step(undo=True)

    def redo(self) -> None:
        self._step(undo=False)

    def _step(self, undo: bool) -> None:
        if not (self.can_undo() if undo else self.can_redo()):
            return
        session = self.session()
        history = session.history
        op = history.take_undo() if undo else history.take_redo()
        label = self.describe_op(session, op)
        fs = self._fs_for(session, op.side)
        session.history_busy = True
        self._update_history_actions()

        def finished(result) -> None:
            session.history_busy = False
            if result.done is not None:
                (history.undone if undo else history.redone)(result.done)
                self._after_op(session, result.done, undone=undo)
                self.notify(tr("fb.status.undone" if undo else "fb.status.redone", action=label))
            self._update_history_actions()
            if result.errors:
                lines = []
                for name, error in result.errors:
                    if isinstance(error, NotEmpty):
                        lines.append(tr("fb.undo.not_empty", name=name))
                    elif isinstance(error, Modified):
                        lines.append(tr("fb.undo.modified", name=name))
                    else:
                        lines.append(f"{name}: {error}")
                self.show_error(tr("fb.error.undo_title" if undo else "fb.error.redo_title"),
                                "\n".join(lines))

        def failed(error) -> None:
            # Unexpected failure (not per item): keep the operation where it was.
            (history.redone if undo else history.undone)(op)
            session.history_busy = False
            self._update_history_actions()
            self.show_error(tr("fb.error.undo_title" if undo else "fb.error.redo_title"), str(error))

        self._status.setText(tr("fb.status.working"))
        self._tasks.run(lambda: apply_op(fs, op, undo), finished, failed)

    def _after_op(self, session: HostSession, op: UndoOp, undone: bool) -> None:
        """Refresh the folders an operation touched; panes inside a moved folder follow it."""
        fs = self._fs_for(session, op.side)
        if fs is None:
            return
        local = op.side == "local"
        folders: list[str] = []
        if op.kind in (MOVE, RENAME):
            for old, new in op.items:
                src, dst = (new, old) if undone else (old, new)
                folders += [fs.parent(src), fs.parent(dst)]
                self._follow_move(session, op.side, src, dst)
        else:
            folders += [fs.parent(p) for p in op.items]
        unique: list[str] = []
        for folder in folders:
            if not any(same_path(folder, u, local) for u in unique):
                unique.append(folder)
        for folder in unique:
            self._on_target_changed(op.side, folder, session)

    def _follow_move(self, session: HostSession, side: str, src: str, dst: str) -> None:
        local = side == "local"
        for pane in self._all_panes(session):
            if pane.side != side or not pane.current_dir:
                continue
            moved = rebase_path(pane.current_dir, src, dst, local)
            if moved is not None and not same_path(moved, pane.current_dir, local):
                pane.navigate(moved, push=False)

    def notify(self, text: str) -> None:
        self._notice.setText(text)
        self._notice_timer.start()

    # ── file operations ──────────────────────────────────────────────────────

    def delete_entries(self, pane: FilePane, entries: list[FileEntry]) -> None:
        if not entries:
            return
        if self.manager.settings.confirm_delete:
            names = "\n".join("• " + e.name for e in entries[:8])
            if len(entries) > 8:
                names += "\n" + tr("fb.delete.more", count=len(entries) - 8)
            text = tr("fb.delete.local_text" if pane.local else "fb.delete.remote_text",
                      count=len(entries)) + "\n\n" + names
            if not StyledMessageBox.question(self, tr("fb.delete.title"), text,
                                             yes_text=tr("fb.delete.yes"), no_text=tr("dialog.cancel")):
                return
        fs = pane.fs
        paths = [e.path for e in entries]
        self._run(lambda: fs.remove_many(paths), lambda _r: pane.refresh(),
                  tr("fb.error.delete_title"), busy=tr("fb.status.deleting", count=len(paths)))

    def rename_entry(self, pane: FilePane, entry: Optional[FileEntry]) -> None:
        if entry is None:
            return
        dlg = StyledInputDialog(self, tr("fb.rename.title"), tr("fb.rename.prompt"), entry.name)
        stem = split_name(entry.name)[0] if not entry.is_dir else entry.name
        dlg._input.setSelection(0, len(stem))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new = dlg._input.text().strip()
        if not new or new == entry.name or "/" in new or "\\" in new:
            return
        fs, session = pane.fs, pane.session
        new_path = fs.join(pane.current_dir, new)

        def renamed(_result) -> None:
            op = UndoOp(RENAME, pane.side, [(entry.path, new_path)])
            self._record(session, op)
            pane.refresh([new])
            self._after_op(session, op, undone=False)   # folder tree, tabs inside a renamed folder

        self._run(lambda: fs.rename(entry.path, new_path), renamed, tr("fb.error.rename_title"))

    def new_folder(self, pane: Optional[FilePane]) -> None:
        self._create(pane, folder=True)

    def new_file(self, pane: Optional[FilePane]) -> None:
        self._create(pane, folder=False)

    def _create(self, pane: Optional[FilePane], folder: bool) -> None:
        if pane is None or not pane.current_dir:
            return
        name, ok = StyledInputDialog.get_text(
            self, tr("fb.new_folder.title" if folder else "fb.new_file.title"),
            tr("fb.new_folder.prompt" if folder else "fb.new_file.prompt"),
            tr("fb.new_folder.default" if folder else "fb.new_file.default"))
        name = name.strip()
        if not ok or not name or "/" in name or "\\" in name:
            return
        fs, session = pane.fs, pane.session
        path = fs.join(pane.current_dir, name)
        fn = (lambda: fs.mkdir(path)) if folder else (lambda: fs.create_empty(path))

        def created(_result) -> None:
            self._record(session, UndoOp(MKDIR if folder else MKFILE, pane.side, [path]))
            pane.refresh([name])

        self._run(fn, created, tr("fb.error.create_title"))

    def properties(self, pane: FilePane, entries: list[FileEntry]) -> None:
        if not entries:
            if not pane.current_dir:
                return
            entries = [FileEntry(name=pane.fs.basename(pane.current_dir), path=pane.current_dir,
                                 is_dir=True)]
        PropertiesDialog(self, self.theme, pane.fs, entries).exec()
        pane.refresh()

    def copy_paths(self, pane: FilePane, entries: list[FileEntry]) -> None:
        paths = [e.path for e in entries] or [pane.current_dir]
        QGuiApplication.clipboard().setText("\n".join(pane.display_path(p) for p in paths))
        self._status.setText(tr("fb.status.copied", count=len(paths)))

    def show_in_explorer(self, entries: list[FileEntry]) -> None:
        if entries:
            subprocess.Popen(["explorer", "/select,", entries[0].path])

    def terminal_here(self, pane: FilePane) -> None:
        session = pane.session
        if self._terminal_opener is None or session is None or session.fs is None \
                or not getattr(session.fs, "can_exec", False):
            return
        self._terminal_opener(session.conn.id,
                              commands.terminal_cd_input(session.fs.is_windows, pane.current_dir))

    # archives, checksum, duplicate (SSH exec)
    def pack(self, pane: FilePane, entries: list[FileEntry]) -> None:
        if not entries:
            return
        dlg = PackDialog(self, self.theme, [e.name for e in entries],
                         self.manager.settings.archive_format)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, fmt = dlg.values()
        cmd = commands.pack_command(pane.fs.is_windows, pane.current_dir,
                                    [e.name for e in entries], name, fmt)
        self._exec(cmd, pane, tr("fb.status.packing"), select=[name])

    def extract(self, pane: FilePane, entry: FileEntry) -> None:
        cmd = commands.extract_command(pane.fs.is_windows, entry.path, pane.current_dir)
        self._exec(cmd, pane, tr("fb.status.extracting"))

    def duplicate(self, pane: FilePane, entry: FileEntry) -> None:
        names = {e.name for e in pane.entries()}
        new = keep_both_name(entry.name, names.__contains__)
        cmd = commands.duplicate_command(pane.fs.is_windows, entry.path,
                                         rjoin(pane.current_dir, new))
        self._exec(cmd, pane, tr("fb.status.working"), select=[new])

    def _exec(self, cmd: str, pane: FilePane, busy: str, select: Optional[list[str]] = None) -> None:
        fs = pane.fs

        def work():
            code, out, err = fs.run(cmd, timeout=3600)
            if code != 0:
                raise FsError((err or out).strip() or f"exit code {code}")
        self._run(work, lambda _r: pane.refresh(select), tr("fb.error.command_title"), busy=busy)

    def download_as_archive(self, pane: FilePane, entries: list[FileEntry]) -> None:
        if not self._usable(pane.session):
            return
        target = self._choose_download_dir(pane)
        if target:
            pane.session.queue.download_as_archive(entries, target)

    # ── dialogs ──────────────────────────────────────────────────────────────

    def settings_dialog(self) -> None:
        SettingsDialog(self, self.manager, self.theme).exec()

    def sync_dialog(self) -> None:
        pane = self.remote_pane()
        if pane is None or not self._usable(pane.session):
            return
        ws = self.workspace()
        local_dir = ws.local.current_dir if ws.split and ws.local.current_dir else self._local_start()
        dlg = SyncDialog(self, self.theme, self.local_fs, pane.fs, local_dir, pane.current_dir,
                         pane.display_path)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.items:
            pane.session.queue.sync(dlg.items, *dlg.roots)

    # conflicts (called from transfer threads)
    def _resolve_conflict(self, session: HostSession, info):
        return self._invoker.call(lambda: self._ask_conflict(session, info), default=(CANCEL, True))

    def _ask_conflict(self, session: HostSession, info):
        while True:
            dlg = ConflictDialog(self, info, self.theme)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return CANCEL, True
            if dlg.decision != COMPARE:
                return dlg.decision, dlg.apply_all
            decision = self._compare(session, info)
            if decision:
                return decision, dlg.apply_all

    def _compare(self, session: HostSession, info) -> Optional[str]:
        """Fetch the remote side into a temp file and show both files side by side."""
        up = info.direction == "up"
        remote_entry = info.target if up else info.source
        local_entry = info.source if up else info.target
        temp = self._fetch_temp(session, remote_entry)
        if temp is None:
            return None
        left_file, right_file = (local_entry.path, temp) if up else (temp, local_entry.path)
        dlg = CompareDialog(
            self, self.theme, self.palette,
            tr("fb.conflict.source_local") if up else tr("fb.conflict.source_remote"), info.source, left_file,
            tr("fb.conflict.target_remote") if up else tr("fb.conflict.target_local"), info.target, right_file,
            decisions=True, can_resume=info.can_resume)
        dlg.exec()
        try:
            os.remove(temp)
        except OSError:
            pass
        return dlg.decision

    def _fetch_temp(self, session: HostSession, entry: FileEntry) -> Optional[str]:
        fs = session.fs
        if fs is None:
            return None
        path = os.path.join(self._temp_dir, "compare-" + uuid.uuid4().hex[:8] + "-" + entry.name)
        progress = QProgressDialog(tr("fb.compare.loading", name=entry.name), tr("dialog.cancel"),
                                   0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)
        cancelled = threading.Event()
        done_state: dict = {}
        loop = QEventLoop()
        progress.canceled.connect(cancelled.set)
        total = max(1, entry.size)
        received = [0]

        def on_data(n: int) -> None:
            if cancelled.is_set():
                from src.filebrowser.fs import TransferAborted
                raise TransferAborted("cancel")
            received[0] += n

        def finish(ok: bool, error=None):
            done_state["ok"] = ok
            done_state["error"] = error
            loop.quit()

        tick = QTimer(self)
        tick.timeout.connect(lambda: progress.setValue(int(received[0] * 100 / total)))
        tick.start(150)

        def run():
            try:
                fs.download(entry.path, path, 0, on_data)
                self._invoker.call(lambda: finish(True))
            except BaseException as e:
                self._invoker.call(lambda: finish(False, e))
        threading.Thread(target=run, daemon=True).start()
        loop.exec()
        tick.stop()
        progress.close()
        if not done_state.get("ok"):
            if not cancelled.is_set() and done_state.get("error"):
                self.show_error(tr("fb.error.transfer_title"), str(done_state["error"]))
            return None
        return path

    # ── context menu ─────────────────────────────────────────────────────────

    def build_context_menu(self, pane: FilePane, entries: list[FileEntry]) -> QMenu:
        c = self.palette.icon
        menu = QMenu(self)

        def act(icon: str, text: str, fn, shortcut: str = "", enabled: bool = True):
            a = menu.addAction(svg_icon(icon, c, 14), text + (f"\t{shortcut}" if shortcut else ""), fn)
            a.setEnabled(enabled)
            return a

        def history_actions():
            act("undo", self.undo_label(), self.undo, "Ctrl+Z", enabled=self.can_undo())
            act("redo", self.redo_label(), self.redo, "Ctrl+Y", enabled=self.can_redo())

        files = [e for e in entries if not e.is_dir]
        single = entries[0] if len(entries) == 1 else None
        other = self._other_pane(pane)
        session = pane.session
        exec_ok = bool(session and getattr(session.fs, "can_exec", False))

        if entries:
            if single and single.is_dir:
                act("folder-open", tr("fb.menu.open"), lambda: pane.navigate(single.path), "Enter")
            elif files:
                act("eye", tr("fb.menu.open"), lambda: self.open_entries(pane, files), "Enter")
                if single:
                    act("edit", tr("fb.menu.open_with"), lambda: self.open_with(pane, single), "Ctrl+O")
            menu.addSeparator()
            if pane.local:
                if other is not None:
                    act("upload", tr("fb.menu.upload_to_server"),
                        lambda: self.transfer_to_other(pane, entries), "F6")
                act("folder", tr("fb.menu.show_in_explorer"), lambda: self.show_in_explorer(entries))
            else:
                act("download", tr("fb.menu.download"), lambda: self.download_entries(pane, entries),
                    "Ctrl+Shift+D")
                if other is not None:
                    act("arrow-left", tr("fb.menu.download_to_local"),
                        lambda: self.transfer_to_other(pane, entries), "F6")
                if exec_ok:
                    act("archive", tr("fb.menu.download_archive"),
                        lambda: self.download_as_archive(pane, entries))
            menu.addSeparator()
            act("edit", tr("fb.menu.rename"), lambda: self.rename_entry(pane, single), "F2",
                enabled=single is not None)
            if not pane.local and exec_ok and single:
                act("copy", tr("fb.menu.duplicate"), lambda: self.duplicate(pane, single))
            act("trash", tr("fb.menu.delete"), lambda: self.delete_entries(pane, entries), "Del")
            menu.addSeparator()
            history_actions()
            if not pane.local and exec_ok:
                menu.addSeparator()
                act("archive", tr("fb.menu.pack"), lambda: self.pack(pane, entries))
                if single and not single.is_dir and commands.archive_kind(single.name):
                    act("archive", tr("fb.menu.extract"), lambda: self.extract(pane, single))
            menu.addSeparator()
            act("clipboard", tr("fb.menu.copy_path"), lambda: self.copy_paths(pane, entries),
                "Ctrl+Shift+C")
            if single and not single.is_dir:
                act("shield-check", tr("fb.menu.checksum"), lambda: self.properties(pane, [single]))
            act("info", tr("fb.menu.properties"), lambda: self.properties(pane, entries), "Alt+Enter")
        else:
            act("refresh", tr("fb.nav.refresh"), pane.refresh, "F5")
            history_actions()
            menu.addSeparator()
            act("folder-plus", tr("fb.tb.new_folder"), lambda: self.new_folder(pane), "F7")
            act("file-plus", tr("fb.tb.new_file"), lambda: self.new_file(pane), "Shift+F4")
            if not pane.local:
                menu.addSeparator()
                act("upload", tr("fb.tb.upload_files"), self.upload_files, "Ctrl+U")
                act("upload", tr("fb.tb.upload_folder"), self.upload_folder, "Ctrl+Shift+U")
                act("link", tr("fb.tb.upload_url"), self.upload_url, "Ctrl+Shift+L")
                if exec_ok:
                    act("terminal", tr("fb.tb.terminal"), lambda: self.terminal_here(pane),
                        "Ctrl+Shift+T", enabled=self._terminal_opener is not None)
                act("star", tr("fb.bookmarks.toggle"), pane.toggle_bookmark, "Ctrl+D")
            menu.addSeparator()
            act("clipboard", tr("fb.menu.copy_path"), lambda: self.copy_paths(pane, []), "Ctrl+Shift+C")
            act("info", tr("fb.menu.properties"), lambda: self.properties(pane, []), "Alt+Enter")
        return menu

    # ── state & shutdown ─────────────────────────────────────────────────────

    def _save_state(self) -> None:
        state = self.manager.settings.window
        state.pop("geometry", None)          # left over from the separate window
        state["panel"] = self._vsplit.sizes()
        ws = self.workspace()
        if ws is not None:
            state["split"] = ws.split
        self.manager.save(notify=False)

    def has_active_transfers(self) -> bool:
        return self.active_transfer_count() > 0

    def shutdown(self) -> None:
        """Disconnect every host and clean up (the application quits).

        Does not ask: the main window asks about running transfers first.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._save_state()
        except Exception as e:
            logger.debug("filebrowser: could not save state: %s", e)
        self.manager.remove_listener(self._on_settings_changed)
        self._speed_timer.stop()
        for session in list(self.sessions):
            self._close_session(session)
        self._invoker.close()
        self._tasks.shutdown()
        for timer in self._edit_timers.values():
            timer.stop()
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        if not self._edits:                 # keep files that may still be open in an editor
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        # Let Qt delete the widget tree from the event loop, as closing the
        # old window did; leaving it to Python's garbage collection deletes
        # it at an arbitrary moment and can crash.
        self.deleteLater()

    @property
    def closed(self) -> bool:
        return self._closed
