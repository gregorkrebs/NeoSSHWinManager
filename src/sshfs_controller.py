# sshfs_controller.py - Mount/unmount SSH drives using sshfs-win.
#
# Direkter WinFsp-Mount (kein Netzlaufwerk!):
#   - sshfs.exe mountet via WinFsp als lokales FUSE-Laufwerk
#   - WNetGetConnection() gibt None zurück (kein Netzlaufwerk)
#   - WNetCancelConnection2() schlägt fehl (Fehler 2250 = not connected)
#   - Unmount: sshfs.exe-Prozess für diesen Buchstaben finden und beenden
#   - Label: -ovolname=NAME setzt den Namen direkt via WinFsp

import subprocess
import os
import sys
import shutil
import time
import ctypes
import threading
import psutil
from ctypes import wintypes
from dataclasses import dataclass
from src.config import Connection
from src.remote_os import detect_remote_os
from src.remote_path import looks_like_windows_path, normalize_remote_input
from src.ssh_args import is_safe_cli_value
from src.ui.host_key_utils import confirm_host_key, default_known_hosts
from src.utils.secure_memory import SecureBytes

SSHFS_EXE_PATHS = [
    r"C:\Program Files\SSHFS-Win\bin\sshfs.exe",
    r"C:\Program Files (x86)\SSHFS-Win\bin\sshfs.exe",
]
WINFSP_DLL_PATHS = [
    r"C:\Program Files\WinFsp",
    r"C:\Program Files (x86)\WinFsp",
]


@dataclass
class MountResult:
    success: bool
    message: str
    # Machine-readable reason for a failure the UI handles itself:
    # "drive_in_use" = the drive letter is already taken.
    code: str = ""


def _find_sshfs_exe() -> str | None:
    for p in SSHFS_EXE_PATHS:
        if os.path.exists(p):
            return p
    return shutil.which("sshfs")


def _is_safe_label(label: str) -> bool:
    """
    Validate label to prevent command injection.
    """
    if not label or not isinstance(label, str):
        return False
    # SECURITY FIX: Only allow alphanumeric, spaces, hyphens, underscores, dots
    # Reject all shell metacharacters and dangerous characters
    allowed = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_.')
    dangerous = set(';|&`$(){}[]<>!*\\"\'\n\r\t')
    if any(c in dangerous for c in label):
        return False
    return all(c in allowed for c in label)


def _is_safe_remote_path(path: str) -> bool:
    """
    Validate that a remote path doesn't contain path traversal sequences.
    Prevents server-side path traversal attacks.
    """
    if not path or not isinstance(path, str):
        return True  # Empty path is OK (defaults to /)

    # SECURITY FIX: Normalize path and check for traversal
    try:
        normalized = os.path.normpath(path)
    except Exception:
        return False

    # Check for path traversal
    if '..' in normalized or normalized.startswith('/..'):
        return False

    # Reject shell metacharacters
    dangerous = set(';|&`$(){}[]<>!\\"\'\n\r\t')
    if any(c in dangerous for c in path):
        return False

    return True


def _ssh_host_key_check_option() -> str:
    """
    sshfs only talks to hosts whose key is in known_hosts. _mount_direct()
    checks the key first and asks the user about an unknown one, so nothing
    is ever trusted silently.
    """
    return "StrictHostKeyChecking=yes"


def _redact_remote(cmd: list[str], remote: str) -> str:
    """The sshfs command line for the log, without user, host and path."""
    return " ".join("<remote>" if a == remote else a for a in cmd)


def _sshfs_network_connections() -> list[str]:
    """
    'net use' connections that belong to SSHFS-Win (\\\\sshfs…), by local
    name (drive letter) or, for connections without one, by remote name.
    """
    import win32netcon
    import win32wnet
    names = []
    handle = win32wnet.WNetOpenEnum(win32netcon.RESOURCE_CONNECTED,
                                    win32netcon.RESOURCETYPE_DISK, 0, None)
    try:
        while True:
            items = win32wnet.WNetEnumResource(handle, 64)
            if not items:
                break
            for res in items:
                remote = res.lpRemoteName or ""
                if remote.lower().startswith("\\\\sshfs"):
                    names.append(res.lpLocalName or remote)
    finally:
        win32wnet.WNetCloseEnum(handle)
    return names


def _has_winfsp() -> bool:
    return any(os.path.isdir(p) for p in WINFSP_DLL_PATHS)


def _drive_letter_in_use(drive_letter: str) -> bool:
    letter = drive_letter.strip("\\").upper()
    if not letter.endswith(":"):
        letter += ":"
    idx = ord(letter[0]) - ord('A')
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    return bool(bitmask & (1 << idx))


def _drive_root_definitely_absent(drive_letter: str) -> bool:
    """Return True only when Windows reports the definitive no-root state."""
    letter = drive_letter.rstrip("\\/").rstrip(":").upper()
    if len(letter) != 1 or letter not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        return False
    try:
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(
            ctypes.c_wchar_p(f"{letter}:\\")
        )
    except (AttributeError, OSError):
        return False
    return drive_type == 1  # DRIVE_NO_ROOT_DIR


def _find_sshfs_pid_for_drive(drive_letter: str) -> int | None:
    """
    Findet die PID des sshfs.exe-Prozesses der diesen Laufwerksbuchstaben mounted.
    Sucht in der CommandLine nach dem Buchstaben (z.B. 'F:').
    """
    # SECURITY FIX: Validate drive letter to prevent command injection.
    letter = drive_letter.rstrip("\\/").rstrip(":").upper()
    if len(letter) != 1 or letter not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        return None
    target_arg = f"{letter}:"

    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if (proc.info.get("name") or "").lower() != "sshfs.exe":
                    continue

                # The mount point is a standalone argv item (for example X:).
                # Exact matching avoids selecting a different mount merely because
                # an option or remote path contains the same drive-letter prefix.
                for arg in proc.info.get("cmdline") or ():
                    normalized = str(arg).strip().strip('"').rstrip("\\/").upper()
                    if normalized == target_arg:
                        return int(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except (psutil.Error, OSError):
        # Process enumeration is best-effort. The caller can still try WinFsp's
        # launchctl and verify whether the drive disappeared.
        pass

    return None


class SSHFSController:

    def __init__(self):
        self._process_lock = threading.RLock()
        self._mount_processes: dict[str, subprocess.Popen] = {}
        self._label_generations: dict[str, object] = {}

    @staticmethod
    def _drive_char(drive_letter: str) -> str | None:
        letter = drive_letter.rstrip("\\/").rstrip(":").upper()
        if len(letter) == 1 and letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            return letter
        return None

    def _remember_mount_process(self, drive_letter: str, proc: subprocess.Popen):
        letter = self._drive_char(drive_letter)
        if letter:
            with self._process_lock:
                self._mount_processes[letter] = proc

    def _forget_mount_process(self, drive_letter: str, expected=None):
        letter = self._drive_char(drive_letter)
        if not letter:
            return
        with self._process_lock:
            current = self._mount_processes.get(letter)
            if expected is None or current is expected:
                self._mount_processes.pop(letter, None)

    def _get_mount_process(self, drive_letter: str):
        letter = self._drive_char(drive_letter)
        if not letter:
            return None
        with self._process_lock:
            proc = self._mount_processes.get(letter)
            if proc is not None and proc.poll() is not None:
                self._mount_processes.pop(letter, None)
                return None
            return proc

    def _stop_mount_process(self, drive_letter: str, proc: subprocess.Popen):
        """Best-effort cleanup for a mount process that did not become usable."""
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
        self._forget_mount_process(drive_letter, expected=proc)

    @staticmethod
    def check_sshfs_win_installed() -> bool:
        return _find_sshfs_exe() is not None

    @staticmethod
    def get_install_status() -> dict:
        sshfs_exe = _find_sshfs_exe()
        return {
            "winfsp": _has_winfsp(),
            "sshfs_win": sshfs_exe is not None,
            "sshfs_exe": sshfs_exe,
        }

    # ------------------------------------------------------------------
    # Mount
    # ------------------------------------------------------------------

    def mount(self, conn: Connection, disable_cache: bool = False,
              safe_writes: bool = True) -> MountResult:
        """Nur sshfs.exe direkt – erzeugt ein lokales WinFsp-Laufwerk."""
        result = self._mount_direct(conn, disable_cache=disable_cache,
                                    safe_writes=safe_writes)
        if result.success:
            self._set_drive_label(conn)
        return result

    def _mount_direct(self, conn: Connection, disable_cache: bool = False,
                      safe_writes: bool = True) -> MountResult:
        from src.app_logger import logger

        sshfs_exe = _find_sshfs_exe()
        if not sshfs_exe:
            return MountResult(False, "sshfs.exe nicht gefunden. Bitte SSHFS-Win installieren.")

        letter = self._drive_char(conn.drive_letter)
        if letter is None:
            return MountResult(False, f"Ungültiger Laufwerksbuchstabe: {conn.drive_letter!r}")
        if _drive_letter_in_use(f"{letter}:"):
            return MountResult(False, f"Laufwerksbuchstabe {letter}: ist bereits belegt.", "drive_in_use")

        # Host, user and path are stored encrypted; keep them out of the log.
        logger.info(f"SSHFS mount: connection {conn.id}, auth {conn.auth_method}, drive {letter}:")
        logger.debug(f"SSHFS exe: {sshfs_exe}")

        # sshfs reads an argument starting with "-" as an option
        # ("-oProxyCommand=…" would run a local program).
        if not (is_safe_cli_value(conn.host) and is_safe_cli_value(conn.user)):
            return MountResult(False, "Ungültiger Hostname oder Benutzername.")

        # Windows OpenSSH exposes drives as /C:/… — convert a Windows-style
        # remote path (C:\Users\foo, W:\data, /C:/Users) into the forward-slash
        # form sshfs/SFTP needs, so subpaths (not just "/") can be mounted.
        remote_path = (conn.remote_path or '/').strip() or '/'
        if looks_like_windows_path(remote_path):
            remote_path = normalize_remote_input(remote_path, True)
        elif remote_path == '/' and detect_remote_os(conn.host, conn.port) == "windows":
            # At "/" Windows OpenSSH lists the drive letters ("C:", "E:"), and
            # ":" is illegal in Windows file names, so Explorer would show them
            # as "C" etc. Mount the user's home instead: an empty remote path
            # is relative to the SFTP server's default directory.
            remote_path = ''

        # SECURITY FIX: Validate remote_path to prevent path traversal on server
        if not _is_safe_remote_path(remote_path):
            return MountResult(False, f"Ungültiger remote_path: {conn.remote_path}")

        remote = f"{conn.user}@{conn.host}:{remote_path}"
        sshfs_bin_dir = os.path.dirname(sshfs_exe)

        # volname setzt den Label direkt in WinFsp – kein Registry-Trick nötig
        # SECURITY FIX: Validate label to prevent command injection
        if not _is_safe_label(conn.name):
            return MountResult(False, f"Ungültiger Label-Name: {conn.name}")
        safe_name = conn.name[:32].replace("=", "_").replace(",", "_")

        # Absolute path: sshfs cannot expand %USERPROFILE%.
        known_hosts_path = default_known_hosts()
        # sshfs runs with StrictHostKeyChecking=yes: make sure the key is
        # known, asking the user (on the main thread) about an unknown one.
        from src.sftp_client import HostKeyChanged, HostKeyRejected, SftpClientError
        try:
            confirm_host_key(conn.host, conn.port, known_hosts=known_hosts_path)
        except HostKeyChanged as e:
            from src.i18n import tr
            return MountResult(False, tr("fb.hostkey.changed", host=e.host,
                                         fingerprint=e.fingerprint, path=e.known_hosts))
        except HostKeyRejected as e:
            from src.i18n import tr
            return MountResult(False, tr("fb.hostkey.rejected", host=e.host,
                                         fingerprint=e.fingerprint))
        except SftpClientError as e:
            return MountResult(False, f"Verbindung zu {conn.host}:{conn.port} fehlgeschlagen: {e}")

        cmd = [
            sshfs_exe,
            remote,
            f"{letter}:",
            f"-p{conn.port}",
            f"-ovolname={safe_name}",
            "-f",
            f"-o{_ssh_host_key_check_option()}",
            f"-oUserKnownHostsFile={known_hosts_path}",
            "-oreconnect",
            "-oServerAliveInterval=15",
            "-oServerAliveCountMax=3",
            "-oidmap=user",
            "-ouid=-1",
            "-ogid=-1",
            # umask only shapes the modes shown to Windows (the server still
            # enforces its own permissions). create_umask applies to files and
            # folders created through the drive: 000 made them writable for
            # every account on the server.
            "-oumask=000",
            "-ocreate_umask=022",
            "-odefault_permissions",
        ]

        # NOTE: attr_timeout/entry_timeout/negative_timeout are libfuse/SFTP-side cache
        # knobs — they never reach Explorer. Explorer only ever sees the WinFsp kernel
        # driver's own cache, which is controlled by the separate FileInfoTimeout/
        # DirInfoTimeout/VolumeInfoTimeout options and defaults to sshfs-win's built-in
        # FileInfoTimeout=1000 when unset. Always set these explicitly so the checkbox
        # actually has an effect.
        #
        # WICHTIG (NUL-Byte-Korruption): -oFileInfoTimeout=-1 war die Ursache für
        # Dateien, die nach dem Schreiben nur noch aus Nullbytes bestanden. Die
        # sshfs.exe-Hilfe sagt zu dieser Option wörtlich: "metadata timeout (millis,
        # -1 for data caching)" – d.h. genau der Wert -1 aktiviert das WinFsp-
        # DATEN-Caching, jeder endliche Wert lässt nur (begrenztes) Metadaten-Caching zu.
        #
        # Ablauf des Fehlers: Beim Anlegen/Überschreiben setzt sshfs die Remote-
        # Dateigröße zuerst auf die Endgröße – SFTP füllt diesen Bereich mit Nullen. Die
        # echten Bytes liegen zunächst nur im flüchtigen Write-Back-Datencache. Mit -1
        # hält WinFsp diesen (Null-)Datenzustand dauerhaft für gültig und liefert beim
        # (verzögerten) Zurücklesen die Null-Füllung aus; ein hartes taskkill /F von
        # sshfs.exe beim Unmount verwirft noch nicht geschriebene Cache-Seiten zusätzlich.
        #
        # safe_writes (Default an) stellt das ab – nur von diesem sshfs-win-Build
        # dokumentierte Optionen:
        #   FileInfoTimeout=1000 : endlich statt -1 → Daten-Caching AUS.
        #   -osshfs_sync         : synchrone SFTP-Writes → vor dem ACK am Server,
        #                          taskkill /F kann nichts mehr verlieren.
        #   -ono_readahead       : synchrone Reads → keine spekulativen Null-Seiten.
        if safe_writes:
            cmd += [
                "-oFileInfoTimeout=1000",
                "-oVolumeInfoTimeout=1000",
                "-osshfs_sync",
                "-ono_readahead",
            ]
        else:
            cmd += [
                "-oFileInfoTimeout=-1",
                "-oVolumeInfoTimeout=1000",
            ]

        # WICHTIG (neue Ordner/Dateien erst nach manuellem Explorer-Refresh sichtbar):
        # DirInfoTimeout/attr_timeout/entry_timeout betreffen nur den WinFsp-Kernel-
        # Cache. sshfs.exe führt darunter ein zweites, komplett unabhängiges
        # Verzeichnis-Cache (dir_cache/dcache_*, sshfs --help), das bisher nie gesetzt
        # wurde und mit seinem Default dcache_dir_timeout=20s lief – 20x länger als der
        # WinFsp-Cache oben. dcache_dir_timeout steuert laut --help konkret die Namen
        # (d.h. ob ein frisch angelegter Ordner/Datei überhaupt in der Liste auftaucht),
        # unabhängig vom Refresh-Button: der fragt zwar WinFsp neu ab, aber sshfs
        # antwortet innerhalb der 20s weiterhin aus seinem eigenen Namens-Cache.
        if disable_cache:
            cmd += [
                "-oDirInfoTimeout=0",
                "-oattr_timeout=1",
                "-oentry_timeout=1",
                "-onegative_timeout=0",
                "-odir_cache=no",
            ]
        else:
            cmd += [
                "-oDirInfoTimeout=1000",
                "-odcache_dir_timeout=1",
            ]

        if conn.auth_method == "key" and conn.key_path:
            key_path = conn.key_path.replace("\\", "/")
            # SECURITY FIX (FINDING-07): Validate key_path for path traversal.
            # Prevents an attacker-controlled key_path value from escaping the
            # intended directory via ".." sequences.
            normalized = os.path.normpath(key_path)
            if '..' in normalized:
                return MountResult(False, "Ungültiger Key-Pfad: Path-Traversal erkannt")

            # Validate key file exists and is readable
            if not os.path.exists(key_path):
                return MountResult(False, f"SSH-Key nicht gefunden: {key_path}")

            # OpenSSH keys are valid input for current SSHFS-Win/OpenSSH builds.
            # Keep a lightweight readability check only, but do not block by header type.
            try:
                with open(key_path, 'r', encoding='utf-8') as f:
                    first_line = f.readline().strip()
                    if first_line.startswith("-----BEGIN OPENSSH PRIVATE KEY-----"):
                        logger.info(f"Using OpenSSH private key format: {key_path}")
            except Exception as e:
                logger.error(f"Error reading key file: {e}")
                return MountResult(False, f"Fehler beim Lesen des SSH-Keys: {e}")

            cmd.append(f"-oIdentityFile={key_path}")
            cmd.append("-oBatchMode=yes")
            cmd.append("-oPreferredAuthentications=publickey")
            logger.info(f"Using SSH key: {key_path}")
        elif conn.auth_method in ("password", "ask") and conn.password:
            cmd.append("-oPreferredAuthentications=password,keyboard-interactive")
            cmd.append("-opassword_stdin")
            logger.info("Using password authentication")
        else:
            return MountResult(False, "Kein Passwort oder Key konfiguriert.")

        env = os.environ.copy()
        env["PATH"] = f"{sshfs_bin_dir};{env.get('PATH', '')}"

        proc = None
        try:
            logger.debug(f"SSHFS command: {_redact_remote(cmd, remote)}")
            logger.info(f"SSHFS bin dir: {sshfs_bin_dir}")

            # Preparing a key or connection can take long enough for another
            # device to claim the letter, so check again immediately before Popen.
            if _drive_letter_in_use(f"{letter}:"):
                return MountResult(False, f"Laufwerksbuchstabe {letter}: ist bereits belegt.", "drive_in_use")

            proc = subprocess.Popen(
                cmd,
                stdin=(
                    subprocess.PIPE
                    if conn.auth_method in ("password", "ask") and conn.password
                    else subprocess.DEVNULL
                ),
                stdout=subprocess.DEVNULL,
                # "Quit only" deliberately keeps mounts alive after the GUI exits.
                # A PIPE would then lose its reader and can block/terminate sshfs.
                stderr=subprocess.DEVNULL,
                env=env,
                creationflags=0x08000000,
            )

            logger.info(f"SSHFS process started with PID: {proc.pid}")
            self._remember_mount_process(letter, proc)

            if conn.auth_method in ("password", "ask") and conn.password:
                try:
                    # SECURITY FIX: Use SecureBytes for password handling
                    from src.utils.secure_memory import SecureBytes
                    password_secure = SecureBytes.from_string(conn.password)
                    # SECURITY FIX: Remove password length from logging to prevent information leakage
                    logger.debug("Sende Passwort an sshfs stdin...")
                    try:
                        proc.stdin.write((password_secure.decode() + "\n").encode("utf-8"))
                        proc.stdin.flush()
                        logger.info("Password sent to stdin successfully")
                    finally:
                        if proc.stdin is not None:
                            proc.stdin.close()
                        # SECURITY FIX: Wipe password from memory immediately after use
                        password_secure.wipe()
                except Exception as e:
                    logger.error(f"stdin Fehler: {e}")
                    self._stop_mount_process(letter, proc)
                    return MountResult(False, f"stdin Fehler: {e}")

            def _wait_for_exit():
                try:
                    proc.wait()
                except Exception as e:
                    logger.debug(f"Error waiting for SSHFS process: {e}")
                finally:
                    # Compare-and-remove prevents an old process from deleting a
                    # newer remount that happens to reuse the same drive letter.
                    self._forget_mount_process(letter, expected=proc)

            threading.Thread(target=_wait_for_exit, daemon=True).start()
            logger.info("Waiting for SSHFS drive to become ready...")
            deadline = time.monotonic() + 30.0
            stable_polls = 0
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                if _drive_letter_in_use(f"{letter}:"):
                    stable_polls += 1
                    # It was free before Popen and must now remain present while
                    # this foreground sshfs process is alive for three polls.
                    if stable_polls >= 3:
                        logger.info(
                            f"Drive {letter}: mounted and SSHFS process is running"
                        )
                        return MountResult(
                            True,
                            f"Laufwerk {letter}: eingebunden (sshfs.exe)",
                        )
                else:
                    stable_polls = 0
                time.sleep(0.1)

            returncode = proc.poll()
            logger.error(
                f"Drive {letter}: did not become ready; sshfs returncode={returncode}"
            )
            self._stop_mount_process(letter, proc)
            if returncode is not None:
                return MountResult(
                    False,
                    f"sshfs.exe wurde vor dem Einbinden beendet (Code {returncode}).\n"
                    "Bitte Zugangsdaten, SSH-Key und Server-Verbindung prüfen.",
                )
            return MountResult(
                False,
                f"Zeitüberschreitung beim Einbinden von Laufwerk {letter}:.",
            )

        except Exception as e:
            if proc is not None:
                self._stop_mount_process(letter, proc)
            logger.exception(f"Unexpected SSHFS mount error for {letter}:")
            return MountResult(False, str(e))

    # ------------------------------------------------------------------
    # Label – für direkte WinFsp-Mounts
    # ------------------------------------------------------------------

    def _set_drive_label(self, conn: Connection, delay: float = 1.5):
        """
        Set the drive label.

        For direct WinFsp mounts:
          - -ovolname= sets it during mount → Backup via label.exe + DriveIcons
          - WNetGetConnection returns None → no MountPoints2 trick needed/possible

        For net use mounts (fallback):
          - WNetGetConnection returns the UNC path → set MountPoints2 key
        """
        import winreg
        letter = self._drive_char(conn.drive_letter)
        if letter is None:
            return
        name = conn.name
        generation = object()
        with self._process_lock:
            self._label_generations[letter] = generation

        def is_current_mount() -> bool:
            with self._process_lock:
                is_current = self._label_generations.get(letter) is generation
            return is_current and _drive_letter_in_use(f"{letter}:")

        def finish_generation():
            with self._process_lock:
                if self._label_generations.get(letter) is generation:
                    self._label_generations.pop(letter, None)

        def _apply():
            if delay > 0:
                time.sleep(delay)

            from src.app_logger import logger

            if not is_current_mount():
                logger.debug(f"Label: skip stale update for {letter}:")
                finish_generation()
                return

            # Check if direct WinFsp mount or net use
            actual_unc = self._get_actual_unc(letter)
            logger.debug(f"Label: WNetGetConnection({letter}:) = {actual_unc!r}")

            # 1. label.exe – works for both mount types
            # SECURITY FIX: Removed shell=True to prevent command injection
            try:
                subprocess.run(
                    ["label", f"{letter}:", name],
                    capture_output=True, timeout=5,
                    creationflags=0x08000000,
                )
                logger.debug(f"label.exe gesetzt: {letter}: = {name!r}")
            except Exception as e:
                logger.debug(f"label.exe Fehler: {e}")

            # Registry DriveIcons – Explorer-Override (höchste Priorität)
            # SECURITY FIX: Validate registry key name to prevent registry traversal/injection
            try:
                if not is_current_mount():
                    finish_generation()
                    return
                di_path = (
                    f"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\DriveIcons\\{letter}"
                )
                # Validate registry key components
                if not _is_safe_label(name):
                    logger.warning(f"Rejected unsafe registry value: {name}")
                else:
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, di_path) as k:
                        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, name)
                    logger.debug(f"Registry DriveIcons gesetzt: {di_path} = {name!r}")
            except Exception as e:
                logger.debug(f"DriveIcons Fehler: {e}")

            # 3. MountPoints2 – only for net use (actual_unc present)
            if actual_unc:
                mp_base = (
                    "Software\\Microsoft\\Windows\\CurrentVersion\\"
                    "Explorer\\MountPoints2"
                )
                try:
                    if not is_current_mount():
                        finish_generation()
                        return
                    reg_key = actual_unc.replace("\\", "#")
                    # SECURITY FIX: Validate registry key and value to prevent registry injection
                    if not _is_safe_label(name):
                        logger.warning(f"Rejected unsafe registry value for MountPoints2: {name}")
                    else:
                        with winreg.CreateKey(
                            winreg.HKEY_CURRENT_USER, f"{mp_base}\\{reg_key}"
                        ) as k:
                            winreg.SetValueEx(k, "_LabelFromReg", 0, winreg.REG_SZ, name)
                        logger.debug(f"MountPoints2 gesetzt: {reg_key} = {name!r}")
                except Exception as e:
                    logger.debug(f"MountPoints2 Fehler: {e}")

            # Notify shell – ONLY for this drive letter
            try:
                if not is_current_mount():
                    finish_generation()
                    return
                path_w = ctypes.c_wchar_p(f"{letter}:\\")
                ctypes.windll.shell32.SHChangeNotify(0x00000100, 0x0005, path_w, None)
                ctypes.windll.shell32.SHChangeNotify(0x00008000, 0x0000, None, None)
            except Exception:
                pass
            finally:
                finish_generation()

        threading.Thread(target=_apply, daemon=True).start()

    @staticmethod
    def _get_actual_unc(drive_letter: str) -> str | None:
        """Liest UNC-Pfad via WNetGetConnection. Gibt None bei direkten WinFsp-Mounts."""
        try:
            letter = drive_letter.rstrip("\\").rstrip(":").upper() + ":"
            buf = ctypes.create_unicode_buffer(1024)
            buf_size = ctypes.c_ulong(1024)
            ret = ctypes.windll.mpr.WNetGetConnectionW(letter, buf, ctypes.byref(buf_size))
            if ret == 0:
                return buf.value
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Unmount – for direct WinFsp mounts (no WNetCancelConnection!)
    # ------------------------------------------------------------------

    def unmount(self, drive_letter: str) -> MountResult:
        drive_char = self._drive_char(drive_letter)
        if drive_char is None:
            return MountResult(False, f"Ungültiger Laufwerksbuchstabe: {drive_letter!r}")
        letter_up = f"{drive_char}:"

        try:
            from src.app_logger import logger
        except Exception:
            logger = None

        def log(msg):
            if logger:
                logger.debug(f"Unmount {letter_up}: {msg}")

        log("Start unmount")

        # Read UNC before unmount (for net use mounts)
        unc_before = self._get_actual_unc(letter_up)
        is_network_mount = unc_before is not None
        log(f"Mount type: {'net use' if is_network_mount else 'WinFsp direct'} | UNC={unc_before!r}")

        def verify(after_sec=0.5) -> bool:
            time.sleep(after_sec)
            if not _drive_letter_in_use(letter_up):
                return True
            return (
                not is_network_mount
                and _find_sshfs_pid_for_drive(drive_char) is None
                and _drive_root_definitely_absent(letter_up)
            )

        def cleanup():
            if tracked_proc is not None:
                self._forget_mount_process(drive_char, expected=tracked_proc)
            self._cleanup_drive_label(letter_up, known_unc=unc_before)

        # Prefer the process handle retained at mount time. Process discovery is
        # only needed after an application restart or for legacy mounts.
        tracked_proc = None if is_network_mount else self._get_mount_process(drive_char)
        direct_pid = (
            tracked_proc.pid
            if tracked_proc is not None
            else (None if is_network_mount else _find_sshfs_pid_for_drive(drive_char))
        )

        # Unmount is intentionally idempotent. WinFsp or the polling timer may
        # remove the drive before this worker starts; that is already success.
        drive_present = _drive_letter_in_use(letter_up)
        if (
            not is_network_mount
            and direct_pid is None
            and (
                not drive_present
                or _drive_root_definitely_absent(letter_up)
            )
        ):
            log("Drive is already disconnected")
            cleanup()
            return MountResult(True, f"Laufwerk {letter_up} war bereits getrennt.")

        # ── Strategy A: Direct WinFsp Mount ──────────────────────────
        if not is_network_mount:
            # Step 1: Find and terminate sshfs.exe process for this drive letter
            pid = direct_pid
            log(f"sshfs PID for {drive_char}: = {pid!r}")

            if pid:
                try:
                    kill_result = subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True, timeout=5,
                        creationflags=0x08000000,
                    )
                    if kill_result.returncode == 0:
                        log(f"PID {pid} terminated.")
                    else:
                        log(f"taskkill PID {pid} returned {kill_result.returncode}")
                except Exception as e:
                    log(f"taskkill PID error: {e}")

                if verify(1.5):
                    cleanup()
                    return MountResult(True, f"Drive {letter_up} disconnected.")
            else:
                log("No sshfs process found for this drive letter.")

            # Step 2: WinFsp launchctl as fallback
            winfsp_bin = next((path for path in [
                r"C:\Program Files\WinFsp\bin\launchctl.exe",
                r"C:\Program Files\WinFsp\bin\launchctl-x64.exe",
                r"C:\Program Files\WinFsp\bin\launchctl-a64.exe",
                r"C:\Program Files\WinFsp\bin\launchctl-x86.exe",
                r"C:\Program Files (x86)\WinFsp\bin\launchctl.exe",
                r"C:\Program Files (x86)\WinFsp\bin\launchctl-x64.exe",
                r"C:\Program Files (x86)\WinFsp\bin\launchctl-a64.exe",
                r"C:\Program Files (x86)\WinFsp\bin\launchctl-x86.exe",
            ] if os.path.exists(path)), None)
            if winfsp_bin:
                for cls in ["sshfs", "sshfs-win"]:
                    try:
                        subprocess.run(
                            [winfsp_bin, "stop", cls, drive_char],
                            capture_output=True, timeout=5,
                            creationflags=0x08000000,
                        )
                    except Exception:
                        pass

            if verify(1.0):
                cleanup()
                return MountResult(True, f"Laufwerk {letter_up} getrennt (launchctl).")

        # ── Strategie B: net use Mount ───────────────────────────────────
        else:
            mpr = ctypes.WinDLL('mpr.dll')
            for dw_flags in (1, 0):
                res = mpr.WNetCancelConnection2W(wintypes.LPCWSTR(letter_up), dw_flags, 1)
                log(f"WNetCancelConnection2W(flags={dw_flags}) = {res}")
                if res == 0 or verify(0.5):
                    cleanup()
                    return MountResult(True, f"Laufwerk {letter_up} getrennt (Windows API).")

            try:
                subprocess.run(
                    ["net", "use", letter_up, "/delete", "/yes"],
                    capture_output=True, timeout=10,
                    creationflags=0x08000000,
                )
            except Exception:
                pass

            if verify(0.5):
                cleanup()
                return MountResult(True, f"Laufwerk {letter_up} getrennt (net use).")

        # ── Eskalation: bis zu 10s lang sshfs-Prozess suchen & hart killen ──
        # Deckt Fälle ab, in denen der Prozess beim ersten Versuch noch nicht
        # auffindbar war (Race Condition) bzw. net-use-Mounts ohne Kill-Fallback.
        log("Escalating to force-kill (up to 10s)")
        if self._force_kill_escalation(drive_char, letter_up, log=log):
            cleanup()
            return MountResult(True, f"Laufwerk {letter_up} getrennt (force-kill).")

        return MountResult(
            False,
            f"Laufwerk {letter_up} konnte nicht getrennt werden.\n\n"
            "Alle Programme schließen die auf das Laufwerk zugreifen "
            "und erneut versuchen – oder Windows neu starten.",
        )

    def _force_kill_escalation(self, drive_char: str, letter_up: str,
                               timeout: float = 10.0, log=None) -> bool:
        """Zuletzt eingesetzte Eskalationsstufe beim Unmount: pollt bis zu
        ``timeout`` Sekunden lang, sucht den sshfs.exe-Prozess für das Laufwerk
        und killt ihn hart (``taskkill /F``). Gibt True zurück, sobald der
        Laufwerksbuchstabe frei ist, sonst nach Ablauf des Timeouts False."""
        def _log(msg):
            if log:
                log(msg)

        deadline = time.time() + timeout
        while time.time() < deadline:
            pid = _find_sshfs_pid_for_drive(drive_char)
            if pid:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True, timeout=5,
                        creationflags=0x08000000,
                    )
                    _log(f"Force-kill PID {pid}")
                except Exception as e:
                    _log(f"Force-kill taskkill error: {e}")
            else:
                _log("No sshfs PID found during escalation")

            time.sleep(1.0)
            if not _drive_letter_in_use(letter_up):
                return True
            if (
                _find_sshfs_pid_for_drive(drive_char) is None
                and _drive_root_definitely_absent(letter_up)
            ):
                return True

        if not _drive_letter_in_use(letter_up):
            return True
        return (
            _find_sshfs_pid_for_drive(drive_char) is None
            and _drive_root_definitely_absent(letter_up)
        )

    # ------------------------------------------------------------------
    # Label Cleanup
    # ------------------------------------------------------------------

    def _cleanup_drive_label(self, drive_letter: str, known_unc: str | None = None):
        import winreg
        try:
            letter = self._drive_char(drive_letter)
            if letter is None:
                return
            with self._process_lock:
                self._label_generations.pop(letter, None)

            # Remove DriveIcons ONLY for this drive letter
            di_path = (
                f"Software\\Microsoft\\Windows\\CurrentVersion\\"
                f"Explorer\\DriveIcons\\{letter}"
            )
            self._delete_reg_key_recursive(winreg.HKEY_CURRENT_USER, di_path)

            # MountPoints2 only if net use (UNC known)
            if known_unc:
                mp_base = (
                    "Software\\Microsoft\\Windows\\CurrentVersion\\"
                    "Explorer\\MountPoints2"
                )
                try:
                    reg_key = known_unc.replace("\\", "#")
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER, mp_base, 0, winreg.KEY_ALL_ACCESS
                    ) as base_key:
                        self._delete_reg_key_recursive(base_key, reg_key)
                except Exception:
                    pass

            # Notify shell ONLY for this drive letter
            ctypes.windll.shell32.SHChangeNotify(
                0x00000080, 0x0005, ctypes.c_wchar_p(f"{letter}:\\"), None
            )
        except Exception:
            pass

    def _delete_reg_key_recursive(self, root, subkey):
        import winreg
        try:
            with winreg.OpenKey(root, subkey, 0, winreg.KEY_ALL_ACCESS) as key:
                while True:
                    try:
                        child = winreg.EnumKey(key, 0)
                        self._delete_reg_key_recursive(key, child)
                    except OSError:
                        break
            winreg.DeleteKey(root, subkey)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def purge_all_stale_mounts(self):
        import winreg
        from src.app_logger import logger
        logger.info("Starte Registry-Purge für SSHFS...")
        try:
            mp_base = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\MountPoints2"
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, mp_base, 0, winreg.KEY_ALL_ACCESS) as base_key:
                    keys_to_delete = []
                    i = 0
                    while True:
                        try:
                            name = winreg.EnumKey(base_key, i)
                            if "sshfs" in name.lower():
                                keys_to_delete.append(name)
                            i += 1
                        except OSError:
                            break
                    for k in keys_to_delete:
                        self._delete_reg_key_recursive(base_key, k)
            except Exception:
                pass

            # Only SSHFS-Win's own connections: "net use * /delete" also
            # dropped every other mapped network drive (SMB shares, ...).
            try:
                stale = _sshfs_network_connections()
            except Exception as e:
                logger.warning(f"Netzwerkverbindungen konnten nicht gelesen werden: {e}")
                stale = []
            for name in stale:
                subprocess.run(["net", "use", name, "/delete", "/y"],
                               capture_output=True, creationflags=0x08000000)
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
            logger.info("Purge abgeschlossen.")
            return True
        except Exception as e:
            logger.error(f"Purge Fehler: {e}")
            return False

    @staticmethod
    def restart_explorer():
        from src.app_logger import logger
        try:
            subprocess.run(["taskkill", "/F", "/IM", "explorer.exe"],
                           capture_output=True, creationflags=0x08000000)
            time.sleep(1)
            subprocess.Popen(["explorer.exe"], creationflags=0x08000000)
            return True
        except Exception as e:
            logger.error(f"Explorer Neustart Fehler: {e}")
            return False

    def is_mounted(self, drive_letter: str) -> bool:
        return _drive_letter_in_use(drive_letter)

    def sshfs_letters(self, letters) -> set:
        """Those of *letters* that hold an SSHFS mount: a direct mount (an
        sshfs.exe with the letter as mount point) or a net-use mount of an
        \\\\sshfs UNC path. Other drives on a letter (USB stick, subst, a
        network share) are not ours."""
        wanted = {self._drive_char(l) for l in letters} - {None}
        if not wanted:
            return set()
        found = set()
        for ch in wanted:
            unc = (self._get_actual_unc(f"{ch}:") or "").lower()
            if unc.startswith("\\\\sshfs"):
                found.add(f"{ch}:")
        rest = wanted - {f[0] for f in found}
        if rest:
            try:
                for proc in psutil.process_iter(["name", "cmdline"]):
                    try:
                        if (proc.info.get("name") or "").lower() != "sshfs.exe":
                            continue
                        for arg in proc.info.get("cmdline") or ():
                            a = str(arg).strip().strip('"').rstrip("\\/").upper()
                            if len(a) == 2 and a[1] == ":" and a[0] in rest:
                                found.add(a)
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue
            except (psutil.Error, OSError):
                pass
        return found

    def get_mounted_drives(self) -> dict:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        return {
            f"{ch}:": ""
            for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            if bitmask & (1 << i)
        }
