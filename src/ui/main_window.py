"""
main_window.py – The primary application window for NEO SSH-Win Manager.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QScrollArea,
    QApplication, QSystemTrayIcon, QDialog,
    QLineEdit, QSpinBox, QComboBox, QCheckBox, QFrame,
    QFileDialog, QRadioButton, QDialogButtonBox, QMenu,
    QInputDialog, QSplitter, QSplitterHandle, QSizePolicy, QStackedWidget, QGridLayout
)
from PyQt6.QtGui import QFont, QIcon, QPainter, QPixmap, QColor, QPen, QBrush, QShortcut, QKeySequence
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QSize, pyqtSignal
import os
import sys
from PyQt6 import sip
import ctypes
import ctypes.wintypes
import json
import subprocess
from urllib.parse import quote

# SECURITY FIX (FINDING-01): imports for named-pipe DACL and IPC rate limiting
import win32security
import win32api
import win32con
import ntsecuritycon

from src.auth_manager import Session, UserConnectionManager
from src.sshfs_controller import SSHFSController, _is_safe_label
from src.config import (
    Connection, AppSettings, PROTOCOL_FTP, PROTOCOL_FTPS, PROTOCOL_SFTP,
    default_port,
)
from src.ui.connection_card import ConnectionCard
from src.ui.system_tray import SystemTray
from src.ui.debug_window import DebugWindow
from src.app_logger import logger
from src.ui.worker import MountWorker, UnmountWorker, TerminalConnectWorker
from src.ui.dialogs.styled_message_box import StyledMessageBox
from src.ui.frameless_dialog import FramelessDialog
from src.ui.frameless_window import FramelessMainWindow
from src.ui.icons import icon as svg_icon, pixmap as svg_pixmap, pixmap_with_text as svg_pixmap_text
from src.ui.theme import (
    DEFAULT_ACCENT, accent_text_color, accent_tone, current_accent, dark_tone, is_light,
    normalize_hex,
)
from src.ui.widgets.no_wheel import NoWheelComboBox, NoWheelSpinBox
from src.i18n import tr, current_language, available_languages, set_language, is_rtl
from src.channel import display_name
from PyQt6.QtCore import QThread


_LANG_LABELS = {
    "en": "English",
    "de": "Deutsch",
    "es": "Español",
    "ru": "Русский",
    "nl": "Nederlands",
    "ar": "العربية",
}


def _apply_layout_direction() -> None:
    """Mirror the UI for right-to-left languages (Arabic)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight
        )

# Right-panel mode constants
_PANEL_NONE     = "none"
_PANEL_INFO     = "info"
_PANEL_SYSINFO  = "sysinfo"
_PANEL_EDIT     = "edit"
_PANEL_SETTINGS = "settings"
_PANEL_ADD      = "add"
_PANEL_USERS    = "users"
_PANEL_PROFILE  = "profile"
_PANEL_TERMINAL = "terminal"
_PANEL_CLI_HISTORY = "cli_history"
_PANEL_FILES    = "files"         # the file browser page

# Sidebar icon of the file browser: the host panel's folder with "FTP" in it.
_SB_FILES_ICON = "folder-ftp"
_SB_FILES_ICON_SIZE = 22

try:
    with open(os.path.join(os.path.dirname(__file__), "..", "version.txt"), "r", encoding="utf-8") as f:
        APP_VERSION = f.read().strip()
except Exception:
    APP_VERSION = "?"

class _PillHandle(QSplitterHandle):
    """Splitter handle that paints a centred pill indicator."""
    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pill_w, pill_h = 4, 36
        x = (w - pill_w) // 2
        y = (h - pill_h) // 2
        painter.setPen(QPen(QColor(0, 0, 0, 0)))
        painter.setBrush(QBrush(QColor(0, 180, 216, 55)))
        painter.drawRoundedRect(x, y, pill_w, pill_h, pill_w, pill_w)
        painter.end()


class _PillSplitter(QSplitter):
    """QSplitter that uses _PillHandle for its divider."""
    def createHandle(self) -> QSplitterHandle:  # noqa: N802
        return _PillHandle(self.orientation(), self)


class _TemplateDropdown(QFrame):
    """
    Popup panel listing available templates.
    Each row shows the template host/name plus a trash button to delete it.
    Emits template_selected(Connection) or template_deleted(str conn_id).
    """
    template_selected = pyqtSignal(object)  # Connection
    template_deleted  = pyqtSignal(str)     # conn_id

    def __init__(self, templates: list, theme: str, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("templateDropdownFrame")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build(templates, theme)

    def _build(self, templates: list, theme: str):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)
        for conn in templates:
            label_text = conn.name or conn.host
            row_w = QWidget()
            row_w.setObjectName("templateDropdownRow")
            row_w.setCursor(Qt.CursorShape.PointingHandCursor)
            hl = QHBoxLayout(row_w)
            hl.setContentsMargins(8, 6, 6, 6)
            hl.setSpacing(6)

            lbl = QLabel(label_text)
            lbl.setObjectName("templateDropdownLabel")
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            hl.addWidget(lbl, stretch=1)

            trash_btn = QPushButton()
            trash_btn.setObjectName("rpHeaderBtn")
            trash_btn.setFixedSize(QSize(28, 28))
            trash_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            trash_btn.setToolTip(tr("addedit.template.delete.title"))
            from src.ui.icons import icon as svg_icon
            trash_btn.setIcon(svg_icon("trash", "#ef4444", 13))
            trash_btn.setIconSize(QSize(13, 13))

            _conn = conn  # capture for closure
            trash_btn.clicked.connect(lambda _checked, c=_conn: self._on_delete(c))
            lbl.mousePressEvent = lambda ev, c=_conn: self._on_select(c)

            hl.addWidget(trash_btn)
            outer.addWidget(row_w)

    def _on_select(self, conn):
        self.hide()
        self.template_selected.emit(conn)

    def _on_delete(self, conn):
        self.hide()
        self.template_deleted.emit(conn.id)

    def showEvent(self, event):
        super().showEvent(event)
        if self.parent():
            parent = self.parent()
            self.setFixedWidth(max(parent.width(), 200))


class _AuthMethodDialog(FramelessDialog):
    """Frameless auth chooser for password vs. key login."""

    def __init__(self, parent, conn_name: str, *, has_key: bool, prefer_key: bool):
        super().__init__(parent)
        self.setModal(True)
        self.setObjectName("dialogSurface")
        self.setWindowTitle(tr("addedit.auth.ask.title"))
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self._fdlg_content)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        prompt = QLabel(tr("addedit.auth.ask.prompt", name=conn_name))
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        self._rb_pw = QRadioButton(tr("addedit.auth.password"))
        self._rb_key = QRadioButton(tr("addedit.auth.key"))
        self._rb_key.setEnabled(has_key)

        if has_key and prefer_key:
            self._rb_key.setChecked(True)
        else:
            self._rb_pw.setChecked(True)

        layout.addWidget(self._rb_pw)
        layout.addWidget(self._rb_key)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setObjectName("primaryBtn")
        cancel_btn = btns.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setObjectName("secondaryBtn")

        layout.addWidget(btns)

    def selected_auth_method(self) -> str:
        return "password" if self._rb_pw.isChecked() else "key"


class _BrowserHosts:
    """The file browser's view of the saved connections ("Connect" menu)."""

    def __init__(self, window: "MainWindow") -> None:
        self._window = window

    def connections(self) -> list:
        return self._window._mgr.get_connections()        # no templates, list order

    def prepare(self, conn_id: str):
        """The connection with credentials (may ask for a password), or None."""
        window = self._window
        conn = window._mgr.get_by_id(conn_id)
        if conn is None:
            return None
        return window._prepare_auth(conn, parent=window)


class MainWindow(FramelessMainWindow):

    def __init__(self):
        super().__init__()
        self._user = Session.current()
        self._mgr = UserConnectionManager(self._user)
        # Ensure UI language is always initialized from persisted user settings,
        # even when MainWindow is launched outside the main.py startup path.
        try:
            set_language(self._mgr.get_settings().language)
            _apply_layout_direction()
        except Exception:
            pass
        from src.ui.theme import set_current_accent
        _s = self._mgr.get_settings()
        set_current_accent(getattr(_s, "accent_color", ""))
        # (theme, accent) the widgets were last painted in, see _apply_settings_object()
        self._applied_look = (_s.theme or "dark", current_accent(),
                              bool(getattr(_s, "allow_shared_drive_letters", False)))
        self._controller = SSHFSController()
        self._cards: dict[str, ConnectionCard] = {}
        self._selected_id: str | None = None
        self._workers: dict[str, QThread] = {}
        self._terminal_connect_workers: dict[str, TerminalConnectWorker] = {}
        self._terminal_pending_conn: dict[str, object] = {}
        self._terminal_connecting: set[str] = set()  # conn_ids with a connect in flight
        self._file_browser = None               # the file browser page (all hosts), built on first use
        self._fb_settings = None                # its settings (see _file_browser_settings())
        self._panel_mode: str = _PANEL_NONE
        self._panel_conn_id: str | None = None   # which connection the panel belongs to
        self._ef_initial_snapshot: dict | None = None
        self._settings_initial_snapshot: dict | None = None
        self._leave_guard_active = False
        self._saving_in_progress = False
        self._shortcuts: list[QShortcut] = []
        self._explicit_quit = False
        
        # Debug mode settings
        self._debug_mode = False  # Can be toggled via F2

        # Integrated terminal (xterm.js)
        self._bridge_server = None
        self._terminal_panels: dict[str, object] = {}       # session_key → TerminalPanel
        self._terminal_conn_tabs: dict[str, list] = {}       # conn_id → [session_key, ...]
        self._terminal_active_tab: dict[str, str] = {}       # conn_id → active session_key
        self._terminal_session_counter: dict[str, int] = {}  # conn_id → next session index

        self.setObjectName("MainWindow")
        self.setWindowTitle(display_name() + " v" + APP_VERSION)
        self.setMinimumSize(820, 520)
        self.resize(1100, 640)

        def get_resource_path(relative_path):
            import sys
            if hasattr(sys, '_MEIPASS'):
                return os.path.join(sys._MEIPASS, relative_path)
            return os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                relative_path
            )

        for icon_file in ("app_icon.ico", "app_icon.png"):
            icon_path = get_resource_path(os.path.join("assets", icon_file))
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                break

        self._build_ui()
        self._setup_tray()
        self._refresh_list()
        self._apply_debug_mode()
        self._setup_ipc()
        QTimer.singleShot(0, self._start_terminal_bridge)

        # Setup keyboard shortcut for debug mode toggle (F2)
        debug_shortcut = QShortcut(QKeySequence("F2"), self)
        debug_shortcut.activated.connect(self._debug_widget_under_mouse)
        self._shortcuts.append(debug_shortcut)
        self._install_shortcuts()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_mount_states)
        self._poll_timer.start(self._mgr.get_settings().check_interval_seconds * 1000)

        self._check_prerequisites()
        QTimer.singleShot(2000, self._auto_reconnect_mounts)
        QTimer.singleShot(0, lambda: self._apply_titlebar_color(self._mgr.get_settings().theme or "dark"))
        QTimer.singleShot(0, lambda: self._update_header_btn_icons(self._mgr.get_settings().theme or "dark"))

        import src.app_logger as _log_mod
        _em = _log_mod.log_emitter
        if _em is not None:
            _em.new_record.connect(self._on_log_record_for_status)

        logger.info("NEO SSH-Win Manager gestartet.")

    # ------------------------------------------------------------------
    # CLI Access / IPC
    # ------------------------------------------------------------------

    def _setup_ipc(self):
        import threading
        self._ipc_pipe_name = r"\\.\pipe\SSHWinManager_IPC_v1"
        self._ipc_running = True
        self._ipc_thread = threading.Thread(target=self._ipc_listener, daemon=True)
        self._ipc_thread.start()

    def _ipc_listener(self):
        import time

        # SECURITY FIX (FINDING-01): Rate limiting state — tracked per connecting PID.
        # Max 10 failed/invalid requests per PID per 60-second window.
        _ipc_rate: dict = {}   # pid → {"count": int, "window_start": float}
        _IPC_MAX_FAILS = 10
        _IPC_WINDOW_SEC = 60.0

        def _check_rate(pid: int) -> bool:
            """Return True if this PID is within the allowed request rate."""
            now = time.monotonic()
            entry = _ipc_rate.get(pid, {"count": 0, "window_start": now})
            if now - entry["window_start"] > _IPC_WINDOW_SEC:
                entry = {"count": 0, "window_start": now}
            entry["count"] += 1
            _ipc_rate[pid] = entry
            return entry["count"] <= _IPC_MAX_FAILS

        # SECURITY FIX (FINDING-01): Build a SECURITY_ATTRIBUTES struct that
        # restricts pipe access to the current user only (replaces bare None).
        def _make_pipe_security_attributes():
            """Return a SECURITY_ATTRIBUTES ctypes struct granting access only to
            the current user, or None on failure (falls back to default)."""
            try:
                # Get current user SID
                username = win32api.GetUserNameEx(win32con.NameSamCompatible)
                sid, _, _ = win32security.LookupAccountName(None, username)

                # Build a DACL with a single ACE: GENERIC_READ | GENERIC_WRITE for current user
                dacl = win32security.ACL()
                dacl.AddAccessAllowedAce(
                    win32security.ACL_REVISION,
                    ntsecuritycon.GENERIC_READ | ntsecuritycon.GENERIC_WRITE,
                    sid
                )

                # Attach the DACL to a new Security Descriptor
                sd = win32security.SECURITY_DESCRIPTOR()
                sd.SetSecurityDescriptorDacl(True, dacl, False)

                # Convert SD to a self-relative binary blob and store it so it
                # stays alive for the lifetime of the pipe handle.
                sd_bytes = sd.GetSecurityDescriptorDacl()   # keep reference

                # Build a SECURITY_ATTRIBUTES struct pointing to the SD
                class SECURITY_ATTRIBUTES(ctypes.Structure):
                    _fields_ = [
                        ("nLength",              ctypes.c_ulong),
                        ("lpSecurityDescriptor", ctypes.c_void_p),
                        ("bInheritHandle",       ctypes.c_bool),
                    ]

                sa = SECURITY_ATTRIBUTES()
                sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
                # Keep the SD object alive inside sa so GC doesn't collect it
                sa._sd_obj = sd
                # Obtain a raw pointer to the SD via win32security
                raw_sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                    sd.GetSecurityDescriptorSddl(win32security.DACL_SECURITY_INFORMATION),
                    win32security.SDDL_REVISION_1,
                )
                sa._sd_raw = raw_sd
                # Use the PyHANDLE buffer address as lpSecurityDescriptor
                import ctypes
                sa.lpSecurityDescriptor = ctypes.cast(
                    ctypes.c_char_p(bytes(raw_sd)), ctypes.c_void_p
                )
                sa.bInheritHandle = False
                return sa
            except Exception as e:
                logger.warning(f"IPC: SECURITY_ATTRIBUTES konnte nicht erstellt werden: {e} — "
                               "Pipe wird mit Standard-ACL erstellt (FINDING-01 nicht vollständig gemindert).")
                return None

        PIPE_ACCESS_DUPLEX    = 0x00000003
        PIPE_TYPE_MESSAGE     = 0x00000004
        PIPE_READMODE_MESSAGE = 0x00000002
        PIPE_WAIT             = 0x00000000

        def _read_full_message(pipe_handle):
            """Reads one complete message from a message-mode pipe.

            A single ReadFile call with a fixed buffer silently mangles any
            message larger than that buffer (Win32 message-mode pipes signal
            this via ReadFile returning False with ERROR_MORE_DATA, not via
            an error the JSON parser would explain) — the caller would just
            see a truncated payload fail to parse, with no request ever
            handled. cli_log entries carry command output and can exceed the
            old fixed 64KB assumption, so this loops until the message is
            fully drained. Returns None on a genuine read failure.
            """
            ERROR_MORE_DATA = 234
            MAX_MESSAGE_BYTES = 2 * 1024 * 1024  # Sicherheitsnetz gegen Endlos-Clients
            chunk = ctypes.create_string_buffer(65536)
            read = ctypes.wintypes.DWORD()
            data = bytearray()
            while True:
                ok = ctypes.windll.kernel32.ReadFile(pipe_handle, chunk, 65536, ctypes.byref(read), None)
                data.extend(chunk.raw[:read.value])
                if ok:
                    return bytes(data)
                if ctypes.windll.kernel32.GetLastError() != ERROR_MORE_DATA:
                    return None
                if len(data) > MAX_MESSAGE_BYTES:
                    return None

        while self._ipc_running:
            try:
                sa = _make_pipe_security_attributes()
                sa_ptr = ctypes.byref(sa) if sa is not None else None
                pipe = ctypes.windll.kernel32.CreateNamedPipeW(
                    self._ipc_pipe_name, PIPE_ACCESS_DUPLEX,
                    PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
                    5, 1048576, 1048576, 5000,
                    sa_ptr  # SECURITY FIX (FINDING-01): proper DACL instead of None
                )
                if pipe == -1:
                    time.sleep(1)
                    continue
                ctypes.windll.kernel32.ConnectNamedPipe(pipe, None)
                if not self._ipc_running:
                    ctypes.windll.kernel32.CloseHandle(pipe)
                    break

                # Determine connecting PID for rate limiting
                connecting_pid = 0
                try:
                    pid_val = ctypes.wintypes.ULONG()
                    ctypes.windll.kernel32.GetNamedPipeClientProcessId(
                        pipe, ctypes.byref(pid_val)
                    )
                    connecting_pid = pid_val.value
                except Exception:
                    pass

                raw = _read_full_message(pipe)
                if raw is not None:
                    try:
                        request = json.loads(raw.decode('utf-8'))
                        if request.get("action") == "cli_connect":
                            # SECURITY FIX (FINDING-01): Rate limit by PID
                            if not _check_rate(connecting_pid):
                                logger.warning(
                                    f"IPC: Rate-Limit erreicht für PID {connecting_pid} — "
                                    "Anfrage abgelehnt."
                                )
                                response = {
                                    "success": False,
                                    "error": "Rate-Limit erreicht. Bitte warten."
                                }
                            else:
                                conn = self._mgr.get_by_cli_key(request.get("key", ""))
                                if conn:
                                    # Password auth must work over --connect-cli too — that's
                                    # the whole point of the feature (explicit product decision,
                                    # revisiting FINDING-01's original blanket omission). Sending
                                    # it over this pipe is safe in the same way the key_path was
                                    # already considered safe: CreateNamedPipeW above uses
                                    # _make_pipe_security_attributes(), which restricts the pipe
                                    # to the current user's SID only, so only this same account's
                                    # own processes can ever connect; the 64-byte cli_access_key
                                    # is itself a strong bearer secret gating this response; and
                                    # _check_rate() above throttles repeated attempts per PID.
                                    response = {"success": True, "connection": {
                                        "id": conn.id, "name": conn.name,
                                        "host": conn.host, "user": conn.user,
                                        "port": conn.port, "remote_path": conn.remote_path,
                                        "auth_method": conn.auth_method,
                                        "key_path": conn.key_path,
                                        "password": conn.password,
                                    }}
                                else:
                                    response = {"success": False, "error": "Ungültiger Access Key."}
                        elif request.get("action") == "get_askpass":
                            # Hardened SSH_ASKPASS: Exchange token for password
                            from src.askpass_manager import consume_token
                            token = request.get("token", "")
                            password = consume_token(token)
                            if password is not None:
                                response = {"success": True, "password": password}
                            else:
                                response = {"success": False, "error": "Invalid or expired token."}
                        elif request.get("action") == "cli_log":
                            # CLI-Verlauf: gleiche Key-Prüfung und Rate-Limit wie
                            # cli_connect. Verschlüsselung passiert bewusst hier
                            # (GUI-Prozess) — der CLI-Prozess besitzt den enc_key
                            # nie, das Passwort läuft über denselben, DACL-
                            # beschränkten Pipe-Kanal schon heute im Klartext.
                            if not _check_rate(connecting_pid):
                                logger.warning(
                                    f"IPC: Rate-Limit erreicht für PID {connecting_pid} — "
                                    "cli_log abgelehnt."
                                )
                                response = {"success": False, "error": "Rate-Limit erreicht. Bitte warten."}
                            else:
                                conn = self._mgr.get_by_cli_key(request.get("key", ""))
                                if conn:
                                    entry = request.get("entry") or {}
                                    self._mgr.add_cli_history(
                                        conn.id,
                                        kind=entry.get("kind", "exec"),
                                        command=entry.get("command"),
                                        output=entry.get("output", ""),
                                        exit_code=entry.get("exit_code"),
                                        started_at=entry.get("started_at", ""),
                                        ended_at=entry.get("ended_at"),
                                        truncated=bool(entry.get("truncated", False)),
                                    )
                                    response = {"success": True}
                                else:
                                    response = {"success": False, "error": "Ungültiger Access Key."}
                        else:
                            response = {"success": False, "error": "Unbekannte Aktion."}
                        res = json.dumps(response).encode('utf-8')
                        written = ctypes.wintypes.DWORD()
                        ctypes.windll.kernel32.WriteFile(pipe, res, len(res), ctypes.byref(written), None)
                        ctypes.windll.kernel32.FlushFileBuffers(pipe)
                    except Exception as e:
                        logger.error(f"IPC Request Fehler: {e}")
                ctypes.windll.kernel32.DisconnectNamedPipe(pipe)
                ctypes.windll.kernel32.CloseHandle(pipe)
            except Exception as e:
                logger.error(f"IPC Listener Fehler: {e}")
                time.sleep(1)

    def _stop_ipc(self):
        self._ipc_running = False

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Hosts the app mounted: {conn_id: letter actually used} (persisted for
        # auto-reconnect; '' for records from older versions).
        self._active_mounts: dict[str, str] = {}
        # Last resolved mount state: {conn_id: letter} (see _compute_mounted).
        self._mounted_letters: dict[str, str] = {}
        # Letter a running mount worker mounts on, per conn_id.
        self._mount_targets: dict[str, str] = {}
        self._letter_retry: set[str] = set()   # one automatic retry per mount
        self._load_active_mounts()
        self._containers: dict[str, object] = {}

        # Outer body: sidebar (always visible) + main content stack
        body = QWidget()
        body_h = QHBoxLayout(body)
        body_h.setContentsMargins(0, 0, 0, 0)
        body_h.setSpacing(0)
        body_h.addWidget(self._build_sidebar())

        # Stack page 0: connections list + resizable right panel
        self._right_panel_widget = self._build_right_panel()
        self._body_splitter = _PillSplitter(Qt.Orientation.Horizontal)
        self._body_splitter.setObjectName("bodySplitter")
        self._body_splitter.setHandleWidth(14)
        self._body_splitter.setOpaqueResize(False)
        self._body_splitter.addWidget(self._build_connections_panel())
        self._body_splitter.addWidget(self._right_panel_widget)
        self._body_splitter.setCollapsible(0, False)
        self._body_splitter.setCollapsible(1, False)
        self._body_splitter.setSizes([420, 620])
        self._body_splitter.splitterMoved.connect(self._clamp_splitter_40)

        # Stack page 1: full-screen panel (settings, users)
        self._fullscreen_widget = self._build_fullscreen_panel()

        # Stack page 2: the file browser (created on first use, then kept so
        # connections and transfers survive switching pages)
        self._files_page = QWidget()
        files_l = QVBoxLayout(self._files_page)
        files_l.setContentsMargins(0, 0, 0, 0)
        files_l.setSpacing(0)

        self._main_stack = QStackedWidget()
        self._main_stack.addWidget(self._body_splitter)   # index 0
        self._main_stack.addWidget(self._fullscreen_widget)  # index 1
        self._main_stack.addWidget(self._files_page)      # index 2
        self._main_stack.currentChanged.connect(self._on_main_page_changed)

        body_h.addWidget(self._main_stack, stretch=1)

        root.addWidget(body, stretch=1)
        root.addWidget(self._build_status_bar())
        self._show_right_panel_placeholder()

    def _sidebar_btn(self, icon_name: str, slot=None, *, active: bool = False, btn_type: str = "") -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("sidebarBtn")
        btn.setFixedSize(QSize(42, 42))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if active:
            btn.setProperty("active", "true")
        if btn_type:
            btn.setProperty("btn_type", btn_type)
        theme = (self._mgr.get_settings().theme or "dark")
        if btn_type == "danger":
            color = "#ef4444" if not is_light(theme) else "#b91c1c"
        elif btn_type == "warning":
            color = "#f59e0b"
        elif active:
            # Bright accent shade for active navigation icons in every theme.
            color = accent_tone("#00b4d8")
        else:
            color = "#aab4c4" if not is_light(theme) else "#2f4051"
        self._set_sidebar_icon(btn, icon_name, color)
        if slot:
            btn.clicked.connect(slot)
        return btn

    @staticmethod
    def _set_sidebar_icon(btn: QPushButton, icon_name: str, color: str) -> None:
        if icon_name == _SB_FILES_ICON:
            # Drawn a bit larger than the others so the "FTP" stays legible.
            size = _SB_FILES_ICON_SIZE
            btn.setIcon(QIcon(svg_pixmap_text("folder", color, size, "FTP")))
        else:
            size = 18
            btn.setIcon(svg_icon(icon_name, color, size))
        btn.setIconSize(QSize(size, size))

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(60)
        v = QVBoxLayout(sidebar)
        v.setContentsMargins(8, 10, 8, 10)
        v.setSpacing(8)
        v.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._sb_home_btn = self._sidebar_btn("cloud", active=True)
        self._sb_home_btn.clicked.connect(self._nav_home)
        v.addWidget(self._sb_home_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self._sb_users_btn = None
        if Session.is_admin():
            self._sb_users_btn = self._sidebar_btn("users", self._on_user_management)
            v.addWidget(self._sb_users_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        # Profile button for all users (password change, etc.)
        self._sb_profile_btn = self._sidebar_btn("key", self._on_profile)
        v.addWidget(self._sb_profile_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        # File browser (SFTP/FTP) for all hosts
        self._sb_files_btn = self._sidebar_btn(_SB_FILES_ICON, self._on_file_browser)
        self._sb_files_btn.setToolTip(tr("sidebar.file_browser"))
        v.addWidget(self._sb_files_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        v.addStretch()

        self._debug_btn = self._sidebar_btn("bug", self._on_debug, btn_type="warning")
        self._debug_btn.setVisible(False)
        v.addWidget(self._debug_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self._about_btn = self._sidebar_btn("info", self._on_about)
        v.addWidget(self._about_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self._sb_settings_btn = self._sidebar_btn("settings", self._on_settings)
        v.addWidget(self._sb_settings_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        logout_btn = self._sidebar_btn("logout", self._on_logout, btn_type="danger")
        v.addWidget(logout_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        return sidebar

    def _set_sidebar_active(self, name: str):
        """Set active state on tracked sidebar buttons. name: 'home'|'settings'|'users'|'profile'|'files'"""
        candidates = [
            ("home",     "cloud",        self._sb_home_btn),
            ("settings", "settings",     self._sb_settings_btn),
            ("users",    "users",        self._sb_users_btn),
            ("profile",  "key",          self._sb_profile_btn),
            ("files",    _SB_FILES_ICON, self._sb_files_btn),
            ("about",    "info",         self._about_btn),
        ]
        for key, icon_name, btn in candidates:
            if btn is None:
                continue
            is_active = key == name
            btn.setProperty("active", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            theme = (self._mgr.get_settings().theme or "dark")
            icon_color = accent_tone("#00b4d8") if is_active else ("#aab4c4" if not is_light(theme) else "#2f4051")
            self._set_sidebar_icon(btn, icon_name, icon_color)

    def _build_connections_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("connectionsPanel")
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        header = QWidget()
        header.setObjectName("connectionsHeader")
        header_h = QHBoxLayout(header)
        header_h.setContentsMargins(18, 12, 18, 12)
        header_h.setSpacing(8)

        title_wrap = QWidget()
        title_wrap.setObjectName("connectionsTitleWrap")
        title_layout = QVBoxLayout(title_wrap)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        title_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title_lbl = QLabel(tr("header.connections"))
        title_lbl.setObjectName("connectionsTitle")
        title_layout.addWidget(title_lbl)

        header_h.addWidget(title_wrap)
        header_h.addStretch()

        self._add_btn = QPushButton()
        self._add_btn.setObjectName("headerAddBtn")
        self._add_btn.setFixedSize(QSize(32, 32))
        self._add_btn.setIcon(svg_icon("plus", "#aab4c4", 16))
        self._add_btn.setIconSize(QSize(16, 16))
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setToolTip(tr("main.add_connection"))
        self._add_btn.clicked.connect(self._on_add)
        header_h.addWidget(self._add_btn)

        # Mount/Dismount All Buttons
        self._mount_all_btn = QPushButton()
        self._mount_all_btn.setObjectName("headerActionBtn")
        self._mount_all_btn.setFixedSize(QSize(30, 30))
        self._mount_all_btn.setIcon(svg_icon("cloud", current_accent(), 16))
        self._mount_all_btn.setIconSize(QSize(16, 16))
        self._mount_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mount_all_btn.setToolTip(tr("main.mount_all"))
        self._mount_all_btn.clicked.connect(self._on_mount_all)
        header_h.addWidget(self._mount_all_btn)

        self._dismount_all_btn = QPushButton()
        self._dismount_all_btn.setObjectName("headerActionBtn")
        self._dismount_all_btn.setFixedSize(QSize(30, 30))
        self._dismount_all_btn.setIcon(svg_icon("x", "#ef4444", 16))
        self._dismount_all_btn.setIconSize(QSize(16, 16))
        self._dismount_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dismount_all_btn.setToolTip(tr("main.dismount_all"))
        self._dismount_all_btn.clicked.connect(self._on_dismount_all)
        header_h.addWidget(self._dismount_all_btn)

        # Groups Filter Combo - centered with same height as badge
        self._groups_combo = NoWheelComboBox()
        self._groups_combo.setObjectName("headerGroupsCombo")
        self._groups_combo.setFixedSize(QSize(120, 30))
        self._groups_combo.setToolTip(tr("main.groups_filter"))
        self._groups_combo.currentIndexChanged.connect(self._on_group_filter_changed)
        header_h.addWidget(self._groups_combo, 0, Qt.AlignmentFlag.AlignVCenter)

        self._badge_lbl = QLabel("")
        self._badge_lbl.setObjectName("connectionsBadge")
        self._badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge_lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        header_h.addWidget(self._badge_lbl)

        v.addWidget(header)

        scroll = QScrollArea()
        scroll.setObjectName("connectionScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._list_container = QWidget()
        self._list_container.setObjectName("connectionList")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(12, 12, 12, 12)
        self._list_layout.setSpacing(10)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_container)
        v.addWidget(scroll)
        return panel

    def _build_right_panel(self) -> QWidget:
        """Container for the right panel — content is swapped dynamically."""
        panel = QWidget()
        panel.setObjectName("rightPanel")
        panel.setMinimumWidth(10)
        panel.setMaximumWidth(16777215)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header row (title + action buttons)
        header = QWidget()
        header.setObjectName("rightPanelHeader")
        hh = QHBoxLayout(header)
        hh.setContentsMargins(18, 12, 18, 12)
        hh.setSpacing(8)

        title_wrap = QWidget()
        title_wrap.setObjectName("rightPanelTitleWrap")
        title_layout = QVBoxLayout(title_wrap)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        title_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._right_panel_title = QLabel("")
        self._right_panel_title.setObjectName("rightPanelTitle")
        title_layout.addWidget(self._right_panel_title)

        hh.addWidget(title_wrap)
        hh.addStretch()

        # Info button (shown in info mode - opens system info panel)
        self._rp_info_btn = QPushButton("i")
        self._rp_info_btn.setObjectName("cardInfoBtn")
        self._rp_info_btn.setFixedSize(QSize(32, 32))
        self._rp_info_btn.setIconSize(QSize(14, 14))
        self._rp_info_btn.setToolTip(tr("card.tooltip.info"))
        self._rp_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_info_btn.clicked.connect(self._on_rp_info_clicked)
        self._rp_info_btn.setVisible(False)
        self._rp_info_btn.setAccessibleName(tr("card.tooltip.info"))
        hh.addWidget(self._rp_info_btn)

        # Edit button (shown in info mode)
        self._rp_edit_btn = QPushButton()
        self._rp_edit_btn.setObjectName("rpHeaderBtn")
        self._rp_edit_btn.setFixedSize(QSize(32, 32))
        self._rp_edit_btn.setIcon(svg_icon("edit", "#aab4c4", 15))
        self._rp_edit_btn.setIconSize(QSize(15, 15))
        self._rp_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_edit_btn.setToolTip(tr("card.tooltip.edit"))
        self._rp_edit_btn.clicked.connect(self._on_rp_edit_clicked)
        self._rp_edit_btn.setVisible(False)
        self._rp_edit_btn.setAccessibleName(tr("card.tooltip.edit"))
        hh.addWidget(self._rp_edit_btn)

        # Terminal button (shown in info/sysinfo mode)
        self._rp_terminal_btn = QPushButton()
        self._rp_terminal_btn.setObjectName("rpHeaderBtn")
        self._rp_terminal_btn.setFixedSize(QSize(32, 32))
        self._rp_terminal_btn.setIcon(svg_icon("terminal", "#aab4c4", 15))
        self._rp_terminal_btn.setIconSize(QSize(15, 15))
        self._rp_terminal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_terminal_btn.setToolTip(tr("card.tooltip.ssh"))
        self._rp_terminal_btn.clicked.connect(self._on_rp_terminal_clicked)
        self._rp_terminal_btn.setVisible(False)
        self._rp_terminal_btn.setAccessibleName(tr("card.tooltip.ssh"))
        hh.addWidget(self._rp_terminal_btn)

        # Mount/Unmount button (shown in info/sysinfo mode)
        self._rp_mount_btn = QPushButton()
        self._rp_mount_btn.setObjectName("rpHeaderBtn")
        self._rp_mount_btn.setFixedSize(QSize(32, 32))
        self._rp_mount_btn.setIconSize(QSize(15, 15))
        self._rp_mount_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_mount_btn.clicked.connect(self._on_rp_mount_clicked)
        self._rp_mount_btn.setVisible(False)
        hh.addWidget(self._rp_mount_btn)

        # Delete button (shown in info/edit mode)
        self._rp_del_btn = QPushButton()
        self._rp_del_btn.setObjectName("rpHeaderBtn")
        self._rp_del_btn.setProperty("btn_type", "danger")
        self._rp_del_btn.setFixedSize(QSize(32, 32))
        # Icon is white on danger background
        self._rp_del_btn.setIcon(svg_icon("trash", "#ffffff", 15))
        self._rp_del_btn.setIconSize(QSize(15, 15))
        self._rp_del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_del_btn.setToolTip(tr("main.delete"))
        self._rp_del_btn.clicked.connect(self._on_delete)
        self._rp_del_btn.setVisible(False)
        self._rp_del_btn.setAccessibleName(tr("main.delete"))
        hh.addWidget(self._rp_del_btn)

        self._rp_save_top_btn = QPushButton()
        self._rp_save_top_btn.setObjectName("rpHeaderSaveBtn")
        self._rp_save_top_btn.setFixedSize(QSize(32, 32))
        self._rp_save_top_btn.setIcon(svg_icon("floppy", "#ffffff", 15))
        self._rp_save_top_btn.setIconSize(QSize(15, 15))
        self._rp_save_top_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_save_top_btn.setToolTip(tr("card.tooltip.save_top"))
        self._rp_save_top_btn.clicked.connect(self._on_rp_save)
        self._rp_save_top_btn.setVisible(False)
        self._rp_save_top_btn.setAccessibleName(tr("card.tooltip.save_top"))
        hh.addWidget(self._rp_save_top_btn)

        self._rp_cancel_top_btn = QPushButton()
        self._rp_cancel_top_btn.setObjectName("rpHeaderBtn")
        self._rp_cancel_top_btn.setFixedSize(QSize(32, 32))
        self._rp_cancel_top_btn.setIcon(svg_icon("x", "#aab4c4", 15))
        self._rp_cancel_top_btn.setIconSize(QSize(15, 15))
        self._rp_cancel_top_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_cancel_top_btn.setToolTip(tr("card.tooltip.cancel_top"))
        self._rp_cancel_top_btn.clicked.connect(self._on_rp_cancel)
        self._rp_cancel_top_btn.setVisible(False)
        self._rp_cancel_top_btn.setAccessibleName(tr("card.tooltip.cancel_top"))
        hh.addWidget(self._rp_cancel_top_btn)

        # "Open another session" button (only visible in xterm terminal mode)
        self._rp_new_session_btn = QPushButton()
        self._rp_new_session_btn.setObjectName("rpHeaderBtn")
        self._rp_new_session_btn.setFixedSize(QSize(32, 32))
        self._rp_new_session_btn.setIcon(svg_icon("plus", "#aab4c4", 15))
        self._rp_new_session_btn.setIconSize(QSize(15, 15))
        self._rp_new_session_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_new_session_btn.setToolTip(tr("terminal.new_session"))
        self._rp_new_session_btn.clicked.connect(self._on_new_terminal_session)
        self._rp_new_session_btn.setVisible(False)
        hh.addWidget(self._rp_new_session_btn)

        # Close button
        self._rp_close_btn = QPushButton()
        self._rp_close_btn.setObjectName("rpHeaderBtn")
        self._rp_close_btn.setFixedSize(QSize(32, 32))
        self._rp_close_btn.setIcon(svg_icon("x", "#6a7a8a", 15))
        self._rp_close_btn.setIconSize(QSize(15, 15))
        self._rp_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_close_btn.setToolTip(tr("dialog.close"))
        self._rp_close_btn.clicked.connect(self._close_right_panel)
        self._rp_close_btn.setAccessibleName(tr("dialog.close"))
        hh.addWidget(self._rp_close_btn)

        v.addWidget(header)

        # Scrollable content area
        self._rp_scroll = QScrollArea()
        self._rp_scroll.setObjectName("rightPanelScroll")
        self._rp_scroll.setWidgetResizable(True)
        self._rp_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._rp_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._rp_content = QWidget()
        self._rp_content.setObjectName("rightPanelContent")
        self._rp_layout = QVBoxLayout(self._rp_content)
        self._rp_layout.setContentsMargins(0, 0, 0, 0)
        self._rp_layout.setSpacing(0)
        self._rp_scroll.setWidget(self._rp_content)
        v.addWidget(self._rp_scroll, stretch=1)

        # Terminal area (tab bar + stacked panels + end-session bar)
        # Hidden by default; shown only in _PANEL_TERMINAL mode.
        self._terminal_area = QWidget()
        self._terminal_area.setObjectName("terminalArea")
        ta_layout = QVBoxLayout(self._terminal_area)
        ta_layout.setContentsMargins(0, 0, 0, 0)
        ta_layout.setSpacing(0)

        # Tab bar
        self._terminal_tab_bar = QWidget()
        self._terminal_tab_bar.setObjectName("terminalTabBar")
        self._terminal_tab_bar_layout = QHBoxLayout(self._terminal_tab_bar)
        self._terminal_tab_bar_layout.setContentsMargins(4, 4, 4, 0)
        self._terminal_tab_bar_layout.setSpacing(2)
        self._terminal_tab_bar_layout.addStretch()
        ta_layout.addWidget(self._terminal_tab_bar)

        # Stacked widget for terminal panels
        self._terminal_stack = QStackedWidget()
        self._terminal_stack.setObjectName("terminalStack")
        ta_layout.addWidget(self._terminal_stack, stretch=1)

        # "End session" bottom bar
        self._terminal_end_bar = QWidget()
        self._terminal_end_bar.setObjectName("terminalEndBar")
        eb = QHBoxLayout(self._terminal_end_bar)
        eb.setContentsMargins(12, 6, 12, 6)
        eb.setSpacing(8)
        eb.addStretch()
        self._terminal_end_btn = QPushButton(tr("terminal.end_session"))
        self._terminal_end_btn.setObjectName("dangerBtn")
        self._terminal_end_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._terminal_end_btn.clicked.connect(self._on_end_terminal_session)
        eb.addWidget(self._terminal_end_btn)
        ta_layout.addWidget(self._terminal_end_bar)

        self._terminal_area.setVisible(False)
        v.addWidget(self._terminal_area, stretch=1)

        # Save/Cancel button bar (only visible in edit/add mode)
        self._rp_btn_bar = QWidget()
        self._rp_btn_bar.setObjectName("rpBtnBar")
        bb = QHBoxLayout(self._rp_btn_bar)
        bb.setContentsMargins(12, 8, 12, 12)
        bb.setSpacing(8)
        bb.addStretch()
        self._rp_cancel_btn = QPushButton(tr("dialog.cancel"))
        self._rp_cancel_btn.setObjectName("secondaryBtn")
        self._rp_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_cancel_btn.setToolTip(tr("card.tooltip.cancel_top"))
        self._rp_cancel_btn.clicked.connect(self._on_rp_cancel)
        bb.addWidget(self._rp_cancel_btn)
        self._rp_save_btn = QPushButton(tr("dialog.save"))
        self._rp_save_btn.setObjectName("primaryBtn")
        self._rp_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_save_btn.setToolTip(tr("card.tooltip.save_top"))
        self._rp_save_btn.clicked.connect(self._on_rp_save)
        bb.addWidget(self._rp_save_btn)
        self._rp_btn_bar.setVisible(False)
        v.addWidget(self._rp_btn_bar)

        # Extra action bar for edit mode (in addition to header actions).
        self._rp_edit_btn_bar = QWidget()
        self._rp_edit_btn_bar.setObjectName("rpBtnBar")
        eb = QHBoxLayout(self._rp_edit_btn_bar)
        eb.setContentsMargins(12, 8, 12, 12)
        eb.setSpacing(8)
        self._rp_edit_cancel_btn = QPushButton(tr("dialog.cancel"))
        self._rp_edit_cancel_btn.setObjectName("secondaryBtn")
        self._rp_edit_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_edit_cancel_btn.setToolTip(tr("card.tooltip.cancel_top"))
        self._rp_edit_cancel_btn.clicked.connect(self._on_rp_cancel)
        eb.addWidget(self._rp_edit_cancel_btn)
        self._rp_edit_delete_btn = QPushButton(tr("addedit.button.delete_host"))
        self._rp_edit_delete_btn.setObjectName("dangerBtn")
        self._rp_edit_delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_edit_delete_btn.clicked.connect(self._on_delete)
        eb.addWidget(self._rp_edit_delete_btn)
        eb.addStretch()
        self._rp_edit_save_btn = QPushButton(tr("addedit.button.save_changes"))
        self._rp_edit_save_btn.setObjectName("primaryBtn")
        self._rp_edit_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rp_edit_save_btn.setToolTip(tr("card.tooltip.save_top"))
        self._rp_edit_save_btn.clicked.connect(self._on_rp_save)
        eb.addWidget(self._rp_edit_save_btn)
        self._rp_edit_btn_bar.setVisible(False)
        v.addWidget(self._rp_edit_btn_bar)

        return panel

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("statusBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(8)

        self._status_dot = QLabel("●")
        self._status_dot.setObjectName("statusDot")
        h.addWidget(self._status_dot)

        self._status_lbl = QLabel(tr("app.ready"))
        self._status_lbl.setObjectName("statusText")
        h.addWidget(self._status_lbl)

        h.addStretch()

        self._mount_count_lbl = QLabel("")
        self._mount_count_lbl.setObjectName("versionLabel")
        h.addWidget(self._mount_count_lbl)

        ver_lbl = QLabel("  v" + APP_VERSION)
        ver_lbl.setObjectName("versionLabel")
        h.addWidget(ver_lbl)

        return bar

    def _build_fullscreen_panel(self) -> QWidget:
        """Full-screen content panel used for settings and user management."""
        panel = QWidget()
        panel.setObjectName("fullscreenPanel")
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._fs_header = QWidget()
        self._fs_header.setObjectName("rightPanelHeader")
        fh = QHBoxLayout(self._fs_header)
        fh.setContentsMargins(16, 0, 16, 0)
        fh.setSpacing(12)

        fs_title_wrap = QWidget()
        fs_title_wrap.setObjectName("rightPanelTitleWrap")
        fs_title_layout = QVBoxLayout(fs_title_wrap)
        fs_title_layout.setContentsMargins(0, 0, 0, 0)
        fs_title_layout.setSpacing(0)
        fs_title_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._fs_title = QLabel()
        self._fs_title.setObjectName("rightPanelTitle")
        fs_title_layout.addWidget(self._fs_title)

        fh.addWidget(fs_title_wrap, 1)

        self._fs_close_btn = QPushButton()
        self._fs_close_btn.setObjectName("rpHeaderBtn")
        self._fs_close_btn.setFixedSize(QSize(32, 32))
        self._fs_close_btn.setIcon(svg_icon("x", "#aab4c4", 15))
        self._fs_close_btn.setIconSize(QSize(15, 15))
        self._fs_close_btn.setToolTip(tr("dialog.close"))
        self._fs_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fs_close_btn.clicked.connect(self._nav_home)
        fh.addWidget(self._fs_close_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._fs_header.setVisible(False)
        v.addWidget(self._fs_header)

        self._fs_scroll = QScrollArea()
        self._fs_scroll.setObjectName("rightPanelScroll")
        self._fs_scroll.setWidgetResizable(True)
        self._fs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._fs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._fs_content = QWidget()
        self._fs_content.setObjectName("fullscreenContent")
        self._fs_layout = QVBoxLayout(self._fs_content)
        self._fs_layout.setContentsMargins(0, 0, 0, 0)
        self._fs_layout.setSpacing(0)
        self._fs_scroll.setWidget(self._fs_content)
        v.addWidget(self._fs_scroll, stretch=1)

        self._fs_btn_bar = QWidget()
        self._fs_btn_bar.setObjectName("rpBtnBar")
        bb = QHBoxLayout(self._fs_btn_bar)
        bb.setContentsMargins(24, 8, 24, 12)
        bb.setSpacing(8)
        bb.addStretch()
        self._fs_cancel_btn = QPushButton(tr("dialog.cancel"))
        self._fs_cancel_btn.setObjectName("secondaryBtn")
        self._fs_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fs_cancel_btn.clicked.connect(self._on_fs_cancel)
        bb.addWidget(self._fs_cancel_btn)
        self._fs_save_btn = QPushButton(tr("dialog.save"))
        self._fs_save_btn.setObjectName("primaryBtn")
        self._fs_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fs_save_btn.clicked.connect(self._on_fs_save)
        bb.addWidget(self._fs_save_btn)
        self._fs_btn_bar.setVisible(False)
        v.addWidget(self._fs_btn_bar)

        return panel

    def _clear_fs_content(self):
        while self._fs_layout.count():
            item = self._fs_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _set_fullscreen_header(self, kicker: str = "", title: str = "", show_close: bool = True):
        self._fs_title.setText(title)
        self._fs_title.setVisible(bool(title))
        self._fs_close_btn.setVisible(show_close)
        self._fs_header.setVisible(bool(title or show_close))

    def _nav_home(self):
        """Return to connections view and reset sidebar to home."""
        if not self._guard_leave_form():
            return
        self._clear_fs_content()
        self._set_fullscreen_header("", "", False)
        self._main_stack.setCurrentIndex(0)
        self._panel_mode = _PANEL_NONE
        self._panel_conn_id = None
        self._set_sidebar_active("home")
        self._close_right_panel_force()

    def _on_fs_save(self):
        if self._panel_mode == _PANEL_SETTINGS:
            self._save_settings_form()

    def _on_fs_cancel(self):
        self._nav_home()

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------

    def _setup_tray(self):
        self._tray = SystemTray(self, parent=self)
        self._tray.show()

    # ------------------------------------------------------------------
    # Connection list
    # ------------------------------------------------------------------

    def _refresh_list(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()
        self._containers.clear()
        self._selected_id = None

        connections = self._mgr.get_connections()  # Nur normale Verbindungen (keine Templates)
        mounted = self._compute_mounted(connections)
        # Shared letters switched off: flag hosts that still share a letter.
        from src.drive_utils import duplicate_letters, norm_letter
        dupes = (set() if self._mgr.get_settings().allow_shared_drive_letters
                 else duplicate_letters(connections))

        for conn in connections:
            # FTP/FTPS hosts are never mounted — SSHFS speaks SSH only.
            container = self._create_connection_container(conn, conn.id in mounted)
            self._list_layout.insertWidget(self._list_layout.count() - 1, container)
            self._containers[conn.id] = container
            self._cards[conn.id] = container._card
            container._card.set_mounted_letter(mounted.get(conn.id))
            container._card.set_letter_warning(norm_letter(conn.drive_letter) in dupes)

        self._update_status()
        self._tray.update_connections_menu(connections, mounted)
        self._refresh_groups_combo()  # Gruppen-Filter aktualisieren
        self._apply_group_filter()
        # Restore terminal-active indicators on rebuilt cards
        for conn_id in list(self._terminal_conn_tabs.keys()):
            self._update_card_terminal_indicator(conn_id)

    def _create_connection_container(self, conn, mounted):
        container = QWidget()
        container.setObjectName("connectionContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = ConnectionCard(
            conn, mounted=mounted,
            theme=(self._mgr.get_settings().theme or "dark"),
            debug_edit=bool(self._mgr.get_settings().debug_mode),
        )
        card.mount_requested.connect(self._on_mount)
        card.unmount_requested.connect(self._on_unmount)
        card.ssh_requested.connect(self._on_ssh_requested)
        card.open_path_requested.connect(self._on_open_mounted_path)
        card.open_explorer_requested.connect(self._on_open_explorer)
        card.info_requested.connect(self._on_info_requested)
        card.edit_requested.connect(self._open_edit_panel)
        card.context_menu_requested.connect(self._on_card_context_menu)
        card.mousePressEvent = lambda ev, cid=conn.id: self._select_card(cid)

        layout.addWidget(card)
        container._card = card
        container._conn_id = conn.id
        return container

    # ------------------------------------------------------------------
    # Right panel management
    # ------------------------------------------------------------------

    def _clear_right_panel_content(self):
        """Remove all widgets from the scrollable content area."""
        while self._rp_layout.count():
            item = self._rp_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        # Prevent stale references to deleted Qt widgets from later save/click handlers.
        self._reset_edit_form_refs()

    def _reset_edit_form_refs(self):
        """Clear edit/add form widget references after panel content gets rebuilt."""
        for attr in (
            "_ef_conn", "_ef_name", "_ef_host", "_ef_user", "_ef_path", "_ef_port",
            "_ef_drive", "_ef_auth", "_ef_pw", "_ef_key", "_ef_cli_cb",
            "_ef_cli_widget", "_ef_cli_key", "_ef_cli_copy_btn", "_ef_cli_gen_btn",
            "_ef_putty_key", "_ef_groups", "_ef_template_cb",
            "_ef_protocol", "_ef_ftp_widget", "_ef_ftp_implicit",
            "_ef_ftp_implicit_hint", "_ef_ftp_passive", "_ef_ftp_verify",
            "_ef_ftp_verify_hint", "_ef_ftp_plain_warning", "_ef_key_field",
            "_ef_drive_field", "_ef_cli_section", "_ef_putty_widget",
            "_ef_key_browse_btn", "_ef_lock_banner",
        ):
            setattr(self, attr, None)
        self._ef_mount_locked = False
        self._ef_initial_snapshot = None

    def _ensure_panel_sized(self):
        """Give the right panel a visible size the first time it opens."""
        sizes = self._body_splitter.sizes()
        # If right panel currently has no width, give it a comfortable docked size.
        if len(sizes) == 2 and sizes[1] < 420:
            total = sizes[0] + sizes[1]
            self._body_splitter.setSizes([max(total - 420, 260), 420])

    def _clamp_splitter_40(self, pos: int = 0, index: int = 0) -> None:
        sp = self._body_splitter
        total = sp.widget(0).width() + sp.widget(1).width() + sp.handleWidth()
        if total <= 0:
            return
        min_w = total * 2 // 5
        sizes = sp.sizes()
        if sizes[0] < min_w:
            sp.setSizes([min_w, total - min_w])
        elif sizes[1] < min_w:
            sp.setSizes([total - min_w, min_w])

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_body_splitter"):
            self._clamp_splitter_40()

    def _set_right_panel_header(self, kicker: str = "", title: str = ""):
        self._right_panel_title.setText(title)
        self._right_panel_title.setVisible(bool(title))

    def _show_right_panel_placeholder(self):
        """Render the default empty-state panel instead of collapsing the area."""
        self._clear_right_panel_content()
        self._set_right_panel_header()
        self._rp_info_btn.setVisible(False)
        self._rp_edit_btn.setVisible(False)
        self._rp_terminal_btn.setVisible(False)
        self._rp_mount_btn.setVisible(False)
        self._rp_del_btn.setVisible(False)
        self._rp_save_top_btn.setVisible(False)
        self._rp_cancel_top_btn.setVisible(False)
        self._rp_close_btn.setVisible(False)
        self._rp_new_session_btn.setVisible(False)
        self._rp_btn_bar.setVisible(False)
        self._rp_edit_btn_bar.setVisible(False)
        self._rp_scroll.setVisible(True)
        self._terminal_area.setVisible(False)

        body = QWidget()
        body.setObjectName("rightPanelPlaceholder")
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        v = QVBoxLayout(body)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        v.addStretch()

        copy = QWidget()
        copy.setObjectName("rightPanelPlaceholderCopy")
        copy.setFixedWidth(360)
        copy_layout = QVBoxLayout(copy)
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.setSpacing(10)

        title = QLabel(tr("panel.placeholder.title"))
        title.setObjectName("rightPanelPlaceholderTitle")
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        copy_layout.addWidget(title)

        msg = QLabel(tr("panel.placeholder.body"))
        msg.setObjectName("rightPanelPlaceholderBody")
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        copy_layout.addWidget(msg)

        v.addWidget(copy, 0, Qt.AlignmentFlag.AlignHCenter)

        v.addStretch()
        self._rp_layout.addWidget(body, stretch=1)
        self._right_panel_widget.setVisible(True)
        self._ensure_panel_sized()

    def _close_right_panel(self):
        """Reset the right panel to its placeholder state and deselect."""
        if not self._guard_leave_form():
            return
        self._close_right_panel_force()

    def _close_right_panel_force(self):
        """Close right panel without dirty-check prompt."""
        # Deactivate info btn on previously active card
        if self._panel_conn_id and self._panel_conn_id in self._cards:
            self._cards[self._panel_conn_id].set_info_active(False)

        # If leaving terminal mode: hide terminal area but keep sessions alive
        if self._panel_mode == _PANEL_TERMINAL:
            self._detach_terminal_area()

        self._panel_mode = _PANEL_NONE
        self._panel_conn_id = None
        # Also deselect card highlight
        if self._selected_id and self._selected_id in self._cards:
            card = self._cards[self._selected_id]
            card.setProperty("selected", False)
            card.style().unpolish(card)
            card.style().polish(card)
        self._selected_id = None
        self._show_right_panel_placeholder()

    def _open_info_panel(self, conn_id: str):
        """Show connection details (host data / credentials) for the given connection."""
        if (self._panel_mode in (_PANEL_EDIT, _PANEL_ADD)) and (conn_id != self._panel_conn_id):
            if not self._guard_leave_form():
                return
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return

        if self._panel_conn_id and self._panel_conn_id in self._cards:
            self._cards[self._panel_conn_id].set_info_active(False)

        self._panel_mode = _PANEL_INFO
        self._panel_conn_id = conn_id

        card = self._cards.get(conn_id)
        is_mounted = card and card.is_mounted

        self._set_right_panel_header(tr("panel.header.details"), conn.name.upper())
        # Edit button: always available; while mounted the form locks the
        # connection fields itself.
        theme = self._mgr.get_settings().theme or "dark"
        edit_icon_color = current_accent() if theme == "light" else "#aab4c4"
        self._rp_edit_btn.setIcon(svg_icon("edit", edit_icon_color, 15))
        self._rp_edit_btn.setVisible(True)
        self._rp_edit_btn.setEnabled(True)
        self._rp_edit_btn.setToolTip(tr("card.tooltip.edit"))
        # Header actions (overview): Sysinfo → Edit → Terminal → Mount → Close.
        # Terminal, sysinfo and mount all need SSH, so they are hidden for FTP.
        is_ftp = bool(conn.is_ftp)
        self._rp_info_btn.setVisible(not is_ftp)
        self._rp_terminal_btn.setVisible(not is_ftp)
        self._rp_mount_btn.setVisible(not is_ftp)
        if not is_ftp:
            self._sync_rp_mount_button(conn_id)

        self._rp_del_btn.setVisible(False)
        self._rp_save_top_btn.setVisible(False)
        self._rp_cancel_top_btn.setVisible(False)
        self._rp_close_btn.setVisible(True)
        self._rp_new_session_btn.setVisible(False)
        self._rp_btn_bar.setVisible(False)
        self._rp_edit_btn_bar.setVisible(False)

        self._clear_right_panel_content()
        self._rp_scroll.setVisible(True)
        self._terminal_area.setVisible(False)
        self._build_info_content(conn)
        self._right_panel_widget.setVisible(True)
        self._ensure_panel_sized()

    def _open_sysinfo_panel(self, conn_id: str):
        """Show system info (SSH stats) for the given connection — always, regardless of mount."""
        if self._panel_mode in (_PANEL_EDIT, _PANEL_ADD):
            if not self._guard_leave_form():
                return
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return
        # System info is collected over SSH — not available for FTP/FTPS.
        if self._reject_ftp_action(conn, "ftp.ssh_unsupported"):
            return

        if self._panel_conn_id and self._panel_conn_id in self._cards:
            self._cards[self._panel_conn_id].set_info_active(False)

        self._panel_mode = _PANEL_SYSINFO
        self._panel_conn_id = conn_id

        card = self._cards.get(conn_id)
        if card:
            card.set_info_active(True)

        self._set_right_panel_header(tr("panel.header.sysinfo"), conn.name.upper())
        self._rp_info_btn.setVisible(False)
        self._rp_edit_btn.setVisible(False)
        self._rp_terminal_btn.setVisible(True)
        self._rp_mount_btn.setVisible(True)
        self._sync_rp_mount_button(conn_id)
        self._rp_del_btn.setVisible(False)
        self._rp_save_top_btn.setVisible(False)
        self._rp_cancel_top_btn.setVisible(False)
        self._rp_close_btn.setVisible(True)
        self._rp_new_session_btn.setVisible(False)
        self._rp_btn_bar.setVisible(False)
        self._rp_edit_btn_bar.setVisible(False)

        self._clear_right_panel_content()
        self._rp_scroll.setVisible(True)
        self._terminal_area.setVisible(False)
        self._build_sysinfo_fullpanel(conn)
        self._right_panel_widget.setVisible(True)
        self._ensure_panel_sized()

    def _build_info_content(self, conn: Connection):
        """Build the read-only info view for the right panel."""
        is_mounted = (conn.id in self._cards and self._cards[conn.id].is_mounted)

        _theme = (self._mgr.get_settings().theme or "dark")
        _val_color = "#ffffff" if not is_light(_theme) else "#1a2332"

        body = QWidget()
        body.setObjectName("rpInfoBody")
        v = QVBoxLayout(body)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(8)

        def _section(title):
            lbl = QLabel(title.upper())
            lbl.setObjectName("rpSectionLabel")
            lbl.setStyleSheet(f"color: {current_accent()}; font-size: 11px;font-weight: 600;text-transform: uppercase; letter-spacing: 1px; padding-top: 4px;")
            return lbl

        def _row(label, value, value_obj_name="rpValue"):
            container = QFrame()
            container.setObjectName("rpInfoField")
            container.setFixedHeight(54)
            vl = QVBoxLayout(container)
            vl.setContentsMargins(16, 8, 16, 8)
            vl.setSpacing(4)
            lbl = QLabel(label.upper())
            lbl.setObjectName("rpFieldLabelCaps")
            lbl.setStyleSheet("color: #6a7685; font-size: 11px; font-weight: 500;")
            val = QLabel(str(value) if value else "—")
            val.setObjectName(value_obj_name)
            val.setStyleSheet(f"color: {_val_color}; font-size: 14px; font-weight: 400; padding: 0; background: transparent; border: none;")
            vl.addWidget(lbl)
            vl.addWidget(val)
            return container

        def _row_pair(label1, value1, label2, value2, stretch1=2, stretch2=1):
            wrapper = QWidget()
            hl = QHBoxLayout(wrapper)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(8)
            hl.addWidget(_row(label1, value1), stretch=stretch1)
            hl.addWidget(_row(label2, value2), stretch=stretch2)
            return wrapper

        v.addLayout(self._build_status_row(conn, is_mounted, _theme))
        v.addSpacing(8)

        # General
        v.addWidget(_section(tr("addedit.section.general")))
        v.addWidget(_row_pair(tr("addedit.label.name"), conn.name,
                              tr("panel.label.protocol"), conn.protocol_label, 2, 1))
        v.addWidget(_row_pair(tr("addedit.label.host"), conn.host,
                              tr("addedit.label.port"), str(conn.port), 2, 1))
        v.addWidget(_row(tr("addedit.label.user"), conn.user))

        # Auth
        v.addSpacing(4)
        v.addWidget(_section(tr("addedit.section.auth")))
        auth_map = {"password": tr("addedit.auth.password"), "key": tr("addedit.auth.key"), "ask": tr("addedit.auth.ask")}
        v.addWidget(_row(tr("addedit.label.method"), auth_map.get(conn.auth_method, conn.auth_method)))
        if conn.auth_method in ("password", "ask") and conn.password:
            v.addWidget(_row(tr("addedit.label.password"), "••••••••"))
        if conn.key_path:
            v.addWidget(_row(tr("addedit.label.key"), conn.key_path))

        # Path & Drive (FTP has no drive letter — show the TLS setup instead)
        v.addSpacing(4)
        v.addWidget(_section(tr("addedit.section.path")))
        if conn.is_ftp:
            v.addWidget(_row(tr("addedit.label.path"), conn.remote_path))
            v.addSpacing(4)
            v.addWidget(_section(tr("addedit.section.ftp")))
            _yes, _no = tr("dialog.yes"), tr("dialog.no")
            if conn.protocol == PROTOCOL_FTPS:
                v.addWidget(_row_pair(
                    tr("addedit.ftp.implicit"), _yes if conn.ftp_implicit_tls else _no,
                    tr("addedit.ftp.verify_cert"), _yes if conn.ftp_verify_cert else _no,
                    1, 1,
                ))
            v.addWidget(_row(tr("addedit.ftp.passive"), _yes if conn.ftp_passive else _no))
        else:
            v.addWidget(_row_pair(tr("addedit.label.path"), conn.remote_path,
                                  tr("addedit.label.drive"), self._effective_letter(conn), 3, 1))

        # CLI
        if conn.cli_access_enabled:
            v.addSpacing(4)
            v.addWidget(_section(tr("addedit.section.cli")))
            v.addWidget(_row(tr("addedit.cli.label"), tr("addedit.cli.enable") + " ✓"))
            history_btn = QPushButton(tr("addedit.cli.view_history"))
            history_btn.setObjectName("secondaryBtn")
            history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            history_btn.clicked.connect(lambda _checked, cid=conn.id: self._open_cli_history_panel(cid))
            v.addWidget(history_btn)

        v.addStretch()
        self._rp_layout.addWidget(body)

    def _build_status_row(self, conn: Connection, is_mounted: bool, theme: str) -> QHBoxLayout:
        """Status pill + folder buttons, shared by the info panel and the edit form.

        - Status pill: green when mounted; a click opens the drive in Explorer,
          same as the drive letter in the list.
        - Explorer folder (SFTP only): grey while unmounted, a click mounts;
          green when mounted, a click opens the drive in Explorer.
        - FTP folder (always shown): opens the built-in file browser, which
          works with or without a mount.
        """
        green = "#00d464" if not is_light(theme) else "#007a3d"
        grey = "#8a9aa8"
        accent = accent_tone("#00b4d8") if not is_light(theme) else current_accent()

        def _on_left_click(widget, callback):
            def _handler(ev):
                if ev.button() == Qt.MouseButton.LeftButton:
                    callback()
            widget.mousePressEvent = _handler

        status_row = QHBoxLayout()
        status_row.setSpacing(12)

        status_container = QFrame()
        status_container.setObjectName("rpStatusContainer")
        rgb = "0, 212, 100" if is_mounted else "106, 122, 138"
        status_container.setStyleSheet(f"""
            QFrame#rpStatusContainer {{
                background-color: rgba({rgb}, 0.15);
                border: 1px solid rgba({rgb}, 0.3);
                border-radius: 8px;
            }}
        """)
        status_layout = QHBoxLayout(status_container)
        status_layout.setContentsMargins(12, 6, 16, 6)
        status_layout.setSpacing(6)
        state_color = "#00d464" if is_mounted else grey
        dot = QWidget()
        dot.setFixedSize(6, 6)
        dot.setStyleSheet(f"background-color: {state_color}; border-radius: 3px;")
        status_layout.addWidget(dot)
        status_text = QLabel(tr("panel.status.connected") if is_mounted else tr("panel.status.disconnected"))
        status_text.setStyleSheet(f"color: {state_color}; font-weight: 600; font-size: 13px;")
        status_layout.addWidget(status_text)
        if is_mounted:
            status_container.setCursor(Qt.CursorShape.PointingHandCursor)
            status_container.setToolTip(tr("card.tooltip.open_path"))
            _on_left_click(status_container, lambda cid=conn.id: self._on_open_explorer(cid))
        status_row.addWidget(status_container)
        status_row.addStretch()

        folders = QHBoxLayout()
        folders.setSpacing(4)
        if not conn.is_ftp:
            explorer_lbl = QLabel()
            explorer_lbl.setPixmap(svg_pixmap("folder", green if is_mounted else grey, 30))
            explorer_lbl.setFixedSize(QSize(42, 30))
            explorer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            explorer_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            explorer_lbl.setToolTip(
                tr("card.tooltip.open_path") if is_mounted else tr("card.tooltip.mount_off")
            )
            _on_left_click(explorer_lbl, lambda cid=conn.id: self._on_status_folder_clicked(cid))
            folders.addWidget(explorer_lbl)

        browser_lbl = QLabel()
        browser_lbl.setPixmap(svg_pixmap_text("folder", accent, 30, "FTP"))
        browser_lbl.setFixedSize(QSize(42, 30))
        browser_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        browser_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        browser_lbl.setToolTip(
            tr("card.tooltip.ftp_browser", proto=conn.protocol_label) if conn.is_ftp
            else tr("card.tooltip.sftp_browser")
        )
        _on_left_click(
            browser_lbl, lambda cid=conn.id: self._open_sftp_browser(cid, mounted_only=False)
        )
        folders.addWidget(browser_lbl)
        status_row.addLayout(folders)
        return status_row

    def _on_status_folder_clicked(self, conn_id: str):
        """Explorer folder in the status row: mount, or open the mounted drive."""
        card = self._cards.get(conn_id)
        if card and card.is_mounted:
            self._on_open_explorer(conn_id)
            return
        # A successful mount switches an open edit form to the info panel, so
        # ask first when that would drop unsaved changes.
        if self._panel_mode in (_PANEL_EDIT, _PANEL_ADD) and not self._guard_leave_form():
            return
        self._on_mount(conn_id)

    def _build_sysinfo_fullpanel(self, conn: Connection):
        """Fill the right panel content area with SystemInfoPanel (mounted state)."""
        from src.ui.system_info_panel import SystemInfoPanel
        try:
            sip = SystemInfoPanel(conn, parent=self._rp_content, settings=self._mgr.get_settings())
        except AttributeError:
            sip = SystemInfoPanel(conn, parent=self._rp_content)
        sip.setObjectName("sysinfoFullPanel")
        self._rp_layout.addWidget(sip)
        self._current_info_panel = sip

    def _open_cli_history_panel(self, conn_id: str):
        """Show the CLI history (Befehle + Sitzungen via NeoSSHWinManager-cli.exe) for a host."""
        if self._panel_mode in (_PANEL_EDIT, _PANEL_ADD):
            if not self._guard_leave_form():
                return
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return
        # CLI-Zugriff existiert ohnehin nur für SSH-Hosts (im Edit-Formular
        # für FTP ausgeblendet) — Guard trotzdem der Konsistenz mit den
        # anderen SSH-only-Panels halber.
        if self._reject_ftp_action(conn, "ftp.ssh_unsupported"):
            return

        if self._panel_conn_id and self._panel_conn_id in self._cards:
            self._cards[self._panel_conn_id].set_info_active(False)

        self._panel_mode = _PANEL_CLI_HISTORY
        self._panel_conn_id = conn_id

        card = self._cards.get(conn_id)
        if card:
            card.set_info_active(True)

        self._set_right_panel_header(tr("panel.header.clihistory"), conn.name.upper())
        self._rp_info_btn.setVisible(False)
        self._rp_edit_btn.setVisible(False)
        self._rp_terminal_btn.setVisible(True)
        self._rp_mount_btn.setVisible(True)
        self._sync_rp_mount_button(conn_id)
        self._rp_del_btn.setVisible(False)
        self._rp_save_top_btn.setVisible(False)
        self._rp_cancel_top_btn.setVisible(False)
        self._rp_close_btn.setVisible(True)
        self._rp_new_session_btn.setVisible(False)
        self._rp_btn_bar.setVisible(False)
        self._rp_edit_btn_bar.setVisible(False)

        self._clear_right_panel_content()
        self._rp_scroll.setVisible(True)
        self._terminal_area.setVisible(False)
        self._build_cli_history_fullpanel(conn)
        self._right_panel_widget.setVisible(True)
        self._ensure_panel_sized()

    def _build_cli_history_fullpanel(self, conn: Connection):
        """Fill the right panel content area with CliHistoryPanel."""
        from src.ui.cli_history_panel import CliHistoryPanel
        panel = CliHistoryPanel(conn, self._mgr, parent=self._rp_content, settings=self._mgr.get_settings())
        self._rp_layout.addWidget(panel)

    def _open_edit_panel(self, conn_id: str):
        """Show the inline edit form for the given connection."""
        if not self._guard_leave_form():
            return
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return

        # Mounted hosts can be edited too: the form locks the connection fields.
        card = self._cards.get(conn_id)

        if self._panel_conn_id and self._panel_conn_id in self._cards:
            self._cards[self._panel_conn_id].set_info_active(False)

        self._panel_mode = _PANEL_EDIT
        self._panel_conn_id = conn_id

        if card:
            card.set_info_active(True)

        self._set_right_panel_header(tr("addedit.edit_title"), tr("addedit.edit_title").upper())
        # Edit-Mode: only destructive/save/discard actions in header
        self._rp_info_btn.setVisible(False)
        self._rp_edit_btn.setVisible(False)
        self._rp_terminal_btn.setVisible(False)
        self._rp_mount_btn.setVisible(False)
        self._rp_del_btn.setVisible(True)
        self._rp_del_btn.setEnabled(True)
        self._rp_save_top_btn.setVisible(True)
        self._rp_cancel_top_btn.setVisible(True)
        # Avoid duplicate close/discard UX (and double dirty-prompts)
        self._rp_close_btn.setVisible(False)
        self._rp_new_session_btn.setVisible(False)
        self._rp_btn_bar.setVisible(False)
        self._rp_edit_btn_bar.setVisible(True)

        self._clear_right_panel_content()
        self._rp_scroll.setVisible(True)
        self._terminal_area.setVisible(False)
        self._build_edit_form(conn)
        self._right_panel_widget.setVisible(True)
        self._ensure_panel_sized()

    def _open_add_panel(self):
        """Show the inline add-connection form."""
        if not self._guard_leave_form():
            return
        if self._panel_conn_id and self._panel_conn_id in self._cards:
            self._cards[self._panel_conn_id].set_info_active(False)
        if self._selected_id and self._selected_id in self._cards:
            card = self._cards[self._selected_id]
            card.setProperty("selected", False)
            card.style().unpolish(card)
            card.style().polish(card)
        self._selected_id = None
        self._panel_mode = _PANEL_ADD
        self._panel_conn_id = None

        self._set_right_panel_header(tr("addedit.add_title"), tr("addedit.add_title").upper())
        self._rp_info_btn.setVisible(False)
        self._rp_edit_btn.setVisible(False)
        self._rp_terminal_btn.setVisible(False)
        self._rp_mount_btn.setVisible(False)
        self._rp_del_btn.setVisible(False)
        self._rp_save_top_btn.setVisible(False)
        self._rp_cancel_top_btn.setVisible(False)
        self._rp_close_btn.setVisible(True)
        self._rp_new_session_btn.setVisible(False)
        self._rp_btn_bar.setVisible(True)
        self._rp_edit_btn_bar.setVisible(False)

        self._clear_right_panel_content()
        self._rp_scroll.setVisible(True)
        self._terminal_area.setVisible(False)
        self._build_edit_form(None)
        self._right_panel_widget.setVisible(True)
        self._ensure_panel_sized()

    def _open_settings_panel(self):
        """Show the settings form full-screen. Toggle off if already open."""
        if not self._guard_leave_form():
            return
        if self._panel_mode == _PANEL_SETTINGS:
            # Ignore duplicate/rapid open requests while already in settings.
            return
        if self._panel_conn_id and self._panel_conn_id in self._cards:
            self._cards[self._panel_conn_id].set_info_active(False)
        self._panel_mode = _PANEL_SETTINGS
        self._panel_conn_id = None

        self._clear_fs_content()
        self._set_fullscreen_header(tr("main.settings"), tr("settings.title"), True)
        self._build_settings_form()
        self._settings_initial_snapshot = self._snapshot_settings_form()
        self._fs_btn_bar.setVisible(True)
        self._main_stack.setCurrentIndex(1)
        self._set_sidebar_active("settings")

    def _open_users_panel(self):
        """Show user management full-screen. Toggle off if already open."""
        if not self._guard_leave_form():
            return
        if self._panel_mode == _PANEL_USERS:
            self._nav_home()
            return
        if self._panel_conn_id and self._panel_conn_id in self._cards:
            self._cards[self._panel_conn_id].set_info_active(False)
        self._panel_mode = _PANEL_USERS
        self._panel_conn_id = None

        self._clear_fs_content()
        self._set_fullscreen_header(tr("main.users"), tr("users.title"), True)
        self._build_users_form()
        self._fs_btn_bar.setVisible(False)
        self._main_stack.setCurrentIndex(1)
        self._set_sidebar_active("users")
        self._settings_initial_snapshot = None

    def _build_profile_form(self):
        """Build the profile form for password change (available to all users)."""
        from src.auth_manager import AuthManager
        current_user = Session.current()
        if not current_user:
            return

        _theme = self._mgr.get_settings().theme or "dark"
        _is_light = (_theme == "light")
        _inp_bg    = "#ffffff"  if _is_light else dark_tone(_theme, "#0d1117")
        _inp_bdr   = "#c0cad6" if _is_light else dark_tone(_theme, "#30363d")
        _inp_fg    = "#1a2332" if _is_light else dark_tone(_theme, "#deebf7")
        _lbl_muted = "#5a6a7a" if _is_light else dark_tone(_theme, "#8fa4b8")
        _lbl_bold  = "#1a2332" if _is_light else dark_tone(_theme, "#deebf7")
        _inp_style = f"background-color: {_inp_bg}; border: 1px solid {_inp_bdr}; border-radius: 6px; padding: 8px; color: {_inp_fg};"

        body = QWidget()
        body.setObjectName("fullscreenForm")
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        body.setMinimumWidth(320)
        v = QVBoxLayout(body)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(16)

        # User info section
        _title_color  = "#1a2332" if _is_light else dark_tone(_theme, "#deebf7")
        _pill_bg      = current_accent()

        def _section_card(title: str, pill_text: str = ""):
            frame = QFrame()
            frame.setObjectName("fullscreenSectionCard")
            frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(18, 16, 18, 16)
            layout.setSpacing(12)

            head = QWidget()
            head_layout = QHBoxLayout(head)
            head_layout.setContentsMargins(0, 0, 0, 0)
            head_layout.setSpacing(10)

            head_title = QLabel(title)
            head_title.setStyleSheet(
                f"color: {_title_color}; font-size: 14px; font-weight: 700;"
            )
            head_layout.addWidget(head_title)
            head_layout.addStretch()

            if pill_text:
                pill = QLabel(pill_text)
                pill.setStyleSheet(
                    f"background-color: {_pill_bg}; color: {accent_text_color(_pill_bg)}; "
                    f"border-radius: 8px; padding: 2px 8px; "
                    f"font-size: 10px; font-weight: 700;"
                )
                head_layout.addWidget(pill)

            layout.addWidget(head)
            return frame, layout

        # User info card
        info_card, info_l = _section_card(tr("profile.user_info"), tr("profile.active"))
        
        username_row = QWidget()
        username_h = QHBoxLayout(username_row)
        username_h.setContentsMargins(0, 0, 0, 0)
        username_lbl = QLabel(tr("profile.username"))
        username_lbl.setStyleSheet(f"color: {_lbl_muted}; font-size: 12px;")
        username_val = QLabel(current_user.username)
        username_val.setStyleSheet(f"color: {_lbl_bold}; font-size: 14px; font-weight: 600;")
        username_h.addWidget(username_lbl)
        username_h.addWidget(username_val)
        username_h.addStretch()
        info_l.addWidget(username_row)

        role_row = QWidget()
        role_h = QHBoxLayout(role_row)
        role_h.setContentsMargins(0, 0, 0, 0)
        role_lbl = QLabel(tr("profile.role"))
        role_lbl.setStyleSheet(f"color: {_lbl_muted}; font-size: 12px;")
        role_val = QLabel(tr("profile.role.admin") if Session.is_admin() else tr("profile.role.user"))
        role_val.setStyleSheet("color: #00d464; font-size: 14px; font-weight: 600;" if Session.is_admin() else f"color: {_lbl_bold}; font-size: 14px; font-weight: 600;")
        role_h.addWidget(role_lbl)
        role_h.addWidget(role_val)
        role_h.addStretch()
        info_l.addWidget(role_row)

        v.addWidget(info_card)

        # Single-user mode: the app password is random and nobody knows it,
        # so it cannot be changed here. Setting one means switching to
        # multi-user login in the user management.
        if AuthManager.single_user_mode_enabled():
            su_card, su_l = _section_card(tr("profile.change_password"))
            su_hint = QLabel(tr("profile.single_user_hint"))
            su_hint.setWordWrap(True)
            su_hint.setStyleSheet(f"color: {_lbl_muted}; font-size: 12px;")
            su_l.addWidget(su_hint)
            v.addWidget(su_card)
            v.addStretch()
            self._fs_layout.addWidget(body)
            return

        # Password change card
        pw_card, pw_l = _section_card(tr("profile.change_password"))

        # Current password
        curr_pw_row = QWidget()
        curr_pw_v = QVBoxLayout(curr_pw_row)
        curr_pw_v.setContentsMargins(0, 0, 0, 0)
        curr_pw_v.setSpacing(4)
        curr_pw_lbl = QLabel(tr("chgpw.current"))
        curr_pw_lbl.setStyleSheet(f"color: {_lbl_muted}; font-size: 11px;")
        self._pf_curr_pw = QLineEdit()
        self._pf_curr_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._pf_curr_pw.setStyleSheet(_inp_style)
        self._pf_curr_pw.setPlaceholderText(tr("chgpw.current"))
        curr_pw_v.addWidget(curr_pw_lbl)
        curr_pw_v.addWidget(self._pf_curr_pw)
        pw_l.addWidget(curr_pw_row)

        # New password
        new_pw_row = QWidget()
        new_pw_v = QVBoxLayout(new_pw_row)
        new_pw_v.setContentsMargins(0, 0, 0, 0)
        new_pw_v.setSpacing(4)
        new_pw_lbl = QLabel(tr("chgpw.new"))
        new_pw_lbl.setStyleSheet(f"color: {_lbl_muted}; font-size: 11px;")
        self._pf_new_pw = QLineEdit()
        self._pf_new_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._pf_new_pw.setStyleSheet(_inp_style)
        self._pf_new_pw.setPlaceholderText(tr("chgpw.new"))
        new_pw_v.addWidget(new_pw_lbl)
        new_pw_v.addWidget(self._pf_new_pw)
        pw_l.addWidget(new_pw_row)

        # Confirm password
        conf_pw_row = QWidget()
        conf_pw_v = QVBoxLayout(conf_pw_row)
        conf_pw_v.setContentsMargins(0, 0, 0, 0)
        conf_pw_v.setSpacing(4)
        conf_pw_lbl = QLabel(tr("chgpw.confirm"))
        conf_pw_lbl.setStyleSheet(f"color: {_lbl_muted}; font-size: 11px;")
        self._pf_conf_pw = QLineEdit()
        self._pf_conf_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._pf_conf_pw.setStyleSheet(_inp_style)
        self._pf_conf_pw.setPlaceholderText(tr("chgpw.confirm"))
        conf_pw_v.addWidget(conf_pw_lbl)
        conf_pw_v.addWidget(self._pf_conf_pw)
        pw_l.addWidget(conf_pw_row)

        # Error label
        self._pf_error_lbl = QLabel("")
        self._pf_error_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
        self._pf_error_lbl.hide()
        pw_l.addWidget(self._pf_error_lbl)

        # Save button
        save_btn = QPushButton(tr("dialog.save"))
        save_btn.setObjectName("primaryBtn")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_profile_form)
        pw_l.addWidget(save_btn)

        v.addWidget(pw_card)
        v.addStretch()

        self._fs_layout.addWidget(body)

    def _save_profile_form(self):
        """Save password change from profile form."""
        from src.auth_manager import AuthManager
        current_user = Session.current()
        if not current_user:
            return

        curr_pw = self._pf_curr_pw.text()
        new_pw = self._pf_new_pw.text()
        conf_pw = self._pf_conf_pw.text()

        # Validation
        if not curr_pw:
            self._pf_error_lbl.setText(tr("chgpw.wrong_old"))
            self._pf_error_lbl.show()
            return

        if len(new_pw) < 8:
            self._pf_error_lbl.setText(tr("chgpw.new_min"))
            self._pf_error_lbl.show()
            return

        if new_pw != conf_pw:
            self._pf_error_lbl.setText(tr("chgpw.mismatch"))
            self._pf_error_lbl.show()
            return

        # Try to change password
        try:
            if AuthManager.change_password(current_user.id, curr_pw, new_pw):
                self._pf_error_lbl.setStyleSheet("color: #00d464; font-size: 12px;")
                self._pf_error_lbl.setText(tr("chgpw.success"))
                self._pf_error_lbl.show()
                self._pf_curr_pw.clear()
                self._pf_new_pw.clear()
                self._pf_conf_pw.clear()
                QTimer.singleShot(2000, lambda: self._nav_home())
            else:
                self._pf_error_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
                self._pf_error_lbl.setText(tr("chgpw.wrong_old"))
                self._pf_error_lbl.show()
        except Exception as e:
            self._pf_error_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
            self._pf_error_lbl.setText(str(e))
            self._pf_error_lbl.show()

    def _open_profile_panel(self):
        """Show user profile panel for password change."""
        if self._panel_mode == _PANEL_PROFILE:
            self._nav_home()
            return
        if not self._guard_leave_form():
            return
        if self._panel_conn_id and self._panel_conn_id in self._cards:
            self._cards[self._panel_conn_id].set_info_active(False)
        self._panel_mode = _PANEL_PROFILE
        self._panel_conn_id = None

        self._clear_fs_content()
        self._set_fullscreen_header(tr("main.profile"), tr("profile.title"), True)
        self._build_profile_form()
        self._fs_btn_bar.setVisible(False)
        self._main_stack.setCurrentIndex(1)
        self._set_sidebar_active("profile")
        self._settings_initial_snapshot = None

    def _build_users_form(self):
        from src.auth_manager import AuthManager
        from src.database import get_connection
        from src.crypto import is_keyring_available

        users = AuthManager.list_users()
        current_user = Session.current()
        current_id = current_user.id if current_user else None
        current_username = current_user.username if current_user else ""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT user_id, COUNT(*) AS count FROM connections GROUP BY user_id"
            ).fetchall()
        connection_counts = {row["user_id"]: row["count"] for row in rows}

        body = QWidget()
        body.setObjectName("fullscreenForm")
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        body.setMinimumWidth(320)
        v = QVBoxLayout(body)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(16)

        def _section_card(title: str, pill_text: str = ""):
            frame = QFrame()
            frame.setObjectName("fullscreenSectionCard")
            frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(18, 16, 18, 16)
            layout.setSpacing(12)

            head = QWidget()
            head_layout = QHBoxLayout(head)
            head_layout.setContentsMargins(0, 0, 0, 0)
            head_layout.setSpacing(10)

            head_title = QLabel(title)
            head_title.setObjectName("connectionsTitle")
            head_layout.addWidget(head_title)
            head_layout.addStretch(1)
            if pill_text:
                head_layout.addWidget(self._pill_label(pill_text), 0, Qt.AlignmentFlag.AlignVCenter)

            layout.addWidget(head)
            return frame, layout

        hero = QFrame()
        hero.setObjectName("dialogHeroCard")
        hero_l = QHBoxLayout(hero)
        hero_l.setContentsMargins(22, 18, 22, 18)
        hero_l.setSpacing(14)

        hero_copy = QWidget()
        hero_copy_layout = QVBoxLayout(hero_copy)
        hero_copy_layout.setContentsMargins(0, 0, 0, 0)
        hero_copy_layout.setSpacing(6)
        hero_copy_layout.addWidget(self._section_label(tr("users.section.users")))

        lead = QLabel(tr("dialog.lead.users"))
        lead.setObjectName("connectionsTitle")
        lead.setWordWrap(True)
        hero_copy_layout.addWidget(lead)

        hero_l.addWidget(hero_copy, 1)

        summary = self._pill_label(
            tr("users.summary", users=len(users), admins=sum(1 for user in users if user["is_admin"]))
        )
        hero_l.addWidget(summary, 0, Qt.AlignmentFlag.AlignTop)
        v.addWidget(hero)

        # Login mode. Switching keeps the account id and its encryption key,
        # so connections and settings stay as they are.
        mode_card, mode_layout = _section_card(tr("users.mode.title"))
        if AuthManager.single_user_mode_enabled():
            mode_hint = QLabel(tr("users.mode.single_hint"))
            mode_hint.setObjectName("hintLabel")
            mode_hint.setWordWrap(True)
            mode_layout.addWidget(mode_hint)

            mode_layout.addWidget(self._field_label(tr("users.placeholder.username")))
            self._um_username = QLineEdit()
            self._um_username.setPlaceholderText(tr("users.placeholder.username"))
            mode_layout.addWidget(self._um_username)

            mode_layout.addWidget(self._field_label(tr("users.placeholder.password")))
            self._um_password = QLineEdit()
            self._um_password.setPlaceholderText(tr("users.placeholder.password"))
            self._um_password.setEchoMode(QLineEdit.EchoMode.Password)
            mode_layout.addWidget(self._um_password)

            mode_layout.addWidget(self._field_label(tr("login.pw_confirm")))
            self._um_password2 = QLineEdit()
            self._um_password2.setPlaceholderText(tr("login.pw_repeat"))
            self._um_password2.setEchoMode(QLineEdit.EchoMode.Password)
            self._um_password2.returnPressed.connect(self._migrate_single_user_to_multi)
            mode_layout.addWidget(self._um_password2)

            self._um_error = QLabel("")
            self._um_error.setObjectName("errorLabel")
            self._um_error.setWordWrap(True)
            self._um_error.setVisible(False)
            mode_layout.addWidget(self._um_error)

            mode_btn = QPushButton(tr("users.mode.enable_multi"))
            mode_btn.setObjectName("primaryBtn")
            mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            mode_btn.clicked.connect(self._migrate_single_user_to_multi)
            mode_layout.addWidget(mode_btn)

            # A single account: no user list, no "create user" form
            v.addWidget(mode_card)
            v.addStretch()
            self._fs_layout.addWidget(body, stretch=1)
            return

        mode_hint = QLabel(tr("users.mode.multi_hint"))
        mode_hint.setObjectName("hintLabel")
        mode_hint.setWordWrap(True)
        mode_layout.addWidget(mode_hint)

        keyring_available = is_keyring_available()
        mode_btn = QPushButton(tr("users.mode.enable_single"))
        mode_btn.setObjectName("secondaryBtn")
        mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mode_btn.setEnabled(keyring_available and len(users) <= 1)
        mode_btn.clicked.connect(self._enable_single_user_mode)
        mode_layout.addWidget(mode_btn)

        if not keyring_available or len(users) > 1:
            notice = QLabel(
                tr("login.single_unavailable_keyring") if not keyring_available
                else tr("login.single_unavailable_users")
            )
            notice.setObjectName("hintLabel")
            notice.setWordWrap(True)
            mode_layout.addWidget(notice)

        columns = QHBoxLayout()
        columns.setSpacing(16)

        list_card, list_layout = _section_card(tr("users.section.users"), current_username)

        for u in users:
            uid = u["id"]
            name = u["username"]
            is_me = uid == current_id
            connection_count = int(connection_counts.get(uid, 0))
            count_text = tr("users.connections.one", n=connection_count) if connection_count == 1 else tr("users.connections.many", n=connection_count)

            row = QFrame()
            row.setObjectName("userBox")
            row.setProperty("current", "true" if is_me else "false")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 12, 14, 12)
            rl.setSpacing(10)

            avatar = QLabel(name[:2].upper())
            avatar.setObjectName("userAvatar")
            avatar.setProperty("admin", "true" if u["is_admin"] else "false")
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar.setFixedSize(QSize(46, 46))
            rl.addWidget(avatar)

            meta = QWidget()
            meta_l = QVBoxLayout(meta)
            meta_l.setContentsMargins(0, 0, 0, 0)
            meta_l.setSpacing(4)

            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.setSpacing(8)

            name_lbl = QLabel(name)
            name_lbl.setObjectName("userRowName")
            header_row.addWidget(name_lbl)

            role_badge = QLabel(tr("users.admin") if u["is_admin"] else tr("users.role.member"))
            role_badge.setObjectName("userRoleBadge")
            if u["is_admin"]:
                role_badge.setProperty("variant", "accent")
            header_row.addWidget(role_badge)

            if is_me:
                you_badge = QLabel(tr("users.badge.you"))
                you_badge.setObjectName("userRoleBadge")
                you_badge.setProperty("variant", "accent")
                header_row.addWidget(you_badge)

            header_row.addStretch(1)
            meta_l.addLayout(header_row)

            sub_lbl = QLabel(count_text)
            sub_lbl.setObjectName("userMetaSub")
            meta_l.addWidget(sub_lbl)

            rl.addWidget(meta, stretch=1)

            if not is_me:
                if Session.is_admin():
                    rst_btn = QPushButton()
                    rst_btn.setObjectName("rpHeaderBtn")
                    rst_btn.setFixedSize(QSize(32, 32))
                    rst_btn.setIcon(svg_icon("rotate-cw", "#aab4c4", 15))
                    rst_btn.setIconSize(QSize(15, 15))
                    rst_btn.setToolTip(tr("users.tooltip.reset_pw", name=name))
                    rst_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    rst_btn.clicked.connect(lambda _, i=uid, n=name: self._uf_reset_password(i, n))
                    rl.addWidget(rst_btn)

                del_btn = QPushButton()
                del_btn.setObjectName("rpHeaderBtn")
                del_btn.setFixedSize(QSize(32, 32))
                del_btn.setIcon(svg_icon("trash", "#ef4444", 15))
                del_btn.setIconSize(QSize(15, 15))
                del_btn.setToolTip(tr("users.tooltip.delete", name=name))
                del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                del_btn.clicked.connect(lambda _, i=uid, n=name: self._uf_delete_user(i, n))
                rl.addWidget(del_btn)

            list_layout.addWidget(row)

        create_card, create_layout = _section_card(tr("users.section.new"))

        create_layout.addWidget(self._field_label(tr("users.placeholder.username")))
        self._uf_username = QLineEdit()
        self._uf_username.setPlaceholderText(tr("users.placeholder.username"))
        create_layout.addWidget(self._uf_username)

        create_layout.addWidget(self._field_label(tr("users.placeholder.password")))
        self._uf_password = QLineEdit()
        self._uf_password.setPlaceholderText(tr("users.placeholder.password"))
        self._uf_password.setEchoMode(QLineEdit.EchoMode.Password)
        create_layout.addWidget(self._uf_password)

        self._uf_is_admin = QCheckBox(tr("users.admin"))
        create_layout.addWidget(self._uf_is_admin)

        create_btn = QPushButton(tr("users.create"))
        create_btn.setObjectName("primaryBtn")
        create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        create_btn.clicked.connect(self._uf_add_user)
        create_layout.addWidget(create_btn)


        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.addWidget(list_card, 0, Qt.AlignmentFlag.AlignTop)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(16)
        right_col.addWidget(create_card, 0, Qt.AlignmentFlag.AlignTop)
        right_col.addWidget(mode_card, 0, Qt.AlignmentFlag.AlignTop)
        right_col.addStretch(1)

        columns.addLayout(left_col, 6)
        columns.addLayout(right_col, 5)
        v.addLayout(columns)

        v.addStretch()
        self._fs_layout.addWidget(body, stretch=1)

    def _rebuild_users_panel(self):
        """Rebuild the open users panel (_open_users_panel would close it)."""
        self._panel_mode = None
        self._open_users_panel()

    def _enable_single_user_mode(self):
        from src.auth_manager import AuthManager
        if not StyledMessageBox.question(
            self, tr("users.mode.title"), tr("users.mode.enable_single_confirm"),
            yes_text=tr("users.mode.enable_single"), no_text=tr("dialog.cancel")
        ):
            return
        try:
            # Same account id and encryption key: self._mgr stays valid.
            self._user = AuthManager.enable_single_user_mode()
        except Exception as e:
            self._set_status(str(e))
            return
        self._rebuild_users_panel()

    def _migrate_single_user_to_multi(self):
        from src.auth_manager import AuthManager
        username = self._um_username.text().strip()
        pw = self._um_password.text()

        def _error(msg: str):
            self._um_error.setText(f"⚠ {msg}")
            self._um_error.setVisible(True)

        if len(username) < 3:
            _error(tr("users.username_min"))
            return
        if len(pw) < 8:  # NIST SP 800-63B minimum, as for every other account
            _error(tr("users.password_min"))
            return
        if pw != self._um_password2.text():
            _error(tr("login.passwords_differ"))
            self._um_password2.clear()
            self._um_password2.setFocus()
            return
        try:
            self._user = AuthManager.migrate_single_user_to_multi_user(username, pw)
        except Exception as e:
            _error(str(e))
            return
        StyledMessageBox.information(
            self, tr("users.mode.title"), tr("users.mode.multi_done", name=username)
        )
        self._rebuild_users_panel()

    def _uf_add_user(self):
        from src.auth_manager import AuthManager
        username = self._uf_username.text().strip()
        pw = self._uf_password.text()
        if not username or len(username) < 3:
            self._set_status(tr("users.username_min"))
            return
        if len(pw) < 8:  # SECURITY FIX: NIST SP 800-63B minimum is 8
            self._set_status(tr("users.password_min"))
            return
        try:
            AuthManager.register(username, pw, is_admin=self._uf_is_admin.isChecked())
            self._open_users_panel()
        except Exception as e:
            self._set_status(str(e))

    def _uf_delete_user(self, user_id: str, username: str):
        from src.auth_manager import AuthManager
        if StyledMessageBox.question(
            self, tr("users.delete.title"),
            tr("users.delete.confirm", name=username),
            yes_text="Löschen", no_text="Abbrechen"
        ):
            AuthManager.delete_user(user_id)
            self._open_users_panel()

    def _uf_reset_password(self, user_id: str, username: str):
        from src.auth_manager import AuthManager
        if not StyledMessageBox.question(
            self, tr("users.reset.title"),
            tr("users.reset.confirm", name=username),
            yes_text="Zurücksetzen", no_text="Abbrechen"
        ):
            return
        new_pw = AuthManager.admin_reset_password(user_id)
        if not new_pw:
            self._set_status(tr("users.not_found"))
            return
        StyledMessageBox.information(
            self, tr("users.reset.new_title"),
            tr("users.reset.new_msg", name=username, pw=new_pw)
        )

    # ------------------------------------------------------------------
    # Edit form (add + edit)
    # ------------------------------------------------------------------

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("rpSectionLabel")
        return lbl

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("fieldLabel")
        return lbl

    def _pill_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("connectionsBadge")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        return lbl

    def _divider(self) -> QFrame:
        f = QFrame()
        f.setObjectName("divider")
        f.setFixedHeight(1)
        return f

    def _build_edit_form(self, conn):
        """Build add/edit form inside right panel content area."""
        from src.drive_utils import (
            assignable_letters, get_available_drives, get_used_drives, norm_letter,
        )

        is_edit = conn is not None

        def _ef_field(label_text, input_widget):
            container = QFrame()
            container.setObjectName("rpInfoField")
            container.setFixedHeight(54)
            vl = QVBoxLayout(container)
            vl.setContentsMargins(16, 8, 16, 8)
            vl.setSpacing(4)
            lbl = QLabel(label_text.upper())
            lbl.setObjectName("rpFieldLabelCaps")
            vl.addWidget(lbl)
            vl.addWidget(input_widget)
            return container

        def _ef_field_pair(label1, widget1, label2, widget2, s1=2, s2=1):
            wrapper = QWidget()
            hl = QHBoxLayout(wrapper)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(8)
            hl.addWidget(_ef_field(label1, widget1), stretch=s1)
            hl.addWidget(_ef_field(label2, widget2), stretch=s2)
            return wrapper

        body = QWidget()
        body.setMinimumWidth(268)
        v = QVBoxLayout(body)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        # Status badge — identical to info panel so the transition feels seamless
        if is_edit:
            _theme = self._mgr.get_settings().theme or "dark"
            is_mounted = (conn.id in self._cards and self._cards[conn.id].is_mounted)
            v.addLayout(self._build_status_row(conn, is_mounted, _theme))
            v.addSpacing(8)

            # Mounted: connection fields are locked (see _ef_set_mount_lock);
            # the banner says why. Shown/hidden by _ef_set_mount_lock.
            self._ef_lock_banner = QLabel(tr("edit.mounted_banner"))
            self._ef_lock_banner.setWordWrap(True)
            self._ef_lock_banner.setStyleSheet(
                f"background-color: {accent_tone('rgba(0, 119, 182, 0.12)')};"
                f"border: 1px solid {accent_tone('rgba(0, 119, 182, 0.35)')};"
                "border-radius: 8px; padding: 8px 12px; font-size: 12px; font-weight: 600;"
            )
            self._ef_lock_banner.setVisible(False)
            v.addWidget(self._ef_lock_banner)

            # DEBUG mode: nothing is locked, but editing a mounted host is risky
            # (changing path/drive letter while mounted can leave things inconsistent).
            if is_mounted and self._mgr.get_settings().debug_mode:
                warn = QLabel(tr("edit.debug_warning"))
                warn.setWordWrap(True)
                warn.setStyleSheet(
                    "background-color: rgba(255, 180, 0, 0.15);"
                    "border: 1px solid rgba(255, 180, 0, 0.35);"
                    "border-radius: 8px; padding: 8px 12px;"
                    "color: #d89000; font-size: 12px; font-weight: 600;"
                )
                v.addWidget(warn)
                v.addSpacing(8)

        # Template selector (add mode only)
        self._ef_template_btn = None
        self._ef_templates = []
        if not is_edit:
            _templates = self._mgr.get_templates()
            if _templates:
                self._ef_templates = _templates
                v.addWidget(self._section_label(tr("addedit.section.template")))
                self._ef_template_btn = QPushButton(tr("addedit.template.none"))
                self._ef_template_btn.setObjectName("secondaryBtn")
                self._ef_template_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                self._ef_template_btn.clicked.connect(self._ef_show_template_dropdown)
                v.addWidget(self._ef_template_btn)
                _hint = QLabel(tr("addedit.template.hint"))
                _hint.setObjectName("hintLabel")
                v.addWidget(_hint)
                v.addSpacing(4)

        # General
        v.addWidget(self._section_label(tr("addedit.section.general")))
        self._ef_name = QLineEdit(conn.name if is_edit else "")
        self._ef_name.setPlaceholderText(tr("addedit.placeholder.name"))
        v.addWidget(_ef_field(tr("addedit.label.name"), self._ef_name))

        # Protocol: decides which transport the file browser uses and whether
        # the SSH-only fields below (key, drive letter, CLI, PuTTY) apply.
        self._ef_protocol = NoWheelComboBox()
        self._ef_protocol.addItem(tr("addedit.protocol.sftp"), PROTOCOL_SFTP)
        self._ef_protocol.addItem(tr("addedit.protocol.ftps"), PROTOCOL_FTPS)
        self._ef_protocol.addItem(tr("addedit.protocol.ftp"), PROTOCOL_FTP)
        if is_edit:
            idx = self._ef_protocol.findData(conn.protocol)
            if idx >= 0:
                self._ef_protocol.setCurrentIndex(idx)
        v.addWidget(_ef_field(tr("addedit.label.protocol"), self._ef_protocol))

        self._ef_host = QLineEdit(conn.host if is_edit else "")
        self._ef_host.setPlaceholderText("192.168.1.1")
        self._ef_port = NoWheelSpinBox()
        self._ef_port.setRange(1, 65535)
        self._ef_port.setValue(conn.port if is_edit else 22)
        v.addWidget(_ef_field_pair(tr("addedit.label.host"), self._ef_host,
                                   tr("addedit.label.port"), self._ef_port, 2, 1))

        self._ef_user = QLineEdit(conn.user if is_edit else "")
        self._ef_user.setPlaceholderText("root")
        v.addWidget(_ef_field(tr("addedit.label.user"), self._ef_user))

        # Auth
        v.addSpacing(4)
        v.addWidget(self._section_label(tr("addedit.section.auth")))
        self._ef_auth = NoWheelComboBox()
        self._ef_auth.addItem(tr("addedit.auth.password"), "password")
        self._ef_auth.addItem(tr("addedit.auth.key"), "key")
        self._ef_auth.addItem(tr("addedit.auth.ask"), "ask")
        if is_edit:
            idx = self._ef_auth.findData(conn.auth_method)
            if idx >= 0:
                self._ef_auth.setCurrentIndex(idx)
        v.addWidget(_ef_field(tr("addedit.label.method"), self._ef_auth))

        self._ef_pw = QLineEdit(conn.password if is_edit else "")
        self._ef_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._ef_pw.setPlaceholderText("••••••••")
        self._ef_pw.setStyleSheet("font-size: 8px; letter-spacing: 2px;")
        v.addWidget(_ef_field(tr("addedit.label.password"), self._ef_pw))

        key_container = QWidget()
        key_hl = QHBoxLayout(key_container)
        key_hl.setContentsMargins(0, 0, 0, 0)
        key_hl.setSpacing(6)
        self._ef_key = QLineEdit(conn.key_path if is_edit else "")
        self._ef_key.setPlaceholderText("C:/Users/user/.ssh/id_rsa")
        key_hl.addWidget(self._ef_key, stretch=1)
        self._ef_key_browse_btn = QPushButton("…")
        self._ef_key_browse_btn.setFixedWidth(28)
        self._ef_key_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ef_key_browse_btn.clicked.connect(self._ef_browse_key)
        key_hl.addWidget(self._ef_key_browse_btn)
        self._ef_key_field = _ef_field(tr("addedit.label.key"), key_container)
        v.addWidget(self._ef_key_field)

        # FTP options — only meaningful for FTP/FTPS, hidden for SFTP
        self._ef_ftp_widget = QWidget()
        ftp_v = QVBoxLayout(self._ef_ftp_widget)
        ftp_v.setContentsMargins(0, 4, 0, 0)
        ftp_v.setSpacing(6)
        ftp_v.addWidget(self._section_label(tr("addedit.section.ftp")))

        self._ef_ftp_plain_warning = QLabel(tr("addedit.ftp.plain_warning"))
        self._ef_ftp_plain_warning.setWordWrap(True)
        self._ef_ftp_plain_warning.setStyleSheet(
            "background-color: rgba(255, 180, 0, 0.15);"
            "border: 1px solid rgba(255, 180, 0, 0.35);"
            "border-radius: 8px; padding: 8px 12px;"
            "color: #d89000; font-size: 12px; font-weight: 600;"
        )
        ftp_v.addWidget(self._ef_ftp_plain_warning)

        self._ef_ftp_implicit = QCheckBox(tr("addedit.ftp.implicit"))
        self._ef_ftp_implicit.setChecked(conn.ftp_implicit_tls if is_edit else False)
        self._ef_ftp_implicit.toggled.connect(self._ef_on_protocol_changed)
        self._ef_ftp_implicit_hint = self._field_label(tr("addedit.ftp.implicit.hint"))
        self._ef_ftp_implicit_hint.setWordWrap(True)
        ftp_v.addWidget(self._ef_ftp_implicit)
        ftp_v.addWidget(self._ef_ftp_implicit_hint)

        self._ef_ftp_verify = QCheckBox(tr("addedit.ftp.verify_cert"))
        self._ef_ftp_verify.setChecked(conn.ftp_verify_cert if is_edit else True)
        self._ef_ftp_verify_hint = self._field_label(tr("addedit.ftp.verify_cert.hint"))
        self._ef_ftp_verify_hint.setWordWrap(True)
        ftp_v.addWidget(self._ef_ftp_verify)
        ftp_v.addWidget(self._ef_ftp_verify_hint)

        self._ef_ftp_passive = QCheckBox(tr("addedit.ftp.passive"))
        self._ef_ftp_passive.setChecked(conn.ftp_passive if is_edit else True)
        _passive_hint = self._field_label(tr("addedit.ftp.passive.hint"))
        _passive_hint.setWordWrap(True)
        ftp_v.addWidget(self._ef_ftp_passive)
        ftp_v.addWidget(_passive_hint)

        _ftp_hint = self._field_label(tr("addedit.ftp.hint"))
        _ftp_hint.setWordWrap(True)
        ftp_v.addWidget(_ftp_hint)
        v.addWidget(self._ef_ftp_widget)

        # Path & Drive
        v.addSpacing(4)
        v.addWidget(self._section_label(tr("addedit.section.path")))
        self._ef_path = QLineEdit(conn.remote_path if is_edit else "/")
        self._ef_path.setPlaceholderText("/home/user")
        self._ef_drive = NoWheelComboBox()
        used = [c.drive_letter for c in self._mgr.get_all()
                if not c.is_ftp and (not is_edit or c.id != conn.id)]
        if self._mgr.get_settings().allow_shared_drive_letters:
            # Letters may be shared: every letter, whoever else uses it. A
            # taken letter is resolved when mounting.
            letters = assignable_letters()
        else:
            letters = get_available_drives(exclude=used)
        own = norm_letter(conn.drive_letter) if is_edit else None
        if own and own not in letters:
            letters.append(own)     # the host's own letter is always offered
        for letter in sorted(set(letters)):
            self._ef_drive.addItem(letter, letter)
        if own:
            self._ef_drive.setCurrentIndex(self._ef_drive.findData(own))
        else:
            # New host: the first letter that is free and not used by a host.
            busy = set(get_used_drives()) | {norm_letter(u) for u in used}
            free = [l for l in sorted(set(letters)) if l not in busy]
            if free:
                self._ef_drive.setCurrentIndex(self._ef_drive.findData(free[0]))
        # Same layout as _ef_field_pair, but the drive half stays addressable so
        # it can be hidden for FTP connections (they are never mounted).
        path_row = QWidget()
        path_hl = QHBoxLayout(path_row)
        path_hl.setContentsMargins(0, 0, 0, 0)
        path_hl.setSpacing(8)
        self._ef_drive_field = _ef_field(tr("addedit.label.drive"), self._ef_drive)
        path_hl.addWidget(_ef_field(tr("addedit.label.path"), self._ef_path), stretch=3)
        path_hl.addWidget(self._ef_drive_field, stretch=1)
        v.addWidget(path_row)

        # CLI
        v.addSpacing(4)
        self._ef_cli_section = self._section_label(tr("addedit.section.cli"))
        v.addWidget(self._ef_cli_section)
        self._ef_cli_cb = QCheckBox(tr("addedit.cli.enable"))
        self._ef_cli_cb.setChecked(conn.cli_access_enabled if is_edit else False)
        self._ef_cli_cb.toggled.connect(self._ef_cli_toggle)
        v.addWidget(self._ef_cli_cb)

        self._ef_cli_widget = QWidget()
        cli_inner = QVBoxLayout(self._ef_cli_widget)
        cli_inner.setContentsMargins(0, 4, 0, 0)
        cli_inner.setSpacing(4)
        cli_key_row = QHBoxLayout()
        cli_key_row.setSpacing(4)
        self._ef_cli_key = QLineEdit(conn.cli_access_key or "" if is_edit else "")
        self._ef_cli_key.setReadOnly(True)
        self._ef_cli_key.setPlaceholderText(tr("addedit.cli.none"))
        cli_key_row.addWidget(self._ef_cli_key, stretch=1)
        self._ef_cli_copy_btn = QPushButton()
        self._ef_cli_copy_btn.setObjectName("rpHeaderBtn")
        self._ef_cli_copy_btn.setFixedSize(32, 32)
        self._ef_cli_copy_btn.setIcon(svg_icon("copy", "#aab4c4", 15))
        self._ef_cli_copy_btn.setIconSize(QSize(15, 15))
        self._ef_cli_copy_btn.setToolTip(tr("addedit.cli.copy"))
        self._ef_cli_copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ef_cli_copy_btn.clicked.connect(self._ef_copy_cli_key)
        cli_key_row.addWidget(self._ef_cli_copy_btn)
        self._ef_cli_gen_btn = QPushButton()
        self._ef_cli_gen_btn.setObjectName("rpHeaderBtn")
        self._ef_cli_gen_btn.setFixedSize(32, 32)
        self._ef_cli_gen_btn.setIcon(svg_icon("refresh", "#aab4c4", 15))
        self._ef_cli_gen_btn.setIconSize(QSize(15, 15))
        self._ef_cli_gen_btn.setToolTip(tr("addedit.cli.generate"))
        self._ef_cli_gen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ef_cli_gen_btn.clicked.connect(self._ef_generate_new_cli_key)
        cli_key_row.addWidget(self._ef_cli_gen_btn)
        cli_inner.addLayout(cli_key_row)
        self._ef_cli_widget.setVisible(conn.cli_access_enabled if is_edit else False)
        v.addWidget(self._ef_cli_widget)

        if is_edit and conn.cli_access_enabled and not conn.cli_access_key:
            self._ef_generate_new_cli_key()

        # PuTTY (only when enabled globally)
        s = self._mgr.get_settings()
        self._ef_putty_widget = None
        if s.use_putty:
            self._ef_putty_widget = QWidget()
            putty_v = QVBoxLayout(self._ef_putty_widget)
            putty_v.setContentsMargins(0, 4, 0, 0)
            putty_v.setSpacing(6)
            putty_v.addWidget(self._section_label("PuTTY"))
            putty_container = QWidget()
            putty_hl = QHBoxLayout(putty_container)
            putty_hl.setContentsMargins(0, 0, 0, 0)
            putty_hl.setSpacing(6)
            self._ef_putty_key = QLineEdit(conn.putty_key_path if is_edit else "")
            self._ef_putty_key.setPlaceholderText("C:/Users/user/.ssh/id_rsa.ppk")
            putty_hl.addWidget(self._ef_putty_key, stretch=1)
            putty_browse_btn = QPushButton("…")
            putty_browse_btn.setFixedWidth(28)
            putty_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            putty_browse_btn.clicked.connect(self._ef_browse_putty_key)
            putty_hl.addWidget(putty_browse_btn)
            putty_v.addWidget(_ef_field(tr("addedit.putty_key.label"), putty_container))
            putty_v.addWidget(self._field_label(tr("addedit.putty_key.hint")))
            v.addWidget(self._ef_putty_widget)

        # Groups/Tags
        v.addSpacing(4)
        v.addWidget(self._section_label(tr("addedit.section.groups")))
        self._ef_groups = QLineEdit(conn.groups if is_edit else "")
        self._ef_groups.setPlaceholderText(tr("addedit.placeholder.groups"))
        v.addWidget(_ef_field(tr("addedit.label.groups"), self._ef_groups))
        v.addWidget(self._field_label(tr("addedit.groups.hint")))

        # Template Option (nur im Add-Modus oder bei Bearbeitung sichtbar)
        v.addSpacing(4)
        v.addWidget(self._section_label(tr("addedit.section.template_options")))
        # Editing a host: the box saves a template COPY; the host stays as it is.
        _copy = is_edit and not conn.is_template
        self._ef_template_cb = QCheckBox(tr("addedit.template.save_copy") if _copy
                                         else tr("addedit.template.save_as_template"))
        self._ef_template_cb.setChecked(conn.is_template if is_edit else False)
        self._ef_template_cb.setToolTip(tr("addedit.template.save_copy.hint") if _copy
                                        else tr("addedit.template.save_as_template.hint"))
        v.addWidget(self._ef_template_cb)

        v.addStretch()
        self._rp_layout.addWidget(body)
        self._ef_conn = conn
        for w in (self._ef_name, self._ef_host, self._ef_user):
            w.textChanged.connect(self._validate_edit_form)
        # Wire up protocol switching only after every field exists, then apply
        # the initial visibility for the loaded/default protocol.
        self._ef_protocol.currentIndexChanged.connect(self._ef_on_protocol_changed)
        self._ef_apply_protocol_visibility()
        if is_edit:
            self._ef_set_mount_lock(self._ef_should_lock(conn.id))
        self._ef_initial_snapshot = self._snapshot_form()
        self._validate_edit_form()
        self._setup_edit_tab_order()
        QTimer.singleShot(0, self._ef_name.setFocus)

    # ── Editing a mounted host ───────────────────────────────────────────
    # The running mount depends on these; everything else (name, CLI access,
    # PuTTY key, groups, template copy) stays editable.
    _EF_MOUNT_LOCKED_WIDGETS = (
        "_ef_protocol", "_ef_host", "_ef_port", "_ef_user", "_ef_auth", "_ef_pw",
        "_ef_key", "_ef_key_browse_btn", "_ef_ftp_implicit", "_ef_ftp_verify",
        "_ef_ftp_passive", "_ef_path", "_ef_drive",
    )
    _EF_MOUNT_LOCKED_FIELDS = (
        "protocol", "host", "port", "user", "auth_method", "password", "key_path",
        "ftp_implicit_tls", "ftp_verify_cert", "ftp_passive", "remote_path", "drive_letter",
    )

    def _ef_should_lock(self, conn_id: str) -> bool:
        card = self._cards.get(conn_id)
        return bool(card and card.is_mounted and not self._mgr.get_settings().debug_mode)

    def _ef_set_mount_lock(self, locked: bool):
        """Grey out the connection fields while the host is mounted; hovering
        one (or its field frame) says why."""
        self._ef_mount_locked = locked
        tip = tr("edit.locked_field") if locked else ""
        for name in self._EF_MOUNT_LOCKED_WIDGETS:
            w = getattr(self, name, None)
            if w is None:
                continue
            try:
                w.setEnabled(not locked)
                w.setToolTip(tip)
                frame = w.parentWidget()
                for _ in range(3):
                    if frame is None or frame.objectName() == "rpInfoField":
                        break
                    frame = frame.parentWidget()
                if frame is not None and frame.objectName() == "rpInfoField":
                    frame.setToolTip(tip)
            except RuntimeError:
                continue    # widget already deleted
        banner = getattr(self, "_ef_lock_banner", None)
        if banner is not None:
            try:
                banner.setVisible(locked)
            except RuntimeError:
                pass

    # ── Protocol-dependent form behaviour ────────────────────────────────

    def _ef_current_protocol(self) -> str:
        return self._safe_current_data("_ef_protocol", PROTOCOL_SFTP)

    def _ef_on_protocol_changed(self, *_args):
        """Protocol (or implicit-TLS) changed: adjust port and field visibility."""
        self._ef_sync_default_port()
        self._ef_apply_protocol_visibility()

    def _ef_sync_default_port(self):
        """
        Move the port to the new protocol's default.

        Only standard ports are rewritten — a custom port the user typed in
        stays untouched.
        """
        spin = getattr(self, "_ef_port", None)
        if spin is None:
            return
        try:
            current = int(spin.value())
            if current not in (21, 22, 990):
                return
            spin.setValue(default_port(
                self._ef_current_protocol(),
                self._safe_bool_checked("_ef_ftp_implicit", False),
            ))
        except RuntimeError:
            pass

    def _ef_apply_protocol_visibility(self):
        """Show only the fields that apply to the selected protocol."""
        protocol = self._ef_current_protocol()
        is_ftp = protocol in (PROTOCOL_FTP, PROTOCOL_FTPS)
        is_tls = protocol == PROTOCOL_FTPS

        widgets = (
            # (attribute, visible?)
            ("_ef_ftp_widget", is_ftp),
            ("_ef_ftp_plain_warning", protocol == PROTOCOL_FTP),
            ("_ef_ftp_implicit", is_tls),
            ("_ef_ftp_implicit_hint", is_tls),
            ("_ef_ftp_verify", is_tls),
            ("_ef_ftp_verify_hint", is_tls),
            # SSH-only fields
            ("_ef_key_field", not is_ftp),
            ("_ef_drive_field", not is_ftp),
            ("_ef_cli_section", not is_ftp),
            ("_ef_cli_cb", not is_ftp),
            ("_ef_putty_widget", not is_ftp),
        )
        for attr, visible in widgets:
            widget = getattr(self, attr, None)
            if widget is None:
                continue
            try:
                widget.setVisible(visible)
            except RuntimeError:
                pass

        # FTP authenticates with user/password only — key auth would silently
        # log in with an empty password, so move that selection to "password".
        auth = getattr(self, "_ef_auth", None)
        if is_ftp and auth is not None:
            try:
                if auth.currentData() == "key":
                    idx = auth.findData("password")
                    if idx >= 0:
                        auth.setCurrentIndex(idx)
            except RuntimeError:
                pass

        # The CLI key row follows its checkbox, but never shows for FTP.
        cli_widget = getattr(self, "_ef_cli_widget", None)
        if cli_widget is not None:
            try:
                cli_widget.setVisible(
                    (not is_ftp) and self._safe_bool_checked("_ef_cli_cb", False)
                )
            except RuntimeError:
                pass

    def _setup_edit_tab_order(self):
        chain = [
            self._ef_name, self._ef_protocol, self._ef_host, self._ef_port, self._ef_user,
            self._ef_auth, self._ef_pw, self._ef_key,
            self._ef_path, self._ef_drive,
            self._ef_cli_cb, self._ef_cli_key,
            self._ef_groups, self._ef_template_cb
        ]
        if getattr(self, "_ef_putty_key", None) is not None:
            chain.insert(-2, self._ef_putty_key)
        for i in range(len(chain) - 1):
            self.setTabOrder(chain[i], chain[i + 1])

    def _ef_show_template_dropdown(self):
        templates = self._mgr.get_templates()
        if not templates:
            return
        theme = self._mgr.get_settings().theme or "dark"
        btn = self._ef_template_btn
        if btn is None:
            return
        popup = _TemplateDropdown(templates, theme, btn)
        popup.template_selected.connect(self._on_ef_template_selected)
        popup.template_deleted.connect(self._on_ef_template_deleted)
        global_pos = btn.mapToGlobal(btn.rect().bottomLeft())
        popup.move(global_pos)
        popup.show()

    def _next_unique_name(self, base: str) -> str:
        """Return base if unused, else base#2, base#3, … (first free slot)."""
        existing = {c.name.lower() for c in self._mgr.get_all(include_templates=False)}
        if base.lower() not in existing:
            return base
        n = 2
        while f"{base}#{n}".lower() in existing:
            n += 1
        return f"{base}#{n}"

    def _on_ef_template_selected(self, conn):
        # Name: template name, auto-incremented if already taken
        unique_name = self._next_unique_name(conn.name)
        if getattr(self, "_ef_name", None):
            try:
                self._ef_name.setText(unique_name)
            except RuntimeError:
                pass

        # Host
        if getattr(self, "_ef_host", None):
            try:
                self._ef_host.setText(conn.host)
            except RuntimeError:
                pass

        # Protocol (before the port, so the port from the template wins over
        # the default port the protocol switch would otherwise apply)
        if getattr(self, "_ef_protocol", None):
            try:
                idx = self._ef_protocol.findData(conn.protocol)
                if idx >= 0:
                    self._ef_protocol.setCurrentIndex(idx)
                if getattr(self, "_ef_ftp_implicit", None):
                    self._ef_ftp_implicit.setChecked(bool(conn.ftp_implicit_tls))
                if getattr(self, "_ef_ftp_passive", None):
                    self._ef_ftp_passive.setChecked(bool(conn.ftp_passive))
                if getattr(self, "_ef_ftp_verify", None):
                    self._ef_ftp_verify.setChecked(bool(conn.ftp_verify_cert))
            except RuntimeError:
                pass

        # Port
        if getattr(self, "_ef_port", None):
            try:
                self._ef_port.setValue(conn.port or 22)
            except RuntimeError:
                pass

        # User
        if getattr(self, "_ef_user", None):
            try:
                self._ef_user.setText(conn.user)
            except RuntimeError:
                pass

        # Auth method (no password / key paths)
        if getattr(self, "_ef_auth", None):
            try:
                idx = self._ef_auth.findData(conn.auth_method)
                if idx >= 0:
                    self._ef_auth.setCurrentIndex(idx)
            except RuntimeError:
                pass

        # Remote path
        if getattr(self, "_ef_path", None):
            try:
                self._ef_path.setText(conn.remote_path or "/")
            except RuntimeError:
                pass

        # Groups
        if getattr(self, "_ef_groups", None):
            try:
                self._ef_groups.setText(conn.groups or "")
            except RuntimeError:
                pass

        # Update dropdown button label to template name
        if self._ef_template_btn:
            try:
                self._ef_template_btn.setText(conn.name or conn.host)
            except RuntimeError:
                pass

        self._validate_edit_form()

    def _on_ef_template_deleted(self, conn_id: str):
        conn = self._mgr.get_by_id(conn_id)
        name = conn.name if conn else conn_id
        confirmed = StyledMessageBox.question(
            self,
            tr("addedit.template.delete.title"),
            tr("addedit.template.delete.confirm", name=name),
        )
        if not confirmed:
            return
        self._mgr.delete(conn_id)
        self._ef_templates = self._mgr.get_templates()
        if not self._ef_templates and self._ef_template_btn:
            try:
                self._ef_template_btn.setVisible(False)
            except RuntimeError:
                pass

    def _ef_browse_key(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("addedit.select_key"), "", "All Files (*)"
        )
        if path and getattr(self, "_ef_key", None) is not None:
            try:
                self._ef_key.setText(path)
            except RuntimeError:
                pass

    def _ef_browse_putty_key(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("addedit.putty_key.select"), "", "PuTTY Private Key (*.ppk)"
        )
        if path and getattr(self, "_ef_putty_key", None) is not None:
            try:
                self._ef_putty_key.setText(path)
            except RuntimeError:
                pass

    def _ef_cli_toggle(self, checked: bool):
        if getattr(self, "_ef_cli_widget", None) is None or getattr(self, "_ef_cli_key", None) is None:
            return
        try:
            self._ef_cli_widget.setVisible(checked)
            is_empty = not self._ef_cli_key.text()
        except RuntimeError:
            return
        if checked and is_empty:
            self._ef_generate_new_cli_key()

    def _ef_generate_new_cli_key(self):
        import secrets as _secrets
        if getattr(self, "_ef_cli_key", None) is None:
            return
        try:
            self._ef_cli_key.setText(_secrets.token_hex(64))
        except RuntimeError:
            pass

    def _ef_copy_cli_key(self):
        if getattr(self, "_ef_cli_key", None) is None:
            return
        try:
            key = self._ef_cli_key.text()
        except RuntimeError:
            return
        if not key:
            return

        QApplication.clipboard().setText(key)
        if getattr(self, "_ef_cli_copy_btn", None) is None:
            return
        try:
            self._ef_cli_copy_btn.setIcon(svg_icon("check", "#00d464", 15))
        except RuntimeError:
            return
        QTimer.singleShot(
            1500,
            self._ef_restore_copy_icon
        )

    def _ef_restore_copy_icon(self):
        btn = getattr(self, "_ef_cli_copy_btn", None)
        if btn is None:
            return
        try:
            btn.setIcon(svg_icon("copy", "#aab4c4", 15))
        except RuntimeError:
            pass

    def _install_shortcuts(self):
        mapping = [
            ("Ctrl+S", self._shortcut_save),
            ("Esc", self._shortcut_escape),
            ("Ctrl+N", self._shortcut_add),
            ("Ctrl+E", self._shortcut_edit),
            ("Delete", self._shortcut_delete),
        ]
        for key, slot in mapping:
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(slot)
            self._shortcuts.append(sc)

    def _shortcut_save(self):
        if self._panel_mode in (_PANEL_EDIT, _PANEL_ADD):
            self._on_rp_save()

    def _shortcut_escape(self):
        if self._panel_mode in (_PANEL_EDIT, _PANEL_ADD):
            self._on_rp_cancel()
        elif self._panel_mode in (_PANEL_INFO, _PANEL_SYSINFO):
            self._close_right_panel()

    def _shortcut_add(self):
        self._open_add_panel()

    def _shortcut_edit(self):
        target_id = self._panel_conn_id or self._selected_id
        if target_id:
            self._open_edit_panel(target_id)

    def _shortcut_delete(self):
        if self._panel_mode == _PANEL_EDIT and self._panel_conn_id:
            self._on_delete()

    # ------------------------------------------------------------------
    # Settings form
    # ------------------------------------------------------------------

    def _build_settings_form(self):
        """Build the settings form inside the fullscreen panel."""
        s = self._mgr.get_settings()

        # ── helpers ───────────────────────────────────────────────────────
        def _group_card() -> tuple[QFrame, QVBoxLayout]:
            card = QFrame()
            card.setObjectName("settingsGroupCard")
            vl = QVBoxLayout(card)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(0)
            return card, vl

        def _inner_sep() -> QFrame:
            f = QFrame()
            f.setObjectName("rowSep")
            f.setFixedHeight(1)
            return f

        def _row_combo(label_text: str, combo: QWidget) -> QWidget:
            w = QWidget()
            w.setObjectName("settingsRow")
            hl = QHBoxLayout(w)
            hl.setContentsMargins(16, 11, 16, 11)
            hl.setSpacing(0)
            lbl = QLabel(label_text)
            lbl.setObjectName("rowLabel")
            hl.addWidget(lbl, stretch=1)
            hl.addWidget(combo)
            return w

        def _row_check(checkbox: QCheckBox, hint_text: str = "") -> QWidget:
            w = QWidget()
            w.setObjectName("settingsRow")
            vl = QVBoxLayout(w)
            vl.setContentsMargins(16, 11, 16, 11)
            vl.setSpacing(4)
            vl.addWidget(checkbox)
            if hint_text:
                hl = QLabel(hint_text)
                hl.setObjectName("hintLabel")
                hl.setWordWrap(True)
                hl.setContentsMargins(24, 0, 0, 0)
                vl.addWidget(hl)
            return w

        def _row_action(button: QPushButton, desc_text: str) -> QWidget:
            w = QWidget()
            w.setObjectName("settingsRow")
            vl = QVBoxLayout(w)
            vl.setContentsMargins(16, 11, 16, 13)
            vl.setSpacing(11)
            desc = QLabel(desc_text)
            desc.setObjectName("hintLabel")
            desc.setWordWrap(True)
            vl.addWidget(desc)
            vl.addWidget(button)
            return w

        def _section_hdr(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("sectionLabel")
            return lbl

        def _hint_row(text: str) -> QWidget:
            w = QWidget()
            w.setObjectName("settingsRow")
            hl = QHBoxLayout(w)
            hl.setContentsMargins(16, 6, 16, 8)
            lbl = QLabel(text)
            lbl.setObjectName("hintLabel")
            lbl.setWordWrap(True)
            hl.addWidget(lbl)
            return w

        # ── root scroll container ─────────────────────────────────────────
        body = QWidget()
        body.setObjectName("fullscreenForm")
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        v = QVBoxLayout(body)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(6)

        # ── APPEARANCE ────────────────────────────────────────────────────
        v.addWidget(_section_hdr("APPEARANCE"))
        v.addSpacing(4)

        self._sf_lang = NoWheelComboBox()
        self._sf_lang.setFixedWidth(180)
        for code in available_languages():
            self._sf_lang.addItem(_LANG_LABELS.get(code, code), code)
        idx = self._sf_lang.findData(getattr(s, 'language', 'en') or 'en')
        if idx >= 0:
            self._sf_lang.setCurrentIndex(idx)

        self._sf_theme = NoWheelComboBox()
        self._sf_theme.setFixedWidth(180)
        self._sf_theme.addItem(tr("settings.theme.dark"), "dark")
        self._sf_theme.addItem(tr("settings.theme.gray"), "gray")
        self._sf_theme.addItem(tr("settings.theme.light"), "light")
        idx = self._sf_theme.findData(getattr(s, 'theme', 'dark') or 'dark')
        if idx >= 0:
            self._sf_theme.setCurrentIndex(idx)

        # Accent colour: swatch button opens the picker, "Standard" resets.
        self._sf_accent = normalize_hex(getattr(s, "accent_color", "")) or DEFAULT_ACCENT
        self._sf_accent_btn = QPushButton()
        self._sf_accent_btn.setObjectName("settingsActionBtn")
        self._sf_accent_btn.setFixedWidth(120)
        self._sf_accent_btn.setMinimumHeight(32)
        self._sf_accent_btn.setIconSize(QSize(14, 14))
        self._sf_accent_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sf_accent_btn.setToolTip(tr("colorpicker.title"))
        self._sf_accent_btn.clicked.connect(self._sf_pick_accent)
        self._sf_accent_reset_btn = QPushButton(tr("settings.accent.reset"))
        self._sf_accent_reset_btn.setObjectName("settingsActionBtn")
        self._sf_accent_reset_btn.setMinimumHeight(32)
        self._sf_accent_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sf_accent_reset_btn.setToolTip(DEFAULT_ACCENT)
        self._sf_accent_reset_btn.clicked.connect(
            lambda: self._sf_set_accent(DEFAULT_ACCENT, preview=True))
        accent_box = QWidget()
        accent_hl = QHBoxLayout(accent_box)
        accent_hl.setContentsMargins(0, 0, 0, 0)
        accent_hl.setSpacing(8)
        accent_hl.addWidget(self._sf_accent_reset_btn)
        accent_hl.addWidget(self._sf_accent_btn)
        self._sf_update_accent_ui()

        app_card, app_vl = _group_card()
        app_vl.addWidget(_row_combo(tr("settings.theme.label"), self._sf_theme))
        app_vl.addWidget(_inner_sep())
        app_vl.addWidget(_row_combo(tr("settings.accent.label"), accent_box))
        app_vl.addWidget(_inner_sep())
        app_vl.addWidget(_row_combo(tr("settings.language.label"), self._sf_lang))
        app_vl.addWidget(_hint_row(tr("settings.language.restart")))
        v.addWidget(app_card)
        v.addSpacing(14)

        # ── GENERAL ───────────────────────────────────────────────────────
        v.addWidget(_section_hdr(tr("settings.section.general")))
        v.addSpacing(4)

        self._sf_start = QCheckBox(tr("settings.start_with_windows"))
        self._sf_start.setChecked(s.start_with_windows)
        self._sf_tray = QCheckBox(tr("settings.minimize_to_tray"))
        self._sf_tray.setChecked(s.minimize_to_tray)
        self._sf_admin = QCheckBox(tr("settings.require_admin"))
        self._sf_admin.setChecked(s.require_admin)
        self._sf_telemetry = QCheckBox(tr("settings.telemetry"))
        self._sf_telemetry.setChecked(getattr(s, "telemetry_enabled", False))

        self._sf_shortcut_btn = QPushButton(tr("settings.create_shortcut"))
        self._sf_shortcut_btn.setObjectName("settingsActionBtn")
        self._sf_shortcut_btn.setFixedWidth(170)
        self._sf_shortcut_btn.setMinimumHeight(32)
        self._sf_shortcut_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sf_shortcut_btn.clicked.connect(self._sf_create_shortcut)

        gen_card, gen_vl = _group_card()
        gen_vl.addWidget(_row_check(self._sf_start))
        gen_vl.addWidget(_inner_sep())
        gen_vl.addWidget(_row_check(self._sf_tray))
        gen_vl.addWidget(_inner_sep())
        gen_vl.addWidget(_row_check(self._sf_admin))
        gen_vl.addWidget(_inner_sep())
        gen_vl.addWidget(_row_check(self._sf_telemetry, tr("settings.telemetry.hint")))
        gen_vl.addWidget(_inner_sep())
        gen_vl.addWidget(_row_action(self._sf_shortcut_btn, tr("settings.create_shortcut.hint")))
        v.addWidget(gen_card)
        v.addSpacing(14)

        # ── UPDATES ───────────────────────────────────────────────────────
        v.addWidget(_section_hdr(tr("settings.section.updates")))
        v.addSpacing(4)

        self._sf_update_btn = QPushButton(tr("settings.check_updates"))
        self._sf_update_btn.setObjectName("settingsActionBtn")
        self._sf_update_btn.setProperty("btn_type", "primary")
        self._sf_update_btn.setFixedWidth(170)
        self._sf_update_btn.setMinimumHeight(32)
        self._sf_update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sf_update_btn.clicked.connect(self._sf_check_updates)

        upd_card, upd_vl = _group_card()
        upd_vl.addWidget(_row_action(self._sf_update_btn, tr("settings.updates.hint")))
        v.addWidget(upd_card)
        v.addSpacing(14)

        # ── MOUNT STATUS ──────────────────────────────────────────────────
        v.addWidget(_section_hdr(tr("settings.section.mount")))
        v.addSpacing(4)

        self._sf_interval = NoWheelSpinBox()
        self._sf_interval.setRange(5, 300)
        self._sf_interval.setValue(s.check_interval_seconds)
        self._sf_interval.setFixedWidth(72)
        self._sf_auto_reconnect = QCheckBox(tr("settings.auto_reconnect"))
        self._sf_auto_reconnect.setChecked(getattr(s, "auto_reconnect", False))
        self._sf_auto_remount = QCheckBox(tr("settings.auto_remount"))
        self._sf_auto_remount.setChecked(getattr(s, "auto_remount_on_lost", True))
        self._sf_sshfs_disable_cache = QCheckBox(tr("settings.sshfs_disable_cache"))
        self._sf_sshfs_disable_cache.setChecked(getattr(s, "sshfs_disable_cache", False))
        self._sf_shared_letters = QCheckBox(tr("settings.shared_letters"))
        self._sf_shared_letters.setChecked(getattr(s, "allow_shared_drive_letters", False))
        self._sf_auto_pick_letter = QCheckBox(tr("settings.auto_pick_letter"))
        self._sf_auto_pick_letter.setChecked(
            self._sf_shared_letters.isChecked() and getattr(s, "auto_pick_free_drive_letter", False))
        # Auto-pick only makes sense while letters may be shared.
        self._sf_auto_pick_letter.setEnabled(self._sf_shared_letters.isChecked())

        def _on_shared_letters_toggled(on: bool):
            self._sf_auto_pick_letter.setEnabled(on)
            if not on:
                self._sf_auto_pick_letter.setChecked(False)
        self._sf_shared_letters.toggled.connect(_on_shared_letters_toggled)

        mnt_card, mnt_vl = _group_card()
        mnt_vl.addWidget(_row_combo(tr("settings.check_interval"), self._sf_interval))
        mnt_vl.addWidget(_inner_sep())
        mnt_vl.addWidget(_row_check(self._sf_auto_reconnect))
        mnt_vl.addWidget(_inner_sep())
        mnt_vl.addWidget(_row_check(self._sf_auto_remount))
        mnt_vl.addWidget(_inner_sep())
        mnt_vl.addWidget(_row_check(self._sf_sshfs_disable_cache, tr("settings.sshfs_disable_cache.hint")))
        mnt_vl.addWidget(_inner_sep())
        mnt_vl.addWidget(_row_check(self._sf_shared_letters, tr("settings.shared_letters.hint")))
        mnt_vl.addWidget(_inner_sep())
        mnt_vl.addWidget(_row_check(self._sf_auto_pick_letter, tr("settings.auto_pick_letter.hint")))
        v.addWidget(mnt_card)
        v.addSpacing(14)

        # ── SSH TERMINAL ──────────────────────────────────────────────────
        v.addWidget(_section_hdr(tr("settings.section.terminal")))
        v.addSpacing(4)

        _tc = getattr(s, 'terminal_client', 'xterm') or 'xterm'

        self._sf_term_ssh   = QRadioButton(tr("settings.terminal_client.ssh"))
        self._sf_term_putty = QRadioButton(tr("settings.terminal_client.putty"))
        self._sf_term_xterm = QRadioButton(tr("settings.terminal_client.xterm"))
        self._sf_term_ssh.setChecked(_tc == 'ssh')
        self._sf_term_putty.setChecked(_tc == 'putty')
        self._sf_term_xterm.setChecked(_tc == 'xterm')
        # Explicit group required because _row_check() wraps each button in its
        # own QWidget, breaking Qt's parent-based auto-grouping.
        from PyQt6.QtWidgets import QButtonGroup
        self._sf_term_group = QButtonGroup(self)
        self._sf_term_group.addButton(self._sf_term_ssh)
        self._sf_term_group.addButton(self._sf_term_putty)
        self._sf_term_group.addButton(self._sf_term_xterm)
        self._sf_term_group.buttonToggled.connect(self._sf_terminal_client_toggled)

        # Legacy alias so existing code that references _sf_putty still works
        self._sf_putty = self._sf_term_putty

        self._sf_putty_path = QLineEdit(getattr(s, 'putty_path', r"C:\Program Files\PuTTY\putty.exe"))
        self._sf_putty_path.setPlaceholderText(r"C:\Program Files\PuTTY\putty.exe")
        browse_p = QPushButton("…")
        browse_p.setObjectName("rpHeaderBtn")
        browse_p.setFixedWidth(36)
        browse_p.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_p.clicked.connect(self._sf_browse_putty)

        putty_path_row = QWidget()
        putty_path_row.setObjectName("settingsRow")
        pp_vl = QVBoxLayout(putty_path_row)
        pp_vl.setContentsMargins(16, 10, 16, 10)
        pp_vl.setSpacing(6)
        pp_lbl = QLabel(tr("settings.putty_path"))
        pp_lbl.setObjectName("rowLabel")
        pp_vl.addWidget(pp_lbl)
        pp_hl = QHBoxLayout()
        pp_hl.setContentsMargins(0, 0, 0, 0)
        pp_hl.setSpacing(6)
        pp_hl.addWidget(self._sf_putty_path, stretch=1)
        pp_hl.addWidget(browse_p)
        pp_vl.addLayout(pp_hl)
        hint2 = QLabel(tr("settings.putty_hint"))
        hint2.setObjectName("hintLabel")
        hint2.setWordWrap(True)
        pp_vl.addWidget(hint2)

        term_card, term_vl = _group_card()
        term_vl.addWidget(_row_check(self._sf_term_ssh))
        term_vl.addWidget(_inner_sep())
        term_vl.addWidget(_row_check(self._sf_term_putty))
        self._sf_putty_widget = putty_path_row
        self._sf_putty_widget.setVisible(_tc == 'putty')
        term_vl.addWidget(self._sf_putty_widget)

        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl as _QUrl
        self._sf_putty_download_lbl = QLabel(
            f'<a href="https://www.putty.org" style="color:{current_accent()};">'
            f'{tr("settings.putty_download_link")}</a>'
        )
        self._sf_putty_download_lbl.setObjectName("hintLabel")
        self._sf_putty_download_lbl.setContentsMargins(16, 0, 16, 8)
        self._sf_putty_download_lbl.setOpenExternalLinks(False)
        self._sf_putty_download_lbl.linkActivated.connect(
            lambda: QDesktopServices.openUrl(_QUrl("https://www.putty.org"))
        )
        self._sf_putty_download_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sf_putty_download_lbl.setVisible(_tc == 'putty')
        term_vl.addWidget(self._sf_putty_download_lbl)

        term_vl.addWidget(_inner_sep())
        term_vl.addWidget(_row_check(self._sf_term_xterm))
        v.addWidget(term_card)
        v.addSpacing(14)

        # ── SECURITY (only for OpenSSH / PuTTY) ───────────────────────────
        _show_sec = (_tc != 'xterm')
        self._sf_sec_header = _section_hdr(tr("settings.section.security"))
        self._sf_sec_header.setVisible(_show_sec)
        v.addWidget(self._sf_sec_header)
        _sec_spacing = v.count()  # index used to manage the spacing widget below
        self._sf_sec_spacing = QWidget()
        self._sf_sec_spacing.setFixedHeight(4)
        self._sf_sec_spacing.setVisible(_show_sec)
        v.addWidget(self._sf_sec_spacing)

        self._sf_security_level = NoWheelComboBox()
        self._sf_security_level.addItem(tr("settings.security.level.ask"), 0)
        self._sf_security_level.addItem(tr("settings.security.level.autologin"), 1)
        _cur_level = min(getattr(s, 'security_level', 0), 1)
        self._sf_security_level.setCurrentIndex(_cur_level)
        self._sf_security_level.setFixedWidth(260)

        self._sf_sec_warning = QLabel(tr("settings.security.warning.level1"))
        self._sf_sec_warning.setObjectName("errorLabel")
        self._sf_sec_warning.setWordWrap(True)
        self._sf_sec_warning.setContentsMargins(16, 6, 16, 10)

        sec_card, sec_vl = _group_card()
        sec_vl.addWidget(_row_combo(tr("settings.security.level.label"), self._sf_security_level))
        sec_vl.addWidget(self._sf_sec_warning)
        self._sf_sec_card = sec_card
        self._sf_sec_card.setVisible(_show_sec)
        v.addWidget(sec_card)
        self._sf_security_level.currentIndexChanged.connect(self._on_sf_security_changed)
        self._on_sf_security_changed(_cur_level)
        v.addSpacing(14)

        # ── DEVELOPER ─────────────────────────────────────────────────────
        v.addWidget(_section_hdr(tr("settings.section.developer")))
        v.addSpacing(4)

        self._sf_debug = QCheckBox(tr("settings.debug_mode"))
        self._sf_debug.setChecked(s.debug_mode)
        self._sf_debug.toggled.connect(self._sf_debug_toggled)

        fix_btn = QPushButton(tr("settings.fix_ghosts"))
        fix_btn.setObjectName("settingsActionBtn")
        fix_btn.setProperty("btn_type", "primary")
        fix_btn.setFixedWidth(170)
        fix_btn.setMinimumHeight(32)
        fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fix_btn.clicked.connect(self._sf_fix_ghosts)

        rst_btn = QPushButton(tr("settings.restart_explorer"))
        rst_btn.setObjectName("settingsActionBtn")
        rst_btn.setFixedWidth(170)
        rst_btn.setMinimumHeight(32)
        rst_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rst_btn.clicked.connect(self._sf_restart_explorer)

        self._sf_tools_widget = QWidget()
        tw_inner = QVBoxLayout(self._sf_tools_widget)
        tw_inner.setContentsMargins(0, 0, 0, 0)
        tw_inner.setSpacing(0)
        tw_inner.addWidget(_inner_sep())
        tw_inner.addWidget(_row_action(fix_btn, tr("settings.section.tools")))
        tw_inner.addWidget(_inner_sep())
        tw_inner.addWidget(_row_action(rst_btn, tr("settings.restart_explorer_hint") if hasattr(tr, '__call__') else "Windows Explorer neu starten"))
        self._sf_tools_widget.setVisible(s.debug_mode)

        dev_card, dev_vl = _group_card()
        dev_vl.addWidget(_row_check(self._sf_debug))
        dev_vl.addWidget(self._sf_tools_widget)
        v.addWidget(dev_card)
        v.addSpacing(14)

        from src.pro_manager import SHOW_PRO_UI
        if SHOW_PRO_UI:
            self._build_pro_settings(v, _section_hdr, _group_card)

        v.addStretch()
        self._fs_layout.addWidget(body)

    def _build_pro_settings(self, v, _section_hdr, _group_card):
        """The Pro licence section of the settings (hidden while SHOW_PRO_UI is off)."""
        # ── PRO LICENSE ───────────────────────────────────────────────────
        v.addWidget(_section_hdr(tr("settings.section.pro")))
        v.addSpacing(4)

        from src.pro_manager import is_pro_active as _is_pro_active
        _pro_active = _is_pro_active()

        self._sf_pro_status_lbl = QLabel(
            tr("settings.pro.active") if _pro_active else tr("settings.pro.inactive")
        )
        self._sf_pro_status_lbl.setObjectName("rpSectionLabel" if _pro_active else "hintLabel")
        self._sf_pro_status_lbl.setWordWrap(True)

        self._sf_pro_key = QLineEdit()
        self._sf_pro_key.setPlaceholderText("NEO-XXXX-XXXX-XXXX")
        self._sf_pro_key.setVisible(not _pro_active)

        self._sf_pro_activate_btn = QPushButton(tr("settings.pro.activate"))
        self._sf_pro_activate_btn.setObjectName("primaryBtn")
        self._sf_pro_activate_btn.setFixedWidth(120)
        self._sf_pro_activate_btn.setMinimumHeight(32)
        self._sf_pro_activate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sf_pro_activate_btn.setVisible(not _pro_active)
        self._sf_pro_activate_btn.clicked.connect(self._sf_activate_pro)

        pro_card, pro_vl = _group_card()
        _pro_status_row = QWidget()
        _pro_status_row.setObjectName("settingsRow")
        _pro_inner = QVBoxLayout(_pro_status_row)
        _pro_inner.setContentsMargins(16, 11, 16, 11)
        _pro_inner.setSpacing(6)
        _pro_inner.addWidget(self._sf_pro_status_lbl)
        if not _pro_active:
            _key_row_w = QWidget()
            _key_row_hl = QHBoxLayout(_key_row_w)
            _key_row_hl.setContentsMargins(0, 0, 0, 0)
            _key_row_hl.setSpacing(8)
            _key_row_hl.addWidget(self._sf_pro_key, stretch=1)
            _key_row_hl.addWidget(self._sf_pro_activate_btn)
            _pro_inner.addWidget(_key_row_w)
            _donate_lbl = QLabel(
                f'<a href="https://neosshwinmanager.org/pro" style="color:{current_accent()};">'
                f'{tr("settings.pro.learn_more")}</a>'
            )
            _donate_lbl.setObjectName("hintLabel")
            _donate_lbl.setOpenExternalLinks(True)
            _pro_inner.addWidget(_donate_lbl)
        pro_vl.addWidget(_pro_status_row)
        v.addWidget(pro_card)

    def _sf_check_updates(self):
        """Manual update check from settings screen."""
        try:
            from src.ui.dialogs.about_dialog import APP_VERSION
            from src.updater import UpdaterManager
            from src.ui.dialogs.update_dialog import run_update_dialog, run_pending_update_dialog
        except Exception as e:
            self._show_inline_message("Update", str(e), is_error=True)
            return

        btn = getattr(self, "_sf_update_btn", None)
        if btn:
            btn.setEnabled(False)
            btn.setText(tr("settings.check_updates_running"))

        updater = UpdaterManager(APP_VERSION)
        self._sf_updater = updater  # keep alive until callbacks fire

        def _reset_btn():
            if btn:
                btn.setEnabled(True)
                btn.setText(tr("settings.check_updates"))

        def _on_update_available(version: str, changelog: str, download_url: str, obj_type: str):
            try:
                run_update_dialog(self, updater, version, changelog, download_url, obj_type)
            finally:
                _reset_btn()

        def _on_no_update():
            # An installer may already be waiting on disk (downloaded earlier).
            if not run_pending_update_dialog(self, updater):
                StyledMessageBox.information(self, "Update", tr("settings.up_to_date"))
            _reset_btn()

        def _on_failed(msg: str):
            if not run_pending_update_dialog(self, updater):
                StyledMessageBox.warning(self, tr("dialog.error"), tr("settings.update_check_failed", msg=msg))
            _reset_btn()

        updater.update_available.connect(_on_update_available)
        if hasattr(updater, "no_update_available"):
            updater.no_update_available.connect(_on_no_update)
        if hasattr(updater, "check_failed"):
            updater.check_failed.connect(_on_failed)

        from src.telemetry import attach_update_telemetry
        attach_update_telemetry(updater, 'settings', self._mgr.get_settings())

        updater.check_for_updates_async()

    def _on_sf_security_changed(self, index: int):
        self._sf_sec_warning.setVisible(index >= 1)

    def _sf_activate_pro(self):
        from src.pro_manager import activate_pro
        key = getattr(self._sf_pro_key, "text", lambda: "")().strip().upper()
        if not key:
            self._show_inline_message("PRO", tr("settings.pro.key_required"), is_error=True)
            return
        self._sf_pro_activate_btn.setEnabled(False)
        self._sf_pro_activate_btn.setText(tr("settings.pro.activating"))
        QApplication.processEvents()
        result = activate_pro(key)
        self._sf_pro_activate_btn.setEnabled(True)
        self._sf_pro_activate_btn.setText(tr("settings.pro.activate"))
        if result["success"]:
            StyledMessageBox.information(self, "PRO", tr("settings.pro.activation_success"))
            self._open_settings_panel()
        else:
            self._show_inline_message("PRO", result.get("error", ""), is_error=True)

    def _sf_terminal_client_toggled(self, _button=None, _checked=None):
        is_putty = self._sf_term_putty.isChecked()
        self._sf_putty_widget.setVisible(is_putty)
        if hasattr(self, "_sf_putty_download_lbl"):
            self._sf_putty_download_lbl.setVisible(is_putty)
        _show_sec = not self._sf_term_xterm.isChecked()
        self._sf_sec_header.setVisible(_show_sec)
        self._sf_sec_spacing.setVisible(_show_sec)
        self._sf_sec_card.setVisible(_show_sec)

    def _sf_putty_toggled(self, checked: bool):
        self._sf_putty_widget.setVisible(checked)

    def _sf_debug_toggled(self, checked: bool):
        self._sf_tools_widget.setVisible(checked)

    def _sf_browse_putty(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("settings.select_putty"),
            r"C:\Program Files\PuTTY", "Executables (*.exe)"
        )
        if path:
            self._sf_putty_path.setText(path)

    def _sf_fix_ghosts(self):
        ok = self._controller.purge_all_stale_mounts()
        msg = tr("settings.ghosts_ok") if ok else tr("settings.ghosts_failed")
        self._show_inline_message("", msg, is_error=not ok)
        if ok:
            SSHFSController.restart_explorer()

    def _sf_restart_explorer(self):
        SSHFSController.restart_explorer()
        self._show_inline_message("", tr("settings.explorer_restarted"))

    def _sf_create_shortcut(self):
        ok = StyledMessageBox.question(
            self,
            tr("settings.create_shortcut"),
            tr("settings.create_shortcut.confirm"),
            yes_text=tr("dialog.understood"),
            no_text=tr("dialog.cancel"),
        )
        if not ok:
            return

        success, msg = self._create_desktop_shortcut()
        if success:
            StyledMessageBox.information(self, tr("dialog.success"), tr("settings.create_shortcut.success"))
        else:
            logger.error(f"Shortcut creation failed: {msg}")
            StyledMessageBox.warning(self, tr("dialog.error"), tr("settings.create_shortcut.failed"))

    @staticmethod
    def _create_desktop_shortcut() -> tuple[bool, str]:
        import subprocess

        # In packaged mode this is the app EXE path.
        if getattr(sys, "frozen", False):
            target_path = os.path.abspath(sys.executable)
            args = ""
        else:
            target_path = os.path.abspath(sys.executable)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            main_script = os.path.join(project_root, "main.py")
            args = f'"{main_script}"'

        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        shortcut_path = os.path.join(desktop, "NEO SSH-Win Manager.lnk")

        ps_script = (
            "$WshShell = New-Object -ComObject WScript.Shell\n"
            f"$Shortcut = $WshShell.CreateShortcut('{shortcut_path}')\n"
            f"$Shortcut.TargetPath = '{target_path}'\n"
            f"$Shortcut.WorkingDirectory = '{os.path.dirname(target_path)}'\n"
            "$Shortcut.Description = 'NEO SSH-Win Manager'\n"
            f"$Shortcut.IconLocation = '{target_path},0'\n"
            + (f"$Shortcut.Arguments = '{args}'\n" if args else "")
            + "$Shortcut.Save()"
        )

        try:
            cp = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                check=True,
                capture_output=True,
                text=True,
            )
            if not os.path.exists(shortcut_path):
                return False, "Shortcut file was not created"
            return True, cp.stdout.strip()
        except subprocess.CalledProcessError as e:
            return False, (e.stderr or e.stdout or str(e)).strip()
        except Exception as e:
            return False, str(e)

    # ------------------------------------------------------------------
    # Right panel save / cancel
    # ------------------------------------------------------------------

    def _on_rp_save(self):
        if self._saving_in_progress:
            return
        self._set_saving_state(True)
        try:
            if self._panel_mode == _PANEL_EDIT:
                self._save_edit_form()
            elif self._panel_mode == _PANEL_ADD:
                self._save_add_form()
        except RuntimeError:
            self._err_popup(
                tr("dialog.error"),
                tr("sysinfo.error") + " Formular wurde neu geladen. Bitte Eingaben prüfen und erneut speichern."
            )
            if self._panel_conn_id:
                self._open_edit_panel(self._panel_conn_id)
            else:
                self._open_add_panel()
        except Exception as e:
            self._err_popup(tr("dialog.error"), str(e))
        finally:
            self._set_saving_state(False)
            if self._panel_mode in (_PANEL_EDIT, _PANEL_ADD):
                self._validate_edit_form()

    def _on_rp_cancel(self):
        if self._panel_mode in (_PANEL_EDIT, _PANEL_ADD):
            if not self._guard_leave_form():
                return
            if self._panel_conn_id:
                self._open_info_panel(self._panel_conn_id)
            else:
                self._close_right_panel_force()

    def _on_rp_terminal_clicked(self):
        """Header terminal button for the currently open connection panel."""
        conn_id = self._panel_conn_id
        if not conn_id:
            return
        settings = self._mgr.get_settings()
        if getattr(settings, "terminal_client", "ssh") == "xterm":
            self._open_terminal_panel(conn_id)
        else:
            self._on_ssh_terminal(conn_id)

    def _sync_rp_mount_button(self, conn_id: str):
        """Update mount/unmount header button state based on card mount state."""
        btn = getattr(self, "_rp_mount_btn", None)
        if btn is None:
            return
        card = self._cards.get(conn_id)
        is_mounted = bool(card and card.is_mounted)
        if is_mounted:
            # Match ConnectionCard.update_mount_state()
            btn.setIcon(svg_icon("minus", "#ef4444", 16))
            btn.setToolTip(tr("card.tooltip.mount_on"))
            btn.setEnabled(True)
        else:
            # Match ConnectionCard.update_mount_state()
            btn.setIcon(svg_icon("arrow-right", "#aab4c4", 16))
            btn.setToolTip(tr("card.tooltip.mount_off"))
            btn.setEnabled(True)
        btn.setAccessibleName(btn.toolTip())

    def _on_rp_mount_clicked(self):
        """Header mount/unmount button for the currently open connection panel."""
        conn_id = self._panel_conn_id
        if not conn_id:
            return
        card = self._cards.get(conn_id)
        if not card:
            return
        if card.is_mounted:
            self._on_unmount(conn_id)
        else:
            self._on_mount(conn_id)

    def _safe_lineedit_text(self, attr_name: str) -> str:
        """
        Return text from a potentially stale QLineEdit attribute.
        If the wrapped Qt object was already deleted, return empty string.
        """
        widget = getattr(self, attr_name, None)
        if widget is None:
            return ""
        try:
            return widget.text().strip()
        except RuntimeError:
            return ""

    def _safe_current_data(self, attr_name: str, default=None):
        widget = getattr(self, attr_name, None)
        if widget is None:
            return default
        try:
            value = widget.currentData()
            return default if value is None else value
        except RuntimeError:
            return default

    def _safe_bool_checked(self, attr_name: str, default: bool = False) -> bool:
        widget = getattr(self, attr_name, None)
        if widget is None:
            return default
        try:
            return bool(widget.isChecked())
        except RuntimeError:
            return default

    def _safe_spin_value(self, attr_name: str, default: int = 22) -> int:
        widget = getattr(self, attr_name, None)
        if widget is None:
            return default
        try:
            return int(widget.value())
        except RuntimeError:
            return default

    def _set_saving_state(self, saving: bool):
        self._saving_in_progress = saving
        for btn_name in (
            "_rp_save_top_btn", "_rp_save_btn", "_rp_cancel_top_btn", "_rp_cancel_btn",
            "_rp_edit_save_btn", "_rp_edit_cancel_btn", "_rp_edit_delete_btn"
        ):
            btn = getattr(self, btn_name, None)
            if btn is None:
                continue
            try:
                btn.setEnabled(not saving)
            except RuntimeError:
                pass
        if saving:
            self._set_status(tr("card.loading.saving"))

    def _snapshot_form(self) -> dict:
        return {
            "name": self._safe_lineedit_text("_ef_name"),
            "host": self._safe_lineedit_text("_ef_host"),
            "user": self._safe_lineedit_text("_ef_user"),
            "path": self._safe_lineedit_text("_ef_path"),
            "port": self._safe_spin_value("_ef_port", 22),
            "auth": self._safe_current_data("_ef_auth", "password"),
            "password": self._safe_lineedit_text("_ef_pw"),
            "key": self._safe_lineedit_text("_ef_key"),
            "putty_key": self._safe_lineedit_text("_ef_putty_key"),
            "drive": self._safe_current_data("_ef_drive", "Z:"),
            "protocol": self._safe_current_data("_ef_protocol", PROTOCOL_SFTP),
            "ftp_implicit_tls": self._safe_bool_checked("_ef_ftp_implicit", False),
            "ftp_passive": self._safe_bool_checked("_ef_ftp_passive", True),
            "ftp_verify_cert": self._safe_bool_checked("_ef_ftp_verify", True),
            "cli_enabled": self._safe_bool_checked("_ef_cli_cb", False),
            "cli_key": self._safe_lineedit_text("_ef_cli_key"),
            "groups": self._safe_lineedit_text("_ef_groups"),
            "is_template": self._safe_bool_checked("_ef_template_cb", False),
        }

    def _form_is_dirty(self) -> bool:
        if self._panel_mode not in (_PANEL_EDIT, _PANEL_ADD):
            return False
        if self._ef_initial_snapshot is None:
            return False
        return self._snapshot_form() != self._ef_initial_snapshot

    def _snapshot_settings_form(self) -> dict:
        if self._panel_mode != _PANEL_SETTINGS:
            return {}
        return {
            "start": self._safe_bool_checked("_sf_start", False),
            "tray": self._safe_bool_checked("_sf_tray", False),
            "admin": self._safe_bool_checked("_sf_admin", False),
            "telemetry": self._safe_bool_checked("_sf_telemetry", False),
            "interval": self._safe_spin_value("_sf_interval", 30),
            "auto_reconnect": self._safe_bool_checked("_sf_auto_reconnect", False),
            "auto_remount": self._safe_bool_checked("_sf_auto_remount", True),
            "disable_cache": self._safe_bool_checked("_sf_sshfs_disable_cache", False),
            "shared_letters": self._safe_bool_checked("_sf_shared_letters", False),
            "auto_pick_letter": self._safe_bool_checked("_sf_auto_pick_letter", False),
            "theme": self._safe_current_data("_sf_theme", "dark"),
            "accent": getattr(self, "_sf_accent", DEFAULT_ACCENT),
            "lang": self._safe_current_data("_sf_lang", "en"),
            "term_ssh": self._safe_bool_checked("_sf_term_ssh", False),
            "term_putty": self._safe_bool_checked("_sf_term_putty", False),
            "term_xterm": self._safe_bool_checked("_sf_term_xterm", True),
            "putty_path": self._safe_lineedit_text("_sf_putty_path"),
            "security_level": self._safe_current_data("_sf_security_level", 0),
            "debug": self._safe_bool_checked("_sf_debug", False),
        }

    def _settings_form_is_dirty(self) -> bool:
        if self._panel_mode != _PANEL_SETTINGS:
            return False
        if self._settings_initial_snapshot is None:
            return False
        return self._snapshot_settings_form() != self._settings_initial_snapshot

    def _ask_settings_dirty_action(self) -> str:
        dlg = QDialog(self)
        dlg.setObjectName("dialogSurface")
        dlg.setWindowTitle(tr("dirty.title"))
        dlg.setModal(True)
        dlg.setMinimumWidth(420)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title_lbl = QLabel(tr("dirty.title"))
        title_lbl.setObjectName("dialogTitle")
        layout.addWidget(title_lbl)

        msg_lbl = QLabel(tr("dirty.settings.body"))
        msg_lbl.setWordWrap(True)
        layout.addWidget(msg_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        cancel_btn = QPushButton(tr("dialog.cancel"))
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.clicked.connect(lambda: dlg.done(0))
        btn_row.addWidget(cancel_btn)

        discard_btn = QPushButton(tr("dirty.discard"))
        discard_btn.setObjectName("dangerBtn")
        discard_btn.clicked.connect(lambda: dlg.done(1))
        btn_row.addWidget(discard_btn)

        apply_btn = QPushButton(tr("dirty.apply"))
        apply_btn.setObjectName("primaryBtn")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(lambda: dlg.done(2))
        btn_row.addWidget(apply_btn)

        layout.addLayout(btn_row)

        code = dlg.exec()
        if code == 2:
            return "apply"
        if code == 1:
            return "discard"
        return "cancel"

    def _guard_leave_form(self) -> bool:
        if self._leave_guard_active:
            # Drop re-entrant navigation calls to avoid double-trigger side effects.
            return False

        self._leave_guard_active = True
        try:
            if self._panel_mode in (_PANEL_EDIT, _PANEL_ADD):
                if not self._form_is_dirty():
                    return True
                discard = StyledMessageBox.question(
                    self, tr("dirty.title"), tr("dirty.body"),
                    yes_text=tr("dirty.discard"), no_text=tr("dirty.keep")
                )
                if discard:
                    self._ef_initial_snapshot = None
                return discard

            if self._panel_mode == _PANEL_SETTINGS:
                if not self._settings_form_is_dirty():
                    return True
                action = self._ask_settings_dirty_action()
                if action == "cancel":
                    return False
                if action == "apply":
                    if not self._save_settings_form(navigate_home=False):
                        return False
                else:
                    self._sf_revert_accent_preview()
                self._settings_initial_snapshot = None
                return True

            return True
        finally:
            self._leave_guard_active = False

    def _name_is_duplicate(self, name: str, exclude_id: str | None = None) -> bool:
        """Returns True if another connection already uses this name (case-insensitive)."""
        name_lower = name.strip().lower()
        for c in self._mgr.get_all(include_templates=False):
            if c.name.lower() == name_lower and c.id != exclude_id:
                return True
        return False

    def _validate_edit_form(self):
        required = ("_ef_name", "_ef_host", "_ef_user")
        is_valid = True
        for attr in required:
            widget = getattr(self, attr, None)
            if widget is None:
                continue
            try:
                text = widget.text().strip()
                invalid = not text
                if attr == "_ef_name" and text and not _is_safe_label(text):
                    invalid = True
                elif attr == "_ef_name" and text and _is_safe_label(text):
                    excl = getattr(self, "_ef_conn", None)
                    excl_id = excl.id if excl and self._panel_mode == _PANEL_EDIT else None
                    if self._name_is_duplicate(text, exclude_id=excl_id):
                        invalid = True
                widget.setProperty("invalid", "true" if invalid else "false")
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                is_valid = is_valid and (not invalid)
            except RuntimeError:
                is_valid = False

        for btn_name in ("_rp_save_top_btn", "_rp_save_btn", "_rp_edit_save_btn"):
            btn = getattr(self, btn_name, None)
            if btn is None:
                continue
            try:
                btn.setEnabled(is_valid and not self._saving_in_progress)
            except RuntimeError:
                pass

    def _template_name_is_duplicate(self, name: str, exclude_id: str | None = None) -> bool:
        """Returns True if a template with this name already exists (case-insensitive)."""
        name_lower = name.strip().lower()
        for c in self._mgr.get_templates():
            if c.name.lower() == name_lower and c.id != exclude_id:
                return True
        return False

    def _suggest_unique_template_name(self, base_name: str, exclude_id: str | None = None) -> str:
        """Returns a unique template name, appending (1), (2) etc. if the base name is taken."""
        if not self._template_name_is_duplicate(base_name, exclude_id):
            return base_name
        counter = 1
        while True:
            candidate = f"{base_name} ({counter})"
            if not self._template_name_is_duplicate(candidate, exclude_id):
                return candidate
            counter += 1

    def _ask_template_name(self, base_name: str, exclude_id: str | None = None) -> str | None:
        """Shows a styled input dialog for the template name. Returns the chosen name or None if cancelled."""
        from src.ui.dialogs.styled_message_box import StyledInputDialog
        suggested = self._suggest_unique_template_name(base_name, exclude_id)
        while True:
            text, ok = StyledInputDialog.get_text(
                self,
                tr("addedit.template.name.title"),
                tr("addedit.template.name.label"),
                suggested,
            )
            if not ok:
                return None
            if not text:
                StyledMessageBox.critical(self, tr("dialog.error"), tr("addedit.required.name"))
                suggested = text
                continue
            if not _is_safe_label(text):
                StyledMessageBox.critical(self, tr("dialog.error"), tr("addedit.name.invalid"))
                suggested = text
                continue
            if self._template_name_is_duplicate(text, exclude_id):
                StyledMessageBox.critical(self, tr("dialog.error"), tr("addedit.template.name.duplicate"))
                suggested = text
                continue
            return text

    def _ef_collect_protocol_fields(self) -> dict:
        """
        Protocol-dependent Connection fields taken from the edit form.

        SSH-only values (key files, drive letter, CLI access) are cleared for
        FTP/FTPS so a protocol switch cannot leave stale data behind.
        """
        protocol = self._ef_current_protocol()
        is_ftp = protocol in (PROTOCOL_FTP, PROTOCOL_FTPS)
        cli_enabled = (not is_ftp) and self._safe_bool_checked("_ef_cli_cb", False)
        return {
            "protocol": protocol,
            "ftp_implicit_tls": (protocol == PROTOCOL_FTPS
                                 and self._safe_bool_checked("_ef_ftp_implicit", False)),
            "ftp_passive": self._safe_bool_checked("_ef_ftp_passive", True),
            "ftp_verify_cert": self._safe_bool_checked("_ef_ftp_verify", True),
            "key_path": "" if is_ftp else self._safe_lineedit_text("_ef_key"),
            "putty_key_path": "" if is_ftp else self._safe_lineedit_text("_ef_putty_key"),
            "drive_letter": "" if is_ftp else self._safe_current_data("_ef_drive", "Z:"),
            "cli_access_enabled": cli_enabled,
            "cli_access_key": (self._safe_lineedit_text("_ef_cli_key")
                               if cli_enabled else None),
        }

    def _save_edit_form(self):
        if not getattr(self, "_ef_conn", None):
            self._show_inline_message(tr("dialog.error"), "Formular ist nicht verfügbar. Bitte erneut öffnen.", is_error=True)
            return
        import dataclasses
        import uuid
        conn = self._ef_conn
        name = self._safe_lineedit_text("_ef_name")
        host = self._safe_lineedit_text("_ef_host")
        user = self._safe_lineedit_text("_ef_user")
        is_template = self._safe_bool_checked("_ef_template_cb", False)
        # Editing a host: the template box saves a COPY as template; the host
        # itself stays (and stays mounted). Editing a template keeps it one.
        make_copy = is_template and not conn.is_template
        errors = []
        if not name: errors.append(tr("addedit.required.name"))
        elif not _is_safe_label(name): errors.append(tr("addedit.name.invalid"))
        elif (not is_template or make_copy) and self._name_is_duplicate(name, exclude_id=conn.id): errors.append(tr("addedit.name.duplicate"))
        if not host: errors.append(tr("addedit.required.host"))
        if not user: errors.append(tr("addedit.required.user"))
        fields = self._ef_collect_protocol_fields()
        locked = bool(getattr(self, "_ef_mount_locked", False))
        if not locked and not is_template:
            letter_error = self._drive_letter_conflict(fields.get("drive_letter"), exclude_id=conn.id)
            if letter_error:
                errors.append(letter_error)
        if errors:
            self._show_inline_message(tr("addedit.required.title"), "\n".join(errors), is_error=True)
            return

        tpl_name = None
        if is_template:
            tpl_name = self._ask_template_name(name, exclude_id=conn.id)
            if tpl_name is None:
                return
            if not make_copy:
                name = tpl_name

        # PuTTY disabled globally: its field is not in the form, keep the path.
        if getattr(self, "_ef_putty_key", None) is None and fields["protocol"] == conn.protocol:
            fields["putty_key_path"] = conn.putty_key_path

        # Start from the stored host so fields the form does not show
        # (template_id, …) survive the save.
        updated = dataclasses.replace(
            conn,
            name=name, host=host, user=user,
            remote_path=self._safe_lineedit_text("_ef_path") or "/",
            port=self._safe_spin_value("_ef_port", 22),
            auth_method=self._safe_current_data("_ef_auth", "password"),
            password=self._safe_lineedit_text("_ef_pw"),
            groups=self._safe_lineedit_text("_ef_groups"),
            is_template=is_template and not make_copy,
            **fields,
        )
        if locked:
            # Mounted: the running mount depends on these, keep the stored values.
            updated = dataclasses.replace(
                updated, **{f: getattr(conn, f) for f in self._EF_MOUNT_LOCKED_FIELDS})
        self._mgr.update(updated)

        if make_copy:
            # Templates are stored without credentials; a CLI key must stay unique.
            self._mgr.add(dataclasses.replace(
                updated, id=str(uuid.uuid4()), name=tpl_name, is_template=True,
                template_id=None, password="", key_path="", putty_key_path="",
                cli_access_enabled=False, cli_access_key=None,
            ))

        if updated.name != conn.name and self._cards.get(conn.id) and self._cards[conn.id].is_mounted:
            # Renamed while mounted: Explorer shows the name as drive label.
            try:
                self._controller._set_drive_label(
                    dataclasses.replace(updated, drive_letter=self._effective_letter(updated)), delay=0)
            except Exception as e:
                logger.warning(f"Laufwerksbezeichnung nicht aktualisiert: {e}")

        self._refresh_list()
        self._set_status(tr("status.template_copy_saved", name=tpl_name) if make_copy
                         else tr("status.saved"))
        # Reopen info panel for the updated connection
        self._open_info_panel(conn.id)

    def _drive_letter_conflict(self, letter, exclude_id=None) -> str | None:
        """Shared letters off: an error text if another host already has *letter*."""
        from src.drive_utils import norm_letter
        letter = norm_letter(letter)
        if not letter or self._mgr.get_settings().allow_shared_drive_letters:
            return None
        other = next((c for c in self._mgr.get_connections()
                      if c.id != exclude_id and not c.is_ftp
                      and norm_letter(c.drive_letter) == letter), None)
        return tr("addedit.drive.taken", drive=letter, name=other.name) if other else None

    def _save_add_form(self):
        name = self._safe_lineedit_text("_ef_name")
        host = self._safe_lineedit_text("_ef_host")
        user = self._safe_lineedit_text("_ef_user")
        is_tpl = self._safe_bool_checked("_ef_template_cb", False)
        errors = []
        if not name: errors.append(tr("addedit.required.name"))
        elif not _is_safe_label(name): errors.append(tr("addedit.name.invalid"))
        elif not is_tpl and self._name_is_duplicate(name): errors.append(tr("addedit.name.duplicate"))
        if not host: errors.append(tr("addedit.required.host"))
        if not user: errors.append(tr("addedit.required.user"))
        if not is_tpl:
            letter_error = self._drive_letter_conflict(self._safe_current_data("_ef_drive", ""))
            if letter_error and self._ef_current_protocol() == PROTOCOL_SFTP:
                errors.append(letter_error)
        if errors:
            self._show_inline_message(tr("addedit.required.title"), "\n".join(errors), is_error=True)
            return

        if is_tpl:
            tpl_name = self._ask_template_name(name)
            if tpl_name is None:
                return
            name = tpl_name

        # Templates are stored without any credentials.
        fields = self._ef_collect_protocol_fields()
        if is_tpl:
            fields["key_path"] = ""
            fields["putty_key_path"] = ""

        new_conn = Connection(
            name=name, host=host, user=user,
            remote_path=self._safe_lineedit_text("_ef_path") or "/",
            port=self._safe_spin_value("_ef_port", 22),
            auth_method=self._safe_current_data("_ef_auth", "password"),
            password="" if is_tpl else self._safe_lineedit_text("_ef_pw"),
            groups=self._safe_lineedit_text("_ef_groups"),
            is_template=is_tpl,
            **fields,
        )
        self._mgr.add(new_conn)
        self._refresh_list()
        self._set_status(tr("status.saved"))
        self._ef_initial_snapshot = self._snapshot_form()
        self._open_info_panel(new_conn.id)

    def _save_settings_form(self, navigate_home: bool = True) -> bool:
        if self._sf_term_putty.isChecked():
            import os as _os
            path = self._sf_putty_path.text().strip()
            if not path:
                self._show_inline_message("PuTTY", tr("settings.putty_missing"), is_error=True)
                return False
            if not _os.path.exists(path):
                self._show_inline_message(
                    tr("settings.putty_not_found_title"),
                    tr("settings.putty_not_found", path=path),
                    is_error=True
                )
                return False

        if self._sf_term_putty.isChecked():
            _tc = "putty"
        elif self._sf_term_xterm.isChecked():
            _tc = "xterm"
        else:
            _tc = "ssh"

        old_lang = current_language()
        _sec = 0 if _tc == "xterm" else self._sf_security_level.currentIndex()
        new_settings = AppSettings(
            start_with_windows=self._sf_start.isChecked(),
            minimize_to_tray=self._sf_tray.isChecked(),
            require_admin=self._sf_admin.isChecked(),
            check_interval_seconds=self._sf_interval.value(),
            auto_reconnect=self._sf_auto_reconnect.isChecked(),
            auto_remount_on_lost=self._sf_auto_remount.isChecked(),
            auto_reconnect_mounts=self._sf_auto_reconnect.isChecked(),
            debug_mode=self._sf_debug.isChecked(),
            terminal_client=_tc,
            use_putty=(_tc == "putty"),
            putty_path=self._sf_putty_path.text().strip(),
            language=self._sf_lang.currentData() or "en",
            theme=self._sf_theme.currentData() or "dark",
            security_level=_sec,
            allow_passwordless_key_auth=_sec >= 1,
            allow_insecure_password_auth=_sec >= 2,
            telemetry_enabled=getattr(self, "_sf_telemetry").isChecked() if hasattr(self, "_sf_telemetry") else False,
            telemetry_prompt_shown=getattr(self._mgr.get_settings(), "telemetry_prompt_shown", False),
            sshfs_disable_cache=self._sf_sshfs_disable_cache.isChecked(),
            accent_color="" if self._sf_accent == DEFAULT_ACCENT else self._sf_accent,
            allow_shared_drive_letters=self._sf_shared_letters.isChecked(),
            auto_pick_free_drive_letter=(self._sf_shared_letters.isChecked()
                                         and self._sf_auto_pick_letter.isChecked()),
        )
        self._mgr.save_settings(new_settings)
        self._apply_settings_object(new_settings)
        self._settings_initial_snapshot = self._snapshot_settings_form()
        self._set_status(tr("status.settings_saved"))
        if navigate_home:
            self._nav_home()
        if new_settings.language != old_lang:
            self._show_inline_message("Info", tr("settings.language.restart"))
        return True

    # ------------------------------------------------------------------
    # Inline message helper
    # ------------------------------------------------------------------

    def _show_inline_message(self, title: str, msg: str, is_error: bool = False):
        """Show a brief status message in the status bar."""
        self._set_status(f"{'⚠ ' if is_error else ''}{title + ': ' if title else ''}{msg.splitlines()[0]}")

    def _err_popup(self, title: str, message: str) -> None:
        """Error dialog with a copy-to-clipboard button. Also persists title+first line in status bar."""
        self._set_error_status(f"⚠ {title}: {message.splitlines()[0]}")

        dlg = QDialog(self)
        dlg.setObjectName("dialogSurface")
        dlg.setWindowTitle(title)
        dlg.setModal(True)
        dlg.setMinimumWidth(420)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("dialogTitle")
        layout.addWidget(title_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setObjectName("errorLabel")
        msg_lbl.setWordWrap(True)
        layout.addWidget(msg_lbl, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        copy_btn = QPushButton()
        copy_btn.setObjectName("rpHeaderBtn")
        copy_btn.setFixedSize(32, 32)
        copy_btn.setIcon(svg_icon("copy", "#aab4c4", 16))
        copy_btn.setIconSize(QSize(16, 16))
        copy_btn.setToolTip("Fehlermeldung kopieren")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _clip_text = f"{title}\n\n{message}"
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(_clip_text))
        btn_row.addWidget(copy_btn)
        btn_row.addStretch()

        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primaryBtn")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(dlg.accept)
        ok_btn.setDefault(True)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)
        dlg.exec()

    def _set_error_status(self, msg: str) -> None:
        """Set a persistent error message in the status bar (no timeout)."""
        self._set_status(msg)

    def _show_mount_failure_dialog(self, conn: Connection | None, message: str) -> bool:
        """Show a richer failure dialog that mirrors the website demo's guidance blocks."""
        dialog = QDialog(self)
        dialog.setObjectName("mountErrorDialog")
        dialog.setWindowTitle(tr("mount.failed.title"))
        dialog.setModal(True)
        dialog.setMinimumWidth(540)

        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)

        title = QLabel(tr("mount.failed.title"))
        title.setObjectName("dialogTitle")
        outer.addWidget(title)

        lead = QLabel(tr("mount.failed.main", name=conn.name if conn else "?"))
        lead.setObjectName("mountErrorLead")
        lead.setWordWrap(True)
        outer.addWidget(lead)

        checks_frame = QFrame()
        checks_frame.setObjectName("mountErrorBlock")
        checks_layout = QVBoxLayout(checks_frame)
        checks_layout.setContentsMargins(14, 12, 14, 12)
        checks_layout.setSpacing(0)
        checks = QLabel(
            tr(
                "mount.failed.troubleshoot",
                host=conn.host if conn else "?",
                port=conn.port if conn else "?",
            ).strip()
        )
        checks.setObjectName("mountErrorBody")
        checks.setWordWrap(True)
        checks_layout.addWidget(checks)
        outer.addWidget(checks_frame)

        details = QLabel(tr("mount.failed.details", msg=message).strip())
        details.setObjectName("mountErrorDetails")
        details.setWordWrap(True)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(details)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        close_btn = QPushButton(tr("dialog.close"))
        close_btn.setObjectName("secondaryBtn")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(dialog.reject)
        btn_row.addWidget(close_btn)

        retry_btn = QPushButton(tr("mount.failed.retry"))
        retry_btn.setObjectName("primaryBtn")
        retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        retry_btn.setDefault(True)
        retry_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(retry_btn)

        outer.addLayout(btn_row)
        return dialog.exec() == QDialog.DialogCode.Accepted

    # ------------------------------------------------------------------
    # Info panel helpers
    # ------------------------------------------------------------------

    def _on_rp_edit_clicked(self):
        """Edit button in right panel header."""
        if self._panel_conn_id:
            self._open_edit_panel(self._panel_conn_id)

    def _on_rp_info_clicked(self):
        """Info button in right panel header - opens system info panel with toggle logic."""
        if self._panel_conn_id:
            if self._panel_mode == _PANEL_SYSINFO and self._panel_conn_id == self._panel_conn_id:
                self._close_right_panel()
            else:
                self._open_sysinfo_panel(self._panel_conn_id)

    # ------------------------------------------------------------------
    # Card selection
    # ------------------------------------------------------------------

    def _select_card(self, conn_id: str):
        if conn_id != self._panel_conn_id and not self._guard_leave_form():
            return
        if self._selected_id and self._selected_id in self._cards:
            prev = self._cards[self._selected_id]
            prev.setProperty("selected", False)
            prev.style().unpolish(prev)
            prev.style().polish(prev)

        self._selected_id = conn_id
        if conn_id in self._cards:
            card = self._cards[conn_id]
            card.setProperty("selected", True)
            card.style().unpolish(card)
            card.style().polish(card)

        # Card click always shows connection details (not sysinfo)
        if self._panel_mode not in (_PANEL_INFO, _PANEL_EDIT) or self._panel_conn_id != conn_id:
            self._open_info_panel(conn_id)

    @pyqtSlot(str)
    def _on_info_requested(self, conn_id: str):
        """[i] button clicked — always shows system info, toggles closed on second click."""
        if self._panel_mode == _PANEL_SYSINFO and self._panel_conn_id == conn_id:
            self._close_right_panel()
        else:
            self._open_sysinfo_panel(conn_id)

    def _update_status(self):
        connections = self._mgr.get_all()
        total = len(connections)
        mounted = sum(1 for c in self._cards.values() if c.is_mounted)
        if total:
            active_str = tr("badge.n_active", n=total)
            mount_str  = tr("badge.n_mounted", n=mounted)
            self._badge_lbl.setText(f"{active_str} · {mount_str}")
        else:
            self._badge_lbl.setText("")
        self._mount_count_lbl.setText(
            tr("status.mounted_short", n=mounted) if mounted else tr("status.mounted_none")
        )

    # ------------------------------------------------------------------
    # Mount state polling
    # ------------------------------------------------------------------

    def _poll_mount_states(self):
        mounted = self._compute_mounted([c.connection for c in self._cards.values()])

        for conn_id, card in self._cards.items():
            conn = card.connection
            if conn.is_ftp:
                continue        # never mounted, nothing to poll
            is_mounted_now = conn_id in mounted
            card.set_mounted_letter(mounted.get(conn_id))
            if is_mounted_now != card.is_mounted:
                card.update_mount_state(is_mounted_now)
                # Refresh open panel for this connection on mount state change
                if self._panel_conn_id == conn_id:
                    if self._panel_mode == _PANEL_INFO:
                        self._open_info_panel(conn_id)
                    elif self._panel_mode == _PANEL_SYSINFO:
                        self._open_sysinfo_panel(conn_id)

        self._update_status()

    # ------------------------------------------------------------------
    # Action slots
    # ------------------------------------------------------------------

    def _on_add(self):
        self._open_add_panel()

    def _on_delete(self):
        conn_id = self._panel_conn_id or self._selected_id
        if not conn_id:
            self._set_status(tr("delete.select_one"))
            return
        self._delete_connection(conn_id)

    def _delete_connection(self, conn_id: str):
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return
        card = self._cards.get(conn_id)
        if card and card.is_mounted:
            if not StyledMessageBox.question(
                self, tr("delete.title"),
                tr("delete.mounted_confirm", name=conn.name),
                yes_text=tr("delete.anyway"), no_text=tr("dialog.cancel")
            ):
                return
            self._controller.unmount(self._effective_letter(conn))
            self._save_active_mount(conn_id, False)
        else:
            if not StyledMessageBox.question(
                self, tr("delete.title"),
                tr("delete.confirm", name=conn.name),
                yes_text=tr("main.delete"), no_text=tr("dialog.cancel")
            ):
                return
        self._mgr.delete(conn_id)
        self._close_right_panel_force()
        self._refresh_list()
        self._set_status(tr("status.connection_deleted", name=conn.name))

    def _prepare_auth(self, conn, parent=None):
        """parent: the window the questions belong to (the file browser asks too)."""
        import copy
        conn = copy.copy(conn)
        parent = parent or self

        if conn.auth_method == "ask":
            has_key = bool(conn.key_path)
            dlg = _AuthMethodDialog(
                parent,
                conn.name,
                has_key=has_key,
                prefer_key=has_key and not conn.password,
            )
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return None
            conn.auth_method = dlg.selected_auth_method()

        if conn.auth_method == "password" and not conn.password:
            pw, ok = QInputDialog.getText(
                parent, tr("auth.enter_password.title"),
                tr("auth.enter_password.prompt", name=conn.name),
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return None
            conn.password = pw

        return conn

    def _reject_ftp_action(self, conn, message_key: str) -> bool:
        """
        Block SSH-only actions (mount, terminal) on FTP/FTPS connections.

        Returns True when the action was rejected and the caller must stop.
        """
        if conn is None or not conn.is_ftp:
            return False
        proto = conn.protocol_label
        self._err_popup(
            tr("ftp.mount_unsupported.title", proto=proto),
            tr(message_key, name=conn.name, proto=proto),
        )
        card = self._cards.get(conn.id)
        if card:
            card.hide_loading()
        return True

    @pyqtSlot(str)
    def _on_mount(self, conn_id: str):
        self._mount(conn_id, interactive=True)

    def _mount(self, conn_id: str, interactive: bool = True):
        """Mount a host. interactive=False (auto-reconnect at start) never asks:
        if the letter is taken and no free one may be picked, the host is skipped."""
        if conn_id in self._workers:
            return
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return
        if self._reject_ftp_action(conn, "ftp.mount_unsupported"):
            return
        # Settle the drive letter first: never ask for a password and then
        # report that the letter is taken.
        letter = self._resolve_mount_letter(conn, interactive)
        if letter is None:
            card = self._cards.get(conn_id)
            if card:
                card.hide_loading()
            return
        conn = self._prepare_auth(self._mgr.get_by_id(conn_id) or conn)
        if conn is None:
            card = self._cards.get(conn_id)
            if card:
                card.hide_loading()
            return
        self._start_mount_worker(conn_id, conn, letter)

    def _start_mount_worker(self, conn_id: str, conn, letter: str):
        """Run the mount on *letter* (conn is a copy prepared by _prepare_auth)."""
        conn.drive_letter = letter
        self._mount_targets[conn_id] = letter
        self._set_status(tr("status.connecting", name=conn.name, drive=letter))
        card = self._cards.get(conn_id)
        if card:
            card.show_loading(tr("card.loading.connect"))
        _disable_cache = bool(getattr(self._mgr.get_settings(), "sshfs_disable_cache", False))
        worker = MountWorker(conn, self._controller, disable_cache=_disable_cache)
        worker.finished.connect(self._on_mount_finished)
        self._workers[conn_id] = worker
        worker.start()

    # ── drive letters ──────────────────────────────────────────────────────

    def _drives_in_use(self) -> set[str]:
        from src.drive_utils import norm_letter
        return {l for l in (norm_letter(k) for k in self._controller.get_mounted_drives()) if l}

    def _compute_mounted(self, connections=None) -> dict[str, str]:
        """Which host is mounted on which letter; also remembered for
        _effective_letter(). See drive_utils.resolve_mounted."""
        from src.drive_utils import norm_letter, resolve_mounted
        if connections is None:
            connections = self._mgr.get_connections()
        in_use = self._drives_in_use()
        # Hosts the app has no mount record for only count as mounted if their
        # letter really holds an SSHFS mount (not a USB stick on that letter).
        unrecorded = {norm_letter(c.drive_letter) for c in connections
                      if c.id not in self._active_mounts and not c.is_ftp}
        candidates = unrecorded & in_use
        ours = self._controller.sshfs_letters(candidates) if candidates else set()
        self._mounted_letters = resolve_mounted(
            connections, self._active_mounts, in_use, ours)
        return self._mounted_letters

    def _effective_letter(self, conn) -> str:
        """The letter the host is mounted on, else its configured letter."""
        from src.drive_utils import norm_letter
        return (self._mounted_letters.get(conn.id)
                or norm_letter(self._active_mounts.get(conn.id))
                or conn.drive_letter)

    def _resolve_mount_letter(self, conn, interactive: bool = True) -> str | None:
        """The letter to mount *conn* on, or None to cancel.

        Never a letter that is in use. If the configured one is taken:
        - shared letters + auto-pick: a random free letter, for this mount only;
        - otherwise (interactive): offer a free letter; accepting stores it on
          the host. Not interactive: skip the host.
        """
        from src.drive_utils import norm_letter, suggest_free_letter
        settings = self._mgr.get_settings()
        shared = bool(getattr(settings, "allow_shared_drive_letters", False))
        auto_pick = shared and bool(getattr(settings, "auto_pick_free_drive_letter", False))
        wanted = norm_letter(conn.drive_letter)
        in_use = self._drives_in_use()
        if wanted and wanted not in in_use:
            return wanted

        others = [c for c in self._mgr.get_connections()
                  if c.id != conn.id and not c.is_ftp]
        mounted = self._compute_mounted()
        if conn.id in mounted:
            return None                     # already mounted
        # Letters other hosts are configured for: avoided where possible, and
        # always when letters may not be shared.
        taken_by_hosts = {norm_letter(c.drive_letter) for c in others}
        busy = wanted or conn.drive_letter

        if auto_pick:
            pick = (suggest_free_letter(in_use, taken_by_hosts, randomize=True)
                    or suggest_free_letter(in_use, randomize=True))
            if pick:
                logger.info(f"Mount {conn.name}: {busy} belegt, nutze {pick} (nur für diesen Mount)")
                self._set_status(tr("status.mount_other_letter", name=conn.name,
                                    drive=busy, other=pick))
                return pick
        else:
            pick = suggest_free_letter(in_use, taken_by_hosts)
            if pick is None and shared:
                pick = suggest_free_letter(in_use)

        if pick is None:
            if interactive:
                StyledMessageBox.warning(self, tr("mount.letter_busy.title"),
                                         tr("mount.letter_busy.none", drive=busy))
            self._set_status(tr("status.mount_letter_busy", name=conn.name, drive=busy))
            return None
        if not interactive:
            self._set_status(tr("status.mount_letter_busy", name=conn.name, drive=busy))
            return None

        owner = next((c for c in others if mounted.get(c.id) == wanted), None)
        by = (tr("mount.letter_busy.by_host", name=owner.name) if owner
              else tr("mount.letter_busy.by_drive"))
        if not StyledMessageBox.question(
            self, tr("mount.letter_busy.title"),
            tr("mount.letter_busy.body", drive=busy, by=by, other=pick),
            yes_text=tr("mount.letter_busy.switch", other=pick),
            no_text=tr("dialog.cancel"),
        ):
            self._set_status(tr("status.mount_letter_busy", name=conn.name, drive=busy))
            return None
        stored = self._mgr.get_by_id(conn.id)
        if stored is None:
            return None
        stored.drive_letter = pick
        self._mgr.update(stored)
        self._refresh_list()
        return pick

    def _on_mount_finished(self, conn_id: str, result):
        if conn_id in self._workers:
            self._workers[conn_id].deleteLater()
            del self._workers[conn_id]
        conn = self._mgr.get_by_id(conn_id)
        letter = self._mount_targets.pop(conn_id, None) or (conn.drive_letter if conn else "")
        card = self._cards.get(conn_id)
        if card:
            card.hide_loading()
        if result.success:
            self._letter_retry.discard(conn_id)
            self._save_active_mount(conn_id, True, letter)
            self._mounted_letters[conn_id] = letter
            if card:
                card.update_mount_state(True)
                card.set_mounted_letter(letter)
            if conn:
                self._set_status(tr("status.connected", name=conn.name, drive=letter))
            if self._panel_conn_id == conn_id:
                # Keep header mount state and panel content in sync.
                if self._panel_mode == _PANEL_EDIT:
                    # Keep any unsaved edits; just lock the connection fields.
                    self._ef_set_mount_lock(self._ef_should_lock(conn_id))
                elif self._panel_mode == _PANEL_INFO:
                    self._open_info_panel(conn_id)
                elif self._panel_mode == _PANEL_SYSINFO:
                    self._open_sysinfo_panel(conn_id)
                else:
                    self._sync_rp_mount_button(conn_id)
        else:
            name = conn.name if conn else "?"
            # The letter was taken between the check and the mount: start over,
            # which offers another letter (once, so this can never loop).
            if getattr(result, "code", "") == "drive_in_use" and conn_id not in self._letter_retry:
                self._letter_retry.add(conn_id)
                QTimer.singleShot(0, lambda: self._on_mount(conn_id))
                return
            self._letter_retry.discard(conn_id)
            # SSH Key Fallback: Wenn Key fehlschlägt aber Passwort hinterlegt ist
            if conn and conn.auth_method == "key" and conn.password:
                if self._show_key_fallback_dialog(conn):
                    # Temporär auf Passwort-Auth wechseln und retry
                    conn.auth_method = "password"
                    QTimer.singleShot(500, lambda: self._retry_mount_with_password(conn_id, conn, letter))
                    return
            if self._show_mount_failure_dialog(conn, result.message):
                QTimer.singleShot(500, lambda: self._on_mount(conn_id))
                return
            self._set_status(tr("status.connect_failed", name=name))
        self._update_status()
        self._apply_group_filter()

    def _show_key_fallback_dialog(self, conn) -> bool:
        """Zeigt Dialog an, der fragt ob mit Passwort statt Key verbunden werden soll.
        Returns True wenn User zustimmt."""
        return StyledMessageBox.question(
            self, tr("dialog.key_fallback.title"),
            tr("dialog.key_fallback.message", name=conn.name),
            yes_text=tr("dialog.key_fallback.yes"), no_text=tr("dialog.key_fallback.no")
        )

    def _retry_mount_with_password(self, conn_id: str, conn, letter: str):
        """Retry mount with password authentication (on the same letter)."""
        if conn_id in self._workers:
            return
        self._start_mount_worker(conn_id, conn, letter)

    @pyqtSlot(str)
    def _on_unmount(self, conn_id: str):
        if conn_id in self._workers:
            return
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return
        letter = self._effective_letter(conn)
        self._set_status(tr("status.disconnecting", drive=letter))
        card = self._cards.get(conn_id)
        if card:
            card.show_loading(tr("card.loading.disconnect"))
        worker = UnmountWorker(conn_id, letter, self._controller)
        worker.finished.connect(self._on_unmount_finished)
        self._workers[conn_id] = worker
        worker.start()

    def _on_unmount_finished(self, conn_id: str, result):
        try:
            worker = self._workers.pop(conn_id, None)
            if worker is not None:
                worker.finished.disconnect()
                worker.deleteLater()
        except Exception as e:
            logger.warning(f"Unmount worker cleanup error: {e}")

        try:
            conn = self._mgr.get_by_id(conn_id)
            card = self._cards.get(conn_id)
            if card:
                card.hide_loading()
            if result.success:
                self._mounted_letters.pop(conn_id, None)
                if card:
                    card.update_mount_state(False)
                    card.set_mounted_letter(None)
                self._save_active_mount(conn_id, False)
                self._set_status(tr("status.disconnected", name=conn.name if conn else "?"))
                try:
                    if self._panel_conn_id == conn_id:
                        if self._panel_mode == _PANEL_INFO:
                            self._open_info_panel(conn_id)
                        elif self._panel_mode == _PANEL_SYSINFO:
                            self._open_sysinfo_panel(conn_id)
                        elif self._panel_mode == _PANEL_EDIT:
                            self._ef_set_mount_lock(False)
                        else:
                            self._sync_rp_mount_button(conn_id)
                except Exception as e:
                    logger.warning(f"Panel refresh after unmount failed: {e}")
            else:
                self._err_popup(tr("unmount.failed.title"), result.message)
                if conn:
                    self._set_status(tr("status.disconnect_failed", name=conn.name))
        except Exception as e:
            logger.error(f"Unexpected error in unmount callback for {conn_id}: {e}")
        finally:
            try:
                self._update_status()
                self._apply_group_filter()
            except Exception:
                pass

    @pyqtSlot(str)
    def _on_ssh_requested(self, conn_id: str):
        """Dispatcher: routes to integrated xterm panel or external SSH client."""
        if self._reject_ftp_action(self._mgr.get_by_id(conn_id), "ftp.ssh_unsupported"):
            return
        settings = self._mgr.get_settings()
        if getattr(settings, "terminal_client", "ssh") == "xterm":
            self._open_terminal_panel(conn_id)
        else:
            self._on_ssh_terminal(conn_id)

    @pyqtSlot(str)
    def _on_ssh_terminal(self, conn_id: str):
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return
        if self._reject_ftp_action(conn, "ftp.ssh_unsupported"):
            return
        conn = self._prepare_auth(conn)
        if conn is None:
            return
        from src.ssh_launcher import launch_ssh_terminal
        success, error = launch_ssh_terminal(conn, self._mgr.get_settings())
        if success:
            backend = "PuTTY" if self._mgr.get_settings().use_putty else "SSH"
            self._set_status(tr("status.ssh_started", backend=backend, name=conn.name))
        else:
            self._err_popup("SSH-Terminal", error)

    def _on_ssh_terminal_with_backend(self, conn_id: str, backend: str):
        if self._reject_ftp_action(self._mgr.get_by_id(conn_id), "ftp.ssh_unsupported"):
            return
        if backend == "xterm":
            self._open_terminal_panel(conn_id)
            return

        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return
        conn = self._prepare_auth(conn)
        if conn is None:
            return

        import copy as _copy
        from src.ssh_launcher import launch_ssh_terminal
        settings = _copy.copy(self._mgr.get_settings())
        settings.terminal_client = backend
        settings.use_putty = (backend == "putty")

        success, error = launch_ssh_terminal(conn, settings)
        if success:
            backend_label = "PuTTY" if backend == "putty" else "SSH"
            self._set_status(tr("status.ssh_started", backend=backend_label, name=conn.name))
        else:
            self._err_popup("SSH-Terminal", error)

    def _open_sftp_browser(self, conn_id: str, mounted_only: bool = True):
        """
        Open a host in the file browser page (SFTP, FTP or FTPS depending on the connection).

        In mounted_only mode an SFTP connection must be mounted; FTP hosts are
        never mounted, so the requirement does not apply to them.
        """
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return
        card = self._cards.get(conn_id)
        if not card:
            return
        if mounted_only and not conn.is_ftp and not card.is_mounted:
            return

        # One browser for all hosts: every host is a tab in it. A host that
        # is open already only gets its tab brought to the front.
        browser = self._file_browser
        if browser is not None and browser.has_session(conn_id):
            if self._show_file_browser_page():
                browser.focus_host(conn_id)
            return

        if not self._guard_leave_form():
            return
        conn = self._prepare_auth(conn, parent=self)
        if conn is None:
            return
        self._show_file_browser_page(guard=False)
        self._file_browser.open_host(conn)
        if conn.is_ftp:
            self._set_status(tr(
                "status.ftp_browser_opened", name=conn.name, proto=conn.protocol_label
            ))
        else:
            self._set_status(tr("status.sftp_browser_opened", name=conn.name))

    def _on_open_mounted_path(self, conn_id: str):
        """Open the file browser for the mounted (SFTP) or FTP connection."""
        self._open_sftp_browser(conn_id, mounted_only=True)

    def _file_browser_settings(self):
        """The file browser's settings for this user."""
        if self._fb_settings is None:
            from src.filebrowser.settings import AuthManagerStore, SettingsManager
            self._fb_settings = SettingsManager(AuthManagerStore(self._mgr))
        return self._fb_settings

    def _ensure_file_browser(self):
        """The file browser, created on first use and kept until the app quits."""
        if self._file_browser is None:
            from src.filebrowser.ui.view import FileBrowserView
            theme = self._mgr.get_settings().theme or "dark"
            browser = FileBrowserView(None, self._file_browser_settings(), theme=theme,
                                      terminal_opener=self._open_terminal_at,
                                      hosts=_BrowserHosts(self), parent=self._files_page)
            self._files_page.layout().addWidget(browser)
            self._file_browser = browser
        return self._file_browser

    def _on_file_browser(self):
        """Sidebar: the file browser page (empty until a host is connected)."""
        self._show_file_browser_page()

    def _show_file_browser_page(self, guard: bool = True) -> bool:
        """Switch to the file browser page; False if an unsaved form kept the user."""
        if guard and self._panel_mode != _PANEL_FILES and not self._guard_leave_form():
            return False
        if self.isMinimized() or not self.isVisible():
            self.showNormal()                   # e.g. opened from the tray
        self.raise_()
        self.activateWindow()
        browser = self._ensure_file_browser()
        if self._panel_mode != _PANEL_FILES:
            if self._panel_conn_id and self._panel_conn_id in self._cards:
                self._cards[self._panel_conn_id].set_info_active(False)
            self._clear_fs_content()
            self._set_fullscreen_header("", "", False)
            self._panel_mode = _PANEL_FILES
            self._panel_conn_id = None
        self._main_stack.setCurrentWidget(self._files_page)
        self._set_sidebar_active("files")
        browser.focus_current()
        return True

    def _leave_file_browser_page(self) -> None:
        """Back to the connections page without touching its right panel."""
        self._main_stack.setCurrentIndex(0)
        self._panel_mode = _PANEL_NONE
        self._panel_conn_id = None
        self._set_sidebar_active("home")

    def _on_main_page_changed(self, _index: int) -> None:
        # The browser brings its own F2, Del, Esc, ...: the main window's
        # shortcuts would make them ambiguous (Qt then triggers neither).
        on_files = self._main_stack.currentWidget() is self._files_page
        for shortcut in self._shortcuts:
            shortcut.setEnabled(not on_files)

    def _confirm_quit_with_transfers(self) -> bool:
        """Ask before quitting while file browser transfers are still running."""
        browser = self._file_browser
        busy = browser.active_transfer_count() if browser is not None else 0
        if not busy:
            return True
        return StyledMessageBox.question(
            self, tr("fb.quit.title"), tr("fb.quit.text", count=busy),
            yes_text=tr("fb.quit.yes"), no_text=tr("dialog.cancel"))

    def _close_file_browser(self) -> None:
        """Disconnect the browser's hosts (the application quits)."""
        if self._file_browser is not None:
            self._file_browser.shutdown()
            self._file_browser = None

    def _open_terminal_at(self, conn_id: str, initial_input: str) -> None:
        """Integrated terminal for conn_id, started in a folder (file browser)."""
        if self.isMinimized() or not self.isVisible():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        # The terminal lives in the connections page's right panel.
        if self._panel_mode == _PANEL_FILES:
            self._leave_file_browser_page()
        elif self._main_stack.currentIndex() != 0:
            self._nav_home()
            if self._main_stack.currentIndex() != 0:   # an unsaved form kept the user
                return
        if not self._terminal_conn_tabs.get(conn_id):
            self._open_terminal_panel(conn_id, initial_input=initial_input)
            return
        self._open_terminal_panel(conn_id)
        if self._panel_mode == _PANEL_TERMINAL and self._panel_conn_id == conn_id:
            self._add_terminal_session(conn_id, initial_input)

    def _open_ftp_in_explorer(self, conn_id: str):
        """
        Hand a plain-FTP connection to the Windows Explorer FTP client.

        Only unencrypted FTP is supported by Explorer — FTPS has to stay in the
        built-in browser. The password is deliberately left out of the URL
        (Explorer asks for it) so it never lands in a shell command line or in
        Explorer's history.
        """
        conn = self._mgr.get_by_id(conn_id)
        if not conn or not conn.is_ftp:
            return
        if conn.protocol != PROTOCOL_FTP:
            self._err_popup(
                tr("ftp.mount_unsupported.title", proto=conn.protocol_label),
                tr("ftp.explorer_tls_unsupported"),
            )
            return

        user = quote(conn.user or "anonymous", safe="")
        port = f":{conn.port}" if conn.port and conn.port != 21 else ""
        path = quote((conn.remote_path or "/").replace("\\", "/"), safe="/")
        url = f"ftp://{user}@{conn.host}{port}{path}"
        try:
            subprocess.Popen(["explorer.exe", url])
            self._set_status(tr(
                "status.ftp_browser_opened", name=conn.name, proto=conn.protocol_label
            ))
        except OSError as e:
            self._err_popup(
                tr("ftp.mount_unsupported.title", proto=conn.protocol_label),
                tr("ftp.explorer_failed", url=url, err=str(e)),
            )

    @pyqtSlot(str, object)
    def _on_card_context_menu(self, conn_id: str, global_pos):
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return
        card = self._cards.get(conn_id)
        if not card:
            return

        menu = QMenu(self)
        is_mounted = bool(card.is_mounted)
        is_ftp = bool(conn.is_ftp)

        act_mount = None
        act_explorer = None
        act_explorer_ftp = None
        act_connect_ssh = None
        act_ssh_openssh = act_ssh_putty = act_ssh_xterm = None

        if is_ftp:
            # No SSHFS mount and no SSH terminal for FTP/FTPS — the browser is
            # the main action, with Windows Explorer as the plain-FTP extra.
            act_sftp = menu.addAction(
                tr("card.menu.ftp_browser", proto=conn.protocol_label)
            )
            if conn.protocol == PROTOCOL_FTP:
                act_explorer_ftp = menu.addAction(tr("card.menu.open_explorer_ftp"))
            menu.addSeparator()
        else:
            act_mount = menu.addAction(
                tr("card.menu.unmount") if is_mounted else tr("card.menu.mount")
            )
            menu.addSeparator()

            if is_mounted:
                act_explorer = menu.addAction(tr("card.menu.open_explorer"))
            act_sftp = menu.addAction(tr("card.menu.sftp_browser"))
            menu.addSeparator()

            act_connect_ssh = menu.addAction(tr("card.menu.connect_ssh"))
            ssh_menu = menu.addMenu(tr("card.menu.ssh_open_with"))
            act_ssh_openssh = ssh_menu.addAction(tr("card.menu.ssh_openssh"))
            act_ssh_putty = ssh_menu.addAction(tr("card.menu.ssh_putty"))
            act_ssh_xterm = ssh_menu.addAction(tr("card.menu.ssh_xterm"))
            menu.addSeparator()

        act_edit = menu.addAction(tr("card.menu.edit"))
        act_delete = menu.addAction(tr("card.menu.delete"))

        chosen = menu.exec(global_pos)
        if chosen is None:
            return

        if act_explorer_ftp is not None and chosen == act_explorer_ftp:
            self._open_ftp_in_explorer(conn_id)
        elif act_mount is not None and chosen == act_mount:
            if is_mounted:
                self._on_unmount(conn_id)
            else:
                self._on_mount(conn_id)
        elif act_explorer is not None and chosen == act_explorer:
            self._on_open_explorer(conn_id)
        elif chosen == act_sftp:
            self._open_sftp_browser(conn_id, mounted_only=False)
        elif act_connect_ssh is not None and chosen == act_connect_ssh:
            self._on_ssh_requested(conn_id)
        elif act_ssh_openssh is not None and chosen == act_ssh_openssh:
            self._on_ssh_terminal_with_backend(conn_id, "ssh")
        elif act_ssh_putty is not None and chosen == act_ssh_putty:
            self._on_ssh_terminal_with_backend(conn_id, "putty")
        elif act_ssh_xterm is not None and chosen == act_ssh_xterm:
            self._on_ssh_terminal_with_backend(conn_id, "xterm")
        elif chosen == act_edit:
            self._open_edit_panel(conn_id)
        elif chosen == act_delete:
            self._delete_connection(conn_id)

    def _on_open_explorer(self, conn_id: str):
        """Open the locally mounted drive in Windows Explorer."""
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return
        card = self._cards.get(conn_id)
        if not card or not card.is_mounted:
            return
        letter = self._effective_letter(conn)
        path = f"{letter.rstrip(':').rstrip(chr(92))}:\\"
        try:
            os.startfile(path)
            self._set_status(tr("status.explorer_opened", name=conn.name, drive=letter))
        except OSError as e:
            self._err_popup(tr("explorer.failed.title"), f"{path}\n\n{e}")

    def _on_settings(self):
        self._open_settings_panel()

    def _apply_settings(self):
        s = self._mgr.get_settings()
        self._apply_settings_object(s)

    def _apply_settings_object(self, s: AppSettings):
        interval = s.check_interval_seconds * 1000
        if self._poll_timer.interval() != interval:
            self._poll_timer.setInterval(interval)
        self._apply_debug_mode()
        from src.ui.theme import build_stylesheet, set_current_accent
        theme = s.theme or "dark"
        set_current_accent(getattr(s, "accent_color", ""))
        QApplication.instance().setStyleSheet(build_stylesheet(theme, current_accent()))
        self.set_app_theme(theme)          # update custom titlebar palette
        self._apply_titlebar_color(theme)  # kept for any residual DWM calls
        self._update_header_btn_icons(theme)
        self._mount_all_btn.setIcon(svg_icon("cloud", current_accent(), 16))
        # Connection cards paint their icons in the theme/accent they were
        # built with, and show duplicate-letter warnings only while letters
        # may not be shared; rebuild them when any of that changed.
        look = (theme, current_accent(), bool(getattr(s, "allow_shared_drive_letters", False)))
        if look != self._applied_look:
            self._applied_look = look
            self._refresh_list()
        # Repaint sidebar icon colors for current theme and active item.
        if self._panel_mode == _PANEL_SETTINGS:
            self._set_sidebar_active("settings")
        elif self._panel_mode == _PANEL_USERS:
            self._set_sidebar_active("users")
        elif self._panel_mode == _PANEL_PROFILE:
            self._set_sidebar_active("profile")
        elif self._panel_mode == _PANEL_FILES:
            self._set_sidebar_active("files")
        else:
            self._set_sidebar_active("home")
        if self._file_browser is not None:
            self._file_browser.set_theme(theme)

    # ── accent colour (settings panel) ────────────────────────────────────────

    def _sf_update_accent_ui(self):
        """Show the pending accent on the swatch button."""
        color = self._sf_accent
        pm = QPixmap(14, 14)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(128, 128, 128, 140), 1))
        p.setBrush(QColor(color))
        p.drawRoundedRect(0, 0, 13, 13, 4, 4)
        p.end()
        self._sf_accent_btn.setIcon(QIcon(pm))
        self._sf_accent_btn.setText(color.upper())
        self._sf_accent_reset_btn.setEnabled(color != DEFAULT_ACCENT)

    def _sf_preview_accent(self, color: str):
        """Live preview: restyle the app in *color* without saving it."""
        from src.ui.theme import build_stylesheet, set_current_accent
        set_current_accent(color)
        theme = self._mgr.get_settings().theme or "dark"
        QApplication.instance().setStyleSheet(build_stylesheet(theme, current_accent()))
        self._mount_all_btn.setIcon(svg_icon("cloud", current_accent(), 16))
        self._set_sidebar_active("settings")
        if self._file_browser is not None:
            self._file_browser.set_theme(theme)

    def _sf_set_accent(self, color: str, preview: bool):
        self._sf_accent = normalize_hex(color) or DEFAULT_ACCENT
        self._sf_update_accent_ui()
        if preview:
            self._sf_preview_accent(self._sf_accent)

    def _sf_pick_accent(self):
        from src.ui.widgets.color_picker import AccentColorDialog
        # Cancel makes the dialog preview the colour it started with again.
        chosen = AccentColorDialog.pick(self, self._sf_accent, self._sf_preview_accent)
        if chosen is not None:
            self._sf_set_accent(chosen, preview=False)

    def _sf_revert_accent_preview(self):
        """Settings discarded: go back to the saved accent if a preview changed it."""
        saved = normalize_hex(getattr(self._mgr.get_settings(), "accent_color", "")) or DEFAULT_ACCENT
        if current_accent() != saved:
            self._sf_preview_accent(saved)

    def _update_header_btn_icons(self, theme: str):
        if theme == "light":
            del_color  = "#b91c1c"
            save_color = "#16a34a"
        else:
            del_color  = "#ffffff"
            save_color = "#ffffff"
        self._rp_del_btn.setIcon(svg_icon("trash", del_color, 15))
        self._rp_save_top_btn.setIcon(svg_icon("floppy", save_color, 15))

    def _apply_titlebar_color(self, theme: str = None):
        """Update the custom titlebar theme (replaces the former DWM caption-colour hack)."""
        if theme is None:
            theme = (self._mgr.get_settings().theme or "dark")
        self.set_app_theme(theme)

    def _apply_debug_mode(self):
        enabled = self._mgr.get_settings().debug_mode
        self._debug_btn.setVisible(enabled)
        # Keep the per-card edit lock in sync with DEBUG mode so mounted hosts
        # become editable (or lock again) without rebuilding the list.
        for card in self._cards.values():
            card.set_debug_edit(enabled)

    def _on_debug(self):
        if not hasattr(self, '_debug_window') or self._debug_window is None:
            self._debug_window = DebugWindow(self)
        self._debug_window.show()
        self._debug_window.raise_()
        self._debug_window.activateWindow()

    def _on_user_management(self):
        if not Session.is_admin():
            return
        self._open_users_panel()

    def _on_change_own_password(self):
        user = Session.current()
        if not user:
            return
        from src.ui.dialogs.login_dialog import ChangePasswordDialog
        ChangePasswordDialog(user.id, self).exec()

    def _on_logout(self):
        from src.ui.dialogs.logout_dialog import LogoutConfirmDialog
        result = LogoutConfirmDialog.ask(self)
        if result == "cancel":
            return
        # "logout" unmounts all; "quit" keeps hosts mounted
        Session.logout()
        self.quit_app(unmount=(result == "logout"))

    def _on_profile(self):
        """Show user profile panel for password change."""
        if self._panel_mode == _PANEL_PROFILE:
            self._nav_home()
            return
        if not self._guard_leave_form():
            return
        if self._panel_conn_id and self._panel_conn_id in self._cards:
            self._cards[self._panel_conn_id].set_info_active(False)
        self._panel_mode = _PANEL_PROFILE
        self._panel_conn_id = None

        self._clear_fs_content()
        self._set_fullscreen_header(tr("main.profile"), tr("profile.title"), True)
        self._build_profile_form()
        self._fs_btn_bar.setVisible(False)
        self._main_stack.setCurrentIndex(1)
        self._set_sidebar_active("profile")

    def _on_about(self):
        from src.ui.dialogs.about_dialog import AboutDialog
        AboutDialog(self).exec()

    # ------------------------------------------------------------------
    # Window close
    # ------------------------------------------------------------------

    def quit_app(self, unmount: bool = True, confirm: bool = True):
        """Proper shutdown: optionally unmount drives, stop bridge, then quit."""
        if confirm and not self._confirm_quit_with_transfers():
            return
        self._explicit_quit = True
        self._close_file_browser()
        if unmount:
            self._shutdown_disconnect_all()
        if self._bridge_server:
            try:
                self._bridge_server.stop()
            except Exception:
                pass
        QApplication.quit()

    def closeEvent(self, event):
        if self._explicit_quit:
            event.accept()
            return

        settings = self._mgr.get_settings()
        if settings.minimize_to_tray:
            event.ignore()
            self.hide()
            self._tray.showMessage(
                display_name(), tr("tray.running"),
                self._tray.MessageIcon.Information, 2000,
            )
        else:
            if not self._confirm_quit_with_transfers():
                event.ignore()
                return
            event.accept()
            self.quit_app(confirm=False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)

    @pyqtSlot(str)
    def _on_log_record_for_status(self, line: str):
        lu = line.upper()
        if "[ERROR" in lu or "[CRITICAL" in lu:
            short = line.split(" — ", 1)[-1] if " — " in line else line
            self._set_status(f"⚠ Fehler: {short[:140]}")

    def _check_prerequisites(self):
        status = SSHFSController.get_install_status()
        if not status["winfsp"] and not status["sshfs_win"]:
            self._set_status(tr("prereq.missing_both"))
        elif not status["winfsp"]:
            self._set_status(tr("prereq.missing_winfsp"))
        elif not status["sshfs_win"]:
            self._set_status(tr("prereq.missing_sshfs"))
        else:
            self._set_status(tr("prereq.ok", path=status['sshfs_exe']))

    def _load_active_mounts(self):
        try:
            self._active_mounts = dict(self._mgr.get_active_mounts())
        except Exception as e:
            logger.warning(f"Konnte aktive Mounts nicht laden: {e}")
            self._active_mounts = {}

    def _save_active_mount(self, conn_id: str, mounted: bool, letter: str = ""):
        try:
            if mounted:
                from src.drive_utils import norm_letter
                letter = norm_letter(letter) or ""
                # A letter holds one mount: other records on it are stale
                # (that mount is gone) and would claim the drive for the wrong host.
                for other, other_letter in list(self._active_mounts.items()):
                    if other != conn_id and letter and norm_letter(other_letter) == letter:
                        self._mgr.remove_active_mount(other)
                        self._active_mounts.pop(other, None)
                self._mgr.add_active_mount(conn_id, letter)
                self._active_mounts[conn_id] = letter
            else:
                self._mgr.remove_active_mount(conn_id)
                self._active_mounts.pop(conn_id, None)
        except Exception as e:
            logger.warning(f"Konnte Mount-Status nicht speichern: {e}")

    def _auto_reconnect_mounts(self):
        if not self._mgr.get_settings().auto_reconnect_mounts:
            return
        if not self._active_mounts:
            return
        mounted = self._compute_mounted()
        for conn_id in list(self._active_mounts):
            if conn_id not in mounted and self._mgr.get_by_id(conn_id):
                QTimer.singleShot(1000, lambda cid=conn_id: self._mount(cid, interactive=False))

    def _on_mount_all(self):
        """Mount all connections (or filtered by selected group)."""
        selected_group = self._groups_combo.currentData()
        conns = self._mgr.get_connections()

        mounted_count = 0
        for conn in conns:
            # Filter by group if selected
            if selected_group and selected_group not in ("__all__", "__mounted__", "__unmounted__"):
                conn_groups = [g.strip() for g in (conn.groups or "").split(",") if g.strip()]
                if selected_group not in conn_groups:
                    continue

            card = self._cards.get(conn.id)
            if card and not card.is_mounted:
                self._on_mount(conn.id)
                mounted_count += 1

        if mounted_count > 0:
            self._set_status(tr("status.mount_all_started", count=mounted_count))
        else:
            self._set_status(tr("status.mount_all_none"))

    def _on_dismount_all(self):
        """Dismount all mounted connections (or filtered by selected group)."""
        selected_group = self._groups_combo.currentData()
        conns = self._mgr.get_connections()

        dismounted_count = 0
        for conn in conns:
            # Filter by group if selected
            if selected_group and selected_group not in ("__all__", "__mounted__", "__unmounted__"):
                conn_groups = [g.strip() for g in (conn.groups or "").split(",") if g.strip()]
                if selected_group not in conn_groups:
                    continue

            card = self._cards.get(conn.id)
            if card and card.is_mounted:
                self._on_unmount(conn.id)
                dismounted_count += 1

        if dismounted_count > 0:
            self._set_status(tr("status.dismount_all_started", count=dismounted_count))
        else:
            self._set_status(tr("status.dismount_all_none"))

    def _on_group_filter_changed(self, index: int):
        """Handle group filter selection change."""
        self._apply_group_filter()

    def _apply_group_filter(self):
        """Show/hide connection containers based on the active filter selection."""
        selected = self._groups_combo.currentData()
        for conn_id, container in self._containers.items():
            card = self._cards.get(conn_id)
            if selected == "__all__":
                container.setVisible(True)
            elif selected == "__mounted__":
                container.setVisible(bool(card and card.is_mounted))
            elif selected == "__unmounted__":
                container.setVisible(bool(card and not card.is_mounted))
            else:
                conn = self._mgr.get_by_id(conn_id)
                if conn:
                    conn_groups = [g.strip() for g in (conn.groups or "").split(",") if g.strip()]
                    container.setVisible(selected in conn_groups)
                else:
                    container.setVisible(False)

    def _refresh_groups_combo(self):
        """Refresh the groups filter combo with available groups."""
        prev = self._groups_combo.currentData()
        self._groups_combo.blockSignals(True)
        self._groups_combo.clear()
        self._groups_combo.addItem(tr("main.groups_all"), "__all__")
        self._groups_combo.addItem(tr("main.groups_mounted"), "__mounted__")
        self._groups_combo.addItem(tr("main.groups_unmounted"), "__unmounted__")

        # Collect all unique groups from connections
        all_groups = set()
        for conn in self._mgr.get_connections():
            if conn.groups:
                groups = [g.strip() for g in conn.groups.split(",") if g.strip()]
                all_groups.update(groups)

        for group in sorted(all_groups):
            self._groups_combo.addItem(group, group)

        # Restore previous selection if still present
        if prev:
            idx = self._groups_combo.findData(prev)
            if idx >= 0:
                self._groups_combo.setCurrentIndex(idx)
        self._groups_combo.blockSignals(False)

    def _shutdown_disconnect_all(self):
        """Schnelles Trennen beim Beenden: sshfs-Prozesse killen (sofort).
        Nur wenn das fehlschlägt, normalen Unmount als Fallback versuchen."""
        import subprocess
        any_killed = False
        for proc_name in ["sshfs.exe", "sshfs-win.exe", "sshfs-win-broker.exe"]:
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", proc_name],
                    capture_output=True, creationflags=0x08000000, timeout=5,
                )
                if result.returncode == 0:
                    any_killed = True
            except Exception:
                pass

        if any_killed:
            # Prozesse erfolgreich beendet – direkt fertig, kein weiteres Warten.
            return

        # Fallback: normaler Unmount, aber nur eigene Laufwerke (keine System-Drives).
        for conn_id in list(self._active_mounts):
            conn = self._mgr.get_by_id(conn_id)
            letter = self._effective_letter(conn) if conn else ""
            if letter:
                try:
                    self._controller.unmount(letter)
                except Exception as e:
                    logger.warning(f"Unmount {letter} fehlgeschlagen: {e}")

    def _debug_widget_under_mouse(self):
        """Debug the widget currently under the mouse cursor (triggered by F2)."""
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QCursor
        
        # Get widget under mouse cursor using global cursor position
        cursor_pos = QCursor.pos()
        widget = QApplication.widgetAt(cursor_pos)
        
        if widget:
            self._log_widget_debug_info(widget)
        else:
            msg = "DEBUG: No widget under mouse cursor"
            print(msg)
            logger.debug(msg)
            if hasattr(self, '_debug_window') and self._debug_window and not sip.isdeleted(self._debug_window):
                self._debug_window.append_log(msg + "\n")

    def _log_widget_debug_info(self, widget):
        """Log detailed widget information to debug console, logger, and statusbar."""
        # Collect widget information
        widget_info = {
            'widget_type': type(widget).__name__,
            'object_name': widget.objectName(),
            'text': getattr(widget, 'text', lambda: 'N/A')(),
            'tooltip': getattr(widget, 'toolTip', lambda: 'N/A')(),
            'accessible_name': getattr(widget, 'accessibleName', lambda: 'N/A')(),
            'parent': type(widget.parent()).__name__ if widget.parent() else None,
            'visible': widget.isVisible(),
            'enabled': widget.isEnabled(),
            'geometry': f"{widget.geometry().width()}x{widget.geometry().height()} at ({widget.geometry().x()}, {widget.geometry().y()})",
            'style_sheet': widget.styleSheet()[:100] + '...' if len(widget.styleSheet()) > 100 else widget.styleSheet()
        }
        
        # Format debug message
        debug_msg = "=== DEBUG: Widget Under Mouse ===\n"
        for key, value in widget_info.items():
            debug_msg += f"{key.upper()}: {value}\n"
        debug_msg += "================================\n"
        
        # Log to debug console
        print(debug_msg)
        
        # Log to file logger
        logger.debug(debug_msg)
        
        # Log to debug window if exists
        if hasattr(self, '_debug_window') and self._debug_window and not sip.isdeleted(self._debug_window):
            self._debug_window.append_log(debug_msg)
        
        # Log to statusbar
        status_msg = f"DEBUG: {widget_info['widget_type']} | {widget_info['object_name'] or 'No Name'} | {widget_info['text'][:30] if widget_info['text'] != 'N/A' else 'N/A'}"
        if hasattr(self, 'statusBar') and self.statusBar():
            self.statusBar().showMessage(status_msg, 5000)

    # ------------------------------------------------------------------
    # Integrated Terminal (xterm.js)
    # ------------------------------------------------------------------

    def _start_terminal_bridge(self):
        try:
            from src.terminal.bridge_server import TerminalBridgeServer
            self._bridge_server = TerminalBridgeServer()
            self._bridge_server.host_key_verify_callback = self._terminal_tofu_callback
            self._bridge_server.start()

            logger.debug("Terminal bridge server started on port %d", self._bridge_server.port)
        except Exception as e:
            logger.warning("Terminal bridge server could not start: %s", e)

    def _terminal_tofu_callback(self, host: str, port: int, fingerprint: str) -> bool:
        """Called from bridge_server thread when an unknown host key is encountered."""
        import threading
        result = threading.Event()
        accepted = [False]

        def _ask():
            from PyQt6.QtWidgets import QMessageBox
            body = tr("terminal.host_key_dialog.body").format(host=host, fingerprint=fingerprint)
            dlg = QMessageBox(self)
            dlg.setWindowTitle(tr("terminal.host_key_dialog.title"))
            dlg.setText(body)
            dlg.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            dlg.setDefaultButton(QMessageBox.StandardButton.No)
            accepted[0] = dlg.exec() == QMessageBox.StandardButton.Yes
            result.set()

        QTimer.singleShot(0, _ask)
        result.wait(timeout=30)
        return accepted[0]

    def _open_terminal_panel(self, conn_id: str, initial_input: str | None = None):
        """Switch the right panel to _PANEL_TERMINAL for conn_id, opening the first session."""
        if self._panel_mode in (_PANEL_EDIT, _PANEL_ADD):
            if not self._guard_leave_form():
                return

        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return
        if self._reject_ftp_action(conn, "ftp.ssh_unsupported"):
            return

        # If already showing terminal for same conn → just bring to front
        if self._panel_mode == _PANEL_TERMINAL and self._panel_conn_id == conn_id:
            return

        # Deactivate previous card highlight
        if self._panel_conn_id and self._panel_conn_id in self._cards:
            self._cards[self._panel_conn_id].set_info_active(False)

        self._panel_mode = _PANEL_TERMINAL
        self._panel_conn_id = conn_id

        self._set_right_panel_header("", conn.name.upper())
        self._rp_info_btn.setVisible(False)
        self._rp_edit_btn.setVisible(False)
        self._rp_terminal_btn.setVisible(False)
        self._rp_mount_btn.setVisible(False)
        self._rp_del_btn.setVisible(False)
        self._rp_save_top_btn.setVisible(False)
        self._rp_cancel_top_btn.setVisible(False)
        self._rp_close_btn.setVisible(True)
        self._rp_new_session_btn.setVisible(True)
        self._rp_btn_bar.setVisible(False)

        self._clear_right_panel_content()
        self._rp_scroll.setVisible(False)
        self._terminal_area.setVisible(True)

        # If this conn already has sessions, just restore the active tab
        if conn_id in self._terminal_conn_tabs and self._terminal_conn_tabs[conn_id]:
            self._rebuild_tab_bar(conn_id)
            active_key = self._terminal_active_tab.get(conn_id)
            if active_key:
                self._switch_terminal_tab(conn_id, active_key)
        else:
            # First session for this conn — check the free session limit
            if self._terminal_limit_reached():
                self._show_pro_session_limit_dialog()
                self._close_right_panel()
                return
            self._create_terminal_session(conn_id, initial_input=initial_input)

        self._right_panel_widget.setVisible(True)
        self._ensure_panel_sized()

    def _create_terminal_session(self, conn_id: str, initial_input: str | None = None) -> bool:
        """
        Start a new SSH session for conn_id in the background and add its tab
        once connected. The actual SSH handshake (bridge_server.create_session_token)
        runs in a TerminalConnectWorker thread — paramiko's connect() only bounds the
        TCP/banner phase with its `timeout` argument, so a slow or unresponsive auth
        phase (default auth_timeout=30s) used to freeze the whole window when this
        ran directly on the Qt main thread.
        """
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return False

        if self._bridge_server is None:
            logger.error("Terminal bridge server not running")
            return False

        if conn_id in self._terminal_connecting:
            return False

        conn_auth = self._prepare_auth(conn)
        if conn_auth is None:
            return False

        idx = self._terminal_session_counter.get(conn_id, 0) + 1
        self._terminal_session_counter[conn_id] = idx
        session_key = f"{conn_id}#{idx}"

        self._start_terminal_connect(session_key, conn_auth, initial_input)
        return True

    def _start_terminal_connect(self, session_key: str, conn_auth,
                                initial_input: str | None = None) -> None:
        conn_id = session_key.rsplit("#", 1)[0]
        self._terminal_connecting.add(conn_id)
        self._set_status(tr("terminal.connecting"))
        self._terminal_pending_conn[session_key] = conn_auth
        worker = TerminalConnectWorker(self._bridge_server, session_key, conn_auth, initial_input)
        worker.finished.connect(self._on_terminal_connected)
        self._terminal_connect_workers[session_key] = worker
        worker.start()

    def _on_terminal_connected(self, session_key: str, token: object):
        """TerminalConnectWorker finished: build the tab if the SSH session came up."""
        conn_id = session_key.rsplit("#", 1)[0]
        self._terminal_connecting.discard(conn_id)

        worker = self._terminal_connect_workers.pop(session_key, None)
        if worker:
            worker.deleteLater()
        conn_auth = self._terminal_pending_conn.pop(session_key, None)

        if token is None:
            self._err_popup(tr("terminal.connecting"), tr("terminal.error_connect"))
            return

        theme = self._mgr.get_settings().theme or "dark"
        from src.terminal.terminal_panel import TerminalPanel
        panel = TerminalPanel(self._bridge_server, session_key, conn_auth, theme, self)
        panel.reconnect_requested.connect(lambda sk: self._on_terminal_reconnect(sk))
        self._terminal_panels[session_key] = panel
        self._terminal_stack.addWidget(panel)
        panel.load_session(token)

        tabs = self._terminal_conn_tabs.setdefault(conn_id, [])
        tabs.append(session_key)
        self._terminal_active_tab[conn_id] = session_key

        self._rebuild_tab_bar(conn_id)
        self._switch_terminal_tab(conn_id, session_key)
        self._update_card_terminal_indicator(conn_id)

    def _rebuild_tab_bar(self, conn_id: str):
        """Rebuild the tab bar for the given conn_id."""
        layout = self._terminal_tab_bar_layout
        # Remove all tab buttons (keep the trailing stretch)
        while layout.count() > 1:
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        tabs = self._terminal_conn_tabs.get(conn_id, [])
        active_key = self._terminal_active_tab.get(conn_id)
        for n, sk in enumerate(tabs, start=1):
            label = tr("terminal.session_tab").format(n=n)
            btn = QPushButton(label)
            btn.setObjectName("terminalTabBtn")
            btn.setCheckable(True)
            btn.setChecked(sk == active_key)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("session_key", sk)
            btn.clicked.connect(lambda checked, _sk=sk: self._switch_terminal_tab(conn_id, _sk))
            layout.insertWidget(n - 1, btn)

        # Show tab bar only when there are multiple sessions
        self._terminal_tab_bar.setVisible(len(tabs) > 1)

    def _switch_terminal_tab(self, conn_id: str, session_key: str):
        """Activate the tab for session_key."""
        self._terminal_active_tab[conn_id] = session_key
        panel = self._terminal_panels.get(session_key)
        if panel:
            self._terminal_stack.setCurrentWidget(panel)

        # Update checked state on all tab buttons
        layout = self._terminal_tab_bar_layout
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item:
                w = item.widget()
                if w and w.objectName() == "terminalTabBtn":
                    w.setChecked(w.property("session_key") == session_key)

    def _detach_terminal_area(self):
        """Hide the terminal area and restore the scroll area (session stays alive)."""
        self._terminal_area.setVisible(False)
        self._rp_scroll.setVisible(True)
        self._rp_new_session_btn.setVisible(False)

    def _teardown_session_key(self, session_key: str):
        """Destroy one terminal panel + SSH session."""
        panel = self._terminal_panels.pop(session_key, None)
        if panel is not None:
            panel.close_session()
            self._terminal_stack.removeWidget(panel)
            panel.setParent(None)
            panel.deleteLater()
        elif self._bridge_server:
            self._bridge_server.close_session(session_key)

    def _teardown_all_terminal_sessions(self, conn_id: str):
        """Destroy all sessions for conn_id."""
        for sk in list(self._terminal_conn_tabs.get(conn_id, [])):
            self._teardown_session_key(sk)
        self._terminal_conn_tabs.pop(conn_id, None)
        self._terminal_active_tab.pop(conn_id, None)
        self._terminal_session_counter.pop(conn_id, None)
        self._update_card_terminal_indicator(conn_id)

    def _on_new_terminal_session(self):
        """Header button: open an additional SSH session for the current conn."""
        if self._panel_mode != _PANEL_TERMINAL or not self._panel_conn_id:
            return
        self._add_terminal_session(self._panel_conn_id)

    def _add_terminal_session(self, conn_id: str, initial_input: str | None = None) -> None:
        """Another session for conn_id, within the free session limit."""
        if self._terminal_limit_reached():
            self._show_pro_session_limit_dialog()
            return
        self._create_terminal_session(conn_id, initial_input=initial_input)

    def _terminal_limit_reached(self) -> bool:
        """True when the free session limit is on, reached, and Pro is not active."""
        from src import pro_manager
        limit = pro_manager.FREE_TERMINAL_SESSION_LIMIT
        if limit is None:
            return False
        total = sum(len(tabs) for tabs in self._terminal_conn_tabs.values())
        return total >= limit and not pro_manager.is_pro_active()

    def _show_pro_session_limit_dialog(self):
        StyledMessageBox.information(
            self,
            tr("pro.session_limit.title"),
            tr("pro.session_limit.body"),
        )

    def _on_end_terminal_session(self):
        """'Session beenden' button: terminate active tab; if last → close terminal panel."""
        if self._panel_mode != _PANEL_TERMINAL or not self._panel_conn_id:
            return
        conn_id = self._panel_conn_id
        active_key = self._terminal_active_tab.get(conn_id)
        if not active_key:
            return

        tabs = self._terminal_conn_tabs.get(conn_id, [])
        self._teardown_session_key(active_key)
        tabs = [sk for sk in tabs if sk != active_key]
        self._terminal_conn_tabs[conn_id] = tabs

        if not tabs:
            # No more sessions → close terminal panel
            self._teardown_all_terminal_sessions(conn_id)
            self._close_right_panel_force()
        else:
            # Switch to last remaining tab
            self._terminal_active_tab[conn_id] = tabs[-1]
            self._rebuild_tab_bar(conn_id)
            self._switch_terminal_tab(conn_id, tabs[-1])
            self._update_card_terminal_indicator(conn_id)

    def _on_terminal_reconnect(self, session_key: str):
        """User pressed 'Reconnect' in the xterm.js overlay for session_key."""
        conn_id = session_key.rsplit("#", 1)[0]
        tabs = self._terminal_conn_tabs.get(conn_id, [])
        if session_key not in tabs:
            return

        if conn_id in self._terminal_connecting:
            return

        # Destroy old session
        self._teardown_session_key(session_key)
        tabs.remove(session_key)
        self._terminal_conn_tabs[conn_id] = tabs

        # Create fresh session in its place
        conn = self._mgr.get_by_id(conn_id)
        if not conn:
            return
        conn_auth = self._prepare_auth(conn)
        if conn_auth is None:
            return
        if self._bridge_server is None:
            return

        idx = self._terminal_session_counter.get(conn_id, 0) + 1
        self._terminal_session_counter[conn_id] = idx
        new_key = f"{conn_id}#{idx}"

        self._start_terminal_connect(new_key, conn_auth)

    def _update_card_terminal_indicator(self, conn_id: str):
        """Set SSH button accent color on card when active sessions exist for conn_id."""
        card = self._cards.get(conn_id)
        if card:
            has_sessions = bool(self._terminal_conn_tabs.get(conn_id))
            card.set_terminal_active(has_sessions)

