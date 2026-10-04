"""
tests/test_theme_accent.py – Gray theme, user-chosen accent colour, picker.
"""

import colorsys
import os
import re
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ui import theme
from src.ui.theme import (
    DEFAULT_ACCENT, THEMES, build_stylesheet, normalize_hex, normalize_theme, recolor_accent,
)

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
_RGBA = re.compile(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,")


@pytest.fixture(autouse=True)
def _reset_accent():
    yield
    theme.set_current_accent(DEFAULT_ACCENT)


# ── helpers ──────────────────────────────────────────────────────────────────

class TestNormalize:
    @pytest.mark.parametrize("value, expected", [
        ("#0077b6", "#0077b6"), ("0077B6", "#0077b6"), ("#abc", "#aabbcc"),
        ("  #FFF ", "#ffffff"), ("", None), (None, None), ("#12345", None),
        ("#ggg", None), ("#0077b6ff", None),
    ])
    def test_hex(self, value, expected):
        assert normalize_hex(value) == expected

    def test_theme(self):
        assert [normalize_theme(t) for t in THEMES] == list(THEMES)
        assert normalize_theme("purple") == "dark"
        assert normalize_theme(None) == "dark"
        assert theme.is_light("light") and not theme.is_light("gray")


# ── stylesheets ──────────────────────────────────────────────────────────────

class TestStylesheets:
    @pytest.mark.parametrize("name", THEMES)
    def test_placeholders_filled(self, name):
        sheet = build_stylesheet(name)
        assert "__" not in sheet

    def test_default_accent_is_identity(self):
        assert recolor_accent(theme.STYLESHEET, DEFAULT_ACCENT) == theme.STYLESHEET
        assert recolor_accent(theme.LIGHT_STYLESHEET, "") == theme.LIGHT_STYLESHEET

    @pytest.mark.parametrize("name", THEMES)
    @pytest.mark.parametrize("accent", ["#ff7a00", "#8b5cf6", "#ffeb3b", "#808080", "#000000"])
    def test_custom_accent_replaces_every_teal_shade(self, name, accent):
        sheet = build_stylesheet(name, accent)
        left = {c.lower() for c in _HEX.findall(sheet)} & set(theme._ACCENT_HEX)
        assert not left
        assert not [m for m in _RGBA.finditer(sheet)
                    if tuple(map(int, m.groups())) in theme._ACCENT_RGB]
        for c in _HEX.findall(sheet):
            assert normalize_hex(c)

    def test_shift_keeps_base(self):
        # The base shade becomes exactly the chosen accent.
        assert recolor_accent("#0077b6", "#ff7a00") == "#ff7a00"
        assert recolor_accent("rgba(0, 119, 182, 0.42)", "#ff7a00") == "rgba(255, 122, 0, 0.42)"
        # Semantic colours never change.
        for c in ("#00d464", "#ef4444", "#f59e0b"):
            assert recolor_accent(c, "#ff7a00") == c

    def test_light_accent_gets_dark_button_text(self):
        assert theme.accent_text_color("#ffeb3b") == "#111111"
        assert theme.accent_text_color(DEFAULT_ACCENT) == "#ffffff"
        assert "color: #111111;" in build_stylesheet("dark", "#ffeb3b")
        assert "color: #111111;" not in build_stylesheet("dark", "#8b5cf6")

    def test_gray_sheet_has_no_tinted_neutrals(self):
        keep = set(theme._ACCENT_HEX) | {"#00d464", "#ef4444", "#f59e0b", "#ff8d8d"}
        for c in {c.lower() for c in _HEX.findall(theme.GRAY_STYLESHEET)} - keep:
            r, g, b = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
            _, _, s = colorsys.rgb_to_hls(r, g, b)
            assert s < 0.06, c   # VS Code's own selection gray #37373d is 0.052

    def test_every_dark_neutral_has_a_gray_mapping(self):
        keep = set(theme._ACCENT_HEX) | {"#00d464", "#ef4444", "#f59e0b", "#ff8d8d",
                                         "#ffffff", "#f1f1f1"}
        missing = {c.lower() for c in _HEX.findall(theme.STYLESHEET)} - keep - set(theme._GRAY_MAP)
        assert not missing

    def test_accent_tone_and_terminal_colors_follow_current_accent(self):
        theme.set_current_accent("#ff7a00")
        assert theme.current_accent() == "#ff7a00"
        assert theme.accent_tone("#0077b6") == "#ff7a00"
        assert all(c["accent"] == "#ff7a00" for c in theme.THEME_COLORS.values())
        theme.set_current_accent("nonsense")
        assert theme.current_accent() == DEFAULT_ACCENT

    def test_dark_tone(self):
        assert theme.dark_tone("dark", "#111822") == "#111822"
        assert theme.dark_tone("gray", "#111822") == "#252526"


class TestPalettes:
    def test_file_browser_palette(self):
        from src.filebrowser.ui import style
        assert style.palette("dark") is style.DARK
        assert style.palette("gray") is style.GRAY
        p = style.palette("light", "#ff7a00")
        assert p.accent == "#ff7a00" and "255, 122, 0" in p.hover
        theme.set_current_accent("#ff7a00")
        assert style.palette("gray").accent == "#ff7a00"

    def test_titlebar_palette(self):
        from src.ui.titlebar_theme import GRAY_PALETTE, get_palette
        assert get_palette("gray") is GRAY_PALETTE


# ── persistence ──────────────────────────────────────────────────────────────

def test_accent_color_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from src.auth_manager import AppUser, UserConnectionManager
    from src.config import AppSettings
    from src.database import get_connection, init_db

    init_db()
    uid = str(uuid.uuid4())
    with get_connection() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(app_settings)")]
        assert "accent_color" in cols
        conn.execute(
            "INSERT INTO users (id, username, pw_hash, pw_salt, enc_key_enc, enc_key_iv)"
            " VALUES (?, 'tester', 'x', 'x', 'x', 'x')", (uid,))
    mgr = UserConnectionManager(AppUser(id=uid, username="tester", is_admin=False))
    assert mgr.get_settings().accent_color == ""
    mgr.save_settings(AppSettings(theme="gray", accent_color="#ff7a00"))
    s = mgr.get_settings()
    assert (s.theme, s.accent_color) == ("gray", "#ff7a00")


# ── picker ───────────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_picker_hex_input_and_reset(app):
    from src.ui.widgets.color_picker import AccentColorDialog
    dlg = AccentColorDialog("#8b5cf6")
    seen = []
    dlg.colorChanged.connect(seen.append)

    dlg._hex.setText("#ff7a00")
    dlg._hex.textEdited.emit("#ff7a00")
    assert dlg.color() == "#ff7a00" and seen == ["#ff7a00"]

    dlg._hex.setText("#12")
    dlg._hex.textEdited.emit("#12")
    dlg._hex.editingFinished.emit()
    assert dlg.color() == "#ff7a00" and seen == ["#ff7a00"]   # invalid: ignored

    dlg._hex.setText("abc")
    dlg._hex.editingFinished.emit()
    assert dlg.color() == "#aabbcc"

    dlg._reset_btn.click()
    assert dlg.color() == DEFAULT_ACCENT and seen[-1] == DEFAULT_ACCENT
    assert not dlg._reset_btn.isEnabled()

    # Cancel previews the starting colour again.
    dlg.reject()
    assert seen[-1] == "#8b5cf6"


def test_picker_field_sets_color(app):
    from PyQt6.QtCore import QPointF
    from src.ui.widgets.color_picker import AccentColorDialog
    dlg = AccentColorDialog(DEFAULT_ACCENT)
    dlg._sv.resize(200, 100)
    dlg._sv._pick(QPointF(200, 0))      # full saturation and brightness
    assert dlg.color() != DEFAULT_ACCENT
    assert dlg._hex.text() == dlg.color()
