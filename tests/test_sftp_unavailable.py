"""
A server that logs the user in but does not start SFTP (web hosting without
SSH access, an extra FTP user, no "Subsystem sftp", a forced command such as
cloud-init's "Please login as the user ...") is explained in plain words, in
the file browser and when mounting, instead of paramiko's "EOF during
negotiation" or sshfs's "remote host has disconnected". A refused key offers
the stored password once, never in a loop.
"""

import copy
from types import SimpleNamespace

import pytest

from src import sftp_client, sshfs_controller
from src.config import Connection
from src.filebrowser.ui.session import HostSession
from src.i18n import set_language, tr
from src.sftp_client import AuthenticationFailed, SftpClient, SftpUnavailable
from src.sshfs_controller import MountResult
from src.ui.host_key_utils import known_hosts_line
from tests.sftp_test_server import NOTICE, SftpTestServer
from tests.test_ssh_identities import _mount


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sftp_client, "_session_keys", {})
    return tmp_path


@pytest.fixture
def german():
    set_language("de")
    yield
    set_language("en")


@pytest.fixture
def server_factory(tmp_path):
    servers = []

    def make(sftp):
        root = tmp_path / "root"
        root.mkdir(exist_ok=True)
        server = SftpTestServer(str(root), sftp=sftp).__enter__()
        servers.append(server)
        return server
    yield make
    for server in servers:
        server.close()


def _conn(server, password="pass"):
    return Connection(name="t", host="127.0.0.1", user="user", password=password, port=server.port)


def _connect(server, password="pass"):
    client = SftpClient()
    try:
        client.connect(_conn(server, password), tofu_callback=lambda *_a: True)
    finally:
        client.disconnect()


def _shown(error) -> str:
    return HostSession.error_text(SimpleNamespace(error=error))


def test_sftp_closed_after_login_is_explained(server_factory, german):
    with pytest.raises(SftpUnavailable) as info:
        _connect(server_factory("closed"))
    assert info.value.detail == "EOF during negotiation"
    assert info.value.server_message == ""
    text = _shown(info.value)
    assert text.startswith("Die Anmeldung hat geklappt, aber der Server startet für diesen "
                           "Benutzer kein SFTP.\n\n• Webhosting:")
    assert "FTPS" in text and "SSH-Zugang" in text and "Der Server meldet" not in text
    assert text.endswith("\n\nTechnische Details: EOF during negotiation")


def test_sftp_refused_after_login_is_explained(server_factory):
    with pytest.raises(SftpUnavailable) as info:
        _connect(server_factory("missing"))
    text = _shown(info.value)
    assert text.startswith("Logging in worked, but the server does not start SFTP")
    assert text.endswith(f"Technical details: {info.value.detail}")


def test_the_servers_notice_is_shown(server_factory, german):
    # root on an Ubuntu cloud image: the key is accepted, a forced command
    # prints the notice instead of starting SFTP.
    with pytest.raises(SftpUnavailable) as info:
        _connect(server_factory("notice"))
    assert info.value.detail == "Garbage packet received"
    assert info.value.server_message == NOTICE
    text = _shown(info.value)
    assert text.split("\n\n")[1] == f"Der Server meldet: {NOTICE}"


def test_wrong_password_is_not_taken_for_missing_sftp(server_factory, german):
    with pytest.raises(AuthenticationFailed) as info:
        _connect(server_factory("closed"), password="wrong")
    assert _shown(info.value) == tr("sftp.error.auth_failed") == "Authentifizierung fehlgeschlagen"


def test_working_sftp_still_connects(server_factory):
    _connect(server_factory("on"))


# ── mounting ─────────────────────────────────────────────────────────────────

def _known(home, server):
    # After a mount the host is in known_hosts: sshfs added it.
    (home / ".ssh").mkdir(exist_ok=True)
    with open(home / ".ssh" / "known_hosts", "a") as f:
        f.write(known_hosts_line(f"[127.0.0.1]:{server.port}", server._key) + "\n")
    return server


def test_mount_diagnosis_reads_the_servers_notice(server_factory, home):
    error = sshfs_controller._sftp_unavailable(_conn(_known(home, server_factory("notice"))))
    assert isinstance(error, SftpUnavailable) and error.server_message == NOTICE


def test_mount_diagnosis_gives_up_quietly(server_factory, home):
    # SFTP works (the mount failed for another reason): nothing to explain
    assert sshfs_controller._sftp_unavailable(_conn(_known(home, server_factory("on")))) is None
    # unknown host: no question from the mount thread, no diagnosis
    assert sshfs_controller._sftp_unavailable(_conn(server_factory("notice"))) is None


def test_mount_that_was_disconnected_after_login_explains_why(monkeypatch, tmp_path, german):
    seen = []

    def diagnose(conn):
        seen.append(conn.user)
        return SftpUnavailable("Garbage packet received", NOTICE)
    monkeypatch.setattr(sshfs_controller, "_sftp_unavailable", diagnose)
    result, _cmd, _kw = _mount(monkeypatch, tmp_path, [], stderr_text=b"remote host has disconnected\r\n",
                               code=1)
    assert seen == ["alice"]
    assert result.success is False and result.code == "sftp_unavailable"
    assert f"Der Server meldet: {NOTICE}" in result.message


def test_mount_disconnect_without_diagnosis_keeps_the_sshfs_message(monkeypatch, tmp_path):
    monkeypatch.setattr(sshfs_controller, "_sftp_unavailable", lambda conn: None)
    result, _cmd, _kw = _mount(monkeypatch, tmp_path, [], stderr_text=b"remote host has disconnected\r\n",
                               code=1)
    assert result.code == "" and "remote host has disconnected" in result.message


def test_refused_login_is_marked_for_the_password_question(monkeypatch, tmp_path):
    monkeypatch.setattr(sshfs_controller, "_sftp_unavailable",
                        lambda conn: pytest.fail("no diagnosis for a refused login"))
    result, _cmd, _kw = _mount(monkeypatch, tmp_path, [],
                               stderr_text=b"alice@example.test: Permission denied (publickey).\r\n", code=1)
    assert result.code == "auth_failed"


# ── the password question after a refused key ────────────────────────────────

class _Window:
    """Just what MainWindow._on_mount_finished uses."""

    def __init__(self, conn):
        from src.ui.main_window import MainWindow
        self._on_mount_finished = MainWindow._on_mount_finished.__get__(self)
        self._retry_mount_with_password = MainWindow._retry_mount_with_password.__get__(self)
        self._workers, self._mount_targets, self._cards = {}, {}, {}
        self._letter_retry, self._password_retry = set(), set()
        self._mgr = SimpleNamespace(get_by_id=lambda _id: copy.copy(conn))
        self.asked, self.failures, self.started, self.errors = [], [], [], []

    def _show_key_fallback_dialog(self, conn):
        self.asked.append(conn.auth_method)
        return True

    def _show_mount_failure_dialog(self, conn, message):
        self.failures.append(message)
        return False

    def _start_mount_worker(self, conn_id, conn, letter):
        self.started.append((conn.auth_method, letter))

    def _set_status(self, _text):
        pass

    def _update_status(self):
        pass

    def _apply_list_filters(self):
        pass


@pytest.fixture
def window(monkeypatch):
    import src.ui.main_window as mw
    monkeypatch.setattr(mw, "QTimer", SimpleNamespace(singleShot=lambda _ms, fn: fn()))
    conn = Connection(name="192.168.50.114", host="192.168.50.114", user="root", auth_method="key",
                      key_path=r"C:\Users\me\.ssh\id_ed25519", password="pw", drive_letter="V:")
    win = _Window(conn)
    monkeypatch.setattr(mw, "StyledMessageBox",
                        SimpleNamespace(critical=lambda _p, title, text: win.errors.append(text)))
    return win


def test_failed_password_retry_does_not_ask_again(window):
    refused = MountResult(False, "Permission denied (publickey).", "auth_failed")
    window._on_mount_finished("c1", refused)
    assert window.asked == ["key"] and window.started == [("password", "V:")]

    window._on_mount_finished("c1", MountResult(False, "Permission denied (publickey).", "auth_failed"))
    assert window.asked == ["key"]                       # not asked a second time
    assert window.failures == ["Permission denied (publickey)."]

    window._on_mount_finished("c1", refused)             # a new mount may ask again
    assert window.asked == ["key", "key"]


def test_password_is_offered_only_when_the_login_was_refused(window):
    window._on_mount_finished("c1", MountResult(False, "Zeitüberschreitung beim Einbinden"))
    assert window.asked == [] and window.failures == ["Zeitüberschreitung beim Einbinden"]


def test_sftp_unavailable_is_shown_without_password_or_retry(window):
    window._on_mount_finished("c1", MountResult(False, "Die Anmeldung hat geklappt ...", "sftp_unavailable"))
    assert window.asked == [] and window.failures == [] and window.started == []
    assert window.errors == ["192.168.50.114\n\nDie Anmeldung hat geklappt ..."]
