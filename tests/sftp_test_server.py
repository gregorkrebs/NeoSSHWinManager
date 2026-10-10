"""
A tiny SFTP server for integration tests (paramiko, localhost, temp dir).

    with SftpTestServer(root_dir) as server:
        client = server.connect()        # object shaped like src.sftp_client.SftpClient

The server serves `root_dir` as "/" with password auth ("user"/"pass"). It
never touches ~/.ssh: the client side trusts the generated host key directly.
"""

from __future__ import annotations

import os
import posixpath
import socket
import threading

import paramiko
from paramiko import (
    SFTP_FAILURE, SFTP_NO_SUCH_FILE, SFTP_OK, SFTP_PERMISSION_DENIED,
    SFTPAttributes, SFTPHandle, SFTPServer, SFTPServerInterface, ServerInterface,
)


def _errno_to_sftp(e: OSError) -> int:
    import errno
    if e.errno == errno.ENOENT:
        return SFTP_NO_SUCH_FILE
    if e.errno in (errno.EACCES, errno.EPERM):
        return SFTP_PERMISSION_DENIED
    return SFTP_FAILURE


class _Handle(SFTPHandle):
    def stat(self):
        try:
            return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
        except OSError as e:
            return _errno_to_sftp(e)

    def chattr(self, attr):
        try:
            _apply_attr(self.filename, attr)
            return SFTP_OK
        except OSError as e:
            return _errno_to_sftp(e)


def _apply_attr(path, attr):
    if attr._flags & attr.FLAG_PERMISSIONS:
        os.chmod(path, attr.st_mode)
    if attr._flags & attr.FLAG_AMTIME:
        os.utime(path, (attr.st_atime, attr.st_mtime))


class _SftpImpl(SFTPServerInterface):
    ROOT = "."
    WINDOWS = False              # mimic Windows OpenSSH: "/" lists drives, paths like /C:/x
    HOME = "/"
    DENY: tuple = ()             # folders that may not be listed (permission denied)

    def canonicalize(self, path):
        if path in ("", "."):
            return self.HOME
        # posixpath instead of paramiko's default, which yields "//" for "/" on Windows
        return posixpath.normpath("/" + path.replace("\\", "/").lstrip("/"))

    def _real(self, path):
        rel = self.canonicalize(path).lstrip("/")
        if self.WINDOWS and len(rel) >= 2 and rel[1] == ":":
            rel = rel[0].upper() + "_drive" + rel[2:]      # "C:/x" -> "C_drive/x"
        return os.path.join(self.ROOT, rel)

    def list_folder(self, path):
        if self.canonicalize(path) in self.DENY:
            return SFTP_PERMISSION_DENIED
        if self.WINDOWS and self.canonicalize(path) == "/":
            out = []
            for name in sorted(os.listdir(self.ROOT)):
                if name.endswith("_drive") and len(name) == 7:
                    attr = SFTPAttributes.from_stat(os.stat(os.path.join(self.ROOT, name)))
                    attr.filename = name[0] + ":"
                    out.append(attr)
            return out
        real = self._real(path)
        try:
            out = []
            for name in os.listdir(real):
                attr = SFTPAttributes.from_stat(os.stat(os.path.join(real, name)))
                attr.filename = name
                out.append(attr)
            return out
        except OSError as e:
            return _errno_to_sftp(e)

    def stat(self, path):
        try:
            return SFTPAttributes.from_stat(os.stat(self._real(path)))
        except OSError as e:
            return _errno_to_sftp(e)

    lstat = stat

    def open(self, path, flags, attr):
        real = self._real(path)
        try:
            binary = getattr(os, "O_BINARY", 0)
            fd = os.open(real, flags | binary, 0o666)
        except OSError as e:
            return _errno_to_sftp(e)
        if flags & os.O_CREAT and attr is not None:
            attr._flags &= ~attr.FLAG_PERMISSIONS
            _apply_attr(real, attr)
        if flags & os.O_WRONLY:
            mode = "ab" if flags & os.O_APPEND else "wb"
        elif flags & os.O_RDWR:
            mode = "a+b" if flags & os.O_APPEND else "r+b"
        else:
            mode = "rb"
        f = os.fdopen(fd, mode)
        handle = _Handle(flags)
        handle.filename = real
        handle.readfile = f
        handle.writefile = f
        return handle

    def remove(self, path):
        try:
            os.remove(self._real(path))
        except OSError as e:
            return _errno_to_sftp(e)
        return SFTP_OK

    def rename(self, oldpath, newpath):
        try:
            os.rename(self._real(oldpath), self._real(newpath))
        except OSError as e:
            return _errno_to_sftp(e)
        return SFTP_OK

    def mkdir(self, path, attr):
        try:
            os.mkdir(self._real(path))
        except OSError as e:
            return _errno_to_sftp(e)
        return SFTP_OK

    def rmdir(self, path):
        try:
            os.rmdir(self._real(path))
        except OSError as e:
            return _errno_to_sftp(e)
        return SFTP_OK

    def chattr(self, path, attr):
        try:
            _apply_attr(self._real(path), attr)
        except OSError as e:
            return _errno_to_sftp(e)
        return SFTP_OK


class _Server(ServerInterface):
    def check_auth_password(self, username, password):
        ok = username == "user" and password == "pass"
        return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class _ClosingSubsystem(paramiko.SubsystemHandler):
    """Closes the SFTP channel at once, like a web host whose user may not use SSH."""

    def start_subsystem(self, name, transport, channel):
        # Like sshd running a login shell that exits: the request was accepted,
        # the client has sent its SFTP init, and then the channel ends.
        channel.recv(1024)
        channel.close()


class ConnectedClient:
    """Shaped like src.sftp_client.SftpClient for SftpFS."""

    def __init__(self, ssh: paramiko.SSHClient) -> None:
        self._ssh = ssh
        self.sftp = ssh.open_sftp()
        self.home_path = self.sftp.normalize(".")
        self.is_windows = self.home_path[1:3].endswith(":")
        self.is_connected = True

    @property
    def transport(self):
        return self._ssh.get_transport()

    def disconnect(self) -> None:
        try:
            self.sftp.close()
        finally:
            self._ssh.close()


class SftpTestServer:
    def __init__(self, root: str, windows_home: str = "", home: str = "/",
                 deny_list: tuple = (), sftp: str = "on") -> None:
        """
        windows_home (e.g. "/C:/Users/test"): behave like Windows OpenSSH;
        drive X: is served from the folder "<root>/X_drive".
        home: the login folder (realpath of ".").
        deny_list: folders whose listing fails with "permission denied".
        sftp: "on"; "closed" starts the subsystem and closes it at once;
        "missing" refuses the subsystem request (no "Subsystem sftp").
        """
        self.root = os.path.abspath(root)
        self.windows_home = windows_home
        self.home = windows_home or home
        self.deny_list = tuple(deny_list)
        self.sftp = sftp
        self._key = paramiko.RSAKey.generate(2048)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self._transports: list[paramiko.Transport] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.close()

    def _accept(self) -> None:
        impl = type("Impl", (_SftpImpl,), {"ROOT": self.root, "WINDOWS": bool(self.windows_home),
                                           "HOME": self.home, "DENY": self.deny_list})
        self._sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = paramiko.Transport(conn)
            t.add_server_key(self._key)
            if self.sftp == "on":
                t.set_subsystem_handler("sftp", SFTPServer, impl)
            elif self.sftp == "closed":
                t.set_subsystem_handler("sftp", _ClosingSubsystem)
            try:
                t.start_server(server=_Server())
            except (paramiko.SSHException, EOFError, OSError):
                # e.g. ssh-keyscan asking for a key type this server lacks:
                # drop that client, keep accepting the next ones.
                t.close()
                continue
            self._transports.append(t)

    def drop_connections(self) -> None:
        """Simulate a network drop: kill every server-side transport."""
        for t in self._transports:
            t.close()
        self._transports.clear()

    def connect(self) -> ConnectedClient:
        ssh = paramiko.SSHClient()
        ssh.get_host_keys().add(f"[127.0.0.1]:{self.port}", self._key.get_name(), self._key)
        ssh.connect("127.0.0.1", port=self.port, username="user", password="pass",
                    look_for_keys=False, allow_agent=False, timeout=10)
        return ConnectedClient(ssh)

    def close(self) -> None:
        self._stop.set()
        self.drop_connections()
        try:
            self._sock.close()
        except OSError:
            pass
