"""
sftp_browser.py – Native SFTP file browser window for NEO SSH-Win Manager.

Opens as a non-modal FramelessDialog when the user clicks the folder button on a
mounted connection. Provides directory navigation, file download/upload, rename,
delete, and new-folder operations — all without blocking the Qt UI thread.
"""

from __future__ import annotations

import os
import tempfile
import threading
from datetime import datetime
from typing import Any

from PyQt6.QtCore import (
    QAbstractTableModel, QFileSystemWatcher, QModelIndex, QSize,
    QSortFilterProxyModel, Qt, QTimer, pyqtSignal,
)
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu, QProgressDialog,
    QPushButton, QSizePolicy, QTreeView, QVBoxLayout, QWidget,
)

from src.app_logger import logger
from src.config import Connection
from src.i18n import tr
from src.sftp_client import SftpClient, SftpEntry
from src.ui.dialogs.styled_message_box import StyledMessageBox
from src.ui.frameless_dialog import FramelessDialog
from src.ui.icons import icon as svg_icon, pixmap as svg_pixmap
from src.ui.sftp_worker import (
    SftpConnectWorker,
    SftpDeleteWorker,
    SftpDownloadWorker,
    SftpListWorker,
    SftpMkdirWorker,
    SftpRenameWorker,
    SftpUploadWorker,
)


# ── Table model ──────────────────────────────────────────────────────────────

_COL_NAME  = 0
_COL_SIZE  = 1
_COL_MTIME = 2
_COL_PERMS = 3
_COL_TYPE  = 4

_ENTRY_ROLE = Qt.ItemDataRole.UserRole


class SftpFileModel(QAbstractTableModel):
    """Table model backing the QTreeView in SftpBrowserWindow."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[SftpEntry] = []

    def set_entries(self, entries: list[SftpEntry]) -> None:
        self.beginResetModel()
        self._entries = entries
        self.endResetModel()

    def entry_at(self, row: int) -> SftpEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 5

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == _COL_NAME:
                return entry.name
            if col == _COL_SIZE:
                return "—" if entry.is_dir else _fmt_size(entry.size)
            if col == _COL_MTIME:
                try:
                    return datetime.fromtimestamp(entry.modified).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    return ""
            if col == _COL_PERMS:
                return entry.permissions
            if col == _COL_TYPE:
                return tr("sftp.type.dir") if entry.is_dir else tr("sftp.type.file")

        if role == Qt.ItemDataRole.TextAlignmentRole and col == _COL_SIZE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == _ENTRY_ROLE:
            return entry

        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return [
                tr("sftp.col.name"),
                tr("sftp.col.size"),
                tr("sftp.col.modified"),
                tr("sftp.col.permissions"),
                tr("sftp.col.type"),
            ][section]
        return None


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


# ── Browser window ───────────────────────────────────────────────────────────

class SftpBrowserWindow(FramelessDialog):
    """
    Non-modal SFTP file browser window.

    Created by MainWindow._on_open_mounted_path() and shown with show().
    One instance per connection; reopening an already-open browser raises
    the existing window instead.
    """

    def __init__(
        self,
        conn: Connection,
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, show_maximize=True)
        self._conn = conn
        self._theme = theme
        self._client = SftpClient()
        self._current_path: str = (conn.remote_path or "/").rstrip("/") or "/"
        self._history: list[str] = []
        self._forward_stack: list[str] = []
        self._active_list_worker: SftpListWorker | None = None
        self._workers: list = []   # keep references so Qt doesn't GC running workers
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_watched_file_changed)
        # local_path → remote_path for files currently open for editing
        self._edit_map: dict[str, str] = {}
        # Debounce: local_path → QTimer to avoid double-upload on save
        self._edit_timers: dict[str, QTimer] = {}

        self.setWindowTitle(tr("sftp.title", name=conn.name))
        self.resize(960, 620)

        self._build_ui()
        self.set_dialog_theme(theme)
        self._apply_theme_stylesheet()

        # Defer connection so the window appears first
        QTimer.singleShot(0, self._connect_and_load)

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self._fdlg_content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar.setObjectName("sftpToolbar")
        toolbar.setFixedHeight(44)
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 6, 8, 6)
        tb_layout.setSpacing(4)

        icon_color = "#aab4c4" if self._theme == "dark" else "#4a5a6a"

        self._btn_back = QPushButton("←")
        self._btn_back.setObjectName("sftpNavBtn")
        self._btn_back.setFixedSize(QSize(32, 30))
        self._btn_back.setToolTip(tr("sftp.toolbar.back"))
        self._btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_back.clicked.connect(self._on_back)
        tb_layout.addWidget(self._btn_back)

        self._btn_forward = QPushButton("→")
        self._btn_forward.setObjectName("sftpNavBtn")
        self._btn_forward.setFixedSize(QSize(32, 30))
        self._btn_forward.setToolTip(tr("sftp.toolbar.forward"))
        self._btn_forward.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_forward.clicked.connect(self._on_forward)
        tb_layout.addWidget(self._btn_forward)

        self._btn_up = QPushButton("↑")
        self._btn_up.setObjectName("sftpNavBtn")
        self._btn_up.setFixedSize(QSize(32, 30))
        self._btn_up.setToolTip(tr("sftp.toolbar.up"))
        self._btn_up.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_up.clicked.connect(self._on_up)
        tb_layout.addWidget(self._btn_up)

        self._btn_refresh = QPushButton()
        self._btn_refresh.setObjectName("sftpNavBtn")
        self._btn_refresh.setFixedSize(QSize(32, 30))
        self._btn_refresh.setIcon(svg_icon("refresh", icon_color, 15))
        self._btn_refresh.setIconSize(QSize(15, 15))
        self._btn_refresh.setToolTip(tr("sftp.toolbar.refresh"))
        self._btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_refresh.clicked.connect(self._on_refresh)
        tb_layout.addWidget(self._btn_refresh)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setFixedWidth(1)
        sep1.setObjectName("sftpSep")
        tb_layout.addWidget(sep1)
        tb_layout.addSpacing(4)

        self._path_edit = QLineEdit(self._current_path)
        self._path_edit.setObjectName("sftpPathEdit")
        self._path_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._path_edit.returnPressed.connect(self._on_path_entered)
        tb_layout.addWidget(self._path_edit)

        tb_layout.addSpacing(4)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setFixedWidth(1)
        sep2.setObjectName("sftpSep")
        tb_layout.addWidget(sep2)
        tb_layout.addSpacing(4)

        self._btn_upload = QPushButton()
        self._btn_upload.setObjectName("sftpActionBtn")
        self._btn_upload.setFixedSize(QSize(32, 30))
        self._btn_upload.setIcon(svg_icon("plus", icon_color, 15))
        self._btn_upload.setIconSize(QSize(15, 15))
        self._btn_upload.setToolTip(tr("sftp.toolbar.upload"))
        self._btn_upload.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_upload.clicked.connect(self._on_upload)
        tb_layout.addWidget(self._btn_upload)

        self._btn_mkdir = QPushButton()
        self._btn_mkdir.setObjectName("sftpActionBtn")
        self._btn_mkdir.setFixedSize(QSize(32, 30))
        self._btn_mkdir.setIcon(svg_icon("folder", icon_color, 15))
        self._btn_mkdir.setIconSize(QSize(15, 15))
        self._btn_mkdir.setToolTip(tr("sftp.toolbar.mkdir"))
        self._btn_mkdir.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_mkdir.clicked.connect(self._on_mkdir)
        tb_layout.addWidget(self._btn_mkdir)

        root.addWidget(toolbar)

        # Tree view
        self._model = SftpFileModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self._tree = QTreeView()
        self._tree.setObjectName("sftpTree")
        self._tree.setModel(self._proxy)
        self._tree.setSortingEnabled(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.setUniformRowHeights(True)
        self._tree.doubleClicked.connect(self._on_double_click)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

        header = self._tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(_COL_SIZE,  90)
        header.resizeSection(_COL_MTIME, 140)
        header.resizeSection(_COL_PERMS, 110)
        header.resizeSection(_COL_TYPE,  75)
        header.setSortIndicator(_COL_NAME, Qt.SortOrder.AscendingOrder)

        root.addWidget(self._tree, stretch=1)

        # Status bar
        self._status_lbl = QLabel(tr("sftp.status.connecting"))
        self._status_lbl.setObjectName("sftpStatusLbl")
        self._status_lbl.setContentsMargins(8, 3, 8, 3)
        root.addWidget(self._status_lbl)

        self._update_nav_buttons()

    # ── Theme ────────────────────────────────────────────────────────────────

    def _apply_theme_stylesheet(self) -> None:
        if self._theme == "dark":
            bg       = "#0d0d12"
            surface  = "#0D1117"
            text     = "#c8d6e5"
            accent   = "#00b4d8"
            border   = "#1a2535"
            alt_row  = "#090910"
            sep_col  = "#1e2a3a"
        else:
            bg       = "#f0f2f5"
            surface  = "#ffffff"
            text     = "#1a2332"
            accent   = "#0077b6"
            border   = "#dde2e8"
            alt_row  = "#f8fafc"
            sep_col  = "#dde2e8"

        self._fdlg_content.setStyleSheet(f"""
            QWidget#sftpToolbar {{
                background-color: {bg};
                border-bottom: 1px solid {border};
            }}
            QFrame#sftpSep {{
                background-color: {sep_col};
                border: none;
            }}
            QLineEdit#sftpPathEdit {{
                background-color: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 12px;
            }}
            QLineEdit#sftpPathEdit:focus {{
                border-color: {accent};
            }}
            QPushButton#sftpNavBtn, QPushButton#sftpActionBtn {{
                background-color: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
                font-size: 13px;
            }}
            QPushButton#sftpNavBtn:hover, QPushButton#sftpActionBtn:hover {{
                border-color: {accent};
            }}
            QPushButton#sftpNavBtn:disabled {{
                color: {"#3a4a5a" if self._theme == "dark" else "#b0bbc8"};
                border-color: {"#1a2535" if self._theme == "dark" else "#dde2e8"};
            }}
            QTreeView#sftpTree {{
                background-color: {surface};
                alternate-background-color: {alt_row};
                color: {text};
                border: none;
                gridline-color: {border};
                font-size: 12px;
            }}
            QTreeView#sftpTree::item:selected {{
                background-color: {accent};
                color: #ffffff;
            }}
            QTreeView#sftpTree::item:hover {{
                background-color: {"rgba(0,180,216,0.10)" if self._theme == "dark" else "rgba(0,119,182,0.08)"};
            }}
            QHeaderView::section {{
                background-color: {bg};
                color: {text};
                border: none;
                border-bottom: 1px solid {border};
                border-right: 1px solid {border};
                padding: 4px 6px;
                font-size: 11px;
                font-weight: 600;
            }}
            QLabel#sftpStatusLbl {{
                background-color: {bg};
                color: {"#6a7a8a" if self._theme == "dark" else "#7a8a9a"};
                font-size: 11px;
                border-top: 1px solid {border};
            }}
        """)

    # ── Connection ───────────────────────────────────────────────────────────

    def _connect_and_load(self) -> None:
        self._set_status(tr("sftp.status.connecting"))
        worker = SftpConnectWorker(self._client, self._conn, self._tofu_callback)
        worker.connected.connect(self._on_connected)
        worker.error.connect(self._on_connect_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _on_connected(self) -> None:
        self._navigate_to(self._current_path, push_history=False)

    def _on_connect_error(self, msg: str) -> None:
        self._set_status(tr("sftp.status.connect_failed"))
        StyledMessageBox.critical(self, tr("sftp.error.connect_title"), msg)

    def _tofu_callback(self, host: str, port: int, fingerprint: str) -> bool:
        """Called from worker thread — dispatches dialog to the main thread and waits."""
        result_holder: list[bool] = [False]
        event = threading.Event()

        def _ask() -> None:
            result_holder[0] = StyledMessageBox.question(
                self,
                tr("sftp.tofu.title"),
                tr("sftp.tofu.body", host=host, fingerprint=fingerprint),
                yes_text=tr("dialog.yes"),
                no_text=tr("dialog.no"),
            )
            event.set()

        QTimer.singleShot(0, _ask)
        event.wait(timeout=60)
        return result_holder[0]

    # ── Navigation ───────────────────────────────────────────────────────────

    def _navigate_to(self, path: str, *, push_history: bool = True) -> None:
        if push_history and self._current_path and self._current_path != path:
            self._history.append(self._current_path)
            self._forward_stack.clear()
        self._current_path = path
        self._path_edit.setText(path)
        self._load_directory(path)
        self._update_nav_buttons()

    def _on_back(self) -> None:
        if not self._history:
            return
        self._forward_stack.append(self._current_path)
        prev = self._history.pop()
        self._navigate_to(prev, push_history=False)

    def _on_forward(self) -> None:
        if not self._forward_stack:
            return
        self._history.append(self._current_path)
        nxt = self._forward_stack.pop()
        self._navigate_to(nxt, push_history=False)

    def _on_up(self) -> None:
        parent = self._current_path.rstrip("/").rsplit("/", 1)[0] or "/"
        if parent != self._current_path:
            self._navigate_to(parent)

    def _on_refresh(self) -> None:
        self._load_directory(self._current_path)

    def _on_path_entered(self) -> None:
        path = self._path_edit.text().strip() or "/"
        self._navigate_to(path)

    def _update_nav_buttons(self) -> None:
        self._btn_back.setEnabled(bool(self._history))
        self._btn_forward.setEnabled(bool(self._forward_stack))
        self._btn_up.setEnabled(self._current_path not in ("/", ""))

    # ── Directory loading ────────────────────────────────────────────────────

    def _load_directory(self, path: str) -> None:
        if self._active_list_worker and self._active_list_worker.isRunning():
            try:
                self._active_list_worker.finished.disconnect()
                self._active_list_worker.error.disconnect()
            except Exception:
                pass
            self._active_list_worker = None

        self._set_status(tr("sftp.status.loading"))
        worker = SftpListWorker(self._client, path)
        worker.finished.connect(self._on_list_finished)
        worker.error.connect(self._on_list_error)
        self._active_list_worker = worker
        self._workers.append(worker)
        worker.finished.connect(lambda *_: self._workers.remove(worker) if worker in self._workers else None)
        worker.error.connect(lambda *_: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _on_list_finished(self, path: str, entries: list) -> None:
        self._active_list_worker = None
        self._model.set_entries(entries)
        count = len(entries)
        self._set_status(tr("sftp.status.items", count=count))

    def _on_list_error(self, path: str, msg: str) -> None:
        self._active_list_worker = None
        self._set_status(tr("sftp.status.error", msg=msg))
        StyledMessageBox.critical(self, tr("sftp.error.title"), msg)

    # ── Double click ─────────────────────────────────────────────────────────

    def _on_double_click(self, proxy_index: QModelIndex) -> None:
        src_index = self._proxy.mapToSource(proxy_index)
        entry = self._model.entry_at(src_index.row())
        if entry is None:
            return
        if entry.is_dir:
            self._navigate_to(entry.path)
        else:
            self._download_and_open(entry)

    # ── Download ─────────────────────────────────────────────────────────────

    def _download_and_open(self, entry: SftpEntry) -> None:
        tmp_dir = tempfile.mkdtemp(prefix="neossh_sftp_")
        local_path = os.path.join(tmp_dir, entry.name)
        remote_path = entry.path

        worker = SftpDownloadWorker(self._client, remote_path, local_path)
        self._workers.append(worker)

        fname = entry.name
        prog = QProgressDialog(
            tr("sftp.progress.downloading", name=fname),
            tr("dialog.cancel"), 0, 100, self,
        )
        prog.setWindowTitle(tr("sftp.error.download_title"))
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)

        def _on_progress(done: int, total: int) -> None:
            if total > 0:
                prog.setValue(int(done * 100 / total))

        def _on_finished(lp: str) -> None:
            prog.close()
            if worker in self._workers:
                self._workers.remove(worker)
            # Register for edit-watch before opening so we catch the first save
            self._edit_map[lp] = remote_path
            self._watcher.addPath(lp)
            try:
                os.startfile(lp)
            except Exception as e:
                StyledMessageBox.critical(self, tr("sftp.error.title"), str(e))

        def _on_error(msg: str) -> None:
            prog.close()
            if worker in self._workers:
                self._workers.remove(worker)
            StyledMessageBox.critical(self, tr("sftp.error.download_title"), msg)

        worker.progress.connect(_on_progress)
        worker.finished.connect(_on_finished)
        worker.error.connect(_on_error)
        worker.start()

    def _on_watched_file_changed(self, local_path: str) -> None:
        """Called by QFileSystemWatcher when a watched temp file is modified."""
        remote_path = self._edit_map.get(local_path)
        if not remote_path:
            return
        # Some editors delete-and-recreate on save; re-add the path if it dropped out.
        if local_path not in self._watcher.files():
            QTimer.singleShot(200, lambda: self._watcher.addPath(local_path))

        # Debounce: wait 500 ms after the last change event before uploading,
        # because editors often write in multiple bursts.
        if local_path in self._edit_timers:
            self._edit_timers[local_path].stop()

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._upload_edited_file(local_path, remote_path))
        self._edit_timers[local_path] = timer
        timer.start(500)

    def _upload_edited_file(self, local_path: str, remote_path: str) -> None:
        """Silently upload a temp file back to the server after the user saved it."""
        self._edit_timers.pop(local_path, None)
        if not os.path.exists(local_path):
            return
        fname = os.path.basename(local_path)
        worker = SftpUploadWorker(self._client, local_path, remote_path)
        self._workers.append(worker)

        def _on_finished(_remote: str) -> None:
            if worker in self._workers:
                self._workers.remove(worker)
            self._set_status(tr("sftp.status.saved", name=fname))
            self._on_refresh()

        def _on_error(msg: str) -> None:
            if worker in self._workers:
                self._workers.remove(worker)
            StyledMessageBox.critical(
                self, tr("sftp.error.upload_title"),
                tr("sftp.error.edit_upload_failed", name=fname, msg=msg),
            )

        worker.finished.connect(_on_finished)
        worker.error.connect(_on_error)
        worker.start()

    def _start_download(
        self, remote_path: str, local_path: str, open_after: bool = False
    ) -> None:
        fname = os.path.basename(remote_path)
        prog = QProgressDialog(
            tr("sftp.progress.downloading", name=fname),
            tr("dialog.cancel"),
            0, 100, self,
        )
        prog.setWindowTitle(tr("sftp.error.download_title"))
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)

        worker = SftpDownloadWorker(self._client, remote_path, local_path)
        self._workers.append(worker)

        def _on_progress(done: int, total: int) -> None:
            if total > 0:
                prog.setValue(int(done * 100 / total))

        def _on_finished(lp: str) -> None:
            prog.close()
            if worker in self._workers:
                self._workers.remove(worker)
            if open_after:
                try:
                    os.startfile(lp)
                except Exception as e:
                    StyledMessageBox.critical(self, tr("sftp.error.title"), str(e))

        def _on_error(msg: str) -> None:
            prog.close()
            if worker in self._workers:
                self._workers.remove(worker)
            StyledMessageBox.critical(self, tr("sftp.error.download_title"), msg)

        worker.progress.connect(_on_progress)
        worker.finished.connect(_on_finished)
        worker.error.connect(_on_error)
        worker.start()

    # ── Upload ───────────────────────────────────────────────────────────────

    def _on_upload(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("sftp.upload.select"),
            "",
            tr("sftp.upload.filter"),
        )
        for local_path in paths:
            fname = os.path.basename(local_path)
            remote_path = self._current_path.rstrip("/") + "/" + fname
            self._start_upload(local_path, remote_path)

    def _start_upload(self, local_path: str, remote_path: str) -> None:
        fname = os.path.basename(local_path)
        prog = QProgressDialog(
            tr("sftp.progress.uploading", name=fname),
            tr("dialog.cancel"),
            0, 100, self,
        )
        prog.setWindowTitle(tr("sftp.error.upload_title"))
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)

        worker = SftpUploadWorker(self._client, local_path, remote_path)
        self._workers.append(worker)

        def _on_progress(done: int, total: int) -> None:
            if total > 0:
                prog.setValue(int(done * 100 / total))

        def _on_finished(_remote: str) -> None:
            prog.close()
            if worker in self._workers:
                self._workers.remove(worker)
            self._on_refresh()

        def _on_error(msg: str) -> None:
            prog.close()
            if worker in self._workers:
                self._workers.remove(worker)
            StyledMessageBox.critical(self, tr("sftp.error.upload_title"), msg)

        worker.progress.connect(_on_progress)
        worker.finished.connect(_on_finished)
        worker.error.connect(_on_error)
        worker.start()

    # ── Context menu ─────────────────────────────────────────────────────────

    def _on_context_menu(self, pos) -> None:
        proxy_index = self._tree.indexAt(pos)
        if not proxy_index.isValid():
            return
        src_index = self._proxy.mapToSource(proxy_index)
        entry = self._model.entry_at(src_index.row())
        if entry is None:
            return

        icon_color = "#aab4c4" if self._theme == "dark" else "#4a5a6a"
        menu = QMenu(self)

        act_dl = None
        if not entry.is_dir:
            act_dl = menu.addAction(
                svg_icon("arrow-right", icon_color, 15),
                tr("sftp.menu.download"),
            )
        act_rename = menu.addAction(svg_icon("edit",  icon_color, 15), tr("sftp.menu.rename"))
        act_delete = menu.addAction(svg_icon("trash", "#ef4444",   15), tr("sftp.menu.delete"))
        menu.addSeparator()
        act_mkdir  = menu.addAction(svg_icon("folder", icon_color, 15), tr("sftp.menu.new_folder"))
        act_upload = menu.addAction(svg_icon("plus",   icon_color, 15), tr("sftp.menu.upload"))

        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))

        if act_dl and chosen == act_dl:
            save_path, _ = QFileDialog.getSaveFileName(
                self, tr("sftp.upload.select"), entry.name
            )
            if save_path:
                self._start_download(entry.path, save_path, open_after=False)
        elif chosen == act_rename:
            self._on_rename(entry)
        elif chosen == act_delete:
            self._on_delete(entry)
        elif chosen == act_mkdir:
            self._on_mkdir()
        elif chosen == act_upload:
            self._on_upload()

    # ── CRUD operations ──────────────────────────────────────────────────────

    def _on_delete(self, entry: SftpEntry) -> None:
        confirmed = StyledMessageBox.question(
            self,
            tr("sftp.delete.title"),
            tr("sftp.delete.confirm", name=entry.name),
            yes_text=tr("dialog.yes"),
            no_text=tr("dialog.no"),
        )
        if not confirmed:
            return
        worker = SftpDeleteWorker(self._client, entry.path, entry.is_dir)
        self._workers.append(worker)
        worker.finished.connect(lambda _: (
            self._workers.remove(worker) if worker in self._workers else None,
            self._on_refresh(),
        ))
        worker.error.connect(lambda msg: (
            self._workers.remove(worker) if worker in self._workers else None,
            StyledMessageBox.critical(self, tr("sftp.error.delete_title"), msg),
        ))
        worker.start()

    def _on_rename(self, entry: SftpEntry) -> None:
        new_name, ok = QInputDialog.getText(
            self, tr("sftp.rename.title"), tr("sftp.rename.prompt"), text=entry.name
        )
        if not ok or not new_name.strip() or new_name.strip() == entry.name:
            return
        parent = entry.path.rsplit("/", 1)[0] or "/"
        new_path = parent.rstrip("/") + "/" + new_name.strip()
        worker = SftpRenameWorker(self._client, entry.path, new_path)
        self._workers.append(worker)
        worker.finished.connect(lambda *_: (
            self._workers.remove(worker) if worker in self._workers else None,
            self._on_refresh(),
        ))
        worker.error.connect(lambda msg: (
            self._workers.remove(worker) if worker in self._workers else None,
            StyledMessageBox.critical(self, tr("sftp.error.rename_title"), msg),
        ))
        worker.start()

    def _on_mkdir(self) -> None:
        name, ok = QInputDialog.getText(
            self, tr("sftp.mkdir.title"), tr("sftp.mkdir.prompt")
        )
        if not ok or not name.strip():
            return
        new_path = self._current_path.rstrip("/") + "/" + name.strip()
        worker = SftpMkdirWorker(self._client, new_path)
        self._workers.append(worker)
        worker.finished.connect(lambda _: (
            self._workers.remove(worker) if worker in self._workers else None,
            self._on_refresh(),
        ))
        worker.error.connect(lambda msg: (
            self._workers.remove(worker) if worker in self._workers else None,
            StyledMessageBox.critical(self, tr("sftp.error.mkdir_title"), msg),
        ))
        worker.start()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self._status_lbl.setText(msg)

    def keyPressEvent(self, event) -> None:
        # QDialog would close/accept on Enter and Escape — suppress both so the
        # path bar's returnPressed and the tree's keyboard navigation work normally.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            event.ignore()
            return
        super().keyPressEvent(event)

    # ── Close ────────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        for t in self._edit_timers.values():
            t.stop()
        self._edit_timers.clear()
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        self._edit_map.clear()
        client = self._client
        threading.Thread(target=client.disconnect, daemon=True, name="SftpDisconnect").start()
        super().closeEvent(event)
