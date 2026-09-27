"""
remote_path.py – Helpers for remote SFTP path handling across server OSes.

The SFTP protocol always uses forward slashes. Windows OpenSSH exposes drives
as /C:/…, /W:/… and lists the drive letters at the virtual root "/". These
helpers let the SFTP browser and the sshfs mount accept Windows-style user
input and talk to the server in its canonical form.

Kept dependency-free (no paramiko/Qt) so any layer can import it cheaply.
"""

from __future__ import annotations

import re

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def looks_like_windows_path(path: str) -> bool:
    """True if an SFTP path looks like a Windows OpenSSH path (/C:/…, C:\\…)."""
    if not path:
        return False
    p = path.lstrip("/")
    return bool(_DRIVE_RE.match(p)) or "\\" in path


def normalize_remote_input(path: str, is_windows: bool) -> str:
    """
    Turn a user-entered path into the SFTP server's canonical form.

    On Windows this accepts C:\\Users, C:/Users, /C:/Users and \\folder and
    always yields the forward-slash, leading-slash form the sftp-server expects
    (e.g. "/C:/Users"). On POSIX it just guarantees a leading slash.
    """
    p = (path or "").strip()
    if not p:
        return "/"
    if is_windows:
        p = p.replace("\\", "/")
        if _DRIVE_RE.match(p):          # C:/Users -> /C:/Users
            p = "/" + p
        if not p.startswith("/"):
            p = "/" + p
        while "//" in p:
            p = p.replace("//", "/")
        if len(p) > 1:
            p = p.rstrip("/") or "/"
        return p
    if not p.startswith("/"):
        p = "/" + p
    return p
