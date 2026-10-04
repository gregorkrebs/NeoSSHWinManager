"""
tests/test_drive_letters.py – Shared drive letters, per-host mount state,
free-letter suggestions and the persisted settings behind them.
"""

import os
import random
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import Connection, PROTOCOL_FTP
from src.drive_utils import (
    assignable_letters, duplicate_letters, norm_letter, resolve_mounted, suggest_free_letter,
)


def _host(name, letter, **kw):
    return Connection(name=name, host=f"{name}.test", user="u", drive_letter=letter, **kw)


class TestNormLetter:
    @pytest.mark.parametrize("value, expected", [
        ("x", "X:"), ("X:", "X:"), ("x:\\", "X:"), (" Q: ", "Q:"),
        ("", None), (None, None), ("XY", None), ("1:", None),
    ])
    def test_norm(self, value, expected):
        assert norm_letter(value) == expected

    def test_assignable_skips_reserved(self):
        letters = assignable_letters()
        assert letters[0] == "D:" and letters[-1] == "Z:"
        assert not {"A:", "B:", "C:"} & set(letters)


class TestDuplicates:
    def test_counts_only_mountable_hosts(self):
        conns = [
            _host("a", "X:"), _host("b", "x:"), _host("c", "Y:"),
            _host("tpl", "Y:", is_template=True),
            _host("ftp", "Y:", protocol=PROTOCOL_FTP),
        ]
        assert duplicate_letters(conns) == {"X:"}


class TestResolveMounted:
    def test_single_owner_without_record(self):
        # Today's behaviour: the only host on a letter that is in use.
        a = _host("a", "X:")
        assert resolve_mounted([a], {}, {"C:", "X:"}) == {a.id: "X:"}

    def test_shared_letter_without_record_is_nobodys(self):
        # Any drive (USB stick …) on a shared letter must not make both look mounted.
        a, b = _host("a", "X:"), _host("b", "X:")
        assert resolve_mounted([a, b], {}, {"X:"}) == {}

    def test_shared_letter_goes_to_recorded_host(self):
        a, b = _host("a", "X:"), _host("b", "X:")
        assert resolve_mounted([a, b], {b.id: "X:"}, {"X:"}) == {b.id: "X:"}

    def test_legacy_record_without_letter(self):
        a, b = _host("a", "X:"), _host("b", "X:")
        assert resolve_mounted([a, b], {a.id: ""}, {"X:"}) == {a.id: "X:"}

    def test_mounted_on_other_letter(self):
        # Auto-picked letter: the host is mounted on Q:, not on its own X:.
        a, b = _host("a", "X:"), _host("b", "X:")
        result = resolve_mounted([a, b], {a.id: "Q:"}, {"X:", "Q:"})
        assert result == {a.id: "Q:"}

    def test_stale_record_is_not_mounted(self):
        a = _host("a", "X:")
        assert resolve_mounted([a], {a.id: "X:"}, {"C:"}) == {}

    def test_letter_belongs_to_one_host_only(self):
        a, b = _host("a", "X:"), _host("b", "Y:")
        result = resolve_mounted([a, b], {a.id: "Z:", b.id: "Z:"}, {"Z:"})
        assert len(result) == 1

    def test_foreign_drive_without_record_is_not_mounted(self):
        # A USB stick / subst on the host's letter is not the host's mount.
        a = _host("a", "X:")
        assert resolve_mounted([a], {}, {"X:"}, ours=set()) == {}
        assert resolve_mounted([a], {}, {"X:"}, ours={"X:"}) == {a.id: "X:"}

    def test_ftp_and_templates_never_mounted(self):
        ftp = _host("ftp", "X:", protocol=PROTOCOL_FTP)
        tpl = _host("tpl", "Y:", is_template=True)
        assert resolve_mounted([ftp, tpl], {}, {"X:", "Y:"}) == {}


class TestSuggest:
    def test_highest_free_letter(self):
        assert suggest_free_letter({"C:", "Z:"}) == "Y:"

    def test_avoid(self):
        assert suggest_free_letter({"Z:"}, avoid={"Y:", "X:"}) == "W:"

    def test_nothing_free(self):
        assert suggest_free_letter(assignable_letters()) is None
        assert suggest_free_letter(set(), avoid=assignable_letters()) is None

    def test_random_stays_free(self):
        in_use = set(assignable_letters()) - {"E:", "K:"}
        rng = random.Random(1)
        for _ in range(20):
            assert suggest_free_letter(in_use, randomize=True, rng=rng) in {"E:", "K:"}


# ── persistence ──────────────────────────────────────────────────────────────

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
    return UserConnectionManager(AppUser(id=uid, username="tester", is_admin=False))


def test_settings_roundtrip(mgr):
    from src.config import AppSettings
    s = mgr.get_settings()
    assert not s.allow_shared_drive_letters and not s.auto_pick_free_drive_letter
    mgr.save_settings(AppSettings(allow_shared_drive_letters=True, auto_pick_free_drive_letter=True))
    s = mgr.get_settings()
    assert s.allow_shared_drive_letters and s.auto_pick_free_drive_letter


def test_active_mounts_keep_actual_letter(mgr):
    mgr.add_active_mount("a", "Q:")
    mgr.add_active_mount("b")
    assert mgr.get_active_mounts() == {"a": "Q:", "b": ""}
    mgr.add_active_mount("a", "R:")            # remount elsewhere: updated
    assert mgr.get_active_mounts()["a"] == "R:"
    mgr.remove_active_mount("a")
    assert mgr.get_active_mounts() == {"b": ""}
