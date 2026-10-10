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


@pytest.mark.parametrize("installed", ["1.6.1", "1.7.0", "1.7.1", "1.7.2"])
def test_update_to_1_7_3_shows_the_notes_of_every_1_7_version(installed):
    # The headings of 1.7.2, 1.7.1 and 1.7.0 have no brackets: their notes are
    # part of the 1.7.3 section, so every update to 1.7.3 shows all four, once each.
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = updater.notes_between(changelog, installed, "1.7.3")
    assert notes.startswith("## Version 1.7.3\n")
    order = [notes.index(f"## Version {v}\n") for v in ("1.7.3", "1.7.2", "1.7.1", "1.7.0")]
    assert order == sorted(order)
    for v in ("1.7.3", "1.7.2", "1.7.1", "1.7.0"):
        assert notes.count(f"## Version {v}") == 1
    for item in ("Import your sites from FileZilla.",
                 "Mounting checks the server's key against your known servers again.",
                 "New servers work in the terminal straight away.",
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
    return exe, started


def test_handover_starts_the_installer_silently_with_valid_handles(appdata, tmp_path, monkeypatch):
    exe, started = _frozen(monkeypatch, tmp_path)
    installer = tmp_path / "NeoSSHWinManager-Setup-9.9.9.exe"
    installer.write_bytes(b"")
    updater.updates_dir().mkdir(parents=True)
    legacy = updater.updates_dir() / "run_update.cmd"
    legacy.write_text("@echo off")

    assert updater.launch_pending_installer({"installer_path": str(installer), "version": "9.9.9"},
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
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"")

    assert updater.launch_pending_installer({"installer_path": str(installer), "version": "9.9.9"})

    (_cmd, kw), = started
    assert not [k for k in kw["env"] if k.upper().startswith("_PYI_")]
    assert kw["env"]["APPDATA"] == os.environ["APPDATA"]


def test_start_hands_over_once_and_disarms(appdata, tmp_path, monkeypatch):
    _exe, started = _frozen(monkeypatch, tmp_path)
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"")
    updater.save_pending_update("9.9.9", str(installer), installer.name, install_on_next_start=True)

    assert updater.maybe_install_pending_update("1.6.1") is True
    assert len(started) == 1
    # Disarmed before the handover: a failing installer cannot cause a loop.
    assert updater.read_pending_update()["install_on_next_start"] is False
    assert updater.maybe_install_pending_update("1.6.1") is False
    assert len(started) == 1
