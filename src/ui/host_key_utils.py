"""
host_key_utils.py – SSH host-key verification helpers shared by the terminal bridge
and the SFTP browser.

Provides TOFU (Trust On First Use) utilities that check known_hosts, fetch server
fingerprints via ssh-keyscan, and implement a paramiko missing-host-key policy
that saves accepted keys to disk.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def is_host_known(host: str, port: int, known_hosts_path: str) -> bool:
    """Return True if host:port already appears in known_hosts_path."""
    if not os.path.exists(known_hosts_path):
        return False

    ssh_keygen = shutil.which("ssh-keygen") or r"C:\Windows\System32\OpenSSH\ssh-keygen.exe"
    if shutil.which("ssh-keygen") or os.path.exists(ssh_keygen):
        try:
            target = f"[{host}]:{port}" if port != 22 else host
            result = subprocess.run(
                [ssh_keygen, "-F", target, "-f", known_hosts_path],
                capture_output=True, timeout=5,
                creationflags=0x08000000,
            )
            return result.returncode == 0
        except Exception:
            pass

    # Fallback: plain-text scan (does not handle hashed entries)
    try:
        target_plain = host
        target_port = f"[{host}]:{port}" if port != 22 else None
        with open(known_hosts_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                for h in parts[0].split(","):
                    if h == target_plain or (target_port and h == target_port):
                        return True
    except Exception:
        pass

    return False


def get_server_fingerprint(host: str, port: int) -> str | None:
    """Return the SHA256 fingerprint of the server's host key, or None on failure."""
    ssh_keyscan = shutil.which("ssh-keyscan") or r"C:\Windows\System32\OpenSSH\ssh-keyscan.exe"
    if not (shutil.which("ssh-keyscan") or os.path.exists(ssh_keyscan)):
        return None
    try:
        result = subprocess.run(
            [ssh_keyscan, "-p", str(port), "-H", host],
            capture_output=True, timeout=8,
            creationflags=0x08000000,
        )
        keyscan_output = result.stdout.decode("utf-8", errors="ignore")
        if not keyscan_output.strip():
            return None
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            tmp.write(keyscan_output)
            tmp_path = tmp.name
        try:
            ssh_keygen = ssh_keyscan.replace("ssh-keyscan", "ssh-keygen").replace(
                "ssh-keyscan.exe", "ssh-keygen.exe"
            )
            r2 = subprocess.run(
                [ssh_keygen, "-l", "-f", tmp_path],
                capture_output=True, timeout=5,
                creationflags=0x08000000,
            )
            lines = r2.stdout.decode("utf-8", errors="ignore").strip().splitlines()
            if lines:
                return lines[0]
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception:
        pass
    return None


def ensure_host_known(host: str, port: int, known_hosts_path: str) -> bool:
    """
    Make sure host:port is present in known_hosts, adding it silently if missing.

    Used before headless SSH subprocess calls (e.g. the system-info panel) so a
    first-time host does not surface a spurious host-key error to the user. The
    key is fetched with ssh-keyscan and appended to known_hosts. Returns True if
    the host is known afterwards.
    """
    if is_host_known(host, port, known_hosts_path):
        return True

    ssh_keyscan = shutil.which("ssh-keyscan") or r"C:\Windows\System32\OpenSSH\ssh-keyscan.exe"
    if not (shutil.which("ssh-keyscan") or os.path.exists(ssh_keyscan)):
        return False
    try:
        result = subprocess.run(
            [ssh_keyscan, "-p", str(port), "-H", host],
            capture_output=True, timeout=8,
            creationflags=0x08000000,
        )
        output = result.stdout.decode("utf-8", errors="ignore")
        lines = [
            line for line in output.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not lines:
            return False
        append_known_hosts(known_hosts_path, lines)
        return True
    except Exception:
        return False


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


class TOFUAcceptPolicy:
    """Paramiko missing-host-key policy that saves accepted keys to known_hosts."""

    def __init__(self, known_hosts_path: str) -> None:
        self._path = known_hosts_path

    def missing_host_key(self, client, hostname: str, key) -> None:
        append_known_hosts(self._path, [known_hosts_line(hostname, key)])
