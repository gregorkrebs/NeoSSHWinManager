"""
debug_window.py – Live log viewer dialog for SSH Win Manager.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QCheckBox, QFileDialog, QWidget, QFrame
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont

import src.app_logger as _app_logger
from src.auth_manager import Session, UserConnectionManager
from src.i18n import tr
from src.sshfs_controller import SSHFSController


def _emitter():
    """Return the live log_emitter, or None if not yet initialised."""
    return _app_logger.log_emitter


class DebugWindow(QDialog):
    """Floating live log viewer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("debugSurface")
        self.setWindowTitle(tr("debug.title"))
        self.setMinimumSize(700, 480)
        self.resize(860, 560)
        self.setModal(False)
        self._auto_scroll = True
        self._build_ui()
        self._load_history()

        em = _emitter()
        if em is not None:
            em.new_record.connect(self._on_new_record)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._build_toolbar())

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Consolas", 10))
        self._log_view.setObjectName("debugLogView")
        layout.addWidget(self._log_view, stretch=1)

    def _build_toolbar(self) -> QWidget:
        tb = QFrame()
        tb.setObjectName("debugToolbar")
        h = QHBoxLayout(tb)
        h.setContentsMargins(18, 16, 18, 16)
        h.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        dot = QLabel("●")
        dot.setObjectName("statusDot")
        title = QLabel(tr("debug.live_log"))
        title.setObjectName("debugTitle")
        title_row.addWidget(dot)
        title_row.addWidget(title)
        title_row.addStretch()
        title_col.addLayout(title_row)

        subtitle = QLabel(tr("debug.subtitle"))
        subtitle.setToolTip(tr("debug.subtitle.tooltip"))
        subtitle.setObjectName("debugMeta")
        title_col.addWidget(subtitle)

        h.addLayout(title_col)
        h.addStretch()

        self._auto_scroll_cb = QCheckBox(tr("debug.auto_scroll"))
        self._auto_scroll_cb.setObjectName("debugCheck")
        self._auto_scroll_cb.setChecked(True)
        self._auto_scroll_cb.toggled.connect(
            lambda v: setattr(self, "_auto_scroll", v)
        )
        h.addWidget(self._auto_scroll_cb)

        for label, slot, btn_type in [
            (tr("debug.purge_mounts"), self._purge_mounts, "danger"),
            (tr("debug.test_decryption"), self._test_decryption, "warning"), # simplified label for space
            (tr("debug.clear"),    self._clear,     "secondary"),
            (tr("debug.save_log"), self._save_log,  "primary"),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("actionBtn")
            if btn_type != "secondary":
                btn.setProperty("btn_type", btn_type)
            btn.setFixedSize(90 if len(label) < 10 else 110, 32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            h.addWidget(btn)

        return tb

    # ------------------------------------------------------------------
    # Log rendering
    # ------------------------------------------------------------------

    def _load_history(self):
        for line in _app_logger.get_all_logs():
            self._render_line(line)
        self._scroll_to_bottom()

    @pyqtSlot(str)
    def _on_new_record(self, line: str):
        self._render_line(line)
        if self._auto_scroll:
            self._scroll_to_bottom()

    def _render_line(self, line: str):
        color = "#c8d6e5"
        lu = line.upper()
        if "[WARNING" in lu:
            color = "#f59e0b"
        elif "[ERROR" in lu:
            color = "#ef4444"
        elif "[CRITICAL" in lu:
            color = "#ff00cc"
        elif "[DEBUG" in lu:
            color = "#4a5a6a"

        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._log_view.append(
            f'<span style="color:{color}; font-family:Consolas,monospace;">{safe}</span>'
        )

    def _scroll_to_bottom(self):
        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def append_log(self, text: str) -> None:
        """Append text directly to the log view (public API for external callers)."""
        self._render_line(text)
        if self._auto_scroll:
            self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _clear(self):
        self._log_view.clear()

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("debug.save_log"), "sshwinmanager_debug.log",
            "Log Files (*.log);;All Files (*)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._log_view.toPlainText())

    def _purge_mounts(self):
        from src.app_logger import logger
        logger.warning(tr("debug.purge_mounts.started"))
        ok = SSHFSController().purge_all_stale_mounts()
        if ok:
            logger.info(tr("debug.purge_mounts.successful"))
        else:
            logger.error(tr("debug.purge_mounts.failed"))

    def _test_decryption(self):
        from src.app_logger import logger
        logger.info(tr("debug.test.starting"))
        user = Session.current()
        if not user:
            logger.error(tr("debug.test.no_user"))
            return

        mgr = UserConnectionManager(user)
        conns = mgr.get_all()
        logger.info(f"Test {len(conns)} Hosts...")
        for c in conns:
            if c.password:
                logger.info(f"✓ {c.name}: {tr('debug.password.decryption.successful')}")
            else:
                logger.warning(f"⚠ {c.name}: {tr('debug.password.empty.or.decryption.failed')}")
        logger.info(tr("debug.test.completed"))

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        em = _emitter()
        if em is not None:
            try:
                em.new_record.disconnect(self._on_new_record)
            except Exception:
                pass
        super().closeEvent(event)
