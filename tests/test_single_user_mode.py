"""
tests/test_single_user_mode.py – Single-user mode (automatic login with the
app password kept in Windows Credential Manager) and switching between the
login modes without losing data.

Credential Manager is replaced by an in-memory store, so the tests never
touch the real one.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fresh database plus a fake Credential Manager; yields the store dict."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import src.auth_manager as am
    from src.database import init_db

    store: dict[str, str] = {}

    def _store(value, name):
        store[name] = value
        return True

    def _delete(name):
        return store.pop(name, None) is not None

    monkeypatch.setattr(am, "is_keyring_available", lambda: True)
    monkeypatch.setattr(am, "store_key_in_credential_manager", _store)
    monkeypatch.setattr(am, "retrieve_key_from_credential_manager", store.get)
    monkeypatch.setattr(am, "delete_key_from_credential_manager", _delete)
    monkeypatch.setattr(am, "_login_attempts", {})
    init_db()
    yield store
    am.Session.logout()


def _add_connection(user, password="s3cret-ssh"):
    from src.auth_manager import UserConnectionManager
    from src.config import Connection
    mgr = UserConnectionManager(user)
    return mgr.add(Connection(id="", name="web", host="example.org", user="root", password=password)).id


def _connection_password(user, conn_id):
    from src.auth_manager import UserConnectionManager
    return UserConnectionManager(user).get_by_id(conn_id).password


def test_off_by_default(env):
    from src.auth_manager import AuthManager
    AuthManager.register("alice", "password123")
    assert not AuthManager.single_user_mode_enabled()
    assert AuthManager.authenticate_single_user() is None


def test_initial_setup_signs_in_automatically(env):
    from src.auth_manager import AuthManager
    user = AuthManager.initialize_single_user_mode()
    assert user.username == "default" and user.is_admin
    assert AuthManager.single_user_mode_enabled()
    assert env[AuthManager._SINGLE_CREDENTIAL]

    again = AuthManager.authenticate_single_user()
    assert again is not None
    assert (again.id, again.enc_key) == (user.id, user.enc_key)


def test_initial_setup_refused_when_users_exist(env):
    from src.auth_manager import AuthManager
    AuthManager.register("alice", "password123")
    with pytest.raises(RuntimeError):
        AuthManager.initialize_single_user_mode()
    assert not AuthManager.single_user_mode_enabled()
    assert env == {}


def test_initial_setup_rolls_back_when_credential_cannot_be_stored(env, monkeypatch):
    import src.auth_manager as am
    monkeypatch.setattr(am, "store_key_in_credential_manager", lambda value, name: False)
    with pytest.raises(RuntimeError):
        am.AuthManager.initialize_single_user_mode()
    assert not am.AuthManager.has_any_users()
    assert not am.AuthManager.single_user_mode_enabled()


def test_unavailable_without_keyring(env, monkeypatch):
    import src.auth_manager as am
    monkeypatch.setattr(am, "is_keyring_available", lambda: False)
    assert not am.AuthManager.can_enable_single_user_mode()
    with pytest.raises(RuntimeError):
        am.AuthManager.initialize_single_user_mode()
    assert not am.AuthManager.has_any_users()


def test_enable_keeps_connections(env):
    from src.auth_manager import AuthManager, Session
    alice = AuthManager.authenticate(*_register("alice", "password123"))
    conn_id = _add_connection(alice)
    Session.login(alice)

    user = AuthManager.enable_single_user_mode()
    assert (user.id, user.username) == (alice.id, "default")
    assert AuthManager.single_user_mode_enabled()
    # The old password no longer opens the account ...
    assert AuthManager.authenticate("alice", "password123") is None
    # ... the stored one does, with the same encryption key.
    auto = AuthManager.authenticate_single_user()
    assert auto.enc_key == alice.enc_key
    assert _connection_password(auto, conn_id) == "s3cret-ssh"


def test_enable_requires_exactly_one_user(env):
    from src.auth_manager import AuthManager, Session
    alice = AuthManager.authenticate(*_register("alice", "password123"))
    AuthManager.register("bob", "password456")
    Session.login(alice)
    with pytest.raises(RuntimeError):
        AuthManager.enable_single_user_mode()
    assert not AuthManager.single_user_mode_enabled()
    assert env == {}
    assert AuthManager.authenticate("alice", "password123") is not None


def test_enable_requires_a_session(env):
    from src.auth_manager import AuthManager
    AuthManager.register("alice", "password123")
    with pytest.raises(RuntimeError):
        AuthManager.enable_single_user_mode()
    assert not AuthManager.single_user_mode_enabled()


def test_switch_back_to_multi_user(env):
    from src.auth_manager import AuthManager, Session
    default = AuthManager.initialize_single_user_mode()
    conn_id = _add_connection(default)
    Session.login(default)

    user = AuthManager.migrate_single_user_to_multi_user("  carol ", "new-password")
    assert (user.id, user.username) == (default.id, "carol")
    assert Session.current().username == "carol"
    assert not AuthManager.single_user_mode_enabled()
    assert AuthManager._SINGLE_CREDENTIAL not in env
    assert AuthManager.authenticate_single_user() is None

    carol = AuthManager.authenticate("carol", "new-password")
    assert carol.enc_key == default.enc_key
    assert _connection_password(carol, conn_id) == "s3cret-ssh"


@pytest.mark.parametrize("username, password", [("ab", "new-password"), ("carol", "short")])
def test_switch_back_validates_input(env, username, password):
    from src.auth_manager import AuthManager
    AuthManager.initialize_single_user_mode()
    with pytest.raises(ValueError):
        AuthManager.migrate_single_user_to_multi_user(username, password)
    assert AuthManager.single_user_mode_enabled()


def test_missing_credential_falls_back_to_login_dialog(env):
    from src.auth_manager import AuthManager
    AuthManager.initialize_single_user_mode()
    env.clear()
    assert AuthManager.authenticate_single_user() is None


def test_login_attempts_not_loaded_before_init_db():
    """main.py imports AuthManager only after the permission repair and
    init_db(), because importing it already reads the database."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()
    head, _, body = src.partition("def main():")
    assert "src.auth_manager" not in head
    assert "src.ui.main_window" not in head
    assert body.index("init_db()") < body.index("from src.auth_manager import AuthManager, Session")


def _register(username, password):
    from src.auth_manager import AuthManager
    AuthManager.register(username, password)
    return username, password
