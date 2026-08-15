from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import sshfs_controller
from src.config import Connection
from src.sshfs_controller import SSHFSController, _find_sshfs_pid_for_drive


class _FakeProcessInfo:
    def __init__(self, pid, name, cmdline):
        self.info = {"pid": pid, "name": name, "cmdline": cmdline}


class _RunningProcess:
    def __init__(self, pid=4242):
        self.pid = pid
        self.stdin = None
        self.killed = False
        self.wait_calls = 0

    def poll(self):
        return None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.wait_calls += 1
        return 0


class _CapturedThread:
    created = []

    def __init__(self, target, **_kwargs):
        self.target = target
        self.created.append(self)

    def start(self):
        pass


def test_find_sshfs_pid_matches_mount_argument_exactly(monkeypatch):
    processes = [
        _FakeProcessInfo(
            101,
            "sshfs.exe",
            ["sshfs.exe", "user@host:/", "Y:", r"-oIdentityFile=X:\keys\id_ed25519"],
        ),
        _FakeProcessInfo(202, "SSHFS.EXE", ["sshfs.exe", "user@host:/", "x:\\"]),
    ]
    monkeypatch.setattr(sshfs_controller.psutil, "process_iter", lambda _attrs: processes)

    assert _find_sshfs_pid_for_drive("X:") == 202


@pytest.mark.parametrize("drive_letter", ["", "XY:", "1:", "Ä:"])
def test_find_sshfs_pid_rejects_invalid_drive_letters(monkeypatch, drive_letter):
    process_iter = Mock()
    monkeypatch.setattr(sshfs_controller.psutil, "process_iter", process_iter)

    assert _find_sshfs_pid_for_drive(drive_letter) is None
    process_iter.assert_not_called()


def test_direct_mount_uses_parent_independent_stdio_and_stable_drive(
    monkeypatch, tmp_path
):
    key_path = tmp_path / "id_ed25519"
    key_path.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n", encoding="utf-8")
    conn = Connection(
        name="Server",
        host="example.test",
        user="alice",
        auth_method="key",
        key_path=str(key_path),
        drive_letter="X:",
    )
    proc = _RunningProcess()
    popen = Mock(return_value=proc)
    drive_states = iter([False, False, True, True, True])
    _CapturedThread.created.clear()
    monkeypatch.setattr(sshfs_controller, "_find_sshfs_exe", lambda: r"C:\sshfs.exe")
    monkeypatch.setattr(
        sshfs_controller,
        "_drive_letter_in_use",
        lambda _letter: next(drive_states),
    )
    monkeypatch.setattr(sshfs_controller.subprocess, "Popen", popen)
    monkeypatch.setattr(sshfs_controller.threading, "Thread", _CapturedThread)
    monkeypatch.setattr(sshfs_controller.time, "sleep", lambda _seconds: None)

    controller = SSHFSController()
    result = controller._mount_direct(conn)

    assert result.success is True
    cmd = popen.call_args.args[0]
    assert "-f" in cmd
    assert "-odebug" not in cmd
    assert "-ologlevel=debug1" not in cmd
    assert popen.call_args.kwargs["stdout"] is sshfs_controller.subprocess.DEVNULL
    assert popen.call_args.kwargs["stderr"] is sshfs_controller.subprocess.DEVNULL
    assert controller._get_mount_process("X:") is proc

    _CapturedThread.created[0].target()
    assert proc.wait_calls == 1
    assert controller._get_mount_process("X:") is None


def test_direct_mount_rejects_preoccupied_drive(monkeypatch, tmp_path):
    key_path = tmp_path / "id_ed25519"
    key_path.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n", encoding="utf-8")
    conn = Connection(
        name="Server",
        host="example.test",
        user="alice",
        auth_method="key",
        key_path=str(key_path),
        drive_letter="X:",
    )
    popen = Mock()
    monkeypatch.setattr(sshfs_controller, "_find_sshfs_exe", lambda: r"C:\sshfs.exe")
    monkeypatch.setattr(sshfs_controller, "_drive_letter_in_use", lambda _letter: True)
    monkeypatch.setattr(sshfs_controller.subprocess, "Popen", popen)

    result = SSHFSController()._mount_direct(conn)

    assert result.success is False
    assert "bereits belegt" in result.message
    popen.assert_not_called()


def test_unexpected_error_after_popen_stops_and_forgets_process(
    monkeypatch, tmp_path
):
    key_path = tmp_path / "id_ed25519"
    key_path.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n", encoding="utf-8")
    conn = Connection(
        name="Server",
        host="example.test",
        user="alice",
        auth_method="key",
        key_path=str(key_path),
        drive_letter="X:",
    )
    proc = _RunningProcess()

    class _BrokenThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("thread start failed")

    monkeypatch.setattr(sshfs_controller, "_find_sshfs_exe", lambda: r"C:\sshfs.exe")
    monkeypatch.setattr(sshfs_controller, "_drive_letter_in_use", lambda _letter: False)
    monkeypatch.setattr(sshfs_controller.subprocess, "Popen", Mock(return_value=proc))
    monkeypatch.setattr(sshfs_controller.threading, "Thread", _BrokenThread)

    controller = SSHFSController()
    result = controller._mount_direct(conn)

    assert result.success is False
    assert "thread start failed" in result.message
    assert proc.killed is True
    assert proc.wait_calls == 1
    assert controller._get_mount_process("X:") is None


def test_unmount_already_disconnected_is_success_without_delay(monkeypatch):
    controller = SSHFSController()
    cleanup = Mock()
    monkeypatch.setattr(controller, "_get_actual_unc", lambda _letter: None)
    monkeypatch.setattr(controller, "_cleanup_drive_label", cleanup)
    monkeypatch.setattr(sshfs_controller, "_find_sshfs_pid_for_drive", lambda _letter: None)
    monkeypatch.setattr(sshfs_controller, "_drive_letter_in_use", lambda _letter: False)
    root_absent = Mock()
    monkeypatch.setattr(
        sshfs_controller, "_drive_root_definitely_absent", root_absent
    )
    sleep = Mock()
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(sshfs_controller.time, "sleep", sleep)
    monkeypatch.setattr(sshfs_controller.subprocess, "run", run)

    result = controller.unmount("x")

    assert result.success is True
    assert "bereits getrennt" in result.message
    cleanup.assert_called_once_with("X:", known_unc=None)
    sleep.assert_not_called()
    run.assert_not_called()
    root_absent.assert_not_called()


@pytest.mark.parametrize(
    ("drive_type", "expected"),
    [
        (0, False),
        (1, True),
        (2, False),
        (3, False),
        (4, False),
        (5, False),
        (6, False),
    ],
)
def test_drive_root_absence_requires_no_root_dir(
    monkeypatch, drive_type, expected
):
    roots = []

    class _Kernel32:
        def GetDriveTypeW(self, root):
            roots.append(root.value)
            return drive_type

    monkeypatch.setattr(
        sshfs_controller.ctypes,
        "windll",
        SimpleNamespace(kernel32=_Kernel32()),
    )

    assert sshfs_controller._drive_root_definitely_absent("x:") is expected
    assert roots == ["X:\\"]


def test_unmount_stale_logical_drive_bit_is_already_disconnected(monkeypatch):
    controller = SSHFSController()
    cleanup = Mock()
    root_absent = Mock(return_value=True)
    monkeypatch.setattr(controller, "_get_actual_unc", lambda _letter: None)
    monkeypatch.setattr(controller, "_cleanup_drive_label", cleanup)
    monkeypatch.setattr(
        sshfs_controller, "_find_sshfs_pid_for_drive", lambda _letter: None
    )
    monkeypatch.setattr(sshfs_controller, "_drive_letter_in_use", lambda _letter: True)
    monkeypatch.setattr(
        sshfs_controller, "_drive_root_definitely_absent", root_absent
    )
    sleep = Mock()
    run = Mock()
    monkeypatch.setattr(sshfs_controller.time, "sleep", sleep)
    monkeypatch.setattr(sshfs_controller.subprocess, "run", run)

    result = controller.unmount("x")

    assert result.success is True
    assert "bereits getrennt" in result.message
    root_absent.assert_called_once_with("X:")
    cleanup.assert_called_once_with("X:", known_unc=None)
    sleep.assert_not_called()
    run.assert_not_called()


def test_unmount_does_not_hide_present_root_without_sshfs_pid(monkeypatch):
    controller = SSHFSController()
    cleanup = Mock()
    escalation = Mock(return_value=False)
    monkeypatch.setattr(controller, "_get_actual_unc", lambda _letter: None)
    monkeypatch.setattr(controller, "_cleanup_drive_label", cleanup)
    monkeypatch.setattr(controller, "_force_kill_escalation", escalation)
    monkeypatch.setattr(
        sshfs_controller, "_find_sshfs_pid_for_drive", lambda _letter: None
    )
    monkeypatch.setattr(sshfs_controller, "_drive_letter_in_use", lambda _letter: True)
    monkeypatch.setattr(
        sshfs_controller,
        "_drive_root_definitely_absent",
        lambda _letter: False,
    )
    monkeypatch.setattr(sshfs_controller.os.path, "exists", lambda _path: False)
    monkeypatch.setattr(sshfs_controller.time, "sleep", lambda _seconds: None)
    run = Mock()
    monkeypatch.setattr(sshfs_controller.subprocess, "run", run)

    result = controller.unmount("x")

    assert result.success is False
    cleanup.assert_not_called()
    escalation.assert_called_once()
    run.assert_not_called()


def test_unmount_prefers_retained_process(monkeypatch):
    controller = SSHFSController()
    proc = _RunningProcess()
    controller._remember_mount_process("X:", proc)
    cleanup = Mock()
    drive_states = iter([True, False])
    monkeypatch.setattr(controller, "_get_actual_unc", lambda _letter: None)
    monkeypatch.setattr(controller, "_cleanup_drive_label", cleanup)
    discovered_pid = Mock(return_value=9999)
    monkeypatch.setattr(sshfs_controller, "_find_sshfs_pid_for_drive", discovered_pid)
    monkeypatch.setattr(
        sshfs_controller, "_drive_letter_in_use", lambda _letter: next(drive_states)
    )
    monkeypatch.setattr(sshfs_controller.time, "sleep", lambda _seconds: None)
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(sshfs_controller.subprocess, "run", run)

    result = controller.unmount("x:")

    assert result.success is True
    discovered_pid.assert_not_called()
    run.assert_called_once_with(
        ["taskkill", "/F", "/PID", "4242"],
        capture_output=True,
        timeout=5,
        creationflags=0x08000000,
    )
    cleanup.assert_called_once_with("X:", known_unc=None)
    assert controller._get_mount_process("X:") is None


def test_unmount_accepts_no_root_state_after_process_kill(monkeypatch):
    controller = SSHFSController()
    cleanup = Mock()
    discovered_pids = iter([4242, None])
    monkeypatch.setattr(controller, "_get_actual_unc", lambda _letter: None)
    monkeypatch.setattr(controller, "_cleanup_drive_label", cleanup)
    monkeypatch.setattr(
        sshfs_controller,
        "_find_sshfs_pid_for_drive",
        lambda _letter: next(discovered_pids),
    )
    monkeypatch.setattr(sshfs_controller, "_drive_letter_in_use", lambda _letter: True)
    root_absent = Mock(return_value=True)
    monkeypatch.setattr(
        sshfs_controller, "_drive_root_definitely_absent", root_absent
    )
    monkeypatch.setattr(sshfs_controller.time, "sleep", lambda _seconds: None)
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(sshfs_controller.subprocess, "run", run)

    result = controller.unmount("x:")

    assert result.success is True
    run.assert_called_once_with(
        ["taskkill", "/F", "/PID", "4242"],
        capture_output=True,
        timeout=5,
        creationflags=0x08000000,
    )
    root_absent.assert_called_once_with("X:")
    cleanup.assert_called_once_with("X:", known_unc=None)


def test_stale_label_job_does_not_touch_missing_drive(monkeypatch):
    controller = SSHFSController()
    conn = Connection(
        name="Server",
        host="example.test",
        user="alice",
        drive_letter="X:",
    )
    _CapturedThread.created.clear()
    monkeypatch.setattr(sshfs_controller.threading, "Thread", _CapturedThread)
    monkeypatch.setattr(sshfs_controller, "_drive_letter_in_use", lambda _letter: False)
    run = Mock()
    monkeypatch.setattr(sshfs_controller.subprocess, "run", run)

    controller._set_drive_label(conn, delay=0)
    _CapturedThread.created[0].target()

    run.assert_not_called()
