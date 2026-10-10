"""
The user's default SSH keys for connections that are set to a password.

The embedded terminal and the file browser log in with paramiko, which tries
~/.ssh/id_* before the password (look_for_keys). sshfs and the system info run
an ssh client of their own and used to try the password only, so a server
that accepts keys only worked in the terminal but could not be mounted. They
now get the same keys first.
"""
from __future__ import annotations

import os

# The key files paramiko's look_for_keys tries, newest type first.
DEFAULT_KEY_NAMES = ("id_ed25519", "id_ecdsa", "id_rsa")


def default_identity_files() -> list[str]:
    """
    The user's default private keys that load without a passphrase, as
    absolute paths. A key with a passphrase is left out: ssh would ask for it,
    and that prompt would wait for an answer nobody gives.
    """
    import paramiko

    ssh_dir = os.path.join(os.path.expanduser("~"), ".ssh")
    found = []
    for name in DEFAULT_KEY_NAMES:
        path = os.path.join(ssh_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            paramiko.PKey.from_path(path)
        except Exception:       # passphrase, unknown format or unreadable
            continue
        found.append(path)
    return found
