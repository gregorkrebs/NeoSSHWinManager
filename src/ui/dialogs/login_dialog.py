"""
login_dialog.py – Login-Dialog for NEO SSH-Win Manager.

Shows a registration form on the first start.
On subsequent starts, a login dialog is displayed.
Admins can create additional users.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QCheckBox, QTabWidget, QWidget,
    QScrollArea, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QFont, QIcon
import os

from src.auth_manager import AuthManager, Session, LoginLockedError, SingleUserModeError
from src.crypto import is_available, is_keyring_available
from src.ui.dialog_utils import match_parent_height, make_maximize_button
from src.ui.dialogs.styled_message_box import StyledMessageBox
from src.ui.frameless_dialog import FramelessDialog
from src.ui.icons import icon as svg_icon
from src.ui.widgets.no_wheel import NoWheelScrollArea
from src.i18n import tr

class LoginDialog(FramelessDialog):
    """
    Shown at app start.
    - First start: Registration form
    - Subsequent starts: Login
    - Admin tab for creating additional users
    """

    login_successful = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dialogSurface")
        self.setWindowTitle(tr("login.title"))
        self.setMinimumWidth(440)
        self.setModal(True)
        for icon_file in ("app_icon.ico", "app_icon.png"):
            icon_path = self._resource_path(os.path.join("assets", icon_file))
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                break

        self._first_run = not AuthManager.has_any_users()
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

    @staticmethod
    def _set_lock_icon(label) -> None:
        """Fallback when the app icon is missing: a lock in the accent colour."""
        from PyQt6.QtWidgets import QApplication
        from src.ui.icons import pixmap as svg_pixmap
        from src.ui.theme import current_accent
        screen = QApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0
        label.setPixmap(svg_pixmap("lock", current_accent(), 56, dpr))

    def _build_ui(self):
        layout = QVBoxLayout(self._fdlg_content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("dialogHeroCard")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(22, 22, 22, 22)
        hero_l.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setObjectName("dialogIconLarge")
        try:
            icon_path = self._resource_path(os.path.join("assets", "app_icon.png"))
            if os.path.exists(icon_path):
                from PyQt6.QtGui import QPixmap
                pm = QPixmap(icon_path).scaled(
                    64, 64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                icon_lbl.setPixmap(pm)
            else:
                self._set_lock_icon(icon_lbl)
        except Exception:
            self._set_lock_icon(icon_lbl)
        hero_l.addWidget(icon_lbl)

        title = QLabel("NEO SSH-Win Manager")
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_l.addWidget(title)

        try:
            with open(os.path.join(os.path.dirname(__file__), "..", "..", "version.txt"), "r", encoding="utf-8") as f:
                APP_VERSION = f.read().strip()
        except Exception:
            APP_VERSION = "?"

        ver_lbl = QLabel(f"v{APP_VERSION}")
        ver_lbl.setObjectName("dialogPill")
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_l.addWidget(ver_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        lead = QLabel(tr("login.create_first") if self._first_run else tr("login.please_sign_in"))
        lead.setObjectName("dialogLead")
        lead.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lead.setWordWrap(True)
        hero_l.addWidget(lead)
        layout.addWidget(hero)

        form_card = QFrame()
        form_card.setObjectName("dialogSectionCard")
        form_l = QVBoxLayout(form_card)
        form_l.setContentsMargins(22, 20, 22, 20)
        form_l.setSpacing(10)

        if self._first_run:
            self._build_register_form(form_l)
        else:
            self._build_login_form(form_l)
        layout.addWidget(form_card)

    def _build_login_form(self, layout: QVBoxLayout):
        lbl_user = QLabel(tr("login.username"))
        lbl_user.setObjectName("fieldLabel")
        layout.addWidget(lbl_user)
        self._login_user = self._input(tr("login.username"))
        layout.addWidget(self._login_user)

        lbl_pw = QLabel(tr("login.password"))
        lbl_pw.setObjectName("fieldLabel")
        layout.addWidget(lbl_pw)
        self._login_pw = self._input(tr("login.password"), password=True)
        self._login_pw.returnPressed.connect(self._do_login)
        layout.addWidget(self._login_pw)

        self._login_error = QLabel("")
        self._login_error.setObjectName("errorLabel")
        self._login_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._login_error.setWordWrap(True)
        self._login_error.setVisible(False)
        layout.addWidget(self._login_error)

        self._login_btn = QPushButton(tr("login.sign_in"))
        self._login_btn.setObjectName("primaryBtn")
        self._login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._login_btn.setMinimumHeight(34)
        self._login_btn.setEnabled(False)
        self._login_btn.clicked.connect(self._do_login)
        layout.addWidget(self._login_btn)

        self._login_user.textChanged.connect(self._update_login_btn_state)
        self._login_pw.textChanged.connect(self._update_login_btn_state)

        self._lockout_timer = QTimer(self)
        self._lockout_timer.setInterval(1000)
        self._lockout_timer.timeout.connect(self._tick_lockout)
        self._lockout_remaining = 0

        self._login_user.setFocus()

    def _build_register_form(self, layout: QVBoxLayout):
        for attr, lbl, ph, pw in [
            ("_reg_user", tr("login.username"), tr("login.username"), False),
            ("_reg_pw",   tr("login.password"), tr("login.pw_min"), True),
            ("_reg_pw2",  tr("login.pw_confirm"), tr("login.pw_repeat"), True),
        ]:
            label = QLabel(lbl)
            label.setObjectName("fieldLabel")
            layout.addWidget(label)
            field = self._input(ph, pw)
            setattr(self, attr, field)
            layout.addWidget(field)

        self._reg_error = QLabel("")
        self._reg_error.setObjectName("errorLabel")
        self._reg_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._reg_error.setVisible(False)
        layout.addWidget(self._reg_error)

        btn = QPushButton(tr("login.create_account").replace("&", "&&"))
        btn.setObjectName("primaryBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(34)
        btn.clicked.connect(self._do_register)
        layout.addWidget(btn)

        # Alternative: no account of one's own, automatic sign-in instead
        keyring_ok = is_keyring_available()
        self._single_btn = QPushButton(tr("login.initial_setup"))
        self._single_btn.setObjectName("secondaryBtn")
        self._single_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._single_btn.setMinimumHeight(34)
        self._single_btn.setEnabled(keyring_ok)
        self._single_btn.clicked.connect(self._initial_single_setup)
        layout.addWidget(self._single_btn)

        single_hint = QLabel(
            tr("login.single_hint") if keyring_ok else tr("login.single_unavailable_keyring")
        )
        single_hint.setObjectName("hintLabel")
        single_hint.setWordWrap(True)
        layout.addWidget(single_hint)

        self._reg_user.setFocus()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _update_login_btn_state(self):
        enabled = bool(self._login_user.text().strip()) and bool(self._login_pw.text())
        self._login_btn.setEnabled(enabled)

    def _do_login(self):
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

        Session.login(user)
        self.accept()

    def _start_lockout_countdown(self, seconds: int, total_failures: int):
        self._lockout_remaining = seconds
        self._login_btn.setEnabled(False)
        self._login_user.setEnabled(False)
        self._login_pw.setEnabled(False)
        self._update_lockout_label()
        self._lockout_timer.start()

    def _tick_lockout(self):
        self._lockout_remaining -= 1
        if self._lockout_remaining <= 0:
            self._lockout_timer.stop()
            self._login_user.setEnabled(True)
            self._login_pw.setEnabled(True)
            self._login_error.setVisible(False)
            self._update_login_btn_state()
            self._login_pw.setFocus()
        else:
            self._update_lockout_label()

    def _update_lockout_label(self):
        s = self._lockout_remaining
        if s >= 86400:
            human = f"{s // 86400}T {(s % 86400) // 3600}h"
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
            Session.login(user)
            self.accept()
        except Exception as e:
            self._show_reg_error(str(e))

    def _initial_single_setup(self):
        if not is_available():
            StyledMessageBox.critical(self, tr("dialog.error"), tr("login.no_crypto"))
            return
        try:
            user = AuthManager.initialize_single_user_mode()
        except Exception as e:
            self._show_reg_error(SingleUserModeError.text_for(e))
            return
        Session.login(user)
        self.accept()

    def _show_login_error(self, msg: str):
        self._login_error.setText(f"⚠ {msg}")
        self._login_error.setVisible(True)

    def _show_reg_error(self, msg: str):
        self._reg_error.setText(f"⚠ {msg}")
        self._reg_error.setVisible(True)

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
