"""
cli_main.py - Console entry point for NEO SSH-Win Manager CLI access.

Built as a separate console-subsystem EXE (NeoSSHWinManager-cli.exe) so that
stdin/stdout stay in the caller's terminal. The GUI main instance must be
running and logged in; this process only talks to it over the named pipe
to resolve the access key, then opens the paramiko session in-place.

Usage:
    NeoSSHWinManager-cli.exe --connect-cli <access_key>
    NeoSSHWinManager-cli.exe --connect-cli -          # liest Key von stdin (empfohlen)
"""

import sys
import os


def _handle_cli_connect(key: str, exec_cmd: str = None) -> int:
    # src/ auf den Importpfad legen – sowohl im Dev-Modus als auch im frozen EXE.
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    if base not in sys.path:
        sys.path.insert(0, base)

    from src.ipc_security import IpcError, IpcNotRunning, IpcUntrustedServer, request

    # The pipe server must run as this account before the key is sent
    # (see src/ipc_security.py).
    try:
        res_data = request({"action": "cli_connect", "key": key}, timeout_ms=10000)
    except IpcNotRunning:
        print("Fehler: SSH Win Manager muss gestartet und eingeloggt sein.")
        return 1
    except IpcUntrustedServer:
        print("Fehler: Die Gegenstelle der IPC-Pipe läuft unter einem anderen Benutzerkonto – "
              "Verbindung abgebrochen.")
        return 1
    except IpcError:
        print("Fehler: Keine Antwort von SSH Win Manager erhalten.")
        return 1

    if not res_data.get("success"):
        print(f"Fehler: {res_data.get('error', 'Ungültiger Key oder Zugriff verweigert.')}")
        return 1

    conn_data = res_data["connection"]
    if not exec_cmd:
        print(f"Verbindung zu '{conn_data['name']}' wird hergestellt...")

    from src.ssh_launcher import launch_ssh_in_current_terminal
    # Rückgabewert durchreichen: vorher wurde er verworfen und pauschal 0
    # gemeldet — ein gescheiterter Verbindungsaufbau war für Aufrufer damit
    # nicht von einem Erfolg zu unterscheiden.
    # cli_key (derselbe Access-Key wie oben) wird durchgereicht, damit am
    # Ende ein CLI-Verlaufseintrag an die GUI-Instanz gesendet werden kann.
    rc = launch_ssh_in_current_terminal(conn_data, exec_command=exec_cmd, cli_key=key)
    return rc if isinstance(rc, int) else 0


def main() -> int:
    argv = sys.argv[1:]
    key = None
    exec_cmd = None
    for flag in ("--connect-cli", "-connectssh"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv):
                key = argv[i + 1]
            break

    if "--exec" in argv:
        i = argv.index("--exec")
        if i + 1 < len(argv):
            exec_cmd = argv[i + 1]

    if not key:
        print("Usage: NeoSSHWinManager-cli.exe --connect-cli <access_key> [--exec \"command\"]")
        print("       NeoSSHWinManager-cli.exe --connect-cli - [--exec \"command\"]  # Key via stdin")
        return 2

    # CWE-214: Key via stdin lesen wenn "-" übergeben — verhindert Exposition in Prozessliste
    if key == "-":
        key = sys.stdin.readline().rstrip("\n\r")
        if not key:
            print("Fehler: Kein Key via stdin empfangen.")
            return 2

    try:
        return _handle_cli_connect(key, exec_cmd=exec_cmd)
    except Exception as e:
        print(f"Fehler bei CLI-Verbindung: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
