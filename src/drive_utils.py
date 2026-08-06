"""
drive_utils.py – Utilities for Windows drive letter management.
"""

import subprocess
import string
import re
from typing import List


ALL_LETTERS = [f"{c}:" for c in string.ascii_uppercase]
# Reserve system / common letters
RESERVED = {"A:", "B:", "C:"}


def get_used_drives() -> List[str]:
    """Return list of drive letters currently in use via GetLogicalDrives bitmask."""
    import ctypes
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    used = []
    for i in range(26):
        if bitmask & (1 << i):
            used.append(f"{chr(65 + i)}:")
    return used


def get_available_drives(exclude: List[str] = None) -> List[str]:
    """Return drive letters that are free and can be used for mounting."""
    used = set(get_used_drives())
    if exclude:
        used.update(exclude)
    return [l for l in ALL_LETTERS if l not in RESERVED and l not in used]


def is_drive_in_use(letter: str) -> bool:
    """Check if a specific drive letter is currently in use."""
    return letter.upper().rstrip("\\") + ":" in get_used_drives() or \
           letter.upper() in get_used_drives()
