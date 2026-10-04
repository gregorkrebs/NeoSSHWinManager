"""
transfer_panel.py – Transfer lists (with progress bars) and transfer log.

Like FileZilla, the transfers are split into three lists: the ones still to
do (queued, running, paused), the failed ones (failed, cancelled) and the
successful ones (done, skipped). A job moves between the lists as its state
changes. A fourth tab holds the log.

The browser's one panel shows the jobs of every connected host; each
host has its own TransferQueue (job ids are unique across queues).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QMenu, QStyledItemDelegate,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from src.filebrowser.model import fmt_eta, fmt_size, fmt_speed
from src.filebrowser.transfers import (
    CANCELLED, DELETE_LOCAL, DELETE_REMOTE, DONE, DOWNLOAD, FAILED, PAUSED, QUEUED, RUNNING,
    SKIPPED, UPLOAD, URL_CLIENT, URL_SERVER, TransferJob, TransferQueue, export_log_csv,
)
from src.filebrowser.ui.pane import tool_button
from src.i18n import tr
from src.ui.icons import icon as svg_icon

_JOB_ID = Qt.ItemDataRole.UserRole + 1
_PROGRESS = Qt.ItemDataRole.UserRole + 2
_STATE = Qt.ItemDataRole.UserRole + 3

C_NAME, C_KIND, C_PROGRESS, C_SIZE, C_SPEED, C_ETA, C_TIME, C_STATE, C_TARGET, C_HOST = range(10)

# The three lists and the job states each one holds.
PENDING, FAILED_LIST, DONE_LIST = "pending", "failed", "done"
_LIST_STATES = {
    PENDING: (QUEUED, RUNNING, PAUSED),
    FAILED_LIST: (FAILED, CANCELLED),
    DONE_LIST: (DONE, SKIPPED),
}


def list_for(state: str) -> str:
    for name, states in _LIST_STATES.items():
        if state in states:
            return name
    return PENDING


def kind_label(kind: str) -> str:
    return {
        UPLOAD: "↑ " + tr("fb.kind.upload"),
        DOWNLOAD: "↓ " + tr("fb.kind.download"),
        URL_CLIENT: "↑ " + tr("fb.kind.url"),
        URL_SERVER: "↑ " + tr("fb.kind.url_server"),
        DELETE_REMOTE: "✕ " + tr("fb.kind.delete_remote"),
        DELETE_LOCAL: "✕ " + tr("fb.kind.delete_local"),
    }.get(kind, kind)


def state_label(state: str) -> str:
    return tr(f"fb.state.{state}")


class _ProgressDelegate(QStyledItemDelegate):
    def __init__(self, palette, parent=None) -> None:
        super().__init__(parent)
        self._p = palette

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)
        value = index.data(_PROGRESS)
        if value is None:
            return
        state = index.data(_STATE)
        rect = QRectF(option.rect).adjusted(4, 6, -4, -6)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._p.border))
        painter.drawRoundedRect(rect, 3, 3)
        color = {FAILED: self._p.error, PAUSED: self._p.warn, DONE: self._p.ok}.get(state, self._p.accent)
        if value > 0:
            fill = QRectF(rect)
            fill.setWidth(max(4.0, rect.width() * min(1.0, value)))
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(fill, 3, 3)
        painter.setPen(QColor(self._p.text))
        f = painter.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        painter.setFont(f)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{int(value * 100)} %")
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(110, 22)


class _JobList(QWidget):
    """One of the three transfer lists: a toolbar and the job rows."""

    # Columns that only mean something while a job is still to do, and the
    # finish time that only means something afterwards.
    _LIVE_COLUMNS = (C_PROGRESS, C_SPEED, C_ETA)

    def __init__(self, panel: "TransferPanel", name: str) -> None:
        super().__init__()
        self._panel = panel
        self.name = name
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("fbToolbar")
        self._bar = QHBoxLayout(bar)
        self._bar.setContentsMargins(6, 3, 6, 3)
        self._bar.setSpacing(3)
        v.addWidget(bar)

        self.tree = QTreeWidget()
        self.tree.setObjectName("fbJobs")
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setHeaderLabels([
            tr("fb.col.name"), tr("fb.jobs.col.kind"), tr("fb.jobs.col.progress"),
            tr("fb.col.size"), tr("fb.jobs.col.speed"), tr("fb.jobs.col.eta"),
            tr("fb.jobs.col.finished"), tr("fb.jobs.col.state"), tr("fb.jobs.col.target"),
            tr("fb.jobs.col.host"),
        ])
        if name == PENDING:
            self.tree.setItemDelegateForColumn(C_PROGRESS, _ProgressDelegate(panel._p, self.tree))
        hdr = self.tree.header()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, w in ((C_NAME, 220), (C_KIND, 110), (C_PROGRESS, 120), (C_SIZE, 80),
                       (C_SPEED, 90), (C_ETA, 70), (C_TIME, 130), (C_STATE, 150), (C_TARGET, 260)):
            hdr.resizeSection(col, w)
        hdr.setStretchLastSection(True)
        hidden = (C_TIME,) if name == PENDING else self._LIVE_COLUMNS
        for col in hidden:
            self.tree.setColumnHidden(col, True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(self.update_buttons)
        v.addWidget(self.tree)

        self._buttons: dict[str, object] = {}
        self._build_buttons()
        self.update_buttons()

    # ── toolbar ──────────────────────────────────────────────────────────────

    def _button(self, key: str, icon_name: str, label: str, slot):
        btn = tool_button(icon_name, label, self._panel._p.icon, label)
        btn.clicked.connect(slot)
        self._buttons[key] = btn
        return btn

    def _build_buttons(self) -> None:
        p = self._panel
        sel = self.selected_ids
        if self.name == PENDING:
            left = [
                self._button("pause", "pause", tr("fb.jobs.pause"), lambda: p.each(sel(), "pause")),
                self._button("resume", "play", tr("fb.jobs.resume"), lambda: p.each(sel(), "resume")),
                self._button("cancel", "x", tr("fb.jobs.cancel"), lambda: p.each(sel(), "cancel")),
            ]
            right = [self._button("all", "trash", tr("fb.jobs.cancel_all"), p.cancel_all)]
        elif self.name == FAILED_LIST:
            left = [
                self._button("retry", "rotate-cw", tr("fb.jobs.retry"), lambda: p.each(sel(), "retry")),
                self._button("remove", "minus", tr("fb.jobs.remove"), lambda: p.each(sel(), "remove")),
            ]
            right = [
                self._button("retry_all", "refresh", tr("fb.jobs.retry_all"),
                             lambda: p.each(self.all_ids(), "retry")),
                self._button("all", "trash", tr("fb.jobs.clear_list"),
                             lambda: p.each(self.all_ids(), "remove")),
            ]
        else:
            left = [
                self._button("remove", "minus", tr("fb.jobs.remove"), lambda: p.each(sel(), "remove")),
            ]
            right = [self._button("all", "trash", tr("fb.jobs.clear_list"),
                                  lambda: p.each(self.all_ids(), "remove"))]
        for b in left:
            self._bar.addWidget(b)
        self._bar.addStretch()
        for b in right:
            self._bar.addWidget(b)

    def update_buttons(self) -> None:
        jobs = [self._panel.job(i) for i in self.selected_ids()]
        states = [j.state for j in jobs if j is not None]
        has_rows = self.tree.topLevelItemCount() > 0
        enabled = {
            "pause": any(s in (RUNNING, QUEUED) for s in states),
            "resume": any(s == PAUSED for s in states),
            "cancel": any(s in (RUNNING, QUEUED, PAUSED) for s in states),
            "retry": bool(states),
            "remove": bool(states),
            "retry_all": has_rows,
            "all": has_rows,
        }
        for key, btn in self._buttons.items():
            btn.setEnabled(enabled.get(key, True))

    # ── rows ─────────────────────────────────────────────────────────────────

    def selected_ids(self) -> list[int]:
        return [it.data(0, _JOB_ID) for it in self.tree.selectedItems()]

    def all_ids(self) -> list[int]:
        return [self.tree.topLevelItem(i).data(0, _JOB_ID)
                for i in range(self.tree.topLevelItemCount())]

    def count(self) -> int:
        return self.tree.topLevelItemCount()

    def add(self, item: QTreeWidgetItem) -> None:
        if self.name == PENDING:
            self.tree.addTopLevelItem(item)          # in queue order
        else:
            self.tree.insertTopLevelItem(0, item)    # newest first

    def take(self, item: QTreeWidgetItem) -> None:
        idx = self.tree.indexOfTopLevelItem(item)
        if idx >= 0:
            self.tree.takeTopLevelItem(idx)

    def _menu(self, pos) -> None:
        ids = self.selected_ids()
        if not ids:
            return
        p = self._panel
        menu = QMenu(self)
        if self.name == PENDING:
            menu.addAction(tr("fb.jobs.pause"), lambda: p.each(ids, "pause"))
            menu.addAction(tr("fb.jobs.resume"), lambda: p.each(ids, "resume"))
            menu.addAction(tr("fb.jobs.cancel"), lambda: p.each(ids, "cancel"))
        else:
            if self.name == FAILED_LIST:
                menu.addAction(tr("fb.jobs.retry"), lambda: p.each(ids, "retry"))
            menu.addAction(tr("fb.jobs.remove"), lambda: p.each(ids, "remove"))
        job = p.job(ids[0])
        if job is not None and job.kind == DOWNLOAD:
            menu.addSeparator()
            menu.addAction(tr("fb.jobs.show_target"),
                           lambda: os.startfile(os.path.dirname(job.target)))
        menu.exec(self.tree.viewport().mapToGlobal(pos))


class TransferPanel(QTabWidget):
    def __init__(self, palette, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("fbBottom")
        self._p = palette
        self._queues: dict[TransferQueue, str] = {}          # queue -> host name
        self._owner: dict[int, TransferQueue] = {}           # job id -> queue
        self._items: dict[int, QTreeWidgetItem] = {}
        self._where: dict[int, _JobList] = {}                # job id -> list showing it
        self._log: list[tuple[str, object]] = []             # (host, LogEntry)
        self.setDocumentMode(True)
        self.tabBar().setDrawBase(False)            # Qt's base line is white in both themes
        self.lists = {name: _JobList(self, name) for name in (PENDING, FAILED_LIST, DONE_LIST)}
        for job_list in self.lists.values():
            self.addTab(job_list, "")
        self._build_log()
        self._update_title()

    @property
    def jobs(self) -> QTreeWidget:
        """The list of transfers still to do."""
        return self.lists[PENDING].tree

    # ── queues ───────────────────────────────────────────────────────────────

    def add_queue(self, queue: TransferQueue, host: str) -> None:
        self._queues[queue] = host
        queue.job_added.connect(lambda job, q=queue: self._on_job(job, q))
        queue.job_changed.connect(lambda job, q=queue: self._on_job(job, q))
        queue.jobs_removed.connect(self._on_removed)
        queue.log_added.connect(lambda e, h=host: self._on_log(e, h))
        queue.activity_changed.connect(self._update_title)

    def set_palette(self, palette) -> None:
        """Theme switch (the browser re-colours the buttons itself)."""
        self._p = palette
        delegate = self.jobs.itemDelegateForColumn(C_PROGRESS)
        if isinstance(delegate, _ProgressDelegate):
            delegate._p = palette
        for jid in list(self._items):             # only the rows already listed
            job = self.job(jid)
            if job is not None:
                self._on_job(job)
        self.jobs.viewport().update()
        self._update_title()

    def remove_queue(self, queue: TransferQueue) -> None:
        """A host was closed: its (finished) jobs leave the list, the log stays."""
        self._queues.pop(queue, None)
        self._on_removed([jid for jid, q in self._owner.items() if q is queue])

    def _jobs(self):
        for queue in self._queues:
            yield from queue.jobs.values()

    def job(self, jid: int) -> Optional[TransferJob]:
        queue = self._owner.get(jid)
        return queue.jobs.get(jid) if queue is not None else None

    def each(self, ids: list[int], action: str) -> None:
        """Run pause/resume/cancel/retry/remove on the queues the jobs belong to."""
        by_queue: dict[TransferQueue, list[int]] = {}
        for jid in ids:
            queue = self._owner.get(jid)
            if queue is not None and queue in self._queues:
                by_queue.setdefault(queue, []).append(jid)
        for queue, jids in by_queue.items():
            getattr(queue, action)(jids)

    def clear_finished(self) -> None:
        for queue in list(self._queues):
            queue.clear_finished()

    def cancel_all(self) -> None:
        for queue in list(self._queues):
            queue.cancel_all()

    # ── job rows ─────────────────────────────────────────────────────────────

    def _on_job(self, job: TransferJob, queue: Optional[TransferQueue] = None) -> None:
        item = self._items.get(job.id)
        if item is None:
            item = QTreeWidgetItem()
            item.setData(0, _JOB_ID, job.id)
            self._items[job.id] = item
            if queue is not None:
                self._owner[job.id] = queue
                item.setText(C_HOST, self._queues.get(queue, ""))
        target_list = self.lists[list_for(job.state)]
        current = self._where.get(job.id)
        if current is not target_list:
            if current is not None:
                current.take(item)
            target_list.add(item)
            self._where[job.id] = target_list
            if current is not None:
                current.update_buttons()
            self._update_title()
        label = job.extra.get("label") or job.name
        item.setText(C_NAME, label)
        item.setToolTip(C_NAME, job.source)
        item.setText(C_KIND, kind_label(job.kind))
        item.setData(C_PROGRESS, _PROGRESS, 1.0 if job.state == DONE else job.progress)
        item.setData(C_PROGRESS, _STATE, job.state)
        item.setText(C_SIZE, fmt_size(job.size) if job.size else "")
        running = job.state == RUNNING
        item.setText(C_SPEED, fmt_speed(job.speed) if running else "")
        item.setText(C_ETA, fmt_eta(job.eta) if running else "")
        ended = job.ended if job.state in (FAILED, CANCELLED, DONE, SKIPPED) else 0
        item.setText(C_TIME, datetime.fromtimestamp(ended).strftime("%Y-%m-%d %H:%M:%S") if ended else "")
        state = state_label(job.state)
        detail = job.error or job.note
        item.setText(C_STATE, f"{state} – {detail}" if detail else state)
        item.setToolTip(C_STATE, detail)
        item.setText(C_TARGET, job.target)
        item.setToolTip(C_TARGET, job.target)
        color = {FAILED: self._p.error, CANCELLED: self._p.text_dim, SKIPPED: self._p.text_dim,
                 DONE: self._p.ok, PAUSED: self._p.warn}.get(job.state)
        item.setForeground(C_STATE, QColor(color or self._p.text))
        target_list.update_buttons()

    def _on_removed(self, ids: list) -> None:
        touched = set()
        for jid in ids:
            self._owner.pop(jid, None)
            item = self._items.pop(jid, None)
            job_list = self._where.pop(jid, None)
            if item is not None and job_list is not None:
                job_list.take(item)
                touched.add(job_list)
        for job_list in touched:
            job_list.update_buttons()
        self._update_title()

    def _update_title(self) -> None:
        titles = {
            PENDING: tr("fb.jobs.tab.pending"),
            FAILED_LIST: tr("fb.jobs.tab.failed"),
            DONE_LIST: tr("fb.jobs.tab.done"),
        }
        for name, job_list in self.lists.items():
            n = job_list.count()
            idx = self.indexOf(job_list)
            self.setTabText(idx, f"{titles[name]} ({n})" if n else titles[name])
        failed = self.lists[FAILED_LIST]
        self.setTabIcon(self.indexOf(failed),
                        svg_icon("alert-triangle", self._p.error, 14) if failed.count() else QIcon())

    # ── log tab ──────────────────────────────────────────────────────────────

    def _build_log(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("fbToolbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(6, 3, 6, 3)
        h.addStretch()
        export = tool_button("download", tr("fb.log.export"), self._p.icon, tr("fb.log.export"))
        export.clicked.connect(self._export_log)
        clear = tool_button("trash", tr("fb.log.clear"), self._p.icon, tr("fb.log.clear"))
        clear.clicked.connect(self._clear_log)
        h.addWidget(export)
        h.addWidget(clear)
        v.addWidget(bar)

        self.log = QTreeWidget()
        self.log.setObjectName("fbLog")
        self.log.setRootIsDecorated(False)
        self.log.setAlternatingRowColors(True)
        self.log.setUniformRowHeights(True)
        self.log.setHeaderLabels([
            tr("fb.log.col.time"), tr("fb.jobs.col.kind"), tr("fb.log.col.source"),
            tr("fb.jobs.col.target"), tr("fb.col.size"), tr("fb.log.col.duration"),
            tr("fb.jobs.col.state"), tr("fb.log.col.message"), tr("fb.jobs.col.host"),
        ])
        hdr = self.log.header()
        for col, w in ((0, 130), (1, 110), (2, 220), (3, 220), (4, 80), (5, 70), (6, 100), (7, 220)):
            hdr.resizeSection(col, w)
        v.addWidget(self.log)
        self.addTab(page, tr("fb.log.title"))

    def _on_log(self, e, host: str = "") -> None:
        self._log.append((host, e))
        item = QTreeWidgetItem([
            datetime.fromtimestamp(e.time).strftime("%Y-%m-%d %H:%M:%S"),
            kind_label(e.kind), e.source, e.target, fmt_size(e.size) if e.size else "",
            f"{e.duration:.1f} s", state_label(e.result), e.message, host,
        ])
        for col in (2, 3, 7):
            item.setToolTip(col, item.text(col))
        if e.result == FAILED:
            item.setForeground(6, QColor(self._p.error))
        self.log.insertTopLevelItem(0, item)

    def _export_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("fb.log.export"),
            f"transfer-log-{datetime.now():%Y%m%d-%H%M}.csv", "CSV (*.csv)")
        if path:
            export_log_csv([e for _h, e in self._log], path, hosts=[h for h, _e in self._log])

    def _clear_log(self) -> None:
        for queue in self._queues:
            queue.log.clear()
        self._log.clear()
        self.log.clear()
