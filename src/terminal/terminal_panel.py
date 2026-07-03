"""
TerminalPanel – QWidget that embeds xterm.js via QWebEngineView.

One panel = one SSH session. The panel is kept alive in MainWindow._terminal_panels
even when the right panel switches to another mode (session persistence).
"""

from __future__ import annotations

import logging
import os
import sys

from PyQt6.QtCore import QSize, QUrl, pyqtSignal
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from src.terminal.web_channel_bridge import TerminalWebBridge

logger = logging.getLogger(__name__)

# Reconnect sentinel: bridge.resize(-1, -1) means "user pressed Reconnect"
_RECONNECT_SENTINEL_COLS = -1
_RECONNECT_SENTINEL_ROWS = -1


def _assets_dir() -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "assets", "terminal")
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "assets", "terminal",
    )


class TerminalPanel(QWidget):
    """
    Wraps QWebEngineView + QWebChannel to display an xterm.js terminal
    connected to a paramiko SSH session via TerminalBridgeServer.

    Signals:
        reconnect_requested(conn_id): user pressed the Reconnect button in JS.
    """

    reconnect_requested = pyqtSignal(str)

    def __init__(self, bridge_server, conn_id: str, conn, theme: str = "dark", parent=None):
        super().__init__(parent)
        self._bridge_server = bridge_server
        self._conn_id = conn_id
        self._conn = conn
        self._theme = theme

        self._view = QWebEngineView(self)
        self._page = QWebEnginePage(self._view)
        self._view.setPage(self._page)

        self._channel = QWebChannel(self._page)
        self._bridge = TerminalWebBridge(bridge_server, conn_id, self)
        self._channel.registerObject("bridge", self._bridge)
        self._page.setWebChannel(self._channel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._view)

        # Wire up the reconnect sentinel from the bridge
        original_resize = self._bridge.resize

        def _intercept_resize(cols: int, rows: int):
            if cols == _RECONNECT_SENTINEL_COLS and rows == _RECONNECT_SENTINEL_ROWS:
                self.reconnect_requested.emit(self._conn_id)
            else:
                original_resize(cols, rows)

        self._bridge.resize = _intercept_resize  # type: ignore[method-assign]

    def load_session(self, token: str):
        """Load the xterm.js page for the given session token."""
        port = self._bridge_server.port
        ws_url = f"ws://127.0.0.1:{port}/ws/{token}"

        from src.ui.theme import THEME_COLORS
        colors = THEME_COLORS.get(self._theme, THEME_COLORS["dark"])
        bg = colors["background"]
        fg = colors["text"]
        accent = colors["accent"]
        surface = colors["surface"]

        html = _build_html(ws_url, bg, fg, accent, surface)
        base_url = QUrl.fromLocalFile(_assets_dir() + "/")
        self._page.setHtml(html, base_url)
        logger.debug("TerminalPanel: loaded for conn %s on port %d", self._conn_id, port)

    def sizeHint(self) -> QSize:
        return QSize(620, 400)

    def is_alive(self) -> bool:
        return self._bridge_server.is_session_alive(self._conn_id)

    def close_session(self):
        """Intentionally close the SSH session without showing the disconnect overlay."""
        self._page.runJavaScript("if (window.closeSession) window.closeSession();")
        self._bridge_server.close_session(self._conn_id)


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
