"""
The named pipe to the GUI instance (src/ipc_security.py).

Clients (askpass helper, CLI) must not send a token or access key to a pipe
that another account created; the server must not join a pipe somebody else
created first and must reject remote clients. The Windows calls are replaced
by fakes, so the decisions can be checked on any platform.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import ipc_security as ipc  # noqa: E402


class _FakeKernel32:
    def __init__(self, pipe_exists=True, server_pid=4242):
        self.pipe_exists = pipe_exists
        self.server_pid = server_pid
        self.closed = []
        self.written = []

    def WaitNamedPipeW(self, name, timeout):
        return self.pipe_exists

    def CreateFileW(self, *args):
        return 77

    def GetNamedPipeServerProcessId(self, handle, pid_ref):
        pid_ref._obj.value = self.server_pid
        return True

    def SetNamedPipeHandleState(self, *args):
        return True

    def WriteFile(self, handle, data, size, written_ref, overlapped):
        self.written.append(bytes(data))
        return True

    def ReadFile(self, handle, buf, size, read_ref, overlapped):
        reply = b'{"success": true, "password": "pw"}'
        buf.raw = reply + buf.raw[len(reply):]
        read_ref._obj.value = len(reply)
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


@pytest.fixture
def fake(monkeypatch):
    k = _FakeKernel32()
    monkeypatch.setattr(ipc, "_libs", lambda: (k, None))
    monkeypatch.setattr(ipc.sys, "platform", "win32")
    return k


def test_nothing_is_sent_to_a_pipe_of_another_account(fake, monkeypatch):
    monkeypatch.setattr(ipc, "process_runs_as_current_user", lambda pid: False)
    with pytest.raises(ipc.IpcUntrustedServer):
        ipc.request({"action": "get_askpass", "token": "secret"})
    assert fake.written == []
    assert fake.closed == [77]


def test_request_to_own_app_is_answered(fake, monkeypatch):
    checked = []
    monkeypatch.setattr(ipc, "process_runs_as_current_user", lambda pid: checked.append(pid) or True)
    reply = ipc.request({"action": "get_askpass", "token": "t"})
    assert reply == {"success": True, "password": "pw"}
    assert checked == [4242]
    assert b'"get_askpass"' in fake.written[0]
    assert fake.closed == [77]


def test_missing_pipe_means_not_running(fake):
    fake.pipe_exists = False
    with pytest.raises(ipc.IpcNotRunning):
        ipc.request({"action": "cli_connect", "key": "k"})


def test_requests_need_windows(monkeypatch):
    monkeypatch.setattr(ipc.sys, "platform", "linux")
    with pytest.raises(ipc.IpcNotRunning):
        ipc.request({"action": "cli_connect", "key": "k"})


def test_server_pipe_rejects_remote_clients_and_is_message_based():
    assert ipc.SERVER_PIPE_MODE & ipc.PIPE_REJECT_REMOTE_CLIENTS
    assert ipc.SERVER_PIPE_MODE & ipc.PIPE_TYPE_MESSAGE
    assert ipc.FILE_FLAG_FIRST_PIPE_INSTANCE == 0x00080000


def test_clients_use_the_checked_request():
    root = os.path.join(os.path.dirname(__file__), "..")
    for rel in ("main.py", "cli_main.py", os.path.join("src", "ssh_launcher.py")):
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            source = f.read()
        assert r"\\.\pipe" not in source, rel        # no own, unchecked pipe client
        assert "ipc_security import" in source, rel
