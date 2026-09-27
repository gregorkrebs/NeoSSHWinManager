"""
models.py – Table model, sort/filter proxy and drag & drop payload.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

from PyQt6.QtCore import (
    QAbstractTableModel, QMimeData, QModelIndex, QSortFilterProxyModel, Qt, QUrl,
)
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import QFileIconProvider

from src.filebrowser.model import FileEntry, fmt_size, is_hidden, _natural_key
from src.i18n import tr

COL_NAME, COL_SIZE, COL_MTIME, COL_TYPE, COL_PERMS, COL_OWNER = range(6)
ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1

MIME_ENTRIES = "application/x-neossh-entries"

_provider: Optional[QFileIconProvider] = None
_icon_cache: dict[str, QIcon] = {}


def icon_for(entry: FileEntry, local: bool) -> QIcon:
    """Windows shell icon by extension (cached); real icon for local .exe/.lnk."""
    global _provider
    if _provider is None:
        _provider = QFileIconProvider()
    if entry.is_dir:
        key = "<dir>"
        if key not in _icon_cache:
            _icon_cache[key] = _provider.icon(QFileIconProvider.IconType.Folder)
        return _icon_cache[key]
    ext = entry.extension
    if local and ext in ("exe", "lnk", "ico", "url"):
        from PyQt6.QtCore import QFileInfo
        return _provider.icon(QFileInfo(entry.path))
    key = "." + ext
    if key not in _icon_cache:
        from PyQt6.QtCore import QFileInfo
        icon = _provider.icon(QFileInfo(f"x.{ext}")) if ext else QIcon()
        if icon.isNull():
            icon = _provider.icon(QFileIconProvider.IconType.File)
        _icon_cache[key] = icon
    return _icon_cache[key]


def type_label(entry: FileEntry) -> str:
    if entry.is_dir:
        return tr("fb.type.link_dir") if entry.is_link else tr("fb.type.dir")
    ext = entry.extension
    if entry.is_link:
        return tr("fb.type.link")
    return tr("fb.type.file_ext", ext=ext.upper()) if ext else tr("fb.type.file")


UP_NAME = "..."


class FileTableModel(QAbstractTableModel):
    """
    The folder's entries, preceded by a "..." row that leads one level up
    (except in the topmost folder). `entries` holds only the real entries;
    rows are the "..." row plus those.
    """

    def __init__(self, local: bool, parent=None, origin: str = "") -> None:
        super().__init__(parent)
        self.local = local
        self.entries: list[FileEntry] = []
        self.rows: list[FileEntry] = []
        self.side = "local" if local else "remote"
        self.origin = origin                    # which browser window a drag comes from
        self.drop_row = -1                      # folder row highlighted during a drag
        self.drop_color: Optional[QColor] = None
        self.up_icon: Optional[QIcon] = None
        self.up_tooltip = ""

    def set_entries(self, entries: list[FileEntry], parent_dir: Optional[str] = None) -> None:
        """parent_dir: target of the "..." row, None in the topmost folder."""
        self.beginResetModel()
        self.entries = list(entries)
        up = [FileEntry(name=UP_NAME, path=parent_dir, is_dir=True, is_up=True)] \
            if parent_dir is not None else []
        self.rows = up + self.entries
        self.drop_row = -1
        self.endResetModel()

    @property
    def has_up(self) -> bool:
        return bool(self.rows) and self.rows[0].is_up

    def set_drop_row(self, row: int) -> None:
        if row == self.drop_row:
            return
        old, self.drop_row = self.drop_row, row
        for r in (old, row):
            if 0 <= r < len(self.rows):
                self.dataChanged.emit(self.index(r, 0), self.index(r, self.columnCount() - 1))

    def entry(self, row: int) -> Optional[FileEntry]:
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 6

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return [tr("fb.col.name"), tr("fb.col.size"), tr("fb.col.modified"),
                    tr("fb.col.type"), tr("fb.col.permissions"), tr("fb.col.owner")][section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        e = self.rows[index.row()]
        col = index.column()
        if e.is_up:
            if role == Qt.ItemDataRole.DisplayRole:
                return UP_NAME if col == COL_NAME else ""
            if role == Qt.ItemDataRole.DecorationRole and col == COL_NAME:
                return self.up_icon or icon_for(e, self.local)
            if role == Qt.ItemDataRole.ToolTipRole:
                return self.up_tooltip or None
            if role == Qt.ItemDataRole.BackgroundRole and index.row() == self.drop_row:
                return self.drop_color
            return e if role == ENTRY_ROLE else None
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return e.name
            if col == COL_SIZE:
                return "" if e.is_dir else fmt_size(e.size)
            if col == COL_MTIME:
                if not e.mtime:
                    return ""
                try:
                    return datetime.fromtimestamp(e.mtime).strftime("%Y-%m-%d %H:%M")
                except (OverflowError, OSError, ValueError):
                    return ""
            if col == COL_TYPE:
                return type_label(e)
            if col == COL_PERMS:
                return e.permissions
            if col == COL_OWNER:
                return f"{e.owner}:{e.group}" if e.owner or e.group else ""
        elif role == Qt.ItemDataRole.DecorationRole and col == COL_NAME:
            return icon_for(e, self.local)
        elif role == Qt.ItemDataRole.TextAlignmentRole and col == COL_SIZE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif role == Qt.ItemDataRole.ToolTipRole and col == COL_NAME:
            return e.path
        elif role == Qt.ItemDataRole.BackgroundRole and index.row() == self.drop_row:
            return self.drop_color
        elif role == ENTRY_ROLE:
            return e
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if not index.isValid():
            return base | Qt.ItemFlag.ItemIsDropEnabled
        e = self.rows[index.row()]
        if e.is_up:                             # a drop target, never dragged itself
            return base | Qt.ItemFlag.ItemIsDropEnabled
        flags = base | Qt.ItemFlag.ItemIsDragEnabled
        if e.is_dir:
            flags |= Qt.ItemFlag.ItemIsDropEnabled
        return flags

    # drag & drop
    def supportedDragActions(self) -> Qt.DropAction:  # noqa: N802
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    def supportedDropActions(self) -> Qt.DropAction:  # noqa: N802
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:  # noqa: N802
        return [MIME_ENTRIES, "text/uri-list"]

    def mimeData(self, indexes) -> QMimeData:  # noqa: N802
        rows = sorted({i.row() for i in indexes})
        entries = [self.rows[r] for r in rows if 0 <= r < len(self.rows) and not self.rows[r].is_up]
        return make_mime(self.side, entries, self.origin)


def make_mime(side: str, entries: list[FileEntry], origin: str = "") -> QMimeData:
    """origin identifies the browser window: server paths only mean something there."""
    mime = QMimeData()
    payload = {"side": side, "origin": origin, "entries": [
        {"name": e.name, "path": e.path, "is_dir": e.is_dir, "size": e.size, "mtime": e.mtime}
        for e in entries
    ]}
    mime.setData(MIME_ENTRIES, json.dumps(payload).encode("utf-8"))
    if side == "local":
        # Local files are real files: Explorer and other apps accept them too.
        mime.setUrls([QUrl.fromLocalFile(e.path) for e in entries])
    return mime


def read_mime(mime: QMimeData) -> tuple[Optional[str], list[FileEntry]]:
    """(side, entries) from our own payload, or ('explorer', files) for URLs."""
    if mime.hasFormat(MIME_ENTRIES):
        try:
            payload = json.loads(bytes(mime.data(MIME_ENTRIES)).decode("utf-8"))
            return payload["side"], [FileEntry(**e) for e in payload["entries"]]
        except (ValueError, KeyError, TypeError):
            return None, []
    if mime.hasUrls():
        entries = []
        for url in mime.urls():
            if url.isLocalFile():
                path = os.path.normpath(url.toLocalFile())
                entries.append(FileEntry(name=os.path.basename(path.rstrip("\\/")) or path,
                                         path=path, is_dir=os.path.isdir(path)))
        return "explorer", entries
    return None, []


def mime_origin(mime: QMimeData) -> str:
    """The browser window a drag of ours started in ("" for Explorer drags)."""
    if not mime.hasFormat(MIME_ENTRIES):
        return ""
    try:
        return str(json.loads(bytes(mime.data(MIME_ENTRIES)).decode("utf-8")).get("origin", ""))
    except (ValueError, AttributeError):
        return ""


class FileProxy(QSortFilterProxyModel):
    """"..." then folders on top in both sort directions; text filter; hidden files."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text = ""
        self.show_hidden = False
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_filter_text(self, text: str) -> None:
        self._text = text.strip().lower()
        self.invalidateFilter()

    def set_show_hidden(self, show: bool) -> None:
        self.show_hidden = show
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:  # noqa: N802
        model: FileTableModel = self.sourceModel()
        e = model.entry(row)
        if e is None:
            return False
        if e.is_up:
            return True                         # "..." is never filtered away
        if not self.show_hidden and is_hidden(e):
            return False
        return not self._text or self._text in e.name.lower()

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        model: FileTableModel = self.sourceModel()
        a, b = model.entry(left.row()), model.entry(right.row())
        if a is None or b is None:
            return False
        if a.is_up or b.is_up:
            # "..." stays first; Qt reverses the result for descending order.
            descending = self.sortOrder() == Qt.SortOrder.DescendingOrder
            return b.is_up if descending else a.is_up
        if a.is_dir != b.is_dir:
            descending = self.sortOrder() == Qt.SortOrder.DescendingOrder
            return b.is_dir if descending else a.is_dir
        col = left.column()
        if col == COL_SIZE:
            return a.size < b.size
        if col == COL_MTIME:
            return a.mtime < b.mtime
        if col == COL_TYPE:
            return (a.extension, _natural_key(a.name)) < (b.extension, _natural_key(b.name))
        if col == COL_PERMS:
            return a.permissions < b.permissions
        if col == COL_OWNER:
            return (a.owner, a.group) < (b.owner, b.group)
        return _natural_key(a.name) < _natural_key(b.name)
