"""
threads.py – Glue between Python worker threads and the Qt main thread.

MainThreadInvoker  lets a worker thread run a function on the main thread and
                   wait for its result (used to show a conflict dialog from a
                   transfer thread).
TaskRunner         runs a function in a worker thread and delivers the result
                   or the exception to callbacks on the main thread.

Both rely on a QObject living in the main thread whose signal is emitted from
the worker thread; Qt queues such emissions to the receiver's thread. Unlike
QTimer.singleShot this works from plain Python threads without an event loop.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal

from src.app_logger import logger


class _Box:
    __slots__ = ("fn", "result", "error", "event")

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.fn = fn
        self.result: Any = None
        self.error: Optional[BaseException] = None
        self.event = threading.Event()


class MainThreadInvoker(QObject):
    """Run callables on the thread this object lives in (the main thread)."""

    _request = pyqtSignal(object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._request.connect(self._execute, Qt.ConnectionType.QueuedConnection)
        self._closed = False

    def _execute(self, box: _Box) -> None:
        try:
            box.result = box.fn()
        except BaseException as e:          # re-raised in the calling thread
            box.error = e
        finally:
            box.event.set()

    def call(self, fn: Callable[[], Any], default: Any = None) -> Any:
        """Run fn on the main thread and return its result (blocking)."""
        if QThread.currentThread() is self.thread():
            return fn()
        if self._closed:
            return default
        box = _Box(fn)
        self._request.emit(box)
        while not box.event.wait(0.25):
            if self._closed:
                return default
        if box.error is not None:
            raise box.error
        return box.result

    def close(self) -> None:
        """Unblock waiting threads; later calls return their default."""
        self._closed = True


class TaskRunner(QObject):
    """Run work off the UI thread; callbacks fire on the main thread."""

    _finished = pyqtSignal(object, object, object, object)   # on_done, on_error, result, error

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)
        self._alive = True

    def run(
        self,
        fn: Callable[[], Any],
        on_done: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[BaseException], None]] = None,
    ) -> None:
        def _work() -> None:
            result, error = None, None
            try:
                result = fn()
            except BaseException as e:
                error = e
            if self._alive:
                self._finished.emit(on_done, on_error, result, error)

        threading.Thread(target=_work, daemon=True, name="fb-task").start()

    def _deliver(self, on_done, on_error, result, error) -> None:
        if not self._alive:
            return
        try:
            if error is not None:
                if on_error:
                    on_error(error)
                else:
                    logger.warning("filebrowser task failed: %s", error)
            elif on_done:
                on_done(result)
        except RuntimeError as e:
            # Widget deleted while the task ran (window closed): nothing to update.
            logger.debug("filebrowser task callback skipped: %s", e)

    def shutdown(self) -> None:
        self._alive = False
