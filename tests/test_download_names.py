"""
Names from the server must never leave the local target folder.

A POSIX file name may contain "\\" and ":", so a hostile or compromised server
can list "..\\..\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\
Startup\\x.bat" or "C:\\x". Up to 1.7.2 such names were joined into the local
path unchecked, which on Windows writes outside the chosen folder.
"""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.filebrowser.fs import SftpFS  # noqa: E402
from src.filebrowser.model import (  # noqa: E402
    UnsafeNameError, is_safe_local_name, local_child, local_relative,
)
from src.filebrowser.settings import MemoryStore, SettingsManager  # noqa: E402
from src.filebrowser.transfers import TransferQueue  # noqa: E402
from tests.sftp_test_server import SftpTestServer  # noqa: E402

EVIL = "..\\..\\evil.bat"


@pytest.mark.parametrize("name", [
    "..", ".", "...", " . ", EVIL, "C:\\x", "C:x", "a/b", "a\\b", "x\x00", "x\ny", "file:stream",
])
def test_unsafe_names(name):
    assert not is_safe_local_name(name)
    with pytest.raises(UnsafeNameError):
        local_child("target", name)


@pytest.mark.parametrize("name", ["a.txt", ".bashrc", "my file", "ünïcödé", "a..b", "-dash"])
def test_plain_names(name):
    assert is_safe_local_name(name)
    assert local_child("target", name) == os.path.join("target", name)


def test_relative_paths_check_every_component():
    assert local_relative("t", "a/b/c") == os.path.join("t", "a", "b", "c")
    with pytest.raises(UnsafeNameError):
        local_relative("t", "a/../b")
    with pytest.raises(UnsafeNameError):
        local_relative("t", "a/" + EVIL)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_download_skips_names_that_would_escape(qapp, tmp_path):
    remote = tmp_path / "remote"
    (remote / "dir" / "sub").mkdir(parents=True)
    (remote / "dir" / "good.txt").write_text("good")
    (remote / "dir" / EVIL).write_text("evil")
    (remote / "dir" / "sub" / "C:evil").write_text("evil")
    (remote / EVIL).write_text("evil")
    local = tmp_path / "local"
    local.mkdir()

    with SftpTestServer(str(remote)) as server:
        fs = SftpFS(server.connect(), reconnect=server.connect)
        try:
            queue = TransferQueue(fs, SettingsManager(MemoryStore({})), lambda info: ("overwrite", False))
            messages = []
            queue.message.connect(messages.append)
            entries = {e.name: e for e in fs.listdir("/")}
            queue.download([entries["dir"], entries[EVIL]], str(local))
            end = time.time() + 20
            while time.time() < end and (queue.active_count() or not messages):
                qapp.processEvents()
                time.sleep(0.01)
        finally:
            fs.close()

    written = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())
    assert os.path.join("local", "dir", "good.txt") in written
    assert not any("evil" in w and not w.startswith("remote") for w in written)
    assert messages and "3" in messages[0]
