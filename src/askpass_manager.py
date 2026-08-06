import uuid
import threading
import time
from src.utils.secure_memory import SecureBytes

# Store for one-time tokens
# token -> {"password": SecureBytes, "created_at": float}
_tokens: dict = {}
_lock = threading.Lock()

# Expiry for tokens (helper should be fast)
TOKEN_EXPIRY_SEC = 30.0

def create_token(password: str) -> str:
    """Creates a new one-time token for a password. Stores it as SecureBytes."""
    token = str(uuid.uuid4())
    with _lock:
        _tokens[token] = {
            "password": SecureBytes.from_string(password),
            "created_at": time.time()
        }
    return token

def consume_token(token: str) -> str | None:
    """Retrieves and deletes a password for a given token. Wipes SecureBytes after use."""
    _cleanup_expired()
    with _lock:
        if token in _tokens:
            entry = _tokens.pop(token)
            secure: SecureBytes = entry["password"]
            result = secure.decode()
            secure.wipe()
            return result
    return None

def _cleanup_expired():
    """Removes tokens that were not consumed within the threshold."""
    now = time.time()
    with _lock:
        to_delete = [
            t for t, data in _tokens.items()
            if now - data["created_at"] > TOKEN_EXPIRY_SEC
        ]
        for t in to_delete:
            secure: SecureBytes = _tokens[t]["password"]
            secure.wipe()
            del _tokens[t]
