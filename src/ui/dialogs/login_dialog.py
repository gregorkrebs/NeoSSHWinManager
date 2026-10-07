"""
login_dialog.py – Login-Dialog for NEO SSH-Win Manager.

Shows a registration form on the first start.
On subsequent starts, a login dialog is displayed.
The login screen has a language picker and takes its theme and accent
colour from the user who signed in last.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QCheckBox, QTabWidget, QWidget,
    QScrollArea, QApplication, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer, QEvent
from PyQt6.QtGui import QFont, QIcon, QAction
import ctypes
import os
import tempfile

from src.auth_manager import AuthManager, Session, LoginLockedError, SingleUserModeError
from src.crypto import is_available, is_keyring_available
from src.ui.dialog_utils import match_parent_height, make_maximize_button
from src.ui.dialogs.styled_message_box import StyledMessageBox
from src.ui.frameless_dialog import FramelessDialog
from src.ui.icons import icon as svg_icon, pixmap as svg_pixmap, svg_file
from src.ui.theme import current_accent, dark_tone, is_light, normalize_theme
from src.ui.widgets.no_wheel import NoWheelScrollArea
from src.i18n import (
    tr, set_language, current_language, available_languages, is_rtl, LANGUAGE_NAMES,
)


def _caps_lock_on() -> bool:
    try:
        return bool(ctypes.windll.user32.GetKeyState(0x14) & 1)  # VK_CAPITAL
    except Exception:
        return False


class LoginDialog(FramelessDialog):
    """
    Shown at app start.
    - First start: registration form, or single-user mode instead
    - Subsequent starts: login
    """

    login_successful = pyqtSignal()

    WIDTH = 500

    def __init__(self, parent=None, theme: str = "dark"):
        super().__init__(parent)
        self.setObjectName("dialogSurface")
        self.setFixedWidth(self.WIDTH)
        self.setModal(True)
        for icon_file in ("app_icon.ico", "app_icon.png"):
            icon_path = self._resource_path(os.path.join("assets", icon_file))
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                break

        self._theme = normalize_theme(theme)
        self.set_dialog_theme(self._theme)
        self._first_run = not AuthManager.has_any_users()
        self._lang_changed = False

        # Lives across rebuilds (a language change rebuilds the form)
        self._lockout_timer = QTimer(self)
        self._lockout_timer.setInterval(1000)
        self._lockout_timer.timeout.connect(self._tick_lockout)
        self._lockout_remaining = 0

        self._root_layout = QVBoxLayout(self._fdlg_content)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root = None
        self._build_ui()

    @staticmethod
    def _resource_path(relative_path: str) -> str:
        import sys
        if hasattr(sys, '_MEIPASS'):
            return os.path.join(sys._MEIPASS, relative_path)
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            relative_path
        )

    # ------------------------------------------------------------------
    # Building blocks
    # ------------------------------------------------------------------

    def _icon_color(self) -> str:
        return "#7a8a9a" if is_light(self._theme) else dark_tone(self._theme, "#8fa4b8")

    _icon_tmp: str | None = None

    @classmethod
    def _icon_dir(cls) -> str:
        if cls._icon_tmp is None:
            cls._icon_tmp = tempfile.mkdtemp(prefix="neossh_login_")
        return cls._icon_tmp

    @staticmethod
    def _dpr() -> float:
        screen = QApplication.primaryScreen()
        return screen.devicePixelRatio() if screen is not None else 1.0

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("loginFieldLabel")
        return lbl

    def _input(self, placeholder: str, icon_name: str, password: bool = False) -> QLineEdit:
        w = QLineEdit()
        w.setObjectName("loginInput")
        w.setPlaceholderText(placeholder)
        w.addAction(svg_icon(icon_name, self._icon_color(), 16),
                    QLineEdit.ActionPosition.LeadingPosition)
        if password:
            w.setEchoMode(QLineEdit.EchoMode.Password)
            toggle = QAction(svg_icon("eye", self._icon_color(), 16), tr("login.show_password"), w)
            toggle.setToolTip(tr("login.show_password"))
            toggle.triggered.connect(lambda _=False, f=w, a=toggle: self._toggle_password(f, a))
            w.addAction(toggle, QLineEdit.ActionPosition.TrailingPosition)
            w.installEventFilter(self)
        return w

    def _toggle_password(self, field: QLineEdit, action: QAction) -> None:
        hidden = field.echoMode() == QLineEdit.EchoMode.Password
        field.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        action.setIcon(svg_icon("eye-off" if hidden else "eye", self._icon_color(), 16))
        tip = tr("login.hide_password") if hidden else tr("login.show_password")
        action.setText(tip)
        action.setToolTip(tip)

    def _icon_row(self, object_name: str, icon_name: str, color: str) -> tuple[QFrame, QLabel]:
        """A row with a small icon and a word-wrapped text (alerts, hints)."""
        frame = QFrame()
        frame.setObjectName(object_name)
        row = QHBoxLayout(frame)
        row.setContentsMargins(*((12, 9, 12, 9) if object_name == "loginAlert" else (2, 0, 2, 0)))
        row.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(svg_pixmap(icon_name, color, 15, self._dpr()))
        icon.setFixedSize(16, 16)
        icon.setStyleSheet("background: transparent;")
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        text = QLabel()
        text.setObjectName("loginAlertText" if object_name == "loginAlert" else "loginCapsText")
        text.setWordWrap(True)
        row.addWidget(text, 1)
        frame.setVisible(False)
        return frame, text

    @staticmethod
    def _messages(*rows: QFrame) -> QVBoxLayout:
        """Hints and errors under the fields; hidden ones take no space."""
        box = QVBoxLayout()
        box.setContentsMargins(0, 10, 0, 0)
        box.setSpacing(8)
        for row in rows:
            box.addWidget(row)
        return box

    def _alert(self) -> tuple[QFrame, QLabel]:
        return self._icon_row("loginAlert", "alert-triangle",
                              "#dc2626" if is_light(self._theme) else "#ff8d8d")

    def _caps_hint(self) -> QFrame:
        frame, text = self._icon_row("loginCapsHint", "keyboard",
                                     "#b45309" if is_light(self._theme) else "#f59e0b")
        text.setText(tr("login.caps_lock"))
        return frame

    def _app_icon(self) -> QLabel:
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("background: transparent;")
        icon_path = self._resource_path(os.path.join("assets", "app_icon.png"))
        if os.path.exists(icon_path):
            from PyQt6.QtGui import QPixmap
            pm = QPixmap(icon_path)
            if not pm.isNull():
                dpr = self._dpr()
                pm = pm.scaled(int(68 * dpr), int(68 * dpr),
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                pm.setDevicePixelRatio(dpr)
                lbl.setPixmap(pm)
                return lbl
        # Fallback when the app icon is missing: a lock in the accent colour
        lbl.setPixmap(svg_pixmap("lock", current_accent(), 56, self._dpr()))
        return lbl

    def _language_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.setObjectName("loginLangCombo")
        combo.setToolTip(tr("login.language"))
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        combo.setIconSize(QSize(14, 14))
        # The shared chevron is drawn in currentColor, which a stylesheet
        # url() renders black: give this one the theme's icon colour.
        arrow = svg_file("chevron-down", self._icon_color(), self._icon_dir())
        combo.setStyleSheet(f'QComboBox#loginLangCombo::down-arrow {{ image: url("{arrow}"); }}')
        globe = svg_icon("globe", self._icon_color(), 14)
        for code in available_languages():
            combo.addItem(globe, LANGUAGE_NAMES.get(code, code), code)
        combo.setCurrentIndex(max(0, combo.findData(current_language())))
        combo.currentIndexChanged.connect(self._on_language_picked)
        return combo

    @staticmethod
    def _version() -> str:
        try:
            with open(os.path.join(os.path.dirname(__file__), "..", "..", "version.txt"),
                      "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return "?"

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setWindowTitle(tr("login.title"))

        root = QFrame()
        root.setObjectName("loginRoot")
        v = QVBoxLayout(root)
        v.setContentsMargins(28, 16, 28, 22)
        v.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addStretch(1)
        self._lang_combo = self._language_combo()
        top.addWidget(self._lang_combo)
        v.addLayout(top)

        v.addSpacing(4)
        v.addWidget(self._app_icon())
        v.addSpacing(14)

        headline = QLabel(tr("login.headline.setup") if self._first_run else tr("login.headline.signin"))
        headline.setObjectName("loginHeadline")
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        headline.setWordWrap(True)
        v.addWidget(headline)
        v.addSpacing(6)

        subline = QLabel(tr("login.subline.setup") if self._first_run else tr("login.subline.signin"))
        subline.setObjectName("loginSubline")
        subline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subline.setWordWrap(True)
        v.addWidget(subline)
        v.addSpacing(20)

        card = QFrame()
        card.setObjectName("loginCard")
        form = QVBoxLayout(card)
        form.setContentsMargins(24, 22, 24, 24)
        form.setSpacing(0)
        if self._first_run:
            self._build_register_form(form)
        else:
            self._build_login_form(form)
        v.addWidget(card)

        v.addSpacing(16)
        ver_lbl = QLabel(f"v{self._version()}")
        ver_lbl.setObjectName("dialogPill")
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(ver_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        self._root_layout.addWidget(root)
        self._root = root

    def _build_login_form(self, layout: QVBoxLayout):
        layout.addWidget(self._field_label(tr("login.username")))
        layout.addSpacing(6)
        self._login_user = self._input(tr("login.username"), "user")
        layout.addWidget(self._login_user)
        layout.addSpacing(16)

        layout.addWidget(self._field_label(tr("login.password")))
        layout.addSpacing(6)
        self._login_pw = self._input(tr("login.password"), "lock", password=True)
        self._login_pw.returnPressed.connect(self._do_login)
        layout.addWidget(self._login_pw)

        self._caps = self._caps_hint()
        self._login_alert, self._login_error = self._alert()
        layout.addLayout(self._messages(self._caps, self._login_alert))

        layout.addSpacing(18)
        self._login_btn = QPushButton(tr("login.sign_in"))
        self._login_btn.setObjectName("primaryBtn")
        self._login_btn.setProperty("size", "large")
        self._login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._login_btn.setEnabled(False)
        self._login_btn.clicked.connect(self._do_login)
        layout.addWidget(self._login_btn)

        self._login_user.returnPressed.connect(self._login_pw.setFocus)
        self._login_user.textChanged.connect(self._update_login_btn_state)
        self._login_pw.textChanged.connect(self._update_login_btn_state)

        if self._lockout_remaining > 0:
            self._set_login_locked(True)
            self._update_lockout_label()
        self._login_user.setFocus()

    def _build_register_form(self, layout: QVBoxLayout):
        for attr, lbl, ph, icon_name, pw in [
            ("_reg_user", tr("login.username"), tr("login.username"), "user", False),
            ("_reg_pw",   tr("login.password"), tr("login.pw_min"), "lock", True),
            ("_reg_pw2",  tr("login.pw_confirm"), tr("login.pw_repeat"), "lock", True),
        ]:
            if attr != "_reg_user":
                layout.addSpacing(16)
            layout.addWidget(self._field_label(lbl))
            layout.addSpacing(6)
            field = self._input(ph, icon_name, pw)
            setattr(self, attr, field)
            layout.addWidget(field)
        self._reg_user.returnPressed.connect(self._reg_pw.setFocus)
        self._reg_pw.returnPressed.connect(self._reg_pw2.setFocus)
        self._reg_pw2.returnPressed.connect(self._do_register)

        self._caps = self._caps_hint()
        self._reg_alert, self._reg_error = self._alert()
        layout.addLayout(self._messages(self._caps, self._reg_alert))

        layout.addSpacing(18)
        # Qt reads "&" in button texts as a shortcut marker; "&&" shows it.
        btn = QPushButton(tr("login.create_account").replace("&", "&&"))
        btn.setObjectName("primaryBtn")
        btn.setProperty("size", "large")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self._do_register)
        layout.addWidget(btn)

        # Alternative: no account of one's own, automatic sign-in instead
        layout.addSpacing(18)
        or_row = QHBoxLayout()
        or_row.setSpacing(12)
        or_lbl = QLabel(tr("login.or").upper())
        or_lbl.setObjectName("loginOrLabel")
        left_line, right_line = QFrame(), QFrame()
        left_line.setObjectName("loginOrLine")
        right_line.setObjectName("loginOrLine")
        or_row.addWidget(left_line, 1)
        or_row.addWidget(or_lbl)
        or_row.addWidget(right_line, 1)
        layout.addLayout(or_row)
        layout.addSpacing(18)

        keyring_ok = is_keyring_available()
        self._single_btn = QPushButton(tr("login.initial_setup"))
        self._single_btn.setObjectName("secondaryBtn")
        self._single_btn.setProperty("size", "large")
        self._single_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._single_btn.setEnabled(keyring_ok)
        self._single_btn.clicked.connect(self._initial_single_setup)
        layout.addWidget(self._single_btn)

        layout.addSpacing(8)
        single_hint = QLabel(
            tr("login.single_hint") if keyring_ok else tr("login.single_unavailable_keyring")
        )
        single_hint.setObjectName("loginHint")
        single_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        single_hint.setWordWrap(True)
        layout.addWidget(single_hint)

        self._reg_user.setFocus()

    # ------------------------------------------------------------------
    # Language
    # ------------------------------------------------------------------

    def _on_language_picked(self, index: int):
        code = self._lang_combo.itemData(index)
        if code and code != current_language():
            # Rebuild after the combo's signal has returned: it is part of
            # the form that gets replaced.
            QTimer.singleShot(0, lambda: self._switch_language(code))

    def _switch_language(self, code: str):
        values = {attr: getattr(self, attr).text()
                  for attr in ("_login_user", "_login_pw", "_reg_user", "_reg_pw", "_reg_pw2")
                  if hasattr(self, attr)}
        set_language(code)
        self._lang_changed = True
        QApplication.instance().setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight
        )
        old = self._root
        self._root_layout.removeWidget(old)
        old.hide()
        old.deleteLater()
        self._build_ui()
        for attr, text in values.items():
            getattr(self, attr).setText(text)
        self._lang_combo.setFocus()
        self.adjustSize()

    def _remember_language(self, user_id: str, always: bool = False):
        """Keep the language picked here as the user's language."""
        if always or self._lang_changed:
            try:
                AuthManager.set_user_language(user_id, current_language())
            except Exception:
                pass  # the login itself has succeeded; never block it here

    # ------------------------------------------------------------------
    # Caps Lock hint
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease,
                            QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            QTimer.singleShot(0, self._update_caps_hint)
        return super().eventFilter(obj, event)

    def _update_caps_hint(self):
        caps = getattr(self, "_caps", None)
        if caps is None:
            return
        in_password = QApplication.focusWidget() in self._password_fields()
        caps.setVisible(in_password and _caps_lock_on())

    def _password_fields(self) -> list:
        return [getattr(self, a) for a in ("_login_pw", "_reg_pw", "_reg_pw2") if hasattr(self, a)]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _update_login_btn_state(self):
        enabled = bool(self._login_user.text().strip()) and bool(self._login_pw.text())
        self._login_btn.setEnabled(enabled and self._lockout_remaining <= 0)

    def _do_login(self):
        if self._lockout_remaining > 0:
            return
        username = self._login_user.text().strip()
        password = self._login_pw.text()

        try:
            user = AuthManager.authenticate(username, password)
        except LoginLockedError as e:
            self._start_lockout_countdown(e.seconds_remaining, e.total_failures)
            self._login_pw.clear()
            return

        if user is None:
            self._show_login_error(tr("login.invalid"))
            self._login_pw.clear()
            self._login_pw.setFocus()
            return

        self._remember_language(user.id)
        Session.login(user)
        self.accept()

    def _set_login_locked(self, locked: bool):
        self._login_user.setEnabled(not locked)
        self._login_pw.setEnabled(not locked)
        if locked:
            self._login_btn.setEnabled(False)
        else:
            self._update_login_btn_state()

    def _start_lockout_countdown(self, seconds: int, total_failures: int):
        self._lockout_remaining = seconds
        self._set_login_locked(True)
        self._update_lockout_label()
        self._lockout_timer.start()

    def _tick_lockout(self):
        self._lockout_remaining -= 1
        if self._lockout_remaining <= 0:
            self._lockout_timer.stop()
            self._login_alert.setVisible(False)
            self._set_login_locked(False)
            self._login_pw.setFocus()
        else:
            self._update_lockout_label()

    def _update_lockout_label(self):
        s = self._lockout_remaining
        if s >= 86400:
            human = f"{s // 86400}d {(s % 86400) // 3600}h"
        elif s >= 3600:
            h = s // 3600
            m = (s % 3600) // 60
            human = f"{h}h {m:02d}m" if m else f"{h}h"
        elif s >= 60:
            human = f"{s // 60}m {s % 60:02d}s"
        else:
            human = f"{s}s"
        self._show_login_error(tr("login.locked", time=human))

    def _do_register(self):
        username = self._reg_user.text().strip()
        pw = self._reg_pw.text()
        pw2 = self._reg_pw2.text()

        if not username:
            self._show_reg_error(tr("login.enter_username"))
            return
        if len(username) < 3:
            self._show_reg_error(tr("login.username_min"))
            return
        if len(pw) < 8:  # SECURITY FIX (FINDING-D): NIST SP 800-63B minimum is 8 for user-chosen passwords
            self._show_reg_error(tr("login.password_min"))
            return
        if pw != pw2:
            self._show_reg_error(tr("login.passwords_differ"))
            self._reg_pw2.clear()
            self._reg_pw2.setFocus()
            return

        if not is_available():
            StyledMessageBox.critical(self, tr("dialog.error"), tr("login.no_crypto"))
            return

        try:
            user = AuthManager.register(username, pw, is_admin=True)
        except Exception as e:
            self._show_reg_error(str(e))
            return
        self._remember_language(user.id, always=True)
        Session.login(user)
        self.accept()

    def _initial_single_setup(self):
        if not is_available():
            StyledMessageBox.critical(self, tr("dialog.error"), tr("login.no_crypto"))
            return
        try:
            user = AuthManager.initialize_single_user_mode()
        except Exception as e:
            self._show_reg_error(SingleUserModeError.text_for(e))
            return
        self._remember_language(user.id, always=True)
        Session.login(user)
        self.accept()

    def _show_login_error(self, msg: str):
        self._login_error.setText(msg)
        self._login_alert.setVisible(True)

    def _show_reg_error(self, msg: str):
        self._reg_error.setText(msg)
        self._reg_alert.setVisible(True)

    def closeEvent(self, event):
        # Wenn nicht eingeloggt → App beenden
        if not Session.is_logged_in():
            from PyQt6.QtWidgets import QApplication
            QApplication.quit()
        super().closeEvent(event)


class UserManagementDialog(QDialog):
    """Admin-Dialog zum Verwalten von Benutzern."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dialogSurface")
        self.setWindowTitle(tr("users.title"))
        self.setMinimumWidth(520)
        self.setMinimumHeight(400)
        self.setModal(True)
        self._build_ui()
        self._refresh_users()
        # Max-Höhe = Bildschirm, Start-Höhe = volle Hauptfenster-Höhe (scrollbar bei Overflow).
        screen = QApplication.primaryScreen()
        if screen:
            self.setMaximumHeight(int(screen.availableGeometry().height() * 0.95))
        match_parent_height(self, parent)

    def _divider(self) -> QFrame:
        f = QFrame()
        f.setObjectName("divider")
        f.setFixedHeight(1)
        return f

    def _input(self, placeholder="", password=False) -> QLineEdit:
        w = QLineEdit()
        w.setPlaceholderText(placeholder)
        if password:
            w.setEchoMode(QLineEdit.EchoMode.Password)
        return w

    def _build_ui(self):
        # Äußeres Layout: scrollbarer Content oben, fixe Button-Leiste unten.
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
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 20, 20, 12)
        layout.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("dialogHeroCard")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(22, 20, 22, 20)
        hero_l.setSpacing(8)

        title = QLabel(tr("users.title"))
        title.setObjectName("dialogTitle")
        hero_l.addWidget(title)

        lead = QLabel(tr("dialog.lead.users"))
        lead.setObjectName("dialogLead")
        lead.setWordWrap(True)
        hero_l.addWidget(lead)
        layout.addWidget(hero)

        content_card = QFrame()
        content_card.setObjectName("dialogSectionCard")
        content = QVBoxLayout(content_card)
        content.setContentsMargins(22, 20, 22, 20)
        content.setSpacing(10)

        # Benutzerliste
        list_lbl = QLabel(tr("users.section.users"))
        list_lbl.setObjectName("sectionLabel")
        content.addWidget(list_lbl)

        self._users_layout = QVBoxLayout()
        self._users_layout.setSpacing(8)
        content.addLayout(self._users_layout)

        content.addWidget(self._divider())

        # Neuen Benutzer anlegen
        new_lbl = QLabel(tr("users.section.new"))
        new_lbl.setObjectName("sectionLabel")
        content.addWidget(new_lbl)

        self._new_user = self._input(tr("users.placeholder.username"))
        content.addWidget(self._new_user)

        self._new_pw = self._input(tr("users.placeholder.password"), password=True)
        content.addWidget(self._new_pw)

        self._new_is_admin = QCheckBox(tr("users.admin"))
        content.addWidget(self._new_is_admin)

        add_btn = QPushButton(tr("users.create"))
        add_btn.setObjectName("primaryBtn")
        add_btn.setMinimumHeight(34)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._add_user)
        content.addWidget(add_btn)

        content.addStretch()
        layout.addWidget(content_card)

        # Fixe Button-Leiste außerhalb der Scroll-Area.
        btn_bar = QWidget()
        btn_bar.setObjectName("dialogBtnBar")
        btn_bar_layout = QVBoxLayout(btn_bar)
        btn_bar_layout.setContentsMargins(20, 8, 20, 16)
        btn_bar_layout.setSpacing(8)
        btn_bar_layout.addWidget(self._divider())

        close_row = QHBoxLayout()
        close_row.setContentsMargins(0, 10, 0, 0)
        close_row.addWidget(make_maximize_button(self))
        close_row.addStretch()
        close_btn = QPushButton(tr("dialog.close"))
        close_btn.setObjectName("secondaryBtn")
        close_btn.setMinimumHeight(34)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        close_row.addStretch()
        _sp = QWidget(); _sp.setFixedWidth(32); close_row.addWidget(_sp)
        btn_bar_layout.addLayout(close_row)

        outer.addWidget(btn_bar)

    def _refresh_users(self):
        from src.database import get_connection

        # Liste leeren
        while self._users_layout.count():
            item = self._users_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        current_id = Session.current().id if Session.current() else None
        users = AuthManager.list_users()
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT user_id, COUNT(*) AS count FROM connections GROUP BY user_id"
            ).fetchall()
        connection_counts = {row["user_id"]: row["count"] for row in rows}

        for u in users:
            row = QFrame()
            row.setObjectName("userBox")
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(14, 12, 14, 12)
            row_l.setSpacing(10)

            name = u["username"]
            is_me = u["id"] == current_id
            connection_count = int(connection_counts.get(u["id"], 0))
            count_text = tr("users.connections.one", n=connection_count) if connection_count == 1 else tr("users.connections.many", n=connection_count)

            avatar = QLabel(name[:2].upper())
            avatar.setObjectName("userAvatar")
            avatar.setProperty("admin", "true" if u["is_admin"] else "false")
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar.setFixedSize(QSize(40, 40))
            row_l.addWidget(avatar)

            meta = QWidget()
            meta_l = QVBoxLayout(meta)
            meta_l.setContentsMargins(0, 0, 0, 0)
            meta_l.setSpacing(4)

            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(8)

            name_lbl = QLabel(name)
            name_lbl.setObjectName("connName")
            title_row.addWidget(name_lbl)

            role_badge = QLabel(tr("users.admin") if u["is_admin"] else tr("users.role.member"))
            role_badge.setObjectName("userRoleBadge")
            if u["is_admin"]:
                role_badge.setProperty("variant", "accent")
            title_row.addWidget(role_badge)

            if is_me:
                you_badge = QLabel(tr("users.badge.you"))
                you_badge.setObjectName("userRoleBadge")
                you_badge.setProperty("variant", "accent")
                title_row.addWidget(you_badge)

            title_row.addStretch(1)
            meta_l.addLayout(title_row)

            sub_lbl = QLabel(count_text)
            sub_lbl.setObjectName("userMetaSub")
            meta_l.addWidget(sub_lbl)
            row_l.addWidget(meta, stretch=1)

            if is_me:
                # Eigener Eintrag: Passwort-ändern-Button
                chg_btn = QPushButton()
                chg_btn.setObjectName("rpHeaderBtn")
                chg_btn.setFixedSize(32, 32)
                chg_btn.setIcon(svg_icon("key", "#aab4c4", 16))
                chg_btn.setIconSize(QSize(16, 16))
                chg_btn.setToolTip(tr("users.tooltip.change_pw"))
                chg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                chg_btn.clicked.connect(self._change_own_password)
                row_l.addWidget(chg_btn)
            else:
                # Admin-Aktionen für andere User
                if Session.is_admin():
                    reset_btn = QPushButton()
                    reset_btn.setObjectName("rpHeaderBtn")
                    reset_btn.setFixedSize(32, 32)
                    reset_btn.setIcon(svg_icon("rotate-cw", "#aab4c4", 16))
                    reset_btn.setIconSize(QSize(16, 16))
                    reset_btn.setToolTip(tr("users.tooltip.reset_pw", name=name))
                    reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    uid_r = u["id"]
                    reset_btn.clicked.connect(lambda _, i=uid_r, n=name: self._reset_user_password(i, n))
                    row_l.addWidget(reset_btn)

                del_btn = QPushButton()
                del_btn.setObjectName("rpHeaderBtn")
                del_btn.setFixedSize(32, 32)
                del_btn.setIcon(svg_icon("trash", "#ff6b7a", 16))
                del_btn.setIconSize(QSize(16, 16))
                del_btn.setToolTip(tr("users.tooltip.delete", name=name))
                del_btn.setProperty("btn_type", "danger")
                del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                uid = u["id"]
                del_btn.clicked.connect(lambda _, i=uid, n=name: self._delete_user(i, n))
                row_l.addWidget(del_btn)
            self._users_layout.addWidget(row)

    def _add_user(self):
        username = self._new_user.text().strip()
        pw = self._new_pw.text()
        is_admin = self._new_is_admin.isChecked()

        if not username or len(username) < 3:
            StyledMessageBox.warning(self, tr("dialog.error"), tr("users.username_min"))
            return
        if len(pw) < 8:  # SECURITY FIX (FINDING-D): NIST SP 800-63B minimum is 8
            StyledMessageBox.warning(self, tr("dialog.error"), tr("users.password_min"))
            return

        try:
            AuthManager.register(username, pw, is_admin=is_admin)
            self._new_user.clear()
            self._new_pw.clear()
            self._new_is_admin.setChecked(False)
            self._refresh_users()
        except Exception as e:
            StyledMessageBox.critical(self, tr("dialog.error"), str(e))

    def _delete_user(self, user_id: str, username: str):
        if StyledMessageBox.question(
            self, tr("users.delete.title"),
            tr("users.delete.confirm", name=username),
            yes_text="Löschen", no_text="Abbrechen"
        ):
            AuthManager.delete_user(user_id)
            self._refresh_users()

    def _reset_user_password(self, user_id: str, username: str):
        if not StyledMessageBox.question(
            self, tr("users.reset.title"),
            tr("users.reset.confirm", name=username),
            yes_text="Zurücksetzen", no_text="Abbrechen"
        ):
            return
        new_pw = AuthManager.admin_reset_password(user_id)
        if not new_pw:
            StyledMessageBox.critical(self, tr("dialog.error"), tr("users.not_found"))
            return
        StyledMessageBox.information(
            self, tr("users.reset.new_title"),
            tr("users.reset.new_msg", name=username, pw=new_pw)
        )

    def _change_own_password(self):
        user = Session.current()
        if not user:
            return
        dlg = ChangePasswordDialog(user.id, self)
        dlg.exec()


class ChangePasswordDialog(QDialog):
    """Dialog für den User, um das eigene Passwort zu ändern."""

    def __init__(self, user_id: str, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self.setObjectName("dialogSurface")
        self.setWindowTitle(tr("chgpw.title"))
        self.setMinimumWidth(420)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("dialogHeroCard")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(20, 18, 20, 18)
        hero_l.setSpacing(8)

        title = QLabel(tr("chgpw.title"))
        title.setObjectName("dialogTitle")
        hero_l.addWidget(title)

        lead = QLabel(tr("users.tooltip.change_pw"))
        lead.setObjectName("dialogLead")
        lead.setWordWrap(True)
        hero_l.addWidget(lead)
        layout.addWidget(hero)

        form_card = QFrame()
        form_card.setObjectName("dialogSectionCard")
        form_l = QVBoxLayout(form_card)
        form_l.setContentsMargins(20, 18, 20, 18)
        form_l.setSpacing(10)

        self._old_pw = QLineEdit()
        self._old_pw.setPlaceholderText(tr("chgpw.current"))
        self._old_pw.setEchoMode(QLineEdit.EchoMode.Password)
        form_l.addWidget(self._old_pw)

        self._new_pw = QLineEdit()
        self._new_pw.setPlaceholderText(tr("chgpw.new"))
        self._new_pw.setEchoMode(QLineEdit.EchoMode.Password)
        form_l.addWidget(self._new_pw)

        self._confirm_pw = QLineEdit()
        self._confirm_pw.setPlaceholderText(tr("chgpw.confirm"))
        self._confirm_pw.setEchoMode(QLineEdit.EchoMode.Password)
        form_l.addWidget(self._confirm_pw)
        layout.addWidget(form_card)

        footer = QWidget()
        footer.setObjectName("dialogBtnBar")
        footer_l = QVBoxLayout(footer)
        footer_l.setContentsMargins(0, 8, 0, 0)
        footer_l.setSpacing(0)
        sep = QFrame()
        sep.setObjectName("divider")
        sep.setFixedHeight(1)
        footer_l.addWidget(sep)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 10, 0, 0)
        btn_row.addWidget(make_maximize_button(self))
        btn_row.addStretch()
        cancel = QPushButton(tr("dialog.cancel"))
        cancel.setObjectName("secondaryBtn")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        save = QPushButton(tr("dialog.save"))
        save.setObjectName("primaryBtn")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._save)
        btn_row.addWidget(save)
        footer_l.addLayout(btn_row)
        layout.addWidget(footer)

    def _save(self):
        old_pw = self._old_pw.text()
        new_pw = self._new_pw.text()
        confirm = self._confirm_pw.text()
        if len(new_pw) < 8:
            StyledMessageBox.warning(self, tr("dialog.error"), tr("chgpw.new_min"))
            return
        if new_pw != confirm:
            StyledMessageBox.warning(self, tr("dialog.error"), tr("chgpw.mismatch"))
            return
        ok = AuthManager.change_password(self._user_id, old_pw, new_pw)
        if not ok:
            StyledMessageBox.critical(self, tr("dialog.error"), tr("chgpw.wrong_old"))
            return
        StyledMessageBox.information(self, tr("dialog.success"), tr("chgpw.success"))
        self.accept()
