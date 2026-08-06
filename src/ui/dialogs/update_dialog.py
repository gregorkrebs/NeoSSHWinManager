import webbrowser
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget, QProgressBar, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from src.ui.dialog_utils import match_parent_height
from src.ui.frameless_dialog import FramelessDialog
from src.ui.widgets.no_wheel import NoWheelScrollArea
from src.i18n import tr

class UpdateDialog(FramelessDialog):
    """
    Shows an available update and manages the installer download.

    The installer is never run while the app is up: it is downloaded once and
    armed for the next program start (see src/updater.py). Two states:
      * not downloaded yet  → "download" button
      * downloaded/armed    → checkbox for the next start + "install now"
    """

    start_background_download = pyqtSignal()
    # Checkbox "install at next program start" was toggled.
    schedule_changed = pyqtSignal(bool)
    # User wants to restart into the installer right away.
    install_now = pyqtSignal()
    # User left the app and downloads from the release page instead.
    browser_opened = pyqtSignal()

    def __init__(self, parent=None, version: str = "", changelog: str = "",
                 download_url: str = "", obj_type: str = "installer",
                 already_downloaded: bool = False, armed: bool = True):
        super().__init__(parent)
        self.version = version
        self.changelog = changelog
        self.download_url = download_url
        self.obj_type = obj_type
        self._downloaded = already_downloaded
        self._armed = armed

        self.setObjectName("dialogSurface")
        self.setWindowTitle(tr("update.window_title"))
        self.setMinimumWidth(550)
        self.setMinimumHeight(450)
        self.setModal(True)
        self._build_ui()
        match_parent_height(self, parent)

    def _build_ui(self):
        outer = QVBoxLayout(self._fdlg_content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Hero
        hero = QFrame()
        hero.setObjectName("dialogHeroCard")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(22, 20, 22, 20)
        hero_l.setSpacing(8)

        title = QLabel(tr("update.title", version=self.version))
        title.setObjectName("dialogTitle")
        hero_l.addWidget(title)

        self.lead = QLabel(tr("update.ready_lead") if self._downloaded else tr("update.lead"))
        self.lead.setObjectName("dialogLead")
        self.lead.setWordWrap(True)
        hero_l.addWidget(self.lead)
        outer.addWidget(hero)

        # Details / Changelog
        scroll = NoWheelScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner_l = QVBoxLayout(inner)
        inner_l.setContentsMargins(22, 20, 22, 20)

        changelog_lbl = QLabel(self.changelog)
        changelog_lbl.setObjectName("fieldLabel")
        changelog_lbl.setWordWrap(True)
        changelog_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        inner_l.addWidget(changelog_lbl)
        inner_l.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll, stretch=1)

        # "Install at next start" – only meaningful once the installer is here
        opt_row = QWidget()
        opt_l = QVBoxLayout(opt_row)
        opt_l.setContentsMargins(22, 12, 22, 0)
        opt_l.setSpacing(4)

        self.schedule_cb = QCheckBox(tr("update.install_next_start"))
        self.schedule_cb.setChecked(self._armed)
        self.schedule_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.schedule_cb.toggled.connect(self._on_schedule_toggled)
        opt_l.addWidget(self.schedule_cb)

        self.schedule_hint = QLabel(tr("update.install_next_start.hint"))
        self.schedule_hint.setObjectName("hintLabel")
        self.schedule_hint.setWordWrap(True)
        opt_l.addWidget(self.schedule_hint)

        opt_row.setVisible(self._downloaded)
        self._opt_row = opt_row
        outer.addWidget(opt_row)

        # Progress (hidden initially)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(4)

        outer.addWidget(self.progress_bar)

        # Bottom Buttons
        btn_bar = QWidget()
        btn_bar.setObjectName("dialogBtnBar")
        btn_bar_layout = QHBoxLayout(btn_bar)
        btn_bar_layout.setContentsMargins(20, 16, 20, 16)
        btn_bar_layout.setSpacing(10)

        cancel_btn = QPushButton(tr("update.btn.later"))
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        self.browser_btn = QPushButton(tr("update.btn.browser"))
        self.browser_btn.setObjectName("secondaryBtn")
        self.browser_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browser_btn.clicked.connect(self._open_browser)

        self.install_btn = QPushButton(
            tr("update.btn.install_now") if self._downloaded else tr("update.btn.download")
        )
        self.install_btn.setObjectName("primaryBtn")
        self.install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_btn.clicked.connect(self._on_primary_clicked)

        btn_bar_layout.addStretch()
        btn_bar_layout.addWidget(cancel_btn)
        if self.download_url:
            btn_bar_layout.addWidget(self.browser_btn)

        if self.obj_type != "browser":
            btn_bar_layout.addWidget(self.install_btn)

        outer.addWidget(btn_bar)

    def _open_browser(self):
        if self.download_url:
            webbrowser.open(self.download_url)
            self.browser_opened.emit()
        self.accept()

    def _on_schedule_toggled(self, checked: bool):
        self._armed = checked
        self.schedule_changed.emit(checked)

    def _on_primary_clicked(self):
        if self._downloaded:
            self._restart_and_install()
        else:
            self._start_download()

    def _start_download(self):
        self.install_btn.setEnabled(False)
        self.install_btn.setText(tr("update.btn.downloading"))
        self.browser_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.start_background_download.emit()

    def _restart_and_install(self):
        self.install_btn.setEnabled(False)
        self.install_btn.setText(tr("update.btn.installing"))
        self.install_now.emit()
        self.accept()

    def update_progress(self, percent: int):
        self.progress_bar.setValue(percent)

    def on_download_finished(self, success: bool, msg: str):
        if success:
            self._downloaded = True
            self.progress_bar.setValue(100)
            self.progress_bar.setVisible(False)
            self.lead.setText(tr("update.downloaded_lead"))
            self._opt_row.setVisible(True)
            self.schedule_cb.setChecked(self._armed)
            self.browser_btn.setEnabled(True)
            self.install_btn.setEnabled(True)
            self.install_btn.setText(tr("update.btn.install_now"))
        else:
            self.install_btn.setText(tr("update.btn.download_failed"))
            self.install_btn.setEnabled(True)
            self.browser_btn.setEnabled(True)
            self.progress_bar.setVisible(False)


def _wire(dlg: "UpdateDialog", updater, download_url: str = ""):
    """Connect a dialog to the updater: download, arming, restart-into-installer."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from src.telemetry import send_telemetry_async
    from src.updater import launch_pending_installer, set_install_on_next_start

    # Nur mit Einwilligung; send_telemetry_async prüft das selbst. Erfasst wird,
    # wofür der Nutzer sich entscheidet — nicht, wer er ist.
    target = dlg.version
    acted = {"any": False}

    def _report(choice: str):
        acted["any"] = True
        send_telemetry_async('update_action', choice=choice, target=target)

    if download_url:
        dlg.start_background_download.connect(lambda: updater.download_update_async(download_url))
        dlg.start_background_download.connect(lambda: _report('download'))
        updater.download_progress.connect(dlg.update_progress)
        updater.download_finished.connect(dlg.on_download_finished)
        updater.download_finished.connect(
            lambda ok, _msg: send_telemetry_async(
                'update_download', result='ok' if ok else 'failed', target=target
            )
        )

    dlg.schedule_changed.connect(set_install_on_next_start)
    dlg.schedule_changed.connect(lambda on: _report('schedule_on' if on else 'schedule_off'))
    dlg.browser_opened.connect(lambda: _report('browser'))

    def _dismissed():
        # accept() gibt es nur bei "sofort installieren" und "im Browser
        # öffnen" — ein rejected ohne vorherige Aktion ist also ein echtes
        # "Später". Wer erst herunterlädt und dann zumacht, zählt nicht doppelt.
        if not acted["any"]:
            _report('later')

    dlg.rejected.connect(_dismissed)

    def _shutdown():
        # Prefer the app's own shutdown (stops the IPC bridge); mounts stay up,
        # exactly like a normal "quit" — they are separate sshfs processes.
        for w in QApplication.topLevelWidgets():
            if hasattr(w, "quit_app"):
                w.quit_app(unmount=False)
                return
        QApplication.instance().quit()

    def _install_now():
        record = updater.pending_update()
        if record and launch_pending_installer(record, from_version=updater.current_version):
            # Kurz auf den Versand warten: gleich beendet sich die App, und der
            # Sende-Thread ist ein Daemon — sonst ginge genau dieses Ereignis
            # regelmäßig verloren.
            acted["any"] = True
            send_telemetry_async('update_action', choice='install_now',
                                 target=target, wait=1.5)
            # The helper waits for this process to exit before starting Setup.
            QTimer.singleShot(200, _shutdown)

    dlg.install_now.connect(_install_now)


def run_update_dialog(parent, updater, version: str, changelog: str,
                      download_url: str, obj_type: str):
    """Modal update dialog for a version reported by the GitHub check."""
    pending = updater.pending_update()
    already = bool(pending) and str(pending.get("version", "")) == version
    armed = bool(pending.get("install_on_next_start")) if already else True

    dlg = UpdateDialog(parent, version, changelog, download_url, obj_type,
                       already_downloaded=already, armed=armed)
    _wire(dlg, updater, download_url)
    dlg.exec()


def run_pending_update_dialog(parent, updater) -> bool:
    """
    Modal dialog for an installer that is already on disk (used when the
    GitHub check found nothing new or failed). Returns False if none exists.
    """
    record = updater.pending_update()
    if not record:
        return False

    dlg = UpdateDialog(parent, str(record.get("version", "")),
                       str(record.get("changelog", "")), "", "installer",
                       already_downloaded=True,
                       armed=bool(record.get("install_on_next_start")))
    _wire(dlg, updater)
    dlg.exec()
    return True
