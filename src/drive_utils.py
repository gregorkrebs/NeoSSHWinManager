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


# ---------------------------------------------------------------------------
# Drive letters per host: shared letters, mount state, free-letter suggestions.
# Pure functions (no Windows calls) so they can be tested anywhere.
# ---------------------------------------------------------------------------

def norm_letter(value) -> "str | None":
    """'x', 'X:', 'x:\\' -> 'X:'; anything else -> None."""
    v = str(value or "").strip().rstrip("\\/").rstrip(":").upper()
    return f"{v}:" if len(v) == 1 and v in string.ascii_uppercase else None


def assignable_letters() -> List[str]:
    """Every letter a host may be given (D: … Z:)."""
    return [l for l in ALL_LETTERS if l not in RESERVED]


def _mountable(conns):
    # FTP/FTPS hosts are never mounted, templates are not hosts.
    return [c for c in conns
            if not getattr(c, "is_ftp", False) and not getattr(c, "is_template", False)]


def duplicate_letters(conns) -> set:
    """Letters assigned to more than one mountable host."""
    from collections import Counter
    counts = Counter(norm_letter(c.drive_letter) for c in _mountable(conns))
    return {l for l, n in counts.items() if l and n > 1}


def resolve_mounted(conns, active: dict, in_use, ours=None) -> dict:
    """Which host is mounted on which letter: {conn_id: 'X:'}.

    *active* maps conn_id -> the letter recorded when the app mounted it ('' for
    records from before letters were recorded); *in_use* is every letter
    Windows reports. A letter belongs to at most one host:
      1. a host whose recorded letter is in use;
      2. a host recorded without a letter, on its configured letter;
      3. a host without a record, on its configured letter, but only if no
         other host is configured for that letter and – when *ours* (letters
         that really hold an SSHFS mount) is given – the drive there is an
         SSHFS mount, not a USB stick or other drive.
    """
    in_use = {l for l in (norm_letter(x) for x in in_use) if l}
    hosts = _mountable(conns)
    mounted: dict = {}
    claimed: set = set()

    def take(conn, letter):
        if letter and letter in in_use and letter not in claimed:
            mounted[conn.id] = letter
            claimed.add(letter)

    for c in hosts:
        if norm_letter(active.get(c.id)):
            take(c, norm_letter(active[c.id]))
    for c in hosts:
        if c.id in active and not norm_letter(active.get(c.id)) and c.id not in mounted:
            take(c, norm_letter(c.drive_letter))
    from collections import Counter
    configured = Counter(norm_letter(c.drive_letter) for c in hosts)
    for c in hosts:
        if c.id not in active and c.id not in mounted:
            letter = norm_letter(c.drive_letter)
            if configured[letter] == 1 and (ours is None or letter in ours):
                take(c, letter)
    return mounted


def suggest_free_letter(in_use, avoid=(), randomize: bool = False, rng=None) -> "str | None":
    """A letter that is free on the system and not in *avoid*.

    Deterministic: the highest free letter (Z: first, like the add form);
    randomize=True picks any free one. None if nothing is free.
    """
    blocked = {l for l in (norm_letter(x) for x in list(in_use) + list(avoid)) if l}
    candidates = [l for l in reversed(assignable_letters()) if l not in blocked]
    if not candidates:
        return None
    if randomize:
        import random
        return (rng or random).choice(candidates)
    return candidates[0]
