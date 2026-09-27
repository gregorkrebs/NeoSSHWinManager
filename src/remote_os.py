"""
remote_os.py – Cheap, unauthenticated detection of the remote SSH server's OS.

Reads the identification string an SSH server sends right after the TCP
connect (RFC 4253 section 4.2), e.g. "SSH-2.0-OpenSSH_for_Windows_9.5". No
credentials are involved, so it can run before any authenticated call and
spares an extra login attempt just to find out which command set to use.
"""

from __future__ import annotations

import socket

# Substrings (lower-case) that identify a Windows SSH server in its banner.
_WINDOWS_MARKERS = ("windows", "winsshd", "bitvise")


def read_ssh_banner(host: str, port: int, timeout: float = 4.0) -> str | None:
    """Return the server's "SSH-..." identification line, or None on failure."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            data = b""
            # Servers may send other lines before the SSH- line (RFC 4253).
            while len(data) < 4096:
                chunk = sock.recv(512)
                if not chunk:
                    break
                data += chunk
                for line in data.decode("latin-1").splitlines():
                    if line.startswith("SSH-"):
                        banner = line.strip()
                        try:
                            # Answer with our own identification so the server
                            # logs a clean preauth close, not a missing banner.
                            sock.sendall(b"SSH-2.0-NeoSSHWinManager_probe\r\n")
                        except OSError:
                            pass
                        return banner
    except OSError:
        pass
    return None


def os_from_banner(banner: str | None) -> str | None:
    """Map an SSH banner to "windows", or None when it does not say."""
    if not banner:
        return None
    low = banner.lower()
    if any(marker in low for marker in _WINDOWS_MARKERS):
        return "windows"
    return None


def detect_remote_os(host: str, port: int, timeout: float = 4.0) -> str | None:
    """"windows" if the server's banner identifies it as Windows, else None."""
    return os_from_banner(read_ssh_banner(host, port, timeout))
