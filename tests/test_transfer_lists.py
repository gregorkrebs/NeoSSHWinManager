"""
tests/test_transfer_lists.py – The file browser's three transfer lists
(to do / failed / successful), as in FileZilla.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.filebrowser.transfers import (  # noqa: E402
    CANCELLED, DONE, FAILED, PAUSED, QUEUED, RUNNING, SKIPPED, UPLOAD, TransferJob,
)
from src.filebrowser.ui import style  # noqa: E402
from src.filebrowser.ui.transfer_panel import (  # noqa: E402
    C_HOST, C_TIME, DONE_LIST, FAILED_LIST, PENDING, TransferPanel, list_for,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _FakeQueue(QObject):
    job_added = pyqtSignal(object)
    job_changed = pyqtSignal(object)
    jobs_removed = pyqtSignal(list)
    log_added = pyqtSignal(object)
    activity_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.jobs = {}
        self.calls = []

    def add(self, job):
        self.jobs[job.id] = job
        self.job_added.emit(job)

    def set_state(self, job, state):
        job.state = state
        job.ended = 1_700_000_000.0 if state in (DONE, FAILED, CANCELLED, SKIPPED) else 0.0
        self.job_changed.emit(job)

    def __getattr__(self, name):          # retry / remove / pause / ... are recorded
        if name in ("retry", "remove", "pause", "resume", "cancel"):
            return lambda ids: self.calls.append((name, list(ids)))
        raise AttributeError(name)


def _job(jid, state=QUEUED):
    return TransferJob(id=10_000 + jid, kind=UPLOAD, source=f"C:/f{jid}.txt",
                       target=f"/srv/f{jid}.txt", size=100, state=state)


def _rows(panel, name):
    tree = panel.lists[name].tree
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def test_states_map_to_lists():
    assert [list_for(s) for s in (QUEUED, RUNNING, PAUSED)] == [PENDING] * 3
    assert [list_for(s) for s in (FAILED, CANCELLED)] == [FAILED_LIST] * 2
    assert [list_for(s) for s in (DONE, SKIPPED)] == [DONE_LIST] * 2


def test_jobs_move_between_lists_with_their_state(app):
    panel = TransferPanel(style.DARK)
    q = _FakeQueue()
    panel.add_queue(q, "Web")
    a, b, c = _job(1), _job(2), _job(3)
    for job in (a, b, c):
        q.add(job)
    assert _rows(panel, PENDING) == ["f1.txt", "f2.txt", "f3.txt"]

    q.set_state(a, RUNNING)
    q.set_state(a, DONE)
    q.set_state(b, FAILED)
    q.set_state(c, DONE)
    assert _rows(panel, PENDING) == []
    assert _rows(panel, FAILED_LIST) == ["f2.txt"]
    assert _rows(panel, DONE_LIST) == ["f3.txt", "f1.txt"]          # newest first
    done = panel.lists[DONE_LIST].tree.topLevelItem(0)
    assert done.text(C_HOST) == "Web" and done.text(C_TIME)

    # Tab titles carry the counts; the failed tab gets a warning icon.
    titles = [panel.tabText(i) for i in range(3)]
    assert "(" not in titles[0]
    assert titles[1].endswith("(1)") and titles[2].endswith("(2)")
    assert not panel.tabIcon(1).isNull() and panel.tabIcon(0).isNull()

    # Retrying puts the job back into the list of transfers to do.
    q.set_state(b, QUEUED)
    assert _rows(panel, FAILED_LIST) == [] and _rows(panel, PENDING) == ["f2.txt"]
    assert panel.tabIcon(1).isNull()

    q.jobs_removed.emit([a.id, c.id])
    assert _rows(panel, DONE_LIST) == []


def test_list_buttons_act_on_their_rows(app):
    panel = TransferPanel(style.DARK)
    q = _FakeQueue()
    panel.add_queue(q, "Web")
    a, b = _job(4), _job(5)
    q.add(a)
    q.add(b)
    q.set_state(a, FAILED)
    q.set_state(b, CANCELLED)
    failed = panel.lists[FAILED_LIST]
    assert not failed._buttons["retry"].isEnabled()      # nothing selected
    assert failed._buttons["retry_all"].isEnabled()
    failed._buttons["retry_all"].click()
    assert q.calls[-1] == ("retry", [b.id, a.id])
    failed.tree.topLevelItem(0).setSelected(True)
    assert failed._buttons["remove"].isEnabled()
    failed._buttons["remove"].click()
    assert q.calls[-1] == ("remove", [b.id])
    failed._buttons["all"].click()
    assert q.calls[-1] == ("remove", [b.id, a.id])
