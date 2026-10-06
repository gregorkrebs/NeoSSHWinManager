"""
styled_message_box.py – Custom message box and input dialog with the app's frameless titlebar.
"""
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog, QLineEdit
from PyQt6.QtCore import Qt

from src.ui.frameless_dialog import FramelessDialog
from src.i18n import tr


class StyledMessageBox(FramelessDialog):

    @classmethod
    def information(cls, parent, title: str, text: str):
        dlg = cls(parent, title, text, "info")
        dlg.exec()

    @classmethod
    def warning(cls, parent, title: str, text: str):
        dlg = cls(parent, title, text, "warning")
        dlg.exec()

    @classmethod
    def critical(cls, parent, title: str, text: str):
        dlg = cls(parent, title, text, "error")
        dlg.exec()

    @classmethod
    def question(cls, parent, title: str, text: str,
                 yes_text: str | None = None, no_text: str | None = None,
                 destructive: bool = False) -> bool:
        """Ask a yes/no question. *destructive* shows the confirm button in red."""
        dlg = cls(parent, title, text, "question",
                  yes_text=yes_text, no_text=no_text, destructive=destructive)
        return dlg.exec() == QDialog.DialogCode.Accepted

    def __init__(self, parent, title: str, text: str, mode: str = "info",
                 yes_text: str | None = None, no_text: str | None = None,
                 destructive: bool = False):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.setObjectName("dialogSurface")
        # Defaults are resolved here, not in the signature: the language is
        # only known at runtime.
        self._build_content(title, text, mode,
                            yes_text or tr("dialog.yes"), no_text or tr("dialog.no"),
                            destructive)

    def _build_content(self, title: str, text: str, mode: str,
                       yes_text: str, no_text: str, destructive: bool):
        layout = QVBoxLayout(self._fdlg_content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Content row: icon + text
        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        from src.ui.dialog_utils import MESSAGE_ICONS, dialog_icon, message_color
        kind = mode if mode in MESSAGE_ICONS else "info"
        icon_lbl = dialog_icon(MESSAGE_ICONS[kind], message_color(kind, self._fdlg_theme))
        content_row.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("msgTitle")
        text_col.addWidget(title_lbl)

        msg_lbl = QLabel(text)
        msg_lbl.setObjectName("msgText")
        msg_lbl.setWordWrap(True)
        msg_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        text_col.addWidget(msg_lbl)

        content_row.addLayout(text_col, stretch=1)
        layout.addLayout(content_row)
        layout.addSpacing(4)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        if mode == "question":
            no_btn = QPushButton(no_text)
            no_btn.setObjectName("secondaryBtn")
            no_btn.setMinimumHeight(32)
            no_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            no_btn.clicked.connect(self.reject)
            btn_row.addWidget(no_btn)

            yes_btn = QPushButton(yes_text)
            yes_btn.setObjectName("dangerBtn" if destructive else "primaryBtn")
            yes_btn.setMinimumHeight(32)
            yes_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            yes_btn.clicked.connect(self.accept)
            btn_row.addWidget(yes_btn)
        else:
            ok_btn = QPushButton(tr("dialog.ok"))
            ok_btn.setObjectName("primaryBtn")
            ok_btn.setMinimumHeight(32)
            ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            ok_btn.clicked.connect(self.accept)
            btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)


class StyledInputDialog(FramelessDialog):
    """Single-line text input dialog matching the app's frameless design."""

    @classmethod
    def get_text(cls, parent, title: str, label: str, text: str = "") -> tuple[str, bool]:
        """Show dialog, return (entered_text, accepted)."""
        dlg = cls(parent, title, label, text)
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        return (dlg._input.text().strip(), accepted)

    def __init__(self, parent, title: str, label: str, text: str = ""):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.setObjectName("dialogSurface")
        self._build_content(title, label, text)

    def _build_content(self, title: str, label: str, text: str):
        layout = QVBoxLayout(self._fdlg_content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        lbl = QLabel(label)
        lbl.setObjectName("msgText")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self._input = QLineEdit(text)
        self._input.setObjectName("formInput")
        self._input.setMinimumHeight(34)
        self._input.selectAll()
        self._input.returnPressed.connect(self.accept)
        layout.addWidget(self._input)

        layout.addSpacing(4)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton(tr("dialog.cancel"))
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.setMinimumHeight(32)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton(tr("dialog.ok"))
        ok_btn.setObjectName("primaryBtn")
        ok_btn.setMinimumHeight(32)
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)
        self._input.setFocus()
