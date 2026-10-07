"""
tests/test_connection_filter.py – Text filter of the connection list: what
matches, and that the filter text is kept, encrypted, until it is changed.
"""

import os
import sys
import uuid
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.connection_filter import matches, terms

CONN = SimpleNamespace(name="Rabenschlag.de", host="home130328193.1and1-data.host", user="u38382119")


@pytest.mark.parametrize("query", [
    "", "   ", "raben", "RABEN", "1and1", "u3838", "u38382119@home", "raben 1and1", "  raben   u383  ",
])
def test_matches(query):
    assert matches(CONN, query)


@pytest.mark.parametrize("query", ["armhosting", "raben armhosting", "@armhosting", "kunde"])
def test_does_not_match(query):
    assert not matches(CONN, query)


def test_terms_and_missing_fields():
    assert terms(" Foo  BAR ") == ["foo", "bar"]
    assert terms(None) == []
    assert matches(SimpleNamespace(name="x", host=None, user=None), "x")


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from src.auth_manager import AppUser, UserConnectionManager
    from src.database import get_connection, init_db
    init_db()
    uid = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (id, username, pw_hash, pw_salt, enc_key_enc, enc_key_iv)"
            " VALUES (?, 'tester', 'x', 'x', 'x', 'x')", (uid,))
    return UserConnectionManager(AppUser(id=uid, username="tester", is_admin=False, _enc_key=os.urandom(32)))


def test_filter_text_is_kept_encrypted(mgr):
    from src.database import get_connection
    assert mgr.get_connection_filter() == ""
    mgr.save_connection_filter("armhosting")
    assert mgr.get_connection_filter() == "armhosting"
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM app_settings").fetchone()
    assert "armhosting" not in " ".join(str(v) for v in tuple(row))


def test_saving_the_settings_keeps_the_filter(mgr):
    from src.config import AppSettings
    mgr.save_connection_filter("kunde")
    mgr.save_settings(AppSettings(theme="gray"))
    assert mgr.get_connection_filter() == "kunde"
    mgr.save_connection_filter("")
    assert mgr.get_connection_filter() == ""
