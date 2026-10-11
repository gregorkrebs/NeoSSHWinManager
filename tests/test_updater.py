"""Update handover and release notes (src/updater.py)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src import updater

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path


def test_notes_between_lists_every_newer_version_without_details():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = updater.notes_between(changelog, "1.5.5", "1.6.1")
    assert notes.startswith("## Version 1.6.1")
    assert "## Version 1.6.0" in notes
    assert notes.index("## Version 1.6.1") < notes.index("## Version 1.6.0")
    assert "Version 1.5.5" not in notes
    assert "<details>" not in notes and "Technical details" not in notes
    assert "\n---" not in notes


def test_notes_between_only_the_newest_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = updater.notes_between(changelog, "1.6.0", "1.6.1")
    assert notes.startswith("## Version 1.6.1") and "Version 1.6.0" not in notes


@pytest.mark.parametrize("installed", ["1.6.1", "1.7.0", "1.7.1"])
def test_update_to_1_7_2_shows_the_notes_of_1_7_2_1_7_1_and_1_7_0(installed):
    # The headings of 1.7.1 and 1.7.0 have no brackets: their notes are part of
    # the 1.7.2 section, so every update to 1.7.2 shows all three, once each.
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = updater.notes_between(changelog, installed, "1.7.2")
    assert notes.startswith("## Version 1.7.2\n")
    assert notes.index("## Version 1.7.2\n") < notes.index("## Version 1.7.1\n") < notes.index("## Version 1.7.0\n")
    for v in ("1.7.2", "1.7.1", "1.7.0"):
        assert notes.count(f"## Version {v}") == 1
    for item in ("New servers work in the terminal straight away.",
                 "The app starts again on its own after an update.",
                 "Start right away, no account to set up."):
        assert notes.count(item) == 1
    assert "Version 1.6.1" not in notes
    assert "2026-" not in notes
    assert "<details>" not in notes and "Technical details" not in notes


def test_clean_release_notes_drops_the_technical_details():
    body = "### What changes for you\n\n- Fixed.\n\n<details>\n<summary>Technical details</summary>\n\n" \
           "- `x.py` changed.\n\n</details>\n\n---\n"
    assert updater.clean_release_notes(body) == "### What changes for you\n\n- Fixed."


def test_release_body_is_the_fallback(monkeypatch):
    def offline(*_a, **_k):
        raise OSError("offline")
    monkeypatch.setattr(updater.urllib.request, "urlopen", offline)
    body = "- Fixed.\n<details>x</details>"
    assert updater.fetch_release_notes("v9.9.9", "1.0.0", "9.9.9", body) == "- Fixed."


def _frozen(monkeypatch, tmp_path):
    exe = tmp_path / "app" / "NeoSSHWinManager.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    started = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda cmd, **kw: started.append((cmd, kw)))
    # Windows-only constants, so the handover logic can be checked anywhere.
    monkeypatch.setattr(updater.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(updater.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x1000000, raising=False)
    return exe, started


def _installer(name="NeoSSHWinManager-Setup-9.9.9.exe", data=b"installer"):
    """A downloaded installer where the updater keeps it, plus its SHA-256."""
    updater.updates_dir().mkdir(parents=True, exist_ok=True)
    path = updater.updates_dir() / name
    path.write_bytes(data)
    return path, updater.file_sha256(str(path))


def test_handover_starts_the_installer_silently_with_valid_handles(appdata, tmp_path, monkeypatch):
    exe, started = _frozen(monkeypatch, tmp_path)
    installer, sha = _installer()
    legacy = updater.updates_dir() / "run_update.cmd"
    legacy.write_text("@echo off")

    assert updater.launch_pending_installer(
        {"installer_path": str(installer), "version": "9.9.9", "sha256": sha},
        from_version="1.6.1")

    (cmd, kw), = started
    assert cmd[0] == str(installer)
    assert {"/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"} <= set(cmd)
    assert f"/WAITPID={os.getpid()}" in [a.split(",")[0] for a in cmd]
    assert f"/RELAUNCH={exe}" in cmd
    assert "/LOG=" + str(updater.updates_dir() / "install.log") in cmd
    # A windowed app has no standard handles; the child must get valid ones.
    assert kw["stdin"] == kw["stdout"] == kw["stderr"] == subprocess.DEVNULL
    assert not legacy.exists()
    attempt = json.loads((updater.updates_dir() / "update_attempt.json").read_text())
    assert attempt["from_version"] == "1.6.1" and attempt["to_version"] == "9.9.9"


def test_handover_does_not_pass_on_the_pyinstaller_environment(appdata, tmp_path, monkeypatch):
    # Inherited by the relaunched app, these made it look for its Python DLL
    # in this app's deleted temp folder.
    _exe, started = _frozen(monkeypatch, tmp_path)
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", str(_exe))
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", str(tmp_path / "_MEI12345"))
    monkeypatch.setenv("_PYI_PARENT_PROCESS_LEVEL", "1")
    installer, sha = _installer("setup.exe")

    assert updater.launch_pending_installer(
        {"installer_path": str(installer), "version": "9.9.9", "sha256": sha})

    (_cmd, kw), = started
    assert not [k for k in kw["env"] if k.upper().startswith("_PYI_")]
    assert kw["env"]["APPDATA"] == os.environ["APPDATA"]


def test_start_hands_over_once_and_disarms(appdata, tmp_path, monkeypatch):
    _exe, started = _frozen(monkeypatch, tmp_path)
    installer, sha = _installer("setup.exe")
    updater.save_pending_update("9.9.9", str(installer), installer.name, install_on_next_start=True,
                                sha256=sha)

    assert updater.maybe_install_pending_update("1.6.1") is True
    assert len(started) == 1
    # Disarmed before the handover: a failing installer cannot cause a loop.
    assert updater.read_pending_update()["install_on_next_start"] is False
    assert updater.maybe_install_pending_update("1.6.1") is False
    assert len(started) == 1


# ── integrity (the installer is verified before it is kept and before it runs) ──

def test_installer_changed_after_download_is_refused(appdata, tmp_path, monkeypatch):
    _exe, started = _frozen(monkeypatch, tmp_path)
    installer, sha = _installer()
    installer.write_bytes(b"swapped by someone else")
    record = {"installer_path": str(installer), "version": "9.9.9", "sha256": sha}
    updater.save_pending_update("9.9.9", str(installer), installer.name, sha256=sha)
    assert updater.launch_pending_installer(record) is False
    assert started == []
    assert not installer.exists()                       # discarded with its record


def test_installer_without_verified_hash_is_refused(appdata, tmp_path, monkeypatch):
    _exe, started = _frozen(monkeypatch, tmp_path)
    installer, _sha = _installer()
    assert updater.launch_pending_installer({"installer_path": str(installer), "version": "9.9.9"}) is False
    assert started == []


def test_installer_outside_the_updates_folder_is_refused(appdata, tmp_path, monkeypatch):
    _exe, started = _frozen(monkeypatch, tmp_path)
    elsewhere = tmp_path / "elsewhere.exe"
    elsewhere.write_bytes(b"x")
    record = {"installer_path": str(elsewhere), "version": "9.9.9",
              "sha256": updater.file_sha256(str(elsewhere))}
    assert updater.launch_pending_installer(record) is False
    assert started == []


def test_clearing_never_deletes_outside_the_updates_folder(appdata, tmp_path):
    victim = tmp_path / "important.exe"
    victim.write_bytes(b"keep me")
    updater.save_pending_update("9.9.9", str(victim), victim.name)
    updater.clear_pending_update()
    assert victim.exists()


class _Response:
    def __init__(self, data: bytes):
        self._data = data

    def read(self, *_a):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _manager_with_download(tmp_path, checksum_url, checksums: bytes, monkeypatch):
    mgr = updater.UpdaterManager("1.0.0")
    path = tmp_path / "NeoSSHWinManager-Setup-9.9.9.exe"
    path.write_bytes(b"installer")
    mgr.update_file_path = str(path)
    mgr._checksum_url = checksum_url
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *_a, **_k: _Response(checksums))
    return mgr, path


CHECKSUM_URL = "https://github.com/gregorkrebs/NeoSSHWinManager/releases/download/v9.9.9/sha256sums.txt"


def test_checksum_match_returns_the_hash(tmp_path, monkeypatch):
    import hashlib
    digest = hashlib.sha256(b"installer").hexdigest()
    mgr, _ = _manager_with_download(
        tmp_path, CHECKSUM_URL, f"{digest}  NeoSSHWinManager-Setup-9.9.9.exe\n".encode(), monkeypatch)
    assert mgr._verify_checksum() == digest


@pytest.mark.parametrize("url, text", [
    ("", b""),                                                        # no checksum file
    ("https://example.org/sha256sums.txt", b""),                      # not from this project
    (CHECKSUM_URL, b"0" * 64 + b"  other.exe\n"),                     # no entry for the file
    (CHECKSUM_URL, b"0" * 64 + b"  NeoSSHWinManager-Setup-9.9.9.exe\n"),  # mismatch
])
def test_unverifiable_download_is_rejected(tmp_path, monkeypatch, url, text):
    mgr, _ = _manager_with_download(tmp_path, url, text, monkeypatch)
    with pytest.raises(ValueError):
        mgr._verify_checksum()


def test_checksum_download_error_is_not_ignored(tmp_path, monkeypatch):
    mgr, _ = _manager_with_download(tmp_path, CHECKSUM_URL, b"", monkeypatch)

    def offline(*_a, **_k):
        raise OSError("offline")
    monkeypatch.setattr(updater.urllib.request, "urlopen", offline)
    with pytest.raises(OSError):
        mgr._verify_checksum()


@pytest.mark.parametrize("url, ok", [
    ("https://github.com/gregorkrebs/NeoSSHWinManager/releases/download/v1/Setup.exe", True),
    ("http://github.com/gregorkrebs/NeoSSHWinManager/releases/download/v1/Setup.exe", False),
    ("https://evil.example/gregorkrebs/NeoSSHWinManager/releases/download/v1/Setup.exe", False),
    ("https://github.com/someone/else/releases/download/v1/Setup.exe", False),
    ("https://github.com.evil.example/gregorkrebs/NeoSSHWinManager/releases/download/v1/x.exe", False),
])
def test_only_this_projects_release_assets_are_downloaded(url, ok):
    assert updater.is_release_asset_url(url) is ok


@pytest.mark.parametrize("name, ok", [
    ("NeoSSHWinManager-Setup-1.7.3.exe", True),
    ("..\\..\\Startup\\x.exe", False),
    ("../x.exe", False),
    ("C:x.exe", False),
    ("setup.txt", False),
    ("", False),
])
def test_asset_names_are_plain_exe_names(name, ok):
    assert (updater.safe_asset_file_name(name) is not None) is ok
