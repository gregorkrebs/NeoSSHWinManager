"""
host_key_utils.py – SSH host-key verification helpers shared by the terminal
bridge, the SFTP browser and the external clients (ssh.exe, sshfs.exe).

Every check reads known_hosts with paramiko (hashed entries included) and asks
on first contact with the fingerprint of the key the server actually
presented. The key that was shown is the key that gets saved: no separate
ssh-keyscan run whose answer may differ, and nothing is ever added without
the user's consent.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import Callable, Optional

# ask(host, port, fingerprint) -> True to trust and save the key
HostKeyPrompt = Callable[[str, int, str], bool]

_prompt: Optional[HostKeyPrompt] = None


def default_known_hosts() -> str:
    """The user's OpenSSH known_hosts (%USERPROFILE%\\.ssh\\known_hosts on Windows)."""
    return os.path.join(os.path.expanduser("~"), ".ssh", "known_hosts")


def set_host_key_prompt(ask: Optional[HostKeyPrompt]) -> None:
    """
    Register the question confirm_host_key() asks when no callback is passed.
    The main window registers a thread-safe dialog; without one, unknown hosts
    are refused.
    """
    global _prompt
    _prompt = ask


@dataclass
class PendingHostKey:
    """A key the server presented that known_hosts does not hold yet."""
    host: str
    port: int
    name: str           # known_hosts host field: "host" or "[host]:port"
    key: object         # paramiko.PKey
    fingerprint: str
    known_hosts: str

    def trust(self) -> None:
        """Save exactly this key (the one the user was shown)."""
        append_known_hosts(self.known_hosts, [known_hosts_line(self.name, self.key)])


def check_host_key(host: str, port: int, known_hosts: Optional[str] = None,
                   timeout: float = 10.0) -> Optional[PendingHostKey]:
    """
    Read the key the host presents and compare it with known_hosts.

    Returns None when it is known, a PendingHostKey to put to the user when it
    is not. Raises src.sftp_client.HostKeyChanged when known_hosts holds a
    different key of the same type, SftpClientError when the host cannot be
    reached.
    """
    from src.sftp_client import HostKeyChanged, HostKeyVerifier, SftpClientError

    known_hosts = known_hosts or default_known_hosts()
    port = int(port or 22)
    verifier = HostKeyVerifier(host, port, known_hosts, None)
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as e:
        raise SftpClientError(str(e)) from e
    transport = None
    try:
        transport = verifier.transport_factory(sock)
        transport.start_client(timeout=timeout)
        key = transport.get_remote_server_key()
    except Exception as e:
        raise SftpClientError(str(e)) from e
    finally:
        if transport is not None:
            transport.close()
        else:
            sock.close()

    stored = verifier.known.get(key.get_name())
    if stored is not None:
        if stored.asbytes() == key.asbytes():
            return None
        raise HostKeyChanged(verifier.name, key_fingerprint(key), known_hosts)
    return PendingHostKey(host, port, verifier.name, key, key_fingerprint(key), known_hosts)


def confirm_host_key(host: str, port: int, ask: Optional[HostKeyPrompt] = None,
                     known_hosts: Optional[str] = None, timeout: float = 10.0) -> None:
    """
    For clients that verify host keys themselves (ssh.exe with
    StrictHostKeyChecking=yes, sshfs.exe): make sure the key the host presents
    is in known_hosts, asking on first contact (ask, else the registered
    prompt; without either, unknown hosts are refused).

    Returns when the key is known or was accepted and saved. Raises
    src.sftp_client.HostKeyRejected / HostKeyChanged for host-key problems and
    SftpClientError when the host cannot be reached.
    """
    from src.sftp_client import HostKeyRejected

    pending = check_host_key(host, port, known_hosts, timeout)
    if pending is None:
        return
    ask = ask or _prompt
    if not (ask and ask(pending.host, pending.port, pending.fingerprint)):
        raise HostKeyRejected(pending.name, pending.fingerprint)
    pending.trust()


def append_known_hosts(known_hosts_path: str, lines: list[str]) -> None:
    """Append entries to known_hosts, starting on a fresh line (LF endings)."""
    os.makedirs(os.path.dirname(known_hosts_path), exist_ok=True)
    # Guarantee a newline boundary so we never merge onto a previous entry.
    needs_prefix_nl = False
    if os.path.exists(known_hosts_path) and os.path.getsize(known_hosts_path) > 0:
        try:
            with open(known_hosts_path, "rb") as f:
                f.seek(-1, os.SEEK_END)
                needs_prefix_nl = f.read(1) not in (b"\n", b"\r")
        except Exception:
            needs_prefix_nl = False
    with open(known_hosts_path, "a", encoding="utf-8", newline="\n") as f:
        if needs_prefix_nl:
            f.write("\n")
        for line in lines:
            f.write(line.rstrip("\r\n") + "\n")


def known_hosts_line(hostname: str, key) -> str:
    """'hostname keytype base64' for a paramiko key."""
    import base64
    return f"{hostname} {key.get_name()} {base64.b64encode(key.asbytes()).decode()}"


def key_fingerprint(key) -> str:
    """Like `ssh-keygen -l`: '256 SHA256:… (ED25519)' for a paramiko key."""
    import base64
    import hashlib
    digest = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
    name = key.get_name()
    label = {"ssh-ed25519": "ED25519", "ssh-rsa": "RSA"}.get(
        name, "ECDSA" if name.startswith("ecdsa-") else name)
    try:
        bits = key.get_bits()
    except Exception:
        bits = 0
    return f"{bits} SHA256:{digest} ({label})" if bits else f"SHA256:{digest} ({label})"

