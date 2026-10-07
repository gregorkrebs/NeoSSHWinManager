"""
tests/test_login_dialog.py – Login screen: language picker, the look of the
user who signed in last, password visibility and the Caps Lock hint.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import src.auth_manager as am
    from src.database import init_db
    from src.i18n import set_language
    monkeypatch.setattr(am, "_login_attempts", {})
    init_db()
    set_language("en")
    yield tmp_path
    am.Session.logout()
    set_language("en")


def _settings(user_id, **values):
    from src.database import get_connection
    cols = ", ".join(f"{k} = ?" for k in values)
    with get_connection() as conn:
        conn.execute(f"UPDATE app_settings SET {cols} WHERE user_id = ?", (*values.values(), user_id))


def _language_of(user_id):
    from src.database import get_connection
    with get_connection() as conn:
        return conn.execute("SELECT language FROM app_settings WHERE user_id = ?", (user_id,)).fetchone()[0]


def _pump(app):
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(30, loop.quit)
    loop.exec()


# ── look of the last user ────────────────────────────────────────────────────

def test_appearance_follows_the_last_login(env):
    from src.auth_manager import AuthManager
    alice = AuthManager.register("alice", "password-1")
    bob = AuthManager.register("bob", "password-2")
    _settings(alice.id, theme="light", accent_color="#8b5cf6", language="de")
    _settings(bob.id, theme="gray", accent_color="", language="es")

    # Nobody has signed in since last_login_at exists: the oldest account wins.
    assert AuthManager.login_screen_appearance() == {"theme": "light", "accent": "#8b5cf6", "language": "de"}

    AuthManager.record_login(bob.id)
    assert AuthManager.login_screen_appearance() == {"theme": "gray", "accent": "", "language": "es"}


def test_appearance_before_the_first_account(env):
    from src.auth_manager import AuthManager
    assert AuthManager.login_screen_appearance() == {"theme": "dark", "accent": "", "language": "en"}
    (env / "SSHWinManager" / "install_prefs.json").write_text(
        json.dumps({"language": "nl", "theme": "light"}), encoding="utf-8")
    assert AuthManager.login_screen_appearance() == {"theme": "light", "accent": "", "language": "nl"}


# ── the dialog ───────────────────────────────────────────────────────────────

def test_dialog_uses_the_given_theme(app, env):
    from src.auth_manager import AuthManager
    from src.ui.dialogs.login_dialog import LoginDialog
    AuthManager.register("alice", "password-1")
    dlg = LoginDialog(theme="light")
    assert dlg._fdlg_theme == "light" and not dlg._first_run


def test_language_switch_rebuilds_and_keeps_input(app, env):
    from src.auth_manager import AuthManager
    from src.i18n import current_language
    from src.ui.dialogs.login_dialog import LoginDialog
    AuthManager.register("alice", "password-1")
    dlg = LoginDialog()
    dlg._login_user.setText("alice")
    dlg._login_pw.setText("password-1")

    dlg._lang_combo.setCurrentIndex(dlg._lang_combo.findData("de"))
    _pump(app)
    t = json.load(open(os.path.join(os.path.dirname(__file__), "..", "src", "translations", "de.json"),
                       encoding="utf-8"))
    assert current_language() == "de"
    assert dlg._login_btn.text() == t["login.sign_in"]
    assert dlg.windowTitle() == t["login.title"]
    assert (dlg._login_user.text(), dlg._login_pw.text()) == ("alice", "password-1")
    assert dlg._lang_combo.currentData() == "de"


def test_picked_language_is_kept_for_the_user(app, env):
    from src.auth_manager import AuthManager
    from src.ui.dialogs.login_dialog import LoginDialog
    alice = AuthManager.register("alice", "password-1")
    _settings(alice.id, language="en")

    dlg = LoginDialog()
    dlg._lang_combo.setCurrentIndex(dlg._lang_combo.findData("ru"))
    _pump(app)
    dlg._login_user.setText("alice")
    dlg._login_pw.setText("password-1")
    dlg._do_login()
    assert dlg.result() == dlg.DialogCode.Accepted
    assert _language_of(alice.id) == "ru"


def test_language_untouched_without_a_pick(app, env):
    from src.auth_manager import AuthManager
    from src.i18n import set_language
    from src.ui.dialogs.login_dialog import LoginDialog
    alice = AuthManager.register("alice", "password-1")
    _settings(alice.id, language="nl")
    set_language("es")  # e.g. the language of another user who signed in last

    dlg = LoginDialog()
    dlg._login_user.setText("alice")
    dlg._login_pw.setText("password-1")
    dlg._do_login()
    assert _language_of(alice.id) == "nl"


def test_registration_stores_the_shown_language(app, env):
    from src.i18n import set_language
    from src.auth_manager import Session
    from src.ui.dialogs.login_dialog import LoginDialog
    set_language("es")
    dlg = LoginDialog()
    assert dlg._first_run
    dlg._reg_user.setText("carol")
    dlg._reg_pw.setText("password-3")
    dlg._reg_pw2.setText("password-3")
    dlg._do_register()
    assert _language_of(Session.current().id) == "es"


def test_password_can_be_shown(app, env):
    from PyQt6.QtWidgets import QLineEdit
    from src.auth_manager import AuthManager
    from src.ui.dialogs.login_dialog import LoginDialog
    AuthManager.register("alice", "password-1")
    dlg = LoginDialog()
    toggle = dlg._login_pw.actions()[-1]
    assert dlg._login_pw.echoMode() == QLineEdit.EchoMode.Password
    toggle.trigger()
    assert dlg._login_pw.echoMode() == QLineEdit.EchoMode.Normal
    toggle.trigger()
    assert dlg._login_pw.echoMode() == QLineEdit.EchoMode.Password


def test_caps_lock_hint_only_in_password_fields(app, env, monkeypatch):
    import src.ui.dialogs.login_dialog as ld
    from src.auth_manager import AuthManager
    AuthManager.register("alice", "password-1")
    monkeypatch.setattr(ld, "_caps_lock_on", lambda: True)
    dlg = ld.LoginDialog()
    dlg.show()
    focus = {"w": None}
    monkeypatch.setattr(ld.QApplication, "focusWidget", staticmethod(lambda: focus["w"]))

    focus["w"] = dlg._login_user
    dlg._update_caps_hint()
    assert dlg._caps.isHidden()
    focus["w"] = dlg._login_pw
    dlg._update_caps_hint()
    assert not dlg._caps.isHidden()

    monkeypatch.setattr(ld, "_caps_lock_on", lambda: False)
    dlg._update_caps_hint()
    assert dlg._caps.isHidden()


def test_errors_show_an_icon_not_an_emoji(app, env):
    from PyQt6.QtWidgets import QLabel
    from src.auth_manager import AuthManager
    from src.ui.dialogs.login_dialog import LoginDialog
    AuthManager.register("alice", "password-1")
    dlg = LoginDialog()
    dlg._login_user.setText("alice")
    dlg._login_pw.setText("wrong-password")
    dlg._do_login()
    assert not dlg._login_alert.isHidden()
    assert "⚠" not in dlg._login_error.text()
    assert any(l.pixmap() is not None and not l.pixmap().isNull()
               for l in dlg._login_alert.findChildren(QLabel))
