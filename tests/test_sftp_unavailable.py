"""
A server that logs the user in but does not start SFTP (web hosting without
SSH access, an extra FTP user, no "Subsystem sftp"): the file browser says so
in plain words instead of paramiko's "EOF during negotiation".
"""

from types import SimpleNamespace

import pytest

from src import sftp_client
from src.config import Connection
from src.filebrowser.ui.session import HostSession
from src.i18n import set_language, tr
from src.sftp_client import AuthenticationFailed, SftpClient, SftpUnavailable
from tests.sftp_test_server import SftpTestServer


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sftp_client, "_session_keys", {})


@pytest.fixture
def german():
    set_language("de")
    yield
    set_language("en")


def _connect(tmp_path, sftp, password="pass"):
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    with SftpTestServer(str(root), sftp=sftp) as server:
        conn = Connection(name="t", host="127.0.0.1", user="user", password=password,
                          port=server.port)
        client = SftpClient()
        try:
            client.connect(conn, tofu_callback=lambda *_a: True)
        finally:
            client.disconnect()


def _shown(error) -> str:
    return HostSession.error_text(SimpleNamespace(error=error))


def test_sftp_closed_after_login_is_explained(tmp_path, german):
    with pytest.raises(SftpUnavailable) as info:
        _connect(tmp_path, "closed")
    assert info.value.detail == "EOF during negotiation"
    text = _shown(info.value)
    assert text.startswith("Die Anmeldung hat geklappt, aber der Server startet für diesen "
                           "Benutzer kein SFTP.")
    assert "FTPS" in text and "SSH-Zugang" in text
    assert text.endswith("Technische Details: EOF during negotiation")


def test_sftp_refused_after_login_is_explained(tmp_path):
    with pytest.raises(SftpUnavailable) as info:
        _connect(tmp_path, "missing")
    text = _shown(info.value)
    assert text.startswith("Logging in worked, but the server does not start SFTP")
    assert text.endswith(f"Technical details: {info.value.detail}")


def test_wrong_password_is_not_taken_for_missing_sftp(tmp_path, german):
    with pytest.raises(AuthenticationFailed) as info:
        _connect(tmp_path, "closed", password="wrong")
    assert _shown(info.value) == tr("sftp.error.auth_failed") == "Authentifizierung fehlgeschlagen"


def test_working_sftp_still_connects(tmp_path):
    _connect(tmp_path, "on")
