"""The host-key question of the embedded terminal (first contact with a host).

TerminalConnectWorker runs bridge_server.create_session_token() in its own
thread, so the question for an unknown host key comes from that thread. It
has to appear on the main thread and its answer has to reach the worker. It
used to be scheduled with QTimer.singleShot() from the worker, never ran, and
every newly added host failed after 30 s with "check host, credentials and
network".
"""
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import QThread  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from src.filebrowser.threads import MainThreadInvoker  # noqa: E402
from src.ui import main_window as mw  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _window():
    window = QWidget()
    window._terminal_invoker = MainThreadInvoker(window)
    return window


def _ask_from_worker(qapp, window, answer, monkeypatch):
    """Ask from a worker thread while the main thread runs its event loop."""
    asked_on_main = []

    def fake_exec(dlg):
        asked_on_main.append(QThread.currentThread() is qapp.thread())
        return answer
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    result = []
    worker = threading.Thread(target=lambda: result.append(
        mw.MainWindow._terminal_tofu_callback(window, "new.example.com", 22, "SHA256:abc")))
    worker.start()
    deadline = time.monotonic() + 10
    while worker.is_alive() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    window._terminal_invoker.close()
    worker.join(5)
    return asked_on_main, result


def test_unknown_host_key_is_asked_on_the_main_thread(qapp, monkeypatch):
    asked_on_main, result = _ask_from_worker(
        qapp, _window(), QMessageBox.StandardButton.Yes, monkeypatch)
    assert asked_on_main == [True]
    assert result == [True]


def test_rejected_host_key_refuses_the_connection(qapp, monkeypatch):
    asked_on_main, result = _ask_from_worker(
        qapp, _window(), QMessageBox.StandardButton.No, monkeypatch)
    assert asked_on_main == [True]
    assert result == [False]


def test_quitting_releases_a_worker_waiting_for_the_answer(qapp):
    window = _window()
    result = []
    worker = threading.Thread(target=lambda: result.append(
        mw.MainWindow._terminal_tofu_callback(window, "new.example.com", 22, "SHA256:abc")))
    worker.start()                      # the main thread never gets to ask
    time.sleep(0.3)
    window._terminal_invoker.close()    # what quit_app() does
    worker.join(5)
    assert not worker.is_alive()
    assert result == [False]
