"""
help_links.py – Links from the app into the online documentation.

Every help button names a docs page and an anchor on it. The anchors are the
same in both languages; the page is the German one while the UI speaks
German and the English one otherwise (the site has no other languages).
"""

from __future__ import annotations

from src.i18n import current_language

SITE = "https://www.neosshwinmanager.org"

# page -> (German path, English path)
PAGES = {
    "connections": ("/de/docs/verbindungen", "/en/docs/connections"),
    "settings": ("/de/docs/einstellungen", "/en/docs/configuration"),
    "interface": ("/de/docs/oberflaeche", "/en/docs/interface"),
    "users": ("/de/docs/benutzer", "/en/docs/users"),
}

# Anchors on the connections page, one per field of the connection form.
CONNECTION_FORM = "connection-form"
CONNECTION_FIELDS = (
    "field-template", "field-name", "field-protocol", "field-host", "field-port",
    "field-user", "field-auth-method", "field-password", "field-key", "field-ftp-options",
    "field-remote-path", "field-drive-letter", "field-cli-access", "field-putty-key",
    "field-groups", "field-save-as-template",
)


def help_url(page: str, anchor: str = "") -> str:
    """The docs URL of *page* (a key of PAGES) at *anchor*, in the UI language."""
    de, en = PAGES[page]
    path = de if current_language() == "de" else en
    return SITE + path + (f"#{anchor}" if anchor else "")


def open_help(page: str, anchor: str = "") -> None:
    """Open the docs at *page*#*anchor* in the default browser."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl(help_url(page, anchor)))
