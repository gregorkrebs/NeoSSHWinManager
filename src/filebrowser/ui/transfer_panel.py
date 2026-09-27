"""
transfer_panel.py – Transfer list (with progress bars) and transfer log.

The browser's one panel shows the jobs of every connected host; each
host has its own TransferQueue (job ids are unique across queues).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter
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

_JOB_ID = Qt.ItemDataRole.UserRole + 1
_PROGRESS = Qt.ItemDataRole.UserRole + 2
_STATE = Qt.ItemDataRole.UserRole + 3

C_NAME, C_KIND, C_PROGRESS, C_SIZE, C_SPEED, C_ETA, C_STATE, C_TARGET, C_HOST = range(9)


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


class TransferPanel(QTabWidget):
    def __init__(self, palette, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("fbBottom")
        self._p = palette
        self._queues: dict[TransferQueue, str] = {}          # queue -> host name
        self._owner: dict[int, TransferQueue] = {}           # job id -> queue
        self._items: dict[int, QTreeWidgetItem] = {}
        self._log: list[tuple[str, object]] = []             # (host, LogEntry)
        self.setDocumentMode(True)
        self.tabBar().setDrawBase(False)            # Qt's base line is white in both themes
        self._build_jobs()
        self._build_log()
        self._update_title()

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
            job = self._job(jid)
            if job is not None:
                self._on_job(job)
        self.jobs.viewport().update()

    def remove_queue(self, queue: TransferQueue) -> None:
        """A host was closed: its (finished) jobs leave the list, the log stays."""
        self._queues.pop(queue, None)
        self._on_removed([jid for jid, q in self._owner.items() if q is queue])

    def _jobs(self):
        for queue in self._queues:
            yield from queue.jobs.values()

    def _job(self, jid: int) -> Optional[TransferJob]:
        queue = self._owner.get(jid)
        return queue.jobs.get(jid) if queue is not None else None

    def _each(self, ids: list[int], action: str) -> None:
        """Run pause/resume/cancel on the queues the jobs belong to."""
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

    # ── transfers tab ────────────────────────────────────────────────────────

    def _build_jobs(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("fbToolbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(6, 3, 6, 3)
        h.setSpacing(3)
        c = self._p.icon
        self._b_pause = tool_button("pause", tr("fb.jobs.pause"), c, tr("fb.jobs.pause"))
        self._b_resume = tool_button("play", tr("fb.jobs.resume"), c, tr("fb.jobs.resume"))
        self._b_cancel = tool_button("x", tr("fb.jobs.cancel"), c, tr("fb.jobs.cancel"))
        # check-circle, not check: check.svg is drawn in fixed white (checkbox tick)
        self._b_clear = tool_button("check-circle", tr("fb.jobs.clear_done"), c, tr("fb.jobs.clear_done"))
        self._b_cancel_all = tool_button("trash", tr("fb.jobs.cancel_all"), c, tr("fb.jobs.cancel_all"))
        self._b_pause.clicked.connect(lambda: self._each(self._selected_ids(), "pause"))
        self._b_resume.clicked.connect(lambda: self._each(self._selected_ids(), "resume"))
        self._b_cancel.clicked.connect(lambda: self._each(self._selected_ids(), "cancel"))
        self._b_clear.clicked.connect(self.clear_finished)
        self._b_cancel_all.clicked.connect(self.cancel_all)
        for b in (self._b_pause, self._b_resume, self._b_cancel):
            h.addWidget(b)
        h.addStretch()
        h.addWidget(self._b_clear)
        h.addWidget(self._b_cancel_all)
        v.addWidget(bar)

        self.jobs = QTreeWidget()
        self.jobs.setObjectName("fbJobs")
        self.jobs.setRootIsDecorated(False)
        self.jobs.setAlternatingRowColors(True)
        self.jobs.setUniformRowHeights(True)
        self.jobs.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.jobs.setHeaderLabels([
            tr("fb.col.name"), tr("fb.jobs.col.kind"), tr("fb.jobs.col.progress"),
            tr("fb.col.size"), tr("fb.jobs.col.speed"), tr("fb.jobs.col.eta"),
            tr("fb.jobs.col.state"), tr("fb.jobs.col.target"), tr("fb.jobs.col.host"),
        ])
        self.jobs.setItemDelegateForColumn(C_PROGRESS, _ProgressDelegate(self._p, self.jobs))
        hdr = self.jobs.header()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, w in ((C_NAME, 220), (C_KIND, 110), (C_PROGRESS, 120), (C_SIZE, 80),
                       (C_SPEED, 90), (C_ETA, 70), (C_STATE, 150), (C_TARGET, 260)):
            hdr.resizeSection(col, w)
        hdr.setStretchLastSection(True)
        self.jobs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.jobs.customContextMenuRequested.connect(self._job_menu)
        self.jobs.itemSelectionChanged.connect(self._update_buttons)
        v.addWidget(self.jobs)
        self.addTab(page, tr("fb.jobs.title"))
        self._update_buttons()

    def _selected_ids(self) -> list[int]:
        return [it.data(0, _JOB_ID) for it in self.jobs.selectedItems()]

    def _update_buttons(self) -> None:
        jobs = [self._job(i) for i in self._selected_ids()]
        states = [j.state for j in jobs if j is not None]
        self._b_pause.setEnabled(any(s in (RUNNING, QUEUED) for s in states))
        self._b_resume.setEnabled(any(s in (PAUSED, FAILED) for s in states))
        self._b_cancel.setEnabled(any(s in (RUNNING, QUEUED, PAUSED) for s in states))

    def _on_job(self, job: TransferJob, queue: Optional[TransferQueue] = None) -> None:
        item = self._items.get(job.id)
        if item is None:
            item = QTreeWidgetItem()
            item.setData(0, _JOB_ID, job.id)
            self._items[job.id] = item
            if queue is not None:
                self._owner[job.id] = queue
                item.setText(C_HOST, self._queues.get(queue, ""))
            self.jobs.addTopLevelItem(item)
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
        state = state_label(job.state)
        detail = job.error or job.note
        item.setText(C_STATE, f"{state} – {detail}" if detail else state)
        item.setToolTip(C_STATE, detail)
        item.setText(C_TARGET, job.target)
        item.setToolTip(C_TARGET, job.target)
        color = {FAILED: self._p.error, CANCELLED: self._p.text_dim, SKIPPED: self._p.text_dim,
                 DONE: self._p.ok, PAUSED: self._p.warn}.get(job.state)
        if color:
            item.setForeground(C_STATE, QColor(color))
        self._update_buttons()

    def _on_removed(self, ids: list) -> None:
        for jid in ids:
            self._owner.pop(jid, None)
            item = self._items.pop(jid, None)
            if item is not None:
                idx = self.jobs.indexOfTopLevelItem(item)
                if idx >= 0:
                    self.jobs.takeTopLevelItem(idx)
        self._update_title()

    def _job_menu(self, pos) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        menu = QMenu(self)
        menu.addAction(tr("fb.jobs.pause"), lambda: self._each(ids, "pause"))
        menu.addAction(tr("fb.jobs.resume"), lambda: self._each(ids, "resume"))
        menu.addAction(tr("fb.jobs.cancel"), lambda: self._each(ids, "cancel"))
        job = self._job(ids[0])
        if job is not None and job.kind == DOWNLOAD:
            menu.addSeparator()
            menu.addAction(tr("fb.jobs.show_target"),
                           lambda: os.startfile(os.path.dirname(job.target)))
        menu.exec(self.jobs.viewport().mapToGlobal(pos))

    def _update_title(self) -> None:
        active = sum(1 for j in self._jobs() if j.state in (RUNNING, QUEUED))
        failed = sum(1 for j in self._jobs() if j.state == FAILED)
        title = tr("fb.jobs.title")
        if active:
            title += f" ({active})"
        if failed:
            title += "  ⚠ " + str(failed)
        self.setTabText(0, title)

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
