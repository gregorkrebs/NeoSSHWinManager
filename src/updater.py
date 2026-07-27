import hashlib
import hmac
import os
import re
import sys
import json
import urllib.request
import urllib.error
import threading
import tempfile
import subprocess
from packaging import version
from PyQt6.QtCore import QObject, pyqtSignal
from src.app_logger import logger

# Regex for safe executable paths (A-Z drive, no shell metacharacters)
_SAFE_EXE_PATH_RE = re.compile(r'^[A-Za-z]:\\[\w\\\s.\-]+\.exe$')

GITHUB_API_URL = "https://api.github.com/repos/gregorkrebs/neosshwinmanager/releases/latest"

class UpdaterManager(QObject):
    update_available = pyqtSignal(str, str, str, str)  # version, changelog, download_url, obj_type
    no_update_available = pyqtSignal()
    check_failed = pyqtSignal(str)
    download_progress = pyqtSignal(int)
    download_finished = pyqtSignal(bool, str) # success, msg/path

    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version
        self.update_file_path = None
        self._is_downloading = False

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
                    checksum_url = ""
                    obj_type = "browser"

                    # Search for .exe release asset; also collect sha256sums file if present
                    for asset in data.get("assets", []):
                        name = asset.get("name", "")
                        if name.endswith(".exe") and "cli" not in name.lower() and not download_url:
                            download_url = asset.get("browser_download_url", "")
                            obj_type = "exe"
                        if name in ("sha256sums.txt", "checksums.txt", "SHA256SUMS"):
                            checksum_url = asset.get("browser_download_url", "")

                    if not download_url:
                        # Fallback to the release page if no direct .exe asset is found
                        download_url = data.get("html_url", "")
                        obj_type = "browser"

                    # Attach checksum URL to download URL via a custom separator for later use
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
                temp_dir = tempfile.gettempdir()
                self.update_file_path = os.path.join(temp_dir, "NeoSSHWinManager_update.exe")

                # urllib für den Download mit Progress
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

                # SECURITY: Verify SHA-256 checksum if a checksum file was found in the release
                checksum_url = getattr(self, '_checksum_url', '')
                if checksum_url:
                    try:
                        cs_req = urllib.request.Request(checksum_url, headers={"User-Agent": "NeoSSHWinManager-Updater"})
                        with urllib.request.urlopen(cs_req, timeout=10) as cs_resp:
                            checksums_text = cs_resp.read().decode('utf-8', errors='replace')

                        # Compute actual hash of downloaded file
                        sha256 = hashlib.sha256()
                        with open(self.update_file_path, 'rb') as f:
                            for chunk in iter(lambda: f.read(65536), b''):
                                sha256.update(chunk)
                        actual_hex = sha256.hexdigest()

                        # Find expected hash in checksums file (format: "<hash>  <filename>")
                        exe_name = os.path.basename(self.update_file_path)
                        expected_hex = None
                        for line in checksums_text.splitlines():
                            parts = line.strip().split()
                            if len(parts) >= 2 and parts[1].lstrip('*') in (exe_name, 'NeoSSHWinManager.exe'):
                                expected_hex = parts[0].lower()
                                break

                        if expected_hex is None:
                            logger.warning("Checksum file found but no matching entry for exe — skipping verification")
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
                else:
                    logger.warning("No checksum file found in release assets — integrity not verified.")

                self.download_finished.emit(True, self.update_file_path)
            except Exception as e:
                logger.error(f"Download failed: {e}")
                self.download_finished.emit(False, str(e))
            finally:
                self._is_downloading = False

        threading.Thread(target=_worker, daemon=True).start()

    def install_on_exit(self):
        """Creates a batch file that will be executed when the app closes."""
        if not self.update_file_path or not os.path.exists(self.update_file_path):
            return

        current_exe = sys.executable
        # Only perform the swap if we are actually running as a compiled .exe
        if not getattr(sys, 'frozen', False):
            logger.info("Not running as frozen exe, skipping physical replace.")
            return

        # SECURITY: Validate paths before embedding in bat script to prevent injection
        if not _SAFE_EXE_PATH_RE.match(current_exe):
            logger.error(f"Updater: unsafe current_exe path rejected: {current_exe}")
            return
        if not _SAFE_EXE_PATH_RE.match(self.update_file_path):
            logger.error(f"Updater: unsafe update_file_path rejected: {self.update_file_path}")
            return

        bat_path = os.path.join(tempfile.gettempdir(), "neosshwinmanager_updater.bat")
        exe_name = os.path.basename(current_exe)

        # Batch script that waits for the main process to exit, then replaces the file.
        # After the move, a freshly written .exe is scanned by Windows Defender's
        # real-time protection on first execution; if that scan still holds a lock
        # when the PyInstaller bootloader tries to extract its embedded python DLL,
        # the launch fails with "Failed to load Python DLL". So we wait a bit for
        # the scan to settle, then retry the launch a few times (safe: the app's
        # single-instance mutex makes extra launch attempts no-ops once one succeeds).
        bat_content = f"""@echo off
echo Warte auf das Beenden von NeoSSHWinManager...
timeout /t 3 /nobreak >nul
del "{current_exe}" /f /q
move /y "{self.update_file_path}" "{current_exe}"
timeout /t 2 /nobreak >nul
for /L %%i in (1,1,5) do (
    start "" "{current_exe}"
    timeout /t 2 /nobreak >nul
    tasklist /fi "imagename eq {exe_name}" | find /i "{exe_name}" >nul
    if not errorlevel 1 goto launched
)
:launched
del "%~f0"
"""
        try:
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_content)
        except Exception as e:
            logger.error(f"Failed to write updater.bat: {e}")
            return

        # Start Batch file hidden and detached
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.Popen(["cmd.exe", "/c", bat_path], startupinfo=startupinfo, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        logger.info("Updater batch scheduled for exit.")
