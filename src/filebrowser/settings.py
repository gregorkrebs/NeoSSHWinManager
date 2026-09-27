"""
settings.py – Per-user settings of the file browser.

Stored as one JSON document (encrypted by the auth manager, like connection
metadata). All browser windows share one SettingsManager, so a bookmark added
in one window is not lost when another window saves later, and changes such
as rate limits reach every window immediately.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Callable, Optional, Protocol

from src.app_logger import logger
from src.filebrowser.model import POLICIES, POLICY_ASK

OPEN_WITH_SYSTEM = "__system__"        # open_with value: Windows file association


@dataclass
class BrowserSettings:
    # transfers
    max_downloads: int = 3
    max_uploads: int = 3
    limit_down_kib: int = 0            # 0 = unlimited
    limit_up_kib: int = 0
    conflict_policy: str = POLICY_ASK
    preserve_mtime: bool = True
    verify_checksum: bool = False
    auto_reconnect: bool = True
    retry_attempts: int = 3
    # view
    show_hidden: bool = False
    show_tree: bool = True
    tree_from_root: bool = False       # server tree from "/" instead of the home path
    confirm_delete: bool = True
    confirm_move: bool = True          # ask before moving by drag & drop
    double_click: str = "open"         # "open" | "download"
    archive_format: str = "tar.gz"     # default for "pack" and archive transfers
    local_start: str = "C:\\"
    # remembered state
    open_with: dict = field(default_factory=dict)      # ext -> program path | OPEN_WITH_SYSTEM
    bookmarks: dict = field(default_factory=dict)      # connection id -> [remote paths]
    last_remote: dict = field(default_factory=dict)    # connection id -> remote path
    last_local: str = ""
    window: dict = field(default_factory=dict)         # geometry, split, column states …

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "BrowserSettings":
        defaults = cls()
        if not isinstance(data, dict):
            return defaults
        values = {}
        for f in fields(cls):
            default = getattr(defaults, f.name)
            value = data.get(f.name, default)
            if type(value) is not type(default):
                try:
                    value = type(default)(value)
                except (TypeError, ValueError):
                    value = default
            values[f.name] = value
        s = cls(**values)
        s.normalize()
        return s

    def normalize(self) -> None:
        self.max_downloads = min(8, max(1, int(self.max_downloads)))
        self.max_uploads = min(8, max(1, int(self.max_uploads)))
        self.limit_down_kib = max(0, int(self.limit_down_kib))
        self.limit_up_kib = max(0, int(self.limit_up_kib))
        self.retry_attempts = min(10, max(0, int(self.retry_attempts)))
        if self.conflict_policy not in POLICIES:
            self.conflict_policy = POLICY_ASK
        if self.double_click not in ("open", "download"):
            self.double_click = "open"
        if self.archive_format not in ("tar.gz", "zip"):
            self.archive_format = "tar.gz"
        self.open_with = {
            str(k).lower().lstrip("."): str(v) for k, v in self.open_with.items() if k and v
        }

    def to_dict(self) -> dict:
        return asdict(self)

    # convenience
    def program_for(self, extension: str) -> Optional[str]:
        return self.open_with.get((extension or "").lower().lstrip("."))

    def bookmarks_for(self, conn_id: str) -> list[str]:
        return list(self.bookmarks.get(conn_id, []))


class SettingsStore(Protocol):
    def load(self) -> dict: ...
    def save(self, data: dict) -> None: ...


class MemoryStore:
    """In-memory store (tests, or when no user session is available)."""

    def __init__(self, data: Optional[dict] = None) -> None:
        self.data = dict(data or {})

    def load(self) -> dict:
        return dict(self.data)

    def save(self, data: dict) -> None:
        self.data = dict(data)


class AuthManagerStore:
    """Persists into the logged-in user's app_settings row (encrypted)."""

    def __init__(self, manager) -> None:
        self._mgr = manager

    def load(self) -> dict:
        return self._mgr.get_sftp_browser_settings()

    def save(self, data: dict) -> None:
        self._mgr.save_sftp_browser_settings(data)


class SettingsManager:
    """Shared settings object plus change notification for all windows."""

    def __init__(self, store: SettingsStore) -> None:
        self._store = store
        try:
            self.settings = BrowserSettings.from_dict(store.load())
        except Exception as e:
            logger.warning("filebrowser: could not load settings: %s", e)
            self.settings = BrowserSettings()
        self._listeners: list[Callable[[BrowserSettings], None]] = []

    def add_listener(self, fn: Callable[[BrowserSettings], None]) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[BrowserSettings], None]) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def save(self, notify: bool = True) -> None:
        self.settings.normalize()
        try:
            self._store.save(self.settings.to_dict())
        except Exception as e:
            logger.warning("filebrowser: could not save settings: %s", e)
        if notify:
            for fn in list(self._listeners):
                try:
                    fn(self.settings)
                except Exception as e:
                    logger.debug("filebrowser: settings listener failed: %s", e)
