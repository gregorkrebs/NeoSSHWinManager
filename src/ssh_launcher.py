# ssh_launcher.py – Starts an SSH terminal session.
#
# Supports two backends:
#   1. Windows native ssh.exe (default) – opens cmd.exe with ssh
#      Password auth: SSH_ASKPASS + SSH_ASKPASS_REQUIRE=force mechanism
#      The app itself is called with --pass-helper to print the password.
#   2. PuTTY (optional) – opens putty.exe directly, auto-login with password
#
# PuTTY notes:
#   - Password auth: putty -pw <password> user@host -P <port>
#   - Key auth:      putty -i <keyfile.ppk> user@host -P <port>

import os
import subprocess
import shutil
from src.config import Connection, AppSettings
from src.app_logger import logger
from src.utils.secure_memory import SecureBytes
from src.sshfs_controller import _is_safe_label


def launch_ssh_terminal(conn: Connection, settings: AppSettings) -> tuple[bool, str]:
    """
    Start an SSH terminal for the given connection.
    Returns (success, error_message).
    """
    # Audit Log für Sicherheits-Tracking
    logger.info(f"Auth-Versuch: SSH-Terminal für {conn.name} (Methode: {conn.auth_method})")
    
    if conn.auth_method == "key" and not conn.key_path:
        return False, "Fehler: Passwortloser Login erfordert einen gültigen SSH-Key-Pfad."

    if getattr(settings, 'use_putty', False) and getattr(settings, 'putty_path', ''):
        return _launch_putty(conn, settings.putty_path, settings)
    else:
        return _launch_native_ssh(conn, settings)


# ------------------------------------------------------------------
# Native ssh.exe (default)
# ------------------------------------------------------------------

def _launch_native_ssh(conn: Connection, settings: AppSettings | None = None) -> tuple[bool, str]:
    """
    Open cmd.exe with ssh.

    SECURITY: All inputs are validated to prevent command injection.
    Command arguments are properly escaped using subprocess.list2cmdline.
    Passwort-Auth: SSH_ASKPASS + SSH_ASKPASS_REQUIRE=force
    SSH ruft das askpass-Programm auf statt nach Terminal-Eingabe zu fragen.
    """
    ssh_exe = _find_native_ssh()
    if not ssh_exe:
        return False, "ssh.exe nicht gefunden. Prüfe ob OpenSSH unter Windows installiert ist."

    # SECURITY: Validate host, user and name to prevent command injection
    if not _is_safe_ssh_identifier(conn.host):
        return False, f"Ungültiger Hostname: {conn.host}"
    if not _is_safe_ssh_identifier(conn.user):
        return False, f"Ungültiger Username: {conn.user}"
    if not _is_safe_label(conn.name):
        return False, f"Ungültiger Verbindungsname: {conn.name}"

    # SECURITY FIX: Use absolute path for known_hosts instead of %USERPROFILE%
    known_hosts_path = os.path.expanduser("~\\.ssh\\known_hosts")
    
    ssh_cmd_list = [
        ssh_exe,
        "-o", "StrictHostKeyChecking=accept-new", # First use is trusted, changed hosts still fail
        "-o", f"UserKnownHostsFile={known_hosts_path}",
        "-p", str(conn.port),
    ]

    if conn.auth_method == "key" and conn.key_path:
        # SECURITY FIX: Validate key path
        if not _is_safe_file_path(conn.key_path):
            return False, f"Ungültiger Key-Pfad: {conn.key_path}"
        ssh_cmd_list.extend(["-i", conn.key_path])

    ssh_cmd_list.append(f"{conn.user}@{conn.host}")

    env = os.environ.copy()
    sec_level = getattr(settings, 'security_level', 0) if settings else 0
    if sec_level >= 1 and conn.auth_method == "password" and conn.password:
        import sys as _sys
        import os.path as _osp
        from src.askpass_manager import create_token
        if getattr(_sys, "frozen", False):
            askpass_cmd = f'"{_sys.executable}" --pass-helper'
        else:
            _main_py = _osp.abspath(_osp.join(_osp.dirname(__file__), "..", "main.py"))
            askpass_cmd = f'"{_sys.executable}" "{_main_py}" --pass-helper'
        token = create_token(conn.password)
        env["SSH_ASKPASS_TOKEN"] = token
        env["SSH_ASKPASS"] = askpass_cmd
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env["DISPLAY"] = "dummy:0"

    logger.debug(f"Native SSH cmd: {ssh_cmd_list}")
    try:
        # CWE-78: cmd.exe
        # CREATE_NEW_CONSOLE opens a new window; /k keeps it open after SSH ends.
        # title sets the window title; & is a cmd internal concatenator, not a shell risk,
        # since conn.name is already sanitized by _is_safe_label().
        cmd_str = subprocess.list2cmdline(ssh_cmd_list)
        subprocess.Popen(
            ['cmd.exe', '/k', f'title "{conn.name} SSH" & {cmd_str}'],
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            close_fds=True,
        )
        return True, ""
    except Exception as e:
        return False, str(e)


def launch_ssh_in_current_terminal(conn_data: dict, exec_command: str = None):
    """
    Starts an interactive SSH shell directly in this terminal via Paramiko.
    No extra window, no ssh.exe subprocess, no SSH_ASKPASS issues.
    Used for CLI mode.
    """
    try:
        import paramiko
    except ImportError:
        print("Error: paramiko is not installed. Please run 'pip install paramiko'.")
        return

    import sys
    import msvcrt
    import threading
    import ctypes
    import ctypes.wintypes

    # Windows Console Handles direkt über CONOUT$/CONIN$ öffnen –
    # GetStdHandle liefert bei GUI-EXE nach AttachConsole INVALID_HANDLE_VALUE.
    GENERIC_READ  = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_RW = 0x00000003
    OPEN_EXISTING = 3
    _hOut = ctypes.windll.kernel32.CreateFileW("CONOUT$", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_RW, None, OPEN_EXISTING, 0, None)
    _hErr = _hOut
    _hIn  = ctypes.windll.kernel32.CreateFileW("CONIN$",  GENERIC_READ | GENERIC_WRITE,  FILE_SHARE_RW, None, OPEN_EXISTING, 0, None)

    # ANSI/VT-Sequenzen aktivieren, damit Farben/Escape-Codes vom Remote korrekt
    # gerendert werden (statt als ←[32m sichtbar zu bleiben).
    ENABLE_PROCESSED_OUTPUT            = 0x0001
    ENABLE_WRAP_AT_EOL_OUTPUT          = 0x0002
    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
    ENABLE_PROCESSED_INPUT             = 0x0001
    ENABLE_VIRTUAL_TERMINAL_INPUT      = 0x0200
    _old_out_mode = ctypes.wintypes.DWORD(0)
    _old_in_mode  = ctypes.wintypes.DWORD(0)
    ctypes.windll.kernel32.GetConsoleMode(_hOut, ctypes.byref(_old_out_mode))
    ctypes.windll.kernel32.GetConsoleMode(_hIn,  ctypes.byref(_old_in_mode))
    ctypes.windll.kernel32.SetConsoleMode(
        _hOut,
        _old_out_mode.value | ENABLE_PROCESSED_OUTPUT | ENABLE_WRAP_AT_EOL_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING,
    )
    ctypes.windll.kernel32.SetConsoleMode(
        _hIn,
        (_old_in_mode.value & ~ENABLE_PROCESSED_INPUT) | ENABLE_VIRTUAL_TERMINAL_INPUT,
    )

    def _con_write(handle, data: bytes):
        """Writes bytes directly to a Windows console handle using WriteFile."""
        written = ctypes.wintypes.DWORD(0)
        ctypes.windll.kernel32.WriteFile(
            handle, data, len(data), ctypes.byref(written), None
        )

    def _write_stdout(data: bytes):
        _con_write(_hOut, data)

    def _write_stderr(data: bytes):
        _con_write(_hErr, data)

    host = conn_data.get("host", "")
    port = int(conn_data.get("port", 22))
    user = conn_data.get("user", "")
    auth_method = conn_data.get("auth_method", "password")
    password = conn_data.get("password", "")
    key_path = conn_data.get("key_path", "")

    # SECURITY FIX: Use SecureBytes for password handling
    password_secure = None
    if password:
        password_secure = SecureBytes.from_string(password)

    _write_stdout(f"Verbinde mit {user}@{host}:{port} ...\r\n".encode())

    client = paramiko.SSHClient()
    # SECURITY FIX: Use RejectPolicy instead of AutoAddPolicy to prevent MITM attacks
    # Host keys must be manually verified and added to known_hosts
    client.set_missing_host_key_policy(paramiko.RejectPolicy())

    try:
        if auth_method == "key" and key_path:
            client.connect(host, port=port, username=user, key_filename=key_path, timeout=15)
        else:
            # SECURITY FIX: Use SecureBytes for password
            if password_secure:
                client.connect(host, port=port, username=user, password=password_secure.decode(), timeout=15)
            else:
                client.connect(host, port=port, username=user, password="", timeout=15)
    except Exception as e:
        _write_stderr(f"Fehler: SSH-Verbindung fehlgeschlagen: {e}\r\n".encode())
        return
    finally:
        # SECURITY FIX: Wipe password from memory after connection attempt
        if password_secure:
            password_secure.wipe()

    # ── Non-interaktiver Modus: einzelnen Befehl ausführen und beenden ──
    if exec_command:
        try:
            stdin_, stdout_, stderr_ = client.exec_command(exec_command, timeout=30)
            out = stdout_.read()
            err = stderr_.read()
            if out:
                _write_stdout(out)
            if err:
                _write_stderr(err)
        except Exception as e:
            _write_stderr(f"Fehler beim Ausführen des Befehls: {e}\r\n".encode())
        finally:
            client.close()
        return

    # Interaktive Shell öffnen
    channel = client.invoke_shell(term="xterm-256color", width=220, height=50)
    channel.settimeout(0.0)

    stop_event = threading.Event()

    def write_all(data: bytes):
        while data:
            written = channel.send(data)
            data = data[written:]

    def stdin_to_channel():
        """Reads characters from the Windows console and writes them to the SSH channel."""
        try:
            while not stop_event.is_set() and not channel.closed:
                try:
                    if msvcrt.kbhit():
                        ch = msvcrt.getwch()
                        if ch in ('\x00', '\xe0'):
                            ch2 = msvcrt.getwch()
                            arrow_map = {
                                'H': b'\x1b[A',  # Up
                                'P': b'\x1b[B',  # Down
                                'M': b'\x1b[C',  # Right
                                'K': b'\x1b[D',  # Left
                            }
                            seq = arrow_map.get(ch2)
                            if seq:
                                write_all(seq)
                            else:
                                write_all(('\x00' + ch2).encode('utf-8', errors='replace'))
                        else:
                            write_all(ch.encode('utf-8', errors='replace'))
                    else:
                        import time
                        time.sleep(0.01)
                except Exception:
                    import time
                    time.sleep(0.01)
        except Exception:
            stop_event.set()

    stdin_thread = threading.Thread(target=stdin_to_channel, daemon=True)
    stdin_thread.start()

    try:
        while not channel.closed:
            # Read output from the server and write it directly to stdout
            if channel.recv_ready():
                data = channel.recv(4096)
                if not data:
                    break
                _write_stdout(data)
            elif channel.recv_stderr_ready():
                data = channel.recv_stderr(4096)
                if data:
                    _write_stderr(data)
            elif channel.exit_status_ready():
                # Noch verbleibende Daten lesen
                while channel.recv_ready():
                    data = channel.recv(4096)
                    if data:
                        _write_stdout(data)
                break
            else:
                import time
                time.sleep(0.01)
    except KeyboardInterrupt:
        channel.send(b'\x03')  # Send Ctrl+C to the remote
    finally:
        stop_event.set()
        channel.close()
        client.close()
        # Restore console mode to prevent the calling shell from staying in VT mode.
        try:
            ctypes.windll.kernel32.SetConsoleMode(_hOut, _old_out_mode.value)
            ctypes.windll.kernel32.SetConsoleMode(_hIn,  _old_in_mode.value)
        except Exception:
            pass


def _is_safe_ssh_identifier(value: str) -> bool:
    """
    Validate that a hostname or username doesn't contain shell metacharacters.
    Prevents command injection attacks.
    """
    if not value or not isinstance(value, str):
        return False
    # Allow alphanumeric, dots, dashes, underscores, @ for user@host
    allowed = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_@')
    # Reject common shell metacharacters
    dangerous = set(';|&`$(){}[]<>!\\"\'\n\r\t ')
    if any(c in dangerous for c in value):
        return False
    return all(c in allowed for c in value)


def _is_safe_file_path(path: str) -> bool:
    """Validate that a file path is safe and doesn't contain traversal or shell chars."""
    if not path or not isinstance(path, str):
        return False

    # SECURITY FIX: Normalize path first to catch all traversal patterns
    try:
        normalized = os.path.normpath(path)
    except Exception:
        return False

    # Check for path traversal using normalized path
    if '..' in normalized:
        return False

    # Check for dangerous characters
    dangerous = set(';|&`$(){}[]<>!\n\r')
    if any(c in dangerous for c in path):
        return False

    # Ensure path is within expected directories (e.g., only under user's .ssh)
    # Additional validation could be added here
    return True


def _find_native_ssh() -> str | None:
    candidates = [
        r"C:\Windows\System32\OpenSSH\ssh.exe",
        r"C:\Windows\SysWOW64\OpenSSH\ssh.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return shutil.which("ssh")


# ------------------------------------------------------------------
# PuTTY
# ------------------------------------------------------------------

def _launch_putty(conn: Connection, putty_path: str, settings: AppSettings | None = None) -> tuple[bool, str]:
    """
    Open PuTTY directly with appropriate flags.
    
    SECURITY NOTE: PuTTY -pw flag is not recommended as passwords may be visible
    in process lists. SSH key authentication is preferred.
    """
    if not os.path.exists(putty_path):
        return False, (
            f"PuTTY nicht gefunden unter:\n{putty_path}\n\n"
            "Bitte den Pfad in den Einstellungen korrigieren."
        )

    # SECURITY FIX: Validate inputs to prevent command injection
    if not _is_safe_ssh_identifier(conn.host):
        return False, f"Ungültiger Hostname: {conn.host}"
    if not _is_safe_ssh_identifier(conn.user):
        return False, f"Ungültiger Username: {conn.user}"

    cmd = [putty_path, "-ssh", "-P", str(conn.port)]

    sec_level = getattr(settings, 'security_level', 0) if settings else 0
    if sec_level >= 1 and conn.auth_method == "password" and conn.password:
        logger.warning(f"PuTTY Autologin (Sicherheitsstufe 1) für {conn.name} – Passwort in Prozessliste.")
        cmd += ["-pw", conn.password]

    if conn.auth_method == "key" and (conn.putty_key_path or conn.key_path):
        dangerous = set(';"\'`$()&|<>')
        # Use putty_key_path if available, otherwise fall back to key_path
        key_path = conn.putty_key_path or conn.key_path
        if not _is_safe_file_path(key_path):
            return False, f"Ungültiger Key-Pfad: {key_path}"
        if not key_path.lower().endswith(".ppk"):
            logger.warning(
                f"PuTTY erwartet .ppk Schlüssel, gefunden: {key_path}\n"
                "Konvertiere mit PuTTYgen falls der Login fehlschlägt."
            )
        cmd += ["-i", key_path]

    # SECURITY FIX: Validate the combined user@host
    user_host = f"{conn.user}@{conn.host}"
    if not _is_safe_ssh_identifier(user_host):
        return False, f"Ungültige Verbindung: {user_host}"
    cmd.append(user_host)

    # SECURITY FIX (FINDING-A): Mask -pw argument value in log to prevent credential exposure
    safe_cmd = [
        ("[REDACTED]" if (i > 0 and cmd[i - 1] == "-pw") else a)
        for i, a in enumerate(cmd)
    ]
    logger.debug(f"PuTTY cmd: {' '.join(safe_cmd)}")
    try:
        subprocess.Popen(cmd, creationflags=0x08000000)
        return True, ""
    except Exception as e:
        return False, str(e)
