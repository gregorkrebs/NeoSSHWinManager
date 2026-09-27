"""
dialogs.py – Dialogs of the file browser.

ConflictDialog    target exists: overwrite / keep both / skip / resume / compare
CompareDialog     both files side by side (text diff, image preview, metadata)
OpenWithDialog    choose the program for a file extension (remembered)
SettingsDialog    transfer, view and program settings
MoveConfirmDialog ask before a drag & drop move ("don't ask again")
UrlDialog         fetch a file from an http(s) URL onto the server
PackDialog        archive name + format
PropertiesDialog  details, folder size, permissions (chmod), SHA-256
SyncDialog        compare a local and a remote folder and sync them
ShortcutsDialog   keyboard reference
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPixmap, QTextBlockFormat, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QRadioButton, QScrollArea, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from src.filebrowser import commands
from src.filebrowser.model import (
    ACT_DELETE_LOCAL, ACT_DELETE_REMOTE, ACT_DOWNLOAD, ACT_UPLOAD, CANCEL, KEEP_BOTH,
    OVERWRITE, POLICIES, RESUME, SKIP, SYNC_BOTH, SYNC_DOWNLOAD, SYNC_UPLOAD,
    ConflictInfo, FileEntry, SyncSide, compare_trees, fmt_size, parse_octal_mode,
)
from src.filebrowser.settings import OPEN_WITH_SYSTEM, BrowserSettings
from src.filebrowser.threads import TaskRunner
from src.i18n import tr
from src.ui.frameless_dialog import FramelessDialog

COMPARE = "compare"
_TEXT_LIMIT = 5 * 1024 * 1024
_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "webp", "ico"}


def _btn(text: str, kind: str = "secondaryBtn") -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(kind)
    b.setMinimumHeight(32)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    # Under the app stylesheet the size hint ignores the bold font and the
    # padding, so crowded button rows clipped their labels: reserve the room.
    b.ensurePolished()
    bold = b.font()
    bold.setBold(True)
    from PyQt6.QtGui import QFontMetrics
    b.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(text) + 40)
    return b


def _elide_middle(text: str, limit: int = 64) -> str:
    if len(text) <= limit:
        return text
    keep = (limit - 1) // 2
    return text[:keep] + "…" + text[-keep:]


def _date(ts: float) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "—"


class _Dialog(FramelessDialog):
    def __init__(self, parent, title: str, theme: str, min_width: int = 420) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setObjectName("dialogSurface")
        self.setMinimumWidth(min_width)
        self.set_dialog_theme(theme)
        # Dialogs are separate windows and do not inherit the browser
        # window's stylesheet, so they apply it themselves.
        from src.filebrowser.ui.style import palette, stylesheet
        self._fdlg_content.setStyleSheet(stylesheet(palette(theme)))
        self.body = QVBoxLayout(self._fdlg_content)
        self.body.setContentsMargins(22, 18, 22, 18)
        self.body.setSpacing(12)

    def add_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("msgTitle")
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)
        return lbl

    def add_text(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("msgText")
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)
        return lbl

    def button_row(self, buttons: list[QPushButton], left: Optional[list[QPushButton]] = None) -> None:
        row = QHBoxLayout()
        for b in left or []:
            row.addWidget(b)
        row.addStretch()
        for b in buttons:
            row.addWidget(b)
        self.body.addLayout(row)


def _meta_block(title: str, entry: FileEntry, highlight_newer: bool) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("fbMetaTitle")
    v.addWidget(t)
    for text in (
        _elide_middle(entry.path),
        tr("fb.meta.size", size=fmt_size(entry.size), bytes=f"{entry.size:,}".replace(",", ".")),
        tr("fb.meta.modified", date=_date(entry.mtime)) + ("  ★ " + tr("fb.meta.newer") if highlight_newer else ""),
    ):
        lbl = QLabel(text)
        lbl.setObjectName("fbMeta")
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(lbl)
    w.setToolTip(entry.path)
    return w


# ── Conflict ─────────────────────────────────────────────────────────────────

class ConflictDialog(_Dialog):
    def __init__(self, parent, info: ConflictInfo, theme: str) -> None:
        super().__init__(parent, tr("fb.conflict.title"), theme, 760)
        self.decision = CANCEL
        up = info.direction == "up"
        self.add_title(tr("fb.conflict.text", name=info.target.name))
        cols = QHBoxLayout()
        cols.setSpacing(24)
        src_newer = info.source.mtime > info.target.mtime + 2
        dst_newer = info.target.mtime > info.source.mtime + 2
        cols.addWidget(_meta_block(tr("fb.conflict.source_local") if up else tr("fb.conflict.source_remote"),
                                   info.source, src_newer), 1)
        cols.addWidget(_meta_block(tr("fb.conflict.target_remote") if up else tr("fb.conflict.target_local"),
                                   info.target, dst_newer), 1)
        self.body.addLayout(cols)
        self._all = QCheckBox(tr("fb.conflict.apply_all"))
        self.body.addWidget(self._all)

        buttons = []
        b = _btn(tr("fb.conflict.overwrite"), "primaryBtn")
        b.clicked.connect(lambda: self._done(OVERWRITE))
        buttons.append(b)
        b = _btn(tr("fb.conflict.keep_both"))
        b.clicked.connect(lambda: self._done(KEEP_BOTH))
        buttons.append(b)
        if info.can_resume:
            b = _btn(tr("fb.conflict.resume"))
            b.setToolTip(tr("fb.conflict.resume_hint"))
            b.clicked.connect(lambda: self._done(RESUME))
            buttons.append(b)
        b = _btn(tr("fb.conflict.skip"))
        b.clicked.connect(lambda: self._done(SKIP))
        buttons.append(b)
        compare = _btn(tr("fb.conflict.compare"))
        compare.clicked.connect(lambda: self._done(COMPARE))
        cancel = _btn(tr("fb.conflict.cancel_all"), "dangerBtn")
        cancel.clicked.connect(lambda: self._done(CANCEL))
        self.button_row(buttons, left=[compare])
        # Stopping the whole action is rare and destructive: its own row.
        self.button_row([], left=[cancel])

    def _done(self, decision: str) -> None:
        self.decision = decision
        self.accept()

    @property
    def apply_all(self) -> bool:
        return self._all.isChecked()


# ── Compare ──────────────────────────────────────────────────────────────────

def _read_text(path: str) -> Optional[str]:
    try:
        if os.path.getsize(path) > _TEXT_LIMIT:
            return None
        raw = open(path, "rb").read()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def aligned_diff(left: list[str], right: list[str]) -> list[tuple[str, Optional[str], Optional[str]]]:
    """Side-by-side rows: (tag, left line or None, right line or None)."""
    rows = []
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            rows.extend(("equal", left[i], right[j]) for i, j in zip(range(i1, i2), range(j1, j2)))
            continue
        a, b = left[i1:i2], right[j1:j2]
        for k in range(max(len(a), len(b))):
            rows.append((tag, a[k] if k < len(a) else None, b[k] if k < len(b) else None))
    return rows


class CompareDialog(_Dialog):
    """left = source, right = target (existing file)."""

    def __init__(self, parent, theme: str, palette, left_title: str, left: FileEntry,
                 left_file: str, right_title: str, right: FileEntry, right_file: str,
                 decisions: bool = True, can_resume: bool = False) -> None:
        super().__init__(parent, tr("fb.compare.title"), theme, 900)
        self.resize(1100, 720)
        self.decision: Optional[str] = None
        self._p = palette
        head = QHBoxLayout()
        head.setSpacing(24)
        head.addWidget(_meta_block(left_title, left, left.mtime > right.mtime + 2), 1)
        head.addWidget(_meta_block(right_title, right, right.mtime > left.mtime + 2), 1)
        self.body.addLayout(head)

        self._summary = QLabel()
        self._summary.setObjectName("msgText")
        self.body.addWidget(self._summary)

        ext = left.extension
        if ext in _IMAGE_EXT:
            self._images(left_file, right_file)
        else:
            lt, rt = _read_text(left_file), _read_text(right_file)
            if lt is not None and rt is not None:
                self._text(lt, rt)
            else:
                self._binary(left_file, right_file)

        buttons = []
        if decisions:
            b = _btn(tr("fb.conflict.overwrite"), "primaryBtn")
            b.clicked.connect(lambda: self._done(OVERWRITE))
            buttons.append(b)
            b = _btn(tr("fb.conflict.keep_both"))
            b.clicked.connect(lambda: self._done(KEEP_BOTH))
            buttons.append(b)
            if can_resume:
                b = _btn(tr("fb.conflict.resume"))
                b.clicked.connect(lambda: self._done(RESUME))
                buttons.append(b)
            b = _btn(tr("fb.conflict.skip"))
            b.clicked.connect(lambda: self._done(SKIP))
            buttons.append(b)
            back = _btn(tr("fb.compare.back"))
            back.clicked.connect(self.reject)
            self.button_row(buttons, left=[back])
        else:
            close = _btn(tr("fb.common.close"), "primaryBtn")
            close.clicked.connect(self.accept)
            self.button_row([close])

    def _done(self, decision: str) -> None:
        self.decision = decision
        self.accept()

    def _text(self, lt: str, rt: str) -> None:
        rows = aligned_diff(lt.splitlines(), rt.splitlines())
        changes = sum(1 for tag, _l, _r in rows if tag != "equal")
        self._summary.setText(tr("fb.compare.identical") if not changes
                              else tr("fb.compare.differences", count=changes))
        left, right = QPlainTextEdit(), QPlainTextEdit()
        for ed in (left, right):
            ed.setObjectName("fbCompare")
            ed.setReadOnly(True)
            ed.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        left.setPlainText("\n".join("" if l is None else l for _t, l, _r in rows))
        right.setPlainText("\n".join("" if r is None else r for _t, _l, r in rows))
        colors = {
            "replace": QColor(self._p.warn), "delete": QColor(self._p.error),
            "insert": QColor(self._p.ok),
        }
        for editor, side in ((left, 1), (right, 2)):
            cursor = QTextCursor(editor.document())
            for i, row in enumerate(rows):
                tag = row[0]
                if tag == "equal":
                    continue
                color = QColor(colors.get(tag, QColor(self._p.warn)))
                if row[side] is None:
                    color = QColor(self._p.border)
                color.setAlpha(70)
                block = editor.document().findBlockByNumber(i)
                cursor.setPosition(block.position())
                fmt = QTextBlockFormat()
                fmt.setBackground(color)
                cursor.setBlockFormat(fmt)
        syncing = [False]

        def sync(src, dst):
            def _f(value):
                if syncing[0]:
                    return
                syncing[0] = True
                dst.setValue(value)
                syncing[0] = False
            src.valueChanged.connect(_f)
        sync(left.verticalScrollBar(), right.verticalScrollBar())
        sync(right.verticalScrollBar(), left.verticalScrollBar())
        sync(left.horizontalScrollBar(), right.horizontalScrollBar())
        sync(right.horizontalScrollBar(), left.horizontalScrollBar())
        row = QHBoxLayout()
        row.addWidget(left)
        row.addWidget(right)
        self.body.addLayout(row, stretch=1)

    def _images(self, lf: str, rf: str) -> None:
        same = _sha256(lf) == _sha256(rf)
        self._summary.setText(tr("fb.compare.identical") if same else tr("fb.compare.image_differs"))
        row = QHBoxLayout()
        for path in (lf, rf):
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pm = QPixmap(path)
            if pm.isNull():
                lbl.setText(tr("fb.compare.no_preview"))
            else:
                lbl.setPixmap(pm.scaled(500, 460, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
                lbl.setToolTip(f"{pm.width()} × {pm.height()} px")
            scroll = QScrollArea()
            scroll.setWidget(lbl)
            scroll.setWidgetResizable(True)
            row.addWidget(scroll)
        self.body.addLayout(row, stretch=1)

    def _binary(self, lf: str, rf: str) -> None:
        same = _sha256(lf) == _sha256(rf)
        self._summary.setText(tr("fb.compare.binary") + "  " +
                              (tr("fb.compare.identical") if same else tr("fb.compare.content_differs")))
        self.body.addStretch()


# ── Open with ────────────────────────────────────────────────────────────────

class OpenWithDialog(_Dialog):
    def __init__(self, parent, extension: str, theme: str, current: Optional[str] = None) -> None:
        super().__init__(parent, tr("fb.openwith.title"), theme, 520)
        ext = f".{extension}" if extension else tr("fb.openwith.no_ext")
        self.add_title(tr("fb.openwith.text", ext=ext))
        self._system = QRadioButton(tr("fb.openwith.system"))
        self._custom = QRadioButton(tr("fb.openwith.custom"))
        group = QButtonGroup(self)
        group.addButton(self._system)
        group.addButton(self._custom)
        self.body.addWidget(self._system)
        self.body.addWidget(self._custom)
        row = QHBoxLayout()
        self._path = QLineEdit()
        self._path.setObjectName("formInput")
        self._path.setPlaceholderText(r"C:\Program Files\…\program.exe")
        browse = _btn(tr("fb.common.browse"))
        browse.clicked.connect(self._browse)
        row.addWidget(self._path, 1)
        row.addWidget(browse)
        self.body.addLayout(row)
        hint = QLabel(tr("fb.openwith.note"))
        hint.setObjectName("fbHint")
        hint.setWordWrap(True)
        self.body.addWidget(hint)
        if current and current != OPEN_WITH_SYSTEM:
            self._custom.setChecked(True)
            self._path.setText(current)
        else:
            self._system.setChecked(True)
        self._path.textEdited.connect(lambda _t: self._custom.setChecked(True))
        cancel = _btn(tr("dialog.cancel"))
        cancel.clicked.connect(self.reject)
        ok = _btn(tr("fb.openwith.open"), "primaryBtn")
        ok.clicked.connect(self._accept)
        self.button_row([cancel, ok])
        self.result_program: Optional[str] = None

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("fb.openwith.custom"), "",
                                              tr("fb.openwith.filter"))
        if path:
            self._path.setText(os.path.normpath(path))
            self._custom.setChecked(True)

    def _accept(self) -> None:
        if self._system.isChecked():
            self.result_program = OPEN_WITH_SYSTEM
        else:
            path = self._path.text().strip().strip('"')
            if not path or not os.path.isfile(path):
                self._path.setFocus()
                self._path.setStyleSheet("border: 1px solid #ef4444;")
                return
            self.result_program = path
        self.accept()

    @classmethod
    def choose(cls, parent, extension: str, theme: str, current: Optional[str] = None) -> Optional[str]:
        dlg = cls(parent, extension, theme, current)
        return dlg.result_program if dlg.exec() == QDialog.DialogCode.Accepted else None


# ── Settings ─────────────────────────────────────────────────────────────────

class SettingsDialog(_Dialog):
    def __init__(self, parent, manager, theme: str) -> None:
        super().__init__(parent, tr("fb.settings.title"), theme, 840)
        self._manager = manager
        self._theme = theme
        self.s: BrowserSettings = copy.deepcopy(manager.settings)
        tabs = QTabWidget()
        tabs.addTab(self._transfers_tab(), tr("fb.settings.tab.transfers"))
        tabs.addTab(self._view_tab(), tr("fb.settings.tab.view"))
        tabs.addTab(self._programs_tab(), tr("fb.settings.tab.programs"))
        self.body.addWidget(tabs, 1)
        cancel = _btn(tr("dialog.cancel"))
        cancel.clicked.connect(self.reject)
        save = _btn(tr("fb.settings.save"), "primaryBtn")
        save.clicked.connect(self._save)
        self.button_row([cancel, save])

    @staticmethod
    def _spin(lo: int, hi: int, value: int, suffix: str = "", special: str = "") -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(value)
        if suffix:
            sp.setSuffix(suffix)
        if special:
            sp.setSpecialValueText(special)
        sp.setMinimumWidth(140)
        # The app stylesheet clips the native arrow buttons; typing, arrow keys
        # and the mouse wheel still change the value.
        sp.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        return sp

    def _transfers_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setVerticalSpacing(10)
        f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        s = self.s
        self._max_down = self._spin(1, 8, s.max_downloads)
        self._max_up = self._spin(1, 8, s.max_uploads)
        unlimited = tr("fb.settings.unlimited")
        self._lim_down = self._spin(0, 1_000_000, s.limit_down_kib, " KiB/s", unlimited)
        self._lim_up = self._spin(0, 1_000_000, s.limit_up_kib, " KiB/s", unlimited)
        self._policy = QComboBox()
        for p in POLICIES:
            self._policy.addItem(tr(f"fb.policy.{p}"), p)
        self._policy.setCurrentIndex(POLICIES.index(s.conflict_policy))
        self._mtime = QCheckBox(tr("fb.settings.preserve_mtime"))
        self._mtime.setChecked(s.preserve_mtime)
        self._checksum = QCheckBox(tr("fb.settings.verify_checksum"))
        self._checksum.setChecked(s.verify_checksum)
        self._checksum.setToolTip(tr("fb.settings.verify_checksum_hint"))
        self._reconnect = QCheckBox(tr("fb.settings.auto_reconnect"))
        self._reconnect.setChecked(s.auto_reconnect)
        self._retries = self._spin(0, 10, s.retry_attempts)
        f.addRow(tr("fb.settings.max_downloads"), self._max_down)
        f.addRow(tr("fb.settings.max_uploads"), self._max_up)
        f.addRow(tr("fb.settings.limit_down"), self._lim_down)
        f.addRow(tr("fb.settings.limit_up"), self._lim_up)
        f.addRow(tr("fb.settings.conflict"), self._policy)
        f.addRow("", self._mtime)
        f.addRow("", self._checksum)
        f.addRow("", self._reconnect)
        f.addRow(tr("fb.settings.retries"), self._retries)
        hint = QLabel(tr("fb.settings.parallel_hint"))
        hint.setObjectName("fbHint")
        hint.setWordWrap(True)
        f.addRow(hint)
        return w

    def _view_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setVerticalSpacing(10)
        f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        s = self.s
        self._hidden = QCheckBox(tr("fb.settings.show_hidden"))
        self._hidden.setChecked(s.show_hidden)
        self._tree = QCheckBox(tr("fb.settings.show_tree"))
        self._tree.setChecked(s.show_tree)
        self._tree_root = QCheckBox(tr("fb.settings.tree_from_root"))
        self._tree_root.setChecked(s.tree_from_root)
        self._tree_root.setToolTip(tr("fb.settings.tree_from_root_hint"))
        self._confirm = QCheckBox(tr("fb.settings.confirm_delete"))
        self._confirm.setChecked(s.confirm_delete)
        # "&&": a single "&" ("Drag & Drop") would turn into a keyboard mnemonic.
        self._confirm_move = QCheckBox(tr("fb.settings.confirm_move").replace("&", "&&"))
        self._confirm_move.setChecked(s.confirm_move)
        self._confirm_move.setToolTip(tr("fb.settings.confirm_move_hint"))
        self._dbl = QComboBox()
        self._dbl.addItem(tr("fb.settings.dbl_open"), "open")
        self._dbl.addItem(tr("fb.settings.dbl_download"), "download")
        self._dbl.setCurrentIndex(0 if s.double_click == "open" else 1)
        self._archive = QComboBox()
        self._archive.addItem("tar.gz", "tar.gz")
        self._archive.addItem("zip", "zip")
        self._archive.setCurrentIndex(0 if s.archive_format == "tar.gz" else 1)
        row = QHBoxLayout()
        self._local_start = QLineEdit(s.local_start)
        self._local_start.setObjectName("formInput")
        self._local_start.setMinimumWidth(320)
        browse = _btn(tr("fb.common.browse"))
        browse.clicked.connect(self._browse_start)
        row.addWidget(self._local_start, 1)
        row.addWidget(browse)
        f.addRow("", self._hidden)
        f.addRow("", self._tree)
        f.addRow("", self._tree_root)
        f.addRow("", self._confirm)
        f.addRow("", self._confirm_move)
        f.addRow(tr("fb.settings.double_click"), self._dbl)
        f.addRow(tr("fb.settings.archive_format"), self._archive)
        f.addRow(tr("fb.settings.local_start"), row)
        return w

    def _browse_start(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("fb.settings.local_start"),
                                                self._local_start.text())
        if path:
            self._local_start.setText(os.path.normpath(path))

    def _programs_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel(tr("fb.settings.programs_hint"))
        hint.setObjectName("fbHint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self._programs = QTableWidget(0, 2)
        self._programs.setHorizontalHeaderLabels([tr("fb.settings.extension"), tr("fb.settings.program")])
        self._programs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._programs.verticalHeader().setVisible(False)
        self._programs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._programs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._programs.doubleClicked.connect(lambda _i: self._edit_program())
        v.addWidget(self._programs, 1)
        row = QHBoxLayout()
        add = _btn(tr("fb.settings.add"))
        add.clicked.connect(self._add_program)
        edit = _btn(tr("fb.settings.change"))
        edit.clicked.connect(self._edit_program)
        remove = _btn(tr("fb.settings.remove"), "dangerBtn")
        remove.clicked.connect(self._remove_program)
        row.addWidget(add)
        row.addWidget(edit)
        row.addStretch()
        row.addWidget(remove)
        v.addLayout(row)
        self._fill_programs()
        return w

    def _fill_programs(self) -> None:
        self._programs.setRowCount(0)
        for ext in sorted(self.s.open_with):
            prog = self.s.open_with[ext]
            r = self._programs.rowCount()
            self._programs.insertRow(r)
            self._programs.setItem(r, 0, QTableWidgetItem("." + ext))
            label = tr("fb.openwith.system") if prog == OPEN_WITH_SYSTEM else prog
            self._programs.setItem(r, 1, QTableWidgetItem(label))

    def _selected_ext(self) -> Optional[str]:
        row = self._programs.currentRow()
        item = self._programs.item(row, 0) if row >= 0 else None
        return item.text().lstrip(".") if item else None

    def _add_program(self) -> None:
        from src.ui.dialogs.styled_message_box import StyledInputDialog
        ext, ok = StyledInputDialog.get_text(self, tr("fb.settings.add"), tr("fb.settings.ext_prompt"))
        ext = ext.strip().lower().lstrip(".")
        if not ok or not ext:
            return
        prog = OpenWithDialog.choose(self, ext, self._theme, self.s.open_with.get(ext))
        if prog:
            self.s.open_with[ext] = prog
            self._fill_programs()

    def _edit_program(self) -> None:
        ext = self._selected_ext()
        if ext is None:
            return
        prog = OpenWithDialog.choose(self, ext, self._theme, self.s.open_with.get(ext))
        if prog:
            self.s.open_with[ext] = prog
            self._fill_programs()

    def _remove_program(self) -> None:
        ext = self._selected_ext()
        if ext is not None:
            self.s.open_with.pop(ext, None)
            self._fill_programs()

    def _save(self) -> None:
        s = self.s
        s.max_downloads = self._max_down.value()
        s.max_uploads = self._max_up.value()
        s.limit_down_kib = self._lim_down.value()
        s.limit_up_kib = self._lim_up.value()
        s.conflict_policy = self._policy.currentData()
        s.preserve_mtime = self._mtime.isChecked()
        s.verify_checksum = self._checksum.isChecked()
        s.auto_reconnect = self._reconnect.isChecked()
        s.retry_attempts = self._retries.value()
        s.show_hidden = self._hidden.isChecked()
        s.show_tree = self._tree.isChecked()
        s.tree_from_root = self._tree_root.isChecked()
        s.confirm_delete = self._confirm.isChecked()
        s.confirm_move = self._confirm_move.isChecked()
        s.double_click = self._dbl.currentData()
        s.archive_format = self._archive.currentData()
        s.local_start = self._local_start.text().strip()
        # Copy onto the shared object, but keep state other windows may have
        # changed meanwhile (bookmarks, last paths, window layout).
        live = self._manager.settings
        for name in ("max_downloads", "max_uploads", "limit_down_kib", "limit_up_kib",
                     "conflict_policy", "preserve_mtime", "verify_checksum", "auto_reconnect",
                     "retry_attempts", "show_hidden", "show_tree", "tree_from_root", "confirm_delete",
                     "confirm_move", "double_click", "archive_format", "local_start",
                     "open_with"):
            setattr(live, name, getattr(s, name))
        self._manager.save()
        self.accept()


# ── Confirm a move (drag & drop) ─────────────────────────────────────────────

class MoveConfirmDialog(_Dialog):
    def __init__(self, parent, theme: str, names: list[str], target_display: str) -> None:
        super().__init__(parent, tr("fb.move.title"), theme, 520)
        target = _elide_middle(target_display, 70)
        if len(names) == 1:
            self.add_title(tr("fb.move.text_one", name=_elide_middle(names[0], 60), target=target))
        else:
            self.add_title(tr("fb.move.text_many", count=len(names), target=target))
            listing = "\n".join("• " + _elide_middle(n, 60) for n in names[:8])
            if len(names) > 8:
                listing += "\n" + tr("fb.delete.more", count=len(names) - 8)
            self.add_text(listing)
        self._dont_ask = QCheckBox(tr("fb.move.dont_ask"))
        self.body.addWidget(self._dont_ask)
        hint = QLabel(tr("fb.move.dont_ask_hint"))
        hint.setObjectName("fbHint")
        hint.setWordWrap(True)
        self.body.addWidget(hint)
        cancel = _btn(tr("dialog.cancel"))
        cancel.clicked.connect(self.reject)
        ok = _btn(tr("fb.move.yes"), "primaryBtn")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        self.button_row([cancel, ok])

    @property
    def dont_ask(self) -> bool:
        return self._dont_ask.isChecked()


# ── Fetch from URL ───────────────────────────────────────────────────────────

class UrlDialog(_Dialog):
    def __init__(self, parent, theme: str, target_display: str, can_server: bool) -> None:
        super().__init__(parent, tr("fb.url.title"), theme, 560)
        self.add_text(tr("fb.url.text", folder=target_display))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self._url = QLineEdit()
        self._url.setObjectName("formInput")
        self._url.setPlaceholderText("https://example.com/file.zip")
        self._name = QLineEdit()
        self._name.setObjectName("formInput")
        self._name_edited = False
        self._name.textEdited.connect(lambda _t: setattr(self, "_name_edited", True))
        self._url.textChanged.connect(self._suggest_name)
        self._method = QComboBox()
        if can_server:
            self._method.addItem(tr("fb.url.via_server"), True)
        self._method.addItem(tr("fb.url.via_pc"), False)
        form.addRow(tr("fb.url.address"), self._url)
        form.addRow(tr("fb.url.filename"), self._name)
        form.addRow(tr("fb.url.method"), self._method)
        self.body.addLayout(form)
        hint = QLabel(tr("fb.url.hint"))
        hint.setObjectName("fbHint")
        hint.setWordWrap(True)
        self.body.addWidget(hint)
        self._error = QLabel()
        self._error.setObjectName("fbHint")
        self._error.setStyleSheet("color: #ef4444;")
        self.body.addWidget(self._error)
        cancel = _btn(tr("dialog.cancel"))
        cancel.clicked.connect(self.reject)
        ok = _btn(tr("fb.url.start"), "primaryBtn")
        ok.clicked.connect(self._accept)
        self.button_row([cancel, ok])
        self.result: Optional[tuple[str, str, bool]] = None

    def _suggest_name(self, text: str) -> None:
        if not self._name_edited:
            try:
                self._name.setText(commands.filename_from_url(commands.validate_url(text)))
            except commands.UrlError:
                pass

    def _accept(self) -> None:
        try:
            url = commands.validate_url(self._url.text())
        except commands.UrlError as e:
            self._error.setText(tr("fb.url.invalid", reason=str(e)))
            return
        name = commands.sanitize_filename(self._name.text())
        self.result = (url, name, bool(self._method.currentData()))
        self.accept()


# ── Pack ─────────────────────────────────────────────────────────────────────

class PackDialog(_Dialog):
    def __init__(self, parent, theme: str, names: list[str], default_fmt: str) -> None:
        super().__init__(parent, tr("fb.pack.title"), theme, 460)
        self.add_text(tr("fb.pack.text", count=len(names)))
        form = QFormLayout()
        self._fmt = QComboBox()
        self._fmt.addItem("tar.gz", "tar.gz")
        self._fmt.addItem("zip", "zip")
        self._fmt.setCurrentIndex(0 if default_fmt == "tar.gz" else 1)
        self._name = QLineEdit(commands.default_archive_name(names, default_fmt))
        self._name.setObjectName("formInput")
        self._fmt.currentIndexChanged.connect(self._fix_ext)
        form.addRow(tr("fb.pack.name"), self._name)
        form.addRow(tr("fb.pack.format"), self._fmt)
        self.body.addLayout(form)
        cancel = _btn(tr("dialog.cancel"))
        cancel.clicked.connect(self.reject)
        ok = _btn(tr("fb.pack.start"), "primaryBtn")
        ok.clicked.connect(self.accept)
        self.button_row([cancel, ok])

    def _fix_ext(self) -> None:
        name = self._name.text()
        for ext in (".tar.gz", ".zip"):
            if name.endswith(ext):
                name = name[: -len(ext)]
        self._name.setText(f"{name}.{self._fmt.currentData()}")

    def values(self) -> tuple[str, str]:
        return commands.sanitize_filename(self._name.text()), self._fmt.currentData()


# ── Properties ───────────────────────────────────────────────────────────────

class PropertiesDialog(_Dialog):
    def __init__(self, parent, theme: str, fs, entries: list[FileEntry]) -> None:
        title = entries[0].name if len(entries) == 1 else tr("fb.props.multi", count=len(entries))
        super().__init__(parent, tr("fb.props.title", name=title), theme, 480)
        self._fs = fs
        self._entries = entries
        self._tasks = TaskRunner(self)
        single = entries[0] if len(entries) == 1 else None
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        row = 0

        def add(label: str, value: str) -> QLabel:
            nonlocal row
            k = QLabel(label)
            k.setObjectName("fbMeta")
            v = QLabel(value)
            v.setObjectName("msgText")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(k, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(v, row, 1)
            row += 1
            return v

        if single:
            add(tr("fb.col.name"), single.name)
            add(tr("fb.props.path"), single.path)
            from src.filebrowser.ui.models import type_label
            add(tr("fb.col.type"), type_label(single))
            add(tr("fb.col.modified"), _date(single.mtime))
            if single.owner or single.group:
                add(tr("fb.col.owner"), f"{single.owner} : {single.group}")
        files_size = sum(e.size for e in entries if not e.is_dir)
        has_dirs = any(e.is_dir for e in entries)
        self._size_lbl = add(tr("fb.col.size"), "—" if has_dirs else
                             f"{fmt_size(files_size)} ({files_size:,} B)".replace(",", "."))
        self.body.addLayout(grid)
        if has_dirs:
            calc = _btn(tr("fb.props.calc_size"))
            calc.clicked.connect(lambda: self._calc_size(calc))
            self.body.addWidget(calc, 0, Qt.AlignmentFlag.AlignLeft)

        self._perm_boxes: list[QCheckBox] = []
        self._octal: Optional[QLineEdit] = None
        self._recursive: Optional[QCheckBox] = None
        show_perms = getattr(fs, "can_chmod", False) and not getattr(fs, "is_windows", False)
        if show_perms:
            self._perm_section(entries[0].perm_bits, has_dirs)

        if single and not single.is_dir:
            sha_row = QHBoxLayout()
            sha_btn = _btn(tr("fb.props.checksum"))
            self._sha = QLabel("")
            self._sha.setObjectName("fbMeta")
            self._sha.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._sha.setWordWrap(True)
            sha_btn.clicked.connect(lambda: self._checksum(sha_btn, single))
            sha_btn.setEnabled(getattr(fs, "is_local", False) or getattr(fs, "can_exec", False))
            sha_row.addWidget(sha_btn)
            sha_row.addWidget(self._sha, 1)
            self.body.addLayout(sha_row)

        close = _btn(tr("fb.common.close"))
        close.clicked.connect(self.reject)
        buttons = [close]
        if show_perms:
            apply = _btn(tr("fb.props.apply"), "primaryBtn")
            apply.clicked.connect(self._apply)
            buttons.append(apply)
        self._status = QLabel()
        self._status.setObjectName("fbHint")
        self.body.addWidget(self._status)
        self.button_row(buttons)

    def _perm_section(self, bits: int, has_dirs: bool) -> None:
        title = QLabel(tr("fb.col.permissions"))
        title.setObjectName("fbMetaTitle")
        self.body.addWidget(title)
        grid = QGridLayout()
        heads = [tr("fb.perm.read"), tr("fb.perm.write"), tr("fb.perm.exec")]
        whos = [tr("fb.perm.owner"), tr("fb.perm.group"), tr("fb.perm.other")]
        for c, h in enumerate(heads):
            lbl = QLabel(h)
            lbl.setObjectName("fbMeta")
            grid.addWidget(lbl, 0, c + 1)
        for r, who in enumerate(whos):
            lbl = QLabel(who)
            lbl.setObjectName("fbMeta")
            grid.addWidget(lbl, r + 1, 0)
            for c in range(3):
                box = QCheckBox()
                shift = 8 - (r * 3 + c)
                box.setChecked(bool(bits & (1 << shift)))
                box.toggled.connect(self._boxes_changed)
                self._perm_boxes.append(box)
                grid.addWidget(box, r + 1, c + 1)
        self.body.addLayout(grid)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("fb.perm.octal")))
        self._octal = QLineEdit(f"{bits & 0o777:03o}")
        self._octal.setObjectName("formInput")
        self._octal.setFixedWidth(80)
        self._octal.textEdited.connect(self._octal_changed)
        row.addWidget(self._octal)
        row.addStretch()
        self.body.addLayout(row)
        if has_dirs:
            self._recursive = QCheckBox(tr("fb.perm.recursive"))
            self.body.addWidget(self._recursive)

    def _mode_from_boxes(self) -> int:
        mode = 0
        for i, box in enumerate(self._perm_boxes):
            if box.isChecked():
                mode |= 1 << (8 - i)
        return mode

    def _boxes_changed(self) -> None:
        if self._octal is not None:
            self._octal.setText(f"{self._mode_from_boxes():03o}")

    def _octal_changed(self, text: str) -> None:
        mode = parse_octal_mode(text)
        if mode is None:
            return
        for i, box in enumerate(self._perm_boxes):
            box.blockSignals(True)
            box.setChecked(bool(mode & (1 << (8 - i))))
            box.blockSignals(False)

    def _calc_size(self, button: QPushButton) -> None:
        button.setEnabled(False)
        self._size_lbl.setText(tr("fb.status.loading"))
        fs, entries = self._fs, self._entries

        def work():
            size = files = dirs = 0
            for e in entries:
                if not e.is_dir:
                    size += e.size
                    files += 1
                    continue
                for _d, sub_dirs, sub_files in fs.walk(e.path):
                    dirs += len(sub_dirs)
                    files += len(sub_files)
                    size += sum(f.size for f in sub_files)
            return size, files, dirs

        def done(result):
            size, files, dirs = result
            self._size_lbl.setText(tr("fb.props.size_detail", size=fmt_size(size),
                                      files=files, dirs=dirs))

        self._tasks.run(work, done, lambda e: self._size_lbl.setText(str(e)))

    def _checksum(self, button: QPushButton, entry: FileEntry) -> None:
        button.setEnabled(False)
        self._sha.setText(tr("fb.props.checksum_running"))
        fs = self._fs

        def work():
            if getattr(fs, "is_local", False):
                return _sha256(entry.path)
            code, out, err = fs.run(commands.checksum_command(fs.is_windows, entry.path), timeout=1800)
            digest = commands.parse_checksum(out) if code == 0 else None
            if digest is None:
                raise RuntimeError((err or out).strip() or tr("fb.props.checksum_na"))
            return digest

        self._tasks.run(work, lambda d: self._sha.setText(f"SHA-256: {d}"),
                        lambda e: self._sha.setText(str(e)))

    def _apply(self) -> None:
        if self._octal is None:
            self.accept()
            return
        mode = parse_octal_mode(self._octal.text())
        if mode is None:
            self._status.setText(tr("fb.perm.invalid"))
            return
        recursive = bool(self._recursive and self._recursive.isChecked())
        fs, entries = self._fs, self._entries
        self._status.setText(tr("fb.status.working"))

        def work():
            count = 0
            for e in entries:
                fs.chmod(e.path, mode)
                count += 1
                if recursive and e.is_dir:
                    for _d, sub_dirs, sub_files in fs.walk(e.path):
                        for x in sub_dirs + sub_files:
                            fs.chmod(x.path, mode)
                            count += 1
            return count

        self._tasks.run(work, lambda n: (self._status.setText(tr("fb.perm.applied", count=n)),
                                         self.accept()),
                        lambda e: self._status.setText(str(e)))

    def done(self, r: int) -> None:  # noqa: A003
        self._tasks.shutdown()
        super().done(r)


# ── Sync ─────────────────────────────────────────────────────────────────────

class SyncDialog(_Dialog):
    def __init__(self, parent, theme: str, local_fs, remote_fs, local_dir: str,
                 remote_dir: str, remote_display) -> None:
        super().__init__(parent, tr("fb.sync.title"), theme, 860)
        self.resize(980, 640)
        self._local_fs = local_fs
        self._remote_fs = remote_fs
        self._remote_display = remote_display
        self._tasks = TaskRunner(self)
        self.items: list = []
        self.roots: tuple[str, str] = ("", "")
        form = QFormLayout()
        lrow = QHBoxLayout()
        self._local = QLineEdit(local_dir)
        self._local.setObjectName("formInput")
        browse = _btn(tr("fb.common.browse"))
        browse.clicked.connect(self._browse)
        lrow.addWidget(self._local, 1)
        lrow.addWidget(browse)
        self._remote = QLineEdit(remote_dir)
        self._remote.setObjectName("formInput")
        self._direction = QComboBox()
        self._direction.addItem(tr("fb.sync.upload"), SYNC_UPLOAD)
        self._direction.addItem(tr("fb.sync.download"), SYNC_DOWNLOAD)
        self._direction.addItem(tr("fb.sync.both"), SYNC_BOTH)
        self._mirror = QCheckBox(tr("fb.sync.mirror"))
        self._mirror.setToolTip(tr("fb.sync.mirror_hint"))
        self._direction.currentIndexChanged.connect(
            lambda _i: self._mirror.setEnabled(self._direction.currentData() != SYNC_BOTH))
        form.addRow(tr("fb.sync.local"), lrow)
        form.addRow(tr("fb.sync.remote"), self._remote)
        form.addRow(tr("fb.sync.direction"), self._direction)
        form.addRow("", self._mirror)
        self.body.addLayout(form)
        compare = _btn(tr("fb.sync.compare"), "primaryBtn")
        compare.clicked.connect(self._compare)
        self._compare_btn = compare
        self.body.addWidget(compare, 0, Qt.AlignmentFlag.AlignLeft)

        self._list = QTreeWidget()
        self._list.setRootIsDecorated(False)
        self._list.setAlternatingRowColors(True)
        self._list.setHeaderLabels([tr("fb.sync.col.action"), tr("fb.sync.col.path"),
                                    tr("fb.sync.col.reason"), tr("fb.sync.col.local"),
                                    tr("fb.sync.col.remote")])
        for col, width in ((0, 130), (1, 300), (2, 170), (3, 190)):
            self._list.header().resizeSection(col, width)
        self._list.itemChanged.connect(self._update_summary)
        self.body.addWidget(self._list, 1)
        self._summary = QLabel()
        self._summary.setObjectName("fbHint")
        self.body.addWidget(self._summary)
        close = _btn(tr("fb.common.close"))
        close.clicked.connect(self.reject)
        self._run = _btn(tr("fb.sync.run"), "primaryBtn")
        self._run.setEnabled(False)
        self._run.clicked.connect(self._execute)
        self.button_row([close, self._run])

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("fb.sync.local"), self._local.text())
        if path:
            self._local.setText(os.path.normpath(path))

    def _compare(self) -> None:
        local_root = self._local.text().strip()
        remote_root = self._remote.text().strip() or "/"
        if not os.path.isdir(local_root):
            self._summary.setText(tr("fb.sync.bad_local"))
            return
        direction = self._direction.currentData()
        mirror = self._mirror.isChecked() and direction != SYNC_BOTH
        self._compare_btn.setEnabled(False)
        self._run.setEnabled(False)
        self._list.clear()
        self._summary.setText(tr("fb.sync.scanning"))
        lfs, rfs = self._local_fs, self._remote_fs

        def snapshot(fs, root, local):
            side = SyncSide()
            for dirpath, dirs, files in fs.walk(root):
                base = os.path.relpath(dirpath, root).replace("\\", "/") if local \
                    else dirpath[len(root.rstrip("/")):].strip("/")
                base = "" if base == "." else base
                for d in dirs:
                    side.dirs.add(f"{base}/{d.name}".strip("/"))
                for f in files:
                    side.files[f"{base}/{f.name}".strip("/")] = f
            return side

        def work():
            return compare_trees(snapshot(lfs, local_root, True),
                                 snapshot(rfs, remote_root, False), direction, mirror)

        def done(items):
            self._compare_btn.setEnabled(True)
            self.items = items
            self.roots = (local_root, remote_root)
            self._fill(items)

        def failed(e):
            self._compare_btn.setEnabled(True)
            self._summary.setText(str(e))

        self._tasks.run(work, done, failed)

    def _fill(self, items) -> None:
        labels = {ACT_UPLOAD: "↑ " + tr("fb.kind.upload"), ACT_DOWNLOAD: "↓ " + tr("fb.kind.download"),
                  ACT_DELETE_REMOTE: "✕ " + tr("fb.kind.delete_remote"),
                  ACT_DELETE_LOCAL: "✕ " + tr("fb.kind.delete_local")}
        self._list.blockSignals(True)
        for item in items:
            row = QTreeWidgetItem([
                labels.get(item.action, item.action), item.rel, tr(f"fb.sync.reason.{item.reason}"),
                f"{fmt_size(item.local.size)} · {_date(item.local.mtime)}" if item.local else "—",
                f"{fmt_size(item.remote.size)} · {_date(item.remote.mtime)}" if item.remote else "—",
            ])
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Checked)
            row.setData(0, Qt.ItemDataRole.UserRole, item)
            if item.action in (ACT_DELETE_LOCAL, ACT_DELETE_REMOTE):
                row.setForeground(0, QColor("#ef4444"))
            self._list.addTopLevelItem(row)
        self._list.blockSignals(False)
        self._update_summary()

    def _update_summary(self, *_args) -> None:
        selected = 0
        size = 0
        for i in range(self._list.topLevelItemCount()):
            row = self._list.topLevelItem(i)
            item = row.data(0, Qt.ItemDataRole.UserRole)
            item.selected = row.checkState(0) == Qt.CheckState.Checked
            if item.selected:
                selected += 1
                size += item.size
        if not self.items:
            self._summary.setText(tr("fb.sync.in_sync"))
        else:
            self._summary.setText(tr("fb.sync.summary", count=selected, total=len(self.items),
                                     size=fmt_size(size)))
        self._run.setEnabled(selected > 0)

    def _execute(self) -> None:
        self.accept()

    def done(self, r: int) -> None:  # noqa: A003
        self._tasks.shutdown()
        super().done(r)


# ── Shortcuts ────────────────────────────────────────────────────────────────

SHORTCUTS = [
    ("Enter", "fb.keys.open"), ("Backspace / Alt+↑", "fb.keys.up"),
    ("Alt+← / Alt+→", "fb.keys.history"), ("F5 / Ctrl+R", "fb.keys.refresh"),
    ("F2", "fb.keys.rename"), ("Del", "fb.keys.delete"),
    ("Ctrl+Z", "fb.keys.undo"), ("Ctrl+Y / Ctrl+Shift+Z", "fb.keys.redo"),
    ("F7 / Ctrl+Shift+N", "fb.keys.new_folder"), ("Shift+F4", "fb.keys.new_file"),
    ("Alt+Enter", "fb.keys.properties"), ("Ctrl+A", "fb.keys.select_all"),
    ("Ctrl+L / F4", "fb.keys.path"), ("Ctrl+F", "fb.keys.filter"),
    ("Ctrl+O", "fb.keys.open_with"), ("Ctrl+Shift+C", "fb.keys.copy_path"),
    ("Ctrl+D", "fb.keys.bookmark"), ("F6", "fb.keys.transfer"), ("Tab", "fb.keys.other_pane"),
    ("F9", "fb.keys.split"), ("Ctrl+Shift+O", "fb.keys.connect"),
    ("Ctrl+T / Ctrl+W", "fb.keys.tabs"),
    ("Ctrl+Tab", "fb.keys.next_tab"), ("Ctrl+U / Ctrl+Shift+U", "fb.keys.upload"),
    ("Ctrl+Shift+D", "fb.keys.download"), ("Ctrl+Shift+L", "fb.keys.url"),
    ("Ctrl+Shift+S", "fb.keys.sync"), ("Ctrl+Shift+T", "fb.keys.terminal"),
    ("Ctrl+,", "fb.keys.settings"), ("F1", "fb.keys.help"),
]


class ShortcutsDialog(_Dialog):
    def __init__(self, parent, theme: str) -> None:
        super().__init__(parent, tr("fb.keys.title"), theme, 520)
        table = QTableWidget(len(SHORTCUTS), 2)
        table.setHorizontalHeaderLabels([tr("fb.keys.key"), tr("fb.keys.action")])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().resizeSection(0, 190)
        for r, (key, label) in enumerate(SHORTCUTS):
            table.setItem(r, 0, QTableWidgetItem(key))
            table.setItem(r, 1, QTableWidgetItem(tr(label)))
        table.setMinimumHeight(520)
        self.body.addWidget(table, 1)
        close = _btn(tr("fb.common.close"), "primaryBtn")
        close.clicked.connect(self.accept)
        self.button_row([close])
