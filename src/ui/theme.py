"""
theme.py - Global stylesheets for SSH Win Manager.

Four themes share two hand-written sheets. "blue" (STYLESHEET, shown as
"Blue (classic)") is the original navy look; "dark" (shown as "Black"), a
classic dark mode, and "gray" are derived from it by mapping its navy-tinted
neutrals onto plain blacks (see _to_black) or VS Code's gray palette (see
_to_gray); "light" has a sheet of its own (LIGHT_STYLESHEET). Up to 1.6.1,
"dark" was the navy look: settings that stored "dark" now show black.

The accent is the default teal DEFAULT_ACCENT plus a family of shades around
it. A user-chosen accent is applied by moving every one of those shades onto
the new hue (recolor_accent), so hover, border and tint colours keep their
relationship to the base colour whatever the user picks.
"""

import colorsys
import re
from functools import lru_cache
from pathlib import Path


_ICON_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"
_CHECKMARK_URL = str(_ICON_DIR / "check.svg").replace("\\", "/")
_CHEVRON_URL = str(_ICON_DIR / "chevron-down.svg").replace("\\", "/")

THEMES = ("dark", "blue", "gray", "light")
DEFAULT_ACCENT = "#0077b6"

THEME_COLORS = {
    "dark": {
        "background": "#000000",
        "surface": "#0a0a0a",
        "text": "#cccccc",
        "accent": DEFAULT_ACCENT
    },
    "blue": {
        "background": "#0d0d12",
        "surface": "#0D1117",
        "text": "#c8d6e5",
        "accent": DEFAULT_ACCENT
    },
    "gray": {
        "background": "#181818",
        "surface": "#1f1f1f",
        "text": "#cccccc",
        "accent": DEFAULT_ACCENT
    },
    "light": {
        "background": "#f0f2f5",
        "surface": "#ffffff",
        "text": "#1a2332",
        "accent": DEFAULT_ACCENT
    }
}


def normalize_theme(theme) -> str:
    """Return *theme* if it is a known theme name, otherwise "dark"."""
    return theme if theme in THEMES else "dark"


def is_light(theme) -> bool:
    """True for the light theme; "dark", "blue" and "gray" are dark themes."""
    return theme == "light"


_HEX_RE = re.compile(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def normalize_hex(value) -> str | None:
    """'#abc', 'abc', '#AABBCC' -> '#aabbcc'; anything else -> None."""
    m = _HEX_RE.fullmatch((value or "").strip())
    if not m:
        return None
    digits = m.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return "#" + digits.lower()


# ── Accent ─────────────────────────────────────────────────────────────────

# Every shade of the default teal used by the sheets (and by a few widgets
# that paint their own colours). recolor_accent() replaces exactly these.
_ACCENT_HEX = (
    # base and the shades around it (hover, pressed, borders, gradients)
    "#0077b6", "#0088c8", "#005a8a", "#005a8e", "#0066a0", "#005fa3",
    "#009add", "#006fb8", "#004a75", "#0f7cb2", "#0099d8", "#1590cf",
    "#00b4d8", "#22c4e8", "#38d4f8", "#47c3ff", "#58a6ff", "#72add6",
    "#7ddfff",
    # dark tints: pill, mounted/selected card and link-hover backgrounds
    "#0f2430", "#0d2137", "#0a1929", "#10202a", "#172531",
    # the same tints in the gray theme (see _GRAY_MAP)
    "#1a303d", "#222e35", "#283139", "#1a2b3d", "#14212e",
    # light tints: hover and selection fills of the light theme
    "#c7dfef", "#d0e6f5", "#e0eef8", "#dff1fb", "#e8f6fb", "#edf5fb",
    "#edf7fc",
)
_ACCENT_RGB = ((0, 119, 182), (71, 195, 255), (125, 223, 255))

_ACCENT_RE = re.compile(
    r"#(?:%s)\b|rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,"
    % "|".join(h[1:] for h in _ACCENT_HEX),
    re.IGNORECASE,
)


def _hex_rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _hls(rgb) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb))


_BASE_HLS = _hls(_hex_rgb(DEFAULT_ACCENT))


@lru_cache(maxsize=4096)
def _shift_rgb(shade: tuple[int, int, int], accent: str) -> tuple[int, int, int]:
    """Move one shade of the default accent onto *accent*."""
    sh, sl, ss = _hls(shade)
    ah, al, as_ = _hls(_hex_rgb(accent))
    bh, bl, bs = _BASE_HLS
    h = (ah + sh - bh) % 1.0
    s = ss * as_ / bs
    # Mid shades (hover, borders, gradients) follow the accent's lightness.
    # Very dark tints (backgrounds) and very light ones (text on dark, fills
    # on light) keep their own lightness so they stay readable on any accent.
    l = sl + (al - bl) if 0.2 <= sl <= 0.6 else sl
    r, g, b = colorsys.hls_to_rgb(h, min(max(l, 0.0), 1.0), min(max(s, 0.0), 1.0))
    return round(r * 255), round(g * 255), round(b * 255)


def recolor_accent(text: str, accent: str) -> str:
    """Replace every default-accent shade in *text* with its *accent* version."""
    accent = normalize_hex(accent) or DEFAULT_ACCENT
    if accent == DEFAULT_ACCENT:
        return text

    def sub(m):
        if m.group(1) is None:
            return "#%02x%02x%02x" % _shift_rgb(_hex_rgb(m.group(0)), accent)
        rgb = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if rgb not in _ACCENT_RGB:
            return m.group(0)
        return "rgba(%d, %d, %d," % _shift_rgb(rgb, accent)

    return _ACCENT_RE.sub(sub, text)


def _luminance(color: str) -> float:
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _hex_rgb(color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _apca_contrast(text: str, background: str) -> float:
    """Lightness contrast |Lc| of *text* on *background* after APCA
    (SAPC 0.0.98G), which tracks how readable text looks better than the
    WCAG 2 ratio, above all on saturated colours."""
    def y(color):
        r, g, b = (c / 255 for c in _hex_rgb(color))
        return 0.2126729 * r ** 2.4 + 0.7151522 * g ** 2.4 + 0.0721750 * b ** 2.4

    def clamp(v):
        return v if v > 0.022 else v + (0.022 - v) ** 1.414

    yt, yb = clamp(y(text)), clamp(y(background))
    if abs(yb - yt) < 0.0005:
        return 0.0
    if yb > yt:                                  # dark text on a light colour
        sapc = (yb ** 0.56 - yt ** 0.57) * 1.14
        return 0.0 if sapc < 0.1 else (sapc - 0.027) * 100
    sapc = (yb ** 0.65 - yt ** 0.62) * 1.14      # light text on a dark colour
    return 0.0 if sapc > -0.1 else -(sapc + 0.027) * 100


def _wcag_contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def accent_text_color(accent: str) -> str:
    """Text colour that stays readable on a button filled with *accent*,
    found automatically: white while it reads comfortably there (an APCA
    contrast of 65 or more, as on blue, violet, red or pink), otherwise
    white or near-black, whichever has the higher contrast (bright accents
    such as orange, a vivid green or yellow get dark text)."""
    accent = normalize_hex(accent) or DEFAULT_ACCENT
    if _apca_contrast("#ffffff", accent) >= 65:
        return "#ffffff"
    return max(("#ffffff", "#111111"), key=lambda text: _wcag_contrast(text, accent))


# Primary buttons are filled with the accent and carry light text; a light
# accent (yellow, light green …) needs dark text instead.
_ON_ACCENT_RULE = """
#actionBtn[btn_type="primary"], #primaryBtn,
QPushButton#settingsActionBtn[btn_type="primary"],
QPushButton#rpActionBtn[btn_type="primary"] {
    color: %s;
}
"""

_current_accent = DEFAULT_ACCENT
_current_accent_text = ""       # chosen text colour on the accent; "" = automatic


def set_current_accent(accent, text_color="") -> None:
    """Set the accent used by get_stylesheet() and accent_tone(), and the
    text colour on it ("" or anything invalid: found automatically)."""
    global _current_accent, _current_accent_text
    _current_accent = normalize_hex(accent) or DEFAULT_ACCENT
    _current_accent_text = normalize_hex(text_color) or ""
    # The terminal (terminal_panel.load_session) reads its cursor and
    # selection colour from THEME_COLORS.
    for colors in THEME_COLORS.values():
        colors["accent"] = _current_accent


def current_accent() -> str:
    return _current_accent


def current_accent_text() -> str:
    """The text colour chosen for the current accent; "" = automatic."""
    return _current_accent_text


def text_on_accent(accent: str | None = None) -> str:
    """The colour of text on *accent* (default: the current accent): the
    one the user chose for the current accent, else found automatically."""
    if accent is None or normalize_hex(accent) == _current_accent:
        return _current_accent_text or accent_text_color(_current_accent)
    return accent_text_color(accent)


def accent_tone(default_shade: str) -> str:
    """The current accent's version of a shade of the default teal,
    e.g. accent_tone("#00b4d8") for the bright cyan used on icons."""
    return recolor_accent(default_shade, _current_accent)


@lru_cache(maxsize=16)
def build_stylesheet(theme: str = "dark", accent: str = DEFAULT_ACCENT, text_color: str = "") -> str:
    """Return the application stylesheet for *theme* in *accent*, with
    *text_color* on accent-filled buttons ("" = found automatically)."""
    theme = normalize_theme(theme)
    accent = normalize_hex(accent) or DEFAULT_ACCENT
    sheet = {"dark": BLACK_STYLESHEET, "blue": STYLESHEET, "gray": GRAY_STYLESHEET,
             "light": LIGHT_STYLESHEET}[theme]
    sheet = recolor_accent(sheet, accent)
    chosen = normalize_hex(text_color)
    if chosen:
        sheet += _ON_ACCENT_RULE % chosen
    elif accent_text_color(accent) != "#ffffff":
        sheet += _ON_ACCENT_RULE % accent_text_color(accent)
    return (
        sheet.replace("__CHECKMARK_URL__", _CHECKMARK_URL)
        .replace("__CHEVRON_URL__", _CHEVRON_URL)
        .replace("__SURFACE__", THEME_COLORS[theme]["surface"])
    )


def get_stylesheet(theme: str = "dark") -> str:
    """Return the stylesheet for *theme* in the current accent."""
    return build_stylesheet(normalize_theme(theme), _current_accent, _current_accent_text)


STYLESHEET = """
/* ============================================================
    NEO SSH-Win Manager - Modern Cyber Theme (v2.0)
   ============================================================ */

/* ---- Custom Titlebar (dark) ------------------------------- */
/* The darker tone of the window frame, like the sidebar below it. */
#customTitlebar {
    background-color: #0a0a0f;
    border-bottom: 1px solid #1a1a2e;
}
#customTitlebarTitle {
    color: #c8d6e5;
    font-family: "Segoe UI", sans-serif;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
#customTitlebarVersion {
    color: #8fa4b8;
    font-family: "Consolas";
    font-size: 10px;
    background: transparent;
    padding: 0 4px;
}
#fwOuter {
    background-color: #0d0d12;
}

/* ---- Global Bases ----------------------------------------- */
QWidget {
    color: #c8d6e5;
    font-family: "Inter", "Segoe UI", sans-serif;
    font-size: 13px;
    border: none;
    outline: none;
}

QLabel, QCheckBox, QRadioButton, QGroupBox {
    background: transparent;
}

/* ---- Checkboxes ------------------------------------------- */
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1.5px solid #243243;
    background-color: #14141f;
}
QCheckBox::indicator:hover {
    border-color: #3a5068;
}
QCheckBox::indicator:checked {
    width: 16px;
    height: 16px;
    background-color: #0077b6;
    border: 1.5px solid #005a8a;
    image: url("__CHECKMARK_URL__");
}
QCheckBox::indicator:checked:hover {
    width: 16px;
    height: 16px;
    background-color: #0088c8;
    border: 1.5px solid #0066a0;
    image: url("__CHECKMARK_URL__");
}

/* ---- Radio Buttons --------------------------------------- */
QRadioButton {
    spacing: 8px;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1.5px solid #243243;
    background-color: #14141f;
}
QRadioButton::indicator:hover {
    border-color: #3a5068;
}
QRadioButton::indicator:checked {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1.5px solid #005a8a;
    background-color: #0077b6;
    image: url("__CHECKMARK_URL__");
}
QRadioButton::indicator:checked:hover {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1.5px solid #0066a0;
    background-color: #0088c8;
    image: url("__CHECKMARK_URL__");
}

/* ---- Main Window ------------------------------------------ */
#MainWindow {
    background-color: #0d0d12;
}

/* ---- Sidebar / Left Panel --------------------------------- */
#sidePanel {
    background-color: #0a0a0f;
    border-right: 1px solid #1a1a2e;
}

/* ---- Scroll Area ------------------------------------------ */
#connectionScroll {
    background-color: transparent;
    border: none;
}

/* --- Dialog Elements --- */
#dialogTitle {
    color: #0077b6;
    font-size: 18px;
    font-weight: bold;
    margin-bottom: 5px;
}

#dialogIconLarge {
    font-size: 36px;
    background: transparent;
    margin-bottom: 5px;
}

#sectionLabel {
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    padding-top: 10px;
}

#fieldLabel {
    color: #8b949e;
    font-size: 12px;
}

#hintLabel {
    color: #5a6d7e;
    font-size: 11px;
}

#ctrlRowLabel {
    color: #9ab0c5;
    font-size: 12px;
    font-weight: 600;
}

/* ---- Settings Cards (per-section) ------------------------ */
#settingsGroupCard {
    background-color: #0f1720;
    border: 1px solid #1a2738;
    border-radius: 14px;
}

#settingsRow {
    background: transparent;
    border-radius: 0px;
}

#settingsRow:hover {
    background: rgba(255, 255, 255, 0.025);
}

#rowSep {
    background-color: rgba(255, 255, 255, 0.05);
    max-height: 1px;
    min-height: 1px;
    margin: 0 14px;
}

#rowLabel {
    color: #c8d6e5;
    font-size: 13px;
}

QPushButton#settingsActionBtn {
    background-color: #141d28;
    border: 1px solid #243243;
    border-radius: 10px;
    color: #9ab0c5;
    font-size: 12px;
    font-weight: 600;
    padding: 0 14px;
    text-align: center;
}
QPushButton#settingsActionBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
    color: #deebf7;
}
QPushButton#settingsActionBtn:disabled {
    background-color: #111822;
    border: 1px solid #1a2330;
    color: #3a4a5a;
}
QPushButton#settingsActionBtn[btn_type="primary"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0088c8, stop:1 #005fa3);
    border: none;
    color: #fff;
    font-weight: 700;
}
QPushButton#settingsActionBtn[btn_type="primary"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #009add, stop:1 #006fb8);
}

#errorLabel {
    color: #ef4444;
    font-size: 12px;
}

#mutedLabel {
    color: #6a7a8a;
    font-size: 12px;
}

#accentLabel {
    color: #0077b6;
    font-size: 11px;
}

#secondaryTitle {
    color: #e4eaf0;
    font-size: 11px;
    font-weight: bold;
}

#divider {
    background-color: rgba(255, 255, 255, 0.05);
}

#dialogHeroCard, #dialogSectionCard {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 18px;
}

#dialogLead {
    color: #8fa4b8;
    font-size: 13px;
}

#dialogPill {
    background-color: #0f2430;
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 10px;
    font-weight: 700;
    border: 1px solid rgba(125, 223, 255, 0.24);
    border-radius: 8px;
    padding: 4px 10px;
}

/* ---- Login screen ----------------------------------------- */
QFrame#loginRoot {
    background: qradialgradient(cx:0.5, cy:0, radius:0.9, fx:0.5, fy:0,
        stop:0 rgba(0, 119, 182, 0.26), stop:0.75 rgba(0, 119, 182, 0));
}
QFrame#loginCard {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 16px;
}
QLabel#loginHeadline {
    color: #e6edf3;
    font-size: 22px;
    font-weight: 700;
    background: transparent;
}
QLabel#loginSubline {
    color: #8fa4b8;
    font-size: 13px;
    background: transparent;
}
QLabel#loginFieldLabel {
    color: #9ab0c5;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
QLineEdit#loginInput {
    background-color: #0d1117;
    border: 1px solid #243243;
    border-radius: 10px;
    color: #e6edf3;
    font-size: 14px;
    padding: 0 6px;
    min-height: 40px;
}
QLineEdit#loginInput:hover {
    border: 1px solid #36506c;
}
QLineEdit#loginInput:focus {
    border: 1px solid #0077b6;
    background-color: #0f1720;
}
QLineEdit#loginInput:disabled {
    color: #556070;
    border: 1px solid #1a2330;
}
QComboBox#loginLangCombo {
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid #243243;
    border-radius: 15px;
    color: #c1cfdd;
    font-size: 12px;
    padding: 0 6px 0 10px;
    min-height: 30px;
    max-height: 30px;
}
QComboBox#loginLangCombo:hover {
    border: 1px solid #36506c;
    color: #deebf7;
}
QComboBox#loginLangCombo::drop-down { width: 22px; border: none; background: transparent; }
QComboBox#loginLangCombo::down-arrow { margin-right: 8px; width: 10px; height: 10px; }
QPushButton#primaryBtn[size="large"] {
    min-height: 42px;
    max-height: 42px;
    border-radius: 12px;
    font-size: 14px;
}
QPushButton#secondaryBtn[size="large"] {
    min-height: 40px;
    max-height: 40px;
    border-radius: 12px;
}
QFrame#loginOrLine {
    background-color: #1f2b3a;
    min-height: 1px;
    max-height: 1px;
}
QLabel#loginOrLabel {
    color: #5a6d7e;
    font-size: 11px;
    font-weight: 600;
    background: transparent;
}
QFrame#loginAlert {
    background-color: rgba(239, 68, 68, 0.10);
    border: 1px solid rgba(239, 68, 68, 0.35);
    border-radius: 10px;
}
QLabel#loginAlertText {
    color: #ff8d8d;
    font-size: 12px;
    background: transparent;
}
QLabel#loginCapsText {
    color: #f59e0b;
    font-size: 11px;
    background: transparent;
}
QLabel#loginHint {
    color: #5a6d7e;
    font-size: 11px;
    background: transparent;
}

QLabel#dialogLink {
    color: #7ddfff;
    font-size: 13px;
    font-weight: 600;
}

QPushButton#dialogMaximizeBtn {
    background-color: #141d28;
    border: 1px solid #243243;
    border-radius: 10px;
}
QPushButton#dialogMaximizeBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
}
QPushButton#dialogMaximizeBtn:checked {
    background-color: rgba(0, 119, 182, 0.15);
    border: 1px solid rgba(0, 119, 182, 0.42);
}

#sysinfoHeroCard, #sysinfoSectionCard, #sysinfoStateCard {
    background-color: transparent;
    border: none;
}

#sysinfoLoadingOverlay {
    background-color: rgba(8, 12, 18, 120);
}
#sysinfoLoadingCard {
    background-color: rgba(17, 24, 34, 246);
    border: 1px solid rgba(71, 195, 255, 0.26);
    border-radius: 18px;
    min-width: 260px;
}
#sysinfoLoadingIcon {
    color: #7ddfff;
    font-size: 26px;
}
#sysinfoLoadingTitle {
    color: #edf4fb;
    font-size: 14px;
    font-weight: 700;
}
#sysinfoLoadingDots {
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 16px;
    font-weight: 700;
    min-height: 18px;
}

#sysinfoHeroTitle {
    color: #edf4fb;
    font-size: 18px;
    font-weight: 700;
}

#sysinfoHeroMeta {
    color: #8fa4b8;
    font-size: 12px;
}

#sysinfoStatePill {
    background-color: #0f2430;
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 10px;
    font-weight: 700;
    border: 1px solid rgba(125, 223, 255, 0.24);
    border-radius: 8px;
    padding: 8px 10px;
}
#sysinfoStatePill[connected="false"] {
    background-color: rgba(239, 68, 68, 0.12);
    color: #ff8d8d;
    border: 1px solid rgba(239, 68, 68, 0.30);
}

#sysinfoStateText {
    color: #8fa4b8;
    font-size: 12px;
}

#sysinfoErrorText {
    color: #ff8d8d;
    font-size: 12px;
}

#sysinfoStatLabel {
    color: #8fa4b8;
    font-size: 12px;
}
#sysinfoStatLabel[strong="true"] {
    color: #e4eaf0;
    font-weight: 700;
}

#sysinfoStatValue {
    color: #e4eaf0;
    font-family: "Consolas";
    font-size: 12px;
    font-weight: 700;
}

#sysinfoDriveMeta {
    color: #6a7a8a;
    font-size: 10px;
}

QProgressBar#sysinfoProgress {
    background-color: #1a2330;
    border: none;
    border-radius: 2px;
}
QProgressBar#sysinfoProgress::chunk {
    background-color: #0077b6;
    border-radius: 2px;
}
QProgressBar#sysinfoProgress[level="warn"]::chunk {
    background-color: #f59e0b;
    border-radius: 2px;
}
QProgressBar#sysinfoProgress[level="error"]::chunk {
    background-color: #ef4444;
    border-radius: 2px;
}

QMenu {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 8px;
    color: #c8d6e5;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: #182232;
    color: #7ddfff;
}
QMenu::item:disabled {
    color: #3a4a5a;
}
QMenu::separator {
    height: 1px;
    background: #1f2b3a;
    margin: 4px 2px;
}

QMenu#trayMenu {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 12px;
    color: #deebf7;
    padding: 6px;
}
QMenu#trayMenu::item {
    padding: 8px 18px;
    border-radius: 8px;
}
QMenu#trayMenu::item:selected {
    background-color: #182232;
    color: #7ddfff;
}
QMenu#trayMenu::separator {
    height: 1px;
    background: #1f2b3a;
    margin: 6px 2px;
}

#debugSurface {
    background-color: #0d1117;
}

#debugToolbar {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 18px;
}

#debugTitle {
    color: #edf4fb;
    font-size: 18px;
    font-weight: 700;
}

#debugMeta {
    color: #8fa4b8;
    font-size: 12px;
}

QCheckBox#debugCheck {
    color: #9ab0c5;
    font-size: 12px;
    font-weight: 600;
}

QTextEdit#debugLogView {
    background-color: #111822;
    color: #deebf7;
    border: 1px solid #1f2b3a;
    border-radius: 18px;
    padding: 14px;
}

#loadingOverlay {
    background-color: rgba(8, 12, 18, 170);
}

#loadingFrame {
    background-color: rgba(17, 24, 34, 246);
    border: 1px solid rgba(71, 195, 255, 0.26);
    border-radius: 18px;
}

#loadingText {
    color: #edf4fb;
    font-size: 18px;
    font-weight: 700;
}

#loadingDots {
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 18px;
    font-weight: 700;
}

#loadingHint {
    color: #8fa4b8;
    font-size: 12px;
}

/* User Management Row */
#userBox {
    background: #141d28;
    border: 1px solid #1e1e30;
    border-radius: 14px;
}

#userBox[current="true"] {
    border: 1px solid rgba(0, 119, 182, 0.42);
    background: rgba(0, 119, 182, 0.12);
}

#userBox QLabel[state="user_row"] {
    color: #c8d6e5;
    font-size: 13px;
    background: transparent;
    border: none;
}

#userAvatar {
    background: #101925;
    border: 1px solid #31465d;
    border-radius: 14px;
    color: #d8e4f0;
    font-family: "Consolas";
    font-size: 13px;
    font-weight: 700;
}

#userAvatar[admin="true"] {
    background: rgba(0, 119, 182, 0.14);
    border: 1px solid rgba(0, 119, 182, 0.42);
    color: #7ddfff;
}

#userMetaSub {
    color: #8fa4b8;
    font-size: 11px;
    font-family: "Consolas";
}

#userRowName {
    color: #edf4fb;
    font-size: 13px;
    font-weight: 600;
}

#userRoleBadge {
    padding: 3px 8px;
    border-radius: 8px;
    background: #101925;
    border: 1px solid #243243;
    color: #8fa4b8;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
}

#userRoleBadge[variant="accent"] {
    background: rgba(0, 119, 182, 0.15);
    border: 1px solid rgba(0, 119, 182, 0.42);
    color: #7ddfff;
}

#connectionList {
    background-color: transparent;
}

QScrollBar:vertical {
    background: transparent;
    width: 4px;
    margin: 2px 0;
    border-radius: 2px;
}
QScrollBar::handle:vertical {
    background: rgba(170, 180, 196, 0.35);
    border-radius: 2px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(170, 180, 196, 0.65);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* ---- Connection Card -------------------------------------- */
#connectionContainer {
    background: transparent;
    margin-bottom: 0px;
}

#connectionCard {
    background-color: #13131E;
    border: 1px solid #1f2b3a;
    border-radius: 16px;
    margin: 0px;
    padding: 0px;
}

#connectionCard:hover {
    background-color: #16202c;
    border: 1px solid #31465d;
}

/* Mounted State Properties */
#connectionCard[mounted="true"] {
    background-color: #10202a;
    border: 1px solid rgba(0, 119, 182, 0.48);
}

/* Selected State */
#connectionCard[selected="true"] {
    border: 1px solid #47c3ff;
    background-color: #172531;
}

/* Mounted overrides selected blue highlight */
#connectionCard[mounted="true"][selected="true"] {
    border: 1px solid #00d464;
    background-color: #10202a;
}

/* Expanded/Panel Open State */
#connectionCard[expanded="true"] {
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
    margin-bottom: 0px;
    border-bottom: none;
}

#cardInfoWrapper {
    background: transparent;
}

#connName {
    color: #e4eaf0;
    font-size: 14px;
    font-weight: 600;
}
#connDetail {
    color: #556070;
    font-size: 11px;
}

#cloudIcon {
    font-size: 22px;
    color: #2a3a4a;
}
#cloudIcon[mounted="true"] {
    color: #00b4d8;
}

#cloudIcon[state="large"] {
    font-size: 48px;
    padding: 8px;
}

#driveBadge {
    background-color: #0f2430;
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 700;
    border-radius: 9px;
    padding: 2px 4px;
    border: 1px solid rgba(125, 223, 255, 0.24);
}
#driveBadge[mounted="true"] {
    background-color: rgba(0, 212, 100, 0.10);
    color: #00d464;
    border: 1px solid rgba(0, 212, 100, 0.42);
}

#groupPill {
    background-color: rgba(0, 119, 182, 0.12);
    color: #f1f1f1;
    border: 1px solid rgba(0, 119, 182, 0.35);
    border-radius: 8px;
    padding: 1px 8px;
    font-size: 9px;
    font-weight: 600;
}
#groupPillMore {
    background-color: rgba(106, 122, 138, 0.20);
    color: #8fa4b8;
    border: 1px solid rgba(106, 122, 138, 0.35);
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 9px;
    font-weight: 600;
}

/* ---- System Info Panel (Inside Card) ---------------------- */
#systemInfoPanel {
    background-color: #0f1218;
    border: 1px solid #1e1e30;
    border-top: none;
    border-bottom-left-radius: 12px;
    border-bottom-right-radius: 12px;
    margin: 0 12px 12px 12px;
    padding: 8px;
}

/* System info as full right panel content */
#sysinfoFullPanel {
    background-color: transparent;
    border: none;
    margin: 0;
    padding: 0;
}

#sectionFrame {
    background-color: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 6px;
}

#sectionTitle {
    color: #58a6ff;
    font-size: 10px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

#infoLabel { color: #8b949e; font-size: 10px; }
#valueLabel { color: #e6edf3; font-size: 11px; font-weight: 500; }
#bigValue { color: #e6edf3; font-size: 15px; font-weight: bold; }

/* ---- Sidebar (Left) --------------------------------------- */
#sidebar {
    background-color: #0a0a0f;
    border-right: 1px solid #1a1a2e;
    min-width: 60px;
    max-width: 60px;
}

/* ---- Connections Panel (Center) --------------------------- */
#connectionsPanel {
    background-color: #0d0d12;
}

#connectionsHeader {
    background-color: #0E0E19;
    border-bottom: 1px solid #1f2b3a;
    min-height: 52px;
    max-height: 52px;
}

#connectionsKicker {
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
}

#connectionsTitle {
    color: #edf4fb;
    font-size: 16px;
    font-weight: 700;
}

#connectionsBadge {
    background-color: #14141F;
    color: #607489;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 600;
    border: 1px solid rgba(96, 116, 137, 0.26);
    border-radius: 8px;
    min-height: 32px;
    max-height: 32px;
    padding: 0 8px;
}

/* ---- Splitter handle ---------------------------------------- */
#bodySplitter::handle {
    background: transparent;
}
/* Carries the header row across the gap between the two panels. */
#splitterHeaderBand {
    background-color: #0E0E19;
    border-bottom: 1px solid #1f2b3a;
}
#bodySplitter::handle:hover {
    background: transparent;
}

/* ---- Right Panel (System Info) ---------------------------- */
#rightPanel {
    background-color: #0E0E19;
    border-left: 1px solid #1c2633;
}

#rightPanelHeader {
    background-color: #0E0E19;
    border-bottom: 1px solid #1f2b3a;
    min-height: 52px;
    max-height: 52px;
    padding: 0 16px;
}

#rightPanelKicker {
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 1.4px;
}

#rightPanelTitle {
    color: #edf4fb;
    font-size: 16px;
    font-weight: 700;
}

#rightPanelEmpty {
    color: #607489;
    font-size: 12px;
}

#rightPanelPlaceholderTitle {
    color: #edf4fb;
    font-size: 20px;
    font-weight: 700;
    padding: 0;
}

#rightPanelPlaceholderBody {
    color: #8fa4b8;
    font-size: 13px;
    padding: 0;
    min-height: 45px;
    max-height: 45px;
}

#rightPanelPlaceholder,
#connectionsTitleWrap,
#rightPanelTitleWrap,
#fullscreenContent {
    background: transparent;
}

#fullscreenPanel {
    background-color: #0d1117;
}

#fullscreenForm {
    background-color: transparent;
}

#fullscreenSectionCard {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 18px;
}

/* ---- Sidebar Buttons -------------------------------------- */
QPushButton#sidebarBtn {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 12px;
    min-width: 42px;
    max-width: 42px;
    min-height: 42px;
    max-height: 42px;
}
QPushButton#sidebarBtn:hover {
    background-color: #182232;
    border: 1px solid #31465d;
}
QPushButton#sidebarBtn[active="true"] {
    background-color: rgba(0, 119, 182, 0.15);
    border: 1px solid rgba(0, 119, 182, 0.42);
}
QPushButton#sidebarBtn[btn_type="danger"] {
    border: 1px solid #1f2b3a;
}
QPushButton#sidebarBtn[btn_type="danger"]:hover {
    background-color: rgba(239, 68, 68, 0.12);
    border: 1px solid rgba(239, 68, 68, 0.32);
}
QPushButton#sidebarBtn[btn_type="warning"] {
    border: 1px solid #1f2b3a;
}
QPushButton#sidebarBtn[btn_type="warning"]:hover {
    background-color: rgba(245, 158, 11, 0.12);
    border: 1px solid rgba(245, 158, 11, 0.32);
}

/* ---- Small Add button in header --------------------------- */
QPushButton#headerAddBtn {
    background-color: #14141F;
    border: 1px solid #243243;
    border-radius: 10px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#headerAddBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
}

/* ---- Mount/Dismount All Buttons ------------------------- */
QPushButton#headerActionBtn {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 12px;
    min-height: 30px;
    max-height: 30px;
    min-width: 30px;
    max-width: 30px;
}
QPushButton#headerActionBtn:hover {
    background-color: #182232;
    border: 1px solid #31465d;
}

/* ---- Connection filter ---------------------------------------- */
QLineEdit#connectionsFilterInput {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 17px;
    min-height: 34px;
    max-height: 34px;
    padding: 0 6px;
    color: #deebf7;
    font-size: 13px;
}
QLineEdit#connectionsFilterInput:focus {
    background-color: #111822;
    border: 1px solid #0077b6;
}
#connectionsFilterCount {
    color: #8fa4b8;
    font-size: 12px;
}
QPushButton#headerActionBtn[active="true"] {
    background-color: #0f2430;
    border: 1px solid #0077b6;
}

/* ---- Groups Filter Dropdown ---------------------------- */
QComboBox#headerGroupsCombo {
    background-color: #111822;
    color: #deebf7;
    border: 1px solid #0077b6;
    border-radius: 12px;
    padding: 4px 10px;
    font-size: 12px;
    min-height: 22px;
}
QComboBox#headerGroupsCombo:hover {
    border: 1px solid #7ddfff;
}
QComboBox#headerGroupsCombo::drop-down {
    border: none;
    width: 20px;
}
QComboBox#headerGroupsCombo::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #deebf7;
    width: 0;
    height: 0;
}
QComboBox#headerGroupsCombo QAbstractItemView {
    background-color: #111822;
    color: #deebf7;
    border: 1px solid #1f2b3a;
    border-radius: 8px;
    selection-background-color: #182232;
    selection-color: #7ddfff;
}

/* ---- Version label in status bar -------------------------- */
#versionLabel {
    color: #607489;
    font-size: 11px;
    font-family: "Consolas";
}

/* ---- Right Panel - content elements ----------------------- */
#rightPanelScroll {
    background-color: transparent;
    border: none;
}
#rightPanelContent {
    background-color: transparent;
    min-width: 100%;
}

/* Info body rows */
#rpInfoBody {
    background-color: transparent;
}
QFrame#rpInfoField {
    background-color: #14141F;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
}
QFrame#rpInfoField QLineEdit,
QFrame#rpInfoField QSpinBox,
QFrame#rpInfoField QComboBox {
    padding: 0;
    min-height: 16px;
    max-height: 20px;
    background-color: transparent;
    border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 0;
    font-size: 14px;
    font-weight: 400;
    color: #c8d6e5;
}
QFrame#rpInfoField QLineEdit:focus,
QFrame#rpInfoField QSpinBox:focus,
QFrame#rpInfoField QComboBox:focus {
    border-bottom: 1px solid #0077b6;
    background-color: transparent;
}
/* Locked while the host is mounted (edit form) */
QFrame#rpInfoField QLineEdit:disabled,
QFrame#rpInfoField QSpinBox:disabled,
QFrame#rpInfoField QComboBox:disabled {
    color: #556070;
    border-bottom: 1px dashed rgba(255, 255, 255, 0.10);
}
QFrame#rpInfoField QPushButton:disabled {
    color: #3a4a5a;
}
QCheckBox:disabled {
    color: #556070;
}
QCheckBox::indicator:disabled {
    background-color: #111822;
    border: 1.5px solid #1a2330;
}
QFrame#rpInfoField QPushButton {
    min-height: 16px;
    max-height: 20px;
    padding: 0 4px;
    font-size: 14px;
}
#rpSectionLabel {
    color: #0077b6;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding-top: 4px;
}

/* ---- Help "?" beside a field ----------------------------------- */
QPushButton#fieldHelpBtn {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 0;
    min-height: 16px;
    max-height: 16px;
}
QPushButton#fieldHelpBtn:hover {
    background-color: #182232;
}
#rpFieldLabel {
    color: #6f8599;
    font-size: 11px;
}
QLabel#rpFieldLabelCaps {
    font-size: 11px;
}
#rpValue {
    color: #ffffff;
    font-size: 18px;
    font-weight: 800;
    background-color: #14141F;
    border: 0px solid #1f2b3a;
    border-radius: 12px;
}
#rpDivider {
    background-color: #1f2b3a;
    max-height: 1px;
    min-height: 1px;
}

/* Status dot/label in info panel */
#rpStatusDot {
    font-size: 9px;
    color: #3a4a5a;
}
#rpStatusDot[mounted="true"] { color: #00d464; }
#rpStatusLabel {
    color: #607489;
    font-size: 11px;
    font-weight: 600;
}
#rpStatusLabel[mounted="true"] { color: #00d464; }

/* Header action buttons (edit, trash, close in right panel) */
QPushButton#rpHeaderBtn {
    background-color: #14141F;
    border: 1px solid #243243;
    border-radius: 10px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#rpHeaderBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
}
QPushButton#rpHeaderBtn[btn_type="danger"] {
    background-color: rgba(239, 68, 68, 0.16);
    border: 1px solid rgba(239, 68, 68, 0.38);
}
QPushButton#rpHeaderBtn[btn_type="danger"]:hover {
    background-color: rgba(239, 68, 68, 0.24);
    border: 1px solid #ef4444;
}
QPushButton#rpHeaderBtn:disabled {
    background-color: #111822;
    border: 1px solid #1a2330;
    color: #2a3a4a;
}
QPushButton#rpHeaderBtn[btn_type="danger"]:disabled,
QPushButton#rpHeaderBtn[btn_type="danger"]:disabled:hover {
    background-color: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.18);
}
QPushButton#rpHeaderSaveBtn {
    background-color: rgba(0, 212, 100, 0.15);
    border: 1px solid rgba(0, 212, 100, 0.35);
    border-radius: 10px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#rpHeaderSaveBtn:hover {
    background-color: rgba(0, 212, 100, 0.24);
    border: 1px solid rgba(0, 212, 100, 0.60);
}
QPushButton#rpHeaderSaveBtn:disabled {
    background: #1a2330;
    border: 1px solid #243243;
}

/* Right panel save/cancel button bar */
#rpBtnBar {
    background-color: #111822;
    border-top: 1px solid #1f2b3a;
}

QPushButton#rpActionBtn {
    background-color: #141d28;
    border: 1px solid #243243;
    border-radius: 12px;
    color: #E4EAF0;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 12px;
    min-height: 32px;
}
QPushButton#rpActionBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
}
QPushButton#rpActionBtn[btn_type="primary"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0077b6, stop:1 #0077b6);
    border: none;
    color: #deebf7;
}
QPushButton#rpActionBtn[btn_type="primary"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #22c4e8, stop:1 #0088c8);
}
QPushButton#rpActionBtn[btn_type="danger"] {
    background: rgba(239, 68, 68, 0.10);
    border: 1px solid rgba(239, 68, 68, 0.28);
    color: #ff8d8d;
}
QPushButton#rpActionBtn[btn_type="danger"]:hover {
    background: rgba(239, 68, 68, 0.16);
    border: 1px solid #ef4444;
}
QPushButton#rpActionBtn:disabled {
    background-color: #111822;
    border: 1px solid #1a2330;
    color: #607489;
}

/* [i] info button active state */
QPushButton#cardInfoBtn[active="true"] {
    background: rgba(0, 119, 182, 0.15);
    border: 1px solid rgba(0, 119, 182, 0.5);
    color: #0077b6;
}

#divider {
    background-color: #1a1a2e;
    max-height: 1px;
    min-height: 1px;
    margin: 10px 4px;
}

/* ---- Global Action Buttons -------------------------------- */
#actionBtn, QPushButton#sshBtn, QPushButton#mountBtn {
    font-weight: 500;
}

/* Standard Secondary Action Button */
#actionBtn {
    background-color: #141d28;
    border: 1px solid #243243;
    border-radius: 12px;
    color: #9ab0c5;
    font-size: 12px;
    padding: 7px 12px;
    text-align: left;
}
#actionBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
    color: #deebf7;
}

/* Primary Brand Button (Add, etc) */
#actionBtn[btn_type="primary"], #primaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0088c8, stop:1 #005fa3);
    border: none;
    color: #deebf7;
    font-weight: 700;
    padding: 0 14px;
    border-radius: 10px;
    min-height: 32px;
    max-height: 32px;
}
#actionBtn[btn_type="primary"]:hover, #primaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #009add, stop:1 #006fb8);
}
#actionBtn[btn_type="primary"]:disabled, #primaryBtn:disabled,
#actionBtn[btn_type="primary"]:disabled:hover, #primaryBtn:disabled:hover {
    background: #111822;
    border: 1px solid #1a2330;
    color: #607489;
}

/* Secondary / Cancel Button */
#secondaryBtn {
    background-color: #141d28;
    border: 1px solid #243243;
    border-radius: 10px;
    color: #c1cfdd;
    font-size: 13px;
    padding: 0 14px;
    min-height: 32px;
    max-height: 32px;
}
#secondaryBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
    color: #deebf7;
}
#templateDropdownFrame {
    background-color: #111820;
    border: 1px solid #243243;
    border-radius: 10px;
}
#templateDropdownRow {
    border-radius: 6px;
}
#templateDropdownRow:hover {
    background-color: #192433;
}
#templateDropdownLabel {
    color: #c1cfdd;
    font-size: 13px;
}
QPushButton#aboutLinkBtn {
    background-color: #141d28;
    border: 1px solid #243243;
    border-radius: 8px;
    color: #0077b6;
    font-size: 12px;
    padding: 0 10px;
    min-height: 34px;
    max-height: 34px;
    text-align: left;
}
QPushButton#aboutLinkBtn:hover {
    background-color: #0d2137;
    border: 1px solid #0077b6;
    color: #38d4f8;
}
QPushButton#aboutLinkBtn:pressed {
    background-color: #0a1929;
}
/* About dialog */
QWidget#aboutBody, QScrollArea#aboutScroll { background: transparent; }
QFrame#aboutFeatureTile, QFrame#aboutCard {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 12px;
}
QLabel#aboutFeatureTitle, QLabel#aboutCardTitle {
    color: #e4eaf0;
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}
QLabel#aboutFeatureBody {
    color: #8fa4b8;
    font-size: 12px;
    background: transparent;
}
QLabel#aboutCardHint, QLabel#aboutLinkHint {
    color: #6a7a8a;
    font-size: 11px;
    background: transparent;
}
QLabel#aboutLinkLabel {
    color: #c1cfdd;
    font-size: 13px;
    background: transparent;
}
QPushButton#aboutLinkRow {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0;
    min-height: 44px;
    max-height: 44px;
}
QPushButton#aboutLinkRow:hover {
    background-color: #141d28;
    border: 1px solid #243243;
}
QPushButton#aboutLinkRow:pressed {
    background-color: #0d2137;
}
QPushButton#aboutLinkRow:focus {
    border: 1px solid #0077b6;
}
QLabel#aboutCredits {
    color: #6a7a8a;
    font-size: 11px;
}
QLineEdit[invalid="true"] {
    border: 2px solid #0077b6;
}
QLineEdit[invalid="true"]:focus {
    border: 2px solid #0077b6;
}
QLineEdit:focus, QPushButton:focus {
    border: 2px solid #0077b6;
}

/* Dialog Button Bar */
#dialogBtnBar {
    background-color: #0d0d12;
    border-top: 1px solid #1a1a2e;
}

/* Danger Button */
#actionBtn[btn_type="danger"], #dangerBtn {
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.2);
    border-radius: 10px;
    color: #ef4444;
    padding: 0 14px;
    min-height: 32px;
    max-height: 32px;
}
#actionBtn[btn_type="danger"]:hover, #dangerBtn:hover {
    background: rgba(239, 68, 68, 0.15);
    border: 1px solid #ef4444;
}

/* Warning Button (Debug) */
#actionBtn[btn_type="warning"] {
    background: rgba(245, 158, 11, 0.08);
    border: 1px solid rgba(245, 158, 11, 0.2);
    color: #f59e0b;
}
#actionBtn[btn_type="warning"]:hover {
    background: rgba(245, 158, 11, 0.15);
    border: 1px solid #f59e0b;
}

/* Integrated Terminal UI */
#terminalArea {
    background-color: #0d0d12;
}
#terminalTabBar {
    background-color: #0d1117;
    border-bottom: 1px solid #1a2330;
}
#terminalTabBtn {
    background-color: #141d28;
    border: 1px solid #1f2b3a;
    border-radius: 6px;
    color: #6a7a8a;
    padding: 3px 12px;
    min-height: 24px;
    max-height: 24px;
    font-size: 11px;
}
#terminalTabBtn:hover {
    background-color: #192433;
    color: #aab4c4;
}
#terminalTabBtn:checked {
    background-color: #192433;
    border-color: #0077b6;
    color: #deebf7;
}
#terminalEndBar {
    background-color: #0d1117;
    border-top: 1px solid #1a2330;
}

/* SSH Circular/Small Button */
QPushButton#sshBtn {
    background: #141d28;
    border: 1px solid #243243;
    color: #7ddfff;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#sshBtn:hover {
    background: rgba(0, 119, 182, 0.14);
    border: 1px solid #47c3ff;
}

/* Card-internal Info/Edit Buttons */
QPushButton#cardInfoBtn, QPushButton#cardEditBtn {
    background: #141d28;
    border: 1px solid #243243;
    color: #c1cfdd;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#cardInfoBtn:hover, QPushButton#cardEditBtn:hover {
    background: rgba(170, 180, 196, 0.12);
    border: 1px solid #9ab0c5;
    color: #deebf7;
}
QPushButton#cardEditBtn:disabled {
    color: #3a3a4a;
    border: 1px solid #1e1e2e;
    background: #14141f;
}

/* Mount Toggle Circle */
QPushButton#mountBtn {
    background-color: #141d28;
    border: 1px solid #2f4358;
    border-radius: 10px;
    color: #deebf7;
    font-size: 12px;
    font-weight: 700;
    padding: 0px;
    text-align: center;
}
QPushButton#mountBtn:hover {
    background-color: rgba(0, 119, 182, 0.14);
    border: 1px solid #47c3ff;
    color: #7ddfff;
}
QPushButton#mountBtn[mounted="true"] {
    background-color: rgba(0, 212, 100, 0.10);
    border: 1px solid rgba(0, 212, 100, 0.42);
    color: #00d464;
}
QPushButton#mountBtn[mounted="true"]:hover {
    background-color: rgba(239, 68, 68, 0.15);
    border: 1px solid #ef4444;
    color: #ef4444;
}
QPushButton#mountBtn[loading="true"], QPushButton#mountBtn[loading="true"]:disabled {
    background-color: rgba(0, 119, 182, 0.14);
    border: 1px solid rgba(71, 195, 255, 0.38);
    border-radius: 16px;
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 700;
    padding: 0 10px;
}

/* ---- Inputs ----------------------------------------------- */
QLineEdit, QSpinBox, QComboBox {
    background-color: #14141f;
    border: 1px solid #1e1e30;
    border-radius: 8px;
    color: #c8d6e5;
    padding: 3px 8px;
    font-size: 13px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #0077b6;
    background-color: #16162a;
}

/* ---- Stepper: number between round - and + buttons ---------- */
QFrame#stepper {
    background-color: #14141f;
    border: 1px solid #1e1e30;
    border-radius: 17px;
}
QFrame#stepper QSpinBox#stepperValue,
QFrame#stepper QSpinBox#stepperValue:focus {
    background: transparent;
    border: none;
    padding: 0;
    color: #deebf7;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#stepperBtn {
    background-color: #182232;
    border: 1px solid #243243;
    border-radius: 12px;
    padding: 0;
}
QPushButton#stepperBtn:hover {
    background-color: #0f2430;
    border: 1px solid #0077b6;
}
QPushButton#stepperBtn:pressed {
    background-color: #0077b6;
    border: 1px solid #0077b6;
}
QPushButton#stepperBtn:disabled {
    background-color: transparent;
    border: 1px solid #1e1e30;
}
QLineEdit::placeholder {
    color: #3f4e5e;
}

QComboBox::drop-down { border: none; width: 30px; }
QComboBox::down-arrow {
    image: url("__CHEVRON_URL__");
    width: 12px;
    height: 12px;
    margin-right: 10px;
}

/* Dropdown popup */
QComboBox QAbstractItemView {
    background-color: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    color: #c8d6e5;
    selection-background-color: rgba(0, 119, 182, 0.18);
    selection-color: #e4eaf0;
    outline: none;
    padding: 1px;
}
QComboBox QAbstractItemView::item {
    padding: 4px 8px;
    min-height: 24px;
    border-radius: 12px;
}
QComboBox QAbstractItemView::item:selected {
    background-color: rgba(0, 119, 182, 0.18);
}

/* ---- Status Bar ------------------------------------------- */
#statusBar {
    background-color: #0a0f15;
    border-top: 1px solid #1c2633;
    color: #8fa4b8;
    font-family: "Consolas";
    font-size: 12px;
    padding: 10px 14px;
}
#statusDot { color: #00d464; font-size: 9px; margin-right: 4px; }
#statusText {
    color: #8fa4b8;
}
#statusPill {
    color: #607489;
}

#mountErrorDialog {
    background-color: #0d1117;
}

#mountErrorLead {
    color: #edf4fb;
    font-size: 13px;
    font-weight: 600;
}

#mountErrorBlock {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 14px;
}

#mountErrorBody {
    color: #9ab0c5;
    font-size: 12px;
}

#mountErrorDetails {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 12px;
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 11px;
    padding: 12px;
}

/* ---- Progress Bars ---------------------------------------- */
QProgressBar {
    background-color: #1a1a2e;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
    height: 8px;
}
QProgressBar::chunk {
    background-color: #0077b6;
    border-radius: 4px;
}

/* ---- Tabs ------------------------------------------------- */
QTabWidget::pane {
    border: 1px solid #1e1e30;
    border-radius: 10px;
    background: #0f0f1a;
    margin-top: -1px;
}
QTabBar::tab {
    background: transparent;
    border-bottom: 2px solid transparent;
    color: #556070;
    font-size: 12px;
    padding: 10px 20px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    color: #0077b6;
    border-bottom: 2px solid #0077b6;
    font-weight: 600;
}

/* ---- Dialogs ---------------------------------------------- */
QDialog {
    background-color: #0d0d12;
}

#dialogTitle {
    color: #e4eaf0;
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 8px;
}

#sectionLabel {
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    padding-top: 12px;
}

#fieldLabel {
    color: #556070;
    font-size: 11px;
    font-weight: 600;
    margin-bottom: 2px;
}

/* ---- Tooltips / Messagebox -------------------------------- */
QToolTip {
    background-color: #1a1a2e;
    border: 1px solid #2a2a4a;
    color: #c8d6e5;
    border-radius: 6px;
    padding: 5px 10px;
}

QMessageBox {
    background-color: __SURFACE__;
    color: #c8d6e5;
}
QMessageBox QPushButton {
    min-width: 90px;
    min-height: 32px;
    max-height: 32px;
    padding: 0 14px;
}
"""

LIGHT_STYLESHEET = """
/* ============================================================
    NEO SSH-Win Manager - Light Theme
   ============================================================ */

/* ---- Custom Titlebar (light) ------------------------------ */
#customTitlebar {
    background-color: #e4e8ef;
    border-bottom: 1px solid #c8d0dc;
}
#customTitlebarTitle {
    color: #1a2332;
    font-family: "Segoe UI", sans-serif;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
#customTitlebarVersion {
    color: #5a6a7a;
    font-family: "Consolas";
    font-size: 10px;
    background: transparent;
    padding: 0 4px;
}
#fwOuter {
    background-color: #f0f2f5;
}

QWidget {
    color: #1a2332;
    font-family: "Inter", "Segoe UI", sans-serif;
    font-size: 13px;
    border: none;
    outline: none;
}

QLabel, QCheckBox, QRadioButton, QGroupBox {
    background: transparent;
}

QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1.5px solid #c8d0dc;
    background-color: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #9aacbe;
}
QCheckBox::indicator:checked {
    width: 16px;
    height: 16px;
    background-color: #0077b6;
    border: 1.5px solid #005a8a;
    image: url("__CHECKMARK_URL__");
}
QCheckBox::indicator:checked:hover {
    width: 16px;
    height: 16px;
    background-color: #0088c8;
    border: 1.5px solid #0066a0;
    image: url("__CHECKMARK_URL__");
}

QRadioButton {
    spacing: 8px;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1.5px solid #c8d0dc;
    background-color: #ffffff;
}
QRadioButton::indicator:hover {
    border-color: #9aacbe;
}
QRadioButton::indicator:checked {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1.5px solid #005a8a;
    background-color: #0077b6;
    image: url("__CHECKMARK_URL__");
}
QRadioButton::indicator:checked:hover {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1.5px solid #0066a0;
    background-color: #0088c8;
    image: url("__CHECKMARK_URL__");
}

#MainWindow {
    background-color: #f0f2f5;
}

#sidePanel {
    background-color: #e4e8ef;
    border-right: 1px solid #c8d0dc;
}

#connectionScroll {
    background-color: transparent;
    border: none;
}

#dialogTitle {
    color: #0077b6;
    font-size: 18px;
    font-weight: bold;
    margin-bottom: 5px;
}

#sectionLabel {
    color: #0077b6;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    margin-top: 8px;
}

#fieldLabel {
    color: #4a5a6a;
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 2px;
}

#hintLabel {
    color: #7a8a9a;
    font-size: 11px;
}

#ctrlRowLabel {
    color: #445769;
    font-size: 12px;
    font-weight: 600;
}

/* ---- Settings Cards (per-section) ------------------------ */
#settingsGroupCard {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 14px;
}

#settingsRow {
    background: transparent;
    border-radius: 0px;
}

#settingsRow:hover {
    background: rgba(0, 0, 0, 0.03);
}

#rowSep {
    background-color: rgba(0, 0, 0, 0.07);
    max-height: 1px;
    min-height: 1px;
    margin: 0 14px;
}

#rowLabel {
    color: #1a2332;
    font-size: 13px;
}

QPushButton#settingsActionBtn {
    background-color: #f0f4f8;
    border: 1px solid #c8d3df;
    border-radius: 10px;
    color: #3a5067;
    font-size: 12px;
    font-weight: 600;
    padding: 0 14px;
    text-align: center;
}
QPushButton#settingsActionBtn:hover {
    background-color: #e4ecf4;
    border: 1px solid #9ab0c5;
    color: #182536;
}
QPushButton#settingsActionBtn:disabled {
    background-color: #f6f9fc;
    border: 1px solid #dde2e8;
    color: #aab4c4;
}
QPushButton#settingsActionBtn[btn_type="primary"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0088c8, stop:1 #005fa3);
    border: none;
    color: #fff;
    font-weight: 700;
}
QPushButton#settingsActionBtn[btn_type="primary"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #009add, stop:1 #006fb8);
}

#errorLabel { color: #dc2626; font-size: 12px; }
#mutedLabel { color: #6a7a8a; font-size: 12px; }
#accentLabel { color: #0077b6; font-size: 11px; }
#secondaryTitle { color: #2a3a4a; font-size: 11px; font-weight: bold; }

#divider {
    background-color: rgba(0, 0, 0, 0.10);
    max-height: 1px;
    min-height: 1px;
    margin: 10px 4px;
}

#dialogHeroCard, #dialogSectionCard {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 18px;
}

#dialogLead {
    color: #617386;
    font-size: 13px;
}

#dialogPill {
    background-color: #edf7fc;
    color: #0077b6;
    font-family: "Consolas";
    font-size: 10px;
    font-weight: 700;
    border: 1px solid rgba(0, 119, 182, 0.18);
    border-radius: 12px;
    padding: 4px 10px;
}

/* ---- Login screen ----------------------------------------- */
QFrame#loginRoot {
    background: qradialgradient(cx:0.5, cy:0, radius:0.9, fx:0.5, fy:0,
        stop:0 rgba(0, 119, 182, 0.13), stop:0.75 rgba(0, 119, 182, 0));
}
QFrame#loginCard {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 16px;
}
QLabel#loginHeadline {
    color: #1a2332;
    font-size: 22px;
    font-weight: 700;
    background: transparent;
}
QLabel#loginSubline {
    color: #617386;
    font-size: 13px;
    background: transparent;
}
QLabel#loginFieldLabel {
    color: #4a5a6a;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
QLineEdit#loginInput {
    background-color: #f7f9fb;
    border: 1px solid #c8d0dc;
    border-radius: 10px;
    color: #1a2332;
    font-size: 14px;
    padding: 0 6px;
    min-height: 40px;
}
QLineEdit#loginInput:hover {
    border: 1px solid #aec6dd;
}
QLineEdit#loginInput:focus {
    border: 1px solid #0077b6;
    background-color: #ffffff;
}
QLineEdit#loginInput:disabled {
    color: #9aacbe;
    border: 1px solid #e2e8ef;
}
QComboBox#loginLangCombo {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 15px;
    color: #2a3a4a;
    font-size: 12px;
    padding: 0 6px 0 10px;
    min-height: 30px;
    max-height: 30px;
}
QComboBox#loginLangCombo:hover {
    border: 1px solid #aec6dd;
    color: #1a2332;
}
QComboBox#loginLangCombo::drop-down { width: 22px; border: none; background: transparent; }
QComboBox#loginLangCombo::down-arrow { margin-right: 8px; width: 10px; height: 10px; }
QPushButton#primaryBtn[size="large"] {
    min-height: 42px;
    max-height: 42px;
    border-radius: 12px;
    font-size: 14px;
}
QPushButton#secondaryBtn[size="large"] {
    min-height: 40px;
    max-height: 40px;
    border-radius: 12px;
}
QFrame#loginOrLine {
    background-color: #dde3ea;
    min-height: 1px;
    max-height: 1px;
}
QLabel#loginOrLabel {
    color: #8a99a8;
    font-size: 11px;
    font-weight: 600;
    background: transparent;
}
QFrame#loginAlert {
    background-color: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 10px;
}
QLabel#loginAlertText {
    color: #b91c1c;
    font-size: 12px;
    background: transparent;
}
QLabel#loginCapsText {
    color: #b45309;
    font-size: 11px;
    background: transparent;
}
QLabel#loginHint {
    color: #7a8a9a;
    font-size: 11px;
    background: transparent;
}

QLabel#dialogLink {
    color: #0077b6;
    font-size: 13px;
    font-weight: 600;
}

QPushButton#dialogMaximizeBtn {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 10px;
}
QPushButton#dialogMaximizeBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
}
QPushButton#dialogMaximizeBtn:checked {
    background-color: rgba(0, 119, 182, 0.10);
    border: 1px solid rgba(0, 119, 182, 0.28);
}

#sysinfoHeroCard, #sysinfoSectionCard, #sysinfoStateCard {
    background-color: transparent;
    border: none;
}

#sysinfoLoadingOverlay {
    background-color: rgba(235, 241, 247, 165);
}
#sysinfoLoadingCard {
    background-color: rgba(255, 255, 255, 248);
    border: 1px solid rgba(0, 119, 182, 0.20);
    border-radius: 18px;
    min-width: 260px;
}
#sysinfoLoadingIcon {
    color: #0077b6;
    font-size: 26px;
}
#sysinfoLoadingTitle {
    color: #182536;
    font-size: 14px;
    font-weight: 800;
}
#sysinfoLoadingDots {
    color: #0077b6;
    font-family: "Consolas";
    font-size: 16px;
    font-weight: 800;
    min-height: 18px;
}

#sysinfoHeroTitle {
    color: #182536;
    font-size: 18px;
    font-weight: 700;
}

#sysinfoHeroMeta {
    color: #617386;
    font-size: 12px;
}

#sysinfoStatePill {
    background-color: #edf7fc;
    color: #0077b6;
    font-family: "Consolas";
    font-size: 10px;
    font-weight: 700;
    border: 1px solid rgba(0, 119, 182, 0.18);
    border-radius: 8px;
    padding: 4px 10px;
}
#sysinfoStatePill[connected="false"] {
    background-color: rgba(220, 38, 38, 0.10);
    color: #c62828;
    border: 1px solid rgba(220, 38, 38, 0.24);
}

#sysinfoStateText {
    color: #617386;
    font-size: 12px;
}

#sysinfoErrorText {
    color: #c62828;
    font-size: 12px;
}

#sysinfoStatLabel {
    color: #617386;
    font-size: 12px;
}
#sysinfoStatLabel[strong="true"] {
    color: #182536;
    font-weight: 700;
}

#sysinfoStatValue {
    color: #182536;
    font-family: "Consolas";
    font-size: 12px;
    font-weight: 700;
}

#sysinfoDriveMeta {
    color: #8a9aab;
    font-size: 10px;
}

QProgressBar#sysinfoProgress {
    background-color: #e3e9f0;
    border: none;
    border-radius: 2px;
}
QProgressBar#sysinfoProgress::chunk {
    background-color: #0077b6;
    border-radius: 2px;
}
QProgressBar#sysinfoProgress[level="warn"]::chunk {
    background-color: #d97706;
    border-radius: 2px;
}
QProgressBar#sysinfoProgress[level="error"]::chunk {
    background-color: #dc2626;
    border-radius: 2px;
}

QMenu {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 8px;
    color: #1a2332;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: #edf5fb;
    color: #0077b6;
}
QMenu::item:disabled {
    color: #aab4c4;
}
QMenu::separator {
    height: 1px;
    background: #d5dde7;
    margin: 4px 2px;
}

QMenu#trayMenu {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    color: #182536;
    padding: 6px;
}
QMenu#trayMenu::item {
    padding: 8px 18px;
    border-radius: 8px;
}
QMenu#trayMenu::item:selected {
    background-color: #edf5fb;
    color: #0077b6;
}
QMenu#trayMenu::separator {
    height: 1px;
    background: #d5dde7;
    margin: 6px 2px;
}

#debugSurface {
    background-color: #f0f4f8;
}

#debugToolbar {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 18px;
}

#debugTitle {
    color: #182536;
    font-size: 18px;
    font-weight: 700;
}

#debugMeta {
    color: #617386;
    font-size: 12px;
}

QCheckBox#debugCheck {
    color: #617386;
    font-size: 12px;
    font-weight: 600;
}

QTextEdit#debugLogView {
    background-color: #ffffff;
    color: #182536;
    border: 1px solid #d5dde7;
    border-radius: 18px;
    padding: 14px;
}

#loadingOverlay {
    background-color: rgba(235, 241, 247, 165);
}

#loadingFrame {
    background-color: rgba(255, 255, 255, 248);
    border: 1px solid rgba(0, 119, 182, 0.20);
    border-radius: 18px;
}

#loadingText {
    color: #182536;
    font-size: 18px;
    font-weight: 700;
}

#loadingDots {
    color: #0077b6;
    font-family: "Consolas";
    font-size: 18px;
    font-weight: 700;
}

#loadingHint {
    color: #617386;
    font-size: 12px;
}

#userBox {
    background: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 16px;
}

#userBox QLabel[state="user_row"] {
    color: #1a2332;
    font-size: 13px;
    background: transparent;
    border: none;
}

#userBox[current="true"] {
    border: 1px solid rgba(0, 119, 182, 0.30);
    background: rgba(0, 119, 182, 0.08);
}

#userAvatar {
    background: #f3f6fa;
    border: 1px solid #c8d3df;
    border-radius: 14px;
    color: #203246;
    font-family: "Consolas";
    font-size: 13px;
    font-weight: 700;
}

#userAvatar[admin="true"] {
    background: rgba(0, 119, 182, 0.12);
    border: 1px solid rgba(0, 119, 182, 0.38);
    color: #0f7cb2;
}

#userMetaSub {
    color: #617386;
    font-size: 11px;
    font-family: "Consolas";
}

#userRowName {
    color: #1a2332;
    font-size: 13px;
    font-weight: 600;
}

#userRoleBadge {
    padding: 3px 8px;
    border-radius: 8px;
    background: #f3f6fa;
    border: 1px solid #d5dde7;
    color: #617386;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
}

#userRoleBadge[variant="accent"] {
    background: rgba(0, 119, 182, 0.12);
    border: 1px solid rgba(0, 119, 182, 0.34);
    color: #0f7cb2;
}

QScrollBar:vertical {
    background: transparent;
    width: 4px;
    margin: 2px 0;
    border-radius: 2px;
}
QScrollBar::handle:vertical {
    background: rgba(100, 130, 160, 0.35);
    border-radius: 2px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: rgba(100, 130, 160, 0.65); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

#connectionCard {
    background-color: #ffffff;
    border: 1px solid #d7e0ea;
    border-radius: 16px;
    margin: 0px;
    padding: 0px;
}
#connectionCard:hover {
    background-color: #eff5fb;
    border: 1px solid #a8c3dc;
}
#connectionCard[mounted="true"] {
    background-color: #e8f6fb;
    border: 1px solid rgba(0, 119, 182, 0.46);
}
#connectionCard[selected="true"] {
    border: 1px solid #1590cf;
    background-color: #dff1fb;
}
#connectionCard[mounted="true"][selected="true"] {
    border: 1px solid #007a3d;
    background-color: #e8f6fb;
}
#connectionCard[expanded="true"] {
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
    margin-bottom: 0px;
    border-bottom: none;
}

#cardInfoWrapper { background: transparent; }
#connName { color: #1a2332; font-size: 14px; font-weight: 600; }
#connDetail { color: #6a7a8a; font-size: 11px; }

#cloudIcon { font-size: 22px; color: #b0bac4; }
#cloudIcon[mounted="true"] { color: #00b4d8; }
#cloudIcon[state="large"] { font-size: 48px; padding: 8px; }

#driveBadge {
    background-color: #edf7fc;
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 700;
    border-radius: 9px;
    padding: 2px 4px;
    border: 1px solid #c7dfef;
}

#driveBadge[mounted="true"] {
    background-color: rgba(0, 180, 80, 0.12);
    color: #007a3d;
    border: 1px solid #007a3d;
}

#groupPill {
    background-color: rgba(0, 119, 182, 0.10);
    color: #004a75;
    border: 1px solid rgba(0, 119, 182, 0.30);
    border-radius: 4px;
    padding: 1px 8px;
    font-size: 9px;
    font-weight: 600;
}
#groupPillMore {
    background-color: rgba(106, 122, 138, 0.15);
    color: #004a75;
    border: 1px solid rgba(106, 122, 138, 0.30);
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 9px;
    font-weight: 600;
}

#systemInfoPanel {
    background-color: #eef2f7;
    border: 1px solid #c8d0dc;
    border-top: none;
    border-bottom-left-radius: 12px;
    border-bottom-right-radius: 12px;
    margin: 0 12px 12px 12px;
    padding: 8px;
}

#sysinfoFullPanel {
    background-color: transparent;
    border: none;
    margin: 0;
    padding: 0;
}

#sectionFrame {
    background-color: #ffffff;
    border: 1px solid #d0d8e4;
    border-radius: 8px;
    padding: 6px;
}

#sectionTitle { color: #0077b6; font-size: 10px; font-weight: bold; text-transform: uppercase; }
#infoLabel { color: #6a7a8a; font-size: 10px; }
#valueLabel { color: #1a2332; font-size: 11px; font-weight: 500; }
#bigValue { color: #1a2332; font-size: 15px; font-weight: bold; }

#sidebar {
    background-color: #e4e8ef;
    border-right: 1px solid #c8d0dc;
    min-width: 60px;
    max-width: 60px;
}

#connectionsPanel { background-color: #f0f2f5; }

#connectionsHeader {
    background-color: #edf2f7;
    border-bottom: 1px solid #d5dde7;
    min-height: 52px;
    max-height: 52px;
}

#connectionsKicker {
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
}

#connectionsTitle {
    color: #1a2332;
    font-size: 16px;
    font-weight: 700;
}

#connectionsBadge {
    background-color: #ffffff;
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 600;
    border: 1px solid rgba(0, 119, 182, 0.22);
    border-radius: 8px;
    min-height: 32px;
    max-height: 32px;
    padding: 0 8px;
}

/* ---- Splitter handle (Light) -------------------------------- */
#bodySplitter::handle {
    background-color: #c8d0dc;
    width: 4px;
}
#bodySplitter::handle:hover {
    background-color: #0077b6;
}
#splitterHeaderBand {
    background-color: #edf2f7;
    border-bottom: 1px solid #d5dde7;
}

#rightPanel {
    background-color: #f3f6fa;
    border-left: 1px solid #d5dde7;
}

#rightPanelHeader {
    background-color: #edf2f7;
    border-bottom: 1px solid #d5dde7;
    min-height: 52px;
    max-height: 52px;
    padding: 0 16px;
}

#rightPanelKicker { color: #0077b6; font-family: "Consolas"; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 1.4px; }
#rightPanelTitle { color: #1a2332; font-size: 16px; font-weight: 700; }
#rightPanelEmpty { color: #8093a7; font-size: 12px; }

#rightPanelPlaceholderTitle {
    color: #182536;
    font-size: 20px;
    font-weight: 700;
    padding: 0;
}

#rightPanelPlaceholderBody {
    color: #617386;
    font-size: 13px;
    padding: 0;
    min-height: 45px;
    max-height: 45px;
}

#rightPanelPlaceholder,
#connectionsTitleWrap,
#rightPanelTitleWrap,
#fullscreenContent {
    background: transparent;
}

#fullscreenPanel {
    background-color: #f0f4f8;
}

#fullscreenForm {
    background-color: transparent;
}

#fullscreenSectionCard {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 18px;
}

QPushButton#sidebarBtn {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    min-width: 42px;
    max-width: 42px;
    min-height: 42px;
    max-height: 42px;
}
QPushButton#sidebarBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
}
QPushButton#sidebarBtn[active="true"] {
    background-color: rgba(0, 119, 182, 0.10);
    border: 1px solid rgba(0, 119, 182, 0.28);
}
QPushButton#sidebarBtn[btn_type="danger"] {
    border: 1px solid #d5dde7;
}
QPushButton#sidebarBtn[btn_type="danger"]:hover {
    background-color: rgba(220, 38, 38, 0.10);
    border: 1px solid rgba(220, 38, 38, 0.3);
}
QPushButton#sidebarBtn[btn_type="warning"] {
    border: 1px solid #d5dde7;
}
QPushButton#sidebarBtn[btn_type="warning"]:hover {
    background-color: rgba(217, 119, 6, 0.10);
    border: 1px solid rgba(217, 119, 6, 0.3);
}

QPushButton#headerAddBtn {
    background-color: #effaf3;
    border: 1px solid rgba(0, 122, 61, 0.26);
    border-radius: 10px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#headerAddBtn:hover {
    background-color: rgba(0, 122, 61, 0.14);
    border: 1px solid #007a3d;
}

/* ---- Mount/Dismount All Buttons (Light) ---------------- */
QPushButton#headerActionBtn {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    min-height: 30px;
    max-height: 30px;
    min-width: 30px;
    max-width: 30px;
}
QPushButton#headerActionBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
}

/* ---- Connection filter (Light) -------------------------------- */
QLineEdit#connectionsFilterInput {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 17px;
    min-height: 34px;
    max-height: 34px;
    padding: 0 6px;
    color: #1a2332;
    font-size: 13px;
}
QLineEdit#connectionsFilterInput:focus {
    background-color: #ffffff;
    border: 1px solid #0077b6;
}
#connectionsFilterCount {
    color: #5a6a7a;
    font-size: 12px;
}
QPushButton#headerActionBtn[active="true"] {
    background-color: #e0eef8;
    border: 1px solid #0077b6;
}

/* ---- Groups Filter Dropdown (Light) -------------------- */
QComboBox#headerGroupsCombo {
    background-color: #ffffff;
    color: #182536;
    border: 1px solid #0077b6;
    border-radius: 12px;
    padding: 4px 10px;
    font-size: 12px;
    min-height: 22px;
}
QComboBox#headerGroupsCombo:hover {
    border: 1px solid #0077b6;
}
QComboBox#headerGroupsCombo::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #182536;
    width: 0;
    height: 0;
}
QComboBox#headerGroupsCombo QAbstractItemView {
    background-color: #ffffff;
    color: #182536;
    border: 1px solid #d5dde7;
    border-radius: 8px;
    selection-background-color: #edf5fb;
    selection-color: #0077b6;
}

#versionLabel { color: #7d8fa2; font-size: 11px; font-family: "Consolas"; }

/* ---- Right Panel - content elements (Light) --------------- */
#rightPanelScroll {
    background-color: transparent;
    border: none;
}
#rightPanelContent { background-color: transparent; min-width: 100%;}
#rpInfoBody { background-color: transparent; }
QFrame#rpInfoField {
    background-color: #ffffff;
    border: 1px solid #e2e8ef;
    border-radius: 12px;
}
QFrame#rpInfoField QLineEdit,
QFrame#rpInfoField QSpinBox,
QFrame#rpInfoField QComboBox {
    padding: 0;
    min-height: 16px;
    max-height: 20px;
    background-color: transparent;
    border: none;
    border-bottom: 1px solid #c8d0dc;
    border-radius: 0;
    font-size: 14px;
    font-weight: 400;
    color: #1a2332;
}
QFrame#rpInfoField QLineEdit:focus,
QFrame#rpInfoField QSpinBox:focus,
QFrame#rpInfoField QComboBox:focus {
    border-bottom: 1px solid #0077b6;
    background-color: transparent;
}
/* Locked while the host is mounted (edit form) */
QFrame#rpInfoField QLineEdit:disabled,
QFrame#rpInfoField QSpinBox:disabled,
QFrame#rpInfoField QComboBox:disabled {
    color: #9aa6b2;
    border-bottom: 1px dashed rgba(0, 0, 0, 0.12);
}
QFrame#rpInfoField QPushButton:disabled {
    color: #b8c4cf;
}
QCheckBox:disabled {
    color: #9aa6b2;
}
QCheckBox::indicator:disabled {
    background-color: #f0f2f5;
    border: 1.5px solid #dde2e8;
}
QFrame#rpInfoField QPushButton {
    min-height: 16px;
    max-height: 20px;
    padding: 0 4px;
    font-size: 14px;
}
#rpSectionLabel {
    color: #0077b6;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding-top: 4px;
}

/* ---- Help "?" beside a field (Light) --------------------------- */
QPushButton#fieldHelpBtn {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 0;
    min-height: 16px;
    max-height: 16px;
}
QPushButton#fieldHelpBtn:hover {
    background-color: #e2e8f0;
}
#rpFieldLabel { color: #000000; font-size: 11px; padding: 6px 0 1px 0; }
#rpValue {
    color: #1a2332;
    font-size: 12px;
    font-weight: 500;
    background-color: transparent;
    border: none;
    padding: 0;
}
QFrame#rpInfoField QLabel#rpFieldLabelCaps {
    color: #6a7685;
}
QLabel#rpFieldLabelCaps {
    font-size: 11px;
}
#rpDivider {
    background-color: #d5dde7;
    max-height: 1px;
    min-height: 1px;
}
#rpStatusDot { font-size: 9px; color: #9aacbe; }
#rpStatusDot[mounted="true"] { color: #007a3d; }
#rpStatusLabel { color: #8093a7; font-size: 11px; font-weight: 600; }
#rpStatusLabel[mounted="true"] { color: #007a3d; }
QPushButton#rpHeaderBtn {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 10px;
    min-width: 32px; max-width: 32px;
    min-height: 32px; max-height: 32px;
}
QPushButton#rpHeaderBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
}
QPushButton#rpHeaderBtn[btn_type="danger"] {
    background-color: rgba(220, 38, 38, 0.16);
    border: 1px solid rgba(220, 38, 38, 0.34);
}
QPushButton#rpHeaderBtn[btn_type="danger"]:hover {
    background-color: rgba(220, 38, 38, 0.22);
    border: 1px solid #dc2626;
}
QPushButton#rpHeaderBtn:disabled {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #b0bcc8;
}
QPushButton#rpHeaderBtn:disabled:hover {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
}
QPushButton#rpHeaderBtn[btn_type="danger"]:disabled,
QPushButton#rpHeaderBtn[btn_type="danger"]:disabled:hover {
    background-color: rgba(220, 38, 38, 0.08);
    border: 1px solid rgba(220, 38, 38, 0.20);
}
QPushButton#rpHeaderSaveBtn {
    background-color: rgba(0, 180, 80, 0.15);
    border: 1px solid rgba(0, 180, 80, 0.35);
    border-radius: 10px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#rpHeaderSaveBtn:hover {
    background-color: rgba(0, 180, 80, 0.24);
    border: 1px solid rgba(0, 180, 80, 0.60);
}
QPushButton#rpHeaderSaveBtn:disabled {
    background: #f4f7fa;
    border: 1px solid #d5dde7;
}
#rpBtnBar {
    background-color: #edf2f7;
    border-top: 1px solid #d5dde7;
}

QPushButton#rpActionBtn {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    color: #4a5a6a;
    font-size: 12px;
    font-weight: 600;
    padding: 7px 12px;
    min-height: 32px;
}
QPushButton#rpActionBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
    color: #1a2332;
}
QPushButton#rpActionBtn[btn_type="primary"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0088c8, stop:1 #0077b6);
    border: none;
    color: #deebf7;
}
QPushButton#rpActionBtn[btn_type="primary"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0099d8, stop:1 #0088c8);
}
QPushButton#rpActionBtn[btn_type="danger"] {
    background: rgba(220, 38, 38, 0.08);
    border: 1px solid rgba(220, 38, 38, 0.24);
    color: #c62828;
}
QPushButton#rpActionBtn[btn_type="danger"]:hover {
    background: rgba(220, 38, 38, 0.14);
    border: 1px solid #dc2626;
}
QPushButton#rpActionBtn:disabled {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #95a6b8;
}
QPushButton#rpActionBtn:disabled:hover {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #95a6b8;
}
QPushButton#cardInfoBtn[active="true"] {
    background: rgba(0, 119, 182, 0.12);
    border: 1px solid rgba(0, 119, 182, 0.5);
    color: #0077b6;
}

#actionBtn {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    color: #4a5a6a;
    font-size: 12px;
    padding: 7px 12px;
    text-align: left;
}
#actionBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
    color: #1a2332;
}
QPushButton#actionBtn:disabled {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #95a6b8;
}
QPushButton#actionBtn:disabled:hover {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #95a6b8;
}

#actionBtn[btn_type="primary"], #primaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0088c8, stop:1 #0077b6);
    border: none;
    color: #deebf7;
    font-weight: 700;
    padding: 0 14px;
    border-radius: 10px;
    min-height: 32px;
    max-height: 32px;
}
#actionBtn[btn_type="primary"]:hover, #primaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0099d8, stop:1 #0088c8);
}
#actionBtn[btn_type="primary"]:disabled, #primaryBtn:disabled,
#actionBtn[btn_type="primary"]:disabled:hover, #primaryBtn:disabled:hover {
    background: #e4e8ef;
    border: 1px solid #d5dde7;
    color: #9aacbe;
}

#secondaryBtn {
    background-color: #E4EAF0;
    border: 1px solid #d5dde7;
    border-radius: 10px;
    color: #4a5a6a;
    font-size: 13px;
    padding: 0 14px;
    min-height: 32px;
    max-height: 32px;
}
#secondaryBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
    color: #1a2332;
}
#templateDropdownFrame {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 10px;
}
#templateDropdownRow {
    border-radius: 6px;
}
#templateDropdownRow:hover {
    background-color: #edf5fb;
}
#templateDropdownLabel {
    color: #2a3a4a;
    font-size: 13px;
}
QPushButton#aboutLinkBtn {
    background-color: #f0f5fa;
    border: 1px solid #d5dde7;
    border-radius: 8px;
    color: #0077b6;
    font-size: 12px;
    padding: 0 10px;
    min-height: 34px;
    max-height: 34px;
    text-align: left;
}
QPushButton#aboutLinkBtn:hover {
    background-color: #e0eef8;
    border: 1px solid #0077b6;
    color: #005a8e;
}
QPushButton#aboutLinkBtn:pressed {
    background-color: #d0e6f5;
}
/* About dialog */
QWidget#aboutBody, QScrollArea#aboutScroll { background: transparent; }
QFrame#aboutFeatureTile, QFrame#aboutCard {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
}
QLabel#aboutFeatureTitle, QLabel#aboutCardTitle {
    color: #1a2a3a;
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}
QLabel#aboutFeatureBody {
    color: #617386;
    font-size: 12px;
    background: transparent;
}
QLabel#aboutCardHint, QLabel#aboutLinkHint {
    color: #8a9aab;
    font-size: 11px;
    background: transparent;
}
QLabel#aboutLinkLabel {
    color: #2a3a4a;
    font-size: 13px;
    background: transparent;
}
QPushButton#aboutLinkRow {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0;
    min-height: 44px;
    max-height: 44px;
}
QPushButton#aboutLinkRow:hover {
    background-color: #f0f5fa;
    border: 1px solid #d5dde7;
}
QPushButton#aboutLinkRow:pressed {
    background-color: #e0eef8;
}
QPushButton#aboutLinkRow:focus {
    border: 1px solid #0077b6;
}
QLabel#aboutCredits {
    color: #8a9aab;
    font-size: 11px;
}
QLineEdit[invalid="true"] {
    border: 1px solid #0077b6;
}
QLineEdit[invalid="true"]:focus {
    border: 1px solid #0077b6;
}
QLineEdit:focus, QPushButton:focus {
    border: 1px solid #0077b6;
}

#dialogBtnBar {
    background-color: #eef2f7;
    border-top: 1px solid #c8d0dc;
}

#actionBtn[btn_type="danger"], #dangerBtn {
    background: rgba(220, 38, 38, 0.08);
    border: 1px solid rgba(220, 38, 38, 0.3);
    border-radius: 10px;
    color: #dc2626;
    padding: 0 14px;
    min-height: 32px;
    max-height: 32px;
}
#actionBtn[btn_type="danger"]:hover, #dangerBtn:hover {
    background: rgba(220, 38, 38, 0.15);
    border: 1px solid #dc2626;
}

#actionBtn[btn_type="warning"] {
    background: rgba(217, 119, 6, 0.08);
    border: 1px solid rgba(217, 119, 6, 0.3);
    color: #d97706;
}
#actionBtn[btn_type="warning"]:hover {
    background: rgba(217, 119, 6, 0.15);
    border: 1px solid #d97706;
}

/* Integrated Terminal UI (light) */
#terminalArea {
    background-color: #f0f2f5;
}
#terminalTabBar {
    background-color: #e8edf3;
    border-bottom: 1px solid #c8d0dc;
}
#terminalTabBtn {
    background-color: #f4f7fa;
    border: 1px solid #d5dde7;
    border-radius: 6px;
    color: #6a7a8a;
    padding: 3px 12px;
    min-height: 24px;
    max-height: 24px;
    font-size: 11px;
}
#terminalTabBtn:hover {
    background-color: #edf5fb;
    color: #1a2332;
}
#terminalTabBtn:checked {
    background-color: #edf5fb;
    border-color: #0077b6;
    color: #0077b6;
}
#terminalEndBar {
    background-color: #e8edf3;
    border-top: 1px solid #c8d0dc;
}

QPushButton#sshBtn {
    background: #ffffff;
    border: 1px solid #d5dde7;
    color: #0077b6;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#sshBtn:hover {
    background: rgba(0, 119, 182, 0.10);
    border: 1px solid #72add6;
}
QPushButton#sshBtn:disabled,
QPushButton#sshBtn:disabled:hover {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #95a6b8;
}

QPushButton#cardInfoBtn, QPushButton#cardEditBtn {
    background: #E4EAF0;
    border: 1px solid #d5dde7;
    color: #4a5a6a;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#cardInfoBtn:hover, QPushButton#cardEditBtn:hover {
    background: rgba(0, 119, 182, 0.10);
    border: 1px solid #72add6;
    color: #0077b6;
}
QPushButton#cardEditBtn:disabled {
    color: #b0bac4;
    border: 1px solid #d0d8e4;
    background: #f0f2f5;
}

QPushButton#mountBtn {
    background-color: #ffffff;
    border: 1px solid #aec6dd;
    border-radius: 10px;
    color: #4a5a6a;
    font-size: 12px;
    font-weight: 700;
    padding: 0px;
    text-align: center;
}
QPushButton#mountBtn:hover {
    background-color: rgba(0, 119, 182, 0.10);
    border: 1px solid #72add6;
    color: #0077b6;
}
QPushButton#mountBtn:disabled,
QPushButton#mountBtn:disabled:hover {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #95a6b8;
}
QPushButton#mountBtn[mounted="true"] {
    background-color: rgba(0, 180, 80, 0.10);
    border: 1px solid #007a3d;
    color: #007a3d;
}
QPushButton#mountBtn[mounted="true"]:hover {
    background-color: rgba(220, 38, 38, 0.12);
    border: 1px solid #dc2626;
    color: #dc2626;
}
QPushButton#mountBtn[loading="true"], QPushButton#mountBtn[loading="true"]:disabled {
    background-color: rgba(0, 119, 182, 0.10);
    border: 1px solid rgba(0, 119, 182, 0.24);
    border-radius: 16px;
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 700;
    padding: 0 10px;
}

QLineEdit, QSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #c8d0dc;
    border-radius: 8px;
    color: #1a2332;
    padding: 3px 8px;
    font-size: 13px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #0077b6;
    background-color: #f5faff;
}

/* ---- Stepper (Light) ---------------------------------------- */
QFrame#stepper {
    background-color: #ffffff;
    border: 1px solid #c8d0dc;
    border-radius: 17px;
}
QFrame#stepper QSpinBox#stepperValue,
QFrame#stepper QSpinBox#stepperValue:focus {
    background: transparent;
    border: none;
    padding: 0;
    color: #1a2332;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#stepperBtn {
    background-color: #edf2f7;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    padding: 0;
}
QPushButton#stepperBtn:hover {
    background-color: #e0eef8;
    border: 1px solid #0077b6;
}
QPushButton#stepperBtn:pressed {
    background-color: #c7dfef;
    border: 1px solid #0077b6;
}
QPushButton#stepperBtn:disabled {
    background-color: transparent;
    border: 1px solid #e4e8ef;
}
QLineEdit::placeholder { color: #9aacbe; }
QComboBox::drop-down { border: none; width: 30px; }
QComboBox::down-arrow {
    image: url("__CHEVRON_URL__");
    width: 12px;
    height: 12px;
    margin-right: 10px;
}

/* Dropdown popup (light) */
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #c8d0dc;
    border-radius: 12px;
    color: #1a2332;
    selection-background-color: rgba(0, 119, 182, 0.12);
    selection-color: #0077b6;
    outline: none;
    padding: 1px;
}
QComboBox QAbstractItemView::item {
    padding: 4px 4px;
    min-height: 24px;
    border-radius: 12px;
}
QComboBox QAbstractItemView::item:selected {
    background-color: rgba(0, 119, 182, 0.12);
}

#statusBar {
    background-color: #edf2f7;
    border-top: 1px solid #d5dde7;
    color: #4a5a6a;
    font-family: "Consolas";
    font-size: 12px;
    padding: 10px 14px;
}
#statusDot { color: #007a3d; font-size: 9px; margin-right: 4px; }
#statusText {
    color: #617386;
}
#statusPill {
    background-color: #ffffff;
    color: #0077b6;
    border: 1px solid rgba(0, 119, 182, 0.22);
    border-radius: 999px;
    padding: 4px 9px;
}

#mountErrorDialog {
    background-color: #f6f9fc;
}

#mountErrorLead {
    color: #182536;
    font-size: 13px;
    font-weight: 600;
}

#mountErrorBlock {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 14px;
}

#mountErrorBody {
    color: #617386;
    font-size: 12px;
}

#mountErrorDetails {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    padding: 12px;
}

QProgressBar {
    background-color: #dde2ea;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
    height: 8px;
}
QProgressBar::chunk {
    background-color: #0077b6;
    border-radius: 4px;
}

QTabWidget::pane {
    border: 1px solid #c8d0dc;
    border-radius: 10px;
    background: #f8fafc;
    margin-top: -1px;
}
QTabBar::tab {
    background: transparent;
    border-bottom: 2px solid transparent;
    color: #6a7a8a;
    font-size: 12px;
    padding: 10px 20px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    color: #0077b6;
    border-bottom: 2px solid #0077b6;
    font-weight: 600;
}

QDialog { background-color: #f0f2f5; }

#dialogTitle {
    color: #1a2332;
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 8px;
}

#sectionLabel {
    color: #0077b6;
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    padding-top: 12px;
}

#fieldLabel {
    color: #4a5a6a;
    font-size: 11px;
    font-weight: 600;
    margin-bottom: 2px;
}

QToolTip {
    background-color: #ffffff;
    border: 1px solid #c8d0dc;
    color: #1a2332;
    border-radius: 6px;
    padding: 5px 10px;
}

QMessageBox { background-color: #ffffff; }
QMessageBox QPushButton {
    min-width: 90px;
    min-height: 32px;
    max-height: 32px;
    padding: 0 14px;
}
"""


# ── Gray theme ─────────────────────────────────────────────────────────────
# A neutral gray dark mode after VS Code's "Dark Modern": the dark sheet with
# every navy-tinted neutral moved onto VS Code's grays. Accent shades and the
# semantic colours (green = mounted, red = danger, amber = warning) stay.

_GRAY_MAP = {
    # window, sidebar, headers, status bar
    "#0a0a0f": "#181818", "#0d0d12": "#1f1f1f", "#0a0f15": "#181818",
    "#0d1117": "#1f1f1f", "#0f1218": "#1f1f1f", "#0e0e19": "#181818",
    "#0f0f1a": "#1f1f1f",
    # cards, panels, menus
    "#0d1720": "#2b2b2b", "#0f1720": "#252526", "#13131e": "#252526",
    "#111820": "#252526", "#111822": "#252526", "#101925": "#2d2d2d",
    "#161b22": "#2a2a2a",
    # inputs and buttons
    "#14141f": "#313131", "#141d28": "#313131", "#16162a": "#313131",
    # hover and selection fills
    "#16202c": "#2a2d2e", "#182232": "#37373d", "#192433": "#3c3c3c",
    "#1a1a2e": "#2b2b2b", "#1a2330": "#2b2b2b", "#1e1e2e": "#2b2b2b",
    # borders
    "#1c2633": "#2b2b2b", "#1a2738": "#333333", "#1e1e30": "#3c3c3c",
    "#21262d": "#3c3c3c", "#1f2b3a": "#3c3c3c", "#243243": "#454545",
    "#2a2a4a": "#454545", "#2f4358": "#555555", "#31465d": "#5a5a5a",
    "#3a5068": "#6b6b6b", "#36506c": "#6b6b6b",
    # muted / disabled text and icons
    "#2a3a4a": "#4a4a4a", "#3a3a4a": "#5a5a5a", "#3a4a5a": "#5a5a5a",
    "#3f4e5e": "#6e6e6e", "#556070": "#858585", "#5a6d7e": "#8b8b8b",
    "#607489": "#8b8b8b", "#6a7a8a": "#969696", "#6f8599": "#969696",
    "#8b949e": "#9d9d9d", "#8fa4b8": "#9d9d9d", "#9ab0c5": "#b0b0b0",
    "#aab4c4": "#b5b5b5",
    # text
    "#c1cfdd": "#c5c5c5", "#c8d6e5": "#cccccc", "#d8e4f0": "#d4d4d4",
    "#e4eaf0": "#e0e0e0", "#deebf7": "#e0e0e0", "#e6edf3": "#e0e0e0",
    "#edf4fb": "#e8e8e8",
    # accent tints, re-based on the gray surfaces (still accent shades)
    "#0f2430": "#1a303d", "#10202a": "#222e35", "#172531": "#283139",
    "#0d2137": "#1a2b3d", "#0a1929": "#14212e",
}
_GRAY_RGBA = {
    (8, 12, 18): (12, 12, 12),          # loading overlays
    (17, 24, 34): (37, 37, 38),         # loading cards
    (170, 180, 196): (180, 180, 180),   # scrollbar handle
    (106, 122, 138): (128, 128, 128),   # "+n" group pill
    (96, 116, 137): (120, 120, 120),    # connections badge border
}
_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}\b|rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,")
_ACCENT_SET = frozenset(_ACCENT_HEX)


def _neutral_gray(color: str) -> str:
    """Fallback for a dark-sheet colour missing from _GRAY_MAP."""
    h, l, s = _hls(_hex_rgb(color))
    if s > 0.5:                 # a real colour, not a tinted neutral
        return color
    if l < 0.2:                 # lift backgrounds into VS Code's range
        l = 0.094 + l * 0.6
    v = round(l * 255)
    return "#%02x%02x%02x" % (v, v, v)


def _to_gray(sheet: str) -> str:
    def sub(m):
        if m.group(1) is None:
            c = m.group(0).lower()
            if c in _GRAY_MAP:
                return _GRAY_MAP[c]
            if c in _ACCENT_SET:
                return m.group(0)
            return _neutral_gray(c)
        rgb = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if rgb in _GRAY_RGBA:
            return "rgba(%d, %d, %d," % _GRAY_RGBA[rgb]
        return m.group(0)

    return _COLOR_RE.sub(sub, sheet)


GRAY_STYLESHEET = _to_gray(STYLESHEET)


# ── Black theme (id "dark") ────────────────────────────────────────────────
# A classic dark mode: the navy sheet on plain, untinted blacks and grays,
# darker than the gray theme. The frame (title bar, sidebar, headers, status
# bar) is black, the content a shade above it. Accent shades, accent tints
# and the semantic colours stay as in the dark sheet.

_BLACK_MAP = {
    # window, sidebar, headers, status bar
    "#0a0a0f": "#000000", "#0d0d12": "#0a0a0a", "#0a0f15": "#000000",
    "#0d1117": "#0a0a0a", "#0f1218": "#0a0a0a", "#0e0e19": "#000000",
    "#0f0f1a": "#0a0a0a",
    # cards, panels, menus
    "#0d1720": "#161616", "#0f1720": "#121212", "#13131e": "#121212",
    "#111820": "#121212", "#111822": "#121212", "#101925": "#181818",
    "#161b22": "#151515",
    # inputs and buttons
    "#14141f": "#1a1a1a", "#141d28": "#1a1a1a", "#16162a": "#1a1a1a",
    # hover and selection fills
    "#16202c": "#1c1c1c", "#182232": "#262626", "#192433": "#2a2a2a",
    "#1a1a2e": "#1c1c1c", "#1a2330": "#1c1c1c", "#1e1e2e": "#1c1c1c",
    # borders
    "#1c2633": "#1c1c1c", "#1a2738": "#222222", "#1e1e30": "#262626",
    "#21262d": "#262626", "#1f2b3a": "#262626", "#243243": "#303030",
    "#2a2a4a": "#303030", "#2f4358": "#3d3d3d", "#31465d": "#424242",
    "#3a5068": "#525252", "#36506c": "#525252",
    # muted / disabled text and icons
    "#2a3a4a": "#4a4a4a", "#3a3a4a": "#5a5a5a", "#3a4a5a": "#5a5a5a",
    "#3f4e5e": "#6e6e6e", "#556070": "#858585", "#5a6d7e": "#8b8b8b",
    "#607489": "#8b8b8b", "#6a7a8a": "#969696", "#6f8599": "#969696",
    "#8b949e": "#9d9d9d", "#8fa4b8": "#9d9d9d", "#9ab0c5": "#b0b0b0",
    "#aab4c4": "#b5b5b5",
    # text
    "#c1cfdd": "#c5c5c5", "#c8d6e5": "#d0d0d0", "#d8e4f0": "#d8d8d8",
    "#e4eaf0": "#e2e2e2", "#deebf7": "#e2e2e2", "#e6edf3": "#e2e2e2",
    "#edf4fb": "#ececec",
}
_BLACK_RGBA = {
    (8, 12, 18): (0, 0, 0),             # loading overlays
    (17, 24, 34): (18, 18, 18),         # loading cards
    (170, 180, 196): (170, 170, 170),   # scrollbar handle
    (106, 122, 138): (128, 128, 128),   # "+n" group pill
    (96, 116, 137): (110, 110, 110),    # connections badge border
}


def _neutral_black(color: str) -> str:
    """Fallback for a dark-sheet colour missing from _BLACK_MAP."""
    h, l, s = _hls(_hex_rgb(color))
    if s > 0.5:                 # a real colour, not a tinted neutral
        return color
    if l < 0.2:                 # backgrounds sink towards black
        l *= 0.55
    v = round(l * 255)
    return "#%02x%02x%02x" % (v, v, v)


def _to_black(sheet: str) -> str:
    def sub(m):
        if m.group(1) is None:
            c = m.group(0).lower()
            if c in _BLACK_MAP:
                return _BLACK_MAP[c]
            if c in _ACCENT_SET:
                return m.group(0)
            return _neutral_black(c)
        rgb = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if rgb in _BLACK_RGBA:
            return "rgba(%d, %d, %d," % _BLACK_RGBA[rgb]
        return m.group(0)

    return _COLOR_RE.sub(sub, sheet)


BLACK_STYLESHEET = _to_black(STYLESHEET)


def dark_tone(theme: str, color: str) -> str:
    """A colour picked for the navy sheet as *theme* shows it: the black
    ("dark") and gray themes map it onto their neutrals. For widgets that
    paint colours outside the QSS."""
    if theme == "gray":
        return _to_gray(color)
    if theme == "blue":
        return color
    return _to_black(color)
