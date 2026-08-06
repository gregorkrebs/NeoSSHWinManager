"""
updater.py – Update check, installer download and deferred installation.

Update strategy (since 1.5.4):
    Only the Windows *installer* (Setup exe from the GitHub release) is
    downloaded, never the portable exe. Swapping the running exe in place was
    unreliable — the file is locked while the app runs, and an installed copy
    usually lives in a directory the user may not write to, so the swap failed
    silently and the old version started again.

    Instead the installer is stored in %APPDATA%\\SSHWinManager\\updates together
    with a small marker file (pending_update.json). If the user arms the update,
    the *next* program start hands over to a helper script that waits for this
    process to exit, runs the installer, and starts the app again afterwards —
    no matter whether the installer completed or was cancelled.
"""

import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from packaging import version
from PyQt6.QtCore import QObject, pyqtSignal

from src.app_logger import logger

GITHUB_API_URL = "https://api.github.com/repos/gregorkrebs/neosshwinmanager/releases/latest"

# Characters that would break out of a quoted path inside the generated .cmd
# helper (or let it run something else entirely).
_UNSAFE_PATH_CHARS = '"%&|<>^\r\n'

_MARKER_NAME = "pending_update.json"
_ATTEMPT_NAME = "update_attempt.json"


# ── Pending-update bookkeeping ──────────────────────────────────────────────

def updates_dir() -> Path:
    """Directory holding a downloaded installer and its marker file."""
    appdata = os.environ.get("APPDATA", str(Path.home()))
    return Path(appdata) / "SSHWinManager" / "updates"


def _marker_path() -> Path:
    return updates_dir() / _MARKER_NAME


def read_pending_update() -> dict | None:
    """
    Raw pending-update record, or None if there is none / the installer file
    is gone. Does not compare versions — see get_pending_update().
    """
    try:
        with open(_marker_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    installer = data.get("installer_path", "")
    if not installer or not os.path.isfile(installer):
        return None
    return data


def get_pending_update(current_version: str) -> dict | None:
    """
    Pending update that is actually newer than the running version.
    A record for a version we are already running is stale (the update went
    through) and gets cleaned up.
    """
    data = read_pending_update()
    if not data:
        return None
    try:
        if version.parse(str(data.get("version", "0"))) <= version.parse(str(current_version)):
            logger.info("Pending update is not newer than the running version — cleaning up.")
            clear_pending_update()
            return None
    except Exception:
        return None
    return data


def save_pending_update(version_str: str, installer_path: str, asset_name: str,
                        changelog: str = "", install_on_next_start: bool = True) -> None:
    """Remember a downloaded installer so later starts/checks can find it."""
    record = {
        "version": version_str,
        "installer_path": str(installer_path),
        "asset_name": asset_name,
        # Kept so the dialog can show release notes without asking GitHub again.
        "changelog": changelog,
        "install_on_next_start": bool(install_on_next_start),
    }
    try:
        updates_dir().mkdir(parents=True, exist_ok=True)
        with open(_marker_path(), "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to write pending-update marker: {e}")


def set_install_on_next_start(enabled: bool) -> bool:
    """Arm/disarm the installer for the next program start. Returns success."""
    data = read_pending_update()
    if not data:
        return False
    data["install_on_next_start"] = bool(enabled)
    try:
        with open(_marker_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Update install-on-next-start set to {bool(enabled)}.")
        return True
    except Exception as e:
        logger.error(f"Failed to update pending-update marker: {e}")
        return False


def clear_pending_update() -> None:
    """Drop the marker and any downloaded installer."""
    data = read_pending_update()
    if data:
        try:
            os.remove(data["installer_path"])
        except Exception:
            pass
    try:
        os.remove(_marker_path())
    except Exception:
        pass


# ── Did the update actually happen? ─────────────────────────────────────────

def _attempt_path() -> Path:
    return updates_dir() / _ATTEMPT_NAME


def record_update_attempt(from_version: str, to_version: str) -> None:
    """
    Remember that we handed over to the installer.

    Whether the update really went through can only be told on the next start:
    if the app now runs the new version, it worked. The installer reports
    nothing back, and the pending-update record is gone by then — the helper
    script deletes the installer once it finished.
    """
    record = {
        "from_version": str(from_version),
        "to_version": str(to_version),
        "started_at": int(time.time()),
    }
    try:
        updates_dir().mkdir(parents=True, exist_ok=True)
        with open(_attempt_path(), "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to write update-attempt marker: {e}")


def take_update_attempt() -> dict | None:
    """
    Read the attempt record and drop it — it is evaluated exactly once.

    A stale record (older than a week) is discarded without a verdict: the
    machine may have been off in between, and a late "installed" would land in
    the wrong day's statistics.
    """
    try:
        with open(_attempt_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    finally:
        try:
            os.remove(_attempt_path())
        except Exception:
            pass

    if not isinstance(data, dict) or not data.get("to_version"):
        return None
    if time.time() - int(data.get("started_at", 0)) > 7 * 86400:
        logger.info("Discarding stale update-attempt marker.")
        return None
    return data


# ── Handover to the installer ───────────────────────────────────────────────

def _is_safe_script_path(path: str) -> bool:
    """Path can be embedded in a quoted .cmd argument without escaping tricks."""
    return bool(path) and not any(c in path for c in _UNSAFE_PATH_CHARS)


def launch_pending_installer(record: dict, from_version: str = "") -> bool:
    """
    Start a detached helper script that waits for this process to exit, runs
    the installer, and relaunches the app afterwards (also when the installer
    was cancelled). The caller must quit right after this returns True.

    `from_version` is only used for the statistics marker — pass the running
    version so the next start can tell whether the update took effect.
    """
    installer = str(record.get("installer_path", ""))
    if not installer or not os.path.isfile(installer):
        logger.warning("launch_pending_installer: installer file is missing.")
        return False

    if not getattr(sys, "frozen", False):
        logger.info("Not running as a frozen exe — skipping installer handover.")
        return False

    app_exe = sys.executable
    exe_name = os.path.basename(app_exe)
    script_path = str(updates_dir() / "run_update.cmd")

    for p in (installer, app_exe, script_path):
        if not _is_safe_script_path(p):
            logger.error(f"Updater: refusing to build helper script for unsafe path: {p}")
            return False

    # Wait for the app to be gone before touching its files: with a PyInstaller
    # onefile build the bootloader parent outlives the Python child briefly and
    # keeps the exe locked, so we wait on the image name, not on a PID.
    # After the installer returns we start the app again — on success the
    # installer's own "launch app" step may already have done so, which is
    # harmless: the single-instance mutex turns the second start into a no-op.
    script = f"""@echo off
setlocal disabledelayedexpansion
set /a _tries=0

:waitloop
tasklist /fi "imagename eq {exe_name}" /nh 2>nul | find /i "{exe_name}" >nul
if errorlevel 1 goto runsetup
set /a _tries+=1
if %_tries% GEQ 60 goto runsetup
timeout /t 1 /nobreak >nul
goto waitloop

:runsetup
start "" /wait "{installer}"
rem Exit code 0 means the installer finished; only then is it safe to discard.
if not errorlevel 1 del /f /q "{installer}" >nul 2>&1
start "" "{app_exe}"
del /f /q "%~f0" >nul 2>&1
"""

    try:
        updates_dir().mkdir(parents=True, exist_ok=True)
        with open(script_path, "w", encoding="ascii") as f:
            f.write(script)
    except Exception as e:
        logger.error(f"Failed to write update helper script: {e}")
        return False

    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        subprocess.Popen(
            ["cmd.exe", "/c", script_path],
            startupinfo=startupinfo,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except Exception as e:
        logger.error(f"Failed to start update helper script: {e}")
        return False

    record_update_attempt(from_version, str(record.get("version", "")))
    logger.info(f"Update handover scheduled: {installer}")
    return True


def maybe_install_pending_update(current_version: str) -> bool:
    """
    Startup hook. Returns True if the installer was handed over and the caller
    must exit immediately (the helper restarts the app afterwards).

    Call this as early as possible — after the single-instance check, before
    the database and the main window are touched.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False

    try:
        record = get_pending_update(current_version)
    except Exception as e:
        logger.warning(f"Pending update check failed: {e}")
        return False

    if not record or not record.get("install_on_next_start"):
        return False

    # Disarm *before* handing over: if the installer crashes or the user keeps
    # cancelling, the app must not get stuck in an install loop. The record
    # itself stays, so the user can re-arm it from the update dialog.
    set_install_on_next_start(False)

    return launch_pending_installer(record, from_version=current_version)


# ── Update check / download ─────────────────────────────────────────────────

class UpdaterManager(QObject):
    # version, changelog, download_url, obj_type ("installer" | "browser")
    update_available = pyqtSignal(str, str, str, str)
    no_update_available = pyqtSignal()
    check_failed = pyqtSignal(str)
    download_progress = pyqtSignal(int)
    download_finished = pyqtSignal(bool, str)  # success, path or error message

    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version
        self.update_file_path = None
        self.latest_version = ""
        self._asset_name = ""
        self._changelog = ""
        self._checksum_url = ""
        self._is_downloading = False

    def pending_update(self) -> dict | None:
        """Already downloaded installer for a newer version, if any."""
        return get_pending_update(self.current_version)

    def check_for_updates_async(self):
        """Checks in the background whether a new version is available."""
        def _worker():
            try:
                req = urllib.request.Request(GITHUB_API_URL, headers={"User-Agent": "NeoSSHWinManager-Updater"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode())

                latest_version_tag = data.get("tag_name", "").lstrip("v")
                if not latest_version_tag:
                    self.check_failed.emit("GitHub API returned no tag_name")
                    return

                # Compare versions using packaging.version for proper semantic versioning
                if version.parse(latest_version_tag) > version.parse(self.current_version):
                    changelog = data.get("body", "No changelog available.")
                    download_url = ""
                    asset_name = ""
                    checksum_url = ""
                    obj_type = "browser"

                    # Only the installer is a valid auto-update target; the
                    # portable exe cannot replace an installed copy.
                    for asset in data.get("assets", []):
                        name = asset.get("name", "")
                        low = name.lower()
                        if low.endswith(".exe") and "setup" in low and not download_url:
                            download_url = asset.get("browser_download_url", "")
                            asset_name = name
                            obj_type = "installer"
                        if name in ("sha256sums.txt", "checksums.txt", "SHA256SUMS"):
                            checksum_url = asset.get("browser_download_url", "")

                    if not download_url:
                        # No installer in this release — send the user to the release page.
                        download_url = data.get("html_url", "")
                        obj_type = "browser"
                        logger.warning("Release has no Setup asset — falling back to browser download.")

                    self.latest_version = latest_version_tag
                    self._asset_name = asset_name
                    self._changelog = changelog
                    self._checksum_url = checksum_url
                    self.update_available.emit(latest_version_tag, changelog, download_url, obj_type)
                else:
                    self.no_update_available.emit()

            except Exception as e:
                logger.warning(f"Failed to check for updates: {e}")
                try:
                    self.check_failed.emit(str(e))
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def download_update_async(self, download_url: str):
        if self._is_downloading:
            return
        self._is_downloading = True

        def _worker():
            try:
                target_dir = updates_dir()
                target_dir.mkdir(parents=True, exist_ok=True)

                # A previously downloaded installer of another version is dead weight.
                clear_pending_update()

                file_name = self._asset_name or "NeoSSHWinManager-Setup.exe"
                self.update_file_path = str(target_dir / file_name)

                req = urllib.request.Request(download_url, headers={"User-Agent": "NeoSSHWinManager-Updater"})
                with urllib.request.urlopen(req, timeout=15) as response:
                    total_size = int(response.headers.get('Content-Length', 0))
                    downloaded = 0
                    chunk_size = 8192

                    with open(self.update_file_path, "wb") as f:
                        while True:
                            buffer = response.read(chunk_size)
                            if not buffer:
                                break
                            f.write(buffer)
                            downloaded += len(buffer)
                            if total_size > 0:
                                percent = int((downloaded / total_size) * 100)
                                self.download_progress.emit(percent)

                self._verify_checksum()

                save_pending_update(
                    self.latest_version,
                    self.update_file_path,
                    file_name,
                    changelog=self._changelog,
                    install_on_next_start=True,
                )
                self.download_finished.emit(True, self.update_file_path)
            except Exception as e:
                logger.error(f"Download failed: {e}")
                try:
                    if self.update_file_path and os.path.exists(self.update_file_path):
                        os.remove(self.update_file_path)
                except Exception:
                    pass
                self.update_file_path = None
                self.download_finished.emit(False, str(e))
            finally:
                self._is_downloading = False

        threading.Thread(target=_worker, daemon=True).start()

    def _verify_checksum(self):
        """
        SECURITY: verify the SHA-256 of the download if the release ships a
        checksum file. A mismatch raises and discards the file; a missing or
        unreadable checksum file only warns.
        """
        checksum_url = self._checksum_url
        if not checksum_url:
            logger.warning("No checksum file found in release assets — integrity not verified.")
            return

        try:
            cs_req = urllib.request.Request(checksum_url, headers={"User-Agent": "NeoSSHWinManager-Updater"})
            with urllib.request.urlopen(cs_req, timeout=10) as cs_resp:
                checksums_text = cs_resp.read().decode('utf-8', errors='replace')

            sha256 = hashlib.sha256()
            with open(self.update_file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b''):
                    sha256.update(chunk)
            actual_hex = sha256.hexdigest()

            # Format: "<hash>  <filename>"
            file_name = os.path.basename(self.update_file_path)
            expected_hex = None
            for line in checksums_text.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1].lstrip('*') == file_name:
                    expected_hex = parts[0].lower()
                    break

            if expected_hex is None:
                logger.warning("Checksum file found but no matching entry for the installer — skipping verification")
            elif not hmac.compare_digest(actual_hex, expected_hex):
                os.remove(self.update_file_path)
                self.update_file_path = None
                raise ValueError(f"SHA-256 mismatch: expected {expected_hex}, got {actual_hex}")
            else:
                logger.info("Update integrity verified via SHA-256.")
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"Checksum verification failed (non-fatal): {e}")
