# auth_manager.py – Benutzerverwaltung und Session für NEO SSH-Win Manager.
#
# Konzept:
#   - Benutzer registrieren sich mit Username + Passwort
#   - Login → Session (enc_key im Speicher, nie auf Disk im Klartext)
#   - Jeder Benutzer sieht nur seine eigenen Verbindungen
#   - Admin-Benutzer können andere Benutzer verwalten
#   - SSH-Passwörter werden mit dem benutzerspezifischen enc_key ver-/entschlüsselt

import uuid
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

from src.database import get_connection
from src.crypto import (
    hash_password, verify_password, generate_enc_key,
    encrypt_key, decrypt_key, encrypt, decrypt, is_available
)
from src.config import Connection, AppSettings
from src.app_logger import logger
from src.utils.secure_memory import SecureBytes, secure_wipe_bytes

# CWE-307: Brute-Force-Schutz — Tier-basiertes Lockout-Schema
#
# Jede Zeile: (Fehlversuche_im_Tier, Sperrdauer_in_Sekunden)
# Nach Ablauf der Sperre bekommt der Nutzer die nächste Tier-Menge an Versuchen.
# Der letzte Tier wiederholt sich unbegrenzt.
#
# Tier 1:  5 Versuche  →  30 s   (Tippfehler toleriert)
# Tier 2: 10 Versuche  →  10 min
# Tier 3:  5 Versuche  →   1 h
# Tier 4:  3 Versuche  →  24 h
# Tier 5+: 2 Versuche  →   7 Tage (Wiederholung)
_LOCKOUT_SCHEDULE: list[tuple[int, int]] = [
    (5,       30),
    (10,     600),
    (5,    3_600),
    (3,   86_400),
    (2,  604_800),
]

# SECURITY FIX (FINDING-05): _login_attempts is now a cache backed by the
# database.  On startup the cache is populated from the DB so that a process
# restart cannot be used to bypass lockouts.
_login_attempts: dict = {}   # key: username.lower() → {"count": int, "locked_until": float}
_LOGIN_LOCK = threading.Lock()


def _lockout_for_count(count: int) -> int:
    """Gibt Sperrdauer in Sekunden zurück, wenn `count` eine Tier-Grenze trifft, sonst 0."""
    cumulative = 0
    for threshold, duration in _LOCKOUT_SCHEDULE:
        cumulative += threshold
        if count == cumulative:
            return duration
    # Hinter dem letzten Tier: alle 2 weiteren Fehlversuche → 7 Tage
    last_boundary = sum(t for t, _ in _LOCKOUT_SCHEDULE)
    last_step, last_dur = _LOCKOUT_SCHEDULE[-1]
    if count > last_boundary and (count - last_boundary) % last_step == 0:
        return last_dur
    return 0


# ------------------------------------------------------------------
# FINDING-05: Persistent login-attempt helpers
# ------------------------------------------------------------------

def _ensure_login_attempts_table() -> None:
    """Create the login_attempts persistence table if it does not exist."""
    try:
        with get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS login_attempts (
                    username_key TEXT PRIMARY KEY,
                    fail_count   INTEGER NOT NULL DEFAULT 0,
                    locked_until REAL    NOT NULL DEFAULT 0.0
                )
            """)
    except Exception as e:
        logger.warning(f"login_attempts Tabelle konnte nicht erstellt werden: {e}")


def _load_login_attempts_from_db() -> None:
    """Populate in-memory cache from the database on startup."""
    try:
        _ensure_login_attempts_table()
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT username_key, fail_count, locked_until FROM login_attempts"
            ).fetchall()
        with _LOGIN_LOCK:
            for row in rows:
                _login_attempts[row["username_key"]] = {
                    "count": row["fail_count"],
                    "locked_until": row["locked_until"],
                }
    except Exception as e:
        logger.warning(f"Fehlversuche konnten nicht aus DB geladen werden: {e}")


def _persist_login_attempt(key: str, attempt: dict) -> None:
    """Write a single attempt record to the database (called under _LOGIN_LOCK)."""
    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO login_attempts (username_key, fail_count, locked_until)
                   VALUES (?, ?, ?)
                   ON CONFLICT(username_key) DO UPDATE SET
                     fail_count   = excluded.fail_count,
                     locked_until = excluded.locked_until""",
                (key, attempt["count"], attempt["locked_until"])
            )
    except Exception as e:
        logger.warning(f"Fehlversuch konnte nicht in DB persistiert werden: {e}")


def _clear_login_attempt_from_db(key: str) -> None:
    """Remove a successfully-authenticated user's attempt record from the DB."""
    try:
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM login_attempts WHERE username_key = ?", (key,)
            )
    except Exception as e:
        logger.warning(f"Login-Attempt konnte nicht aus DB gelöscht werden: {e}")


# Load persisted attempts when this module is first imported.
# This ensures lockouts survive process restarts (FINDING-05).
_load_login_attempts_from_db()


class LoginLockedError(Exception):
    """Wird geworfen, wenn ein Account wegen zu vieler Fehlversuche gesperrt ist."""
    def __init__(self, seconds_remaining: int, total_failures: int):
        self.seconds_remaining = seconds_remaining
        self.total_failures = total_failures
        super().__init__(
            f"Login gesperrt für {seconds_remaining}s ({total_failures} Fehlversuche)"
        )


# ------------------------------------------------------------------
# Datenmodelle
# ------------------------------------------------------------------

@dataclass
class AppUser:
    id: str
    username: str
    is_admin: bool
    # enc_key wird NUR im RAM gehalten, nie persistiert
    _enc_key: bytes = field(default=b"", repr=False)

    @property
    def enc_key(self) -> bytes:
        return self._enc_key


# ------------------------------------------------------------------
# Session (Singleton – aktuell eingeloggter Benutzer)
# ------------------------------------------------------------------

class Session:
    _current_user: Optional[AppUser] = None
    # CWE-362: Lock verhindert Race Condition bei gleichzeitigem Login/Passwortänderung
    _lock: threading.RLock = threading.RLock()

    @classmethod
    def login(cls, user: AppUser) -> None:
        with cls._lock:
            cls._current_user = user
        logger.info(f"Benutzer eingeloggt: {user.username}")

    @classmethod
    def logout(cls) -> None:
        with cls._lock:
            if cls._current_user:
                logger.info(f"Benutzer ausgeloggt: {cls._current_user.username}")
            cls._current_user = None

    @classmethod
    def current(cls) -> Optional[AppUser]:
        with cls._lock:
            return cls._current_user

    @classmethod
    def is_logged_in(cls) -> bool:
        with cls._lock:
            return cls._current_user is not None

    @classmethod
    def is_admin(cls) -> bool:
        with cls._lock:
            return cls._current_user is not None and cls._current_user.is_admin

    @classmethod
    def update_enc_key(cls, user_id: str, enc_key: bytes) -> None:
        """Atomares Update des enc_key im Session-Objekt nach Passwortänderung."""
        with cls._lock:
            if cls._current_user and cls._current_user.id == user_id:
                cls._current_user._enc_key = enc_key


# ------------------------------------------------------------------
# Benutzerverwaltung
# ------------------------------------------------------------------

class AuthManager:

    @staticmethod
    def has_any_users() -> bool:
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()
            return row["c"] > 0

    @staticmethod
    def register(username: str, password: str, is_admin: bool = False) -> AppUser:
        """
        Neuen Benutzer registrieren.
        Beim ersten Benutzer wird is_admin automatisch True gesetzt.
        """
        if not is_available():
            raise RuntimeError(
                "cryptography nicht installiert.\n"
                "Bitte ausführen: pip install cryptography"
            )

        with get_connection() as conn:
            # Erster Benutzer wird automatisch Admin
            count = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
            if count == 0:
                is_admin = True

            pw_hash, salt = hash_password(password)
            enc_key = generate_enc_key()
            # Neue Benutzer erhalten Argon2 als KDF
            enc_key_enc, enc_key_iv = encrypt_key(enc_key, password, salt, kdf='argon2')
            user_id = str(uuid.uuid4())

            conn.execute(
                """INSERT INTO users
                   (id, username, pw_hash, pw_salt, enc_key_enc, enc_key_iv, enc_key_kdf, is_admin)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, username.strip(), pw_hash, salt,
                 enc_key_enc, enc_key_iv, 'argon2', int(is_admin))
            )
            # Default-Einstellungen anlegen
            conn.execute(
                "INSERT INTO app_settings (user_id) VALUES (?)",
                (user_id,)
            )

        user = AppUser(
            id=user_id,
            username=username.strip(),
            is_admin=is_admin,
            _enc_key=enc_key,
        )
        logger.info(f"Benutzer registriert: {username} (admin={is_admin})")
        return user

    @staticmethod
    def authenticate(username: str, password: str) -> Optional[AppUser]:
        """
        Login: Prüft Passwort und lädt den Encryption Key in den RAM.
        Returns None bei falschem Passwort/unbekanntem User.
        Raises LoginLockedError wenn der Account gesperrt ist.
        """
        key = username.strip().lower()
        now = time.time()  # wall-clock: survives process restarts correctly

        # CWE-307: Aktive Sperre prüfen → sofort mit verbleibender Zeit melden
        with _LOGIN_LOCK:
            attempt = _login_attempts.get(key, {"count": 0, "locked_until": 0.0})
            if attempt["locked_until"] > now:
                remaining = int(attempt["locked_until"] - now) + 1
                logger.warning(
                    f"Login gesperrt für '{username}': noch {remaining}s "
                    f"(nach {attempt['count']} Fehlversuchen)"
                )
                raise LoginLockedError(remaining, attempt["count"])

        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username.strip(),)
            ).fetchone()

        def _record_failure():
            """Zählt Fehlversuch; wirft LoginLockedError wenn Tier-Grenze getroffen.
            FINDING-05: count and locked_until are written to DB for persistence."""
            with _LOGIN_LOCK:
                a = _login_attempts.get(key, {"count": 0, "locked_until": 0.0})
                a["count"] += 1
                lockout = _lockout_for_count(a["count"])
                if lockout > 0:
                    a["locked_until"] = time.time() + lockout  # wall-clock for DB persistence
                    logger.warning(
                        f"Login für '{username}' gesperrt für {lockout}s "
                        f"(Versuch #{a['count']})"
                    )
                _login_attempts[key] = a
                # SECURITY FIX (FINDING-05): persist to DB so process restart
                # cannot reset the counter and bypass brute-force protection.
                _persist_login_attempt(key, a)
                return lockout

        if not row:
            lockout = _record_failure()
            logger.warning(f"Login fehlgeschlagen: Benutzer '{username}' nicht gefunden.")
            if lockout:
                raise LoginLockedError(lockout, _login_attempts[key]["count"])
            return None

        if not verify_password(password, row["pw_hash"], row["pw_salt"]):
            lockout = _record_failure()
            logger.warning(f"Login fehlgeschlagen: Falsches Passwort für '{username}'.")
            if lockout:
                raise LoginLockedError(lockout, _login_attempts[key]["count"])
            return None

        kdf = row["enc_key_kdf"] if "enc_key_kdf" in row.keys() else "pbkdf2"
        try:
            enc_key = decrypt_key(
                row["enc_key_enc"], row["enc_key_iv"],
                password, row["pw_salt"], kdf=kdf
            )
        except Exception as e:
            logger.error(f"Encryption Key konnte nicht entschlüsselt werden: {e}")
            return None

        user = AppUser(
            id=row["id"],
            username=row["username"],
            is_admin=bool(row["is_admin"]),
            _enc_key=enc_key,
        )

        # Transparente Migration: PBKDF2 → Argon2 beim ersten Login nach Update
        if kdf == "pbkdf2":
            try:
                new_enc, new_iv = encrypt_key(enc_key, password, row["pw_salt"], kdf='argon2')
                with get_connection() as db:
                    db.execute(
                        "UPDATE users SET enc_key_enc=?, enc_key_iv=?, enc_key_kdf='argon2' WHERE id=?",
                        (new_enc, new_iv, row["id"])
                    )
                logger.info(f"KDF-Migration zu Argon2 abgeschlossen für Benutzer '{row['username']}'.")
            except Exception as e:
                logger.warning(f"KDF-Migration fehlgeschlagen (nicht kritisch): {e}")

        # Migration: Plaintext CLI-Keys → Encrypted + Metadaten-Verschlüsselung
        try:
            conn_mgr = UserConnectionManager(user)
            conn_mgr.migrate_cli_keys()
            conn_mgr.migrate_metadata_encryption()
        except Exception as e:
            logger.warning(f"Migrations fehlgeschlagen (nicht kritisch): {e}")

        # Erfolgreichen Login → Fehlversuchs-Zähler zurücksetzen (CWE-307)
        # FINDING-05: also clear from DB so persistent counter is removed.
        with _LOGIN_LOCK:
            _login_attempts.pop(key, None)
        _clear_login_attempt_from_db(key)

        return user

    @staticmethod
    def change_password(user_id: str, old_pw: str, new_pw: str) -> bool:
        """Passwort ändern und Encryption Key re-verschlüsseln."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()

        if not row or not verify_password(old_pw, row["pw_hash"], row["pw_salt"]):
            return False

        kdf = row["enc_key_kdf"] if "enc_key_kdf" in row.keys() else "pbkdf2"

        try:
            enc_key = decrypt_key(
                row["enc_key_enc"], row["enc_key_iv"],
                old_pw, row["pw_salt"], kdf=kdf
            )
        except Exception:
            return False

        new_hash, new_salt = hash_password(new_pw)
        new_enc_key_enc, new_enc_key_iv = encrypt_key(enc_key, new_pw, new_salt, kdf='argon2')

        with get_connection() as conn:
            conn.execute(
                """UPDATE users SET pw_hash=?, pw_salt=?, enc_key_enc=?, enc_key_iv=?, enc_key_kdf='argon2'
                   WHERE id=?""",
                (new_hash, new_salt, new_enc_key_enc, new_enc_key_iv, user_id)
            )

        # CWE-362: Atomares Update über Session.update_enc_key (thread-safe)
        Session.update_enc_key(user_id, enc_key)

        logger.info(f"Passwort geändert für user_id={user_id}")
        return True

    @staticmethod
    def admin_reset_password(user_id: str) -> Optional[str]:
        """
        Admin-Reset: generiert neues Passwort + neuen enc_key für den User.
        Da der alte enc_key ohne altes Passwort nicht entschlüsselt werden kann,
        gehen vorhandene verschlüsselte SSH-Passwörter verloren. Diese Felder
        werden geleert; Key-Auth-Verbindungen bleiben funktionsfähig.

        Returns das neue Klartext-Passwort oder None wenn der User nicht existiert.
        Raises PermissionError wenn der Aufrufer kein Admin ist.
        """
        # SECURITY: verify caller has admin rights (defence-in-depth beyond UI layer)
        if not Session.is_admin():
            raise PermissionError("admin_reset_password: Admin-Rechte erforderlich")

        import secrets, string
        alphabet = string.ascii_letters + string.digits
        new_pw = ''.join(secrets.choice(alphabet) for _ in range(14))

        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if not row:
                return None

            new_hash, new_salt = hash_password(new_pw)
            new_enc_key = generate_enc_key()
            new_enc_key_enc, new_enc_key_iv = encrypt_key(new_enc_key, new_pw, new_salt, kdf='argon2')

            conn.execute(
                """UPDATE users SET pw_hash=?, pw_salt=?, enc_key_enc=?, enc_key_iv=?, enc_key_kdf='argon2'
                   WHERE id=?""",
                (new_hash, new_salt, new_enc_key_enc, new_enc_key_iv, user_id)
            )
            # Alte verschlüsselte SSH-Passwörter sind unlesbar → leeren
            conn.execute(
                "UPDATE connections SET pw_enc='', pw_iv='' WHERE user_id=?",
                (user_id,)
            )

        logger.warning(f"Admin-Reset: Passwort für user_id={user_id} neu generiert, SSH-Passwörter gelöscht.")
        return new_pw

    @staticmethod
    def delete_user(user_id: str) -> bool:
        """Benutzer und alle zugehörigen Verbindungen löschen (CASCADE).
        Raises PermissionError wenn der Aufrufer kein Admin ist.
        """
        # SECURITY: verify caller has admin rights (defence-in-depth beyond UI layer)
        if not Session.is_admin():
            raise PermissionError("delete_user: Admin-Rechte erforderlich")
        with get_connection() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return True

    @staticmethod
    def list_users() -> List[dict]:
        """Alle Benutzer auflisten (nur für Admins).
        Raises PermissionError wenn der Aufrufer kein Admin ist.
        """
        # SECURITY: verify caller has admin rights (defence-in-depth beyond UI layer)
        if not Session.is_admin():
            raise PermissionError("list_users: Admin-Rechte erforderlich")
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT id, username, is_admin, created_at FROM users ORDER BY username"
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_user_by_username(username: str) -> Optional[dict]:
        """Sucht einen Benutzer anhand des Benutzernamens (für Windows Auto-Login).
        Gibt nur nicht-sensible Felder zurück (kein pw_hash, kein pw_salt, kein enc_key_enc).
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id, username, is_admin, enc_key_kdf, created_at FROM users WHERE username = ? COLLATE NOCASE",
                (username.strip(),)
            ).fetchone()
        return dict(row) if row else None


# ------------------------------------------------------------------
# Verbindungsverwaltung (mit Verschlüsselung)
# ------------------------------------------------------------------

class UserConnectionManager:
    """
    Verwaltet Verbindungen für den aktuell eingeloggten Benutzer.
    SSH-Passwörter werden transparent ver-/entschlüsselt.
    """

    def __init__(self, user: AppUser):
        self._user = user

    def migrate_metadata_encryption(self) -> None:
        """
        CWE-312: Verschlüsselt host, ssh_user, name, remote_path beim ersten Login nach Update.
        Idempotent — überspringt Zeilen, bei denen host_iv bereits gesetzt ist.
        """
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """SELECT id, host, ssh_user, name, remote_path FROM connections
                       WHERE user_id = ?
                       AND (host_iv IS NULL OR host_iv = '')""",
                    (self._user.id,)
                ).fetchall()

            if not rows:
                return

            for row in rows:
                host_enc, host_iv = self._encrypt_pw(row["host"])
                user_enc, user_iv = self._encrypt_pw(row["ssh_user"])
                name_enc, name_iv = self._encrypt_pw(row["name"])
                path_enc, path_iv = self._encrypt_pw(row["remote_path"] or "/")
                with get_connection() as db:
                    db.execute(
                        """UPDATE connections SET
                           host='', host_enc=?, host_iv=?,
                           ssh_user='', ssh_user_enc=?, ssh_user_iv=?,
                           name='', name_enc=?, name_iv=?,
                           remote_path='', remote_path_enc=?, remote_path_iv=?
                           WHERE id=? AND user_id=?""",
                        (host_enc, host_iv, user_enc, user_iv,
                         name_enc, name_iv, path_enc, path_iv,
                         row["id"], self._user.id)
                    )

            logger.info(
                f"Metadaten-Verschlüsselung abgeschlossen für '{self._user.username}': "
                f"{len(rows)} Verbindung(en) verschlüsselt."
            )
        except Exception as e:
            logger.error(f"Metadaten-Verschlüsselung fehlgeschlagen: {e}")

    def migrate_cli_keys(self) -> None:
        """
        Migration: Verschlüsselt alle plaintext CLI-Keys beim ersten Login nach dem Update.
        Idempotent — kann beliebig oft aufgerufen werden.
        """
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """SELECT id, cli_access_key FROM connections
                       WHERE user_id = ?
                       AND cli_access_key IS NOT NULL
                       AND cli_access_key != ''
                       AND (cli_access_key_iv IS NULL OR cli_access_key_iv = '')""",
                    (self._user.id,)
                ).fetchall()

            if not rows:
                return

            for row in rows:
                plaintext_key = row["cli_access_key"]
                if plaintext_key:
                    cli_key_enc, cli_key_iv = self._encrypt_pw(plaintext_key)
                    with get_connection() as db:
                        db.execute(
                            """UPDATE connections SET cli_access_key = ?, cli_access_key_iv = ?
                               WHERE id = ? AND user_id = ?""",
                            (cli_key_enc, cli_key_iv, row["id"], self._user.id)
                        )

            logger.info(f"CLI-Key Migration abgeschlossen für Benutzer {self._user.username}: {len(rows)} Keys verschlüsselt.")
        except Exception as e:
            logger.error(f"CLI-Key Migration fehlgeschlagen: {e}")

    def _encrypt_pw(self, password: str) -> tuple[str, str]:
        if not password:
            return "", ""
        return encrypt(password, self._user.enc_key)

    def _decrypt_pw(self, pw_enc: str, pw_iv: str) -> str:
        if not pw_enc or not pw_iv:
            return ""
        try:
            val = decrypt(pw_enc, pw_iv, self._user.enc_key)
            return val
        except Exception as e:
            logger.error(f"SSH-Passwort konnte nicht entschlüsselt werden: {e}")
            return ""

    def _dec_meta(self, row, enc_col: str, iv_col: str, plain_col: str) -> str:
        """Liest verschlüsselte Metadaten-Spalte; fällt auf Klartext zurück (pre-migration)."""
        try:
            iv = row[iv_col]
            if iv:
                return self._decrypt_pw(row[enc_col], iv)
        except (KeyError, IndexError):
            pass
        return row[plain_col] or ""

    def _row_to_conn(self, row) -> Connection:
        pw = self._decrypt_pw(row["pw_enc"] or "", row["pw_iv"] or "")

        # CWE-312: Bevorzuge verschlüsselte Metadaten-Spalten (post-migration)
        name = self._dec_meta(row, "name_enc", "name_iv", "name")
        host = self._dec_meta(row, "host_enc", "host_iv", "host")
        ssh_user = self._dec_meta(row, "ssh_user_enc", "ssh_user_iv", "ssh_user")
        remote_path = self._dec_meta(row, "remote_path_enc", "remote_path_iv", "remote_path")

        cli_key = ""
        try:
            cli_key_iv = row["cli_access_key_iv"]
            if cli_key_iv:
                try:
                    cli_key = decrypt(row["cli_access_key"], cli_key_iv, self._user.enc_key)
                except Exception as e:
                    logger.error(f"CLI-Key entschlüsselung fehlgeschlagen: {e}")
        except (KeyError, IndexError):
            pass

        # Neue Felder mit Fallback für alte Datenbanken
        try:
            groups = row["groups"] or ""
        except (KeyError, IndexError):
            groups = ""
        try:
            is_template = bool(row["is_template"])
        except (KeyError, IndexError):
            is_template = False
        try:
            template_id = row["template_id"] or None
        except (KeyError, IndexError):
            template_id = None

        # FTP-Felder: Datenbanken vor der FTP-Unterstützung kennen sie nicht
        try:
            protocol = row["protocol"] or "sftp"
        except (KeyError, IndexError):
            protocol = "sftp"
        try:
            ftp_implicit_tls = bool(row["ftp_implicit_tls"])
        except (KeyError, IndexError):
            ftp_implicit_tls = False
        try:
            ftp_passive = bool(row["ftp_passive"])
        except (KeyError, IndexError):
            ftp_passive = True
        try:
            ftp_verify_cert = bool(row["ftp_verify_cert"])
        except (KeyError, IndexError):
            ftp_verify_cert = True

        return Connection(
            id=row["id"],
            name=name,
            host=host,
            user=ssh_user,
            remote_path=remote_path,
            port=row["port"],
            auth_method=row["auth_method"],
            password=pw,
            key_path=row["key_path"] or "",
            putty_key_path=row["putty_key_path"] or "",
            drive_letter=row["drive_letter"],
            protocol=protocol,
            ftp_implicit_tls=ftp_implicit_tls,
            ftp_passive=ftp_passive,
            ftp_verify_cert=ftp_verify_cert,
            cli_access_enabled=bool(row["cli_access_enabled"]),
            cli_access_key=cli_key,
            groups=groups,
            is_template=is_template,
            template_id=template_id,
        )

    def get_all(self, include_templates: bool = False) -> List[Connection]:
        """Alle Verbindungen holen. Wenn include_templates=False, werden Templates ausgeschlossen."""
        with get_connection() as conn:
            if include_templates:
                rows = conn.execute(
                    """SELECT * FROM connections
                       WHERE user_id = ?
                       ORDER BY sort_order, name""",
                    (self._user.id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM connections
                       WHERE user_id = ? AND is_template = 0
                       ORDER BY sort_order, name""",
                    (self._user.id,)
                ).fetchall()
        return [self._row_to_conn(r) for r in rows]

    def get_connections(self) -> List[Connection]:
        """Nur normale Verbindungen (keine Templates)."""
        return self.get_all(include_templates=False)

    def get_templates(self) -> List[Connection]:
        """Nur Templates holen."""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM connections
                   WHERE user_id = ? AND is_template = 1
                   ORDER BY name""",
                (self._user.id,)
            ).fetchall()
        return [self._row_to_conn(r) for r in rows]

    def get_by_id(self, conn_id: str) -> Optional[Connection]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM connections WHERE id = ? AND user_id = ?",
                (conn_id, self._user.id)
            ).fetchone()
        return self._row_to_conn(row) if row else None

    def get_by_cli_key(self, cli_key: str) -> Optional[Connection]:
        """Sucht eine Verbindung anhand des CLI-Keys (global, nur verschlüsselte Keys nach Migration)."""
        with get_connection() as conn:
            cli_key_enc, _ = self._encrypt_pw(cli_key)
            row = conn.execute(
                "SELECT * FROM connections WHERE cli_access_key = ? AND cli_access_key_iv IS NOT NULL AND cli_access_enabled = 1",
                (cli_key_enc,)
            ).fetchone()
        return self._row_to_conn(row) if row else None

    def add(self, c: Connection) -> Connection:
        if not c.id:
            c.id = str(uuid.uuid4())
        pw_enc, pw_iv = self._encrypt_pw(c.password)
        cli_key_enc, cli_key_iv = (self._encrypt_pw(c.cli_access_key)
                                   if c.cli_access_key else (None, None))
        # CWE-312: Metadaten verschlüsseln; Klartext-Spalten bleiben leer
        name_enc, name_iv = self._encrypt_pw(c.name)
        host_enc, host_iv = self._encrypt_pw(c.host)
        user_enc, user_iv = self._encrypt_pw(c.user)
        path_enc, path_iv = self._encrypt_pw(c.remote_path or "/")
        with get_connection() as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM connections WHERE user_id = ?",
                (self._user.id,)
            ).fetchone()[0]
            c.sort_order = max_order + 1
            conn.execute(
                """INSERT INTO connections
                   (id, user_id, name, host, ssh_user, remote_path, port,
                    auth_method, pw_enc, pw_iv, key_path, putty_key_path, drive_letter,
                    protocol, ftp_implicit_tls, ftp_passive, ftp_verify_cert,
                    sort_order, cli_access_enabled, cli_access_key, cli_access_key_iv,
                    name_enc, name_iv, host_enc, host_iv,
                    ssh_user_enc, ssh_user_iv, remote_path_enc, remote_path_iv,
                    groups, is_template, template_id)
                   VALUES (?, ?, '', '', '', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    c.id, self._user.id, c.port, c.auth_method,
                    pw_enc, pw_iv, c.key_path, c.putty_key_path, c.drive_letter,
                    c.protocol, int(c.ftp_implicit_tls), int(c.ftp_passive),
                    int(c.ftp_verify_cert),
                    c.sort_order, int(c.cli_access_enabled), cli_key_enc, cli_key_iv,
                    name_enc, name_iv, host_enc, host_iv,
                    user_enc, user_iv, path_enc, path_iv,
                    c.groups, int(c.is_template), c.template_id,
                )
            )
        return c

    def update(self, c: Connection) -> bool:
        pw_enc, pw_iv = self._encrypt_pw(c.password)
        cli_key_enc, cli_key_iv = (self._encrypt_pw(c.cli_access_key)
                                   if c.cli_access_key else (None, None))
        # CWE-312: Metadaten verschlüsseln; Klartext-Spalten leeren
        name_enc, name_iv = self._encrypt_pw(c.name)
        host_enc, host_iv = self._encrypt_pw(c.host)
        user_enc, user_iv = self._encrypt_pw(c.user)
        path_enc, path_iv = self._encrypt_pw(c.remote_path or "/")
        with get_connection() as conn:
            result = conn.execute(
                """UPDATE connections SET
                   name='', host='', ssh_user='', remote_path='', port=?,
                   auth_method=?, pw_enc=?, pw_iv=?, key_path=?, putty_key_path=?, drive_letter=?,
                   protocol=?, ftp_implicit_tls=?, ftp_passive=?, ftp_verify_cert=?,
                   cli_access_enabled=?, cli_access_key=?, cli_access_key_iv=?,
                   name_enc=?, name_iv=?, host_enc=?, host_iv=?,
                   ssh_user_enc=?, ssh_user_iv=?, remote_path_enc=?, remote_path_iv=?,
                   groups=?, is_template=?, template_id=?
                   WHERE id=? AND user_id=?""",
                (c.port, c.auth_method, pw_enc, pw_iv,
                 c.key_path, c.putty_key_path, c.drive_letter,
                 c.protocol, int(c.ftp_implicit_tls), int(c.ftp_passive),
                 int(c.ftp_verify_cert),
                 int(c.cli_access_enabled), cli_key_enc, cli_key_iv,
                 name_enc, name_iv, host_enc, host_iv,
                 user_enc, user_iv, path_enc, path_iv,
                 c.groups, int(c.is_template), c.template_id,
                 c.id, self._user.id)
            )
        return result.rowcount > 0

    def delete(self, conn_id: str) -> bool:
        with get_connection() as conn:
            result = conn.execute(
                "DELETE FROM connections WHERE id=? AND user_id=?",
                (conn_id, self._user.id)
            )
        return result.rowcount > 0

    # ------------------------------------------------------------------
    # Einstellungen
    # ------------------------------------------------------------------

    def get_settings(self) -> AppSettings:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM app_settings WHERE user_id = ?",
                (self._user.id,)
            ).fetchone()
        if not row:
            return AppSettings()
        auto_reconnect = bool(row["auto_reconnect"]) if "auto_reconnect" in row.keys() else True
        return AppSettings(
            start_with_windows=bool(row["start_with_windows"]),
            minimize_to_tray=bool(row["minimize_to_tray"]),
            check_interval_seconds=row["check_interval_seconds"],
            debug_mode=bool(row["debug_mode"]),
            require_admin=bool(row["require_admin"]),
            terminal_client=(row["terminal_client"] if "terminal_client" in row.keys() and row["terminal_client"] else "ssh"),
            use_putty=(row["terminal_client"] == "putty") if "terminal_client" in row.keys() and row["terminal_client"] else bool(row["use_putty"]),
            putty_path=row["putty_path"] or "",
            auto_login=bool(row["auto_login"]) if "auto_login" in row.keys() else False,
            auto_reconnect=auto_reconnect,
            auto_reconnect_mounts=auto_reconnect,
            auto_remount_on_lost=bool(row["auto_remount_on_lost"]) if "auto_remount_on_lost" in row.keys() else True,
            language=(row["language"] if "language" in row.keys() and row["language"] else "en"),
            theme=(row["theme"] if "theme" in row.keys() and row["theme"] else "dark"),
            security_level=row["security_level"] if "security_level" in row.keys() else 0,
            allow_passwordless_key_auth=bool(row["allow_passwordless_key_auth"]) if "allow_passwordless_key_auth" in row.keys() else False,
            allow_insecure_password_auth=bool(row["allow_insecure_password_auth"]) if "allow_insecure_password_auth" in row.keys() else False,
            telemetry_enabled=bool(row["telemetry_enabled"]) if "telemetry_enabled" in row.keys() else False,
            telemetry_prompt_shown=bool(row["telemetry_prompt_shown"]) if "telemetry_prompt_shown" in row.keys() else False,
            sshfs_disable_cache=bool(row["sshfs_disable_cache"]) if "sshfs_disable_cache" in row.keys() else False,
        )

    def save_settings(self, s: AppSettings) -> None:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO app_settings
                   (user_id, start_with_windows, minimize_to_tray,
                    check_interval_seconds, debug_mode, require_admin,
                    use_putty, putty_path, terminal_client, auto_login, auto_reconnect, language, theme,
                    security_level, allow_passwordless_key_auth, allow_insecure_password_auth,
                    auto_remount_on_lost, telemetry_enabled, telemetry_prompt_shown,
                    sshfs_disable_cache,
                    updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                   ON CONFLICT(user_id) DO UPDATE SET
                     start_with_windows=excluded.start_with_windows,
                     minimize_to_tray=excluded.minimize_to_tray,
                     check_interval_seconds=excluded.check_interval_seconds,
                     debug_mode=excluded.debug_mode,
                     require_admin=excluded.require_admin,
                     use_putty=excluded.use_putty,
                     putty_path=excluded.putty_path,
                     terminal_client=excluded.terminal_client,
                     auto_login=excluded.auto_login,
                     auto_reconnect=excluded.auto_reconnect,
                     language=excluded.language,
                     theme=excluded.theme,
                     security_level=excluded.security_level,
                     allow_passwordless_key_auth=excluded.allow_passwordless_key_auth,
                     allow_insecure_password_auth=excluded.allow_insecure_password_auth,
                     auto_remount_on_lost=excluded.auto_remount_on_lost,
                     telemetry_enabled=excluded.telemetry_enabled,
                     telemetry_prompt_shown=excluded.telemetry_prompt_shown,
                     sshfs_disable_cache=excluded.sshfs_disable_cache,
                     updated_at=excluded.updated_at""",
                (self._user.id,
                 int(s.start_with_windows), int(s.minimize_to_tray),
                 s.check_interval_seconds, int(s.debug_mode),
                 int(s.require_admin), int(s.use_putty), s.putty_path,
                 getattr(s, "terminal_client", "ssh") or "ssh",
                 int(s.auto_login), int(bool(getattr(s, "auto_reconnect", False) or getattr(s, "auto_reconnect_mounts", False))), s.language, s.theme,
                 int(s.security_level),
                 int(s.allow_passwordless_key_auth), int(s.allow_insecure_password_auth),
                 int(bool(getattr(s, "auto_remount_on_lost", True))),
                 int(bool(getattr(s, "telemetry_enabled", False))),
                 int(bool(getattr(s, "telemetry_prompt_shown", False))),
                 int(bool(getattr(s, "sshfs_disable_cache", False))))
            )

    # Backwards-compatible alias used by main.py
    def update_settings(self, s: AppSettings) -> None:
        self.save_settings(s)

    # ------------------------------------------------------------------
    # Active Mounts Tracking (für Auto-Reconnect)
    # ------------------------------------------------------------------

    def add_active_mount(self, conn_id: str) -> None:
        """Markiert eine Verbindung als aktiv gemountet."""
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO active_mounts (user_id, conn_id)
                   VALUES (?, ?)
                   ON CONFLICT(user_id, conn_id) DO UPDATE SET
                   mounted_at = datetime('now')""",
                (self._user.id, conn_id)
            )

    def remove_active_mount(self, conn_id: str) -> None:
        """Entfernt eine Verbindung aus den aktiven Mounts."""
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM active_mounts WHERE user_id = ? AND conn_id = ?",
                (self._user.id, conn_id)
            )

    def get_active_mounts(self) -> List[str]:
        """Gibt Liste der aktiven Connection IDs zurück."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT conn_id FROM active_mounts WHERE user_id = ?",
                (self._user.id,)
            ).fetchall()
        return [r["conn_id"] for r in rows]

    def clear_all_active_mounts(self) -> None:
        """Löscht alle aktiven Mounts (beim Logout)."""
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM active_mounts WHERE user_id = ?",
                (self._user.id,)
            )
