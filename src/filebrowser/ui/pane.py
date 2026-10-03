"""
pane.py – One file pane: header (navigation, breadcrumbs, bookmarks, filter),
the file table and an optional folder tree.

A pane shows either the server ("remote") or this PC ("local"). It owns
navigation state; everything that changes files is delegated to the window
controller (`ctl`), which knows about transfers, dialogs and the other pane.
"""

from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QEvent, QItemSelectionModel, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDragLeaveEvent, QFont, QFontMetrics, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QSizePolicy,
    QSplitter, QStackedWidget, QToolButton, QTreeView, QVBoxLayout, QWidget,
)

from src.filebrowser.model import FileEntry, fmt_size, lparts, path_within, rparts, same_path
from src.filebrowser.threads import TaskRunner
from src.filebrowser.ui.models import (
    COL_MTIME, COL_NAME, COL_OWNER, COL_PERMS, COL_SIZE, COL_TYPE, ENTRY_ROLE,
    FileProxy, FileTableModel, mime_origin, read_mime,
)
from src.filebrowser.ui.tree import FsTree
from src.i18n import tr
from src.remote_path import normalize_remote_input
from src.ui.icons import icon as svg_icon


def tool_button(icon_name: str, tooltip: str, color: str, text: str = "",
                checkable: bool = False) -> QToolButton:
    btn = QToolButton()
    btn.setObjectName("fbTool")
    btn.setProperty("fbIcon", icon_name)         # re-coloured on a theme switch
    btn.setIcon(svg_icon(icon_name, color, 16))
    btn.setIconSize(QSize(16, 16))
    btn.setToolTip(tooltip)
    btn.setCheckable(checkable)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    if text:
        btn.setText(text)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    return btn


# ── Breadcrumbs ──────────────────────────────────────────────────────────────

class CrumbButton(QToolButton):
    """One path segment; files and folders can be dropped onto it."""

    def __init__(self, crumbs: "Breadcrumbs", target: str) -> None:
        super().__init__()
        self._crumbs = crumbs
        self.target = target
        self.setObjectName("fbCrumb")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptDrops(True)

    def _plan(self, event):
        check = self._crumbs.drop_plan
        return check(event.mimeData(), self.target) if check else None

    def _mark(self, on: bool) -> None:
        self.setProperty("dropTarget", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._plan(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self._mark(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._plan(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._mark(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._mark(False)
        plan = self._plan(event)
        if not plan:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)   # the source never deletes anything
        event.accept()
        self._crumbs.dropped.emit(plan)


class Breadcrumbs(QStackedWidget):
    """
    Clickable path segments; click the free area (or Ctrl+L) to type a path.
    Dropping files onto a segment moves (or transfers) them into that folder.

    The bar never demands the width of the whole path: segments that do not
    fit move into the "…" menu on the left, so a long local path does not
    make its pane wider than the other one.
    """

    navigate = pyqtSignal(str)
    dropped = pyqtSignal(object)            # drop plan (side, entries, target)
    MAX_SEGMENTS = 7
    MIN_WIDTH = 60

    def __init__(self, local: bool, parent=None) -> None:
        super().__init__(parent)
        self._local = local
        self._path = ""
        self._display = ""
        self._segments: list[tuple[str, str]] = []
        self._shown: Optional[tuple] = None      # what the buttons currently show
        # Set by the pane: callable(mime, target folder) -> plan or None.
        self.drop_plan = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setFixedHeight(28)

        self._crumbs = QWidget()
        self._crumbs.setObjectName("fbCrumbs")
        self._crumbs.setCursor(Qt.CursorShape.IBeamCursor)
        self._crumbs_l = QHBoxLayout(self._crumbs)
        self._crumbs_l.setContentsMargins(4, 0, 4, 0)
        self._crumbs_l.setSpacing(0)
        self._crumbs.mousePressEvent = lambda _e: self.start_edit()
        self.addWidget(self._crumbs)

        self._edit = QLineEdit()
        self._edit.setObjectName("fbPath")
        self._edit.returnPressed.connect(self._commit)
        self._edit.installEventFilter(self)
        self.addWidget(self._edit)

    def set_path(self, path: str, display: Optional[str] = None) -> None:
        self._path = path
        self._display = display if display is not None else path
        self._segments = lparts(path) if self._local else rparts(path)
        self._shown = None
        self._build_crumbs()
        self.setCurrentWidget(self._crumbs)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._build_crumbs()

    def _label(self, label: str) -> str:
        return label if label != "⌂" else tr("fb.local.this_pc")

    def _fit(self) -> tuple[int, str, bool]:
        """
        How many trailing segments fit into the bar, the last label (elided if
        needed) and whether the "…" menu for the hidden ones still fits.
        """
        labels = [self._label(label) for label, _t in self._segments]
        if not labels:
            return 0, "", False
        font = QFont(self.font())
        font.setPixelSize(12)                    # as in the stylesheet (fbCrumb)
        fm = QFontMetrics(font)
        pad, sep = 16, fm.horizontalAdvance("›") + 8
        more = fm.horizontalAdvance("…") + pad
        avail = max(0, self.width() - 10)
        count = used = 0
        for i in range(len(labels) - 1, -1, -1):
            width = fm.horizontalAdvance(labels[i]) + pad + (sep if count else 0)
            reserve = more + sep if i > 0 else 0         # "…" for what stays hidden
            if count and (count >= self.MAX_SEGMENTS or used + width + reserve > avail):
                break
            used += width
            count += 1
        last = labels[-1]
        show_more = count < len(labels)
        if count == 1:
            room = avail - pad - (more + sep if show_more else 0)
            if show_more and room < 70:
                # Very narrow: the current folder's name matters more than "…".
                show_more = False
                room = avail - pad
            last = fm.elidedText(last, Qt.TextElideMode.ElideMiddle, max(24, room))
        return count, last, show_more

    def _build_crumbs(self) -> None:
        count, last, show_more = self._fit()
        shown = (tuple(self._segments), count, last, show_more)
        if shown == self._shown:
            return                               # nothing changed (most resize steps)
        self._shown = shown
        while self._crumbs_l.count():
            item = self._crumbs_l.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        segments = self._segments
        hidden = segments[:len(segments) - count] if show_more else []
        visible = segments[len(segments) - count:]
        if hidden:
            more = QToolButton()
            more.setObjectName("fbCrumb")
            more.setText("…")
            menu = QMenu(more)
            for label, target in hidden:
                menu.addAction(self._label(label), lambda t=target: self.navigate.emit(t))
            more.setMenu(menu)
            more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self._crumbs_l.addWidget(more)
        for i, (label, target) in enumerate(visible):
            if i or hidden:
                sep = QLabel("›")
                sep.setObjectName("fbCrumbSep")
                self._crumbs_l.addWidget(sep)
            btn = CrumbButton(self, target)
            is_last = i == len(visible) - 1
            btn.setText(last if is_last else self._label(label))
            if is_last and last != self._label(label):
                btn.setToolTip(self._label(label))
            btn.clicked.connect(lambda _c=False, t=target: self.navigate.emit(t))
            self._crumbs_l.addWidget(btn)
        self._crumbs_l.addStretch()

    def start_edit(self) -> None:
        self._edit.setText(self._display)
        self.setCurrentWidget(self._edit)
        self._edit.setFocus()
        self._edit.selectAll()

    def _commit(self) -> None:
        text = self._edit.text().strip()
        self.setCurrentWidget(self._crumbs)
        if text:
            self.navigate.emit(text)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._edit:
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self.setCurrentWidget(self._crumbs)
                return True
            if event.type() == QEvent.Type.FocusOut:
                self.setCurrentWidget(self._crumbs)
        return super().eventFilter(obj, event)


# ── File view with drag & drop and mouse back/forward ────────────────────────

class FileView(QTreeView):
    def __init__(self, pane: "FilePane") -> None:
        super().__init__()
        self._pane = pane
        self.setObjectName("fbTable")
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setSortingEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        # The target folder row is highlighted instead of an "insert between
        # rows" line, which would suggest an order that does not exist.
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        pane = getattr(self, "_pane", None)
        if pane is not None:
            pane.fit_columns()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.BackButton:
            self._pane.go_back()
            return
        if event.button() == Qt.MouseButton.ForwardButton:
            self._pane.go_forward()
            return
        super().mousePressEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._pane.activated.emit(self._pane)

    def _drop_plan(self, event):
        """Plan for the folder row under the cursor, else for the current folder."""
        index = self.indexAt(event.position().toPoint())
        entry = self._pane.entry_at(index) if index.isValid() else None
        if entry is not None and entry.is_dir:
            plan = self._pane.plan_drop(event.mimeData(), entry.path)
            return plan, (index if plan else None)
        return self._pane.plan_drop(event.mimeData(), self._pane.current_dir), None

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        super().dragEnterEvent(event)            # drag state for auto-scroll
        if read_mime(event.mimeData())[1]:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()                       # keep receiving move events
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        super().dragMoveEvent(event)             # auto-scroll near the edges
        plan, row = self._drop_plan(event)
        self._pane.highlight_drop(row)
        if plan:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._pane.highlight_drop(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        plan, _row = self._drop_plan(event)
        self._pane.highlight_drop(None)
        # Qt's drag-leave stops the auto-scroll and resets the drag state;
        # PyQt6 does not expose stopAutoScroll() itself.
        super().dragLeaveEvent(QDragLeaveEvent())
        if not plan:
            event.ignore()
            return
        # Copy action: the drag source must never delete rows or files itself.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self._pane.ctl.handle_drop(self._pane, *plan)


# ── Pane ─────────────────────────────────────────────────────────────────────

class FilePane(QWidget):
    activated = pyqtSignal(object)          # self
    status_changed = pyqtSignal(object)     # self
    path_changed = pyqtSignal(object)       # self

    def __init__(self, ctl, fs, side: str, settings, conn_id: str, icon_color: str,
                 tree_root: Optional[str] = None, origin: Optional[str] = None) -> None:
        super().__init__()
        self._tree_root = tree_root
        self.session = None                      # the host session (set by the window)
        self.setObjectName("fbPane")
        self.ctl = ctl
        self.fs = fs
        self.side = side
        self.local = side == "local"
        self._settings = settings
        self._conn_id = conn_id
        self._icon_color = icon_color
        # Identifies the host session in drag payloads: server paths from
        # another session (tab of another host, another window) belong to
        # another server.
        self._origin = origin if origin is not None else str(getattr(ctl, "drag_origin", ""))
        accent = getattr(getattr(ctl, "palette", None), "accent", "#0077b6")
        self._drop_color = QColor(accent)
        self._drop_color.setAlpha(90)
        self._tasks = TaskRunner(self)
        self.current_dir = ""
        self._history: list[str] = []
        self._forward: list[str] = []
        self._load_seq = 0
        self._loading = False
        self._build()
        self._shortcuts()

    # ── construction ─────────────────────────────────────────────────────────

    def _build(self) -> None:
        c = self._icon_color
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setObjectName("fbPaneHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(6, 5, 6, 5)
        h.setSpacing(3)
        self._btn_back = tool_button("arrow-left", tr("fb.nav.back") + "  (Alt+←)", c)
        self._btn_back.clicked.connect(self.go_back)
        self._btn_fwd = tool_button("arrow-right", tr("fb.nav.forward") + "  (Alt+→)", c)
        self._btn_fwd.clicked.connect(self.go_forward)
        self._btn_up = tool_button("arrow-up", tr("fb.nav.up") + "  (Alt+↑)", c)
        self._btn_up.clicked.connect(self.go_up)
        self._btn_refresh = tool_button("refresh", tr("fb.nav.refresh") + "  (F5)", c)
        self._btn_refresh.clicked.connect(self.refresh)
        for b in (self._btn_back, self._btn_fwd, self._btn_up, self._btn_refresh):
            h.addWidget(b)

        side_label = QLabel(tr("fb.side.local") if self.local else tr("fb.side.remote"))
        side_label.setObjectName("fbHint")
        side_label.setMinimumWidth(1)            # gives way first when the pane is narrow
        h.addSpacing(4)
        h.addWidget(side_label)
        h.addSpacing(2)

        self._crumbs = Breadcrumbs(self.local)
        self._crumbs.navigate.connect(self._navigate_typed)
        self._crumbs.drop_plan = self.plan_drop
        self._crumbs.dropped.connect(lambda plan: self.ctl.handle_drop(self, *plan))
        h.addWidget(self._crumbs, stretch=1)

        self._btn_bookmark = None
        if not self.local:
            self._btn_bookmark = tool_button("star", tr("fb.bookmarks.title") + "  (Ctrl+D)", c)
            self._btn_bookmark.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            self._btn_bookmark.clicked.connect(self.toggle_bookmark)
            self._bookmark_menu = QMenu(self._btn_bookmark)
            self._bookmark_menu.aboutToShow.connect(self._fill_bookmark_menu)
            self._btn_bookmark.setMenu(self._bookmark_menu)
            h.addWidget(self._btn_bookmark)

        self._filter = QLineEdit()
        self._filter.setObjectName("fbFilter")
        self._filter.setPlaceholderText(tr("fb.filter.placeholder"))
        self._filter.setClearButtonEnabled(True)
        self._filter.addAction(svg_icon("search", c, 14), QLineEdit.ActionPosition.LeadingPosition)
        # Full width when there is room, narrower when the pane is squeezed.
        self._filter.setMinimumWidth(70)
        self._filter.setMaximumWidth(170)
        self._filter.textChanged.connect(self._on_filter)
        h.addWidget(self._filter)
        root.addWidget(header)

        self._model = FileTableModel(self.local, self, origin=self._origin)
        self._model.drop_color = self._drop_color
        self._model.up_icon = svg_icon("arrow-up", c, 16)
        self._model.up_tooltip = tr("fb.nav.up") + "  (Backspace)"
        self._proxy = FileProxy(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.set_show_hidden(self._settings.settings.show_hidden)
        self.view = FileView(self)
        self.view.setModel(self._proxy)
        self.view.sortByColumn(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.view.doubleClicked.connect(self._on_double_click)
        self.view.customContextMenuRequested.connect(self._on_context_menu)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self.status_changed.emit(self))
        hdr = self.view.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        if self.local or getattr(self.fs, "is_windows", False):
            # Local files have no POSIX modes; Windows OpenSSH only emulates them.
            self._base_hidden = {COL_PERMS, COL_OWNER}
        else:
            self._base_hidden = set()
        for col in self._base_hidden:
            hdr.hideSection(col)
        self._restore_columns(hdr)
        # Only now: eventFilter uses both widgets, and an exception inside a Qt
        # virtual makes PyQt abort the whole process (qFatal).
        self._filter.installEventFilter(self)
        self.view.installEventFilter(self)

        top = self._tree_root
        self.tree = FsTree(self.fs, self._tasks, origin=self._origin, root=top,
                           root_label=self.display_path(top) if top else None)
        self.tree.show_hidden = self._settings.settings.show_hidden
        self.tree.navigate_requested.connect(lambda p: self.navigate(p))
        self.tree.open_requested.connect(lambda e: self.ctl.open_entry(self, e))
        self.tree.drop_plan = self.plan_drop
        self.tree.drop_color = self._drop_color
        self.tree.dropped.connect(lambda plan: self.ctl.handle_drop(self, *plan))
        self.tree.setMinimumWidth(160)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        if self.local:                        # local tree on the far left …
            self.splitter.addWidget(self.tree)
            self.splitter.addWidget(self.view)
            self.splitter.setStretchFactor(1, 1)
        else:                                 # … remote tree on the far right
            self.splitter.addWidget(self.view)
            self.splitter.addWidget(self.tree)
            self.splitter.setStretchFactor(0, 1)
        root.addWidget(self.splitter, stretch=1)
        self._tree_loaded = False
        self.set_tree_visible(self._settings.settings.show_tree)
        self._update_nav()

    def _shortcuts(self) -> None:
        def on_view(seq, fn):
            QShortcut(QKeySequence(seq), self.view, fn,
                      context=Qt.ShortcutContext.WidgetShortcut)

        def in_pane(seq, fn):
            QShortcut(QKeySequence(seq), self, fn,
                      context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

        on_view("Return", self._open_selection)
        on_view("Enter", self._open_selection)
        on_view("Backspace", self.go_up)
        on_view("Del", lambda: self.ctl.delete_entries(self, self.selected_entries()))
        on_view("F2", lambda: self.ctl.rename_entry(self, self.current_entry()))
        on_view("Tab", lambda: self.ctl.focus_other_pane(self))
        in_pane("F5", self.refresh)
        in_pane("Ctrl+R", self.refresh)
        in_pane("Alt+Up", self.go_up)
        in_pane("Alt+Left", self.go_back)
        in_pane("Alt+Right", self.go_forward)
        in_pane("Ctrl+L", self._crumbs.start_edit)
        in_pane("F4", self._crumbs.start_edit)
        in_pane("Ctrl+F", self.focus_filter)
        in_pane("F7", lambda: self.ctl.new_folder(self))
        in_pane("Ctrl+Shift+N", lambda: self.ctl.new_folder(self))
        in_pane("Shift+F4", lambda: self.ctl.new_file(self))
        in_pane("Alt+Return", lambda: self.ctl.properties(self, self.selected_entries()))
        in_pane("F6", lambda: self.ctl.transfer_to_other(self, self.selected_entries()))
        in_pane("Ctrl+Shift+C", lambda: self.ctl.copy_paths(self, self.selected_entries()))
        in_pane("Ctrl+O", lambda: self.ctl.open_with(self, self.current_entry(), choose=True))
        if not self.local:
            in_pane("Ctrl+D", self.toggle_bookmark)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(obj, event)
        view = getattr(self, "view", None)
        filt = getattr(self, "_filter", None)
        if obj is filt and view is not None:
            if event.key() == Qt.Key.Key_Escape:
                filt.clear()
                view.setFocus()
                return True
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Return):
                view.setFocus()
                return True
        if obj is view and filt is not None:
            if event.key() == Qt.Key.Key_Escape and filt.text():
                filt.clear()
                return True
        return super().eventFilter(obj, event)

    # ── settings ─────────────────────────────────────────────────────────────

    def apply_settings(self, settings) -> None:
        self._proxy.set_show_hidden(settings.show_hidden)
        if self.tree.show_hidden != settings.show_hidden:
            self.tree.show_hidden = settings.show_hidden
            if self._tree_loaded:
                self.tree.load_root()
                self.tree.reveal(self.current_dir)
        self.set_tree_visible(settings.show_tree)
        self.status_changed.emit(self)

    def set_icon_color(self, color: str) -> None:
        """Theme switch: the browser re-coloured the buttons; redraw the bookmark star."""
        self._icon_color = color
        if self.current_dir is not None:
            self._update_nav()

    def set_drop_color(self, accent: str) -> None:
        """Accent switch: the drag-and-drop highlight follows the accent."""
        self._drop_color = QColor(accent)
        self._drop_color.setAlpha(90)

    def set_tree_root(self, root: str) -> None:
        """Server tree: start at another folder (setting changed)."""
        if self.local or same_path(root, self.tree.root_path or "/", False):
            return
        self.tree.root_path = root
        self.tree.root_label = self.display_path(root)
        if self._tree_loaded:
            self.tree.load_root()
            if self.current_dir:
                self.tree.reveal(self.current_dir)

    def set_tree_visible(self, visible: bool) -> None:
        self.tree.setVisible(visible)
        if visible and not self._tree_loaded and self.current_dir is not None:
            self._tree_loaded = True
            self.tree.load_root()
            if self.current_dir:
                self.tree.reveal(self.current_dir)
        if visible:
            sizes = self.splitter.sizes()
            total = sum(sizes) or 800
            tree_w = min(260, max(180, total // 4))
            self.splitter.setSizes([tree_w, total - tree_w] if self.local
                                   else [total - tree_w, tree_w])

    _COL_WIDTHS = {COL_SIZE: 85, COL_MTIME: 125, COL_TYPE: 110, COL_PERMS: 95, COL_OWNER: 110}
    # Least important first; in a very narrow pane only the name is left.
    _DROP_ORDER = (COL_OWNER, COL_PERMS, COL_TYPE, COL_MTIME, COL_SIZE)

    def _column_state(self) -> dict:
        return self._settings.settings.window.setdefault(f"columns_{self.side}", {})

    def _restore_columns(self, hdr) -> None:
        """Remembered column widths and sort order (per side: PC / server)."""
        state = self._column_state()
        self._widths = dict(self._COL_WIDTHS)
        for key, width in (state.get("widths") or {}).items():
            try:
                col, width = int(key), int(width)
            except (TypeError, ValueError):
                continue
            if col in self._widths and 40 <= width <= 600:
                self._widths[col] = width
        for col, width in self._widths.items():
            hdr.resizeSection(col, width)
        sort = state.get("sort")
        if isinstance(sort, list) and len(sort) == 2 and 0 <= int(sort[0]) < 6:
            order = Qt.SortOrder.DescendingOrder if sort[1] else Qt.SortOrder.AscendingOrder
            self.view.sortByColumn(int(sort[0]), order)
        self._fitting = False
        hdr.sectionResized.connect(self._on_section_resized)
        hdr.sortIndicatorChanged.connect(self._on_sort_changed)

    def _on_section_resized(self, col: int, _old: int, new: int) -> None:
        if self._fitting or col not in self._widths or new <= 0:
            return                               # our own show/hide, not the user
        self._widths[col] = new
        self._column_state()["widths"] = {str(c): w for c, w in self._widths.items()}

    def _on_sort_changed(self, col: int, order) -> None:
        self._column_state()["sort"] = [col, 1 if order == Qt.SortOrder.DescendingOrder else 0]

    def fit_columns(self) -> None:
        """Hide the least important columns when the pane gets narrow (split mode)."""
        base_hidden = getattr(self, "_base_hidden", None)
        widths = getattr(self, "_widths", None)
        if base_hidden is None or widths is None:
            return
        hdr = self.view.header()
        width = self.view.viewport().width()
        visible = [c for c in widths if c not in base_hidden]
        for col in self._DROP_ORDER:
            if col not in visible:
                continue
            if 220 + sum(widths[c] for c in visible) <= width:
                break
            visible.remove(col)
        self._fitting = True
        try:
            for col in widths:
                hidden = col not in visible
                if hdr.isSectionHidden(col) != hidden:
                    hdr.setSectionHidden(col, hidden)
                    if not hidden:
                        hdr.resizeSection(col, widths[col])
        finally:
            self._fitting = False

    def set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    # ── navigation ───────────────────────────────────────────────────────────

    def display_path(self, path: str) -> str:
        if not self.local and getattr(self.fs, "is_windows", False):
            from src.filebrowser.model import windows_remote_to_native
            return windows_remote_to_native(path) if path not in ("", "/") else "/"
        return path

    def _navigate_typed(self, text: str) -> None:
        if self.local:
            path = os.path.normpath(os.path.expandvars(os.path.expanduser(text))) if text else ""
            if len(path) == 2 and path[1] == ":":
                path += "\\"
        else:
            path = normalize_remote_input(text, bool(getattr(self.fs, "is_windows", False)))
        self.navigate(path)

    def navigate(self, path: str, push: bool = True, select: Optional[list[str]] = None) -> None:
        if push and self.current_dir != path and self._history is not None and self._loaded_once():
            self._history.append(self.current_dir)
            self._forward.clear()
        self._load(path, select)

    def _loaded_once(self) -> bool:
        return getattr(self, "_has_loaded", False)

    def refresh(self, select: Optional[list[str]] = None) -> None:
        self._load(self.current_dir, select or [e.name for e in self.selected_entries()],
                   keep_scroll=True)

    def go_up(self) -> None:
        parent = self.fs.parent(self.current_dir)
        if parent != self.current_dir:
            self.navigate(parent, select=[self.fs.basename(self.current_dir)])

    def go_back(self) -> None:
        if self._history:
            self._forward.append(self.current_dir)
            self._load(self._history.pop(), None)

    def go_forward(self) -> None:
        if self._forward:
            self._history.append(self.current_dir)
            self._load(self._forward.pop(), None)

    def _load(self, path: str, select: Optional[list[str]], keep_scroll: bool = False) -> None:
        self._load_seq += 1
        seq = self._load_seq
        self._loading = True
        self.status_changed.emit(self)
        scroll = self.view.verticalScrollBar().value() if keep_scroll else 0

        def done(entries: list[FileEntry]) -> None:
            if seq != self._load_seq:
                return                               # a newer navigation won
            changed = path != self.current_dir
            self.current_dir = path
            self._has_loaded = True
            self._loading = False
            parent = self.fs.parent(path) if path else path
            self._model.set_entries(entries, parent if parent != path else None)
            self._crumbs.set_path(path, self.display_path(path))
            self._update_nav()
            if select:
                self._select_names(select)
            if keep_scroll:
                self.view.verticalScrollBar().setValue(scroll)
            # isHidden(), not isVisible(): the tree also follows while the
            # page or this tab is in the background.
            if changed and not self.tree.isHidden():
                self.tree.reveal(path)
            self.status_changed.emit(self)
            if changed:
                self.path_changed.emit(self)

        def failed(error: BaseException) -> None:
            if seq != self._load_seq:
                return
            self._loading = False
            if self.session is not None and self.session.closed:
                return                               # the tab was closed while listing
            self.status_changed.emit(self)
            self.ctl.show_error(tr("fb.error.list_title"), f"{self.display_path(path)}\n\n{error}")
            if not self._loaded_once():
                fallback = self.fs.root if self.local else "/"
                if path != fallback:
                    self._load(fallback, None)

        self._tasks.run(lambda: self.fs.listdir(path), done, failed)

    def _update_nav(self) -> None:
        self._btn_back.setEnabled(bool(self._history))
        self._btn_fwd.setEnabled(bool(self._forward))
        self._btn_up.setEnabled(self.fs.parent(self.current_dir) != self.current_dir
                                if self.current_dir else False)
        if self._btn_bookmark is not None:
            marked = self.current_dir in self._settings.settings.bookmarks_for(self._conn_id)
            self._btn_bookmark.setIcon(svg_icon("star-filled" if marked else "star",
                                                "#f5b301" if marked else self._icon_color, 16))

    def _select_names(self, names: list[str]) -> None:
        sel = self.view.selectionModel()
        sel.clearSelection()
        first = None
        wanted = set(names)
        for row in range(self._proxy.rowCount()):
            idx = self._proxy.index(row, COL_NAME)
            entry = idx.data(ENTRY_ROLE)
            if entry and entry.name in wanted:
                sel.select(idx, QItemSelectionModel.SelectionFlag.Select
                           | QItemSelectionModel.SelectionFlag.Rows)
                first = first or idx
        if first is not None:
            self.view.setCurrentIndex(first)
            self.view.scrollTo(first)

    # ── selection helpers ────────────────────────────────────────────────────

    def entry_at(self, proxy_index) -> Optional[FileEntry]:
        return proxy_index.data(ENTRY_ROLE) if proxy_index.isValid() else None

    def selected_entries(self) -> list[FileEntry]:
        """The selected files and folders; the "..." row is never one of them."""
        rows = self.view.selectionModel().selectedRows(COL_NAME)
        entries = (r.data(ENTRY_ROLE) for r in rows)
        return [e for e in entries if e is not None and not e.is_up]

    def current_entry(self) -> Optional[FileEntry]:
        sel = self.selected_entries()
        if len(sel) == 1:
            return sel[0]
        idx = self.view.currentIndex()
        entry = self.entry_at(idx.siblingAtColumn(COL_NAME)) if idx.isValid() else None
        return None if entry is None or entry.is_up else entry

    def _up_row_is_current(self) -> bool:
        idx = self.view.currentIndex()
        entry = self.entry_at(idx.siblingAtColumn(COL_NAME)) if idx.isValid() else None
        return entry is not None and entry.is_up

    def entries(self) -> list[FileEntry]:
        return list(self._model.entries)

    def focus_filter(self) -> None:
        self._filter.setFocus()
        self._filter.selectAll()

    def _on_filter(self, text: str) -> None:
        self._proxy.set_filter_text(text)
        self.status_changed.emit(self)

    def status_text(self) -> str:
        if self._loading:
            return tr("fb.status.loading")
        visible = self._proxy.rowCount() - (1 if self._model.has_up else 0)
        sel = self.selected_entries()
        text = tr("fb.status.items", count=visible)
        if sel:
            size = sum(e.size for e in sel if not e.is_dir)
            text += "  ·  " + tr("fb.status.selected", count=len(sel), size=fmt_size(size))
        return text

    def accepts_drop(self, side: Optional[str]) -> bool:
        if self.local:
            return side in ("remote", "local")
        return side in ("explorer", "local", "remote")

    def _is_folder_target(self, target: str) -> bool:
        if self.local:
            return bool(target)                  # "This PC" (drive list) is no folder
        # Windows servers list their drives under "/": nothing can go there.
        return not (getattr(self.fs, "is_windows", False) and target in ("", "/"))

    def _movable(self, entry: FileEntry) -> bool:
        """Drives and "/" stay where they are."""
        parent = self.fs.parent(entry.path)
        if same_path(parent, entry.path, self.local):
            return False
        if self.local:
            return bool(parent)
        return not (getattr(self.fs, "is_windows", False) and parent == "/")

    def plan_drop(self, mime, target: Optional[str]):
        """
        (side, entries, target) when dropping `mime` onto the folder `target`
        of this pane makes sense, else None. Same side = move, other side or
        Explorer = transfer.
        """
        side, entries = read_mime(mime)
        if not entries or target is None or not self.accepts_drop(side):
            return None
        if side == "remote" and mime_origin(mime) != self._origin:
            return None                          # dragged from another server's window
        if not self._is_folder_target(target):
            return None
        if side == self.side:
            entries = [e for e in entries
                       if not same_path(self.fs.parent(e.path), target, self.local)]
            if not entries or not all(self._movable(e) for e in entries):
                return None
            if any(path_within(target, e.path, self.local) for e in entries):
                return None                      # into itself or one of its subfolders
        return side, entries, target

    def highlight_drop(self, proxy_index) -> None:
        row = self._proxy.mapToSource(proxy_index).row() if proxy_index is not None else -1
        self._model.set_drop_row(row)

    # ── actions ──────────────────────────────────────────────────────────────

    def _on_double_click(self, index) -> None:
        entry = self.entry_at(index.siblingAtColumn(COL_NAME))
        if entry is not None and entry.is_up:
            self.go_up()
        elif entry is not None:
            self.ctl.activate_entry(self, entry)

    def _open_selection(self) -> None:
        sel = self.selected_entries()
        if not sel and self._up_row_is_current():
            self.go_up()
        elif len(sel) == 1:
            self.ctl.activate_entry(self, sel[0])
        elif sel:
            self.ctl.open_entries(self, [e for e in sel if not e.is_dir])

    # bookmarks (remote only)
    def toggle_bookmark(self) -> None:
        if self.local or not self.current_dir:
            return
        s = self._settings.settings
        marks = s.bookmarks_for(self._conn_id)
        if self.current_dir in marks:
            marks.remove(self.current_dir)
        else:
            marks.append(self.current_dir)
        s.bookmarks[self._conn_id] = marks
        self._settings.save()
        self._update_nav()

    def _fill_bookmark_menu(self) -> None:
        menu = self._bookmark_menu
        menu.clear()
        marks = self._settings.settings.bookmarks_for(self._conn_id)
        here = self.current_dir in marks
        menu.addAction(svg_icon("star", self._icon_color, 14),
                       tr("fb.bookmarks.remove_here") if here else tr("fb.bookmarks.add_here"),
                       self.toggle_bookmark)
        if marks:
            menu.addSeparator()
            for path in marks:
                act = menu.addAction(svg_icon("folder", self._icon_color, 14), self.display_path(path))
                act.triggered.connect(lambda _c=False, p=path: self.navigate(p))
            menu.addSeparator()
            clear = menu.addMenu(tr("fb.bookmarks.remove"))
            for path in marks:
                clear.addAction(self.display_path(path), lambda p=path: self._remove_bookmark(p))
        else:
            empty = menu.addAction(tr("fb.bookmarks.empty"))
            empty.setEnabled(False)

    def _remove_bookmark(self, path: str) -> None:
        s = self._settings.settings
        s.bookmarks[self._conn_id] = [p for p in s.bookmarks_for(self._conn_id) if p != path]
        self._settings.save()
        self._update_nav()

    # context menu
    def _on_context_menu(self, pos) -> None:
        index = self.view.indexAt(pos)
        if index.isValid() and not self.view.selectionModel().isSelected(index):
            self.view.selectionModel().select(
                index, QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows)
        entries = self.selected_entries() if index.isValid() else []
        menu = self.ctl.build_context_menu(self, entries)
        if menu is not None:
            menu.exec(self.view.viewport().mapToGlobal(pos))
