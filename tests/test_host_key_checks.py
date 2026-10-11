"""
Host-key checks outside the SFTP browser: the terminal bridge and the external
clients (ssh.exe, sshfs.exe, system info).

No key may ever be trusted without the user's consent, and the key that gets
saved must be the one whose fingerprint the user saw. Up to 1.7.2 the system
info panel added unknown keys silently via ssh-keyscan (and afterwards the
terminal no longer asked either), sshfs and ssh.exe ran with
StrictHostKeyChecking=accept-new, and the terminal asked about a key from a
separate ssh-keyscan connection but saved whatever key its own connection got.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import paramiko  # noqa: E402
import pytest  # noqa: E402

from src import sftp_client  # noqa: E402
from src.config import Connection  # noqa: E402
from src.sftp_client import HostKeyChanged, HostKeyRejected, SftpClientError  # noqa: E402
from src.ui import host_key_utils as hku  # noqa: E402
from src.ui.host_key_utils import key_fingerprint, known_hosts_line  # noqa: E402
from tests import sftp_test_server  # noqa: E402
from tests.sftp_test_server import SftpTestServer  # noqa: E402


class _ShellServer(sftp_test_server._Server):
    """The test server plus the pty/shell requests the terminal needs."""

    def check_channel_pty_request(self, *args):
        return True

    def check_channel_shell_request(self, channel):
        return True


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sftp_client, "_session_keys", {})
    monkeypatch.setattr(hku, "_prompt", None)
    return tmp_path


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(sftp_test_server, "_Server", _ShellServer)
    root = tmp_path / "root"
    root.mkdir()
    with SftpTestServer(str(root)) as srv:
        yield srv


def _known_hosts(home):
    return home / ".ssh" / "known_hosts"


def _name(server):
    return f"[127.0.0.1]:{server.port}"


def _asker(answer, log):
    return lambda host, port, fp: log.append((host, port, fp)) or answer


# ── confirm_host_key / check_host_key ───────────────────────────────────────

def test_unknown_key_is_asked_with_its_real_fingerprint_and_saved(home, server):
    asked = []
    hku.confirm_host_key("127.0.0.1", server.port, ask=_asker(True, asked))
    assert asked == [("127.0.0.1", server.port, key_fingerprint(server._key))]
    assert _known_hosts(home).read_text() == known_hosts_line(_name(server), server._key) + "\n"

    # Known now: no question, not even a registered prompt is needed.
    hku.confirm_host_key("127.0.0.1", server.port)


def test_declined_key_is_refused_and_not_saved(home, server):
    asked = []
    with pytest.raises(HostKeyRejected):
        hku.confirm_host_key("127.0.0.1", server.port, ask=_asker(False, asked))
    assert len(asked) == 1
    assert not _known_hosts(home).exists()


def test_without_any_prompt_unknown_hosts_are_refused(home, server):
    with pytest.raises(HostKeyRejected):
        hku.confirm_host_key("127.0.0.1", server.port)
    assert not _known_hosts(home).exists()


def test_registered_prompt_is_used(home, server):
    asked = []
    hku.set_host_key_prompt(_asker(True, asked))
    hku.confirm_host_key("127.0.0.1", server.port)
    assert len(asked) == 1


def test_changed_key_is_refused_without_asking(home, server):
    other = paramiko.RSAKey.generate(2048)
    _known_hosts(home).parent.mkdir(parents=True)
    _known_hosts(home).write_text(known_hosts_line(_name(server), other) + "\n")
    asked = []
    with pytest.raises(HostKeyChanged) as info:
        hku.confirm_host_key("127.0.0.1", server.port, ask=_asker(True, asked))
    assert asked == []
    assert info.value.fingerprint == key_fingerprint(server._key)


def test_hashed_known_hosts_entry_counts_as_known(home, server):
    hashed = paramiko.HostKeys.hash_host(_name(server))
    _known_hosts(home).parent.mkdir(parents=True)
    _known_hosts(home).write_text(known_hosts_line(hashed, server._key) + "\n")
    assert hku.check_host_key("127.0.0.1", server.port) is None


def test_pending_key_saves_exactly_the_presented_key(home, server):
    pending = hku.check_host_key("127.0.0.1", server.port)
    assert pending.fingerprint == key_fingerprint(server._key)
    assert not _known_hosts(home).exists()          # checking alone saves nothing
    pending.trust()
    assert hku.check_host_key("127.0.0.1", server.port) is None


def test_unreachable_host_raises_client_error(home):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(SftpClientError):
        hku.confirm_host_key("127.0.0.1", port, ask=lambda *a: True, timeout=2)


# ── terminal bridge ─────────────────────────────────────────────────────────

def _terminal_conn(server):
    return Connection(name="t", host="127.0.0.1", user="user", password="pass",
                      port=server.port, auth_method="password")


def test_terminal_declined_key_opens_no_session(home, server):
    from src.terminal.bridge_server import TerminalBridgeServer
    bridge = TerminalBridgeServer()
    asked = []
    bridge.host_key_verify_callback = _asker(False, asked)
    assert bridge.create_session_token("c#1", _terminal_conn(server)) is None
    assert [fp for *_, fp in asked] == [key_fingerprint(server._key)]
    assert not _known_hosts(home).exists()


def test_terminal_saves_the_key_of_its_own_connection(home, server):
    from src.terminal.bridge_server import TerminalBridgeServer
    bridge = TerminalBridgeServer()
    asked = []
    bridge.host_key_verify_callback = _asker(True, asked)
    token = bridge.create_session_token("c#1", _terminal_conn(server))
    try:
        assert token
        assert [fp for *_, fp in asked] == [key_fingerprint(server._key)]
        assert _known_hosts(home).read_text() == known_hosts_line(_name(server), server._key) + "\n"
    finally:
        session = bridge._sessions.pop("c#1", None)
        if session:
            session.client.close()


def test_terminal_refuses_a_changed_key(home, server):
    from src.terminal.bridge_server import TerminalBridgeServer
    other = paramiko.RSAKey.generate(2048)
    _known_hosts(home).parent.mkdir(parents=True)
    _known_hosts(home).write_text(known_hosts_line(_name(server), other) + "\n")
    bridge = TerminalBridgeServer()
    asked = []
    bridge.host_key_verify_callback = _asker(True, asked)
    assert bridge.create_session_token("c#1", _terminal_conn(server)) is None
    assert asked == []


# ── external clients ────────────────────────────────────────────────────────

def test_external_clients_accept_known_keys_only():
    from src import sshfs_controller
    from src.ui import system_info_panel
    assert sshfs_controller._ssh_host_key_check_option() == "StrictHostKeyChecking=yes"
    assert system_info_panel._ssh_host_key_check_option() == "StrictHostKeyChecking=yes"


def test_system_info_reports_an_unknown_key_instead_of_saving_it(home, server, monkeypatch):
    from src.ui.system_info_panel import HostKeyUnknown, SSHSystemInfoThread
    conn = Connection(name="t", host="127.0.0.1", user="user", password="pass",
                      port=server.port, auth_method="password")
    thread = SSHSystemInfoThread(conn)
    monkeypatch.setattr(thread, "_find_ssh_client", lambda: ("ssh.exe", "ssh"))
    with pytest.raises(HostKeyUnknown) as info:
        thread._gather_info()
    assert info.value.pending.fingerprint == key_fingerprint(server._key)
    assert not _known_hosts(home).exists()


def test_option_like_host_or_user_is_refused():
    from src.ssh_args import is_safe_cli_value
    from src.ssh_launcher import _is_safe_ssh_identifier
    assert not is_safe_cli_value("-oProxyCommand=calc.exe")
    assert not is_safe_cli_value("")
    assert not is_safe_cli_value("bad\nname")
    assert is_safe_cli_value("DOMAIN\\user")
    assert is_safe_cli_value("server-01.example.org")
    assert not _is_safe_ssh_identifier("-oProxyCommand")
    assert _is_safe_ssh_identifier("server-01")


def test_sshfs_mount_refuses_option_like_user(monkeypatch):
    from src import sshfs_controller
    monkeypatch.setattr(sshfs_controller, "_find_sshfs_exe", lambda: "sshfs.exe")
    monkeypatch.setattr(sshfs_controller, "_drive_letter_in_use", lambda letter: False)
    ctrl = sshfs_controller.SSHFSController.__new__(sshfs_controller.SSHFSController)
    monkeypatch.setattr(ctrl, "_drive_char", lambda d: "Z", raising=False)
    conn = Connection(name="t", host="example.org", user="-oProxyCommand=calc", password="x")
    result = ctrl._mount_direct(conn)
    assert not result.success
    assert "Ungültig" in result.message


def test_sshfs_log_line_hides_the_remote():
    from src.sshfs_controller import _redact_remote
    line = _redact_remote(["sshfs.exe", "root@example.org:/srv", "Z:"], "root@example.org:/srv")
    assert "example.org" not in line and "<remote>" in line


def test_known_host_needs_no_extra_connection(home, server, monkeypatch):
    from src.ui import system_info_panel
    _known_hosts(home).parent.mkdir(parents=True)
    _known_hosts(home).write_text(known_hosts_line(_name(server), server._key) + "\n")
    assert hku.is_host_known("127.0.0.1", server.port)
    assert not hku.is_host_known("127.0.0.1", server.port + 1)

    probes = []
    monkeypatch.setattr(system_info_panel, "check_host_key", lambda *a, **k: probes.append(a))
    conn = Connection(name="t", host="127.0.0.1", user="user", password="pass",
                      port=server.port, auth_method="password")
    thread = system_info_panel.SSHSystemInfoThread(conn)
    monkeypatch.setattr(thread, "_find_ssh_client", lambda: ("ssh.exe", "ssh"))
    commands = []
    monkeypatch.setattr(system_info_panel.subprocess, "run",
                        lambda cmd, **k: commands.append(cmd) or (_ for _ in ()).throw(OSError("no ssh")))
    try:
        thread._gather_info()
    except Exception:
        pass
    assert probes == []
    assert commands and "StrictHostKeyChecking=yes" in commands[0]
