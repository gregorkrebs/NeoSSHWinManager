"""
sftp_client.py – Synchronous SFTP client wrapping paramiko.

All public methods raise SftpClientError on failure. Intended to be called
exclusively from QThread workers so the Qt UI thread is never blocked.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from typing import Callable, Optional

import paramiko

from src.app_logger import logger
from src.config import Connection
from src.ui.host_key_utils import TOFUAcceptPolicy, get_server_fingerprint, is_host_known


@dataclass
class SftpEntry:
    """Metadata for a single remote file or directory."""

    name: str
    path: str           # absolute remote path
    size: int           # bytes; 0 for directories
    modified: float     # Unix timestamp
    permissions: str    # e.g. "drwxr-xr-x"
    is_dir: bool


class SftpClientError(Exception):
    """Raised for all SFTP-level errors (auth failures, network, IO)."""


class SftpClient:
    """
    Synchronous SFTP wrapper around paramiko.SSHClient + paramiko.SFTPClient.

    Create one instance per browser window. Call connect() before any other
    operation; call disconnect() when the window closes.
    """

    def __init__(self) -> None:
        self._ssh: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None
        self._connected: bool = False

    # ── Connection lifecycle ────────────────────────────────────────────────

    def connect(
        self,
        conn: Connection,
        *,
        tofu_callback: Optional[Callable[[str, int, str], bool]] = None,
    ) -> None:
        """
        Establish SSH + SFTP session using credentials from conn.

        tofu_callback(host, port, fingerprint) -> bool is called when the host
        is not in known_hosts. Return True to accept and save the key.
        Raises SftpClientError on any failure.
        """
        known_hosts = os.path.expanduser(r"~\.ssh\known_hosts")
        client = paramiko.SSHClient()

        if is_host_known(conn.host, conn.port, known_hosts):
            client.load_host_keys(known_hosts)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            fp = get_server_fingerprint(conn.host, conn.port)
            accepted = False
            if tofu_callback and fp:
                accepted = tofu_callback(conn.host, conn.port, fp)
            if not accepted:
                client.close()
                raise SftpClientError("Host key was rejected")
            client.set_missing_host_key_policy(TOFUAcceptPolicy(known_hosts))

        user = getattr(conn, "user", "") or getattr(conn, "ssh_user", "") or ""
        password = getattr(conn, "password", "") or ""
        key_path = getattr(conn, "key_path", "") or ""
        putty_key_path = getattr(conn, "putty_key_path", "") or ""

        try:
            if conn.auth_method == "key" and key_path:
                client.connect(
                    conn.host, port=conn.port, username=user,
                    key_filename=key_path, timeout=15,
                )
            elif conn.auth_method == "key" and putty_key_path:
                client.connect(
                    conn.host, port=conn.port, username=user,
                    key_filename=putty_key_path, timeout=15,
                )
            elif conn.auth_method in ("password", "ask") and password:
                client.connect(
                    conn.host, port=conn.port, username=user,
                    password=password, timeout=15,
                )
            else:
                client.close()
                raise SftpClientError("No usable credentials configured")
        except SftpClientError:
            raise
        except paramiko.AuthenticationException as e:
            client.close()
            raise SftpClientError("Authentication failed") from e
        except Exception as e:
            client.close()
            raise SftpClientError(str(e)) from e
        finally:
            password = ""   # wipe from local scope

        self._ssh = client
        self._sftp = client.open_sftp()
        self._connected = True
        logger.debug("SftpClient: connected to %s@%s:%d", user, conn.host, conn.port)

    def disconnect(self) -> None:
        """Close the SFTP and SSH connections. Safe to call multiple times."""
        try:
            if self._sftp:
                self._sftp.close()
        except Exception:
            pass
        try:
            if self._ssh:
                self._ssh.close()
        except Exception:
            pass
        self._sftp = None
        self._ssh = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Directory operations ────────────────────────────────────────────────

    def list_directory(self, remote_path: str) -> list[SftpEntry]:
        """
        Return sorted directory listing for remote_path.

        Directories come first, then files, both in case-insensitive alphabetical
        order. Raises SftpClientError on failure.
        """
        self._require_connected()
        try:
            attrs_list = self._sftp.listdir_attr(remote_path)
        except Exception as e:
            raise SftpClientError(str(e)) from e

        entries: list[SftpEntry] = []
        for a in attrs_list:
            if a.filename in (".", ".."):
                continue
            full = remote_path.rstrip("/") + "/" + a.filename
            is_dir = stat.S_ISDIR(a.st_mode or 0)
            perm = stat.filemode(a.st_mode or 0)
            entries.append(SftpEntry(
                name=a.filename,
                path=full,
                size=a.st_size or 0,
                modified=float(a.st_mtime or 0),
                permissions=perm,
                is_dir=is_dir,
            ))

        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def make_directory(self, remote_path: str) -> None:
        """Create a remote directory. Raises SftpClientError on failure."""
        self._require_connected()
        try:
            self._sftp.mkdir(remote_path)
        except Exception as e:
            raise SftpClientError(str(e)) from e

    def rename(self, old_path: str, new_path: str) -> None:
        """Rename/move a remote file or directory. Raises SftpClientError on failure."""
        self._require_connected()
        try:
            self._sftp.rename(old_path, new_path)
        except Exception as e:
            raise SftpClientError(str(e)) from e

    def remove(self, remote_path: str, *, is_dir: bool = False) -> None:
        """
        Delete a remote file or empty directory.

        Note: non-empty directories are not supported (sftp.rmdir requires the
        directory to be empty). Raises SftpClientError on failure.
        """
        self._require_connected()
        try:
            if is_dir:
                self._sftp.rmdir(remote_path)
            else:
                self._sftp.remove(remote_path)
        except Exception as e:
            raise SftpClientError(str(e)) from e

    # ── Transfer operations ─────────────────────────────────────────────────

    def download(
        self,
        remote_path: str,
        local_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """
        Download remote_path to local_path.

        progress_callback(bytes_transferred, total_bytes) is called periodically
        during the transfer. Raises SftpClientError on failure.
        """
        self._require_connected()
        try:
            self._sftp.get(remote_path, local_path, callback=progress_callback)
        except Exception as e:
            raise SftpClientError(str(e)) from e

    def upload(
        self,
        local_path: str,
        remote_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """
        Upload local_path to remote_path.

        progress_callback(bytes_transferred, total_bytes) is called periodically
        during the transfer. Raises SftpClientError on failure.
        """
        self._require_connected()
        try:
            self._sftp.put(local_path, remote_path, callback=progress_callback)
        except Exception as e:
            raise SftpClientError(str(e)) from e

    # ── Internal ────────────────────────────────────────────────────────────

    def _require_connected(self) -> None:
        if not self._connected:
            raise SftpClientError("Not connected to SFTP server")
