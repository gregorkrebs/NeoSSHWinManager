"""
tests/test_tips.py – The tips in the empty overview: every tip is translated,
and each one only shows up where it fits the user's setup.
"""

import json
import os
import pathlib
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import AppSettings, Connection, PROTOCOL_FTP, PROTOCOL_FTPS
from src.tips import TIPS, TipContext, eligible, pick_tip

ROOT = pathlib.Path(__file__).resolve().parent.parent
LANGS = ("en", "de", "es", "nl", "ru", "ar")


def _translations(lang):
    with open(ROOT / "src" / "translations" / f"{lang}.json", encoding="utf-8") as f:
        return json.load(f)


def _ids(ctx):
    return {t.id for t in eligible(ctx)}


def _conn(name, **kw):
    return Connection(name=name, host="example.org", user="root", **kw)


def test_every_tip_is_translated_in_every_language():
    keys = {t.key for t in TIPS} | {t.title_key for t in TIPS} | {"tip.next"}
    for lang in LANGS:
        t = _translations(lang)
        assert keys <= set(t), (lang, keys - set(t))
        # no texts left behind for tips that are gone
        assert {k for k in t if k.startswith("tip.")} == keys, lang


def test_enough_tips_and_jokes():
    assert len({t.id for t in TIPS}) == len(TIPS)
    assert sum(not t.funny for t in TIPS) >= 40
    assert sum(t.funny for t in TIPS) >= 5


def test_every_joke_has_a_heading_of_its_own():
    jokes = [t for t in TIPS if t.funny]
    for lang in LANGS:
        t = _translations(lang)
        headings = [t[j.title_key] for j in jokes]
        assert len(set(headings)) == len(jokes), lang
        assert t["tip.title"] not in headings, lang


def test_single_user_tip_only_for_the_one_password_account():
    offer = TipContext(is_admin=True, single_user=False, can_go_single=True)
    assert "single_user_on" in _ids(offer)
    # more than one account, or no Credential Manager
    assert "single_user_on" not in _ids(TipContext(is_admin=True, can_go_single=False))
    # already on: the tip about creating an account instead
    on = TipContext(is_admin=True, single_user=True)
    assert "single_user_on" not in _ids(on)
    assert "single_user_account" in _ids(on)
    # login tips make no sense without a login
    assert not {"login_lockout", "login_language"} & _ids(on)
    # only an admin reaches the user management
    assert "single_user_account" not in _ids(TipContext(single_user=True))


def test_tips_about_a_setting_disappear_once_it_is_on():
    hosts = [_conn("web")]
    off = TipContext.collect(AppSettings(), hosts)
    on = TipContext.collect(AppSettings(start_with_windows=True, auto_reconnect=True,
                                        sshfs_disable_cache=True, telemetry_enabled=True,
                                        accent_color="#ff8800", background_network=False), hosts)
    tips = {"start_with_windows", "auto_connect", "dir_cache", "telemetry", "accent",
            "background_network"}
    assert tips <= _ids(off)
    assert not tips & _ids(on)


def test_terminal_tips_follow_the_chosen_terminal():
    hosts = [_conn("web")]
    xterm = _ids(TipContext.collect(AppSettings(terminal_client="xterm"), hosts))
    putty = _ids(TipContext.collect(AppSettings(terminal_client="putty"), hosts))
    assert "terminal_tabs" in xterm and "putty_ppk" not in xterm
    assert "putty_ppk" in putty and "terminal_tabs" not in putty


def test_no_connections_yet():
    ctx = TipContext.collect(AppSettings(), [])
    ids = _ids(ctx)
    assert "first_connection" in ids
    assert not {"list_shortcuts", "file_browser", "mount_all", "system_info", "fb_split"} & ids
    # shown first, before any other tip
    assert pick_tip(ctx).id == "first_connection"
    assert pick_tip(ctx, ["first_connection"]).id != "first_connection"


def test_ftp_hosts_get_the_ftp_tips_but_no_drive_tips():
    ftp = TipContext.collect(AppSettings(), [_conn("old", protocol=PROTOCOL_FTP, port=21)])
    assert {"ftp_plain", "ftp_explorer", "file_browser"} <= _ids(ftp)
    assert not {"status_folder", "system_info", "fb_archive", "ghost_drives"} & _ids(ftp)
    ftps = TipContext.collect(AppSettings(), [_conn("safe", protocol=PROTOCOL_FTPS, port=21)])
    assert "ftp_plain" not in _ids(ftps)


def test_collect_reads_the_connections():
    conns = [
        _conn("a", groups="web, prod", auth_method="password", cli_access_enabled=True),
        _conn("b", auth_method="key"),
        _conn("c", protocol=PROTOCOL_FTP, port=21),
    ]
    tpl = [_conn("tpl", is_template=True)]
    ctx = TipContext.collect(AppSettings(), conns, tpl, [conns[0].id, "gone"])
    assert (ctx.connections, ctx.ssh_connections, ctx.mounted) == (3, 2, 1)
    assert ctx.has_groups and ctx.has_templates and ctx.has_plain_ftp
    assert ctx.password_auth and ctx.key_auth and ctx.cli_access
    assert "key_auth" not in _ids(ctx)          # already uses a key somewhere
    assert {"cli_history", "groups_mount", "templates_use", "quit_keep_mounted"} <= _ids(ctx)
    assert not {"cli", "groups_intro", "templates_intro"} & _ids(ctx)
    blank = TipContext.collect(AppSettings(), [_conn("x", groups=" , ")])
    assert not blank.has_groups


def test_pick_tip_does_not_repeat_itself():
    ctx = TipContext.collect(AppSettings(), [_conn("web"), _conn("db")])
    pool = _ids(ctx)
    rng = random.Random(7)
    seen = []
    for _ in range(len(pool)):
        seen.append(pick_tip(ctx, seen, rng).id)
    assert set(seen) == pool                    # every tip once before any comes back
    for _ in range(50):                         # history longer than the pool
        tip = pick_tip(ctx, seen, rng)
        assert tip.id != seen[-1]
        seen.append(tip.id)
