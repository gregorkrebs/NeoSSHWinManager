"""
ftp_client.py – Synchronous FTP / FTPS client built on the stdlib ftplib.

Mirrors the public API of src/sftp_client.SftpClient (connect / disconnect /
list_directory / make_directory / rename / remove / download / upload) so the
SFTP browser window and its QThread workers can drive either protocol.

Supported modes (Connection.protocol / Connection.ftp_implicit_tls):
    "ftp"                        – plain FTP, no encryption (port 21)
    "ftps" + implicit=False      – FTPS explicit, AUTH TLS on the control
                                   connection, PROT P for data (port 21)
    "ftps" + implicit=True       – FTPS implicit, TLS from the first byte
                                   (port 990)

Unlike an SFTP session, an FTP control connection can only carry one command at
a time, so every public method takes the same re-entrant lock. A running
transfer therefore blocks a concurrent directory listing until it finishes.
Servers also drop idle control connections, so each operation first probes the
link with NOOP and transparently re-logs-in when the server hung up.

All public methods raise FtpClientError on failure. Intended to be called
exclusively from QThread workers so the Qt UI thread is never blocked.
"""

from __future__ import annotations

import calendar
import ftplib
import os
import re
import ssl
import stat
import threading
from datetime import datetime
from typing import Callable, Optional

from src.app_logger import logger
from src.config import Connection
from src.sftp_client import SftpEntry

# The browser renders SftpEntry rows; FTP reuses the same shape.
FtpEntry = SftpEntry

_CONNECT_TIMEOUT = 20
_BLOCKSIZE = 64 * 1024


class FtpClientError(Exception):
    """Raised for all FTP-level errors (auth failures, network, IO)."""


class _ImplicitFTP_TLS(ftplib.FTP_TLS):
    """
    FTP_TLS variant for implicit FTPS (port 990).

    ftplib only implements explicit FTPS (AUTH TLS). For implicit mode the
    control socket must already be wrapped when the server sends its welcome
    banner, so the socket attribute is intercepted and wrapped on assignment.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value) -> None:
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value, server_hostname=self.host)
        self._sock = value


class FtpClient:
    """
    Synchronous FTP / FTPS wrapper around ftplib.

    Create one instance per browser window. Call connect() before any other
    operation; call disconnect() when the window closes.
    """

    def __init__(self) -> None:
        self._ftp: Optional[ftplib.FTP] = None
        self._conn: Optional[Connection] = None
        self._connected: bool = False
        self._lock = threading.RLock()

    # ── Connection lifecycle ────────────────────────────────────────────────

    def connect(
        self,
        conn: Connection,
        *,
        tofu_callback: Optional[Callable[[str, int, str], bool]] = None,
    ) -> None:
        """
        Open the control connection and log in with the credentials from conn.

        tofu_callback is accepted for API compatibility with SftpClient and
        ignored – FTP has no host keys. Server certificates are validated by
        the TLS stack unless conn.ftp_verify_cert is False.
        Raises FtpClientError on any failure.
        """
        with self._lock:
            self._conn = conn
            self._ftp = self._open_session(conn)
            self._connected = True

    def _open_session(self, conn: Connection) -> ftplib.FTP:
        """Build, connect and log in a fresh ftplib session for conn."""
        protocol = (getattr(conn, "protocol", "ftp") or "ftp").lower()
        implicit = bool(getattr(conn, "ftp_implicit_tls", False))
        use_tls = protocol == "ftps"
        port = conn.port or (990 if (use_tls and implicit) else 21)
        user = getattr(conn, "user", "") or "anonymous"
        password = getattr(conn, "password", "") or ""

        if use_tls:
            context = self._build_ssl_context(conn)
            ftp: ftplib.FTP = (
                _ImplicitFTP_TLS(context=context) if implicit
                else ftplib.FTP_TLS(context=context)
            )
        else:
            ftp = ftplib.FTP()

        try:
            ftp.connect(conn.host, port, timeout=_CONNECT_TIMEOUT)
            ftp.login(user, password)
            if use_tls:
                # Encrypt the data channel as well; without PROT P directory
                # listings and file contents would travel in the clear.
                ftp.prot_p()  # type: ignore[union-attr]
            ftp.set_pasv(bool(getattr(conn, "ftp_passive", True)))
            self._negotiate_encoding(ftp)
            ftp.voidcmd("TYPE I")
        except ftplib.error_perm as e:
            self._quiet_close(ftp)
            text = str(e)
            if text.startswith(("530", "532")):
                raise FtpClientError(f"Authentication failed: {text}") from e
            raise FtpClientError(text) from e
        except ssl.SSLError as e:
            self._quiet_close(ftp)
            raise FtpClientError(f"TLS error: {e}") from e
        except FtpClientError:
            self._quiet_close(ftp)
            raise
        except Exception as e:
            self._quiet_close(ftp)
            raise FtpClientError(str(e)) from e
        finally:
            password = ""   # wipe from local scope

        logger.debug(
            "FtpClient: connected to %s@%s:%d (%s%s)",
            user, conn.host, port, protocol,
            ", implicit TLS" if (use_tls and implicit) else "",
        )
        return ftp

    @staticmethod
    def _build_ssl_context(conn: Connection) -> ssl.SSLContext:
        context = ssl.create_default_context()
        if not bool(getattr(conn, "ftp_verify_cert", True)):
            # Opt-in for self-signed / mismatched certificates. The traffic is
            # still encrypted, but the server identity is no longer proven.
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            logger.warning(
                "FtpClient: certificate verification disabled for %s", conn.host
            )
        return context

    @staticmethod
    def _negotiate_encoding(ftp: ftplib.FTP) -> None:
        """Keep UTF-8 when the server announces it, else fall back to latin-1."""
        try:
            feat = ftp.sendcmd("FEAT")
        except Exception:
            return
        if "UTF8" in feat.upper():
            try:
                ftp.sendcmd("OPTS UTF8 ON")
            except Exception:
                pass
        else:
            # The reader was created with the old encoding in connect(); it has
            # to be rebuilt or non-ASCII file names would come back mangled.
            ftp.encoding = "latin-1"
            old_file, ftp.file = ftp.file, None
            try:
                if old_file is not None:
                    old_file.close()
            except Exception:
                pass
            ftp.file = ftp.sock.makefile("r", encoding="latin-1")  # type: ignore[union-attr]

    @staticmethod
    def _quiet_close(ftp: Optional[ftplib.FTP]) -> None:
        if ftp is None:
            return
        try:
            ftp.close()
        except Exception:
            pass

    def disconnect(self) -> None:
        """Close the control connection. Safe to call multiple times."""
        with self._lock:
            ftp, self._ftp = self._ftp, None
            self._connected = False
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:
                self._quiet_close(ftp)

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Directory operations ────────────────────────────────────────────────

    def list_directory(self, remote_path: str) -> list[SftpEntry]:
        """
        Return a sorted directory listing for remote_path.

        Uses MLSD (RFC 3659) when the server supports it and falls back to
        parsing LIST output otherwise. Directories come first, then files, both
        in case-insensitive alphabetical order.
        """
        with self._lock:
            ftp = self._require_connected()
            path = _normalize(remote_path)
            try:
                ftp.cwd(path)
            except Exception as e:
                raise FtpClientError(str(e)) from e

            entries = self._list_mlsd(ftp, path)
            if entries is None:
                entries = self._list_line_based(ftp, path)

        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def _list_mlsd(self, ftp: ftplib.FTP, path: str) -> list[SftpEntry] | None:
        """Listing via MLSD; returns None when the server does not support it."""
        entries: list[SftpEntry] = []
        try:
            for name, facts in ftp.mlsd(
                facts=["type", "size", "modify", "perm", "unix.mode"]
            ):
                entry_type = (facts.get("type") or "").lower()
                if entry_type in ("cdir", "pdir") or name in (".", ".."):
                    continue
                is_dir = entry_type in ("dir", "cdir", "pdir")
                if entry_type.startswith("os.unix=slink"):
                    # Symlink: treat as file unless the target is a directory,
                    # which MLSD does not tell us. A failed cwd is harmless.
                    is_dir = False
                entries.append(SftpEntry(
                    name=name,
                    path=_join(path, name),
                    size=_safe_int(facts.get("size")),
                    modified=_parse_mlsd_time(facts.get("modify")),
                    permissions=_perm_string(facts, is_dir),
                    is_dir=is_dir,
                ))
        except ftplib.error_perm:
            return None            # 500/502: MLSD unknown → caller falls back
        except Exception as e:
            raise FtpClientError(str(e)) from e
        return entries

    def _list_line_based(self, ftp: ftplib.FTP, path: str) -> list[SftpEntry]:
        """Listing via LIST, parsing the common Unix and Windows/IIS formats."""
        lines: list[str] = []
        try:
            ftp.retrlines("LIST", lines.append)
        except Exception as e:
            raise FtpClientError(str(e)) from e

        entries: list[SftpEntry] = []
        for line in lines:
            parsed = _parse_list_line(line)
            if parsed is None:
                continue
            name, size, modified, perms, is_dir = parsed
            if name in (".", ".."):
                continue
            entries.append(SftpEntry(
                name=name,
                path=_join(path, name),
                size=size,
                modified=modified,
                permissions=perms,
                is_dir=is_dir,
            ))
        return entries

    def make_directory(self, remote_path: str) -> None:
        """Create a remote directory. Raises FtpClientError on failure."""
        with self._lock:
            ftp = self._require_connected()
            try:
                ftp.mkd(_normalize(remote_path))
            except Exception as e:
                raise FtpClientError(str(e)) from e

    def rename(self, old_path: str, new_path: str) -> None:
        """Rename/move a remote file or directory."""
        with self._lock:
            ftp = self._require_connected()
            try:
                ftp.rename(_normalize(old_path), _normalize(new_path))
            except Exception as e:
                raise FtpClientError(str(e)) from e

    def remove(self, remote_path: str, *, is_dir: bool = False) -> None:
        """
        Delete a remote file or empty directory.

        Note: non-empty directories are not supported (RMD requires the
        directory to be empty on virtually every server).
        """
        with self._lock:
            ftp = self._require_connected()
            path = _normalize(remote_path)
            try:
                if is_dir:
                    ftp.rmd(path)
                else:
                    ftp.delete(path)
            except Exception as e:
                raise FtpClientError(str(e)) from e

    # ── Transfer operations ─────────────────────────────────────────────────

    def download(
        self,
        remote_path: str,
        local_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """
        Download remote_path to local_path.

        progress_callback(bytes_transferred, total_bytes) is called for every
        received block; total is 0 when the server does not answer SIZE.
        """
        with self._lock:
            ftp = self._require_connected()
            path = _normalize(remote_path)
            total = self._size(ftp, path)
            done = 0
            try:
                with open(local_path, "wb") as fh:
                    def _write(block: bytes) -> None:
                        nonlocal done
                        fh.write(block)
                        done += len(block)
                        if progress_callback:
                            progress_callback(done, total or done)

                    ftp.retrbinary(f"RETR {path}", _write, blocksize=_BLOCKSIZE)
            except Exception as e:
                try:
                    os.remove(local_path)   # don't leave a truncated file behind
                except OSError:
                    pass
                raise FtpClientError(str(e)) from e

    def upload(
        self,
        local_path: str,
        remote_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """
        Upload local_path to remote_path.

        progress_callback(bytes_transferred, total_bytes) is called for every
        sent block.
        """
        with self._lock:
            ftp = self._require_connected()
            path = _normalize(remote_path)
            try:
                total = os.path.getsize(local_path)
            except OSError as e:
                raise FtpClientError(str(e)) from e
            done = 0

            def _sent(block: bytes) -> None:
                nonlocal done
                done += len(block)
                if progress_callback:
                    progress_callback(done, total)

            try:
                with open(local_path, "rb") as fh:
                    ftp.storbinary(
                        f"STOR {path}", fh, blocksize=_BLOCKSIZE, callback=_sent
                    )
            except Exception as e:
                raise FtpClientError(str(e)) from e

    @staticmethod
    def _size(ftp: ftplib.FTP, path: str) -> int:
        try:
            return ftp.size(path) or 0
        except Exception:
            return 0            # SIZE is optional; progress falls back to bytes done

    # ── Internal ────────────────────────────────────────────────────────────

    def _require_connected(self) -> ftplib.FTP:
        """
        Return a usable session, reconnecting once if the server timed out.

        Idle FTP control connections are routinely closed by the server, which
        would otherwise surface as a confusing error on the next click.
        """
        if not self._connected or self._ftp is None:
            raise FtpClientError("Not connected to FTP server")
        try:
            self._ftp.voidcmd("NOOP")
            return self._ftp
        except Exception:
            logger.debug("FtpClient: control connection lost, reconnecting")

        self._quiet_close(self._ftp)
        self._ftp = None
        if self._conn is None:
            self._connected = False
            raise FtpClientError("Not connected to FTP server")
        try:
            self._ftp = self._open_session(self._conn)
        except FtpClientError:
            self._connected = False
            raise
        return self._ftp


# ── Listing helpers ─────────────────────────────────────────────────────────

def _normalize(path: str) -> str:
    """Collapse a browser path into an absolute POSIX FTP path."""
    path = (path or "/").replace("\\", "/").strip()
    if not path.startswith("/"):
        path = "/" + path
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


def _join(directory: str, name: str) -> str:
    return _normalize(directory).rstrip("/") + "/" + name


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_mlsd_time(value: Optional[str]) -> float:
    """MLSD 'modify' fact: YYYYMMDDHHMMSS[.sss] in UTC."""
    if not value:
        return 0.0
    try:
        stamp = value.split(".")[0]
        parsed = datetime.strptime(stamp, "%Y%m%d%H%M%S")
        return float(calendar.timegm(parsed.timetuple()))
    except Exception:
        return 0.0


def _perm_string(facts: dict, is_dir: bool) -> str:
    """Render a permission column from the MLSD facts a server chose to send."""
    mode = facts.get("unix.mode")
    if mode:
        try:
            return stat.filemode(
                int(mode, 8) | (stat.S_IFDIR if is_dir else stat.S_IFREG)
            )
        except (TypeError, ValueError):
            pass
    return facts.get("perm", "") or ""


# "drwxr-xr-x  2 owner group     4096 Jan 15 12:34 name"
_UNIX_LIST_RE = re.compile(
    r"^(?P<perms>[bcdlps\-][rwxSsTt\-]{9})[+@.]?\s+"
    r"\d+\s+\S+\s+\S+\s+"
    r"(?P<size>\d+)\s+"
    r"(?P<date>\w{3}\s+\d{1,2}\s+(?:\d{1,2}:\d{2}|\d{4}))\s+"
    r"(?P<name>.+)$"
)

# "01-15-26  12:34PM       <DIR>          name"  (Windows / IIS)
_DOS_LIST_RE = re.compile(
    r"^(?P<date>\d{2}-\d{2}-\d{2,4})\s+(?P<time>\d{2}:\d{2}(?:AM|PM)?)\s+"
    r"(?:(?P<dir><DIR>)|(?P<size>\d+))\s+(?P<name>.+)$",
    re.IGNORECASE,
)


def _parse_list_line(line: str) -> tuple[str, int, float, str, bool] | None:
    """Parse one LIST line into (name, size, mtime, permissions, is_dir)."""
    line = line.rstrip("\r\n")
    if not line.strip():
        return None

    m = _UNIX_LIST_RE.match(line)
    if m:
        perms = m.group("perms")
        name = m.group("name")
        is_dir = perms.startswith("d")
        if perms.startswith("l") and " -> " in name:
            # Symlink: keep the link name, drop the target.
            name = name.split(" -> ", 1)[0]
        return (
            name,
            _safe_int(m.group("size")),
            _parse_unix_list_time(m.group("date")),
            perms,
            is_dir,
        )

    m = _DOS_LIST_RE.match(line)
    if m:
        is_dir = bool(m.group("dir"))
        return (
            m.group("name"),
            _safe_int(m.group("size")),
            _parse_dos_list_time(m.group("date"), m.group("time")),
            "",
            is_dir,
        )

    return None


def _parse_unix_list_time(value: str) -> float:
    """
    'Jan 15 12:34' (current year) or 'Jan 15 2023'.

    A time-of-day entry that would land in the future belongs to last year –
    that is how ls formats anything older than six months.
    """
    parts = value.split()
    if len(parts) != 3:
        return 0.0
    month, day, last = parts
    now = datetime.now()
    try:
        if ":" in last:
            parsed = datetime.strptime(
                f"{month} {day} {now.year} {last}", "%b %d %Y %H:%M"
            )
            if parsed.timestamp() - now.timestamp() > 24 * 3600:
                parsed = parsed.replace(year=now.year - 1)
        else:
            parsed = datetime.strptime(f"{month} {day} {last}", "%b %d %Y")
        return parsed.timestamp()
    except ValueError:
        return 0.0


def _parse_dos_list_time(date: str, clock: str) -> float:
    for fmt in ("%m-%d-%y %I:%M%p", "%m-%d-%Y %I:%M%p", "%m-%d-%y %H:%M", "%m-%d-%Y %H:%M"):
        try:
            return datetime.strptime(f"{date} {clock}", fmt).timestamp()
        except ValueError:
            continue
    return 0.0
