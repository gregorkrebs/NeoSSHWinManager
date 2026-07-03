"""
QWebChannel bridge object exposed to xterm.js for terminal resize signals.
"""

from __future__ import annotations
from PyQt6.QtCore import QObject, pyqtSlot


class TerminalWebBridge(QObject):
    """
    Exposed to JavaScript via QWebChannel as 'bridge'.

    xterm.js calls bridge.resize(cols, rows) when the terminal dimensions change.
    """

    def __init__(self, bridge_server, conn_id: str, parent=None):
        super().__init__(parent)
        self._bridge_server = bridge_server
        self._conn_id = conn_id

    @pyqtSlot(int, int)
    def resize(self, cols: int, rows: int):
        if cols > 0 and rows > 0:
            self._bridge_server.resize_session(self._conn_id, cols, rows)
