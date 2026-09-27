from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QWidget
from PyQt6.QtCore import Qt
from src.ui.dialog_utils import match_parent_height
from src.i18n import tr

class TelemetryPromptDialog(QDialog):
    """
    Zeigt den Opt-In Dialog für die Telemetrie "Volkszählung" beim ersten Start.
    Gibt Accepted (Erlaubt) oder Rejected (Abgelehnt) zurück.

    Der Text zählt auf, was src/telemetry.py tatsächlich sendet – bei neuen
    Angaben dort muss er mitwachsen.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dialogSurface")
        self.setWindowTitle(tr("telemetry.prompt.window_title"))
        self.setMinimumWidth(500)
        self.setModal(True)
        self._build_ui()
        match_parent_height(self, parent)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("dialogHeroCard")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(22, 20, 22, 20)
        hero_l.setSpacing(8)

        title = QLabel(tr("telemetry.prompt.title"))
        title.setObjectName("dialogTitle")
        title.setWordWrap(True)
        hero_l.addWidget(title)

        lead = QLabel(tr("telemetry.prompt.body"))
        lead.setObjectName("dialogLead")
        lead.setWordWrap(True)
        hero_l.addWidget(lead)
        outer.addWidget(hero)

        outer.addStretch()

        # Buttons
        btn_bar = QWidget()
        btn_bar.setObjectName("dialogBtnBar")
        btn_bar_layout = QHBoxLayout(btn_bar)
        btn_bar_layout.setContentsMargins(0, 10, 0, 0)
        btn_bar_layout.setSpacing(10)

        decline_btn = QPushButton(tr("telemetry.prompt.decline"))
        decline_btn.setObjectName("secondaryBtn")
        decline_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        decline_btn.clicked.connect(self.reject)

        accept_btn = QPushButton(tr("telemetry.prompt.accept"))
        accept_btn.setObjectName("primaryBtn")
        accept_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        accept_btn.clicked.connect(self.accept)

        btn_bar_layout.addStretch()
        btn_bar_layout.addWidget(decline_btn)
        btn_bar_layout.addWidget(accept_btn)

        outer.addWidget(btn_bar)
