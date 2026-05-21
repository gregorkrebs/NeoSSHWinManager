"""
worker.py – Asynchronous workers for background tasks.
"""

from PyQt6.QtCore import QThread, pyqtSignal
from src.sshfs_controller import SSHFSController, MountResult
from src.config import Connection


class MountWorker(QThread):
    """
    Worker thread to handle mount operations without blocking the UI.
    """
    finished = pyqtSignal(str, MountResult)  # conn_id, result

    def __init__(self, conn: Connection, controller: SSHFSController, disable_cache: bool = False):
        super().__init__()
        self.conn = conn
        self.controller = controller
        self.disable_cache = disable_cache

    def run(self):
        try:
            result = self.controller.mount(self.conn, disable_cache=self.disable_cache)
            self.finished.emit(self.conn.id, result)
        except Exception as e:
            self.finished.emit(self.conn.id, MountResult(False, f"Thread Error: {str(e)}"))


class UnmountWorker(QThread):
    """
    Worker thread to handle unmount operations without blocking the UI.
    """
    finished = pyqtSignal(str, MountResult)  # conn_id, result

    def __init__(self, conn_id: str, drive_letter: str, controller: SSHFSController):
        super().__init__()
        self.conn_id = conn_id
        self.drive_letter = drive_letter
        self.controller = controller

    def run(self):
        try:
            result = self.controller.unmount(self.drive_letter)
            self.finished.emit(self.conn_id, result)
        except Exception as e:
            self.finished.emit(self.conn_id, MountResult(False, f"Thread Error: {str(e)}"))
