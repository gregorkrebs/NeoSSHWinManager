"""
session.py – One server connection inside the file browser.

The browser is not tied to a host: it holds any number of sessions,
every tab belongs to one of them, and tabs of the same host share it – one
SSH/FTP login, one transfer queue, one undo history. A session connects in
the background and reports its state through `state_changed`.
"""

from __future__ import annotations

import threading
import uuid
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from src.filebrowser.fs import FsError, FtpFS, SftpFS
from src.filebrowser.history import UndoHistory
from src.filebrowser.threads import TaskRunner
from src.filebrowser.transfers import TransferQueue
from src.i18n import tr
from src.remote_path import normalize_remote_input

CONNECTING = "connecting"
CONNECTED = "ok"
RECONNECTING = "reconnecting"
FAILED = "error"


class HostSession(QObject):
    state_changed = pyqtSignal(object)          # self
    _link = pyqtSignal(bool)                    # from transfer threads: link up / down

    def __init__(self, conn, manager, tofu: Optional[Callable[[str, int, str], bool]] = None,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.manager = manager
        self._tofu = tofu
        self.id = uuid.uuid4().hex              # drag origin: server paths mean something only here
        self.fs = None
        self.queue: Optional[TransferQueue] = None
        self.history = UndoHistory()
        self.history_busy = False
        self.home_root = "/"
        self.start_path = "/"
        self.state = CONNECTING
        self.error: Optional[BaseException] = None
        self.closed = False
        self._tasks = TaskRunner(self)
        self._link.connect(self._on_link)

    # ── identity ─────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self.conn.name or self.conn.host

    @property
    def connected(self) -> bool:
        return self.fs is not None and self.state in (CONNECTED, RECONNECTING)

    def tree_root(self) -> str:
        return "/" if self.manager.settings.tree_from_root else self.home_root

    # ── connecting ───────────────────────────────────────────────────────────

    def open_fs(self):
        """Log in and return the file system (runs in a worker thread)."""
        conn = self.conn
        settings = self.manager.settings
        if conn.is_ftp:
            from src.ftp_client import FtpClient

            def factory():
                c = FtpClient()
                c.connect(conn)
                return c
            return FtpFS(factory(), factory,
                         max_sessions=min(4, max(settings.max_downloads, settings.max_uploads)))
        from src.sftp_client import SftpClient
        client = SftpClient()
        client.connect(conn, tofu_callback=self._tofu)

        def reconnect():
            c = SftpClient()
            c.connect(conn)
            return c
        return SftpFS(client, reconnect=reconnect)

    def connect(self) -> None:
        if self.closed or self.fs is not None:
            return
        self._set_state(CONNECTING)
        self.error = None

        def work():
            fs = self.open_fs()
            return fs, self.start_path_for(fs), self.tree_home(fs)

        self._tasks.run(work, self._on_connected, self._on_failed)

    def _on_connected(self, result) -> None:
        fs, self.start_path, self.home_root = result
        if self.closed:
            threading.Thread(target=fs.close, daemon=True, name="fb-close").start()
            return
        self.fs = fs
        fs.on_reconnect = self._link.emit        # called from transfer threads
        self._set_state(CONNECTED)

    def _on_failed(self, error: BaseException) -> None:
        self.error = error
        self._set_state(FAILED)

    def _on_link(self, ok: bool) -> None:
        if self.fs is not None and not self.closed:
            self._set_state(CONNECTED if ok else RECONNECTING)

    def _set_state(self, state: str) -> None:
        self.state = state
        self.state_changed.emit(self)

    def error_text(self) -> str:
        from src.sftp_client import (AuthenticationFailed, HostKeyChanged, HostKeyRejected,
                                     NoCredentials, SftpUnavailable)
        error = self.error
        if isinstance(error, HostKeyChanged):
            return tr("fb.hostkey.changed", host=error.host, fingerprint=error.fingerprint,
                      path=error.known_hosts)
        if isinstance(error, HostKeyRejected):
            return tr("fb.hostkey.rejected", host=error.host, fingerprint=error.fingerprint)
        if isinstance(error, SftpUnavailable):
            return error.user_text()
        if isinstance(error, AuthenticationFailed):
            return tr("sftp.error.auth_failed")
        if isinstance(error, NoCredentials):
            return tr("sftp.error.no_credentials")
        return str(error) if error else ""

    # ── where to start ───────────────────────────────────────────────────────

    def start_path_for(self, fs) -> str:
        """Last visited folder, else the configured path, else the home folder."""
        windows = bool(getattr(fs, "is_windows", False))
        configured = (self.conn.remote_path or "").strip()
        candidates = [self.manager.settings.last_remote.get(self.conn.id)]
        if configured and configured != "/":
            candidates.append(normalize_remote_input(configured, windows))
        candidates.append(fs.home if windows or configured in ("", "/") else "/")
        candidates.append("/")
        for path in candidates:
            if not path:
                continue
            try:
                entry = fs.stat(path)
            except FsError:
                entry = None
            if path == "/" or (entry is not None and entry.is_dir):
                return path
        return "/"

    def tree_home(self, fs) -> str:
        """
        Top folder of the server tree: the connection's path, else the login
        folder. Many accounts may not list "/" or "/home", so a tree starting
        at "/" could never be opened down to their own folder.
        """
        windows = bool(getattr(fs, "is_windows", False))
        configured = (self.conn.remote_path or "").strip()
        if configured and configured != "/":
            path = normalize_remote_input(configured, windows).rstrip("/") or "/"
            try:
                entry = fs.stat(path)
            except FsError:
                entry = None
            if entry is not None and entry.is_dir:
                return path
        return getattr(fs, "home", "/") or "/"

    # ── transfers & shutdown ─────────────────────────────────────────────────

    def active_transfers(self) -> int:
        return self.queue.active_count() if self.queue else 0

    def close(self) -> None:
        """Stop transfers and log out (in the background)."""
        self.closed = True
        if self.queue is not None:
            self.queue.shutdown()
        self._tasks.shutdown()
        fs, self.fs = self.fs, None
        if fs is not None:
            threading.Thread(target=fs.close, daemon=True, name="fb-close").start()
