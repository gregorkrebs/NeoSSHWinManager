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
from ctypes import wintypes
from dataclasses import dataclass
from src.config import Connection
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


def _is_host_known(host: str, port: int, known_hosts_path: str) -> bool:
    """
    Checks if a host is already verified in known_hosts.
    Uses ssh-keygen -F for correct handling of hashed entries.
    Fallback: direct text search for non-hashed entries.
    """
    if not os.path.exists(known_hosts_path):
        return False

    # Primär: ssh-keygen -F (also handles hashed known_hosts correctly)
    ssh_keygen = shutil.which("ssh-keygen") or r"C:\Windows\System32\OpenSSH\ssh-keygen.exe"
    if os.path.exists(ssh_keygen if os.path.isabs(ssh_keygen) else "") or shutil.which("ssh-keygen"):
        try:
            target = f"[{host}]:{port}" if port != 22 else host
            result = subprocess.run(
                [ssh_keygen, "-F", target, "-f", known_hosts_path],
                capture_output=True, timeout=5,
                creationflags=0x08000000,
            )
            return result.returncode == 0
        except Exception:
            pass

    # Fallback: direct text search (only works for non-hashed entries)
    try:
        target_plain = host
        target_port = f"[{host}]:{port}" if port != 22 else None
        with open(known_hosts_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                hosts_field = parts[0]
                for h in hosts_field.split(','):
                    if h == target_plain or (target_port and h == target_port):
                        return True
    except Exception:
        pass

    return False


def _ssh_host_key_check_option() -> str:
    """
    Use OpenSSH's TOFU mode so the first verified connection can populate known_hosts.

    Existing host-key mismatches still fail, but brand-new hosts no longer need a
    separate manual OpenSSH pre-registration step.
    """
    return "StrictHostKeyChecking=accept-new"


def _has_winfsp() -> bool:
    return any(os.path.isdir(p) for p in WINFSP_DLL_PATHS)


def _drive_letter_in_use(drive_letter: str) -> bool:
    letter = drive_letter.strip("\\").upper()
    if not letter.endswith(":"):
        letter += ":"
    idx = ord(letter[0]) - ord('A')
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    return bool(bitmask & (1 << idx))


def _find_sshfs_pid_for_drive(drive_letter: str) -> int | None:
    """
    Findet die PID des sshfs.exe-Prozesses der diesen Laufwerksbuchstaben mounted.
    Sucht in der CommandLine nach dem Buchstaben (z.B. 'F:').
    """
    # SECURITY FIX: Validate drive letter to prevent command injection
    letter = drive_letter.rstrip("\\").rstrip(":").upper()
    if not letter or len(letter) != 1 or not letter.isalpha():
        return None
    letter = letter[0]  # Ensure single character

    target_arg = f"{letter}:"

    try:
        # Fallback: Use native Windows tasklist if psutil is not available
        # We search for sshfs.exe and filter manually by CommandLine to find the one with the target drive letter.
        output = subprocess.check_output(
            ['wmic', 'process', 'where', "name='sshfs.exe'", 'get', 'CommandLine,ProcessId', '/format:csv'],
            creationflags=0x08000000,
            text=True
        )
        for line in output.splitlines():
            if target_arg in line:
                # WMIC CSV Format: Node,CommandLine,ProcessId
                parts = line.strip().split(',')
                if len(parts) >= 3:
                    return int(parts[-1])
    except Exception:
        # Last attempt using tasklist (less details, but better than nothing)
        try:
            task_out = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq sshfs.exe', '/FO', 'CSV'],
                                              creationflags=0x08000000, text=True)
            # Here we unfortunately cannot check the CommandLine, only if it is running. This is a fallback and may lead to false positives if multiple sshfs.exe are running.
            pass
        except Exception:
            pass

    return None


class SSHFSController:

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

    def mount(self, conn: Connection, disable_cache: bool = False) -> MountResult:
        """Nur sshfs.exe direkt – erzeugt ein lokales WinFsp-Laufwerk."""
        result = self._mount_direct(conn, disable_cache=disable_cache)
        if result.success:
            self._set_drive_label(conn)
        return result

    def _mount_direct(self, conn: Connection, disable_cache: bool = False) -> MountResult:
        from src.app_logger import logger

        sshfs_exe = _find_sshfs_exe()
        if not sshfs_exe:
            return MountResult(False, "sshfs.exe nicht gefunden. Bitte SSHFS-Win installieren.")

        letter = conn.drive_letter.rstrip("\\").rstrip(":")

        logger.info(f"=== SSHFS Mount Debug ===")
        logger.info(f"Connection name: {conn.name}")
        logger.info(f"Host: {conn.host}:{conn.port}")
        logger.info(f"User: {conn.user}")
        logger.info(f"Auth method: {conn.auth_method}")
        logger.info(f"Remote path: {conn.remote_path or '/'}")
        logger.info(f"Drive letter: {letter}:")
        logger.info(f"SSHFS exe: {sshfs_exe}")

        # SECURITY FIX: Validate remote_path to prevent path traversal on server
        if not _is_safe_remote_path(conn.remote_path or '/'):
            return MountResult(False, f"Ungültiger remote_path: {conn.remote_path}")

        remote = f"{conn.user}@{conn.host}:{conn.remote_path or '/'}"
        sshfs_bin_dir = os.path.dirname(sshfs_exe)

        # volname setzt den Label direkt in WinFsp – kein Registry-Trick nötig
        # SECURITY FIX: Validate label to prevent command injection
        if not _is_safe_label(conn.name):
            return MountResult(False, f"Ungültiger Label-Name: {conn.name}")
        safe_name = conn.name[:32].replace("=", "_").replace(",", "_")

        # SECURITY FIX: Use absolute path for known_hosts instead of %USERPROFILE%
        # SSHFS cannot expand %USERPROFILE% correctly
        known_hosts_path = os.path.expanduser("~\\.ssh\\known_hosts")

        cmd = [
            sshfs_exe,
            remote,
            f"{letter}:",
            f"-p{conn.port}",
            f"-ovolname={safe_name}",
            "-odebug",
            "-ologlevel=debug1",
            f"-o{_ssh_host_key_check_option()}",
            f"-oUserKnownHostsFile={known_hosts_path}",
            "-oreconnect",
            "-oServerAliveInterval=15",
            "-oServerAliveCountMax=3",
            "-oidmap=user",
            "-ouid=-1",
            "-ogid=-1",
            "-oumask=000",
            "-ocreate_umask=000",
            "-odefault_permissions",
        ]

        # NOTE: attr_timeout/entry_timeout/negative_timeout are libfuse/SFTP-side cache
        # knobs — they never reach Explorer. Explorer only ever sees the WinFsp kernel
        # driver's own cache, which is controlled by the separate FileInfoTimeout/
        # DirInfoTimeout/VolumeInfoTimeout options and defaults to sshfs-win's built-in
        # FileInfoTimeout=1000 when unset. Always set these explicitly so the checkbox
        # actually has an effect.
        cmd += [
            "-oFileInfoTimeout=-1",
            "-oVolumeInfoTimeout=1000",
        ]

        if disable_cache:
            cmd += [
                "-oDirInfoTimeout=0",
                "-oattr_timeout=1",
                "-oentry_timeout=1",
                "-onegative_timeout=0",
            ]
        else:
            cmd += ["-oDirInfoTimeout=1000"]

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

        try:
            logger.debug(f"SSHFS command: {' '.join(cmd)}")
            logger.info(f"SSHFS bin dir: {sshfs_bin_dir}")

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                creationflags=0x08000000,
            )

            logger.info(f"SSHFS process started with PID: {proc.pid}")

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
                        # SECURITY FIX: Wipe password from memory immediately after use
                        password_secure.wipe()
                except Exception as e:
                    logger.error(f"stdin Fehler: {e}")
                    return MountResult(False, f"stdin Fehler: {e}")

            import threading
            debug_lines = []
            done = threading.Event()

            def _read_stderr():
                try:
                    for raw in proc.stderr:
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        logger.info(f"SSHFS stderr: {line}")
                        debug_lines.append(line)
                        if "service sshfs has been started" in line:
                            logger.info("SSHFS service started successfully")
                            done.set()
                            return
                        for err in ["Permission denied", "Connection refused",
                                    "Connection reset", "No route to host",
                                    "mount point in use", "no such identity",
                                    "bad port", "read: ", "Unable to authenticate",
                                    "Host key verification failed",
                                    "REMOTE HOST IDENTIFICATION HAS CHANGED"]:
                            if err in line:
                                logger.error(f"SSHFS error detected: {err}")
                                done.set()
                                return
                except Exception as e:
                    logger.error(f"Error reading stderr: {e}")
                    done.set()

            threading.Thread(target=_read_stderr, daemon=True).start()
            logger.info("Waiting for SSHFS to complete mount...")
            done.wait(timeout=30)
            logger.info(f"SSHFS mount wait completed. Done event: {done.is_set()}")

            full = "\n".join(debug_lines)
            full_lower = full.lower()

            logger.info(f"SSHFS process poll status: {proc.poll()}")
            logger.info(f"SSHFS stderr output length: {len(full)}")
            logger.info(f"SSHFS stderr output: {full[:500]}")

            if proc.poll() is None:
                logger.info("SSHFS process still running, checking drive letter...")
                time.sleep(0.5)
                if _drive_letter_in_use(f"{letter}:"):
                    logger.info(f"Drive {letter}: is in use after 0.5s")
                    return MountResult(True, f"Laufwerk {letter}: eingebunden (sshfs.exe)")
                time.sleep(2.0)
                if _drive_letter_in_use(f"{letter}:"):
                    logger.info(f"Drive {letter}: is in use after 2.0s")
                    return MountResult(True, f"Laufwerk {letter}: eingebunden (sshfs.exe)")
                logger.error(f"Drive {letter}: is NOT in use after waiting")

            if "no such identity" in full_lower:
                logger.error(f"SSH key not found: {conn.key_path}")
                return MountResult(False, f"Private Key (IdentityFile) wurde nicht gefunden:\n{conn.key_path}")
            if "mount point in use" in full_lower:
                logger.error(f"Mount point {letter}: already in use")
                return MountResult(False, f"Laufwerksbuchstabe {letter}: ist bereits belegt (oder wird gerade getrennt).")
            if "permission denied" in full_lower or "unable to authenticate" in full_lower:
                logger.error("SSHFS authentication failed")
                return MountResult(False, "Authentifizierung fehlgeschlagen.\nBitte Passwort oder SSH-Key überprüfen.")
            if "connection refused" in full_lower:
                logger.error(f"SSHFS connection refused to {conn.host}:{conn.port}")
                return MountResult(False, f"Verbindung abgelehnt ({conn.host}:{conn.port}).\nIst der SSH-Dienst auf dem Zielgerät aktiv?")
            if "connection reset" in full_lower or "read: " in full_lower:
                logger.error(f"SSHFS connection reset to {conn.host}:{conn.port}")
                return MountResult(False,
                    f"Die Verbindung wurde unterbrochen oder zurückgesetzt ({conn.host}:{conn.port}).\n"
                    f"Mögliches Netzwerkproblem oder Firewall-Blockade.")

            logger.error(f"SSHFS unknown error. Full output: {full}")
            return MountResult(False, full[-300:] or "Ein unbekannter Fehler in sshfs.exe ist aufgetreten.")

        except Exception as e:
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
        import threading

        letter = conn.drive_letter.rstrip("\\").rstrip(":")
        name = conn.name

        def _apply():
            if delay > 0:
                time.sleep(delay)

            from src.app_logger import logger

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
                path_w = f"{letter}:\\".encode("utf-16le")
                ctypes.windll.shell32.SHChangeNotify(0x00000100, 0x0005, path_w, None)
                ctypes.windll.shell32.SHChangeNotify(0x00008000, 0x0000, None, None)
            except Exception:
                pass

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
        letter = drive_letter.rstrip("\\")
        if not letter.endswith(":"):
            letter += ":"
        letter_up = letter.upper()
        drive_char = letter_up[0]

        try:
            from src.app_logger import logger
        except Exception:
            logger = None

        def log(msg):
            if logger:
                logger.debug(f"Unmount {letter_up}: {msg}")

        def verify(after_sec=0.5) -> bool:
            time.sleep(after_sec)
            return not _drive_letter_in_use(letter_up)

        log("Start unmount")

        # Read UNC before unmount (for net use mounts)
        unc_before = self._get_actual_unc(letter_up)
        is_network_mount = unc_before is not None
        log(f"Mount type: {'net use' if is_network_mount else 'WinFsp direct'} | UNC={unc_before!r}")

        def cleanup():
            self._cleanup_drive_label(letter_up, known_unc=unc_before)

        # ── Strategy A: Direct WinFsp Mount ──────────────────────────
        if not is_network_mount:
            # Step 1: Find and terminate sshfs.exe process for this drive letter
            pid = _find_sshfs_pid_for_drive(drive_char)
            log(f"sshfs PID for {drive_char}: = {pid!r}")

            if pid:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True, timeout=5,
                        creationflags=0x08000000,
                    )
                    log(f"PID {pid} terminated.")
                except Exception as e:
                    log(f"taskkill PID error: {e}")

                if verify(1.5):
                    cleanup()
                    return MountResult(True, f"Drive {letter_up} disconnected.")
            else:
                log("No sshfs process found for this drive letter.")

            # Step 2: WinFsp launchctl as fallback
            for winfsp_bin in [
                r"C:\Program Files\WinFsp\bin\launchctl.exe",
                r"C:\Program Files (x86)\WinFsp\bin\launchctl.exe",
            ]:
                if os.path.exists(winfsp_bin):
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

        return not _drive_letter_in_use(letter_up)

    # ------------------------------------------------------------------
    # Label Cleanup
    # ------------------------------------------------------------------

    def _cleanup_drive_label(self, drive_letter: str, known_unc: str | None = None):
        import winreg
        try:
            letter = drive_letter.rstrip("\\").rstrip(":")

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
                0x00000080, 0x0005, f"{letter}:\\".encode("utf-16le"), None
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

            subprocess.run(["net", "use", "*", "/delete", "/y"],
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

    def get_mounted_drives(self) -> dict:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        return {
            f"{ch}:": ""
            for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            if bitmask & (1 << i)
        }
