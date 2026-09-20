"""
Security tests for NeoSSHWinManager.
Tests for:
1. Command injection prevention
2. Password encryption/decryption
3. Secure memory handling
4. Key derivation (PBKDF2 and Argon2)
5. Input validation
"""

import sys
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils.secure_memory import SecureBytes, secure_wipe_bytes, secure_compare
from src.ssh_launcher import _is_safe_ssh_identifier, _is_safe_file_path

# Import crypto functions from crypto.py
try:
    from src.crypto import (
        derive_key_argon2,
        derive_key_pbkdf2_secure,
        store_key_in_credential_manager,
        retrieve_key_from_credential_manager,
        is_keyring_available,
        encrypt,
        decrypt,
        generate_enc_key,
        SecureCrypto,
        KeyManager,
        generate_secure_random,
    )
    _CRYPTO_AVAILABLE = True
except ImportError as e:
    _CRYPTO_AVAILABLE = False
    print(f"Crypto import error: {e}")


class TestCommandInjectionPrevention:
    """Tests for command injection vulnerabilities."""
    
    def test_safe_hostname_valid(self):
        """Test that valid hostnames are accepted."""
        assert _is_safe_ssh_identifier("example.com") is True
        assert _is_safe_ssh_identifier("192.168.1.1") is True
        assert _is_safe_ssh_identifier("server-01") is True
        assert _is_safe_ssh_identifier("user@host") is True
    
    def test_safe_hostname_invalid_with_semicolon(self):
        """Test that hostnames with semicolon are rejected (command injection)."""
        assert _is_safe_ssh_identifier("example.com; rm -rf /") is False
        assert _is_safe_ssh_identifier("host;whoami") is False
    
    def test_safe_hostname_invalid_with_pipe(self):
        """Test that hostnames with pipe are rejected."""
        assert _is_safe_ssh_identifier("example.com | cat /etc/passwd") is False
    
    def test_safe_hostname_invalid_with_backticks(self):
        """Test that hostnames with backticks are rejected."""
        assert _is_safe_ssh_identifier("host`whoami`") is False
    
    def test_safe_hostname_invalid_with_dollar(self):
        """Test that hostnames with dollar sign are rejected."""
        assert _is_safe_ssh_identifier("host$USER") is False
    
    def test_safe_hostname_invalid_with_ampersand(self):
        """Test that hostnames with ampersand are rejected."""
        assert _is_safe_ssh_identifier("host && whoami") is False
    
    def test_safe_file_path_traversal(self):
        """Test that path traversal is rejected."""
        assert _is_safe_file_path("../../../etc/passwd") is False
        assert _is_safe_file_path("..\\windows\\system32") is False
    
    def test_safe_file_path_valid(self):
        """Test that valid file paths are accepted."""
        assert _is_safe_file_path("C:\\Users\\test\\key.pem") is True
        assert _is_safe_file_path("/home/user/.ssh/id_rsa") is True
    
    def test_safe_file_path_with_shell_chars(self):
        """Test that paths with shell metacharacters are rejected."""
        assert _is_safe_file_path("/path;rm -rf /") is False
        assert _is_safe_file_path("/path|cat /etc/passwd") is False


class TestSecureMemory:
    """Tests for secure memory handling."""
    
    def test_secure_bytes_creation(self):
        """Test SecureBytes can be created from strings and bytes."""
        sb1 = SecureBytes.from_string("test password")
        assert len(sb1) == 13
        
        sb2 = SecureBytes(b"test bytes")
        assert len(sb2) == 10
    
    def test_secure_bytes_wipe(self):
        """Test that SecureBytes wipes data properly."""
        sb = SecureBytes(b"secret123")
        assert not sb.is_empty()
        sb.wipe()
        assert sb.is_empty()
        assert sb._data is None
    
    def test_secure_bytes_context_manager(self):
        """Test SecureBytes works as context manager."""
        with SecureBytes(b"secret") as sb:
            assert not sb.is_empty()
        # After exiting context, should be wiped
        assert sb.is_empty()
    
    def test_secure_bytes_get_bytes(self):
        """Test getting bytes from SecureBytes."""
        sb = SecureBytes(b"test")
        result = sb.get_bytes()
        assert result == b"test"
    
    def test_secure_bytes_decode(self):
        """Test decoding SecureBytes to string."""
        sb = SecureBytes.from_string("hello")
        result = sb.decode()
        assert result == "hello"


class TestCryptoFunctions:
    """Tests for cryptographic functions."""
    
    def test_generate_secure_random(self):
        """Test secure random generation."""
        r1 = generate_secure_random(32)
        r2 = generate_secure_random(32)
        assert len(r1) == 32
        assert len(r2) == 32
        assert r1 != r2  # Should be different each time
    
    def test_secure_compare_equal(self):
        """Test constant-time comparison with equal bytes."""
        a = b"test123"
        b = b"test123"
        assert secure_compare(a, b) is True
    
    def test_secure_compare_unequal(self):
        """Test constant-time comparison with unequal bytes."""
        a = b"test123"
        b = b"test456"
        assert secure_compare(a, b) is False
    
    def test_secure_compare_different_length(self):
        """Test constant-time comparison with different length."""
        a = b"short"
        b = b"longer string"
        assert secure_compare(a, b) is False
    
    def test_key_manager_derive_pbkdf2(self):
        """Test PBKDF2 key derivation."""
        km = KeyManager()
        password = SecureBytes.from_string("master_password_123")
        
        key, salt = km.initialize_with_password(password, use_argon2=False)
        
        assert len(key) == 32  # 256 bits
        assert len(salt) == 32  # 256 bits
        assert key is not None
        
        password.wipe()
    
    def test_key_manager_verify_correct_password(self):
        """Test password verification with correct password."""
        km = KeyManager()
        password = SecureBytes.from_string("correct_password")
        
        key, salt = km.initialize_with_password(password, use_argon2=False)
        
        # Verify with same password
        verify_pw = SecureBytes.from_string("correct_password")
        assert km.verify_password(verify_pw, salt, use_argon2=False) is True
        
        password.wipe()
        verify_pw.wipe()
    
    def test_key_manager_verify_wrong_password(self):
        """Test password verification with wrong password."""
        km = KeyManager()
        password = SecureBytes.from_string("correct_password")
        
        key, salt = km.initialize_with_password(password, use_argon2=False)
        
        # Verify with wrong password
        wrong_pw = SecureBytes.from_string("wrong_password")
        assert km.verify_password(wrong_pw, salt, use_argon2=False) is False
        
        password.wipe()
        wrong_pw.wipe()
    
    def test_key_manager_derive_connection_key(self):
        """Test deriving unique keys per connection."""
        km = KeyManager()
        password = SecureBytes.from_string("master_password")
        
        km.initialize_with_password(password, use_argon2=False)
        
        key1 = km.derive_connection_key("conn_001")
        key2 = km.derive_connection_key("conn_002")
        key3 = km.derive_connection_key("conn_001")  # Same as key1
        
        # Different connections should have different keys
        assert key1 != key2
        # Same connection should derive same key
        assert key1 == key3
        
        password.wipe()
    
    def test_encrypt_decrypt_data(self):
        """Test encryption and decryption with unique IV."""
        km = KeyManager()
        password = SecureBytes.from_string("master_password")
        
        key, salt = km.initialize_with_password(password, use_argon2=False)
        
        # Encrypt data
        plaintext = SecureBytes.from_string("sensitive data here")
        encrypted = SecureCrypto.encrypt_data(plaintext, key)
        
        # Encrypted should include IV (12 bytes) + ciphertext
        assert len(encrypted) > 12
        
        # Decrypt data
        decrypted = SecureCrypto.decrypt_data(encrypted, key)
        assert decrypted.decode() == "sensitive data here"
        
        password.wipe()
        plaintext.wipe()
        decrypted.wipe()
    
    def test_encrypt_unique_iv_per_encryption(self):
        """Test that each encryption produces unique IV and ciphertext."""
        km = KeyManager()
        password = SecureBytes.from_string("master_password")
        
        key, salt = km.initialize_with_password(password, use_argon2=False)
        
        # Encrypt same data twice
        plaintext = SecureBytes.from_string("same data")
        encrypted1 = SecureCrypto.encrypt_data(plaintext, key)
        encrypted2 = SecureCrypto.encrypt_data(plaintext, key)
        
        # Should be different (due to unique IV)
        assert encrypted1 != encrypted2
        
        # But both should decrypt to same plaintext
        decrypted1 = SecureCrypto.decrypt_data(encrypted1, key)
        decrypted2 = SecureCrypto.decrypt_data(encrypted2, key)
        assert decrypted1.decode() == decrypted2.decode()
        
        password.wipe()
        plaintext.wipe()
        decrypted1.wipe()
        decrypted2.wipe()


class TestDatabaseSecurity:
    """Tests for database security."""

    def test_database_path_secure(self):
        """Test that database is created in secure location."""
        from src.database import get_db_path
        db_path = get_db_path()

        appdata = os.environ.get("APPDATA", str(os.path.expanduser("~")))
        assert str(db_path).startswith(appdata) or str(db_path).startswith(os.path.expanduser("~"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-ACL only")
class TestWindowsACL:
    """Tests for Windows ACL enforcement on the database file (CWE-732)."""

    # ── Rights the owner ACE must carry ──────────────────────────────────
    # Regression guard for GitHub issue #22: 1.4.0–1.5.5 granted the owner
    # FILE_GENERIC_READ | FILE_GENERIC_WRITE, which omits these three. Without
    # FILE_TRAVERSE the data folder cannot be opened at all on installs that do
    # not grant SeChangeNotifyPrivilege; without DELETE SQLite cannot clean up
    # its -wal/-shm sidecars; without WRITE_DAC the next start cannot repair the
    # ACL it just wrote. The result was a permanent startup crash.
    REQUIRED_RIGHTS = ("FILE_TRAVERSE", "DELETE", "WRITE_DAC")

    def _get_dacl_sid_strings(self, path: str) -> set:
        """Returns set of SID strings with ACCESS_ALLOWED ACEs on path."""
        import win32security
        sd = win32security.GetFileSecurity(path, win32security.DACL_SECURITY_INFORMATION)
        dacl = sd.GetSecurityDescriptorDacl()
        sids = set()
        if dacl is None:
            return sids
        for i in range(dacl.GetAceCount()):
            ace = dacl.GetAce(i)
            ace_type = ace[0][0]
            if ace_type == win32security.ACCESS_ALLOWED_ACE_TYPE:
                sids.add(win32security.ConvertSidToStringSid(ace[2]))
        return sids

    def _get_ace(self, path: str, sid_str: str):
        """Returns (flags, mask) of the ACCESS_ALLOWED ACE for sid_str, or None."""
        import win32security
        sd = win32security.GetFileSecurity(path, win32security.DACL_SECURITY_INFORMATION)
        dacl = sd.GetSecurityDescriptorDacl()
        for i in range(dacl.GetAceCount()):
            (ace_type, flags), mask, sid = dacl.GetAce(i)
            if (ace_type == win32security.ACCESS_ALLOWED_ACE_TYPE
                    and win32security.ConvertSidToStringSid(sid) == sid_str):
                return flags, mask
        return None

    def _current_sid_str(self) -> str:
        import win32security
        from src.database import current_user_sid
        return win32security.ConvertSidToStringSid(current_user_sid())

    def test_acl_grants_only_current_user_and_system(self):
        """After _set_secure_permissions only the owner and SYSTEM remain."""
        from src.database import _set_secure_permissions

        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            tmp_path = f.name
        try:
            _set_secure_permissions(tmp_path)

            sids = self._get_dacl_sid_strings(tmp_path)
            assert sids == {self._current_sid_str(), "S-1-5-18"}, (
                f"DACL sollte nur Eigentümer + SYSTEM enthalten, hat: {sids}"
            )
        finally:
            os.unlink(tmp_path)

    def test_acl_no_world_access(self):
        """Everyone/World SID (S-1-1-0) must not appear in the DACL."""
        from src.database import _set_secure_permissions

        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            tmp_path = f.name
        try:
            _set_secure_permissions(tmp_path)

            sids = self._get_dacl_sid_strings(tmp_path)
            # S-1-1-0 ist der universelle "Everyone"-SID auf Windows
            assert "S-1-1-0" not in sids, f"Everyone-SID S-1-1-0 darf nicht in der DACL stehen, gefunden: {sids}"
        finally:
            os.unlink(tmp_path)

    def test_owner_ace_keeps_traverse_delete_and_write_dac(self):
        """Issue #22: the owner ACE must not be missing rights the app needs."""
        import ntsecuritycon as con
        from src.database import _set_secure_permissions

        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            tmp_path = f.name
        try:
            _set_secure_permissions(tmp_path)

            ace = self._get_ace(tmp_path, self._current_sid_str())
            assert ace is not None, "Kein ACE für den aktuellen Benutzer"
            _flags, mask = ace
            for right in self.REQUIRED_RIGHTS:
                bit = getattr(con, right)
                assert mask & bit, (
                    f"{right} fehlt in der Eigentümer-Maske 0x{mask:08X} — "
                    "genau das hat in 1.4.0–1.5.5 den Datenordner blockiert."
                )
        finally:
            os.unlink(tmp_path)

    def test_directory_ace_is_inheritable(self):
        """Issue #22: files created later must inherit the same access."""
        import ntsecuritycon as con
        from src.database import _set_secure_permissions

        tmp_dir = tempfile.mkdtemp(prefix="acl_dir_")
        try:
            _set_secure_permissions(tmp_dir)

            ace = self._get_ace(tmp_dir, self._current_sid_str())
            assert ace is not None, "Kein ACE für den aktuellen Benutzer"
            flags, _mask = ace
            assert flags & con.OBJECT_INHERIT_ACE, "OBJECT_INHERIT_ACE fehlt am Ordner-ACE"
            assert flags & con.CONTAINER_INHERIT_ACE, "CONTAINER_INHERIT_ACE fehlt am Ordner-ACE"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_hardened_directory_can_still_open_a_database(self):
        """Issue #22 end-to-end: hardening must not break SQLite in that folder."""
        import sqlite3
        from src.database import _set_secure_permissions

        tmp_dir = tempfile.mkdtemp(prefix="acl_db_")
        try:
            db_file = os.path.join(tmp_dir, "data.db")
            _set_secure_permissions(tmp_dir)

            conn = sqlite3.connect(db_file)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.commit()
            conn.close()

            _set_secure_permissions(db_file)
            conn = sqlite3.connect(db_file)
            conn.execute("INSERT INTO t VALUES (1)")
            conn.commit()
            conn.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_acl_rolls_back_when_it_would_lock_us_out(self):
        """Issue #22: hardening that costs us access must be undone, not kept."""
        import win32security
        from src.database import _set_secure_permissions, _is_usable

        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            tmp_path = f.name
        try:
            before = self._get_dacl_sid_strings(tmp_path)
            # Harden for somebody else — the exact shape of the reported bug.
            foreign = win32security.ConvertStringSidToSid("S-1-5-19")  # LOCAL SERVICE
            _set_secure_permissions(tmp_path, user_sid=foreign)

            assert _is_usable(Path(tmp_path)), "Datei nach Rücknahme immer noch gesperrt"
            assert self._get_dacl_sid_strings(tmp_path) == before, (
                "Vorherige DACL wurde nicht wiederhergestellt"
            )
        finally:
            os.unlink(tmp_path)

    def test_acl_uses_token_sid_not_username_env(self, monkeypatch):
        """Issue #22: USERNAME is a guess; the process token is the truth."""
        from src.database import _set_secure_permissions

        monkeypatch.delenv("USERNAME", raising=False)
        monkeypatch.delenv("USER", raising=False)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            tmp_path = f.name
        try:
            _set_secure_permissions(tmp_path)
            assert self._current_sid_str() in self._get_dacl_sid_strings(tmp_path)
        finally:
            os.unlink(tmp_path)

    def test_acl_raises_when_sid_undeterminable(self, monkeypatch):
        """A SID we cannot determine at all must raise, not harden blindly."""
        import src.database as db

        monkeypatch.setattr(db, "current_user_sid", lambda: None)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            tmp_path = f.name
        try:
            with pytest.raises(RuntimeError, match="ACL-Setzung fehlgeschlagen"):
                db._set_secure_permissions(tmp_path)
        finally:
            os.unlink(tmp_path)

    def test_acl_raises_on_nonexistent_file(self):
        """Calling _set_secure_permissions on a missing file must raise, not pass silently."""
        from src.database import _set_secure_permissions

        nonexistent = os.path.join(tempfile.gettempdir(), "does_not_exist_12345.db")
        with pytest.raises(Exception):
            _set_secure_permissions(nonexistent)

    def test_init_db_sets_acl_on_new_database(self):
        """init_db() on a fresh database must leave the file owner-only accessible."""
        from src.database import get_db_path, init_db

        init_db()
        db_path = str(get_db_path())

        sids = self._get_dacl_sid_strings(db_path)
        assert len(sids) >= 1, "DACL nach init_db() ist leer"
        assert self._current_sid_str() in sids, (
            f"Eigentümer-SID nach init_db() nicht in DACL: {sids}"
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-ACL only")
class TestPermissionRepair:
    """GitHub issue #22: a data folder the app locked itself out of must heal."""

    def _lock_out(self, *paths):
        """Applies the 1.4.0–1.5.5 DACL, but for a SID that is not ours."""
        import ntsecuritycon as con
        import win32security
        foreign = win32security.ConvertStringSidToSid("S-1-5-19")  # LOCAL SERVICE
        for p in paths:
            sd = win32security.GetFileSecurity(
                str(p), win32security.DACL_SECURITY_INFORMATION
            )
            dacl = win32security.ACL()
            dacl.AddAccessAllowedAce(
                win32security.ACL_REVISION,
                con.FILE_GENERIC_READ | con.FILE_GENERIC_WRITE,
                foreign,
            )
            sd.SetSecurityDescriptorDacl(1, dacl, 0)
            win32security.SetFileSecurity(
                str(p), win32security.DACL_SECURITY_INFORMATION, sd
            )

    def test_locked_folder_is_detected(self):
        from src.permission_repair import is_accessible

        tmp_dir = Path(tempfile.mkdtemp(prefix="repair_"))
        try:
            (tmp_dir / "data.db").write_bytes(b"")
            assert is_accessible(tmp_dir)
            self._lock_out(tmp_dir, tmp_dir / "data.db")
            assert not is_accessible(tmp_dir)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_startup_check_heals_without_prompting(self, monkeypatch):
        """We own the files, so WRITE_DAC is implicit: no UAC, no dialog."""
        import sqlite3
        import src.permission_repair as pr

        prompts = []
        monkeypatch.setattr(
            pr, "request_elevated_repair", lambda *a, **k: prompts.append("uac") or True
        )

        tmp_dir = Path(tempfile.mkdtemp(prefix="repair_"))
        try:
            (tmp_dir / "data.db").write_bytes(b"")
            self._lock_out(tmp_dir, tmp_dir / "data.db")

            pr.run_startup_check(tmp_dir)

            assert prompts == [], "Selbstheilbarer Fall darf keine Elevation anfordern"
            assert pr.is_accessible(tmp_dir)
            sqlite3.connect(str(tmp_dir / "data.db")).close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_startup_check_is_silent_on_healthy_folder(self, monkeypatch):
        import src.permission_repair as pr
        from src.database import _set_secure_permissions

        touched = []
        monkeypatch.setattr(
            pr, "request_elevated_repair", lambda *a, **k: touched.append("uac") or True
        )
        monkeypatch.setattr(
            pr, "repair_owner", lambda *a, **k: touched.append("repair") or True
        )

        tmp_dir = Path(tempfile.mkdtemp(prefix="repair_"))
        try:
            (tmp_dir / "data.db").write_bytes(b"")
            _set_secure_permissions(tmp_dir)
            _set_secure_permissions(tmp_dir / "data.db")

            pr.run_startup_check(tmp_dir)
            assert touched == [], "Gesunder Ordner darf keine Reparatur auslösen"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_unlistable_folder_does_not_raise(self):
        """A folder we cannot even enumerate must not blow up the startup check."""
        import src.permission_repair as pr

        tmp_dir = Path(tempfile.mkdtemp(prefix="repair_"))
        try:
            (tmp_dir / "data.db").write_bytes(b"")
            self._lock_out(tmp_dir, tmp_dir / "data.db")
            assert pr._children(tmp_dir) == []
            pr.run_startup_check(tmp_dir)   # must not raise
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestBruteForceProtection:
    """CWE-307: Tier-based brute-force rate limiting on app login."""

    def setup_method(self):
        import src.auth_manager as am
        am._login_attempts.clear()

    def test_lockout_schedule_tier1(self):
        """5 failures → 30s lockout."""
        from src.auth_manager import _lockout_for_count
        assert _lockout_for_count(5) == 30

    def test_lockout_schedule_tier2(self):
        """15 total failures → 10 min lockout."""
        from src.auth_manager import _lockout_for_count
        assert _lockout_for_count(15) == 600

    def test_lockout_schedule_tier3(self):
        """20 total failures → 1h lockout."""
        from src.auth_manager import _lockout_for_count
        assert _lockout_for_count(20) == 3600

    def test_lockout_schedule_tier4(self):
        """23 total failures → 24h lockout."""
        from src.auth_manager import _lockout_for_count
        assert _lockout_for_count(23) == 86400

    def test_lockout_schedule_beyond(self):
        """25+ failures (every 2) → 7-day lockout."""
        from src.auth_manager import _lockout_for_count
        assert _lockout_for_count(25) == 604800
        assert _lockout_for_count(27) == 604800
        assert _lockout_for_count(26) == 0   # mid-tier: no lockout yet

    def test_no_lockout_mid_tier(self):
        """Failures within a tier don't trigger lockout."""
        from src.auth_manager import _lockout_for_count
        for c in (1, 2, 3, 4, 6, 7, 14, 16, 19, 21, 22, 24):
            assert _lockout_for_count(c) == 0, f"count={c} sollte keine Sperre auslösen"

    def test_raises_login_locked_error_at_tier_boundary(self):
        """Hitting a tier boundary raises LoginLockedError."""
        from src.auth_manager import AuthManager, LoginLockedError, _LOCKOUT_SCHEDULE
        import src.auth_manager as am
        username = "__tier_boundary_test__"
        tier1_attempts = _LOCKOUT_SCHEDULE[0][0]  # = 5
        for _ in range(tier1_attempts - 1):
            result = AuthManager.authenticate(username, "wrong")
            assert result is None   # still within tier, no exception
        with pytest.raises(LoginLockedError) as exc_info:
            AuthManager.authenticate(username, "wrong")
        assert exc_info.value.seconds_remaining > 0

    def test_already_locked_raises_with_remaining_time(self):
        """A locked account raises LoginLockedError on re-attempt."""
        import src.auth_manager as am
        from src.auth_manager import AuthManager, LoginLockedError, _LOCKOUT_SCHEDULE
        username = "__already_locked__"
        tier1_attempts = _LOCKOUT_SCHEDULE[0][0]
        for _ in range(tier1_attempts):
            try:
                AuthManager.authenticate(username, "wrong")
            except LoginLockedError:
                pass
        with pytest.raises(LoginLockedError) as exc:
            AuthManager.authenticate(username, "wrong")
        assert exc.value.seconds_remaining > 0

    def test_counter_reset_on_success(self, monkeypatch):
        import src.auth_manager as am
        from src.auth_manager import _login_attempts
        username = "testuser"
        _login_attempts[username.lower()] = {"count": 3, "locked_until": 0.0}

        def fake_get_connection():
            class FakeConn:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def execute(self, *a, **kw):
                    class Row:
                        def keys(self): return ["id", "username", "pw_hash", "pw_salt", "enc_key_enc", "enc_key_iv", "enc_key_kdf", "is_admin"]
                        def __getitem__(self, k):
                            return {"id": "u1", "username": username, "pw_hash": "x", "pw_salt": "s",
                                    "enc_key_enc": "e", "enc_key_iv": "i", "enc_key_kdf": "pbkdf2",
                                    "is_admin": 0}.get(k, "")
                        def fetchone(self): return self
                    return Row()
            return FakeConn()

        monkeypatch.setattr(am, "get_connection", fake_get_connection)
        monkeypatch.setattr(am, "verify_password", lambda *a: True)
        monkeypatch.setattr(am, "decrypt_key", lambda *a, **kw: b"\x00" * 32)

        class FakeMgr:
            def migrate_cli_keys(self): pass
            def migrate_metadata_encryption(self): pass

        monkeypatch.setattr(am, "UserConnectionManager", lambda u: FakeMgr())

        am.AuthManager.authenticate(username, "correct")
        assert username.lower() not in am._login_attempts


class TestSessionLock:
    """CWE-362: Session enc_key update is thread-safe."""

    def test_update_enc_key_correct_user(self):
        from src.auth_manager import Session, AppUser
        user = AppUser(id="u1", username="alice", is_admin=False, _enc_key=b"\x00" * 32)
        Session.login(user)
        new_key = b"\xff" * 32
        Session.update_enc_key("u1", new_key)
        assert Session.current()._enc_key == new_key
        Session.logout()

    def test_update_enc_key_wrong_user_ignored(self):
        from src.auth_manager import Session, AppUser
        original_key = b"\xaa" * 32
        user = AppUser(id="u1", username="bob", is_admin=False, _enc_key=original_key)
        Session.login(user)
        Session.update_enc_key("u2", b"\xbb" * 32)
        assert Session.current()._enc_key == original_key
        Session.logout()

    def test_concurrent_logout_does_not_crash(self):
        import threading
        from src.auth_manager import Session, AppUser
        user = AppUser(id="u1", username="carol", is_admin=False, _enc_key=b"\x00" * 32)
        Session.login(user)
        errors = []
        def worker():
            try:
                Session.update_enc_key("u1", b"\x01" * 32)
                Session.current()
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        Session.logout()
        assert not errors


class TestCLIKeyStdin:
    """CWE-214: CLI access key must be readable from stdin."""

    def test_stdin_sentinel_triggers_readline(self, monkeypatch, capsys):
        import cli_main, io
        monkeypatch.setattr("sys.stdin", io.StringIO("mySecretKey\n"))

        called_with = []
        def fake_handle(key, exec_cmd=None):
            called_with.append(key)
            return 0

        monkeypatch.setattr(cli_main, "_handle_cli_connect", fake_handle)
        monkeypatch.setattr("sys.argv", ["cli", "--connect-cli", "-"])
        cli_main.main()
        assert called_with == ["mySecretKey"]

    def test_empty_stdin_returns_error(self, monkeypatch, capsys):
        import cli_main, io
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        monkeypatch.setattr("sys.argv", ["cli", "--connect-cli", "-"])
        rc = cli_main.main()
        assert rc == 2


class TestMetadataEncryption:
    """CWE-312: Connection metadata is encrypted at rest."""

    def test_encrypt_decrypt_roundtrip(self):
        from src.crypto import encrypt, decrypt, generate_enc_key
        key = generate_enc_key()
        plaintext = "my-server.example.com"
        enc, iv = encrypt(plaintext, key)
        assert enc != plaintext
        assert decrypt(enc, iv, key) == plaintext

    def test_dec_meta_falls_back_to_plaintext(self):
        from src.auth_manager import UserConnectionManager, AppUser
        from src.crypto import generate_enc_key
        user = AppUser(id="u1", username="x", is_admin=False, _enc_key=generate_enc_key())
        mgr = UserConnectionManager(user)

        class FakeRow:
            def __getitem__(self, k):
                return {"host": "fallback-host", "host_enc": "", "host_iv": ""}.get(k, "")
        assert mgr._dec_meta(FakeRow(), "host_enc", "host_iv", "host") == "fallback-host"

    def test_dec_meta_uses_encrypted_when_iv_present(self):
        from src.auth_manager import UserConnectionManager, AppUser
        from src.crypto import generate_enc_key, encrypt
        key = generate_enc_key()
        user = AppUser(id="u1", username="x", is_admin=False, _enc_key=key)
        mgr = UserConnectionManager(user)
        enc, iv = encrypt("secure-host", key)

        class FakeRow:
            def __getitem__(self, k):
                return {"host": "", "host_enc": enc, "host_iv": iv}.get(k, "")
        assert mgr._dec_meta(FakeRow(), "host_enc", "host_iv", "host") == "secure-host"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
