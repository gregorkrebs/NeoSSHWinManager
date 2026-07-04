"""
settings_dialog.py – Settings dialog for NEO SSH-Win Manager.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QRadioButton,
    QPushButton, QSpinBox, QFrame, QWidget, QLineEdit, QButtonGroup,
    QFileDialog, QMessageBox, QScrollArea, QApplication, QComboBox
)
from PyQt6.QtCore import Qt
from src.config import AppSettings
from src.sshfs_controller import SSHFSController
from src.ui.dialogs.styled_message_box import StyledMessageBox
from src.ui.dialog_utils import match_parent_height, make_maximize_button
from src.ui.widgets.no_wheel import NoWheelComboBox, NoWheelScrollArea, NoWheelSpinBox
from src.i18n import tr, available_languages


_LANG_LABELS = {"en": "English", "de": "Deutsch"}


class SettingsDialog(QDialog):

    def __init__(self, parent=None, settings: AppSettings = None):
        super().__init__(parent)
        self._settings = settings or AppSettings()
        self.setObjectName("dialogSurface")
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(520)
        self.setModal(True)
        self._build_ui()
        self._load_settings()
        screen = QApplication.primaryScreen()
        if screen:
            self.setMaximumHeight(int(screen.availableGeometry().height() * 0.95))
        match_parent_height(self, parent)

    # ── Layout primitives ─────────────────────────────────────────────

    def _section_header(self, title: str) -> QLabel:
        """Floating section title above each group card."""
        lbl = QLabel(title)
        lbl.setObjectName("sectionLabel")
        return lbl

    def _section(self, title: str) -> QLabel:
        return self._section_header(title)

    def _hint(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("hintLabel")
        lbl.setWordWrap(True)
        return lbl

    def _divider(self) -> QFrame:
        """Used only for the bottom button bar separator."""
        f = QFrame()
        f.setObjectName("divider")
        f.setFixedHeight(1)
        return f

    def _inner_sep(self) -> QFrame:
        """Hairline separator between rows inside a group card."""
        f = QFrame()
        f.setObjectName("rowSep")
        f.setFixedHeight(1)
        return f

    def _make_group(self) -> tuple[QFrame, QVBoxLayout]:
        """Returns a styled group card + its content layout."""
        card = QFrame()
        card.setObjectName("settingsGroupCard")
        vl = QVBoxLayout(card)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        return card, vl

    def _row_combo(self, label_text: str, combo: QWidget) -> QWidget:
        """Label | Combo row — label fixed 160 px, combo directly next to it."""
        w = QWidget()
        w.setObjectName("settingsRow")
        hl = QHBoxLayout(w)
        hl.setContentsMargins(16, 11, 16, 11)
        hl.setSpacing(0)
        lbl = QLabel(label_text)
        lbl.setObjectName("rowLabel")
        hl.addWidget(lbl, stretch=1)
        hl.addWidget(combo)
        return w

    def _row_check(self, checkbox: QCheckBox, hint: str = "") -> QWidget:
        """Checkbox row with optional muted hint indented directly below."""
        w = QWidget()
        w.setObjectName("settingsRow")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(16, 11, 16, 11)
        vl.setSpacing(4)
        vl.addWidget(checkbox)
        if hint:
            hl = self._hint(hint)
            hl.setContentsMargins(24, 0, 0, 0)
            vl.addWidget(hl)
        return w

    def _row_radio(self, radio: "QRadioButton", hint: str = "") -> QWidget:
        """RadioButton row, same visual style as _row_check."""
        w = QWidget()
        w.setObjectName("settingsRow")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(16, 11, 16, 11)
        vl.setSpacing(4)
        vl.addWidget(radio)
        if hint:
            hl = self._hint(hint)
            hl.setContentsMargins(24, 0, 0, 0)
            vl.addWidget(hl)
        return w

    def _row_action(self, button: QPushButton, description: str) -> QWidget:
        """Button on far left, description text immediately to the right."""
        w = QWidget()
        w.setObjectName("settingsRow")
        hl = QHBoxLayout(w)
        hl.setContentsMargins(16, 11, 16, 11)
        hl.setSpacing(14)
        hl.addWidget(button)
        desc = self._hint(description)
        hl.addWidget(desc, stretch=1)
        return w

    def _row_path(self, label_text: str, line_edit: QLineEdit,
                  browse_btn: QPushButton, hint: str = "") -> QWidget:
        """Label + full-width path input + browse button, optional hint below."""
        w = QWidget()
        w.setObjectName("settingsRow")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(16, 11, 16, 11)
        vl.setSpacing(6)
        lbl = QLabel(label_text)
        lbl.setObjectName("rowLabel")
        vl.addWidget(lbl)
        hl = QHBoxLayout()
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        hl.addWidget(line_edit, stretch=1)
        hl.addWidget(browse_btn)
        vl.addLayout(hl)
        if hint:
            vl.addWidget(self._hint(hint))
        return w

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = NoWheelScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, stretch=1)

        inner = QWidget()
        scroll.setWidget(inner)
        root = QVBoxLayout(inner)
        root.setContentsMargins(20, 20, 20, 12)
        root.setSpacing(6)

        # ── Hero ──────────────────────────────────────────────────────
        hero = QFrame()
        hero.setObjectName("dialogHeroCard")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(22, 18, 22, 18)
        hero_l.setSpacing(4)
        title_lbl = QLabel(tr("settings.title"))
        title_lbl.setObjectName("dialogTitle")
        hero_l.addWidget(title_lbl)
        lead = QLabel(tr("dialog.lead.settings"))
        lead.setObjectName("dialogLead")
        lead.setWordWrap(True)
        hero_l.addWidget(lead)
        root.addWidget(hero)
        root.addSpacing(10)

        # ── APPEARANCE ────────────────────────────────────────────────
        root.addWidget(self._section_header("APPEARANCE"))
        root.addSpacing(4)

        self._lang_combo = NoWheelComboBox()
        self._lang_combo.setFixedWidth(180)
        for code in available_languages():
            self._lang_combo.addItem(_LANG_LABELS.get(code, code), code)

        self._theme_combo = NoWheelComboBox()
        self._theme_combo.setFixedWidth(180)
        self._theme_combo.addItem(tr("settings.theme.dark"), "dark")
        self._theme_combo.addItem(tr("settings.theme.light"), "light")

        app_card, app_vl = self._make_group()
        app_vl.addWidget(self._row_combo(tr("settings.language.label"), self._lang_combo))
        app_vl.addWidget(self._inner_sep())
        app_vl.addWidget(self._row_combo(tr("settings.theme.label"), self._theme_combo))
        hint_row = QWidget()
        hint_row.setObjectName("settingsRow")
        hint_hl = QHBoxLayout(hint_row)
        hint_hl.setContentsMargins(16, 6, 16, 8)
        hint_hl.addWidget(self._hint(tr("settings.language.restart")))
        app_vl.addWidget(hint_row)
        root.addWidget(app_card)
        root.addSpacing(14)

        # ── GENERAL ───────────────────────────────────────────────────
        root.addWidget(self._section_header(tr("settings.section.general")))
        root.addSpacing(4)

        self._start_with_windows = QCheckBox(tr("settings.start_with_windows"))
        self._minimize_to_tray = QCheckBox(tr("settings.minimize_to_tray"))
        self._require_admin = QCheckBox(tr("settings.require_admin"))
        self._telemetry_enabled = QCheckBox("Telemetrie erlauben")

        gen_card, gen_vl = self._make_group()
        gen_vl.addWidget(self._row_check(self._start_with_windows))
        gen_vl.addWidget(self._inner_sep())
        gen_vl.addWidget(self._row_check(self._minimize_to_tray))
        gen_vl.addWidget(self._inner_sep())
        gen_vl.addWidget(self._row_check(self._require_admin))
        gen_vl.addWidget(self._inner_sep())
        gen_vl.addWidget(self._row_check(
            self._telemetry_enabled,
            "Anonyme Nutzungsdaten helfen, das Programm zu verbessern. "
            "Es werden keine persönlichen Daten übertragen."
        ))
        root.addWidget(gen_card)
        root.addSpacing(14)

        # ── UPDATES ───────────────────────────────────────────────────
        root.addWidget(self._section_header("UPDATES"))
        root.addSpacing(4)

        self._update_btn = QPushButton("Auf Updates prüfen")
        self._update_btn.setObjectName("settingsActionBtn")
        self._update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_btn.setFixedWidth(340)
        self._update_btn.setMinimumHeight(32)
        self._update_btn.clicked.connect(self._on_check_updates)

        self._create_shortcut_btn = QPushButton(tr("settings.create_shortcut"))
        self._create_shortcut_btn.setObjectName("settingsActionBtn")
        self._create_shortcut_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._create_shortcut_btn.setFixedWidth(340)
        self._create_shortcut_btn.setMinimumHeight(32)
        self._create_shortcut_btn.clicked.connect(self._on_create_shortcut)

        upd_card, upd_vl = self._make_group()
        upd_vl.addWidget(self._row_action(
            self._update_btn, "Manuell nach neuen Versionen auf GitHub suchen"
        ))
        upd_vl.addWidget(self._inner_sep())
        upd_vl.addWidget(self._row_action(
            self._create_shortcut_btn, "Desktop-Verknüpfung direkt auf dem Desktop erstellen"
        ))
        root.addWidget(upd_card)
        root.addSpacing(14)

        # ── MOUNT STATUS ──────────────────────────────────────────────
        root.addWidget(self._section_header(tr("settings.section.mount")))
        root.addSpacing(4)

        self._interval_spin = NoWheelSpinBox()
        self._interval_spin.setRange(5, 300)
        self._interval_spin.setValue(30)
        self._interval_spin.setFixedWidth(72)
        self._auto_reconnect = QCheckBox(tr("settings.auto_reconnect"))
        self._auto_remount_on_lost = QCheckBox(tr("settings.auto_remount"))

        mnt_card, mnt_vl = self._make_group()
        mnt_vl.addWidget(self._row_combo(tr("settings.check_interval"), self._interval_spin))
        mnt_vl.addWidget(self._inner_sep())
        mnt_vl.addWidget(self._row_check(self._auto_reconnect))
        mnt_vl.addWidget(self._inner_sep())
        mnt_vl.addWidget(self._row_check(self._auto_remount_on_lost))
        root.addWidget(mnt_card)
        root.addSpacing(14)

        # ── SSH TERMINAL ──────────────────────────────────────────────
        root.addWidget(self._section_header(tr("settings.section.terminal")))
        root.addSpacing(4)

        self._term_ssh_radio = QRadioButton(tr("settings.terminal_client.ssh"))
        self._term_putty_radio = QRadioButton(tr("settings.terminal_client.putty"))
        self._term_xterm_radio = QRadioButton(tr("settings.terminal_client.xterm"))

        # Explicit group required because each radio is wrapped in its own row widget.
        self._term_group = QButtonGroup(self)
        self._term_group.addButton(self._term_ssh_radio)
        self._term_group.addButton(self._term_putty_radio)
        self._term_group.addButton(self._term_xterm_radio)
        self._term_group.buttonToggled.connect(self._on_terminal_client_toggled)

        self._putty_path_edit = QLineEdit()
        self._putty_path_edit.setPlaceholderText(r"C:\Program Files\PuTTY\putty.exe")
        browse_btn = QPushButton("…")
        browse_btn.setObjectName("rpHeaderBtn")
        browse_btn.setFixedWidth(36)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._browse_putty)

        self._putty_path_widget = self._row_path(
            tr("settings.putty_path"),
            self._putty_path_edit,
            browse_btn,
            tr("settings.putty_hint")
        )
        self._putty_path_widget.setVisible(False)

        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl as _QUrl
        self._putty_download_lbl = QLabel(
            f'<a href="https://www.putty.org" style="color:#00b4d8;">'
            f'{tr("settings.putty_download_link")}</a>'
        )
        self._putty_download_lbl.setObjectName("hintLabel")
        self._putty_download_lbl.setContentsMargins(16, 0, 16, 8)
        self._putty_download_lbl.setOpenExternalLinks(False)
        self._putty_download_lbl.linkActivated.connect(
            lambda: QDesktopServices.openUrl(_QUrl("https://www.putty.org"))
        )
        self._putty_download_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._putty_download_lbl.setVisible(False)

        term_card, term_vl = self._make_group()
        term_vl.addWidget(self._row_radio(self._term_ssh_radio))
        term_vl.addWidget(self._inner_sep())
        term_vl.addWidget(self._row_radio(self._term_putty_radio))
        term_vl.addWidget(self._putty_path_widget)
        term_vl.addWidget(self._putty_download_lbl)
        term_vl.addWidget(self._inner_sep())
        term_vl.addWidget(self._row_radio(self._term_xterm_radio))
        root.addWidget(term_card)
        root.addSpacing(14)

        # Legacy alias kept for external code that reads _use_putty
        self._use_putty = self._term_putty_radio

        # ── DEVELOPER ─────────────────────────────────────────────────
        root.addWidget(self._section_header(tr("settings.section.developer")))
        root.addSpacing(4)

        self._debug_mode = QCheckBox(tr("settings.debug_mode"))
        self._debug_mode.toggled.connect(self._on_debug_toggled)

        dev_card, dev_vl = self._make_group()
        dev_vl.addWidget(self._row_check(self._debug_mode))

        # Tools rows — appended to dev_card when debug mode is toggled on
        self._fix_ghosts_btn = QPushButton(tr("settings.fix_ghosts"))
        self._fix_ghosts_btn.setObjectName("settingsActionBtn")
        self._fix_ghosts_btn.setProperty("btn_type", "primary")
        self._fix_ghosts_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fix_ghosts_btn.setFixedWidth(170)
        self._fix_ghosts_btn.setMinimumHeight(32)
        self._fix_ghosts_btn.clicked.connect(self._on_fix_ghosts)

        self._restart_explorer_btn = QPushButton(tr("settings.restart_explorer"))
        self._restart_explorer_btn.setObjectName("settingsActionBtn")
        self._restart_explorer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._restart_explorer_btn.setFixedWidth(170)
        self._restart_explorer_btn.setMinimumHeight(32)
        self._restart_explorer_btn.clicked.connect(self._on_restart_explorer)

        self._tools_widget = QWidget()
        tools_vl = QVBoxLayout(self._tools_widget)
        tools_vl.setContentsMargins(0, 0, 0, 0)
        tools_vl.setSpacing(0)
        tools_vl.addWidget(self._inner_sep())
        tools_vl.addWidget(self._row_action(
            self._fix_ghosts_btn, tr("settings.section.tools")
        ))
        tools_vl.addWidget(self._inner_sep())
        tools_vl.addWidget(self._row_action(
            self._restart_explorer_btn, "Windows Explorer neu starten"
        ))
        self._tools_widget.setVisible(False)
        dev_vl.addWidget(self._tools_widget)

        root.addWidget(dev_card)
        root.addStretch()

        # ── Button Bar ────────────────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setObjectName("dialogBtnBar")
        btn_bar_layout = QVBoxLayout(btn_bar)
        btn_bar_layout.setContentsMargins(20, 8, 20, 16)
        btn_bar_layout.setSpacing(0)
        btn_bar_layout.addWidget(self._divider())

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 10, 0, 0)
        btn_row.setSpacing(10)
        btn_row.addWidget(make_maximize_button(self))
        btn_row.addStretch()
        cancel_btn = QPushButton(tr("dialog.cancel"))
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton(tr("dialog.save"))
        save_btn.setObjectName("primaryBtn")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        btn_bar_layout.addLayout(btn_row)

        self.layout().addWidget(btn_bar)

    def _load_settings(self):
        s = self._settings
        self._start_with_windows.setChecked(s.start_with_windows)
        self._minimize_to_tray.setChecked(s.minimize_to_tray)
        self._require_admin.setChecked(s.require_admin)
        self._telemetry_enabled.setChecked(getattr(s, 'telemetry_enabled', False))
        self._interval_spin.setValue(s.check_interval_seconds)
        self._auto_reconnect.setChecked(s.auto_reconnect)
        self._auto_remount_on_lost.setChecked(s.auto_remount_on_lost)
        self._debug_mode.setChecked(s.debug_mode)
        tc = getattr(s, 'terminal_client', 'ssh') or 'ssh'
        self._term_ssh_radio.setChecked(tc == 'ssh')
        self._term_putty_radio.setChecked(tc == 'putty')
        self._term_xterm_radio.setChecked(tc == 'xterm')
        self._putty_path_edit.setText(getattr(s, 'putty_path', r"C:\Program Files\PuTTY\putty.exe"))
        self._putty_path_widget.setVisible(tc == 'putty')
        self._putty_download_lbl.setVisible(tc == 'putty')
        self._tools_widget.setVisible(s.debug_mode)
        # Language
        lang = getattr(s, 'language', 'en') or 'en'
        idx = self._lang_combo.findData(lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        # Theme
        theme = getattr(s, 'theme', 'dark') or 'dark'
        idx = self._theme_combo.findData(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)

    def _on_terminal_client_toggled(self, _button=None, _checked: bool = False):
        is_putty = self._term_putty_radio.isChecked()
        self._putty_path_widget.setVisible(is_putty)
        self._putty_download_lbl.setVisible(is_putty)
        self.adjustSize()

    def _on_putty_toggled(self, checked: bool):
        self._putty_path_widget.setVisible(checked)
        self.adjustSize()

    def _on_debug_toggled(self, checked: bool):
        self._tools_widget.setVisible(checked)
        self.adjustSize()

    def _browse_putty(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("settings.select_putty"),
            r"C:\Program Files\PuTTY",
            "Executables (*.exe)"
        )
        if path:
            self._putty_path_edit.setText(path)

    def _on_fix_ghosts(self):
        controller = SSHFSController()
        ok = controller.purge_all_stale_mounts()
        if ok:
            StyledMessageBox.information(self, tr("dialog.success"), tr("settings.ghosts_ok"))
            SSHFSController.restart_explorer()
        else:
            StyledMessageBox.warning(self, tr("dialog.error"), tr("settings.ghosts_failed"))

    def _on_restart_explorer(self):
        SSHFSController.restart_explorer()
        StyledMessageBox.information(self, "Explorer", tr("settings.explorer_restarted"))

    def _on_create_shortcut(self):
        reply = StyledMessageBox.question(
            self,
            tr("settings.create_shortcut"),
            tr("settings.create_shortcut.confirm"),
            yes_text=tr("dialog.understood"),
            no_text=tr("dialog.cancel"),
        )
        if not reply:
            return

        success, msg = self._create_desktop_shortcut()
        if success:
            StyledMessageBox.information(self, tr("dialog.success"), tr("settings.create_shortcut.success"))
        else:
            from src.app_logger import logger
            logger.error(f"Shortcut creation failed: {msg}")
            StyledMessageBox.warning(self, tr("dialog.error"), tr("settings.create_shortcut.failed"))

    @staticmethod
    def _create_desktop_shortcut() -> tuple[bool, str]:
        import os
        import sys
        import subprocess

        if getattr(sys, "frozen", False):
            target_path = os.path.abspath(sys.executable)
            args = ""
        else:
            target_path = os.path.abspath(sys.executable)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            main_script = os.path.join(project_root, "main.py")
            args = f'"{main_script}"'

        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        shortcut_path = os.path.join(desktop, "NEO SSH-Win Manager.lnk")

        ps_script = (
            "$WshShell = New-Object -ComObject WScript.Shell\n"
            f"$Shortcut = $WshShell.CreateShortcut('{shortcut_path}')\n"
            f"$Shortcut.TargetPath = '{target_path}'\n"
            f"$Shortcut.WorkingDirectory = '{os.path.dirname(target_path)}'\n"
            "$Shortcut.Description = 'NEO SSH-Win Manager'\n"
            f"$Shortcut.IconLocation = '{target_path},0'\n"
            + (f"$Shortcut.Arguments = '{args}'\n" if args else "")
            + "$Shortcut.Save()"
        )

        try:
            cp = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                check=True,
                capture_output=True,
                text=True,
            )
            if not os.path.exists(shortcut_path):
                return False, "Shortcut file was not created"
            return True, cp.stdout.strip()
        except subprocess.CalledProcessError as e:
            return False, (e.stderr or e.stdout or str(e)).strip()
        except Exception as e:
            return False, str(e)

    def _on_check_updates(self):
        self._update_btn.setText("Prüfe... ⏳")
        self._update_btn.setEnabled(False)
        QApplication.processEvents()

        try:
            from src.ui.dialogs.about_dialog import APP_VERSION
            from src.updater import UpdaterManager
            from src.ui.dialogs.update_dialog import UpdateDialog
        except Exception as e:
            StyledMessageBox.warning(self, "Fehler", f"Fehler bei der Update-Prüfung: {e}")
            self._update_btn.setText("Auf Updates prüfen")
            self._update_btn.setEnabled(True)
            return

        updater = UpdaterManager(APP_VERSION)
        self._update_mgr = updater  # keep alive

        def _reset():
            self._update_btn.setText("Auf Updates prüfen")
            self._update_btn.setEnabled(True)

        def _on_update_available(version: str, changelog: str, download_url: str, obj_type: str):
            try:
                dlg = UpdateDialog(self, version, changelog, download_url, obj_type)
                dlg.start_background_download.connect(lambda: updater.download_update_async(download_url))
                updater.download_progress.connect(dlg.update_progress)

                def _on_finished(success: bool, msg: str):
                    if success:
                        updater.install_on_exit()
                    dlg.on_download_finished(success, msg)

                updater.download_finished.connect(_on_finished)
                dlg.exec()
            finally:
                _reset()

        def _on_no_update():
            StyledMessageBox.information(self, "Update", "Du bist auf dem neuesten Stand!")
            _reset()

        def _on_failed(msg: str):
            StyledMessageBox.warning(self, "Fehler", f"Fehler bei der Update-Prüfung: {msg}")
            _reset()

        updater.update_available.connect(_on_update_available)
        updater.no_update_available.connect(_on_no_update)
        updater.check_failed.connect(_on_failed)
        updater.check_for_updates_async()

    def _on_save(self):
        if self._term_putty_radio.isChecked():
            import os
            path = self._putty_path_edit.text().strip()
            if not path:
                StyledMessageBox.warning(self, "PuTTY", tr("settings.putty_missing"))
                return
            if not os.path.exists(path):
                reply = StyledMessageBox.question(
                    self, tr("settings.putty_not_found_title"),
                    tr("settings.putty_not_found", path=path)
                )
                if not reply:
                    return
        self.accept()

    def get_settings(self) -> AppSettings:
        if self._term_putty_radio.isChecked():
            tc = "putty"
        elif self._term_xterm_radio.isChecked():
            tc = "xterm"
        else:
            tc = "ssh"
        s = AppSettings(
            start_with_windows=self._start_with_windows.isChecked(),
            minimize_to_tray=self._minimize_to_tray.isChecked(),
            require_admin=self._require_admin.isChecked(),
            check_interval_seconds=self._interval_spin.value(),
            auto_reconnect=self._auto_reconnect.isChecked(),
            auto_remount_on_lost=self._auto_remount_on_lost.isChecked(),
            debug_mode=self._debug_mode.isChecked(),
            terminal_client=tc,
            use_putty=(tc == "putty"),
            putty_path=self._putty_path_edit.text().strip(),
            language=self._lang_combo.currentData() or "en",
            theme=self._theme_combo.currentData() or "dark",
            telemetry_enabled=self._telemetry_enabled.isChecked(),
            telemetry_prompt_shown=self._settings.telemetry_prompt_shown
        )
        self._apply_autostart(s.start_with_windows)
        return s

    @staticmethod
    def _apply_autostart(enabled: bool):
        try:
            import winreg, sys
            app_name = "NeoSSHWinManager"
            dangerous = set(';|&`$(){}[]<>!\\"\'\n\r\t\\')
            if any(c in dangerous for c in app_name):
                from src.app_logger import logger
                logger.warning(f"Rejected unsafe app_name for registry: {app_name}")
                return
            
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                    0, winreg.KEY_SET_VALUE
                )
                if enabled:
                    winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{sys.executable}"')
                else:
                    try:
                        winreg.DeleteValue(key, app_name)
                    except FileNotFoundError:
                        pass
                from src.app_logger import logger
                logger.info(f"Autostart {'aktiviert' if enabled else 'deaktiviert'}: {app_name}")
            except Exception as e:
                from src.app_logger import logger
                logger.error(f"Autostart konnte nicht {'aktiviert' if enabled else 'deaktiviert'} werden: {e}")
            finally:
                winreg.CloseKey(key)
        except Exception as e:
            from src.app_logger import logger
            logger.warning(f"Autostart konnte nicht gesetzt werden: {e}")
