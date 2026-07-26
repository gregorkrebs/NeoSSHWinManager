"""
config.py – Data models and path helpers for NEO SSH-Win Manager.

Passwords are stored in the SQLite database, AES-GCM encrypted with a
per-user key.  This module only provides the Connection / AppSettings
data classes and the legacy config-file path (used for the admin-
elevation check in main.py before the DB is initialised).
"""

import json
import os
import uuid
from dataclasses import MISSING, dataclass, field, asdict, fields
from typing import List, Optional, Tuple
from pathlib import Path


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

PROTOCOL_SFTP = "sftp"
PROTOCOL_FTP = "ftp"
PROTOCOL_FTPS = "ftps"
PROTOCOLS = (PROTOCOL_SFTP, PROTOCOL_FTP, PROTOCOL_FTPS)


def default_port(protocol: str, implicit_tls: bool = False) -> int:
    """Standard-Port für ein Protokoll (FTPS implizit: 990, sonst 21 bzw. 22)."""
    if protocol == PROTOCOL_FTPS and implicit_tls:
        return 990
    if protocol in (PROTOCOL_FTP, PROTOCOL_FTPS):
        return 21
    return 22


@dataclass
class Connection:
    name: str
    host: str
    user: str
    remote_path: str = "/"
    port: int = 22
    auth_method: str = "password"   # "password" | "key" | "ask"
    password: str = ""              # runtime only – never written to disk here
    key_path: str = ""
    putty_key_path: str = ""        # .ppk format key for PuTTY/plink
    drive_letter: str = "Z:"
    protocol: str = PROTOCOL_SFTP   # "sftp" | "ftp" | "ftps"
    ftp_implicit_tls: bool = False  # ftps only: implicit TLS (990) statt AUTH TLS
    ftp_passive: bool = True        # FTP passive mode (Standard, firewall-freundlich)
    ftp_verify_cert: bool = True    # ftps only: Serverzertifikat prüfen
    cli_access_enabled: bool = False
    cli_access_key: Optional[str] = None
    groups: str = ""                # Kommaseparierte Gruppen/Tags
    is_template: bool = False       # True = Template, False = normale Verbindung
    template_id: Optional[str] = None  # Referenz zu Template
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def is_ftp(self) -> bool:
        """True für FTP und FTPS – Verbindungen ohne SSH/SFTP-Fähigkeiten."""
        return self.protocol in (PROTOCOL_FTP, PROTOCOL_FTPS)

    @property
    def protocol_label(self) -> str:
        """Kurzbezeichnung für UI-Badges."""
        if self.protocol == PROTOCOL_FTPS:
            return "FTPS"
        if self.protocol == PROTOCOL_FTP:
            return "FTP"
        return "SFTP"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Connection":
        values = {}
        for field_info in fields(cls):
            if field_info.name in data:
                values[field_info.name] = data[field_info.name]
            elif field_info.default is not MISSING:
                values[field_info.name] = field_info.default
            elif field_info.default_factory is not MISSING:
                values[field_info.name] = field_info.default_factory()
        return cls(**values)


@dataclass
class AppSettings:
    start_with_windows: bool = False
    minimize_to_tray: bool = True
    auto_reconnect: bool = False
    auto_remount_on_lost: bool = True
    check_interval_seconds: int = 30
    debug_mode: bool = False
    require_admin: bool = False
    use_putty: bool = False
    putty_path: str = r"C:\Program Files\PuTTY\putty.exe"
    terminal_client: str = "xterm"  # "ssh" | "putty" | "xterm"
    auto_login: bool = False
    auto_reconnect_mounts: bool = True
    language: str = "en"
    theme: str = "dark"
    allow_passwordless_key_auth: bool = False
    security_level: int = 0  # 0=Strict, 1=Keys, 2=Passwords
    allow_insecure_password_auth: bool = False
    telemetry_enabled: bool = False
    telemetry_prompt_shown: bool = False
    sshfs_disable_cache: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        return cls(**{k: data.get(k, v) for k, v in asdict(cls()).items()})


# ---------------------------------------------------------------------------
# Legacy config file path
# (only used in main.py to read require_admin before the DB is open)
# ---------------------------------------------------------------------------

def get_config_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home()))
    config_dir = Path(appdata) / "SSHWinManager"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    return get_config_dir() / "config.json"


def save_config(connections: List[Connection], settings: AppSettings) -> None:
    payload = {
        "connections": [
            {
                key: value
                for key, value in conn.to_dict().items()
                if key != "password"
            }
            for conn in connections
        ],
        "settings": settings.to_dict(),
    }

    config_path = get_config_path()
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def load_config() -> Tuple[List[Connection], AppSettings]:
    config_path = get_config_path()
    if not config_path.exists():
        return [], AppSettings()

    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    # Support the current object shape and older list-only files.
    if isinstance(data, list):
        connections_data = data
        settings_data = {}
    else:
        connections_data = data.get("connections", [])
        settings_data = data.get("settings", {})

    return (
        [Connection.from_dict(item) for item in connections_data],
        AppSettings.from_dict(settings_data),
    )
