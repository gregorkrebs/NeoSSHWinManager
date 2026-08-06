# crypto.py – Secure Cryptography for NEO SSH-Win Manager.
#
# Passwort-Hashing:  PBKDF2-HMAC-SHA256 (600.000 Iterationen, OWASP 2024)
#                    OR Argon2id (memory-hard, GPU-resistant)
# SSH-Passwortverschlüsselung: AES-256-GCM
#   - Jeder Benutzer hat einen zufälligen 256-bit Encryption Key
#   - Dieser Key wird mit dem abgeleiteten Benutzer-Passwort verschlüsselt
#   - SSH-Passwörter werden mit diesem Key verschlüsselt
#   - Wenn der Benutzer sein App-Passwort ändert, wird nur der Key re-encrypted
#
# SECURITY FIXES:
#   - Added Argon2id key derivation (memory-hard, resistant to GPU/ASIC attacks)
#   - Secure memory handling with SecureBytes
#   - Windows Credential Manager integration via keyring
#
# pip install cryptography keyring

import os
import secrets
import hashlib
import hmac
from typing import Tuple, Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    keyring = None
    _KEYRING_AVAILABLE = False

from src.utils.secure_memory import SecureBytes, secure_wipe_bytes

# PBKDF2-Parameter (OWASP 2024 Empfehlung)
_PBKDF2_ITERATIONS = 600_000
_PBKDF2_HASH = "sha256"
_KEY_LEN = 32  # 256 bit

# Argon2id parameters (memory-hard, GPU-resistant)
_ARGON2_MEMORY_COST = 65536  # 64 MB
_ARGON2_TIME_COST = 3
_ARGON2_PARALLELISM = 4

# Keyring constants
_KEYRING_SERVICE = "NeoSSHWinManager"
_KEYRING_USERNAME = "master_encryption_key"


# ------------------------------------------------------------------
# Passwort-Hashing (für App-Login)
# ------------------------------------------------------------------

def hash_password(password: str) -> Tuple[str, str]:
    """
    Erzeugt einen sicheren Hash des App-Passworts.
    Returns (hash_hex, salt_hex).
    """
    salt = secrets.token_bytes(32)
    pw_hash = hashlib.pbkdf2_hmac(
        _PBKDF2_HASH,
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
        dklen=_KEY_LEN,
    )
    return pw_hash.hex(), salt.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    """Prüft ob ein Passwort mit dem gespeicherten Hash übereinstimmt."""
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)
    actual = hashlib.pbkdf2_hmac(
        _PBKDF2_HASH,
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
        dklen=_KEY_LEN,
    )
    # Timing-safe Vergleich
    return hmac.compare_digest(actual, expected)


def derive_key(password: str, salt_hex: str) -> bytes:
    """
    Leitet einen 256-bit Schlüssel aus dem Passwort ab.
    Wird genutzt um den Encryption Key des Benutzers zu ver-/entschlüsseln.
    """
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac(
        _PBKDF2_HASH,
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
        dklen=_KEY_LEN,
    )


def derive_key_argon2(password: SecureBytes, salt: Optional[bytes] = None) -> Tuple[bytes, bytes]:
    """
    Derive an encryption key using Argon2id (memory-hard function).
    More secure against GPU/ASIC attacks than PBKDF2.
    
    Args:
        password: The master password as SecureBytes
        salt: Optional salt (generated if not provided)
        
    Returns:
        Tuple of (derived_key, salt)
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography nicht installiert.")
    
    if salt is None:
        salt = secrets.token_bytes(32)
    
    password_bytes = password.get_bytes()
    if password_bytes is None:
        raise ValueError("Password cannot be empty")
    
    kdf = Argon2id(
        salt=salt,
        length=_KEY_LEN,
        iterations=_ARGON2_TIME_COST,
        lanes=_ARGON2_PARALLELISM,
        memory_cost=_ARGON2_MEMORY_COST,
    )
    key = kdf.derive(password_bytes)
    
    return key, salt


def derive_key_pbkdf2_secure(password: SecureBytes, salt: Optional[bytes] = None) -> Tuple[bytes, bytes]:
    """
    Derive an encryption key from a password using PBKDF2-HMAC-SHA256.
    Secure version that uses SecureBytes for password handling.
    
    Args:
        password: The master password as SecureBytes
        salt: Optional salt (generated if not provided)
        
    Returns:
        Tuple of (derived_key, salt)
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography nicht installiert.")
    
    if salt is None:
        salt = secrets.token_bytes(32)
    
    password_bytes = password.get_bytes()
    if password_bytes is None:
        raise ValueError("Password cannot be empty")
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
        backend=default_backend()
    )
    key = kdf.derive(password_bytes)
    
    return key, salt


# ------------------------------------------------------------------
# Windows Credential Manager Integration (Keyring)
# ------------------------------------------------------------------

def store_key_in_credential_manager(key_hex: str, username: str = _KEYRING_USERNAME) -> bool:
    """
    Store the encryption key in Windows Credential Manager.
    More secure than storing in the database.
    
    Args:
        key_hex: The encryption key as hex string
        username: The credential username
        
    Returns:
        True if successful, False otherwise
    """
    if not _KEYRING_AVAILABLE:
        return False
    
    try:
        keyring.set_password(_KEYRING_SERVICE, username, key_hex)
        return True
    except Exception:
        return False


def retrieve_key_from_credential_manager(username: str = _KEYRING_USERNAME) -> Optional[str]:
    """
    Retrieve the encryption key from Windows Credential Manager.
    
    Args:
        username: The credential username
        
    Returns:
        The key as hex string, or None if not found
    """
    if not _KEYRING_AVAILABLE:
        return None
    
    try:
        return keyring.get_password(_KEYRING_SERVICE, username)
    except Exception:
        return None


def delete_key_from_credential_manager(username: str = _KEYRING_USERNAME) -> bool:
    """
    Delete the encryption key from Windows Credential Manager.
    
    Args:
        username: The credential username
        
    Returns:
        True if successful, False otherwise
    """
    if not _KEYRING_AVAILABLE:
        return False
    
    try:
        keyring.delete_password(_KEYRING_SERVICE, username)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------
# AES-256-GCM Verschlüsselung (für SSH-Passwörter und Encryption Key)
# ------------------------------------------------------------------

def generate_enc_key() -> bytes:
    """Erzeugt einen neuen zufälligen 256-bit Encryption Key."""
    return secrets.token_bytes(32)


def encrypt(plaintext: str, key: bytes) -> Tuple[str, str]:
    """
    Verschlüsselt einen String mit AES-256-GCM.
    Returns (ciphertext_hex, iv_hex).
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError(
            "cryptography nicht installiert. "
            "Bitte ausführen: pip install cryptography"
        )
    iv = secrets.token_bytes(12)  # 96-bit IV für GCM
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    return ct.hex(), iv.hex()


def decrypt(ciphertext_hex: str, iv_hex: str, key: bytes) -> str:
    """
    Entschlüsselt AES-256-GCM Ciphertext.
    Raises ValueError bei falschem Key (Authentication Tag schlägt fehl).
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography nicht installiert.")
    ct = bytes.fromhex(ciphertext_hex)
    iv = bytes.fromhex(iv_hex)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ct, None).decode("utf-8")


def encrypt_key(enc_key: bytes, password: str, salt_hex: str, kdf: str = 'pbkdf2') -> Tuple[str, str]:
    """Verschlüsselt den Encryption Key mit dem abgeleiteten Passwort-Key.

    Args:
        kdf: 'pbkdf2' (legacy) oder 'argon2' (empfohlen).
    """
    if kdf == 'argon2':
        if not _CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography nicht installiert.")
        salt = bytes.fromhex(salt_hex)
        pw_secure = SecureBytes.from_string(password)
        try:
            derived, _ = derive_key_argon2(pw_secure, salt)
        finally:
            pw_secure.wipe()
    else:
        derived = derive_key(password, salt_hex)
    return encrypt(enc_key.hex(), derived)


def decrypt_key(enc_key_hex: str, iv_hex: str, password: str, salt_hex: str, kdf: str = 'pbkdf2') -> bytes:
    """Entschlüsselt den Encryption Key mit dem abgeleiteten Passwort-Key.

    Args:
        kdf: 'pbkdf2' (legacy) oder 'argon2'.
    """
    if kdf == 'argon2':
        if not _CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography nicht installiert.")
        salt = bytes.fromhex(salt_hex)
        pw_secure = SecureBytes.from_string(password)
        try:
            derived, _ = derive_key_argon2(pw_secure, salt)
        finally:
            pw_secure.wipe()
    else:
        derived = derive_key(password, salt_hex)
    key_hex = decrypt(enc_key_hex, iv_hex, derived)
    return bytes.fromhex(key_hex)


def is_available() -> bool:
    return _CRYPTO_AVAILABLE


def is_keyring_available() -> bool:
    """Check if keyring (Windows Credential Manager) is available."""
    return _KEYRING_AVAILABLE


# ------------------------------------------------------------------
# High-level Crypto Classes (for cleaner API)
# ------------------------------------------------------------------

class SecureCrypto:
    """
    High-level cryptographic interface for secure data encryption.
    Uses AES-256-GCM for authenticated encryption with unique IV per operation.
    """
    
    IV_LENGTH = 12  # 96 bits for GCM (recommended)
    
    @classmethod
    def generate_iv(cls, length: int = IV_LENGTH) -> bytes:
        """Generate a cryptographically secure random IV."""
        return secrets.token_bytes(length)
    
    @classmethod
    def encrypt_data(cls, plaintext: SecureBytes, key: bytes) -> bytes:
        """
        Encrypt data using AES-256-GCM with a unique IV.
        
        Format: [IV (12 bytes)][ciphertext + auth_tag]
        
        Args:
            plaintext: Data to encrypt as SecureBytes
            key: 32-byte encryption key
            
        Returns:
            Encrypted data with IV prepended
        """
        if not _CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography nicht installiert.")
        
        iv = cls.generate_iv()
        aesgcm = AESGCM(key)
        
        data = plaintext.get_bytes()
        if data is None:
            raise ValueError("Data cannot be empty")
        
        ciphertext = aesgcm.encrypt(iv, data, None)
        return iv + ciphertext
    
    @classmethod
    def decrypt_data(cls, encrypted_data: bytes, key: bytes) -> SecureBytes:
        """
        Decrypt data encrypted with encrypt_data.
        
        Args:
            encrypted_data: Encrypted data with IV prepended
            key: 32-byte encryption key
            
        Returns:
            Decrypted data as SecureBytes
        """
        if not _CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography nicht installiert.")
        
        if len(encrypted_data) < cls.IV_LENGTH:
            raise ValueError("Invalid encrypted data: too short")
        
        iv = encrypted_data[:cls.IV_LENGTH]
        ciphertext = encrypted_data[cls.IV_LENGTH:]
        
        aesgcm = AESGCM(key)
        
        try:
            plaintext = aesgcm.decrypt(iv, ciphertext, None)
            return SecureBytes(plaintext)
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}")


class KeyManager:
    """
    Manages encryption keys with secure storage and derivation.
    """
    
    def __init__(self):
        self._master_key: Optional[bytes] = None
        self._key_salt: Optional[bytes] = None
        self._derived_keys: dict = {}
    
    def initialize_with_password(
        self,
        password: SecureBytes,
        salt: Optional[bytes] = None,
        use_argon2: bool = True
    ) -> Tuple[bytes, bytes]:
        """
        Initialize the key manager with a master password.
        
        Args:
            password: Master password
            salt: Optional existing salt
            use_argon2: Use Argon2id instead of PBKDF2
            
        Returns:
            Tuple of (derived_key, salt)
        """
        if use_argon2:
            key, salt = derive_key_argon2(password, salt)
        else:
            key, salt = derive_key_pbkdf2_secure(password, salt)
        
        self._master_key = key
        self._key_salt = salt
        
        return key, salt
    
    def verify_password(
        self,
        password: SecureBytes,
        salt: bytes,
        use_argon2: bool = True
    ) -> bool:
        """
        Verify a master password against the stored salt.
        
        Args:
            password: Password to verify
            salt: Stored salt
            use_argon2: Use Argon2id
            
        Returns:
            True if password is correct
        """
        try:
            if use_argon2:
                key, _ = derive_key_argon2(password, salt)
            else:
                key, _ = derive_key_pbkdf2_secure(password, salt)
            
            if self._master_key is None:
                return False
            
            return hmac.compare_digest(key, self._master_key)
        except Exception:
            return False
    
    def get_master_key(self) -> Optional[bytes]:
        """Get the master key (for internal use only)."""
        return self._master_key
    
    def get_salt(self) -> Optional[bytes]:
        """Get the key derivation salt."""
        return self._key_salt
    
    def derive_connection_key(self, connection_id: str) -> bytes:
        """
        Derive a unique key for a specific connection.
        
        Args:
            connection_id: Unique identifier for the connection
            
        Returns:
            Derived key for the connection
        """
        if self._master_key is None:
            raise ValueError("Master key not initialized")
        
        if connection_id not in self._derived_keys:
            # Use HKDF-like derivation
            hasher = hmac.new(self._master_key, digestmod=hashlib.sha256)
            hasher.update(connection_id.encode('utf-8'))
            hasher.update(b'connection-key-v1')
            self._derived_keys[connection_id] = hasher.digest()
        
        return self._derived_keys[connection_id]
    
    def clear(self) -> None:
        """Clear all keys from memory."""
        if self._master_key is not None:
            key_array = bytearray(self._master_key)
            secure_wipe_bytes(key_array)
            self._master_key = None
        
        for key in self._derived_keys.values():
            key_array = bytearray(key)
            secure_wipe_bytes(key_array)
        
        self._derived_keys.clear()
        self._key_salt = None


def generate_secure_random(length: int = 32) -> bytes:
    """Generate cryptographically secure random bytes."""
    return secrets.token_bytes(length)


def generate_password(length: int = 32) -> SecureBytes:
    """Generate a secure random password."""
    import secrets
    import string
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return SecureBytes.from_string(password)
