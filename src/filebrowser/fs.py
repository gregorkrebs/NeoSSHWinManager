"""
fs.py – File systems the browser works on: local disk, SFTP and FTP/FTPS.

All three expose the same duck-typed interface (listdir, stat, mkdir, rename,
remove, walk, download/upload with resume offset, …), so panes, the transfer
queue and the sync logic never care which side they talk to.

Remote access is thread-safe:
  * SFTP: one SSH connection. Browsing uses the primary SFTP channel under a
    lock; every running transfer borrows its own extra SFTP channel from a
    small pool, so transfers run in parallel over the same login. A dropped
    connection is re-established transparently (auto-reconnect).
  * FTP: an FTP control connection carries one command at a time, so extra
    transfers get extra logged-in sessions from a pool.

Every method may raise FsError. A transfer callback raising TransferAborted
(pause/cancel) stops the transfer and propagates unchanged.
"""

from __future__ import annotations

import ctypes
import errno
import io
import os
import shutil
import socket
import stat as stat_mod
import threading
import time
from ctypes import wintypes
from datetime import datetime, timezone
from typing import Callable, Iterator, Optional

from src.app_logger import logger
from src.filebrowser.model import (
    FileEntry, lparent, rjoin, rname, rparent, sort_entries,
)

# Transfer block sizes: large blocks for speed, small ones when a rate limit
# is active so the limiter can pace smoothly.
CHUNK_FAST = 256 * 1024
CHUNK_LIMITED = 32 * 1024

DataCallback = Callable[[int], None]


class FsError(Exception):
    """Any failed file-system operation."""


class TransferAborted(BaseException):
    """
    Raised from a transfer callback to stop a transfer (pause or cancel).

    Derived from BaseException on purpose: the protocol libraries and client
    wrappers catch Exception broadly and would otherwise turn a deliberate
    stop into a generic error.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason            # "pause" | "cancel"


# ── Rate limiting ────────────────────────────────────────────────────────────

class RateLimiter:
    """
    Shared token bucket (bytes/s, 0 = unlimited) for all transfers of one
    direction. Thread-safe; the rate can change while transfers run.
    """

    def __init__(self, bytes_per_s: int = 0) -> None:
        self._rate = max(0, int(bytes_per_s))
        self._allowance = float(self._rate)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    @property
    def rate(self) -> int:
        return self._rate

    def set_rate(self, bytes_per_s: int) -> None:
        with self._lock:
            self._rate = max(0, int(bytes_per_s))
            self._allowance = min(self._allowance, float(self._rate))

    def consume(self, n: int, check: Optional[Callable[[], None]] = None) -> None:
        """Account for n bytes, sleeping as needed; check() may raise to abort."""
        with self._lock:
            rate = self._rate
            if rate <= 0:
                return
            now = time.monotonic()
            self._allowance = min(float(rate), self._allowance + (now - self._last) * rate)
            self._last = now
            self._allowance -= n
            deficit = -self._allowance
        wait = deficit / rate if deficit > 0 else 0.0
        end = time.monotonic() + wait
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            if check:
                check()
            time.sleep(min(remaining, 0.1))


# ── Local disk ───────────────────────────────────────────────────────────────

def _list_drives() -> list[str]:
    try:
        return list(os.listdrives())          # Python 3.12+, Windows only
    except (AttributeError, OSError):
        return [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]


def _recycle(paths: list[str]) -> bool:
    """Move paths to the Windows recycle bin. False if that is not possible."""
    if os.name != "nt" or not paths:
        return False

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = "\0".join(os.path.abspath(p) for p in paths) + "\0\0"
    op.fFlags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
    try:
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except Exception:
        return False
    return result == 0 and not op.fAnyOperationsAborted


class LocalFS:
    """The local disk. The path "" is a virtual root listing the drives."""

    is_local = True
    is_windows = os.name == "nt"
    can_exec = False
    can_chmod = False
    can_set_mtime = True
    root = ""

    @property
    def home(self) -> str:
        return os.path.expanduser("~")

    # paths
    def join(self, directory: str, name: str) -> str:
        return os.path.join(directory, name) if directory else name

    def parent(self, path: str) -> str:
        return lparent(path)

    def basename(self, path: str) -> str:
        return os.path.basename(path.rstrip("\\/")) or path

    # listing
    def listdir(self, path: str) -> list[FileEntry]:
        if not path:
            return [FileEntry(name=d, path=d, is_dir=True) for d in _list_drives()]
        entries: list[FileEntry] = []
        try:
            with os.scandir(path) as it:
                for de in it:
                    entries.append(self._entry(de.path, de.name))
        except OSError as e:
            raise FsError(str(e)) from e
        return sort_entries(entries)

    def _entry(self, path: str, name: str) -> FileEntry:
        try:
            st = os.stat(path)
        except OSError:
            try:
                st = os.lstat(path)
            except OSError:
                return FileEntry(name=name, path=path, is_dir=False)
        return FileEntry(
            name=name,
            path=path,
            is_dir=stat_mod.S_ISDIR(st.st_mode),
            size=0 if stat_mod.S_ISDIR(st.st_mode) else st.st_size,
            mtime=st.st_mtime,
            is_link=os.path.islink(path),
        )

    def stat(self, path: str) -> Optional[FileEntry]:
        if not os.path.lexists(path):
            return None
        return self._entry(path, self.basename(path))

    def exists(self, path: str) -> bool:
        return os.path.lexists(path)

    def walk(self, top: str) -> Iterator[tuple[str, list[FileEntry], list[FileEntry]]]:
        for dirpath, dirnames, filenames in os.walk(top):
            dirs = [self._entry(os.path.join(dirpath, n), n) for n in dirnames]
            files = [self._entry(os.path.join(dirpath, n), n) for n in filenames]
            yield dirpath, dirs, files

    # changes
    def mkdir(self, path: str) -> None:
        try:
            os.mkdir(path)
        except OSError as e:
            raise FsError(str(e)) from e

    def makedirs(self, path: str) -> None:
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            raise FsError(str(e)) from e

    def rename(self, old: str, new: str) -> None:
        # A case-only rename ("a.txt" -> "A.txt") finds the file itself.
        same = os.path.normcase(os.path.abspath(old)) == os.path.normcase(os.path.abspath(new))
        if os.path.lexists(new) and not same:
            raise FsError(f"'{self.basename(new)}' already exists")
        try:
            os.rename(old, new)
        except OSError as e:
            raise FsError(str(e)) from e

    def move(self, old: str, new: str) -> None:
        """Move into another folder, across drives too (then copy + delete)."""
        if os.path.lexists(new):
            raise FsError(f"'{self.basename(new)}' already exists")
        try:
            shutil.move(old, new)
        except (OSError, shutil.Error) as e:
            raise FsError(str(e)) from e

    def remove(self, path: str) -> None:
        try:
            os.remove(path)
        except OSError as e:
            raise FsError(str(e)) from e

    def rmdir(self, path: str) -> None:
        try:
            os.rmdir(path)
        except OSError as e:
            raise FsError(str(e)) from e

    def remove_many(self, paths: list[str]) -> None:
        """Delete files and folders, via the recycle bin where possible."""
        if _recycle(paths):
            return
        for p in paths:
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
            except OSError as e:
                raise FsError(str(e)) from e

    def create_empty(self, path: str) -> None:
        try:
            with open(path, "xb"):
                pass
        except OSError as e:
            raise FsError(str(e)) from e

    def set_mtime(self, path: str, mtime: float) -> None:
        try:
            os.utime(path, (mtime, mtime))
        except OSError as e:
            raise FsError(str(e)) from e

    def close(self) -> None:
        pass


# ── Shared remote helpers ────────────────────────────────────────────────────

class _RemoteBase:
    """Path handling and recursive helpers common to SFTP and FTP."""

    is_local = False
    root = "/"

    def join(self, directory: str, name: str) -> str:
        return rjoin(directory, name)

    def parent(self, path: str) -> str:
        return rparent(path)

    def basename(self, path: str) -> str:
        return rname(path)

    def exists(self, path: str) -> bool:
        return self.stat(path) is not None

    def move(self, old: str, new: str) -> None:
        """Move into another folder: a rename on the server."""
        self.rename(old, new)

    def makedirs(self, path: str) -> None:
        missing = []
        p = path.rstrip("/") or "/"
        while p != "/" and self.stat(p) is None:
            missing.append(p)
            p = rparent(p)
        for d in reversed(missing):
            try:
                self.mkdir(d)
            except FsError:
                if self.stat(d) is None:        # lost a race? fine if it exists now
                    raise

    def walk(self, top: str) -> Iterator[tuple[str, list[FileEntry], list[FileEntry]]]:
        entries = self.listdir(top)
        dirs = [e for e in entries if e.is_dir and not e.is_link]
        files = [e for e in entries if not e.is_dir]
        yield top, dirs, files
        for d in dirs:
            yield from self.walk(d.path)

    def rmtree(self, path: str, progress: Optional[Callable[[str], None]] = None) -> None:
        entry = self.stat(path)
        if entry is None:
            return
        if not entry.is_dir or entry.is_link:
            self.remove(path)
            return
        for child in self.listdir(path):
            if child.is_dir and not child.is_link:
                self.rmtree(child.path, progress)
            else:
                self.remove(child.path)
                if progress:
                    progress(child.path)
        self.rmdir(path)

    def remove_many(self, paths: list[str], progress: Optional[Callable[[str], None]] = None) -> None:
        for p in paths:
            self.rmtree(p, progress)


# ── SFTP ─────────────────────────────────────────────────────────────────────

def _is_connection_error(exc: BaseException) -> bool:
    import paramiko
    if isinstance(exc, (EOFError, paramiko.SSHException, socket.timeout, ConnectionError)):
        return True
    return isinstance(exc, OSError) and exc.errno in (
        None, errno.EPIPE, errno.ECONNRESET, errno.ECONNABORTED, errno.ETIMEDOUT,
    ) and not isinstance(exc, (FileNotFoundError, PermissionError, FileExistsError))


class SftpFS(_RemoteBase):
    """
    SFTP over one SSH connection.

    client       an already connected src.sftp_client.SftpClient
    reconnect    callable returning a freshly connected SftpClient, used when
                 the connection drops (None disables auto-reconnect)
    """

    can_chmod = True
    can_set_mtime = True
    can_resume = True
    protocol = "sftp"

    def __init__(self, client, reconnect: Optional[Callable[[], object]] = None,
                 max_channels: int = 6) -> None:
        self._client = client
        self._reconnect_fn = reconnect
        self._browse_lock = threading.RLock()
        self._reconnect_lock = threading.Lock()
        self._pool_lock = threading.Lock()
        self._free: list = []
        self._generation = 0
        self.max_channels = max(1, max_channels)
        self.is_windows = bool(getattr(client, "is_windows", False))
        self.home = getattr(client, "home_path", "/") or "/"
        self.on_reconnect: Optional[Callable[[bool], None]] = None
        self._can_exec: Optional[bool] = None

    # capabilities
    @property
    def can_exec(self) -> bool:
        return True

    @property
    def max_parallel(self) -> int:
        return self.max_channels

    # connection handling
    def connected(self) -> bool:
        t = self._client.transport
        return bool(t and t.is_active())

    def reconnect(self) -> bool:
        """Re-establish a dropped connection. True when connected afterwards."""
        with self._reconnect_lock:
            if self.connected():
                return True
            if self._reconnect_fn is None:
                return False
            logger.info("filebrowser: SFTP connection lost, reconnecting")
            if self.on_reconnect:
                self.on_reconnect(False)
            try:
                new_client = self._reconnect_fn()
            except Exception as e:
                logger.warning("filebrowser: reconnect failed: %s", e)
                return False
            old, self._client = self._client, new_client
            with self._pool_lock:
                self._free.clear()
                self._generation += 1
            try:
                old.disconnect()
            except Exception:
                pass
            if self.on_reconnect:
                self.on_reconnect(True)
            return True

    def _browse(self, fn):
        """Run fn(sftp) on the browse channel; reconnect once on a dropped link."""
        with self._browse_lock:
            try:
                return fn(self._client.sftp)
            except FsError:
                raise
            except Exception as e:
                # Retry only when the link is really gone: a plain SFTP
                # failure (e.g. "Failure" on mkdir) must not run twice.
                if not self.connected() and self.reconnect():
                    try:
                        return fn(self._client.sftp)
                    except Exception as e2:
                        raise FsError(_describe(e2)) from e2
                raise FsError(_describe(e)) from e

    # channel pool for transfers
    def _acquire(self):
        import paramiko
        with self._pool_lock:
            if self._free:
                return self._free.pop(), self._generation
            generation = self._generation
        if not self.connected() and not self.reconnect():
            raise FsError("Not connected")
        try:
            return paramiko.SFTPClient.from_transport(self._client.transport), generation
        except Exception as e:
            raise FsError(f"Could not open an SFTP channel: {_describe(e)}") from e

    def _release(self, channel, generation: int, broken: bool) -> None:
        with self._pool_lock:
            if not broken and generation == self._generation and len(self._free) < self.max_channels:
                self._free.append(channel)
                return
        try:
            channel.close()
        except Exception:
            pass

    # listing & metadata
    def listdir(self, path: str) -> list[FileEntry]:
        def _do(sftp):
            entries = []
            for attr in sftp.listdir_attr(path):
                if attr.filename in (".", ".."):
                    continue
                entry = FileEntry.from_sftp_attr(attr, path)
                if entry.is_link:
                    try:                          # does the link point to a folder?
                        target = sftp.stat(entry.path)
                        entry.is_dir = stat_mod.S_ISDIR(target.st_mode or 0)
                        if not entry.is_dir:
                            entry.size = int(target.st_size or 0)
                    except OSError:
                        pass
                entries.append(entry)
            return sort_entries(entries)
        return self._browse(_do)

    def stat(self, path: str) -> Optional[FileEntry]:
        def _do(sftp):
            try:
                attr = sftp.stat(path)
            except FileNotFoundError:
                return None
            attr.filename = rname(path)
            entry = FileEntry.from_sftp_attr(attr, rparent(path))
            entry.path = path
            return entry
        return self._browse(_do)

    def realpath(self, path: str) -> str:
        return self._browse(lambda sftp: sftp.normalize(path))

    # changes
    def mkdir(self, path: str) -> None:
        self._browse(lambda sftp: sftp.mkdir(path))

    def rename(self, old: str, new: str) -> None:
        if self.stat(new) is not None:
            raise FsError(f"'{rname(new)}' already exists")
        self._browse(lambda sftp: sftp.rename(old, new))

    def remove(self, path: str) -> None:
        self._browse(lambda sftp: sftp.remove(path))

    def rmdir(self, path: str) -> None:
        self._browse(lambda sftp: sftp.rmdir(path))

    def chmod(self, path: str, mode: int) -> None:
        self._browse(lambda sftp: sftp.chmod(path, mode & 0o7777))

    def set_mtime(self, path: str, mtime: float) -> None:
        self._browse(lambda sftp: sftp.utime(path, (mtime, mtime)))

    def create_empty(self, path: str) -> None:
        if self.stat(path) is not None:
            raise FsError(f"'{rname(path)}' already exists")

        def _do(sftp):
            with sftp.open(path, "w"):
                pass
        self._browse(_do)

    # transfers
    def download(self, remote: str, local: str, offset: int, on_data: DataCallback,
                 limited: bool = False) -> None:
        channel, gen = self._acquire()
        broken = False
        try:
            with channel.open(remote, "rb") as rf:
                size = rf.stat().st_size or 0
                if offset:
                    rf.seek(offset)
                if not limited and size > offset:
                    rf.prefetch(size)
                mode = "r+b" if offset else "wb"
                with open(local, mode) as lf:
                    if offset:
                        lf.seek(offset)
                        lf.truncate()
                    block = CHUNK_LIMITED if limited else CHUNK_FAST
                    while True:
                        data = rf.read(block)
                        if not data:
                            break
                        lf.write(data)
                        on_data(len(data))
        except TransferAborted:
            broken = True                 # a half-read prefetch poisons the channel
            raise
        except OSError as e:
            broken = _is_connection_error(e) or not self.connected()
            raise FsError(_describe(e)) from e
        except Exception as e:
            broken = True
            raise FsError(_describe(e)) from e
        finally:
            self._release(channel, gen, broken)

    def upload(self, local: str, remote: str, offset: int, on_data: DataCallback,
               limited: bool = False) -> None:
        with open(local, "rb") as fp:
            if offset:
                fp.seek(offset)
            self.upload_stream(fp, remote, on_data, append_at=offset, limited=limited)

    def upload_stream(self, fp, remote: str, on_data: DataCallback, append_at: int = 0,
                      limited: bool = False) -> None:
        channel, gen = self._acquire()
        broken = False
        try:
            with channel.open(remote, "r+" if append_at else "w") as rf:
                if append_at:
                    rf.seek(append_at)
                rf.set_pipelined(True)
                block = CHUNK_LIMITED if limited else CHUNK_FAST
                while True:
                    data = fp.read(block)
                    if not data:
                        break
                    rf.write(data)
                    on_data(len(data))
        except TransferAborted:
            broken = True
            raise
        except OSError as e:
            broken = _is_connection_error(e) or not self.connected()
            raise FsError(_describe(e)) from e
        except Exception as e:
            broken = True
            raise FsError(_describe(e)) from e
        finally:
            self._release(channel, gen, broken)

    # remote commands
    def run(self, command: str, timeout: float = 120.0,
            should_stop: Optional[Callable[[], bool]] = None) -> tuple[int, str, str]:
        """Run a shell command over SSH exec: (exit code, stdout, stderr)."""
        if not self.connected() and not self.reconnect():
            raise FsError("Not connected")
        try:
            chan = self._client.transport.open_session()
            chan.exec_command(command)
        except Exception as e:
            raise FsError(f"SSH exec failed: {_describe(e)}") from e
        out, err = bytearray(), bytearray()
        deadline = time.monotonic() + timeout
        try:
            while True:
                progressed = False
                if chan.recv_ready():
                    out += chan.recv(65536)
                    progressed = True
                if chan.recv_stderr_ready():
                    err += chan.recv_stderr(65536)
                    progressed = True
                if (chan.exit_status_ready() and not chan.recv_ready()
                        and not chan.recv_stderr_ready()):
                    break
                if not progressed:
                    if time.monotonic() > deadline:
                        raise FsError("Command timed out")
                    if should_stop and should_stop():
                        raise TransferAborted("cancel")
                    time.sleep(0.02)
            code = chan.recv_exit_status()
        finally:
            try:
                chan.close()
            except Exception:
                pass
        return code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    def close(self) -> None:
        with self._pool_lock:
            channels, self._free = self._free, []
        for ch in channels:
            try:
                ch.close()
            except Exception:
                pass
        try:
            self._client.disconnect()
        except Exception:
            pass


def _describe(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    if isinstance(exc, FileNotFoundError):
        return f"No such file or folder ({text})"
    if isinstance(exc, PermissionError):
        return f"Permission denied ({text})"
    return text


# ── FTP / FTPS ───────────────────────────────────────────────────────────────

def mode_from_perm_string(perms: str, is_dir: bool) -> int:
    """'drwxr-xr-x' -> S_IFDIR | 0o755; 0 for non-ls permission strings."""
    if len(perms) != 10 or perms[0] not in "-dlbcps":
        return 0
    bits = 0
    for i, ch in enumerate(perms[1:]):
        if ch not in "-":
            bits |= 1 << (8 - i)
    return (stat_mod.S_IFDIR if is_dir else stat_mod.S_IFREG) | bits


def _mdtm_stamp(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y%m%d%H%M%S")


class FtpFS(_RemoteBase):
    """
    FTP/FTPS via src.ftp_client.FtpClient.

    client    the connected browse session
    factory   callable returning a new connected FtpClient (transfer pool)
    """

    is_windows = False
    can_chmod = True           # SITE CHMOD, where the server supports it
    can_set_mtime = True       # MFMT, where the server supports it
    can_resume = True
    protocol = "ftp"

    def __init__(self, client, factory: Callable[[], object], max_sessions: int = 2) -> None:
        self._client = client
        self._factory = factory
        self._pool_lock = threading.Lock()
        self._free: list = []
        self.max_sessions = max(1, max_sessions)
        self.home = getattr(client, "home_path", "/") or "/"
        self._mlst_ok = True
        self.on_reconnect: Optional[Callable[[bool], None]] = None

    @property
    def can_exec(self) -> bool:
        return False

    @property
    def max_parallel(self) -> int:
        return self.max_sessions

    def connected(self) -> bool:
        return bool(getattr(self._client, "is_connected", False))

    def reconnect(self) -> bool:
        return self.connected()     # FtpClient re-logs-in by itself on the next call

    def _wrap(self, fn):
        try:
            return fn()
        except FsError:
            raise
        except Exception as e:
            raise FsError(str(e)) from e

    def listdir(self, path: str) -> list[FileEntry]:
        rows = self._wrap(lambda: self._client.list_directory(path))
        return sort_entries(
            FileEntry(
                name=r.name, path=r.path, is_dir=r.is_dir, size=r.size,
                mtime=r.modified, mode=mode_from_perm_string(r.permissions or "", r.is_dir),
            )
            for r in rows
        )

    def stat(self, path: str) -> Optional[FileEntry]:
        if path in ("", "/"):
            return FileEntry(name="/", path="/", is_dir=True)
        if self._mlst_ok:
            try:
                facts = self._client.mlst(path)
            except Exception as e:
                if "unsupported" in str(e).lower():
                    self._mlst_ok = False
                else:
                    raise FsError(str(e)) from e
            else:
                if facts is None:
                    return None
                from src.ftp_client import _parse_mlsd_time, _safe_int
                kind = facts.get("type", "").lower()
                is_dir = kind in ("dir", "cdir", "pdir")
                return FileEntry(
                    name=rname(path), path=path, is_dir=is_dir,
                    size=_safe_int(facts.get("size")),
                    mtime=_parse_mlsd_time(facts.get("modify")),
                )
        name = rname(path)
        try:
            siblings = self.listdir(rparent(path))
        except FsError:
            return None
        return next((e for e in siblings if e.name == name), None)

    def mkdir(self, path: str) -> None:
        self._wrap(lambda: self._client.make_directory(path))

    def rename(self, old: str, new: str) -> None:
        if self.stat(new) is not None:
            raise FsError(f"'{rname(new)}' already exists")
        self._wrap(lambda: self._client.rename(old, new))

    def remove(self, path: str) -> None:
        self._wrap(lambda: self._client.remove(path, is_dir=False))

    def rmdir(self, path: str) -> None:
        self._wrap(lambda: self._client.remove(path, is_dir=True))

    def chmod(self, path: str, mode: int) -> None:
        self._wrap(lambda: self._client.command(f"SITE CHMOD {mode & 0o7777:o} {path}"))

    def set_mtime(self, path: str, mtime: float) -> None:
        try:
            self._client.command(f"MFMT {_mdtm_stamp(mtime)} {path}")
        except Exception:
            pass                    # optional extension; keeping the upload is what matters

    def create_empty(self, path: str) -> None:
        if self.stat(path) is not None:
            raise FsError(f"'{rname(path)}' already exists")
        self._wrap(lambda: self._client.store(path, io.BytesIO(b""), lambda _b: None))

    # transfer sessions
    def _acquire(self):
        with self._pool_lock:
            if self._free:
                return self._free.pop()
        try:
            return self._factory()
        except Exception as e:
            raise FsError(str(e)) from e

    def _release(self, session, broken: bool) -> None:
        if not broken:
            with self._pool_lock:
                if len(self._free) < self.max_sessions:
                    self._free.append(session)
                    return
        try:
            session.disconnect()
        except Exception:
            pass

    def download(self, remote: str, local: str, offset: int, on_data: DataCallback,
                 limited: bool = False) -> None:
        session = self._acquire()
        broken = False
        try:
            with open(local, "r+b" if offset else "wb") as lf:
                if offset:
                    lf.seek(offset)
                    lf.truncate()

                def _block(data: bytes) -> None:
                    lf.write(data)
                    on_data(len(data))

                session.retrieve(remote, _block, rest=offset)
        except TransferAborted:
            broken = True          # the data connection was cut mid-transfer
            raise
        except Exception as e:
            broken = True
            raise FsError(str(e)) from e
        finally:
            self._release(session, broken)

    def upload(self, local: str, remote: str, offset: int, on_data: DataCallback,
               limited: bool = False) -> None:
        with open(local, "rb") as fp:
            if offset:
                fp.seek(offset)
            self.upload_stream(fp, remote, on_data, append_at=offset, limited=limited)

    def upload_stream(self, fp, remote: str, on_data: DataCallback, append_at: int = 0,
                      limited: bool = False) -> None:
        session = self._acquire()
        broken = False
        try:
            session.store(remote, fp, lambda block: on_data(len(block)), append=bool(append_at))
        except TransferAborted:
            broken = True
            raise
        except Exception as e:
            broken = True
            raise FsError(str(e)) from e
        finally:
            self._release(session, broken)

    def run(self, command: str, timeout: float = 120.0, should_stop=None):
        raise FsError("Remote commands need SSH (SFTP)")

    def close(self) -> None:
        with self._pool_lock:
            sessions, self._free = self._free, []
        for s in sessions + [self._client]:
            try:
                s.disconnect()
            except Exception:
                pass
