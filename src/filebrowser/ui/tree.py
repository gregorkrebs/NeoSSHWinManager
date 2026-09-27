"""
tree.py – Lazy folder tree (folders and files) for one side of a pane.

Children are listed only when a folder is expanded, in a background thread.
Clicking a folder navigates the pane there; double-clicking a file opens it.
Items can be dragged out, and folders accept drops (a collapsed folder opens
when the drag rests on it).
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush
from PyQt6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from src.filebrowser.model import FileEntry, is_hidden
from src.filebrowser.threads import TaskRunner
from src.filebrowser.ui.models import MIME_ENTRIES, icon_for, make_mime, read_mime
from src.i18n import tr

_ENTRY = Qt.ItemDataRole.UserRole + 1
_LOADED = Qt.ItemDataRole.UserRole + 2


class FsTree(QTreeWidget):
    navigate_requested = pyqtSignal(str)          # folder path
    open_requested = pyqtSignal(object)           # FileEntry (file)
    dropped = pyqtSignal(object)                  # drop plan (side, entries, target)

    def __init__(self, fs, tasks: TaskRunner, parent=None, origin: str = "",
                 root: Optional[str] = None, root_label: Optional[str] = None) -> None:
        super().__init__(parent)
        self.setObjectName("fbTree")
        self.fs = fs
        self._tasks = tasks
        self.show_hidden = False
        self._local = bool(getattr(fs, "is_local", False))
        self.origin = origin
        # Server side: the top folder (home path of the connection, not "/"
        # by default – many accounts may not list "/" or "/home").
        self.root_path = root
        self.root_label = root_label
        # Set by the pane: callable(mime, target folder) -> plan or None.
        self.drop_plan: Optional[Callable] = None
        self.drop_color = None
        self._drop_item: Optional[QTreeWidgetItem] = None
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setAnimated(False)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDropIndicatorShown(False)
        self.setAutoExpandDelay(700)
        self.itemExpanded.connect(self._on_expanded)
        self.itemClicked.connect(self._on_clicked)
        self.itemDoubleClicked.connect(self._on_double_clicked)
        self._pending_reveal: Optional[str] = None

    # building
    def load_root(self) -> None:
        self.clear()
        self._pending_reveal = None
        self._drop_item = None
        if self._local:
            self._load_children(None, self.fs.root)
        else:
            root = self.root_path or "/"
            top = self._make_item(FileEntry(name=self.root_label or root, path=root, is_dir=True))
            self.addTopLevelItem(top)
            top.setExpanded(True)

    def _make_item(self, entry: FileEntry) -> QTreeWidgetItem:
        item = QTreeWidgetItem([entry.name])
        item.setData(0, _ENTRY, entry)
        item.setIcon(0, icon_for(entry, self._local))
        item.setToolTip(0, entry.path)
        if entry.is_dir:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            item.setData(0, _LOADED, False)
        return item

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        if item.data(0, _LOADED):
            return
        entry: FileEntry = item.data(0, _ENTRY)
        self._load_children(item, entry.path)

    def _load_children(self, item: Optional[QTreeWidgetItem], path: str,
                       then: Optional[Callable[[], None]] = None) -> None:
        if item is not None:
            item.setData(0, _LOADED, True)
            loading = QTreeWidgetItem([tr("fb.status.loading")])
            loading.setFlags(Qt.ItemFlag.NoItemFlags)
            item.addChild(loading)

        def done(entries: list[FileEntry]) -> None:
            if item is not None:
                item.takeChildren()
            for e in entries:
                if not self.show_hidden and is_hidden(e):
                    continue
                child = self._make_item(e)
                if item is None:
                    self.addTopLevelItem(child)
                else:
                    item.addChild(child)
            if item is not None and item.childCount() == 0:
                item.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicatorWhenChildless)
            if then:
                then()
            elif self._pending_reveal:
                self._reveal_step()              # a reveal was waiting for this folder

        def failed(_error) -> None:
            if item is not None:
                item.takeChildren()
                item.setData(0, _LOADED, False)
            if self._pending_reveal and self._is_prefix(path, self._pending_reveal):
                self._pending_reveal = None      # e.g. no permission: cannot go deeper

        self._tasks.run(lambda: self.fs.listdir(path), done, failed)

    @staticmethod
    def _is_loading(item: QTreeWidgetItem) -> bool:
        """Children are being listed (only the "Loading…" placeholder is there)."""
        return item.childCount() == 1 and item.child(0).data(0, _ENTRY) is None

    def refresh_folder(self, path: str) -> None:
        """Reload one folder if it is already loaded (after uploads, deletes …)."""
        item = self._find_loaded(path)
        if item is not None and item.isExpanded():
            # The highlighted folder (or one still being revealed) may sit below
            # the reloaded one: find it again once the new children are in.
            current = self.currentItem()
            entry: Optional[FileEntry] = current.data(0, _ENTRY) if current is not None else None
            wanted = self._pending_reveal or (entry.path if entry is not None else None)
            keep = wanted if wanted and self._is_prefix(path, wanted) \
                and not self._same(path, wanted) else None
            item.takeChildren()
            self._load_children(item, path, then=(lambda: self.reveal(keep)) if keep else None)
        elif item is not None:
            item.takeChildren()
            item.setData(0, _LOADED, False)
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)

    def _find_loaded(self, path: str) -> Optional[QTreeWidgetItem]:
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            it = stack.pop()
            e: FileEntry = it.data(0, _ENTRY)
            if e and self._same(e.path, path):
                return it
            stack.extend(it.child(i) for i in range(it.childCount()))
        return None

    def _same(self, a: str, b: str) -> bool:
        if self._local:
            return a.rstrip("\\/").lower() == b.rstrip("\\/").lower()
        return (a.rstrip("/") or "/") == (b.rstrip("/") or "/")

    # reveal the pane's current folder, expanding level by level
    def reveal(self, path: str) -> None:
        self._pending_reveal = path
        self._reveal_step()

    def _reveal_step(self) -> None:
        target = self._pending_reveal
        if not target:
            return
        best, best_len = None, -1
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            it = stack.pop()
            e: FileEntry = it.data(0, _ENTRY)
            if e is None or not e.is_dir:
                continue
            if self._is_prefix(e.path, target) and len(e.path) > best_len:
                best, best_len = it, len(e.path)
            if it.data(0, _LOADED):
                stack.extend(it.child(i) for i in range(it.childCount()))
        if best is None:
            self._pending_reveal = None          # outside the tree (above its root)
            return
        entry: FileEntry = best.data(0, _ENTRY)
        if self._same(entry.path, target):
            self._pending_reveal = None
            self.setCurrentItem(best)
            self.scrollToItem(best)
            return
        if best.data(0, _LOADED) and self._is_loading(best):
            best.setExpanded(True)
            return                               # continues when the listing arrives
        if best.data(0, _LOADED):
            best.setExpanded(True)
            self._pending_reveal = None           # next level not listed (hidden/filtered)
            self.setCurrentItem(best)
            return
        # _load_children marks the item loaded first, so expanding it right
        # after does not start a second listing via itemExpanded.
        self._load_children(best, entry.path, then=self._reveal_step)
        best.setExpanded(True)

    def _is_prefix(self, base: str, path: str) -> bool:
        if self._local:
            b, p = base.rstrip("\\/").lower(), path.rstrip("\\/").lower()
            return p == b or p.startswith(b + "\\")
        b, p = base.rstrip("/") or "/", path.rstrip("/") or "/"
        return b == "/" or p == b or p.startswith(b + "/")

    # interaction
    def _on_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        entry: FileEntry = item.data(0, _ENTRY)
        if entry and entry.is_dir:
            self.navigate_requested.emit(entry.path)

    def _on_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        entry: FileEntry = item.data(0, _ENTRY)
        if entry and not entry.is_dir:
            self.open_requested.emit(entry)

    def mimeData(self, items):  # noqa: N802
        entries = [it.data(0, _ENTRY) for it in items if it.data(0, _ENTRY)]
        return make_mime("local" if self._local else "remote", entries, self.origin)

    # dropping onto a folder
    def mimeTypes(self) -> list[str]:  # noqa: N802
        # Lets the base class enter its drag state (auto-scroll, auto-expand).
        return [MIME_ENTRIES, "text/uri-list"]

    def _plan_at(self, event):
        item = self.itemAt(event.position().toPoint())
        entry: Optional[FileEntry] = item.data(0, _ENTRY) if item is not None else None
        if entry is None or not entry.is_dir or self.drop_plan is None:
            return None, None
        plan = self.drop_plan(event.mimeData(), entry.path)
        return (item, plan) if plan else (None, None)

    def _highlight(self, item: Optional[QTreeWidgetItem]) -> None:
        if item is self._drop_item:
            return
        if self._drop_item is not None:
            try:
                self._drop_item.setBackground(0, QBrush())
            except RuntimeError:
                pass                             # reloaded while dragging
        self._drop_item = item
        if item is not None and self.drop_color is not None:
            item.setBackground(0, self.drop_color)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        super().dragEnterEvent(event)
        if read_mime(event.mimeData())[1]:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()                       # keep receiving move events
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        super().dragMoveEvent(event)             # auto-scroll and auto-expand
        item, plan = self._plan_at(event)
        self._highlight(item)
        if plan:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._highlight(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        _item, plan = self._plan_at(event)
        self._highlight(None)
        self.stopAutoScroll()
        self.setState(QAbstractItemView.State.NoState)
        if not plan:
            event.ignore()
            return
        # Copy action: the drag source must never delete anything itself.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.dropped.emit(plan)
