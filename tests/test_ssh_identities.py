"""Default SSH keys for password connections (src/ssh_identities.py).

sshfs and the system info try the user's default keys before the password,
like the terminal and the file browser (paramiko look_for_keys) always did:
a server that accepts keys only can then be mounted too.
"""
import os

import paramiko
import pytest

from src import sshfs_controller
from src.config import Connection
from src.ssh_identities import default_identity_files
from src.sshfs_controller import SSHFSController
from src.ui.system_info_panel import SSHSystemInfoThread


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".ssh").mkdir()
    return tmp_path / ".ssh"


def test_only_default_keys_without_a_passphrase(home):
    paramiko.ECDSAKey.generate().write_private_key_file(str(home / "id_ecdsa"))
    paramiko.RSAKey.generate(2048).write_private_key_file(str(home / "id_rsa"), password="secret")
    (home / "id_ed25519").write_text("not a key", encoding="utf-8")
    paramiko.RSAKey.generate(2048).write_private_key_file(str(home / "id_other"))

    assert default_identity_files() == [str(home / "id_ecdsa")]


def test_no_ssh_folder_means_no_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_identity_files() == []


class _ExitedProcess:
    pid = 4242
    stdin = None

    def __init__(self, code):
        self.code = code

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        pass


def _mount(monkeypatch, tmp_path, keys, stderr_text=b"", code=None):
    """Run _mount_direct for a password connection; returns (result, cmd, popen kwargs)."""
    conn = Connection(name="Server", host="example.test", user="alice", auth_method="password",
                      password="pw", remote_path="/home/alice", drive_letter="X:")
    seen = {}

    def popen(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        kwargs["stderr"].write(stderr_text)

        class _Stdin:
            def write(self, data):
                pass

            def flush(self):
                pass

            def close(self):
                pass
        proc = _ExitedProcess(code)
        proc.stdin = _Stdin()
        return proc

    log_path = str(tmp_path / "sshfs-X.log")
    monkeypatch.setattr(sshfs_controller, "_find_sshfs_exe", lambda: r"C:\sshfs.exe")
    monkeypatch.setattr(sshfs_controller, "_drive_letter_in_use", lambda _letter: False)
    monkeypatch.setattr(sshfs_controller, "_sshfs_log_path", lambda _letter: log_path)
    monkeypatch.setattr(sshfs_controller, "default_identity_files", lambda: keys)
    monkeypatch.setattr(sshfs_controller.subprocess, "Popen", popen)
    monkeypatch.setattr(sshfs_controller.threading, "Thread",
                        lambda target, **_kw: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr(sshfs_controller.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(sshfs_controller, "detect_remote_os", lambda _host, _port: None)
    controller = SSHFSController()
    monkeypatch.setattr(controller, "_stop_mount_process", lambda _letter, _proc: None)
    return controller._mount_direct(conn), seen["cmd"], seen["kwargs"]


def test_mount_with_a_password_tries_the_default_keys_first(monkeypatch, tmp_path):
    keys = [r"C:\Users\alice\.ssh\id_ed25519", r"C:\Users\alice\.ssh\id_rsa"]
    _result, cmd, _kwargs = _mount(monkeypatch, tmp_path, keys, code=1)
    assert "-oIdentityFile=C:/Users/alice/.ssh/id_ed25519" in cmd
    assert "-oIdentityFile=C:/Users/alice/.ssh/id_rsa" in cmd
    assert "-oIdentitiesOnly=yes" in cmd
    assert "-oPreferredAuthentications=publickey,password,keyboard-interactive" in cmd
    assert "-opassword_stdin" in cmd


def test_mount_with_a_password_and_no_default_keys_is_unchanged(monkeypatch, tmp_path):
    _result, cmd, _kwargs = _mount(monkeypatch, tmp_path, [], code=1)
    assert not any(c.startswith("-oIdentityFile=") or c == "-oIdentitiesOnly=yes" for c in cmd)
    assert "-oPreferredAuthentications=password,keyboard-interactive" in cmd


def test_failed_mount_shows_what_sshfs_said(monkeypatch, tmp_path):
    result, _cmd, kwargs = _mount(
        monkeypatch, tmp_path, [],
        stderr_text=b"alice@example.test: Permission denied (publickey).\r\nread: Connection reset by peer\r\n",
        code=1)
    assert kwargs["stderr"] not in (sshfs_controller.subprocess.PIPE, sshfs_controller.subprocess.DEVNULL)
    assert result.success is False
    assert "(Code 1)" in result.message
    assert "alice@example.test: Permission denied (publickey)." in result.message
    assert "read: Connection reset by peer" in result.message


def test_system_info_with_a_password_tries_the_default_keys_first(monkeypatch):
    import src.ui.system_info_panel as sip
    monkeypatch.setattr(sip, "default_identity_files", lambda: [r"C:\Users\alice\.ssh\id_ed25519"])
    conn = Connection(name="Server", host="example.test", user="alice", auth_method="password",
                      password="pw")
    cmd, target = SSHSystemInfoThread(conn)._build_ssh_command(r"C:\ssh.exe")
    assert target == "alice@example.test"
    i = cmd.index("-i")
    assert cmd[i + 1] == r"C:\Users\alice\.ssh\id_ed25519"
    assert "IdentitiesOnly=yes" in cmd
    assert "PreferredAuthentications=publickey,password,keyboard-interactive" in cmd
    assert "BatchMode=no" in cmd


def test_system_info_with_a_password_and_no_default_keys_is_unchanged(monkeypatch):
    import src.ui.system_info_panel as sip
    monkeypatch.setattr(sip, "default_identity_files", lambda: [])
    conn = Connection(name="Server", host="example.test", user="alice", auth_method="password",
                      password="pw")
    cmd, _target = SSHSystemInfoThread(conn)._build_ssh_command(r"C:\ssh.exe")
    assert "-i" not in cmd and "IdentitiesOnly=yes" not in cmd
    assert "PreferredAuthentications=password,keyboard-interactive" in cmd


def test_error_output_keeps_the_headline_of_a_changed_host_key(tmp_path):
    log = tmp_path / "sshfs-V.log"
    log.write_bytes(
        b"@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\r\n"
        b"@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @\r\n"
        b"@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\r\n"
        b"IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!\r\n"
        b"Please contact your system administrator.\r\n"
        b"Offending RSA key in C:/Users/alice/.ssh/known_hosts:2\r\n"
        b"ECDSA host key for example.test has changed and you have requested strict checking.\r\n"
        b"Host key verification failed.\r\n"
        b"read: Connection reset by peer\r\n")
    out = sshfs_controller._sshfs_error_output(str(log)).splitlines()
    assert out[0] == "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!"
    assert out[1] == "..."
    assert out[-2:] == ["Host key verification failed.", "read: Connection reset by peer"]
    assert len(out) == 6 and not any("@" in line for line in out)
