"""
sftp_worker.py – QThread workers for non-blocking SFTP/FTP operations.

Each worker runs one remote operation in a background thread and emits signals
when done. Pattern mirrors src/ui/worker.py (MountWorker / UnmountWorker).

The workers only talk to the client through the shared interface implemented by
both SftpClient and FtpClient, so the same workers drive SFTP, FTP and FTPS
sessions; the browser window decides which client to hand in.
"""

from __future__ import annotations

from typing import Callable, Optional, Union

from PyQt6.QtCore import QThread, pyqtSignal

from src.ftp_client import FtpClient, FtpClientError
from src.sftp_client import SftpClient, SftpClientError, SftpEntry
from src.config import Connection

# Client implementations and their error types, interchangeable for the workers.
TransferClient = Union[SftpClient, FtpClient]
TransferError = (SftpClientError, FtpClientError)


class SftpConnectWorker(QThread):
    """Establish an SFTP (SSH) or FTP/FTPS session in a background thread."""

    connected = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        client: TransferClient,
        conn: Connection,
        tofu_callback: Optional[Callable[[str, int, str], bool]] = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._conn = conn
        self._tofu_callback = tofu_callback

    def run(self) -> None:
        try:
            self._client.connect(self._conn, tofu_callback=self._tofu_callback)
            self.connected.emit()
        except TransferError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")


class SftpListWorker(QThread):
    """List a remote directory in a background thread."""

    finished = pyqtSignal(str, list)    # remote_path, list[SftpEntry]
    error = pyqtSignal(str, str)        # remote_path, error_message

    def __init__(self, client: TransferClient, remote_path: str) -> None:
        super().__init__()
        self._client = client
        self._remote_path = remote_path

    def run(self) -> None:
        try:
            entries = self._client.list_directory(self._remote_path)
            self.finished.emit(self._remote_path, entries)
        except TransferError as e:
            self.error.emit(self._remote_path, str(e))
        except Exception as e:
            self.error.emit(self._remote_path, f"Unexpected error: {e}")


class SftpDownloadWorker(QThread):
    """Download a remote file in a background thread."""

    progress = pyqtSignal(int, int)     # bytes_done, bytes_total
    finished = pyqtSignal(str)          # local_path on success
    error = pyqtSignal(str)             # error_message

    def __init__(
        self, client: TransferClient, remote_path: str, local_path: str
    ) -> None:
        super().__init__()
        self._client = client
        self._remote_path = remote_path
        self._local_path = local_path

    def run(self) -> None:
        try:
            self._client.download(
                self._remote_path, self._local_path,
                progress_callback=self._on_progress,
            )
            self.finished.emit(self._local_path)
        except TransferError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.emit(done, total)


class SftpUploadWorker(QThread):
    """Upload a local file in a background thread."""

    progress = pyqtSignal(int, int)     # bytes_done, bytes_total
    finished = pyqtSignal(str)          # remote_path on success
    error = pyqtSignal(str)             # error_message

    def __init__(
        self, client: TransferClient, local_path: str, remote_path: str
    ) -> None:
        super().__init__()
        self._client = client
        self._local_path = local_path
        self._remote_path = remote_path

    def run(self) -> None:
        try:
            self._client.upload(
                self._local_path, self._remote_path,
                progress_callback=self._on_progress,
            )
            self.finished.emit(self._remote_path)
        except TransferError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.emit(done, total)


class SftpDeleteWorker(QThread):
    """Delete a remote file or directory in a background thread."""

    finished = pyqtSignal(str)          # deleted remote_path
    error = pyqtSignal(str)             # error_message

    def __init__(
        self, client: TransferClient, remote_path: str, is_dir: bool = False
    ) -> None:
        super().__init__()
        self._client = client
        self._remote_path = remote_path
        self._is_dir = is_dir

    def run(self) -> None:
        try:
            self._client.remove(self._remote_path, is_dir=self._is_dir)
            self.finished.emit(self._remote_path)
        except TransferError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")


class SftpRenameWorker(QThread):
    """Rename/move a remote path in a background thread."""

    finished = pyqtSignal(str, str)     # old_path, new_path
    error = pyqtSignal(str)             # error_message

    def __init__(
        self, client: TransferClient, old_path: str, new_path: str
    ) -> None:
        super().__init__()
        self._client = client
        self._old_path = old_path
        self._new_path = new_path

    def run(self) -> None:
        try:
            self._client.rename(self._old_path, self._new_path)
            self.finished.emit(self._old_path, self._new_path)
        except TransferError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")


class SftpMkdirWorker(QThread):
    """Create a remote directory in a background thread."""

    finished = pyqtSignal(str)          # created remote_path
    error = pyqtSignal(str)             # error_message

    def __init__(self, client: TransferClient, remote_path: str) -> None:
        super().__init__()
        self._client = client
        self._remote_path = remote_path

    def run(self) -> None:
        try:
            self._client.make_directory(self._remote_path)
            self.finished.emit(self._remote_path)
        except TransferError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")
