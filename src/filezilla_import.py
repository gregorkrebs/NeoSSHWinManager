"""Import the sites of FileZilla's Site Manager.

FileZilla keeps its sites in ``%APPDATA%\\FileZilla\\sitemanager.xml``; "File →
Export…" writes the same format. Sites sit in ``<Servers>``, optionally inside
nested ``<Folder>`` elements, which become the connection's group here.

What maps to a connection:

- SFTP sites; FTP sites as FTP or FTPS (explicit or implicit TLS). Other
  protocols FileZilla Pro knows (S3, WebDAV, cloud storage …) are listed but
  cannot be imported.
- The stored password when FileZilla kept it in plain or base64 form. With a
  FileZilla master password it is encrypted; the connection then asks for the
  password when it connects, like the sites set to "Ask for password".
- A key file: an OpenSSH key goes to ``key_path``, a PuTTY key (.ppk) to
  ``putty_key_path`` (the terminal and the file browser use it; mounting a
  drive needs an OpenSSH key).
- The remote folder FileZilla opens first, as the connection's remote path.
"""
from __future__ import annotations

import base64
import binascii
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from src.config import Connection, PROTOCOL_FTP, PROTOCOL_FTPS, PROTOCOL_SFTP

# FileZilla's protocol numbers (ServerProtocol in its server.h)
FZ_FTP = 0             # FTP, explicit TLS if the server offers it
FZ_SFTP = 1
FZ_FTPS = 3            # implicit TLS
FZ_FTPES = 4           # explicit TLS, required
FZ_INSECURE_FTP = 6    # plain FTP only

FZ_PROTOCOL_NAMES = {
    2: "HTTP", 5: "HTTPS", 7: "S3", 8: "Storj", 9: "WebDAV", 10: "Azure Files",
    11: "Azure Blob", 12: "Swift", 13: "Google Cloud Storage", 14: "Google Drive",
    15: "Dropbox", 16: "OneDrive", 17: "Box", 18: "Backblaze B2", 19: "Rackspace",
}

# FileZilla's logon types
LOGON_ANONYMOUS, LOGON_NORMAL, LOGON_ASK, LOGON_INTERACTIVE, LOGON_ACCOUNT, LOGON_KEY = range(6)

MAX_FILE_SIZE = 20 * 1024 * 1024

# Remote directory types whose paths use backslashes and a drive letter
_DOS_TYPES = {3, 8}


@dataclass
class FzSite:
    """One FileZilla site, already translated into the app's terms."""
    name: str
    group: str
    host: str
    port: int
    protocol: str = PROTOCOL_SFTP
    ftp_implicit_tls: bool = False
    ftp_passive: bool = True
    user: str = ""
    auth_method: str = "password"
    password: str = ""
    key_path: str = ""
    putty_key_path: str = ""
    remote_path: str = "/"
    supported: bool = True
    fz_protocol: int = FZ_SFTP
    # translation keys of remarks shown in the import list, with their arguments
    notes: list[tuple[str, dict]] = field(default_factory=list)

    @property
    def protocol_label(self) -> str:
        if not self.supported:
            return FZ_PROTOCOL_NAMES.get(self.fz_protocol, "?")
        return {PROTOCOL_FTPS: "FTPS", PROTOCOL_FTP: "FTP"}.get(self.protocol, "SFTP")


class NotFileZillaError(ValueError):
    """The file is not a FileZilla Site Manager (or export) file."""


def default_path() -> str:
    """Where FileZilla keeps the Site Manager on this computer."""
    return os.path.join(os.environ.get("APPDATA", ""), "FileZilla", "sitemanager.xml")


def _text(el, tag: str, default: str = "") -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None and child.text else default


def _int(el, tag: str, default: int) -> int:
    try:
        return int(_text(el, tag, str(default)))
    except ValueError:
        return default


def parse_remote_dir(value: str) -> str:
    """FileZilla's serialized remote path → a path string.

    Format: "<type> <prefix length> [<prefix>] (<length> <segment>)*", with
    every segment length-prefixed (segments may contain spaces), e.g.
    "1 0 4 home 4 user" → "/home/user", "3 0 2 C: 5 Users" → "C:\\Users".
    """
    s = (value or "").strip()
    if not s:
        return ""
    pos = 0

    def read_int() -> int:
        nonlocal pos
        end = s.find(" ", pos)
        end = len(s) if end < 0 else end
        n = int(s[pos:end])
        pos = end + 1
        return n

    def read_str(n: int) -> str:
        nonlocal pos
        out = s[pos:pos + n]
        if len(out) != n:
            raise ValueError("truncated")
        pos += n + 1
        return out

    try:
        dir_type = read_int()
        prefix_len = read_int()
        prefix = read_str(prefix_len) if prefix_len else ""
        segments = []
        while pos < len(s):
            segments.append(read_str(read_int()))
    except ValueError:
        return ""
    if dir_type in _DOS_TYPES:
        if not segments:
            return ""
        path = "\\".join(segments)
        return path + "\\" if len(segments) == 1 else path
    return prefix + "/" + "/".join(segments)


def _password(server) -> tuple[str, bool]:
    """(password, encrypted with FileZilla's master password)."""
    el = server.find("Pass")
    if el is None or not el.text:
        return "", False
    encoding = (el.get("encoding") or "").lower()
    if encoding == "base64":
        try:
            return base64.b64decode(el.text.strip()).decode("utf-8"), False
        except (binascii.Error, UnicodeDecodeError):
            return "", False
    if encoding == "crypt":
        return "", True
    return el.text, False          # very old versions stored it in plain text


def _site(server, group: str) -> FzSite:
    host = _text(server, "Host")
    fz_proto = _int(server, "Protocol", FZ_FTP)
    # Older versions write the name as text after the child elements
    children = list(server)
    trailing = (children[-1].tail or "").strip() if children else (server.text or "").strip()
    name = _text(server, "Name") or trailing or host
    site = FzSite(name=name, group=group, host=host, port=0, fz_protocol=fz_proto)

    if fz_proto == FZ_SFTP:
        site.protocol, default_port = PROTOCOL_SFTP, 22
    elif fz_proto in (FZ_FTP, FZ_FTPES):
        site.protocol, default_port = PROTOCOL_FTPS, 21
        if fz_proto == FZ_FTP:
            site.notes.append(("import.fz.note.tls_if_available", {}))
    elif fz_proto == FZ_FTPS:
        site.protocol, site.ftp_implicit_tls, default_port = PROTOCOL_FTPS, True, 990
    elif fz_proto == FZ_INSECURE_FTP:
        site.protocol, default_port = PROTOCOL_FTP, 21
    else:
        site.supported, default_port = False, 0
        site.notes.append(("import.fz.note.unsupported",
                           {"proto": FZ_PROTOCOL_NAMES.get(fz_proto, str(fz_proto))}))
    port = _int(server, "Port", 0)
    site.port = port if 0 < port < 65536 else default_port
    site.ftp_passive = _text(server, "PasvMode").upper() != "MODE_ACTIVE"

    logon = _int(server, "Logontype", LOGON_NORMAL)
    site.user = _text(server, "User")
    password, locked = _password(server)
    if logon == LOGON_ANONYMOUS:
        site.user, site.auth_method = "anonymous", "password"
    elif logon == LOGON_KEY:
        keyfile = _text(server, "Keyfile")
        site.auth_method = "key"
        if keyfile.lower().endswith(".ppk"):
            site.putty_key_path = keyfile
            site.notes.append(("import.fz.note.ppk", {}))
        else:
            site.key_path = keyfile
    elif logon in (LOGON_ASK, LOGON_INTERACTIVE) or locked or not password:
        site.auth_method = "ask"
        site.notes.append(("import.fz.note.master_password" if locked else "import.fz.note.ask", {}))
    else:
        site.auth_method, site.password = "password", password

    path = parse_remote_dir(_text(server, "RemoteDir"))
    if path and path != "/":
        site.remote_path = path
    return site


def parse_site_manager(data: bytes | str) -> list[FzSite]:
    """All sites in a sitemanager.xml (or a FileZilla export), in the order shown there."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise NotFileZillaError(str(e)) from e
    if root.tag != "FileZilla3":
        raise NotFileZillaError(root.tag)
    sites: list[FzSite] = []

    def walk(el, folders: list[str]):
        for child in el:
            if child.tag == "Server":
                if _text(child, "Host"):
                    sites.append(_site(child, " / ".join(folders)))
            elif child.tag == "Folder":
                walk(child, folders + [(child.text or "").strip() or "?"])

    for servers in root.iter("Servers"):
        walk(servers, [])
    return sites


def read_site_manager(path: str) -> list[FzSite]:
    """Read and parse a Site Manager file."""
    if os.path.getsize(path) > MAX_FILE_SIZE:
        raise NotFileZillaError("too large")
    with open(path, "rb") as f:
        return parse_site_manager(f.read())


def is_duplicate(site: FzSite, existing) -> bool:
    """True if a connection to the same server, port, user and protocol exists."""
    key = (site.host.lower(), site.port, site.user, site.protocol)
    return any((c.host.lower(), c.port, c.user, c.protocol) == key for c in existing)


def unique_name(name: str, taken: set[str]) -> str:
    """*name*, or "name (2)", "name (3)" … if it is taken (case-insensitive)."""
    low = {t.lower() for t in taken}
    if name.lower() not in low:
        return name
    n = 2
    while f"{name} ({n})".lower() in low:
        n += 1
    return f"{name} ({n})"


def to_connection(site: FzSite, name: str, drive_letter: str) -> Connection:
    """The connection the app stores for *site*."""
    return Connection(
        name=name, host=site.host, user=site.user, remote_path=site.remote_path,
        port=site.port, auth_method=site.auth_method, password=site.password,
        key_path=site.key_path, putty_key_path=site.putty_key_path,
        drive_letter=drive_letter, protocol=site.protocol,
        ftp_implicit_tls=site.ftp_implicit_tls, ftp_passive=site.ftp_passive,
        groups=re.sub(r"\s*,\s*", " ", site.group),        # commas separate groups in the app
    )
