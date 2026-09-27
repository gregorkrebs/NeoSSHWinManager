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
# Re-exported so callers can keep importing these from src.sftp_client.
from src.remote_path import looks_like_windows_path, normalize_remote_input
from src.ui.host_key_utils import append_known_hosts, key_fingerprint, known_hosts_line

__all__ = [
    "SftpEntry",
    "SftpClientError",
    "HostKeyRejected",
    "HostKeyChanged",
    "SftpClient",
    "looks_like_windows_path",
    "normalize_remote_input",
]


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


class HostKeyRejected(SftpClientError):
    """The host is unknown and the user did not trust its key."""

    def __init__(self, host: str, fingerprint: str) -> None:
        super().__init__("Host key was rejected")
        self.host = host
        self.fingerprint = fingerprint


class HostKeyChanged(SftpClientError):
    """The server presented a different key than the one stored in known_hosts."""

    def __init__(self, host: str, fingerprint: str, known_hosts: str) -> None:
        super().__init__(f"The host key of {host} has changed")
        self.host = host
        self.fingerprint = fingerprint
        self.known_hosts = known_hosts


# Key types that sign with the same stored key: an "ssh-rsa" entry in
# known_hosts also verifies a server that negotiates rsa-sha2-256/512.
_ALGORITHMS_FOR_KEY_TYPE = {"ssh-rsa": ("rsa-sha2-512", "rsa-sha2-256", "ssh-rsa")}

# Keys accepted during this run: a reconnect still works when known_hosts
# could not be written.
_session_keys: dict[tuple[str, str], bytes] = {}


class HostKeyVerifier(paramiko.MissingHostKeyPolicy):
    """
    Checks the server's host key against known_hosts and asks on first contact.

    paramiko's built-in check prefers only the first key type stored for a host
    and fails as soon as the server negotiates another one. Here every stored
    type is preferred, and the question shows the fingerprint of the key the
    server actually presented (no separate ssh-keyscan run that may time out
    or report a different key).
    """

    def __init__(self, host: str, port: int, known_hosts: str,
                 ask: Optional[Callable[[str, int, str], bool]]) -> None:
        self.host = host
        self.port = port
        self.known_hosts = known_hosts
        self.ask = ask
        self.name = host if port == 22 else f"[{host}]:{port}"
        self.known = self._load()

    def _load(self) -> dict:
        try:
            keys = paramiko.HostKeys(self.known_hosts) if os.path.exists(self.known_hosts) \
                else paramiko.HostKeys()
        except Exception as e:
            logger.warning("SftpClient: could not read %s: %s", self.known_hosts, e)
            return {}
        for name in dict.fromkeys((self.name, self.name.lower())):
            entry = keys.lookup(name)
            if entry:
                return {kt: entry[kt] for kt in entry.keys()}
        return {}

    def transport_factory(self, sock, **kwargs) -> paramiko.Transport:
        transport = paramiko.Transport(sock, **kwargs)
        if self.known:
            wanted = set()
            for key_type in self.known:
                wanted.update(_ALGORITHMS_FOR_KEY_TYPE.get(key_type, (key_type,)))
            opts = transport.get_security_options()
            opts.key_types = ([k for k in opts.key_types if k in wanted]
                              + [k for k in opts.key_types if k not in wanted])
        return transport

    def missing_host_key(self, client, hostname: str, key) -> None:
        key_type = key.get_name()
        stored = self.known.get(key_type)
        if stored is not None:
            if stored.asbytes() == key.asbytes():
                return
            raise HostKeyChanged(self.name, key_fingerprint(key), self.known_hosts)
        if _session_keys.get((self.name, key_type)) == key.asbytes():
            return
        fingerprint = key_fingerprint(key)
        if not (self.ask and self.ask(self.host, self.port, fingerprint)):
            raise HostKeyRejected(self.name, fingerprint)
        _session_keys[(self.name, key_type)] = key.asbytes()
        try:
            append_known_hosts(self.known_hosts, [known_hosts_line(self.name, key)])
        except OSError as e:
            logger.warning("SftpClient: could not save the host key to %s: %s",
                           self.known_hosts, e)


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
        self._is_windows: bool = False
        self._home_path: str = "/"

    @property
    def is_windows(self) -> bool:
        """True when the remote SFTP server exposes Windows-style drive paths."""
        return self._is_windows

    @property
    def home_path(self) -> str:
        """The server's default directory (from realpath('.')), or '/'."""
        return self._home_path

    @property
    def sftp(self) -> Optional[paramiko.SFTPClient]:
        """The primary SFTP channel (None before connect)."""
        return self._sftp

    @property
    def transport(self) -> Optional[paramiko.Transport]:
        """The SSH transport, for extra SFTP channels and exec sessions."""
        return self._ssh.get_transport() if self._ssh else None

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
        is not in known_hosts (or presents a key type not stored there yet).
        Return True to accept and save the key.
        Raises SftpClientError on any failure (HostKeyRejected / HostKeyChanged
        for host-key problems).
        """
        known_hosts = os.path.expanduser(r"~\.ssh\known_hosts")
        port = int(conn.port or 22)
        verifier = HostKeyVerifier(conn.host, port, known_hosts, tofu_callback)
        client = paramiko.SSHClient()
        # No keys are loaded into the client: every presented key goes through
        # the verifier, which knows all stored key types of this host.
        client.set_missing_host_key_policy(verifier)

        user = getattr(conn, "user", "") or getattr(conn, "ssh_user", "") or ""
        password = getattr(conn, "password", "") or ""
        key_path = getattr(conn, "key_path", "") or ""
        putty_key_path = getattr(conn, "putty_key_path", "") or ""
        common = dict(port=port, username=user, timeout=15,
                      transport_factory=verifier.transport_factory)

        try:
            if conn.auth_method == "key" and key_path:
                client.connect(conn.host, key_filename=key_path, **common)
            elif conn.auth_method == "key" and putty_key_path:
                client.connect(conn.host, key_filename=putty_key_path, **common)
            elif conn.auth_method in ("password", "ask") and password:
                client.connect(conn.host, password=password, **common)
            else:
                client.close()
                raise SftpClientError("No usable credentials configured")
        except SftpClientError:
            client.close()
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

        # Detect the remote OS from the server's canonical home directory.
        # Windows OpenSSH returns something like "/C:/Users/Administrator".
        try:
            home = self._sftp.normalize(".")
        except Exception:
            home = ""
        self._home_path = home or "/"
        self._is_windows = looks_like_windows_path(self._home_path)

        logger.debug(
            "SftpClient: connected to %s@%s:%d (home=%s, windows=%s)",
            user, conn.host, conn.port, self._home_path, self._is_windows,
        )

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
