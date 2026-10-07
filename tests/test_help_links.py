"""
tests/test_help_links.py – Help buttons open the online docs at the right
page and anchor, in the UI language.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import help_links


def test_help_url_follows_the_ui_language():
    from src.i18n import current_language, set_language
    before = current_language()
    try:
        set_language("de")
        assert help_links.help_url("connections", "field-remote-path") == \
            "https://www.neosshwinmanager.org/de/docs/verbindungen#field-remote-path"
        set_language("es")      # no Spanish docs: English
        assert help_links.help_url("connections") == "https://www.neosshwinmanager.org/en/docs/connections"
    finally:
        set_language(before)


def test_every_anchor_the_form_uses_is_known():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "ui", "main_window.py"), encoding="utf-8").read()
    used = set(re.findall(r'"(field-[a-z-]+)"', src))
    assert used and used <= set(help_links.CONNECTION_FIELDS)
