"""
transfers.py – The transfer queue of a browser window.

Jobs are files (folders are expanded into file jobs by a background scan).
The queue runs up to N uploads and M downloads at once (separate limits from
the settings), paces them with one shared rate limiter per direction, asks the
UI about conflicts, resumes paused/failed transfers from their offset, keeps
source timestamps, optionally verifies SHA-256 checksums and records every
finished job in a log.

Threading: the queue object and its job list live in the Qt main thread; every
running job has its own Python worker thread that only touches its own job
object and reports back through queued Qt signals.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import tarfile
import tempfile
import threading
import time
import urllib.request
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal

from src.app_logger import logger
from src.filebrowser import commands
from src.filebrowser.fs import FsError, LocalFS, RateLimiter, TransferAborted
from src.filebrowser.model import (
    CANCEL, KEEP_BOTH, OVERWRITE, RESUME, SKIP,
    ConflictInfo, FileEntry, auto_decision, keep_both_name, rjoin, rname, rparent,
)

# Job kinds
UPLOAD = "upload"
DOWNLOAD = "download"
URL_CLIENT = "url"             # web → this PC → server (streamed, no temp file)
URL_SERVER = "url_server"      # the server downloads by itself (curl/wget/PowerShell)
DELETE_REMOTE = "delete_remote"
DELETE_LOCAL = "delete_local"

# Job states
QUEUED = "queued"
RUNNING = "running"
PAUSED = "paused"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
SKIPPED = "skipped"
FINISHED_STATES = (DONE, FAILED, CANCELLED, SKIPPED)

# What to do after a job finished successfully.
AFTER_EXTRACT_REMOTE = "extract_remote"    # unpack an uploaded archive on the server
AFTER_EXTRACT_LOCAL = "extract_local"      # unpack a downloaded archive locally

ConflictResolver = Callable[[ConflictInfo], tuple[str, bool]]   # -> (decision, apply_to_all)

_JOB_IDS = itertools.count(1)          # shared by all queues (thread-safe in CPython)


@dataclass
class TransferJob:
    id: int
    kind: str
    source: str
    target: str
    size: int = 0
    mtime: float = 0.0
    batch: int = 0
    state: str = QUEUED
    done: int = 0
    speed: float = 0.0
    error: str = ""
    note: str = ""
    started: float = 0.0
    ended: float = 0.0
    decision: Optional[str] = None       # pre-decided conflict answer
    ensure_parent: bool = False          # create the target folder first (sync)
    after: Optional[str] = None
    extra: dict = field(default_factory=dict)
    # control flags, set from the main thread, read by the worker
    pause_requested: bool = False
    cancel_requested: bool = False

    @property
    def direction(self) -> str:
        return "down" if self.kind in (DOWNLOAD, DELETE_LOCAL) else "up"

    @property
    def name(self) -> str:
        return rname(self.target.replace("\\", "/"))

    @property
    def progress(self) -> float:
        return min(1.0, self.done / self.size) if self.size else 0.0

    @property
    def eta(self) -> float:
        if self.speed <= 0 or not self.size:
            return float("inf")
        return max(0.0, (self.size - self.done) / self.speed)


@dataclass
class LogEntry:
    time: float
    kind: str
    source: str
    target: str
    size: int
    duration: float
    result: str
    message: str = ""


class _SpeedMeter:
    """Average speed over the last few seconds."""

    def __init__(self, window: float = 3.0) -> None:
        self._samples: deque = deque()
        self._window = window

    def add(self, total_done: int) -> float:
        now = time.monotonic()
        self._samples.append((now, total_done))
        while len(self._samples) > 2 and now - self._samples[0][0] > self._window:
            self._samples.popleft()
        t0, d0 = self._samples[0]
        return (total_done - d0) / (now - t0) if now > t0 else 0.0


class TransferQueue(QObject):
    job_added = pyqtSignal(object)          # TransferJob
    job_changed = pyqtSignal(object)        # TransferJob (throttled while running)
    jobs_removed = pyqtSignal(list)         # [job ids]
    log_added = pyqtSignal(object)          # LogEntry
    target_changed = pyqtSignal(str, str)   # ("remote"|"local", directory) – refresh hint
    message = pyqtSignal(str)               # user-facing error from a background step
    activity_changed = pyqtSignal()         # totals / idle state changed

    _jobs_found = pyqtSignal(list)
    _scan_finished = pyqtSignal()
    _job_done = pyqtSignal(object)

    def __init__(self, remote, settings_manager, resolver: ConflictResolver,
                 local: Optional[LocalFS] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.remote = remote
        self.local = local or LocalFS()
        self._settings = settings_manager
        self._resolver = resolver
        self.jobs: dict[int, TransferJob] = {}
        self.log: list[LogEntry] = []
        # Job ids are unique across all queues: one transfer list shows the
        # jobs of every host in the browser window.
        self._ids = _JOB_IDS
        self._batches = itertools.count(1)
        self._batch_decisions: dict[int, str] = {}
        self._ask_lock = threading.Lock()
        self._running: set[int] = set()
        self._scans = 0
        self._closed = False
        self._limit_up = RateLimiter()
        self._limit_down = RateLimiter()
        self.apply_settings()
        self._jobs_found.connect(self._add_jobs, Qt.ConnectionType.QueuedConnection)
        self._scan_finished.connect(self._on_scan_finished, Qt.ConnectionType.QueuedConnection)
        self._job_done.connect(self._on_job_done, Qt.ConnectionType.QueuedConnection)

    # ── settings ─────────────────────────────────────────────────────────────

    @property
    def settings(self):
        return self._settings.settings

    def apply_settings(self) -> None:
        s = self.settings
        self._limit_up.set_rate(s.limit_up_kib * 1024)
        self._limit_down.set_rate(s.limit_down_kib * 1024)
        self._pump()

    # ── state queries ────────────────────────────────────────────────────────

    def active_count(self) -> int:
        return sum(1 for j in self.jobs.values() if j.state in (QUEUED, RUNNING)) + self._scans

    def running_jobs(self) -> list[TransferJob]:
        return [self.jobs[i] for i in self._running if i in self.jobs]

    def total_speed(self, direction: str) -> float:
        return sum(j.speed for j in self.running_jobs() if j.direction == direction)

    # ── adding work (main thread) ────────────────────────────────────────────

    def new_batch(self) -> int:
        return next(self._batches)

    def _job(self, kind: str, source: str, target: str, batch: int, **kw) -> TransferJob:
        return TransferJob(id=next(self._ids), kind=kind, source=source, target=target,
                           batch=batch, **kw)

    def upload(self, local_paths: list[str], remote_dir: str) -> int:
        """Queue files and whole folder trees for upload into remote_dir."""
        batch = self.new_batch()

        def scan() -> None:
            jobs = []
            for path in local_paths:
                name = os.path.basename(path.rstrip("\\/"))
                if os.path.isdir(path):
                    base = rjoin(remote_dir, name)
                    self.remote.makedirs(base)
                    for dirpath, dirs, files in self.local.walk(path):
                        rel = os.path.relpath(dirpath, path).replace("\\", "/")
                        rdir = base if rel == "." else rjoin(base, rel)
                        for d in dirs:
                            self.remote.makedirs(rjoin(rdir, d.name))
                        for f in files:
                            jobs.append(self._job(UPLOAD, f.path, rjoin(rdir, f.name), batch,
                                                  size=f.size, mtime=f.mtime))
                        if len(jobs) >= 200:
                            self._jobs_found.emit(jobs)
                            jobs = []
                else:
                    entry = self.local.stat(path)
                    if entry:
                        jobs.append(self._job(UPLOAD, path, rjoin(remote_dir, name), batch,
                                              size=entry.size, mtime=entry.mtime))
            self._jobs_found.emit(jobs)
        self._scan(scan)
        return batch

    def download(self, entries: list[FileEntry], local_dir: str) -> int:
        """Queue remote files and folder trees for download into local_dir."""
        batch = self.new_batch()

        def scan() -> None:
            jobs = []
            for entry in entries:
                if entry.is_dir:
                    base = os.path.join(local_dir, entry.name)
                    os.makedirs(base, exist_ok=True)
                    for dirpath, dirs, files in self.remote.walk(entry.path):
                        rel = dirpath[len(entry.path):].strip("/")
                        ldir = os.path.join(base, *rel.split("/")) if rel else base
                        for d in dirs:
                            os.makedirs(os.path.join(ldir, d.name), exist_ok=True)
                        for f in files:
                            jobs.append(self._job(DOWNLOAD, f.path, os.path.join(ldir, f.name),
                                                  batch, size=f.size, mtime=f.mtime))
                        if len(jobs) >= 200:
                            self._jobs_found.emit(jobs)
                            jobs = []
                else:
                    jobs.append(self._job(DOWNLOAD, entry.path, os.path.join(local_dir, entry.name),
                                          batch, size=entry.size, mtime=entry.mtime))
            self._jobs_found.emit(jobs)
        self._scan(scan)
        return batch

    def download_to(self, entry: FileEntry, local_path: str, decision: Optional[str] = OVERWRITE,
                    on_done: Optional[Callable[[TransferJob], None]] = None) -> TransferJob:
        """One file to an exact local path (open/edit/compare use this)."""
        job = self._job(DOWNLOAD, entry.path, local_path, self.new_batch(),
                        size=entry.size, mtime=entry.mtime, decision=decision)
        if on_done:
            job.extra["on_done"] = on_done
        self._add_jobs([job])
        return job

    def upload_to(self, local_path: str, remote_path: str, decision: Optional[str] = OVERWRITE,
                  on_done: Optional[Callable[[TransferJob], None]] = None) -> TransferJob:
        entry = self.local.stat(local_path)
        job = self._job(UPLOAD, local_path, remote_path, self.new_batch(),
                        size=entry.size if entry else 0, mtime=entry.mtime if entry else 0,
                        decision=decision)
        if on_done:
            job.extra["on_done"] = on_done
        self._add_jobs([job])
        return job

    def upload_url(self, url: str, remote_path: str, via_server: bool) -> TransferJob:
        url = commands.validate_url(url)
        kind = URL_SERVER if via_server and self.remote.can_exec else URL_CLIENT
        job = self._job(kind, url, remote_path, self.new_batch())
        self._add_jobs([job])
        return job

    def sync(self, items, local_root: str, remote_root: str) -> int:
        """Queue the actions of a compare_trees() result (already decided)."""
        from src.filebrowser.model import (
            ACT_DELETE_LOCAL, ACT_DELETE_REMOTE, ACT_DOWNLOAD, ACT_UPLOAD,
        )
        batch = self.new_batch()
        jobs = []
        for item in items:
            if not item.selected:
                continue
            lpath = os.path.join(local_root, *item.rel.split("/"))
            rpath = rjoin(remote_root, item.rel) if item.rel else remote_root
            if item.action == ACT_UPLOAD:
                jobs.append(self._job(UPLOAD, lpath, rpath, batch, size=item.local.size,
                                      mtime=item.local.mtime, decision=OVERWRITE,
                                      ensure_parent=True))
            elif item.action == ACT_DOWNLOAD:
                jobs.append(self._job(DOWNLOAD, rpath, lpath, batch, size=item.remote.size,
                                      mtime=item.remote.mtime, decision=OVERWRITE,
                                      ensure_parent=True))
            elif item.action == ACT_DELETE_REMOTE:
                jobs.append(self._job(DELETE_REMOTE, rpath, rpath, batch))
            elif item.action == ACT_DELETE_LOCAL:
                jobs.append(self._job(DELETE_LOCAL, lpath, lpath, batch))
        self._add_jobs(jobs)
        return batch

    def upload_folder_as_archive(self, local_dir: str, remote_dir: str) -> None:
        """Pack a folder locally, upload one archive, unpack it on the server."""
        batch = self.new_batch()

        def scan() -> None:
            tmp = tempfile.NamedTemporaryFile(prefix="neossh-", suffix=".tar.gz", delete=False)
            tmp.close()
            with tarfile.open(tmp.name, "w:gz") as tar:
                tar.add(local_dir, arcname=os.path.basename(local_dir.rstrip("\\/")))
            archive = rjoin(remote_dir, f".neossh-{uuid.uuid4().hex[:8]}.tar.gz")
            job = self._job(UPLOAD, tmp.name, archive, batch,
                            size=os.path.getsize(tmp.name), decision=OVERWRITE,
                            after=AFTER_EXTRACT_REMOTE,
                            extra={"dest": remote_dir, "cleanup_local": tmp.name,
                                   "label": os.path.basename(local_dir.rstrip("\\/")) + " (tar.gz)"})
            self._jobs_found.emit([job])
        self._scan(scan)

    def download_as_archive(self, entries: list[FileEntry], local_dir: str) -> None:
        """Pack on the server, download one archive, unpack it locally."""
        batch = self.new_batch()
        directory = rparent(entries[0].path)

        def scan() -> None:
            name = f".neossh-{uuid.uuid4().hex[:8]}.tar.gz"
            cmd = commands.pack_command(self.remote.is_windows, directory,
                                        [e.name for e in entries], name, commands.ARCHIVE_TGZ)
            code, out, err = self.remote.run(cmd, timeout=3600)
            if code != 0:
                raise FsError((err or out).strip() or f"exit code {code}")
            archive = rjoin(directory, name)
            entry = self.remote.stat(archive)
            tmp = os.path.join(tempfile.gettempdir(), name.lstrip("."))
            job = self._job(DOWNLOAD, archive, tmp, batch, size=entry.size if entry else 0,
                            decision=OVERWRITE, after=AFTER_EXTRACT_LOCAL,
                            extra={"dest": local_dir, "cleanup_remote": archive,
                                   "label": ", ".join(e.name for e in entries) + " (tar.gz)"})
            self._jobs_found.emit([job])
        self._scan(scan)

    def _scan(self, fn: Callable[[], None]) -> None:
        self._scans += 1
        self.activity_changed.emit()

        def run() -> None:
            try:
                fn()
            except Exception as e:
                logger.warning("filebrowser: scan failed: %s", e)
                self.message.emit(str(e))
            finally:
                self._scan_finished.emit()
        threading.Thread(target=run, daemon=True, name="fb-scan").start()

    def _on_scan_finished(self) -> None:
        self._scans = max(0, self._scans - 1)
        self.activity_changed.emit()

    def _add_jobs(self, jobs: list) -> None:
        if not jobs:
            return
        for job in jobs:
            self.jobs[job.id] = job
            self.job_added.emit(job)
        self.activity_changed.emit()
        self._pump()

    # ── control (main thread) ────────────────────────────────────────────────

    def pause(self, job_ids: list[int]) -> None:
        for jid in job_ids:
            job = self.jobs.get(jid)
            if not job:
                continue
            if job.state == RUNNING:
                job.pause_requested = True
            elif job.state == QUEUED:
                job.state = PAUSED
                self.job_changed.emit(job)
        self.activity_changed.emit()

    def resume(self, job_ids: list[int]) -> None:
        for jid in job_ids:
            job = self.jobs.get(jid)
            if job and job.state in (PAUSED, FAILED):
                # Continue where it stopped: the partial target is ours.
                if job.kind in (UPLOAD, DOWNLOAD) and job.done:
                    job.decision = RESUME
                job.state = QUEUED
                job.error = ""
                job.pause_requested = job.cancel_requested = False
                self.job_changed.emit(job)
        self._pump()
        self.activity_changed.emit()

    def cancel(self, job_ids: list[int]) -> None:
        for jid in job_ids:
            job = self.jobs.get(jid)
            if not job:
                continue
            if job.state == RUNNING:
                job.cancel_requested = True
            elif job.state in (QUEUED, PAUSED):
                job.state = CANCELLED
                self.job_changed.emit(job)
        self.activity_changed.emit()

    def retry(self, job_ids: list[int]) -> None:
        """Queue failed or cancelled jobs again. A failed one continues where
        it stopped; a cancelled one starts over, as its partial target was
        removed on cancel."""
        for jid in job_ids:
            job = self.jobs.get(jid)
            if job and job.state == CANCELLED:
                job.done = 0
                job.note = ""
                if job.decision == RESUME:
                    job.decision = None
                job.state = PAUSED
        self.resume(job_ids)

    def cancel_all(self) -> None:
        self.cancel([j.id for j in self.jobs.values() if j.state not in FINISHED_STATES])

    def remove(self, job_ids: list[int]) -> None:
        """Drop finished jobs from the list; unfinished ones stay."""
        ids = [jid for jid in job_ids
               if jid in self.jobs and self.jobs[jid].state in FINISHED_STATES]
        for jid in ids:
            del self.jobs[jid]
        if ids:
            self.jobs_removed.emit(ids)

    def clear_finished(self) -> None:
        self.remove(list(self.jobs))

    def shutdown(self) -> None:
        self._closed = True
        self.cancel_all()

    # ── scheduling ───────────────────────────────────────────────────────────

    def _limits(self) -> dict[str, int]:
        cap = max(1, int(getattr(self.remote, "max_parallel", 4)))
        return {"up": min(self.settings.max_uploads, cap),
                "down": min(self.settings.max_downloads, cap)}

    def _pump(self) -> None:
        if self._closed:
            return
        limits = self._limits()
        busy = {"up": 0, "down": 0}
        for jid in self._running:
            job = self.jobs.get(jid)
            if job:
                busy[job.direction] += 1
        for job in sorted(self.jobs.values(), key=lambda j: j.id):
            if job.state != QUEUED:
                continue
            if busy[job.direction] >= limits[job.direction]:
                continue
            busy[job.direction] += 1
            self._start(job)

    def _start(self, job: TransferJob) -> None:
        job.state = RUNNING
        job.started = time.time()
        job.pause_requested = job.cancel_requested = False
        self._running.add(job.id)
        self.job_changed.emit(job)
        threading.Thread(target=self._worker, args=(job,), daemon=True,
                         name=f"fb-job-{job.id}").start()

    def _on_job_done(self, job: TransferJob) -> None:
        self._running.discard(job.id)
        job.ended = time.time()
        job.speed = 0.0
        self.job_changed.emit(job)
        if job.state in FINISHED_STATES:
            entry = LogEntry(time=job.ended, kind=job.kind, source=job.source,
                             target=job.target, size=job.done or job.size,
                             duration=max(0.0, job.ended - job.started), result=job.state,
                             message=job.error or job.note)
            self.log.append(entry)
            self.log_added.emit(entry)
        if job.state == DONE:
            if job.kind in (UPLOAD, URL_CLIENT, URL_SERVER, DELETE_REMOTE):
                self.target_changed.emit("remote", rparent(job.target))
                if job.after == AFTER_EXTRACT_REMOTE:
                    self.target_changed.emit("remote", job.extra.get("dest", ""))
            else:
                self.target_changed.emit("local", os.path.dirname(job.target))
                if job.after == AFTER_EXTRACT_LOCAL:
                    self.target_changed.emit("local", job.extra.get("dest", ""))
        callback = job.extra.pop("on_done", None)
        if callback:
            try:
                callback(job)
            except Exception as e:
                logger.debug("filebrowser: job callback failed: %s", e)
        self._pump()
        self.activity_changed.emit()

    # ── worker thread ────────────────────────────────────────────────────────

    def _worker(self, job: TransferJob) -> None:
        try:
            self._execute(job)
            if job.state == RUNNING:
                job.state = DONE
        except TransferAborted as a:
            if a.reason == "pause":
                job.state = PAUSED
            else:
                # Clean up first: until the state changes the job still counts
                # as active, so nobody takes the partial file for gone too early.
                self._cleanup_cancelled(job)
                job.state = CANCELLED
        except Exception as e:
            # Tearing down an aborted transfer can raise on its own (e.g. the
            # SFTP close after cut-off pipelined writes). What the user asked
            # for wins over that follow-up error.
            if job.cancel_requested or self._closed:
                self._cleanup_cancelled(job)
                job.state = CANCELLED
            elif job.pause_requested:
                job.state = PAUSED
            else:
                job.state = FAILED
                job.error = str(e) or e.__class__.__name__
                logger.info("filebrowser: %s %s failed: %s", job.kind, job.source, job.error)
        finally:
            self._job_done.emit(job)

    def _check(self, job: TransferJob) -> None:
        if job.cancel_requested or self._closed:
            raise TransferAborted("cancel")
        if job.pause_requested:
            raise TransferAborted("pause")

    def _data_callback(self, job: TransferJob) -> Callable[[int], None]:
        limiter = self._limit_down if job.direction == "down" else self._limit_up
        meter = _SpeedMeter()
        last_emit = [0.0]

        def on_data(n: int) -> None:
            self._check(job)
            limiter.consume(n, lambda: self._check(job))
            job.done += n
            now = time.monotonic()
            if now - last_emit[0] >= 0.2:
                last_emit[0] = now
                job.speed = meter.add(job.done)
                self.job_changed.emit(job)
        return on_data

    def _limited(self, job: TransferJob) -> bool:
        limiter = self._limit_down if job.direction == "down" else self._limit_up
        return limiter.rate > 0

    def _execute(self, job: TransferJob) -> None:
        self._check(job)
        if job.kind == UPLOAD:
            self._run_upload(job)
        elif job.kind == DOWNLOAD:
            self._run_download(job)
        elif job.kind == URL_CLIENT:
            self._run_url_client(job)
        elif job.kind == URL_SERVER:
            self._run_url_server(job)
        elif job.kind == DELETE_REMOTE:
            self.remote.rmtree(job.target)
        elif job.kind == DELETE_LOCAL:
            self.local.remove_many([job.target])

    # conflicts
    def _resolve_conflict(self, job: TransferJob, source: FileEntry, target: FileEntry) -> str:
        info = ConflictInfo(source=source, target=target,
                            direction="down" if job.kind == DOWNLOAD else "up", batch=job.batch)
        if job.batch in self._batch_decisions:
            decision = self._batch_decisions[job.batch]
        else:
            decision = auto_decision(self.settings.conflict_policy, info)
        if decision is None:
            with self._ask_lock:          # one dialog at a time
                decision = self._batch_decisions.get(job.batch)
                if decision is None:
                    self._check(job)
                    decision, apply_all = self._resolver(info)
                    if apply_all:
                        self._batch_decisions[job.batch] = decision
        if decision == RESUME and not info.can_resume:
            decision = OVERWRITE
        return decision

    def _apply_decision(self, job: TransferJob, decision: str, exists: Callable[[str], bool],
                        target_size: int) -> int:
        """Returns the resume offset (0 = from the start). Raises to stop."""
        if decision == SKIP:
            job.state = SKIPPED
            raise _Skip()
        if decision == CANCEL:
            for other in self.jobs.values():
                if other.batch == job.batch and other.state in (QUEUED, PAUSED):
                    other.cancel_requested = True
                    other.state = CANCELLED
            raise TransferAborted("cancel")
        if decision == KEEP_BOTH:
            if job.kind == DOWNLOAD:
                directory = os.path.dirname(job.target)
                new = keep_both_name(os.path.basename(job.target),
                                     lambda n: exists(os.path.join(directory, n)))
                job.target = os.path.join(directory, new)
            else:
                directory = rparent(job.target)
                new = keep_both_name(rname(job.target), lambda n: exists(rjoin(directory, n)))
                job.target = rjoin(directory, new)
            job.note = new
            return 0
        if decision == RESUME:
            return target_size
        return 0

    # upload / download with retries
    def _transfer_with_retries(self, job: TransferJob, run: Callable[[int], None],
                               offset: int, current_size: Callable[[], int]) -> None:
        attempts = max(0, self.settings.retry_attempts) if self.settings.auto_reconnect else 0
        for attempt in itertools.count():
            job.done = offset
            try:
                run(offset)
                return
            except FsError as e:
                if attempt >= attempts or not self._retryable(e):
                    raise
                self._check(job)
                time.sleep(min(10, 1 + attempt * 2))
                self._check(job)
                self.remote.reconnect()
                # Continue after what already arrived instead of starting over.
                offset = current_size() if getattr(self.remote, "can_resume", False) else 0
                job.note = f"retry {attempt + 1}"

    def _retryable(self, exc: BaseException) -> bool:
        """
        Only connection problems are worth another attempt; a full disk, a
        missing file or "permission denied" would just fail again.
        """
        import ftplib
        import socket
        import paramiko
        if getattr(self.remote, "protocol", "") == "sftp" and not self.remote.connected():
            return True
        e, depth = exc, 0
        while e is not None and depth < 6:
            if isinstance(e, (EOFError, ConnectionError, TimeoutError, socket.timeout,
                              paramiko.SSHException, ftplib.error_temp)):
                return True
            e, depth = e.__cause__ or e.__context__, depth + 1
        return False

    def _run_upload(self, job: TransferJob) -> None:
        if job.ensure_parent:
            self.remote.makedirs(rparent(job.target))
        source = self.local.stat(job.source)
        if source is None:
            raise FsError(f"Local file missing: {job.source}")
        job.size, job.mtime = source.size, source.mtime
        created = False
        offset = 0
        try:
            target = self.remote.stat(job.target)
            if target is not None:
                decision = job.decision or self._resolve_conflict(job, source, target)
                offset = self._apply_decision(job, decision, self.remote.exists, target.size)
            else:
                created = True
        except _Skip:
            return
        if offset >= job.size:
            offset = 0
        job.extra["created"] = created

        def current_size() -> int:
            t = self.remote.stat(job.target)
            return t.size if t and t.size <= job.size else 0

        on_data = self._data_callback(job)
        self._transfer_with_retries(
            job, lambda off: self.remote.upload(job.source, job.target, off, on_data,
                                                limited=self._limited(job)),
            offset, current_size)
        if self.settings.preserve_mtime and job.mtime:
            try:
                self.remote.set_mtime(job.target, job.mtime)
            except FsError as e:
                logger.debug("filebrowser: could not keep mtime: %s", e)
        self._verify(job, local_path=job.source, remote_path=job.target)
        self._after(job)

    def _run_download(self, job: TransferJob) -> None:
        directory = os.path.dirname(job.target)
        if directory:
            os.makedirs(directory, exist_ok=True)
        source = self.remote.stat(job.source)
        if source is None:
            raise FsError(f"Remote file missing: {job.source}")
        job.size, job.mtime = source.size, source.mtime or job.mtime
        created = False
        offset = 0
        try:
            target = self.local.stat(job.target)
            if target is not None:
                decision = job.decision or self._resolve_conflict(job, source, target)
                offset = self._apply_decision(job, decision, os.path.lexists, target.size)
            else:
                created = True
        except _Skip:
            return
        if offset >= job.size:
            offset = 0
        job.extra["created"] = created

        def current_size() -> int:
            try:
                size = os.path.getsize(job.target)
            except OSError:
                return 0
            return size if size <= job.size else 0

        on_data = self._data_callback(job)
        self._transfer_with_retries(
            job, lambda off: self.remote.download(job.source, job.target, off, on_data,
                                                  limited=self._limited(job)),
            offset, current_size)
        if self.settings.preserve_mtime and job.mtime:
            try:
                os.utime(job.target, (job.mtime, job.mtime))
            except OSError:
                pass
        self._verify(job, local_path=job.target, remote_path=job.source)
        self._after(job)

    def _run_url_client(self, job: TransferJob) -> None:
        request = urllib.request.Request(job.source, headers={"User-Agent": "NeoSSHWinManager"})
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except Exception as e:
            raise FsError(f"Download failed: {e}") from e
        with response:
            try:
                job.size = int(response.headers.get("Content-Length") or 0)
            except ValueError:
                job.size = 0
            if self._url_target_conflict(job):
                return
            on_data = self._data_callback(job)
            self.remote.upload_stream(response, job.target, on_data, limited=self._limited(job))
        job.note = "via PC"

    def _run_url_server(self, job: TransferJob) -> None:
        if self._url_target_conflict(job):
            return
        try:                                    # size for the progress bar, if the server says
            head = urllib.request.Request(job.source, method="HEAD",
                                          headers={"User-Agent": "NeoSSHWinManager"})
            with urllib.request.urlopen(head, timeout=10) as resp:
                job.size = int(resp.headers.get("Content-Length") or 0)
        except Exception:
            job.size = 0
        stop = threading.Event()

        def poll() -> None:                     # the file grows on the server
            while not stop.wait(1.0):
                try:
                    entry = self.remote.stat(job.target)
                except FsError:
                    continue
                if entry:
                    job.done = entry.size
                    self.job_changed.emit(job)
        threading.Thread(target=poll, daemon=True).start()
        try:
            code, out, err = self.remote.run(
                commands.fetch_url_command(self.remote.is_windows, job.source, job.target),
                timeout=6 * 3600,
                should_stop=lambda: job.cancel_requested or self._closed,
            )
        finally:
            stop.set()
        if code == 127 and not self.remote.is_windows:
            # Neither curl nor wget on the server: stream it through this PC.
            logger.info("filebrowser: no fetch tool on server, streaming via PC")
            job.kind = URL_CLIENT
            self._run_url_client(job)
            return
        if code != 0:
            raise FsError((err or out).strip() or f"exit code {code}")
        entry = self.remote.stat(job.target)
        job.done = entry.size if entry else job.done
        job.size = job.size or job.done
        job.note = "via server"

    def _url_target_conflict(self, job: TransferJob) -> bool:
        """Conflict handling for URL uploads; True when the job was skipped."""
        target = self.remote.stat(job.target)
        if target is None:
            return False
        source = FileEntry(name=rname(job.target), path=job.source, is_dir=False,
                           size=job.size, mtime=time.time())
        try:
            decision = job.decision or self._resolve_conflict(job, source, target)
            if decision == RESUME:
                decision = OVERWRITE
            self._apply_decision(job, decision, self.remote.exists, target.size)
        except _Skip:
            return True
        return False

    # post-processing
    def _verify(self, job: TransferJob, local_path: str, remote_path: str) -> None:
        if not self.settings.verify_checksum or not self.remote.can_exec:
            return
        self._check(job)
        digest = hashlib.sha256()
        with open(local_path, "rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(block)
        code, out, _err = self.remote.run(
            commands.checksum_command(self.remote.is_windows, remote_path), timeout=1800)
        remote_hash = commands.parse_checksum(out) if code == 0 else None
        if remote_hash is None:
            job.note = "SHA-256 n/a"
        elif remote_hash != digest.hexdigest():
            raise FsError("SHA-256 mismatch after transfer")
        else:
            job.note = "SHA-256 ✓"

    def _after(self, job: TransferJob) -> None:
        if job.after == AFTER_EXTRACT_REMOTE:
            try:
                code, out, err = self.remote.run(
                    commands.extract_command(self.remote.is_windows, job.target, job.extra["dest"]),
                    timeout=3600)
                if code != 0:
                    raise FsError((err or out).strip() or f"exit code {code}")
            finally:
                try:
                    self.remote.remove(job.target)
                except FsError:
                    pass
                cleanup = job.extra.get("cleanup_local")
                if cleanup:
                    try:
                        os.remove(cleanup)
                    except OSError:
                        pass
        elif job.after == AFTER_EXTRACT_LOCAL:
            try:
                with tarfile.open(job.target) as tar:
                    tar.extractall(job.extra["dest"], filter="data")
            finally:
                try:
                    os.remove(job.target)
                except OSError:
                    pass
                cleanup = job.extra.get("cleanup_remote")
                if cleanup:
                    try:
                        self.remote.remove(cleanup)
                    except FsError:
                        pass

    def _cleanup_cancelled(self, job: TransferJob) -> None:
        """Remove a half-written target, but only one this job created."""
        if not job.extra.get("created"):
            return
        # The server may still hold the aborted file open for a moment (it
        # closes it when the torn-down channel is reaped), and Windows refuses
        # to delete open files: retry for a few seconds (this runs in the
        # transfer thread) instead of leaving it behind.
        for delay in (0.1, 0.2, 0.3, 0.4, 0.5, 0.5, 1.0, 1.0, 1.0, 1.0, 0.0):
            try:
                if job.kind == DOWNLOAD:
                    if os.path.exists(job.target):
                        os.remove(job.target)
                elif job.kind in (UPLOAD, URL_CLIENT):
                    if self.remote.stat(job.target) is not None:
                        self.remote.remove(job.target)
                return
            except Exception:
                time.sleep(delay)


class _Skip(Exception):
    """Internal: the conflict decision was 'skip'."""


def export_log_csv(entries: list[LogEntry], path: str,
                   hosts: Optional[list[str]] = None) -> None:
    """hosts: one host name per entry (adds a "host" column)."""
    import csv
    from datetime import datetime
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        head = ["time", "kind", "source", "target", "bytes", "seconds", "result", "message"]
        writer.writerow((["host"] if hosts is not None else []) + head)
        for i, e in enumerate(entries):
            row = [
                datetime.fromtimestamp(e.time).isoformat(sep=" ", timespec="seconds"),
                e.kind, e.source, e.target, e.size, f"{e.duration:.1f}", e.result, e.message,
            ]
            writer.writerow(([hosts[i]] if hosts is not None else []) + row)
