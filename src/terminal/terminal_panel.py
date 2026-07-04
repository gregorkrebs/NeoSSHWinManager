"""
TerminalPanel - QWidget that embeds xterm.js via pywebview (WebView2).

Replaces the former QWebEngineView / QWebChannel implementation to eliminate
the ~200 MB PyQt6-WebEngine / Chromium dependency.  WebView2 is part of every
Windows 10 (post-2021) / Windows 11 installation - nothing extra is bundled.

Architecture
-------------
- pywebview runs in a background daemon thread (webview_host.py).
- Each session gets one pywebview window created with hidden=True.
- After the page loads (events.loaded, webview thread), the window HWND is
  located via Win32 FindWindowW, style set to WS_CHILD, and embedded into this
  QWidget via SetParent - all from the webview thread (same thread that created
  the window, as MSDN requires for SetWindowLong).
- Resize is forwarded asynchronously via SWP_ASYNCWINDOWPOS to avoid
  cross-thread SendMessage blocking.
- PTY resize travels: JS -> WebSocket JSON control message -> bridge_server.
- Reconnect travels: JS -> pywebview js_api -> _TerminalAPI.reconnect()
  -> QMetaObject.invokeMethod (QueuedConnection) -> Qt main thread signal.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import sys
import uuid

from PyQt6.QtCore import QMetaObject, QSize, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

# -- Win32 constants -----------------------------------------------------------
_GWL_STYLE      = -16
_WS_CHILD       = 0x40000000
_WS_VISIBLE     = 0x10000000
_WS_POPUP       = 0x80000000
_WS_CAPTION     = 0x00C00000
_WS_THICKFRAME  = 0x00040000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_SYSMENU     = 0x00080000
_SWP_NOZORDER       = 0x0004
_SWP_FRAMECHANGED   = 0x0020
_SWP_SHOWWINDOW     = 0x0040
_SWP_ASYNCWINDOWPOS = 0x4000

_u32 = ctypes.windll.user32
_u32.FindWindowW.restype      = ctypes.wintypes.HWND
_u32.FindWindowW.argtypes     = [ctypes.wintypes.LPCWSTR, ctypes.wintypes.LPCWSTR]
_u32.GetWindowLongW.restype   = ctypes.c_long
_u32.GetWindowLongW.argtypes  = [ctypes.wintypes.HWND, ctypes.c_int]
_u32.SetWindowLongW.restype   = ctypes.c_long
_u32.SetWindowLongW.argtypes  = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_long]
_u32.SetParent.restype        = ctypes.wintypes.HWND
_u32.SetParent.argtypes       = [ctypes.wintypes.HWND, ctypes.wintypes.HWND]
_u32.SetWindowPos.restype     = ctypes.wintypes.BOOL
_u32.SetWindowPos.argtypes    = [
    ctypes.wintypes.HWND, ctypes.wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]


def _assets_dir() -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "assets", "terminal")
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "assets", "terminal",
    )


# -- JS API exposed to xterm.js via pywebview ----------------------------------

class _TerminalAPI:
    """Exposed to JavaScript as window.pywebview.api (pywebview js_api)."""

    def __init__(self, on_reconnect):
        self._on_reconnect = on_reconnect

    def reconnect(self):
        """Called from JS when the user clicks the Reconnect button."""
        self._on_reconnect()


# -- TerminalPanel -------------------------------------------------------------

class TerminalPanel(QWidget):
    """
    Embeds a pywebview WebView2 window inside this QWidget via Win32 SetParent.

    Signals:
        reconnect_requested(conn_id): user pressed the Reconnect button in JS.
    """

    reconnect_requested = pyqtSignal(str)

    def __init__(self, bridge_server, conn_id: str, conn,
                 theme: str = "dark", parent=None):
        super().__init__(parent)
        self._bridge_server = bridge_server
        self._conn_id = conn_id
        self._conn = conn
        self._theme = theme

        self._wv_window = None
        self._wv_hwnd: int = 0
        self._pending_wv_title: str = ""
        self._qt_hwnd: int = 0

        self._api = _TerminalAPI(self._request_reconnect_threadsafe)

        # Ensure Qt creates a real HWND immediately (required for winId()).
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)

    # -- Reconnect: JS -> pywebview thread -> Qt main thread -------------------

    def _request_reconnect_threadsafe(self):
        """Called from the pywebview background thread."""
        QMetaObject.invokeMethod(
            self, "_emit_reconnect_signal", Qt.ConnectionType.QueuedConnection
        )

    @pyqtSlot()
    def _emit_reconnect_signal(self):
        self.reconnect_requested.emit(self._conn_id)

    # -- Session management ----------------------------------------------------

    def load_session(self, token: str):
        """Create a pywebview window and embed it once the page is loaded."""
        from src.terminal.webview_host import get_webview_host
        get_webview_host()  # ensure background thread is running

        from src.ui.theme import THEME_COLORS
        colors = THEME_COLORS.get(self._theme, THEME_COLORS["dark"])
        port = self._bridge_server.port
        ws_url = f"ws://127.0.0.1:{port}/ws/{token}"
        html = _build_html(
            ws_url,
            colors["background"],
            colors["text"],
            colors["accent"],
            colors["surface"],
        )

        # Cache Qt HWND now (must be read on Qt thread).
        self.ensurePolished()
        self._qt_hwnd = int(self.winId())

        import webview

        win_title = f"neoterm-{uuid.uuid4().hex}"
        self._pending_wv_title = win_title

        self._wv_window = webview.create_window(
            win_title,
            html=html,
            width=max(self.width(), 400),
            height=max(self.height(), 300),
            frameless=True,
            easy_drag=False,
            resizable=False,
            js_api=self._api,
            hidden=True,
        )

        # events.loaded fires from the pywebview background thread.
        self._wv_window.events.loaded += self._on_wv_loaded
        logger.debug("TerminalPanel: load_session for %s", self._conn_id)

    def _on_wv_loaded(self):
        """
        Runs on the pywebview background thread (same thread that created the
        window). Performs Win32 embedding here per MSDN guidance.
        """
        win_title = self._pending_wv_title
        if not win_title:
            return
        self._pending_wv_title = ""

        hwnd = _u32.FindWindowW(None, win_title)
        if not hwnd:
            logger.warning(
                "TerminalPanel: FindWindowW found nothing for '%s'", win_title
            )
            return

        qt_hwnd = self._qt_hwnd  # set on Qt thread before window creation

        # Strip top-level decoration styles; add WS_CHILD.
        style = _u32.GetWindowLongW(hwnd, _GWL_STYLE)
        style &= ~(
            _WS_POPUP | _WS_CAPTION | _WS_THICKFRAME |
            _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX | _WS_SYSMENU
        )
        style |= _WS_CHILD | _WS_VISIBLE
        _u32.SetWindowLongW(hwnd, _GWL_STYLE, style)

        # Re-parent into the Qt widget.
        _u32.SetParent(hwnd, qt_hwnd)

        # Store HWND (Python GIL makes this assignment atomic).
        self._wv_hwnd = hwnd

        # Final resize + show - deferred to the Qt main thread.
        QMetaObject.invokeMethod(
            self, "_show_embedded_webview", Qt.ConnectionType.QueuedConnection
        )
        logger.debug(
            "TerminalPanel: SetParent done HWND=%d -> Qt HWND=%d", hwnd, qt_hwnd
        )

    @pyqtSlot()
    def _show_embedded_webview(self):
        """Runs on Qt main thread - apply initial size and make child visible."""
        if not self._wv_hwnd:
            return
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        _u32.SetWindowPos(
            self._wv_hwnd, 0, 0, 0, w, h,
            _SWP_NOZORDER | _SWP_FRAMECHANGED | _SWP_SHOWWINDOW,
        )
        logger.debug("TerminalPanel: visible at %dx%d", w, h)

    def is_alive(self) -> bool:
        return self._bridge_server.is_session_alive(self._conn_id)

    def close_session(self):
        """Intentionally close the SSH session."""
        if self._wv_window:
            try:
                self._wv_window.evaluate_js(
                    "if (window.closeSession) window.closeSession();"
                )
            except Exception:
                pass
            try:
                self._wv_window.destroy()
            except Exception:
                pass
            self._wv_window = None
            self._wv_hwnd = 0
        self._bridge_server.close_session(self._conn_id)

    # -- Qt event overrides ----------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._wv_hwnd:
            w = max(event.size().width(), 1)
            h = max(event.size().height(), 1)
            # SWP_ASYNCWINDOWPOS avoids cross-thread SendMessage blocking.
            _u32.SetWindowPos(
                self._wv_hwnd, 0, 0, 0, w, h,
                _SWP_NOZORDER | _SWP_ASYNCWINDOWPOS,
            )

    def sizeHint(self) -> QSize:
        return QSize(620, 400)


# -- HTML builder --------------------------------------------------------------

def _build_html(ws_url: str, bg: str, fg: str, accent: str, surface: str = "") -> str:
    template_path = os.path.join(_assets_dir(), "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    from src.i18n import tr
    html = (
        html
        .replace("{{WS_URL}}", ws_url)
        .replace("{{BG}}", bg)
        .replace("{{SURFACE}}", surface or bg)
        .replace("{{FG}}", fg)
        .replace("{{ACCENT}}", accent)
        .replace("{{MSG_CONNECTING}}", tr("terminal.connecting"))
        .replace("{{MSG_CONNECTED}}", tr("terminal.connected"))
        .replace("{{MSG_DISCONNECTED}}", tr("terminal.disconnected"))
        .replace("{{MSG_RECONNECT}}", tr("terminal.reconnect"))
    )
    return html