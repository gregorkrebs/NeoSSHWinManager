"""
What the opt-in telemetry sends: action, version and UI language as query
parameters, and nothing at all without consent.
"""

import urllib.parse
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src import i18n, telemetry


@pytest.fixture
def sent(monkeypatch):
    """Capture the URLs telemetry would open."""
    urls = []

    def fake_urlopen(req, timeout=0):
        urls.append(req.full_url)
        response = MagicMock()
        response.__enter__.return_value.status = 200
        return response

    monkeypatch.setattr(telemetry.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(telemetry, "_app_version", lambda: "1.6.0")
    previous = i18n.current_language()
    yield urls
    i18n.set_language(previous)


def _query(url: str) -> dict:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def test_every_event_carries_version_and_language(sent):
    i18n.set_language("de")
    telemetry.send_telemetry_async("login", SimpleNamespace(telemetry_enabled=True), wait=2)
    assert len(sent) == 1
    assert _query(sent[0]) == {"action": "login", "version": "1.6.0", "language": "de"}


def test_language_follows_the_ui_language(sent):
    i18n.set_language("nl")
    telemetry.send_telemetry_async("update_check", SimpleNamespace(telemetry_enabled=True),
                                   wait=2, source="settings", result="uptodate")
    q = _query(sent[0])
    assert q["language"] == "nl"
    assert q["source"] == "settings" and q["result"] == "uptodate"


def test_nothing_is_sent_without_consent(sent):
    telemetry.send_telemetry_async("login", SimpleNamespace(telemetry_enabled=False), wait=1)
    assert sent == []
