"""
tests/test_ui_translations.py – Every user-visible text goes through tr().

Guards against texts that are written into the code and therefore show up
in the same language (mostly German) whatever the user chose.
"""

import ast
import json
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = pathlib.Path(__file__).resolve().parent.parent
LANGS = ("en", "de", "es", "nl", "ru", "ar")

# Modules nothing imports any more; they still hold old German texts.
LEGACY_MODULES = {
    "src/ui/dialogs/settings_dialog.py",
    "src/ui/dialogs/add_edit_dialog.py",
    "src/ui/loading_overlay.py",
}
LEGACY_CLASSES = {"UserManagementDialog"}  # in login_dialog.py, never instantiated

# Calls whose first argument is shown to the user
TEXT_CALLS = {
    "setToolTip", "setText", "setWindowTitle", "setPlaceholderText", "setStatusTip",
    "addButton", "showMessage", "_set_status", "setTabText", "setTitle",
    "QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QGroupBox", "QToolButton",
}
TEXT_KWARGS = {"yes_text", "no_text"}
# Language-neutral literals: product name, sample values, placeholders
ALLOWED = {"NEO SSH-Win Manager", "root", "web, prod, linux", "SHA-256:"}


def _translations(lang):
    with open(ROOT / "src" / "translations" / f"{lang}.json", encoding="utf-8") as f:
        return json.load(f)


def _source_files():
    files = [ROOT / "main.py", ROOT / "cli_main.py"] + sorted((ROOT / "src").rglob("*.py"))
    return [p for p in files if "translations" not in p.parts]


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8-sig"))


def _walk_skipping(node, skip_classes):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef) and child.name in skip_classes:
            continue
        yield child
        yield from _walk_skipping(child, skip_classes)


def _literal_parts(node):
    """Constant string parts of a literal, f-string or conditional expression."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return ["".join(v.value for v in node.values if isinstance(v, ast.Constant))]
    if isinstance(node, ast.IfExp):
        return _literal_parts(node.body) + _literal_parts(node.orelse)
    return []


def _is_language_text(s):
    s = s.strip()
    if not s or s in ALLOWED or "<a " in s:
        return False
    # paths and URLs ("C:\Program Files\…", "https://…", "/home/user")
    if "\\" in s or "://" in s or s.startswith("/") or re.fullmatch(r"\S*/\S*", s):
        return False
    return re.search(r"[A-Za-zÄÖÜäöüß]{3,}", s) is not None


def test_all_languages_have_the_same_keys():
    en = _translations("en")
    for lang in LANGS[1:]:
        t = _translations(lang)
        assert set(t) == set(en), lang
        assert all(str(v).strip() for v in t.values()), lang


def test_every_tr_key_exists():
    en = _translations("en")
    missing = []
    for path in _source_files():
        for node in ast.walk(_parse(path)):
            if (isinstance(node, ast.Call) and node.args
                    and getattr(node.func, "id", getattr(node.func, "attr", None)) in ("tr", "_tr")
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value not in en):
                missing.append(f"{path.relative_to(ROOT)}:{node.lineno} {node.args[0].value}")
    assert not missing


def test_no_hardcoded_ui_text():
    hits = []
    for path in _source_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in LEGACY_MODULES:
            continue
        for node in _walk_skipping(_parse(path), LEGACY_CLASSES):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            candidates = [kw.value for kw in node.keywords if kw.arg in TEXT_KWARGS]
            if name in TEXT_CALLS and node.args:
                candidates.append(node.args[0])
            if name == "MessageBoxW":  # (hwnd, text, caption, flags)
                candidates += node.args[1:3]
            for cand in candidates:
                for text in _literal_parts(cand):
                    if _is_language_text(text):
                        hits.append(f"{rel}:{node.lineno} {text!r}")
    assert not hits, "\n".join(hits)


def test_legacy_modules_are_not_imported():
    """If one of them is used again, its texts have to be translated first."""
    names = {pathlib.PurePosixPath(m).stem for m in LEGACY_MODULES}
    importers = []
    for path in _source_files():
        if path.relative_to(ROOT).as_posix() in LEGACY_MODULES:
            continue
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[-1] in names:
                importers.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in LEGACY_CLASSES:
                importers.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not importers


# ── the widgets themselves ───────────────────────────────────────────────────

@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=["en", "es", "ru"])
def lang(request):
    from src.i18n import set_language
    set_language(request.param)
    yield request.param
    set_language("en")


def _buttons(widget):
    from PyQt6.QtWidgets import QPushButton
    return {b.text(): b.objectName() for b in widget.findChildren(QPushButton) if b.text()}


def test_question_buttons_follow_language(app, lang):
    from src.ui.dialogs.styled_message_box import StyledMessageBox
    t = _translations(lang)
    plain = _buttons(StyledMessageBox(None, "t", "Delete everything?", "question"))
    assert plain == {t["dialog.no"]: "secondaryBtn", t["dialog.yes"]: "primaryBtn"}
    danger = _buttons(StyledMessageBox(None, "t", "x", "question", destructive=True))
    assert danger[t["dialog.yes"]] == "dangerBtn"
    assert _buttons(StyledMessageBox(None, "t", "x", "info")) == {t["dialog.ok"]: "primaryBtn"}


def test_input_dialog_buttons_follow_language(app, lang):
    from src.ui.dialogs.styled_message_box import StyledInputDialog
    t = _translations(lang)
    assert set(_buttons(StyledInputDialog(None, "t", "label"))) == {t["dialog.cancel"], t["dialog.ok"]}


def test_titlebar_tooltips_follow_language(app, lang):
    from src.ui.custom_titlebar import CustomTitleBar
    t = _translations(lang)
    bar = CustomTitleBar("NEO SSH-Win Manager")
    assert [bar._min_btn.toolTip(), bar._max_btn.toolTip(), bar._close_btn.toolTip()] == \
        [t["window.minimize"], t["window.maximize"], t["dialog.close"]]
    bar.set_maximized(True)
    assert bar._max_btn.toolTip() == t["window.restore"]


def test_ampersand_in_button_text_is_shown(app):
    """Qt reads "&" in button texts as a shortcut marker unless doubled."""
    from PyQt6.QtWidgets import QPushButton
    from src.i18n import set_language
    from src.ui.dialogs.logout_dialog import LogoutConfirmDialog
    set_language("en")
    texts = [b.text() for b in LogoutConfirmDialog().findChildren(QPushButton)]
    assert "Logout && unmount all hosts" in texts


def test_single_user_errors_are_translated():
    from src.auth_manager import SingleUserModeError
    from src.i18n import set_language
    set_language("de")
    try:
        assert SingleUserModeError.text_for(SingleUserModeError("login.single_store_failed")) == \
            _translations("de")["login.single_store_failed"]
        other = SingleUserModeError.text_for(OSError("boom"))
        assert other.startswith(_translations("de")["login.mode_failed"]) and "boom" in other
    finally:
        set_language("en")
