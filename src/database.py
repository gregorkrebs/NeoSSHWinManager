# database.py – Secure SQLite Database for NEO SSH-Win Manager.
#
# Schema:
#   users       – App-eigene Benutzer (unabhängig von Windows-Accounts)
#   connections – SSH-Verbindungen, pro Benutzer getrennt
#   settings    – App-Einstellungen, pro Benutzer
#
# Passwörter:
#   - App-Passwort: PBKDF2-HMAC-SHA256 Hash (nie im Klartext)
#   - SSH-Passwörter: AES-256-GCM verschlüsselt mit user-spezifischem Key
#
# SECURITY FIXES:
#   - Secure file permissions (600 on Unix, restricted ACL on Windows)
#   - Database encryption at rest support (SQLCipher)
#   - TOCTOU fix: _set_secure_permissions() called after DB file creation (FINDING-08)
#
# pip install cryptography

import sqlite3
import os
import stat
import sys
from pathlib import Path

import logging
_db_logger = logging.getLogger(__name__)

if sys.platform == 'win32':
    import win32api
    import win32security
    import ntsecuritycon as con
    import pywintypes

    # Full access for the owner. The old code granted only
    # FILE_GENERIC_READ | FILE_GENERIC_WRITE, which leaves out FILE_TRAVERSE,
    # DELETE and WRITE_DAC — see _set_secure_permissions() for why that locked
    # the app out of its own data folder (GitHub issue #22).
    _FULL = con.FILE_ALL_ACCESS
    _SYSTEM_SID = 'S-1-5-18'   # NT AUTHORITY\SYSTEM, language-independent


def current_user_sid():
    """SID of the account this process actually runs as, or None.

    os.environ['USERNAME'] + LookupAccountName() is only a guess: the value is
    inherited from whatever started us and can resolve to a *different* account
    than the one we run as (renamed account, a domain account that shares the
    name, a process launched via runas or a scheduled task). An owner-only DACL
    built for the wrong SID locks the app out of its own data folder for good,
    so ask the process token — which cannot be wrong — and keep the env-var
    lookup as a fallback for the rare case the token query fails.
    """
    if sys.platform != 'win32':
        return None
    try:
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(), win32security.TOKEN_QUERY
        )
        return win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    except Exception as e:
        _db_logger.debug(f"Token-SID nicht ermittelbar, nutze USERNAME: {e}")
    username = os.environ.get('USERNAME') or os.environ.get('USER')
    if not username:
        return None
    try:
        return win32security.LookupAccountName(None, username)[0]
    except Exception as e:
        _db_logger.debug(f"LookupAccountName({username}) fehlgeschlagen: {e}")
        return None


def _is_usable(path: Path) -> bool:
    """Can *we* still use `path` with the permissions currently on it?

    A real open/create, because os.access() on Windows only looks at the
    read-only attribute and happily reports success on a path whose DACL
    denies us everything.
    """
    try:
        if path.is_dir():
            # PID in the name: a second instance starting at the same moment
            # must not delete our probe out from under us and make us report a
            # perfectly fine folder as locked.
            probe = path / f".permcheck-{os.getpid()}.tmp"
            with open(probe, 'wb'):
                pass
            try:
                os.unlink(probe)
            except OSError:
                pass
        else:
            with open(path, 'r+b'):
                pass
        return True
    except OSError as e:
        _db_logger.warning(f"Zugriffstest fehlgeschlagen für {path}: {e}")
        return False


def _set_secure_permissions(path: Path, user_sid=None, verify: bool = True) -> None:
    """
    Set secure file permissions on the database file.
    - Unix/Linux/macOS: 600 (owner read/write only)
    - Windows: DACL granting full access to the current user and SYSTEM only

    The DACL replaces (does not extend) whatever %APPDATA% inherits down, so
    other standard users and — deliberately, this is the CWE-732 hardening —
    local administrators lose access to the credential database.

    Two rules keep that hardening from turning into a self-lockout (GitHub
    issue #22: the app locked itself out of %APPDATA%\\SSHWinManager on Windows
    10 and then crashed on every start, with no way back short of icacls):

    1. Grant FILE_ALL_ACCESS, not FILE_GENERIC_READ | FILE_GENERIC_WRITE. The
       generic pair omits FILE_TRAVERSE (needed to open *anything* below the
       data folder unless the account happens to hold SeChangeNotifyPrivilege,
       which hardened installs remove), DELETE (SQLite's -wal/-shm cleanup) and
       WRITE_DAC (without it the next start cannot repair the ACL it just
       wrote). SYSTEM is kept because it can take ownership of any file anyway,
       so excluding it buys no security and only breaks backup/AV/repair.
    2. Verify afterwards that the path is still usable and roll the previous
       DACL back if it is not. Whatever the environment does with SIDs and
       policies, the app must never leave itself a folder it cannot open.

    Reading and writing the DACL stay best-effort against ERROR_ACCESS_DENIED:
    they need READ_CONTROL/WRITE_DAC, which the current token only gets
    implicitly if it owns the file. Files created while running as the built-in
    Administrator account can end up owned by the BUILTIN\\Administrators
    *group* instead of the user, and once UAC Admin Approval Mode is enabled
    for that account the normal token no longer carries that group. That is an
    ownership problem for src/permission_repair.py to fix, not something to
    crash app startup over — log and keep whatever permissions already exist.
    Any other error (e.g. the path not existing at all) is a caller bug and
    still raises.

    `user_sid` overrides who the DACL is written for; src/permission_repair.py
    passes the SID of the user being repaired, which is not necessarily the
    account the (elevated) repair itself runs as. `verify` must be turned off
    in that case: the usability probe can only test our own access, and a
    repair that hands the folder back to somebody else would always fail it.
    """
    if sys.platform != 'win32':
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        return

    path = Path(path)
    try:
        sd = win32security.GetFileSecurity(
            str(path), win32security.DACL_SECURITY_INFORMATION
        )
    except pywintypes.error as e:
        if e.winerror == 5:  # ERROR_ACCESS_DENIED
            _db_logger.warning(f"Konnte ACL nicht lesen (Zugriff verweigert) für {path}: {e}")
            return
        raise

    if user_sid is None:
        user_sid = current_user_sid()
    if user_sid is None:
        raise RuntimeError(
            "ACL-Setzung fehlgeschlagen: Konnte die SID des aktuellen Benutzers nicht ermitteln."
        )

    # Subfolders/files created later must inherit the same access, otherwise
    # every new file falls back to the token default DACL and the folder ends
    # up with a patchwork of permissions.
    ace_flags = (
        con.OBJECT_INHERIT_ACE | con.CONTAINER_INHERIT_ACE if path.is_dir() else 0
    )

    dacl = win32security.ACL()
    dacl.AddAccessAllowedAceEx(win32security.ACL_REVISION, ace_flags, _FULL, user_sid)
    try:
        dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION, ace_flags, _FULL,
            win32security.ConvertStringSidToSid(_SYSTEM_SID),
        )
    except Exception as e:   # pragma: no cover – SYSTEM always resolves
        _db_logger.debug(f"SYSTEM-SID nicht auflösbar: {e}")

    previous_dacl = sd.GetSecurityDescriptorDacl()
    sd.SetSecurityDescriptorDacl(1, dacl, 0)
    try:
        win32security.SetFileSecurity(
            str(path), win32security.DACL_SECURITY_INFORMATION, sd
        )
    except Exception as e:
        _db_logger.warning(f"Konnte sichere Berechtigungen nicht setzen für {path}: {e}")
        return

    if not verify or _is_usable(path):
        _db_logger.debug(f"ACL gesetzt (nur Eigentümer + SYSTEM): {path}")
        return

    # Hardening cost us access to our own data — undo it rather than leave the
    # app unable to start. Losing the hardening is recoverable, a locked folder
    # in %APPDATA% is not.
    _db_logger.error(
        f"Sichere ACL hätte den Zugriff auf {path} gesperrt — vorherige Rechte werden "
        "wiederhergestellt (Daten bleiben erreichbar, Härtung übersprungen)."
    )
    try:
        # Restore exactly what was read, including the "no DACL present" case.
        sd.SetSecurityDescriptorDacl(0 if previous_dacl is None else 1, previous_dacl, 0)
        win32security.SetFileSecurity(
            str(path), win32security.DACL_SECURITY_INFORMATION, sd
        )
    except Exception as e:
        _db_logger.error(f"Rücknahme der ACL fehlgeschlagen für {path}: {e}")


def data_dir() -> Path:
    """App data directory (%APPDATA%\\SSHWinManager). Pure path computation,
    no permission side effects — safe to call before any ownership repair."""
    appdata = os.environ.get("APPDATA", str(Path.home()))
    return Path(appdata) / "SSHWinManager"


def get_db_path() -> Path:
    db_dir = data_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "data.db"

    # SECURITY FIX (FINDING-08 – TOCTOU):
    # If the file already exists, apply permissions immediately.
    # If it is a new file, permissions are applied after init_db() creates it
    # via the sqlite3.connect() call — see the else-branch comment below.
    if db_path.exists():
        _set_secure_permissions(db_path)
    else:
        # File does not exist yet.  sqlite3.connect() (called by get_connection()
        # and init_db()) will create the file.  _set_secure_permissions() is
        # then called by init_db() *after* the schema has been written, closing
        # the TOCTOU window between file creation and permission hardening.
        _db_logger.info(f"Neue Datenbankdatei erstellt: {db_path}")

    return db_path


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    """Erstellt alle Tabellen falls sie noch nicht existieren."""
    db_path = get_db_path()
    # Verzeichnis existiert immer (get_db_path() legt es an)
    _set_secure_permissions(db_path.parent)

    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id          TEXT PRIMARY KEY,
                username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
                pw_hash     TEXT NOT NULL,   -- PBKDF2 hex
                pw_salt     TEXT NOT NULL,   -- random salt hex
                enc_key_enc TEXT NOT NULL,   -- AES-key verschlüsselt mit user-pw
                enc_key_iv  TEXT NOT NULL,   -- IV für enc_key_enc
                enc_key_kdf TEXT NOT NULL DEFAULT 'pbkdf2',  -- KDF: 'pbkdf2' | 'argon2'
                is_admin    INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS connections (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name         TEXT NOT NULL,
                host         TEXT NOT NULL,
                ssh_user     TEXT NOT NULL,
                remote_path  TEXT NOT NULL DEFAULT '/',
                port         INTEGER NOT NULL DEFAULT 22,
                auth_method  TEXT NOT NULL DEFAULT 'password',
                pw_enc       TEXT,   -- SSH-Passwort AES verschlüsselt (hex)
                pw_iv        TEXT,   -- IV für pw_enc (hex)
                key_path      TEXT,
                putty_key_path TEXT,  -- .ppk format key for PuTTY/plink
                drive_letter TEXT NOT NULL DEFAULT 'Z:',
                protocol     TEXT NOT NULL DEFAULT 'sftp',  -- 'sftp' | 'ftp' | 'ftps'
                ftp_implicit_tls INTEGER NOT NULL DEFAULT 0, -- FTPS implizit (Port 990)
                ftp_passive      INTEGER NOT NULL DEFAULT 1,
                ftp_verify_cert  INTEGER NOT NULL DEFAULT 1,
                sort_order   INTEGER NOT NULL DEFAULT 0,
                cli_access_enabled INTEGER NOT NULL DEFAULT 0,
                cli_access_key     TEXT UNIQUE,  -- CLI-Access-Key AES verschlüsselt (hex)
                cli_access_key_iv  TEXT,         -- IV für cli_access_key (hex)
                cli_access_key_hash TEXT,        -- SHA-256(Klartext-Key), fürs Lookup (AES-GCM nutzt zufällige IVs → Ciphertext ist nicht wiederholbar vergleichbar)
                groups       TEXT DEFAULT '',    -- Kommaseparierte Gruppen/Tags
                is_template  INTEGER NOT NULL DEFAULT 0,  -- 1 = Template, 0 = normale Verbindung
                template_id  TEXT,               -- Referenz zu Template (falls von Template erstellt)
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                user_id                  TEXT PRIMARY KEY
                    REFERENCES users(id) ON DELETE CASCADE,
                start_with_windows       INTEGER DEFAULT 0,
                minimize_to_tray         INTEGER DEFAULT 1,
                check_interval_seconds   INTEGER DEFAULT 30,
                debug_mode               INTEGER DEFAULT 0,
                require_admin            INTEGER DEFAULT 0,
                use_putty                INTEGER DEFAULT 0,
                putty_path               TEXT    DEFAULT '',
                auto_login               INTEGER DEFAULT 0,  -- Windows Auto-Login
                auto_reconnect           INTEGER DEFAULT 1,  -- Beim Start automatisch reconnecten
                language                 TEXT    DEFAULT 'en',  -- UI Sprache (en, de, es, ru, nl, ar)
                theme                    TEXT    DEFAULT 'dark',  -- UI Theme (dark, light)
                security_level           INTEGER DEFAULT 0,  -- 0=Strict, 1=Key-Auth, 2=Insecure-PW
                allow_passwordless_key_auth INTEGER DEFAULT 0,
                allow_insecure_password_auth INTEGER DEFAULT 0,
                auto_remount_on_lost     INTEGER DEFAULT 1,  -- Bei Verbindungsverlust remounten
                telemetry_enabled        INTEGER DEFAULT 0,
                telemetry_prompt_shown   INTEGER DEFAULT 0,
                updated_at               TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS active_mounts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                conn_id     TEXT NOT NULL,
                mounted_at  TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(user_id, conn_id)
            );

            CREATE TABLE IF NOT EXISTS pro_licenses (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id   TEXT NOT NULL UNIQUE,
                pro_key_hash TEXT NOT NULL,
                hmac_token   TEXT NOT NULL,
                activated_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_checked TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS cli_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                conn_id      TEXT NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
                kind         TEXT NOT NULL,   -- 'exec' | 'session'
                command_enc  TEXT,   -- verschlüsselter Befehl (nur kind='exec')
                command_iv   TEXT,
                output_enc   TEXT,   -- verschlüsselte Ausgabe/Mitschnitt
                output_iv    TEXT,
                exit_code    INTEGER,   -- nur kind='exec'
                truncated    INTEGER NOT NULL DEFAULT 0,
                started_at   TEXT NOT NULL,   -- ISO8601 UTC
                ended_at     TEXT,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_cli_history_conn
                ON cli_history(user_id, conn_id, started_at);
        """)

        # Migration: Add columns that were introduced after the first release.
        # Each ALTER runs on its own: SQLite rejects a few of them on very old
        # databases (e.g. ADD COLUMN ... UNIQUE), and a single failure must not
        # skip every migration that follows it.
        def _add_column(table: str, column: str, ddl: str, existing: list) -> None:
            if column in existing:
                return
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                return
            except Exception as exc:
                _db_logger.warning(
                    f"Migration: Spalte {table}.{column} konnte nicht angelegt werden: {exc}"
                )
            if "UNIQUE" not in ddl.upper():
                return
            # SQLite cannot add a UNIQUE column to an existing table. The column
            # itself matters more than the constraint (the values are random
            # 64-byte keys), so retry without it instead of leaving it missing.
            try:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} "
                    f"{ddl.upper().replace('UNIQUE', '').strip()}"
                )
                _db_logger.info(
                    f"Migration: {table}.{column} ohne UNIQUE-Constraint angelegt"
                )
            except Exception as exc:
                _db_logger.warning(
                    f"Migration: Spalte {table}.{column} endgültig fehlgeschlagen: {exc}"
                )

        try:
            cursor = conn.execute("PRAGMA table_info(connections)")
            cols = [row[1] for row in cursor.fetchall()]
            migrations = [
                ("cli_access_enabled", "INTEGER NOT NULL DEFAULT 0"),
                ("cli_access_key", "TEXT UNIQUE"),
                ("cli_access_key_iv", "TEXT"),
                ("cli_access_key_hash", "TEXT"),
                ("putty_key_path", "TEXT"),
                # CWE-312: Verschlüsselte Metadaten-Spalten
                ("host_enc", "TEXT"), ("host_iv", "TEXT"),
                ("ssh_user_enc", "TEXT"), ("ssh_user_iv", "TEXT"),
                ("name_enc", "TEXT"), ("name_iv", "TEXT"),
                ("remote_path_enc", "TEXT"), ("remote_path_iv", "TEXT"),
                # Gruppen/Tags und Templates
                ("groups", "TEXT DEFAULT ''"),
                ("is_template", "INTEGER NOT NULL DEFAULT 0"),
                ("template_id", "TEXT"),
                # FTP/FTPS-Unterstützung
                ("protocol", "TEXT NOT NULL DEFAULT 'sftp'"),
                ("ftp_implicit_tls", "INTEGER NOT NULL DEFAULT 0"),
                ("ftp_passive", "INTEGER NOT NULL DEFAULT 1"),
                ("ftp_verify_cert", "INTEGER NOT NULL DEFAULT 1"),
            ]
            for column, ddl in migrations:
                _add_column("connections", column, ddl, cols)
        except Exception:
            pass

        # Migration: enc_key_kdf column in users
        try:
            cursor = conn.execute("PRAGMA table_info(users)")
            cols = [row[1] for row in cursor.fetchall()]
            if "enc_key_kdf" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN enc_key_kdf TEXT NOT NULL DEFAULT 'pbkdf2'")
        except Exception:
            pass

        # Migration: language column in app_settings
        try:
            cursor = conn.execute("PRAGMA table_info(app_settings)")
            cols = [row[1] for row in cursor.fetchall()]
            if "language" not in cols:
                conn.execute("ALTER TABLE app_settings ADD COLUMN language TEXT DEFAULT 'en'")
            if "theme" not in cols:
                conn.execute("ALTER TABLE app_settings ADD COLUMN theme TEXT DEFAULT 'dark'")
            if "security_level" not in cols:
                conn.execute("ALTER TABLE app_settings ADD COLUMN security_level INTEGER DEFAULT 0")
            if "allow_passwordless_key_auth" not in cols:
                conn.execute("ALTER TABLE app_settings ADD COLUMN allow_passwordless_key_auth INTEGER DEFAULT 0")
            if "allow_insecure_password_auth" not in cols:
                conn.execute("ALTER TABLE app_settings ADD COLUMN allow_insecure_password_auth INTEGER DEFAULT 0")
            if "auto_remount_on_lost" not in cols:
                conn.execute("ALTER TABLE app_settings ADD COLUMN auto_remount_on_lost INTEGER DEFAULT 1")
            if "telemetry_enabled" not in cols:
                conn.execute("ALTER TABLE app_settings ADD COLUMN telemetry_enabled INTEGER DEFAULT 0")
            if "telemetry_prompt_shown" not in cols:
                conn.execute("ALTER TABLE app_settings ADD COLUMN telemetry_prompt_shown INTEGER DEFAULT 0")
            if "terminal_client" not in cols:
                conn.execute("ALTER TABLE app_settings ADD COLUMN terminal_client TEXT DEFAULT 'xterm'")
            if "sshfs_disable_cache" not in cols:
                conn.execute("ALTER TABLE app_settings ADD COLUMN sshfs_disable_cache INTEGER DEFAULT 0")
        except Exception:
            pass

    # SECURITY FIX (FINDING-08 – TOCTOU): DB file now guaranteed to exist
    # (sqlite3.connect inside get_connection() creates it if absent).
    # Apply secure permissions here so the window between file creation and
    # permission hardening is closed even on the very first run.
    _set_secure_permissions(db_path)
