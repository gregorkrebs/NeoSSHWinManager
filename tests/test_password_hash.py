"""
tests/test_password_hash.py – The stored password hash must never be the key
that wraps a user's encryption key.

Up to 1.7.2 users.pw_hash was PBKDF2(password, pw_salt), the same value
derive_key() returns for accounts whose enc_key_kdf is still 'pbkdf2': the
database alone unwrapped those accounts' keys and with them every stored SSH
password.
"""

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import crypto  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import src.auth_manager as am
    from src.database import init_db
    monkeypatch.setattr(am, "_login_attempts", {})
    init_db()
    yield
    am.Session.logout()


def _insert_legacy_user(username: str, password: str) -> tuple[str, bytes]:
    """An account as 1.7.2 left it: version-1 hash, key wrapped with PBKDF2."""
    from src.database import get_connection
    salt = os.urandom(32).hex()
    pw_hash = crypto.derive_key(password, salt).hex()      # what hash_password() used to store
    enc_key = crypto.generate_enc_key()
    enc_key_enc, enc_key_iv = crypto.encrypt_key(enc_key, password, salt, kdf="pbkdf2")
    user_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO users (id, username, pw_hash, pw_salt, pw_hash_ver,
                                  enc_key_enc, enc_key_iv, enc_key_kdf)
               VALUES (?, ?, ?, ?, 1, ?, ?, 'pbkdf2')""",
            (user_id, username, pw_hash, salt, enc_key_enc, enc_key_iv),
        )
        conn.execute("INSERT INTO app_settings (user_id) VALUES (?)", (user_id,))
    return user_id, enc_key


def _row(user_id):
    from src.database import get_connection
    with get_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def _unwraps_with_stored_hash(row) -> bool:
    try:
        crypto.decrypt(row["enc_key_enc"], row["enc_key_iv"], bytes.fromhex(row["pw_hash"]))
        return True
    except Exception:
        return False


def test_current_hash_verifies_and_is_not_a_key():
    pw_hash, salt = crypto.hash_password("correct horse")
    assert crypto.verify_password("correct horse", pw_hash, salt, crypto.PW_HASH_CURRENT)
    assert not crypto.verify_password("wrong", pw_hash, salt, crypto.PW_HASH_CURRENT)
    # Neither wrapping key may equal the stored value.
    assert crypto.derive_key("correct horse", salt).hex() != pw_hash
    assert crypto._argon2("correct horse", bytes.fromhex(salt)).hex() != pw_hash


def test_wrapped_legacy_hash_still_verifies():
    salt = os.urandom(32).hex()
    legacy = crypto.derive_key("pw", salt).hex()
    wrapped = crypto.wrap_legacy_password_hash(legacy)
    assert wrapped != legacy
    assert crypto.verify_password("pw", wrapped, salt, crypto.PW_HASH_WRAPPED)
    assert not crypto.verify_password("nope", wrapped, salt, crypto.PW_HASH_WRAPPED)


def test_unknown_version_or_garbage_never_verifies():
    pw_hash, salt = crypto.hash_password("pw")
    assert not crypto.verify_password("pw", pw_hash, salt, 99)
    assert not crypto.verify_password("pw", "not-hex", salt, crypto.PW_HASH_CURRENT)


def test_startup_migration_separates_hash_from_key_without_password(db):
    from src.database import init_db
    user_id, _ = _insert_legacy_user("legacy", "old-password")
    assert _unwraps_with_stored_hash(_row(user_id))       # the 1.7.2 weakness

    init_db()                                            # next program start

    row = _row(user_id)
    assert row["pw_hash_ver"] == crypto.PW_HASH_WRAPPED
    assert not _unwraps_with_stored_hash(row)
    init_db()                                            # idempotent
    assert _row(user_id)["pw_hash"] == row["pw_hash"]


def test_legacy_account_signs_in_and_moves_to_current_format(db):
    from src.auth_manager import AuthManager
    from src.database import init_db
    user_id, enc_key = _insert_legacy_user("legacy", "old-password")
    init_db()

    assert AuthManager.authenticate("legacy", "wrong") is None
    user = AuthManager.authenticate("legacy", "old-password")
    assert user is not None and user.enc_key == enc_key

    row = _row(user_id)
    assert row["pw_hash_ver"] == crypto.PW_HASH_CURRENT
    assert row["enc_key_kdf"] == "argon2"
    assert not _unwraps_with_stored_hash(row)
    # Signing in again works with the migrated record and yields the same key.
    assert AuthManager.authenticate("legacy", "old-password").enc_key == enc_key


def test_register_and_change_password_store_current_format(db):
    from src.auth_manager import AuthManager
    user = AuthManager.register("alice", "password123")
    assert _row(user.id)["pw_hash_ver"] == crypto.PW_HASH_CURRENT
    assert AuthManager.change_password(user.id, "password123", "password456")
    row = _row(user.id)
    assert row["pw_hash_ver"] == crypto.PW_HASH_CURRENT
    assert AuthManager.authenticate("alice", "password456").enc_key == user.enc_key
    assert AuthManager.authenticate("alice", "password123") is None


def test_unknown_user_costs_a_real_hash(db, monkeypatch):
    import src.auth_manager as am
    calls = []
    real = am.verify_password
    monkeypatch.setattr(am, "verify_password", lambda *a: calls.append(a) or real(*a))
    assert am.AuthManager.authenticate("nobody", "pw") is None
    assert len(calls) == 1 and calls[0][3] == crypto.PW_HASH_CURRENT
