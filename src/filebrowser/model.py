"""
model.py – Pure data and decision logic of the file browser (no Qt, no I/O).

Everything here is deterministic and unit-tested: file entries, path helpers
for remote (POSIX / Windows OpenSSH) and local paths, "keep both" naming,
conflict policies and the directory-sync comparison.
"""

from __future__ import annotations

import ntpath
import posixpath
import re
import stat as stat_mod
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional


# ── Entries ──────────────────────────────────────────────────────────────────

@dataclass
class FileEntry:
    """One file or directory, remote or local."""

    name: str
    path: str
    is_dir: bool
    size: int = 0
    mtime: float = 0.0
    mode: int = 0               # full st_mode (type + permission bits), 0 if unknown
    owner: str = ""
    group: str = ""
    is_link: bool = False
    is_up: bool = False         # the "..." row of a listing (path = the parent folder)

    @property
    def permissions(self) -> str:
        """ls-style permission string, "" when the server did not report any."""
        if not self.mode:
            return ""
        return stat_mod.filemode(self.mode)

    @property
    def perm_bits(self) -> int:
        return self.mode & 0o7777

    @property
    def extension(self) -> str:
        return file_extension(self.name)

    @classmethod
    def from_sftp_attr(cls, attr, directory: str) -> "FileEntry":
        """Build from a paramiko SFTPAttributes (as returned by listdir_attr)."""
        mode = attr.st_mode or 0
        owner, group = _owner_group_from_longname(getattr(attr, "longname", None))
        if not owner and attr.st_uid is not None:
            owner = str(attr.st_uid)
        if not group and attr.st_gid is not None:
            group = str(attr.st_gid)
        return cls(
            name=attr.filename,
            path=rjoin(directory, attr.filename),
            is_dir=stat_mod.S_ISDIR(mode),
            size=int(attr.st_size or 0),
            mtime=float(attr.st_mtime or 0),
            mode=mode,
            owner=owner,
            group=group,
            is_link=stat_mod.S_ISLNK(mode),
        )


def _owner_group_from_longname(longname: Optional[str]) -> tuple[str, str]:
    """OpenSSH's longname looks like 'drwxr-xr-x 2 alice staff 4096 Jan 1 x'."""
    if not longname:
        return "", ""
    parts = longname.split()
    if len(parts) >= 4 and re.match(r"^[bcdlps\-][rwxsStT\-]{9}", parts[0]):
        return parts[2], parts[3]
    return "", ""


_DOUBLE_EXTENSIONS = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst", ".tar.lz")


def split_name(name: str) -> tuple[str, str]:
    """('archive', '.tar.gz'), ('photo', '.jpg'), ('.bashrc', ''), ('README', '')."""
    low = name.lower()
    for ext in _DOUBLE_EXTENSIONS:
        if low.endswith(ext) and len(name) > len(ext):
            return name[: -len(ext)], name[-len(ext):]
    stem, ext = posixpath.splitext(name)
    return stem, ext


def file_extension(name: str) -> str:
    """Lower-case extension without dot ('tar.gz', 'jpg', '' for none)."""
    return split_name(name)[1].lstrip(".").lower()


def _natural_key(text: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text.lower())]


def sort_entries(entries: Iterable[FileEntry]) -> list[FileEntry]:
    """Directories first, then natural, case-insensitive order ('f2' < 'f10')."""
    return sorted(entries, key=lambda e: (not e.is_dir, _natural_key(e.name)))


def is_hidden(entry: FileEntry) -> bool:
    return entry.name.startswith(".")


# ── Remote paths (always forward slashes) ────────────────────────────────────

def rjoin(directory: str, name: str) -> str:
    directory = directory or "/"
    return directory.rstrip("/") + "/" + name if directory != "/" else "/" + name


def rparent(path: str) -> str:
    """'/a/b' -> '/a', '/a' -> '/', '/C:/x' -> '/C:', '/C:' -> '/'."""
    path = (path or "/").rstrip("/") or "/"
    if path == "/":
        return "/"
    return path.rsplit("/", 1)[0] or "/"


def rname(path: str) -> str:
    path = (path or "/").rstrip("/")
    return path.rsplit("/", 1)[-1] if path else "/"


def rparts(path: str) -> list[tuple[str, str]]:
    """Breadcrumb segments [(label, full_path)], starting with ('/', '/')."""
    out = [("/", "/")]
    current = ""
    for part in (path or "/").strip("/").split("/"):
        if not part:
            continue
        current += "/" + part
        out.append((part, current))
    return out


def rrelative(path: str, base: str) -> str:
    """Path of `path` below `base`, with forward slashes ('' if equal)."""
    base = base.rstrip("/") or "/"
    if path == base:
        return ""
    prefix = base if base.endswith("/") else base + "/"
    return path[len(prefix):] if path.startswith(prefix) else path


def windows_remote_to_native(path: str) -> str:
    """'/C:/Users/x' -> 'C:\\Users\\x' (Windows OpenSSH SFTP path to Win32)."""
    p = (path or "").lstrip("/")
    if re.match(r"^[A-Za-z]:", p):
        native = p.replace("/", "\\")
        return native if len(native) > 2 else native + "\\"
    return (path or "").replace("/", "\\")


# ── Local paths ("" is the virtual root listing the drives) ──────────────────

def lparent(path: str) -> str:
    """'C:\\a\\b' -> 'C:\\a', 'C:\\' -> '' (drive list)."""
    if not path:
        return ""
    drive, rest = ntpath.splitdrive(path)
    if rest.strip("\\/") == "":
        return ""
    return ntpath.dirname(path.rstrip("\\/")) or (drive + "\\")


def lparts(path: str) -> list[tuple[str, str]]:
    """Breadcrumb segments for a local path; the first is the drive list."""
    out = [("⌂", "")]
    if not path:
        return out
    drive, rest = ntpath.splitdrive(path)
    current = drive + "\\"
    out.append((drive + "\\", current))
    for part in rest.strip("\\/").replace("/", "\\").split("\\"):
        if not part:
            continue
        current = ntpath.join(current, part)
        out.append((part, current))
    return out


# ── Path comparison (drop targets, moves, undo) ──────────────────────────────

def _norm(path: str, local: bool) -> str:
    if local:
        return (path or "").replace("/", "\\").rstrip("\\").lower()
    return (path or "/").rstrip("/") or "/"


def same_path(a: str, b: str, local: bool) -> bool:
    """Equal paths; local (Windows) paths compare case-insensitively."""
    return _norm(a, local) == _norm(b, local)


def path_within(path: str, base: str, local: bool) -> bool:
    """True when `path` is `base` itself or lies somewhere below it."""
    p, b = _norm(path, local), _norm(base, local)
    if p == b or (not local and b == "/") or (local and not b):
        return True
    return p.startswith(b + ("\\" if local else "/"))


def rebase_path(path: str, old_base: str, new_base: str, local: bool) -> Optional[str]:
    """Where `path` ended up after `old_base` was moved to `new_base` (None: unaffected)."""
    if _norm(old_base, local) in ("/", "") or not path_within(path, old_base, local):
        return None                              # roots never move
    sep = "\\" if local else "/"
    rest = path.rstrip(sep)[len(old_base.rstrip(sep)):]
    return new_base.rstrip(sep) + rest if rest else new_base


# ── "Keep both" naming ───────────────────────────────────────────────────────

def keep_both_name(name: str, exists: Callable[[str], bool]) -> str:
    """First free 'name_1.ext', 'name_2.ext', … according to `exists`."""
    stem, ext = split_name(name)
    n = 1
    while True:
        candidate = f"{stem}_{n}{ext}"
        if not exists(candidate):
            return candidate
        n += 1


# ── Conflicts ────────────────────────────────────────────────────────────────

OVERWRITE = "overwrite"
SKIP = "skip"
KEEP_BOTH = "keep_both"
RESUME = "resume"
CANCEL = "cancel"

# Policies selectable in the settings (what to do without asking).
POLICY_ASK = "ask"
POLICY_OVERWRITE = "overwrite"
POLICY_SKIP = "skip"
POLICY_KEEP_BOTH = "keep_both"
POLICY_NEWER = "newer"
POLICIES = (POLICY_ASK, POLICY_OVERWRITE, POLICY_NEWER, POLICY_SKIP, POLICY_KEEP_BOTH)

MTIME_TOLERANCE = 2.0   # seconds; FTP and FAT only keep 1–2 s resolution


@dataclass
class ConflictInfo:
    """A transfer whose target already exists."""

    source: FileEntry
    target: FileEntry
    direction: str                      # "up" | "down" | "url"
    batch: int = 0

    @property
    def can_resume(self) -> bool:
        return (
            not self.source.is_dir and not self.target.is_dir
            and 0 < self.target.size < self.source.size
        )


def auto_decision(policy: str, info: ConflictInfo) -> Optional[str]:
    """Decision a policy takes without asking, or None to ask the user."""
    if policy == POLICY_OVERWRITE:
        return OVERWRITE
    if policy == POLICY_SKIP:
        return SKIP
    if policy == POLICY_KEEP_BOTH:
        return KEEP_BOTH
    if policy == POLICY_NEWER:
        newer = info.source.mtime > info.target.mtime + MTIME_TOLERANCE
        return OVERWRITE if newer else SKIP
    return None


# ── Directory sync ───────────────────────────────────────────────────────────

SYNC_UPLOAD = "upload"           # local → remote
SYNC_DOWNLOAD = "download"       # remote → local
SYNC_BOTH = "both"               # newer side wins

ACT_UPLOAD = "upload"
ACT_DOWNLOAD = "download"
ACT_DELETE_REMOTE = "delete_remote"
ACT_DELETE_LOCAL = "delete_local"


@dataclass
class SyncItem:
    rel: str                                  # path relative to both roots, '/'-separated
    action: str
    reason: str                               # "only_local", "newer_local", "size", …
    local: Optional[FileEntry] = None
    remote: Optional[FileEntry] = None
    selected: bool = True

    @property
    def size(self) -> int:
        src = self.local if self.action == ACT_UPLOAD else self.remote
        return src.size if src else 0


@dataclass
class SyncSide:
    """Flat snapshot of one tree: files and directories by relative path."""

    files: dict[str, FileEntry] = field(default_factory=dict)
    dirs: set[str] = field(default_factory=set)


def compare_trees(
    local: SyncSide,
    remote: SyncSide,
    direction: str,
    delete_extra: bool = False,
    tolerance: float = MTIME_TOLERANCE,
) -> list[SyncItem]:
    """
    Work out what a sync has to do.

    One-way sync copies files missing on the target, files whose size differs
    and files that are newer on the source; with delete_extra it also removes
    target files that no longer exist on the source (mirror). Two-way sync
    copies missing files both ways and lets the newer side win on conflicts;
    it never deletes.
    """
    items: list[SyncItem] = []
    for rel in sorted(set(local.files) | set(remote.files), key=_natural_key):
        lf = local.files.get(rel)
        rf = remote.files.get(rel)
        if lf and not rf:
            if direction in (SYNC_UPLOAD, SYNC_BOTH):
                items.append(SyncItem(rel, ACT_UPLOAD, "only_local", lf, None))
            elif delete_extra:
                items.append(SyncItem(rel, ACT_DELETE_LOCAL, "only_local", lf, None))
            continue
        if rf and not lf:
            if direction in (SYNC_DOWNLOAD, SYNC_BOTH):
                items.append(SyncItem(rel, ACT_DOWNLOAD, "only_remote", None, rf))
            elif delete_extra:
                items.append(SyncItem(rel, ACT_DELETE_REMOTE, "only_remote", None, rf))
            continue

        assert lf and rf
        local_newer = lf.mtime > rf.mtime + tolerance
        remote_newer = rf.mtime > lf.mtime + tolerance
        size_differs = lf.size != rf.size
        if not size_differs and not local_newer and not remote_newer:
            continue

        if direction == SYNC_UPLOAD:
            if size_differs or local_newer:
                reason = "newer_local" if local_newer else "size"
                items.append(SyncItem(rel, ACT_UPLOAD, reason, lf, rf))
        elif direction == SYNC_DOWNLOAD:
            if size_differs or remote_newer:
                reason = "newer_remote" if remote_newer else "size"
                items.append(SyncItem(rel, ACT_DOWNLOAD, reason, lf, rf))
        else:
            if local_newer:
                items.append(SyncItem(rel, ACT_UPLOAD, "newer_local", lf, rf))
            elif remote_newer:
                items.append(SyncItem(rel, ACT_DOWNLOAD, "newer_remote", lf, rf))
            # Same age but different size: no safe winner, leave it alone.
    return items


# ── Formatting ───────────────────────────────────────────────────────────────

def fmt_size(size: float) -> str:
    size = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def fmt_speed(bytes_per_s: float) -> str:
    return f"{fmt_size(bytes_per_s)}/s" if bytes_per_s > 0 else "—"


def fmt_eta(seconds: float) -> str:
    if seconds <= 0 or seconds == float("inf"):
        return "—"
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_octal_mode(text: str) -> Optional[int]:
    """'755' / '0644' -> int, None if not a valid permission value."""
    text = (text or "").strip()
    if not re.fullmatch(r"0?[0-7]{3,4}", text):
        return None
    return int(text, 8)
