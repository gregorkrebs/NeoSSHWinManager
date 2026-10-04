"""
tests/test_about_dialog.py – About dialog: structure, links, translations.
"""

import json
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)


@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_shows_features_and_links(app):
    from PyQt6.QtWidgets import QFrame, QLabel
    from src.ui.dialogs import about_dialog
    dlg = about_dialog.AboutDialog(None)
    tiles = [f for f in dlg.findChildren(QFrame) if f.objectName() == "aboutFeatureTile"]
    assert len(tiles) == len(about_dialog._FEATURES)
    urls = {row.toolTip() for row in dlg.findChildren(about_dialog._LinkRow)}
    assert urls == {
        about_dialog._URL_PROJECT_WEBSITE, about_dialog.docs_url(), about_dialog._URL_PROJECT_GITHUB,
        about_dialog._URL_AUTHOR_WEBSITE, about_dialog._URL_AUTHOR_GITHUB,
    }
    credits = [l for l in dlg.findChildren(QLabel) if l.objectName() == "aboutCredits"][0]
    assert about_dialog._URL_WINFSP in credits.text() and about_dialog._URL_SSHFS_WIN in credits.text()


def test_theme_change_recolours_in_place(app):
    from PyQt6.QtWidgets import QLabel
    from src.ui.dialogs.about_dialog import AboutDialog
    dlg = AboutDialog(None)
    before = len(dlg.findChildren(QLabel))
    dlg.set_dialog_theme("light")
    dlg.set_dialog_theme("gray")
    assert len(dlg.findChildren(QLabel)) == before


def test_copy_version_info(app):
    from PyQt6.QtWidgets import QApplication
    from src.ui.dialogs import about_dialog
    dlg = about_dialog.AboutDialog(None)
    dlg._copy_btn.click()
    text = QApplication.clipboard().text()
    assert about_dialog.APP_VERSION in text and "Windows" in text


def test_host_hint():
    from src.ui.dialogs.about_dialog import _host
    assert _host("https://www.neosshwinmanager.org/") == "neosshwinmanager.org"
    assert _host("https://github.com/gregorkrebs") == "github.com/gregorkrebs"


@pytest.mark.parametrize("lang", ["de", "en", "es", "ru", "nl", "ar"])
def test_all_about_keys_translated(lang):
    from src.ui.dialogs.about_dialog import _FEATURES
    keys = ["about.links.title", "about.project.hint", "about.credits", "about.copy_info",
            "about.copy_info.hint", "about.copy_info.done"]
    for name, _icon in _FEATURES:
        keys += [f"about.feature.{name}.title", f"about.feature.{name}.body"]
    with open(os.path.join(ROOT, "src", "translations", f"{lang}.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert [k for k in keys if not data.get(k)] == []
    assert "{winfsp}" in data["about.credits"] and "{sshfs}" in data["about.credits"]


@pytest.mark.parametrize("name", ["code", "arrow-up-right"])
def test_new_icons_render(app, name):
    from src.ui.icons import pixmap
    assert not pixmap(name, "#ff0000", 18, 2.0).isNull()
