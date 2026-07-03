"""
main.py - Entry point for NEO SSH-Win Manager.
"""

import sys
import os
import threading
import traceback
from pathlib import Path

# ── 0. SSH askpass helper (MUST BE FIRST, before anything else) ───────────
# OpenSSH SSH_ASKPASS helper for non-interactive password input.
# Reads SSH_ASKPASS_TOKEN env var and fetches password via Secure IPC.
# Used by system_info_panel.py for password-based SSH connections.
if len(sys.argv) > 1 and sys.argv[1] == "--pass-helper":
    # Hardened SSH_ASKPASS helper: Fetch password from main instance via Secure IPC.
    token = os.environ.get("SSH_ASKPASS_TOKEN", "")
    if not token:
        sys.exit(1)
    
    import json
    import ctypes
    import ctypes.wintypes

    pipe_name = r"\\.\pipe\SSHWinManager_IPC_v1"
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    
    handle = ctypes.windll.kernel32.CreateFileW(
        pipe_name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None
    )
    if handle != -1:
        req = json.dumps({"action": "get_askpass", "token": token}).encode('utf-8')
        written = ctypes.wintypes.DWORD()
        ctypes.windll.kernel32.WriteFile(handle, req, len(req), ctypes.byref(written), None)
        
        buf = ctypes.create_string_buffer(4096)
        read = ctypes.wintypes.DWORD()
        if ctypes.windll.kernel32.ReadFile(handle, buf, 4096, ctypes.byref(read), None):
            try:
                resp = json.loads(buf.value[:read.value].decode('utf-8'))
                if resp.get("success"):
                    print(resp.get("password", ""), end="")
            except Exception:
                pass
        ctypes.windll.kernel32.CloseHandle(handle)
    sys.exit(0)

# ── 0.5 CLI-Modus ist nicht Sache der GUI-EXE ───────────────────────────────
# Eine --windowed EXE hat keine nutzbare stdin/stdout im Parent-Terminal.
# Für CLI-Zugriff existiert NeoSSHWinManager-cli.exe (console-subsystem).
if any(arg in sys.argv for arg in ("--connect-cli", "-connectssh")):
    import ctypes
    ctypes.windll.user32.MessageBoxW(
        None,
        "Für CLI-Zugriff bitte NeoSSHWinManager-cli.exe verwenden.\n\n"
        "Beispiel:\n  NeoSSHWinManager-cli.exe --connect-cli <key>",
        "SSH Win Manager – falscher Einstiegspunkt",
        0x30,  # MB_ICONWARNING
    )
    sys.exit(2)

# ── 1. Single-instance check (before QApplication and all others) ─────────────
from src.single_instance import ensure_single_instance
ensure_single_instance()

# ── 2. Now import everything else ────────────────────────────────
import ctypes
import json

# Ensure src/ is importable from project root
sys.path.insert(0, os.path.dirname(__file__))

def _is_admin() -> bool:
    """Check if the process is running with administrator rights."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _request_elevation() -> bool:
    """
    Restart the app with admin rights (UAC dialog).
    Returns True if the app was restarted (caller should exit).
    """
    if _is_admin():
        return False
    if "--no-elevate" in sys.argv:
        return False
    
    try:
        from src.config import get_config_path, AppSettings
        config_file = get_config_path()
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                settings = AppSettings.from_dict(data.get('settings', {}))
                if not settings.require_admin:
                    return False
    except Exception:
        pass
    
    try:
        params = " ".join(f'"{a}"' if " " in a else a for a in sys.argv[1:] if a != "--no-elevate")
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1  # SW_SHOWNORMAL
        )
        if ret > 32:
            return True
    except Exception:
        pass
    return False


from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon

from src.ui.theme import STYLESHEET, get_stylesheet
from src.ui.main_window import MainWindow
from src.database import init_db
from src.ui.dialogs.login_dialog import LoginDialog
from src.auth_manager import Session
from src.i18n import tr
from src.channel import display_name


def _install_global_exception_handlers():
    """
    Install process-wide exception handlers for UI and worker threads.
    Goal: log/notify on unexpected errors and avoid silent hard-crashes.
    """
    _in_handler = {"active": False}

    def _handle(exc_type, exc_value, exc_tb):
        # Keep standard behavior for Ctrl+C.
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        if _in_handler["active"]:
            # Avoid recursive exception handling loops.
            return
        _in_handler["active"] = True

        try:
            err_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

            # Persist for diagnostics.
            try:
                appdata = os.environ.get("APPDATA", str(Path.home()))
                report_path = Path(appdata) / "SSHWinManager" / "crash_report.txt"
                with open(report_path, "a", encoding="utf-8") as f:
                    f.write("\n" + "=" * 80 + "\n")
                    f.write(err_text)
                # SECURITY FIX: Restrict crash_report.txt to owner only
                # to prevent other local users from reading stack traces that may
                # contain connection metadata (host, user, etc.)
                try:
                    from src.database import _set_secure_permissions
                    _set_secure_permissions(report_path)
                except Exception:
                    pass
            except Exception:
                pass

            # App logger (if already initialized).
            try:
                from src.app_logger import logger as _logger
                _logger.error("UNHANDLED EXCEPTION\n%s", err_text)
            except Exception:
                pass

            # User-visible error without aborting process.
            try:
                from PyQt6.QtWidgets import QMessageBox, QPushButton
                from src.ui.icons import icon as svg_icon
                box = QMessageBox(None)
                box.setIcon(QMessageBox.Icon.Critical)
                box.setWindowTitle(tr("app.unexpected_error.title"))
                box.setText(tr("app.unexpected_error.body"))
                copy_btn = box.addButton("Details kopieren", QMessageBox.ButtonRole.ActionRole)
                copy_btn.setIcon(svg_icon("copy", "#ffffff", 14))
                copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(err_text))
                box.addButton(QMessageBox.StandardButton.Ok)
                box.exec()
            except Exception:
                # Last-resort stderr output.
                try:
                    print(err_text, file=sys.stderr)
                except Exception:
                    pass
        finally:
            _in_handler["active"] = False

    def _threading_hook(args: threading.ExceptHookArgs):
        _handle(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = _handle
    threading.excepthook = _threading_hook


def main():
    # Admin elevation only if permanently enabled in settings
    if os.name == "nt":
        try:
            from src.config import get_config_path, AppSettings
            config_file = get_config_path()
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    settings = AppSettings.from_dict(data.get('settings', {}))
                    if settings.require_admin and _request_elevation():
                        sys.exit(0)
        except Exception:
            pass

    # Enable HiDPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    try:
        with open(os.path.join(os.path.dirname(__file__), "src", "version.txt"), "r", encoding="utf-8") as f:
            APP_VERSION = f.read().strip()
    except Exception:
        APP_VERSION = "?"

    # Windows taskbar icon fix (AppUserModelID)
    try:
        myappid = f'neo.sshwinmanager.{APP_VERSION}'
        if os.name == 'nt':
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    # QtWebEngineWidgets MUST be imported before QApplication is created.
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView as _QWebEngineView  # noqa: F401
        from PyQt6.QtWebEngineCore import QWebEnginePage as _QWebEnginePage    # noqa: F401
        from PyQt6.QtWebChannel import QWebChannel as _QWebChannel              # noqa: F401
    except ImportError:
        pass  # xterm terminal feature unavailable; app still runs without it

    app = QApplication(sys.argv)
    app_name = display_name()
    app.setApplicationName(app_name)
    app.setApplicationDisplayName(app_name)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("NeoSSHWinManager")

    _install_global_exception_handlers()

    def get_resource_path(relative_path):
        if hasattr(sys, '_MEIPASS'):
            return os.path.join(sys._MEIPASS, relative_path)
        return os.path.join(os.path.dirname(__file__), relative_path)

    for icon_file in ("app_icon.ico", "app_icon.png"):
        icon_path = get_resource_path(os.path.join("assets", icon_file))
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            break

    # Init logger AFTER QApplication (QObject requires QApplication to exist)
    from src.app_logger import init_logger, logger
    init_logger()
    logger.info("Application started (Standard Mode)")

    # Apply global stylesheet
    from src.ui.theme import THEME_COLORS
    app.setStyleSheet(get_stylesheet("dark").replace("__SURFACE__", THEME_COLORS["dark"]["surface"]))
    
    # Setze Palette für native Popups
    from PyQt6.QtGui import QPalette, QColor
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(THEME_COLORS["dark"]["surface"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(THEME_COLORS["dark"]["text"]))
    app.setPalette(palette)

    # Default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # ── 3. Database Initialization ────────────────────────────────
    init_db()

    # ── 3.5 Windows Auto-Login (wenn aktiviert) ────────────────────
    windows_user = os.environ.get("USERNAME", "").strip()
    if windows_user:
        from src.auth_manager import AuthManager, Session
        user_data = AuthManager.get_user_by_username(windows_user)
        if user_data:
            # Prüfe ob Auto-Login aktiviert ist für diesen Benutzer
            from src.database import get_connection
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT auto_login FROM app_settings WHERE user_id = ?",
                    (user_data["id"],)
                ).fetchone()
                auto_login_enabled = row and bool(row["auto_login"])
            
            if auto_login_enabled:
                logger.info(f"Windows Auto-Login: Benutzer '{windows_user}' gefunden.")
                # Für Auto-Login ohne Passwort können wir den Encryption Key nicht laden
                # Wir zeigen trotzdem den Login-Dialog, aber mit vorausgefülltem Benutzernamen
                # Der Benutzer muss nur das Passwort eingeben
            else:
                logger.debug(f"Auto-Login deaktiviert für '{windows_user}'")

    # ── 4. Login / Registration ──────────────────────────────────
    login_dlg = LoginDialog()
    if login_dlg.exec() != LoginDialog.DialogCode.Accepted:
        sys.exit(0)

    if not Session.is_logged_in():
        sys.exit(0)

    # Apply user's preferred language
    try:
        from src.auth_manager import UserConnectionManager
        from src.i18n import set_language
        ucm = UserConnectionManager(Session.current())
        user_settings = ucm.get_settings()
        set_language(user_settings.language)
        app.setStyleSheet(get_stylesheet(user_settings.theme))
        
        # Telemetry Opt-In / Send
        if not getattr(user_settings, 'telemetry_prompt_shown', False):
            from src.ui.dialogs.telemetry_prompt_dialog import TelemetryPromptDialog
            from PyQt6.QtWidgets import QDialog
            prompt = TelemetryPromptDialog()
            if prompt.exec() == QDialog.DialogCode.Accepted:
                user_settings.telemetry_enabled = True
            else:
                user_settings.telemetry_enabled = False
            user_settings.telemetry_prompt_shown = True
            ucm.update_settings(user_settings)
            
            from src.telemetry import send_telemetry_async
            send_telemetry_async('install', user_settings)
        
        from src.telemetry import send_telemetry_async
        send_telemetry_async('login', user_settings)
        
    except Exception as e:
        logger.warning(f"Language/theme/telemetry init failed: {e}")

    # ── Prerequisite check: WinFSP + SSHFS-Win required ─────────────────
    from src.sshfs_controller import SSHFSController
    import webbrowser as _webbrowser
    _prereq = SSHFSController.get_install_status()
    if not _prereq["winfsp"] or not _prereq["sshfs_win"]:
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
        from PyQt6.QtCore import Qt as _Qt
        _dlg = QDialog()
        _dlg.setWindowTitle(tr("prereq.dialog.title"))
        _dlg.setMinimumWidth(440)
        _dlg.setWindowFlag(_Qt.WindowType.WindowCloseButtonHint, False)
        _vl = QVBoxLayout(_dlg)
        _vl.setSpacing(16)
        _vl.setContentsMargins(24, 24, 24, 24)
        if not _prereq["winfsp"] and not _prereq["sshfs_win"]:
            _msg = tr("prereq.dialog.text_both")
        elif not _prereq["winfsp"]:
            _msg = tr("prereq.dialog.text_winfsp")
        else:
            _msg = tr("prereq.dialog.text_sshfs")
        _lbl = QLabel(_msg)
        _lbl.setWordWrap(True)
        _vl.addWidget(_lbl)
        _btn_row = QHBoxLayout()
        _btn_row.setSpacing(8)
        if not _prereq["winfsp"]:
            _b1 = QPushButton(tr("prereq.dialog.download_winfsp"))
            _b1.clicked.connect(lambda: _webbrowser.open("https://winfsp.dev/rel/"))
            _btn_row.addWidget(_b1)
        if not _prereq["sshfs_win"]:
            _b2 = QPushButton(tr("prereq.dialog.download_sshfs"))
            _b2.clicked.connect(lambda: _webbrowser.open("https://github.com/winfsp/sshfs-win/releases/latest"))
            _btn_row.addWidget(_b2)
        _vl.addLayout(_btn_row)
        _exit_btn = QPushButton(tr("prereq.dialog.exit"))
        _exit_btn.clicked.connect(_dlg.accept)
        _vl.addWidget(_exit_btn)
        _dlg.exec()
        sys.exit(0)

    # Don't quit when the last window is hidden (tray support)
    app.setQuitOnLastWindowClosed(False)

    try:
        # Create and show main window (maximiert mit Titelleiste)
        window = MainWindow()
        window.showMaximized()

        # Start Update Check
        from src.updater import UpdaterManager
        updater = UpdaterManager(app.applicationVersion())
        
        def _on_update_available(version: str, changelog: str, download_url: str, obj_type: str):
            from src.ui.dialogs.update_dialog import UpdateDialog
            dlg = UpdateDialog(window, version, changelog, download_url, obj_type)
            dlg.start_background_download.connect(lambda: updater.download_update_async(download_url))
            updater.download_progress.connect(dlg.update_progress)
            updater.download_finished.connect(dlg.on_download_finished)
            dlg.exec()
            
        updater.update_available.connect(_on_update_available)
        app.aboutToQuit.connect(updater.install_on_exit)
        updater.check_for_updates_async()

        sys.exit(app.exec())
    except Exception as e:
        err_msg = f"FATAL CRASH during startup/main loop: {e}\n{traceback.format_exc()}"
        print(err_msg, file=sys.stderr)
        with open("crash_report.txt", "w", encoding="utf-8") as f:
            f.write(err_msg)
        try:
            from src.app_logger import logger
            logger.error(err_msg)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
