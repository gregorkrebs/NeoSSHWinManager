"""
pro_manager.py – Pro license validation for NEO SSH-Win Manager.

Architecture:
  - Machine ID: SHA-256 of CPU ProcessorId + disk SerialNumber (via wmic)
  - Pro key format: NEO-XXXX-XXXX-XXXX (uppercase alphanumeric segments)
  - Activation: POST to validation endpoint → server returns HMAC token
  - Token stored locally in pro_licenses table (machine-scoped, not user-scoped)
  - Local check: recompute HMAC-SHA256(machine_id:key_hash, CLIENT_VERIFY_SECRET)
  - Grace: is_pro_active() is purely local — no network on every app start
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import logging
import re
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

PRO_KEY_PATTERN = re.compile(r"^NEO-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")

VALIDATION_ENDPOINT = "https://www.neosshwinmanager.org/neo_pro_validate.php"

# Must match the value in pro.local.php on the server.
# This constant is embedded in the client binary — it is NOT the full server
# secret. Changing it invalidates all previously issued tokens.
CLIENT_VERIFY_SECRET = "NeoSSHWM-ClientVerify-2026"


# ---------------------------------------------------------------------------
# Machine fingerprint
# ---------------------------------------------------------------------------

def generate_machine_id() -> str:
    """
    Returns a 64-char hex SHA-256 digest derived from stable hardware IDs.
    Falls back to username + hostname if WMI is unavailable.
    """
    parts: list[str] = []

    for wmic_args, marker in (
        (["wmic", "cpu", "get", "ProcessorId", "/value"], "ProcessorId="),
        (["wmic", "diskdrive", "get", "SerialNumber", "/value"], "SerialNumber="),
    ):
        try:
            result = subprocess.run(
                wmic_args,
                capture_output=True,
                text=True,
                timeout=6,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            for line in result.stdout.splitlines():
                if marker in line:
                    val = line.split("=", 1)[1].strip()
                    if val:
                        parts.append(val)
                        break
        except Exception as exc:
            logger.debug("wmic call failed: %s", exc)

    if not parts:
        import os, socket
        parts = [os.environ.get("USERNAME", "unknown"), socket.gethostname()]

    combined = "|".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Local HMAC validation
# ---------------------------------------------------------------------------

def _compute_local_token(machine_id: str, key_hash: str) -> str:
    return _hmac.new(
        CLIENT_VERIFY_SECRET.encode("utf-8"),
        f"{machine_id}:{key_hash}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _validate_hmac_locally(machine_id: str, key_hash: str, stored_token: str) -> bool:
    expected = _compute_local_token(machine_id, key_hash)
    return _hmac.compare_digest(expected, stored_token)


# ---------------------------------------------------------------------------
# Database helpers (lazy import to avoid circular imports at module level)
# ---------------------------------------------------------------------------

def _get_db():
    from src.database import get_connection
    return get_connection


def is_pro_active() -> bool:
    """
    Fast local check — no network.
    Returns True only if a valid HMAC token is stored for this machine.
    """
    try:
        machine_id = generate_machine_id()
        get_connection = _get_db()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT pro_key_hash, hmac_token FROM pro_licenses WHERE machine_id = ?",
                (machine_id,),
            ).fetchone()
        if not row:
            return False
        return _validate_hmac_locally(machine_id, row["pro_key_hash"], row["hmac_token"])
    except Exception as exc:
        logger.warning("Pro check failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Activation (network)
# ---------------------------------------------------------------------------

def activate_pro(key: str) -> dict:
    """
    Validates a Pro key against the remote endpoint and stores the token locally.

    Returns:
        {"success": bool, "error": str | None}
    """
    key = key.strip().upper()
    if not PRO_KEY_PATTERN.match(key):
        return {"success": False, "error": "Invalid key format. Expected: NEO-XXXX-XXXX-XXXX"}

    machine_id = generate_machine_id()
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()

    # --- network call ---
    try:
        import urllib.request
        import urllib.error

        payload = json.dumps({"machine_id": machine_id, "key_hash": key_hash}).encode("utf-8")
        req = urllib.request.Request(
            VALIDATION_ENDPOINT,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "NeoSSHWinManager/Pro",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"success": False, "error": f"Network error: {exc}"}

    if not body.get("success"):
        return {"success": False, "error": body.get("error", "Activation failed")}

    token: str = body.get("token", "")
    if not token:
        return {"success": False, "error": "Server returned no token"}

    # --- persist locally ---
    try:
        get_connection = _get_db()
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO pro_licenses (machine_id, pro_key_hash, hmac_token)
                   VALUES (?, ?, ?)
                   ON CONFLICT(machine_id) DO UPDATE SET
                       pro_key_hash = excluded.pro_key_hash,
                       hmac_token   = excluded.hmac_token,
                       last_checked = datetime('now')""",
                (machine_id, key_hash, token),
            )
        logger.info("Pro license activated and stored.")
    except Exception as exc:
        return {"success": False, "error": f"Storage error: {exc}"}

    return {"success": True, "error": None}
