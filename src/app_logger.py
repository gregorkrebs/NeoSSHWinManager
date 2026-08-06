"""
app_logger.py – Global in-memory logger for NEO SSH-Win Manager.

IMPORTANT: log_emitter is created lazily AFTER QApplication exists.
Call init_logger() once after QApplication is created.
"""

import logging
from collections import deque

# In-memory ring buffer — last 2000 lines
_LOG_BUFFER: deque = deque(maxlen=2000)

# Lazy signal emitter (set by init_logger)
log_emitter = None


class _BufferingHandler(logging.Handler):
    """Stores records in buffer and optionally emits Qt signal."""

    def emit(self, record: logging.LogRecord):
        try:
            line = self.format(record)
            _LOG_BUFFER.append(line)
            if log_emitter is not None:
                log_emitter.new_record.emit(line)
        except Exception:
            pass


def get_all_logs() -> list:
    return list(_LOG_BUFFER)


def init_logger():
    """Call ONCE after QApplication is created to enable Qt signals."""
    global log_emitter
    from PyQt6.QtCore import QObject, pyqtSignal

    class _SignalEmitter(QObject):
        new_record = pyqtSignal(str)

    log_emitter = _SignalEmitter()


# ── Configure handler (no QObject at import time) ────────────────────────────

_handler = _BufferingHandler()
_handler.setFormatter(logging.Formatter(
    fmt="%(asctime)s  [%(levelname)-8s]  %(name)s — %(message)s",
    datefmt="%H:%M:%S"
))

logger = logging.getLogger("SSHWinManager")
logger.setLevel(logging.DEBUG)
logger.addHandler(_handler)
logger.propagate = False
