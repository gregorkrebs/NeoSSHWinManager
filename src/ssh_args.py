"""
ssh_args.py – Checks for host and user names before they become command-line
arguments of ssh.exe, plink.exe or sshfs.exe.

These clients read any argument that starts with "-" as an option: a user
name such as "-oProxyCommand=calc.exe" would run a local program. The
arguments are passed as a list (no shell), so other characters are harmless
here; the native-ssh launcher, which goes through cmd.exe, checks more
strictly (ssh_launcher._is_safe_ssh_identifier).
"""

from __future__ import annotations


def is_safe_cli_value(value: str) -> bool:
    """True for a non-empty value that cannot be taken for an option."""
    if not value or not isinstance(value, str):
        return False
    if value.startswith("-"):
        return False
    return not any(ord(c) < 32 or ord(c) == 127 for c in value)


def check_host_and_user(host: str, user: str) -> None:
    """Raise ValueError if host or user could be read as an option."""
    if not is_safe_cli_value(host):
        raise ValueError(f"Ungültiger Hostname: {host!r}")
    if not is_safe_cli_value(user):
        raise ValueError(f"Ungültiger Benutzername: {user!r}")
