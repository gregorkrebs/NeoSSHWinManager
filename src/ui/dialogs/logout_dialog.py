"""logout_dialog.py – Logout options dialog for NEO SSH-Win Manager."""

from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
from PyQt6.QtCore import Qt

from src.ui.frameless_dialog import FramelessDialog
from src.i18n import tr


class LogoutConfirmDialog(FramelessDialog):
    """
    Logout confirmation dialog with three options:
      - Stay logged in  (cancel)
      - Quit only, keep hosts mounted
      - Quit and unmount all hosts

    Returns via ask():
        "cancel"  – stay logged in
        "quit"    – quit, but leave hosts mounted
        "logout"  – quit and unmount all hosts
    """

    @classmethod
    def ask(cls, parent) -> str:
        dlg = cls(parent)
        code = dlg.exec()
        if code == 2:
            return "logout"
        if code == 1:
            return "quit"
        return "cancel"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(tr("logout.title"))
        self.setMinimumWidth(420)
        self.setObjectName("dialogSurface")
        self._build_content()

    def _build_content(self):
        layout = QVBoxLayout(self._fdlg_content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Header row: icon + text
        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        icon_lbl = QLabel("🚪")
        icon_lbl.setStyleSheet(
            "font-size: 36px; background: transparent; margin-right: 6px;"
        )
        icon_lbl.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        )
        content_row.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)

        title_lbl = QLabel(tr("logout.title"))
        title_lbl.setObjectName("msgTitle")
        text_col.addWidget(title_lbl)

        msg_lbl = QLabel(tr("logout.dialog_text"))
        msg_lbl.setObjectName("msgText")
        msg_lbl.setWordWrap(True)
        text_col.addWidget(msg_lbl)

        content_row.addLayout(text_col, stretch=1)
        layout.addLayout(content_row)

        # Divider
        div = QFrame()
        div.setObjectName("divider")
        div.setFixedHeight(1)
        layout.addWidget(div)

        # Buttons – stacked vertically for clarity
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)

        # Option 1: Stay logged in (cancel)
        stay_btn = QPushButton(tr("logout.stay"))
        stay_btn.setObjectName("secondaryBtn")
        stay_btn.setMinimumHeight(36)
        stay_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stay_btn.clicked.connect(self.reject)
        btn_layout.addWidget(stay_btn)

        # Option 2: Quit but keep hosts mounted
        quit_only_btn = QPushButton(tr("logout.quit_only"))
        quit_only_btn.setObjectName("primaryBtn")
        quit_only_btn.setMinimumHeight(36)
        quit_only_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        quit_only_btn.clicked.connect(lambda: self.done(1))
        btn_layout.addWidget(quit_only_btn)

        # Option 3: Quit and unmount all
        logout_btn = QPushButton(tr("logout.quit_unmount"))
        logout_btn.setObjectName("dangerBtn")
        logout_btn.setMinimumHeight(36)
        logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        logout_btn.clicked.connect(lambda: self.done(2))
        btn_layout.addWidget(logout_btn)

        layout.addLayout(btn_layout)
