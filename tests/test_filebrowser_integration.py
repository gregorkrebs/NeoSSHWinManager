"""
End-to-end tests of the file browser core against a real (local) SFTP server:
file-system operations, the transfer queue (trees, conflicts, pause/resume,
reconnect, cancel, rate limit, URL upload, sync) and the generated shell
commands executed for real (Git Bash for Linux, PowerShell for Windows).
"""

import functools
import hashlib
import http.server
import os
import shutil
import subprocess
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.filebrowser import commands  # noqa: E402
from src.filebrowser.fs import LocalFS, SftpFS  # noqa: E402
from src.filebrowser.model import KEEP_BOTH, SYNC_UPLOAD, SyncSide, compare_trees  # noqa: E402
from src.filebrowser.settings import MemoryStore, SettingsManager  # noqa: E402
from src.filebrowser.transfers import (  # noqa: E402
    CANCELLED, DONE, PAUSED, SKIPPED, TransferQueue,
)
from tests.sftp_test_server import SftpTestServer  # noqa: E402

GIT_BASH = r"C:\Program Files\Git\bin\bash.exe"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def remote_root(tmp_path):
    root = tmp_path / "remote"
    root.mkdir()
    return root


@pytest.fixture
def server(remote_root):
    with SftpTestServer(str(remote_root)) as srv:
        yield srv


@pytest.fixture
def fs(server):
    sftp_fs = SftpFS(server.connect(), reconnect=server.connect)
    yield sftp_fs
    sftp_fs.close()


def _queue(fs, resolver=None, **settings):
    manager = SettingsManager(MemoryStore(settings))
    return TransferQueue(fs, manager, resolver or (lambda info: (KEEP_BOTH, False)))


def _wait(queue, qapp, timeout=30.0, until=None):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if until is not None:
            if until():
                return
        elif queue.active_count() == 0:
            qapp.processEvents()
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for the transfer queue")


def _write(path, size, seed=0):
    data = hashlib.sha256(str(seed).encode()).digest() * (size // 32 + 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data[:size])
    return data[:size]


# ── file system ──────────────────────────────────────────────────────────────

def test_sftp_fs_basic_operations(fs, remote_root):
    fs.makedirs("/a/b/c")
    assert (remote_root / "a" / "b" / "c").is_dir()
    fs.create_empty("/a/empty.txt")
    names = [e.name for e in fs.listdir("/a")]
    assert names == ["b", "empty.txt"]                 # folders first
    fs.rename("/a/empty.txt", "/a/renamed.txt")
    assert fs.stat("/a/empty.txt") is None
    assert fs.stat("/a/renamed.txt").size == 0
    fs.set_mtime("/a/renamed.txt", 1_600_000_000)
    assert int(fs.stat("/a/renamed.txt").mtime) == 1_600_000_000
    fs.rmtree("/a")
    assert not (remote_root / "a").exists()


def test_rename_refuses_to_overwrite(fs):
    fs.create_empty("/x")
    fs.create_empty("/y")
    with pytest.raises(Exception):
        fs.rename("/x", "/y")


# ── transfers ────────────────────────────────────────────────────────────────

def test_upload_tree_then_download_it_back(fs, qapp, tmp_path, remote_root):
    src = tmp_path / "src" / "project"
    files = {
        "readme.md": _write(src / "readme.md", 1234, 1),
        "sub/data.bin": _write(src / "sub" / "data.bin", 300_000, 2),
        "sub/deeper/x.txt": _write(src / "sub" / "deeper" / "x.txt", 10, 3),
    }
    (src / "emptydir").mkdir()
    os.utime(src / "readme.md", (1_500_000_000, 1_500_000_000))

    q = _queue(fs)
    q.upload([str(src)], "/")
    _wait(q, qapp)
    assert all(j.state == DONE for j in q.jobs.values())
    for rel, data in files.items():
        assert (remote_root / "project" / rel).read_bytes() == data
    assert (remote_root / "project" / "emptydir").is_dir()
    assert int((remote_root / "project" / "readme.md").stat().st_mtime) == 1_500_000_000

    dest = tmp_path / "back"
    dest.mkdir()
    q.download([fs.stat("/project")], str(dest))
    _wait(q, qapp)
    for rel, data in files.items():
        assert (dest / "project" / rel).read_bytes() == data
    assert int((dest / "project" / "readme.md").stat().st_mtime) == 1_500_000_000
    assert len(q.log) == 6


def test_conflict_asked_once_with_apply_to_all(fs, qapp, tmp_path, remote_root):
    for name in ("a.txt", "b.txt", "c.txt"):
        _write(tmp_path / "up" / name, 50, name)
        (remote_root / name).write_bytes(b"old")
    asked = []

    def resolver(info):
        asked.append(info.source.name)
        return KEEP_BOTH, True

    q = _queue(fs, resolver)
    q.upload([str(tmp_path / "up" / n) for n in ("a.txt", "b.txt", "c.txt")], "/")
    _wait(q, qapp)
    assert len(asked) == 1
    for name in ("a", "b", "c"):
        assert (remote_root / f"{name}.txt").read_bytes() == b"old"
        assert (remote_root / f"{name}_1.txt").stat().st_size == 50


def test_skip_policy_leaves_target_alone(fs, qapp, tmp_path, remote_root):
    _write(tmp_path / "s.txt", 50)
    (remote_root / "s.txt").write_bytes(b"keep")
    q = _queue(fs, conflict_policy="skip")
    q.upload([str(tmp_path / "s.txt")], "/")
    _wait(q, qapp)
    assert list(q.jobs.values())[0].state == SKIPPED
    assert (remote_root / "s.txt").read_bytes() == b"keep"


def test_pause_and_resume_continue_from_offset(fs, qapp, tmp_path, remote_root):
    data = _write(tmp_path / "big.bin", 600_000, 7)
    offsets = []
    original = fs.upload

    def recording_upload(local, remote, offset, on_data, limited=False):
        offsets.append(offset)
        return original(local, remote, offset, on_data, limited)

    fs.upload = recording_upload
    q = _queue(fs, limit_up_kib=100)
    q.upload([str(tmp_path / "big.bin")], "/")
    _wait(q, qapp, until=lambda: any(j.done > 150_000 for j in q.jobs.values()))
    job = next(iter(q.jobs.values()))
    q.pause([job.id])
    _wait(q, qapp, until=lambda: job.state == PAUSED)
    partial = (remote_root / "big.bin").stat().st_size
    assert 0 < partial < len(data)

    q.settings.limit_up_kib = 0
    q.apply_settings()
    q.resume([job.id])
    _wait(q, qapp)
    assert job.state == DONE
    assert offsets[0] == 0 and offsets[1] == partial
    assert (remote_root / "big.bin").read_bytes() == data


def test_transfer_survives_connection_drop(fs, server, qapp, tmp_path, remote_root):
    data = _write(tmp_path / "net.bin", 700_000, 9)
    q = _queue(fs, limit_up_kib=150)
    q.upload([str(tmp_path / "net.bin")], "/")
    _wait(q, qapp, until=lambda: any(j.done > 100_000 for j in q.jobs.values()))
    server.drop_connections()
    q.settings.limit_up_kib = 0
    q.apply_settings()
    _wait(q, qapp, timeout=60)
    job = next(iter(q.jobs.values()))
    assert job.state == DONE, job.error
    assert "retry" in job.note
    assert (remote_root / "net.bin").read_bytes() == data


def test_cancel_removes_the_partial_file_it_created(fs, qapp, tmp_path, remote_root):
    _write(tmp_path / "c.bin", 500_000, 4)
    q = _queue(fs, limit_up_kib=50)
    q.upload([str(tmp_path / "c.bin")], "/")
    _wait(q, qapp, until=lambda: any(j.done > 60_000 for j in q.jobs.values()))
    q.cancel_all()
    _wait(q, qapp)
    assert next(iter(q.jobs.values())).state == CANCELLED
    assert not (remote_root / "c.bin").exists()


def test_rate_limit_is_respected(fs, qapp, tmp_path):
    _write(tmp_path / "r.bin", 300 * 1024, 5)
    q = _queue(fs, limit_up_kib=100)
    started = time.time()
    q.upload([str(tmp_path / "r.bin")], "/")
    _wait(q, qapp)
    # 300 KiB at 100 KiB/s with a one-second burst allowance: at least ~2 s.
    assert time.time() - started >= 1.8


def test_upload_from_url_streams_through_pc(fs, qapp, tmp_path, remote_root):
    web = tmp_path / "web"
    data = _write(web / "file.bin", 250_000, 11)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(web))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        q = _queue(fs)
        q.upload_url(f"http://127.0.0.1:{httpd.server_port}/file.bin", "/web.bin", via_server=False)
        _wait(q, qapp)
    finally:
        httpd.shutdown()
    job = next(iter(q.jobs.values()))
    assert job.state == DONE, job.error
    assert job.size == len(data)
    assert (remote_root / "web.bin").read_bytes() == data


def test_sync_upload_with_mirror(fs, qapp, tmp_path, remote_root):
    local = tmp_path / "site"
    _write(local / "index.html", 100, 1)
    _write(local / "css" / "a.css", 200, 2)
    (remote_root / "site").mkdir()
    (remote_root / "site" / "stale.txt").write_bytes(b"x")

    def snapshot(filesystem, root):
        side = SyncSide()
        for dirpath, dirs, files in filesystem.walk(root):
            for f in files:
                rel = os.path.relpath(f.path, root).replace("\\", "/") if filesystem.is_local \
                    else f.path[len(root):].lstrip("/")
                side.files[rel] = f
        return side

    lfs = LocalFS()
    items = compare_trees(snapshot(lfs, str(local)), snapshot(fs, "/site"), SYNC_UPLOAD,
                          delete_extra=True)
    q = _queue(fs)
    q.sync(items, str(local), "/site")
    _wait(q, qapp)
    assert (remote_root / "site" / "css" / "a.css").stat().st_size == 200
    assert (remote_root / "site" / "index.html").stat().st_size == 100
    assert not (remote_root / "site" / "stale.txt").exists()


# ── shell commands, executed for real ────────────────────────────────────────

def _bash_path(p) -> str:
    drive, rest = os.path.splitdrive(str(p))
    return "/" + drive[0].lower() + rest.replace("\\", "/")


@pytest.mark.skipif(not os.path.exists(GIT_BASH), reason="Git Bash not installed")
def test_linux_commands_run_in_bash(tmp_path):
    work = tmp_path / "w"
    _write(work / "my dir" / "a.txt", 100, 1)
    _write(work / "-dash.txt", 10, 2)

    def bash(cmd):
        return subprocess.run([GIT_BASH, "-c", cmd], capture_output=True, text=True)

    r = bash(commands.pack_command(False, _bash_path(work), ["my dir", "-dash.txt"],
                                   "out.tar.gz", "tar.gz"))
    assert r.returncode == 0, r.stderr
    dest = tmp_path / "x"
    dest.mkdir()
    r = bash(commands.extract_command(False, _bash_path(work / "out.tar.gz"), _bash_path(dest)))
    assert r.returncode == 0, r.stderr
    assert (dest / "my dir" / "a.txt").stat().st_size == 100
    assert (dest / "-dash.txt").exists()

    r = bash(commands.checksum_command(False, _bash_path(work / "my dir" / "a.txt")))
    expected = hashlib.sha256((work / "my dir" / "a.txt").read_bytes()).hexdigest()
    assert commands.parse_checksum(r.stdout) == expected


def _sftp_style(p) -> str:
    return "/" + str(p).replace("\\", "/")


@pytest.mark.skipif(os.name != "nt", reason="PowerShell commands need Windows")
def test_windows_commands_run_in_powershell(tmp_path):
    work = tmp_path / "w"
    _write(work / "it's here" / "a.txt", 100, 1)

    def ps(cmd):
        return subprocess.run(cmd, capture_output=True, text=True, shell=True)

    r = ps(commands.pack_command(True, _sftp_style(work), ["it's here"], "out.zip", "zip"))
    assert r.returncode == 0, r.stderr
    dest = tmp_path / "x"
    r = ps(commands.extract_command(True, _sftp_style(work / "out.zip"), _sftp_style(dest)))
    assert r.returncode == 0, r.stderr
    assert (dest / "it's here" / "a.txt").stat().st_size == 100

    r = ps(commands.checksum_command(True, _sftp_style(work / "it's here" / "a.txt")))
    expected = hashlib.sha256((work / "it's here" / "a.txt").read_bytes()).hexdigest()
    assert commands.parse_checksum(r.stdout) == expected

    r = ps(commands.duplicate_command(True, _sftp_style(work / "it's here"),
                                      _sftp_style(work / "copy")))
    assert r.returncode == 0, r.stderr
    assert (work / "copy" / "a.txt").exists()

    # tar.gz through Windows' own System32\tar.exe (never a GNU tar from PATH).
    if os.path.exists(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")):
        r = ps(commands.pack_command(True, _sftp_style(work), ["it's here"], "o.tar.gz", "tar.gz"))
        assert r.returncode == 0, r.stderr
        dest2 = tmp_path / "y"
        dest2.mkdir()
        r = ps(commands.extract_command(True, _sftp_style(work / "o.tar.gz"), _sftp_style(dest2)))
        assert r.returncode == 0, r.stderr
        assert (dest2 / "it's here" / "a.txt").stat().st_size == 100
