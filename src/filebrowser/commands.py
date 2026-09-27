"""
commands.py – Shell command builders for SSH exec on Linux and Windows servers.

Linux commands are POSIX sh with every argument quoted by shlex.quote.
Windows commands are PowerShell scripts shipped as -EncodedCommand (UTF-16LE
Base64): that works whatever the server's default shell is (cmd.exe or
PowerShell) and needs no quoting across the SSH/cmd layers at all. Inside the
script, strings are single-quoted with '' escaping.

Also home of the URL validation for "upload from URL".
"""

from __future__ import annotations

import base64
import re
import shlex
import urllib.parse
from typing import Iterable, Optional

from src.filebrowser.model import rjoin, split_name, windows_remote_to_native


# ── Quoting ──────────────────────────────────────────────────────────────────

def sh_quote(value: str) -> str:
    return shlex.quote(value)


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def ps_encoded(script: str) -> str:
    """Wrap a PowerShell script so it runs from any Windows default shell."""
    body = "$ErrorActionPreference='Stop'\n$ProgressPreference='SilentlyContinue'\n" + script
    encoded = base64.b64encode(body.encode("utf-16-le")).decode("ascii")
    return f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded}"


def native(path: str, is_windows: bool) -> str:
    return windows_remote_to_native(path) if is_windows else path


# ── Archives ─────────────────────────────────────────────────────────────────

ARCHIVE_ZIP = "zip"
ARCHIVE_TGZ = "tar.gz"

# Windows' own bsdtar by full path: a GNU tar from Git for Windows earlier in
# PATH would read "C:\..." as a remote host ("Cannot connect to C:").
_WIN_TAR = '& "$env:SystemRoot\\System32\\tar.exe"'


def archive_kind(name: str) -> Optional[str]:
    """'zip' or 'tar' for archives the browser can extract, else None."""
    low = name.lower()
    if low.endswith(".zip"):
        return "zip"
    if low.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        return "tar"
    return None


def pack_command(
    is_windows: bool, directory: str, names: Iterable[str], archive_name: str, fmt: str
) -> str:
    """Pack `names` (entries of `directory`) into directory/archive_name."""
    names = list(names)
    archive = rjoin(directory, archive_name)
    if is_windows:
        if fmt == ARCHIVE_ZIP:
            items = ",".join(ps_quote(native(rjoin(directory, n), True)) for n in names)
            return ps_encoded(
                f"Compress-Archive -LiteralPath {items} "
                f"-DestinationPath {ps_quote(native(archive, True))} -Force"
            )
        args = " ".join(ps_quote("./" + n) for n in names)
        return ps_encoded(
            f"{_WIN_TAR} -czf {ps_quote(native(archive, True))} "
            f"-C {ps_quote(native(directory, True))} {args}\n"
            "if ($LASTEXITCODE) { exit $LASTEXITCODE }"
        )
    # "./name" keeps names that start with "-" from being read as options.
    args = " ".join(sh_quote("./" + n) for n in names)
    target = sh_quote("./" + archive_name)
    if fmt == ARCHIVE_ZIP:
        return f"cd {sh_quote(directory)} && zip -r -q {target} {args}"
    return f"cd {sh_quote(directory)} && tar -czf {target} {args}"


def extract_command(is_windows: bool, archive_path: str, dest_dir: str) -> str:
    kind = archive_kind(archive_path)
    if is_windows:
        a, d = native(archive_path, True), native(dest_dir, True)
        if kind == "zip":
            return ps_encoded(
                f"Expand-Archive -LiteralPath {ps_quote(a)} -DestinationPath {ps_quote(d)} -Force"
            )
        return ps_encoded(
            f"{_WIN_TAR} -xf {ps_quote(a)} -C {ps_quote(d)}\n"
            "if ($LASTEXITCODE) { exit $LASTEXITCODE }"
        )
    if kind == "zip":
        return f"unzip -o -q {sh_quote(archive_path)} -d {sh_quote(dest_dir)}"
    return f"tar -xf {sh_quote(archive_path)} -C {sh_quote(dest_dir)}"


def default_archive_name(names: list[str], fmt: str) -> str:
    base = split_name(names[0])[0] if len(names) == 1 else "archive"
    return f"{base or 'archive'}.{fmt}"


# ── Checksums ────────────────────────────────────────────────────────────────

def checksum_command(is_windows: bool, path: str) -> str:
    if is_windows:
        return ps_encoded(
            f"(Get-FileHash -Algorithm SHA256 -LiteralPath {ps_quote(native(path, True))}).Hash"
        )
    q = sh_quote(path)
    return f"sha256sum {q} 2>/dev/null || shasum -a 256 {q}"


def parse_checksum(output: str) -> Optional[str]:
    m = re.search(r"\b([0-9a-fA-F]{64})\b", output or "")
    return m.group(1).lower() if m else None


# ── Server-side copy ─────────────────────────────────────────────────────────

def duplicate_command(is_windows: bool, src: str, dst: str) -> str:
    if is_windows:
        return ps_encoded(
            f"Copy-Item -LiteralPath {ps_quote(native(src, True))} "
            f"-Destination {ps_quote(native(dst, True))} -Recurse"
        )
    return f"cp -a {sh_quote(src)} {sh_quote(dst)}"


# ── Terminal ─────────────────────────────────────────────────────────────────

def terminal_cd_input(is_windows: bool, path: str) -> str:
    """
    Keystrokes that put a fresh interactive shell into `path`.

    On Windows the lines work in cmd.exe and PowerShell alike: "E:" switches
    the drive in both, cd changes the folder, cls clears the screen.
    """
    if is_windows:
        target = native(path, True)
        drive = target[:2] if re.match(r"^[A-Za-z]:", target) else ""
        lines = ([drive] if drive else []) + [f'cd "{target}"', "cls"]
        return "".join(line + "\r" for line in lines)
    return f"cd {sh_quote(path)} && clear\r"


# ── Fetch from URL ───────────────────────────────────────────────────────────

class UrlError(ValueError):
    """The URL is not an http(s) address the browser may fetch."""


def validate_url(url: str) -> str:
    """
    Return the cleaned URL or raise UrlError.

    Only http and https: file:// would let the dialog read arbitrary local
    files, and other schemes are not what "download from the web" means.
    """
    url = (url or "").strip()
    if not url or len(url) > 4096:
        raise UrlError("empty or too long")
    if any(ord(c) < 32 or c.isspace() for c in url):
        raise UrlError("contains whitespace or control characters")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise UrlError("only http and https are supported")
    if not parsed.netloc or not parsed.hostname:
        raise UrlError("no host")
    return url


_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    name = _INVALID_NAME_CHARS.sub("_", name or "").strip().strip(".")
    return name[:200] or "download"


def filename_from_url(url: str, content_disposition: Optional[str] = None) -> str:
    """File name from a Content-Disposition header, else from the URL path."""
    if content_disposition:
        m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", content_disposition, re.I)
        if m:
            return sanitize_filename(urllib.parse.unquote(m.group(1).strip().strip('"')))
        m = re.search(r'filename\s*=\s*"?([^";]+)"?', content_disposition, re.I)
        if m:
            return sanitize_filename(m.group(1).strip())
    path = urllib.parse.urlsplit(url).path
    last = urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[-1]) if path else ""
    return sanitize_filename(last)


def fetch_url_command(is_windows: bool, url: str, dest: str) -> str:
    """Let the server download `url` to `dest` itself (curl, wget or PowerShell)."""
    url = validate_url(url)
    if is_windows:
        return ps_encoded(
            "[Net.ServicePointManager]::SecurityProtocol = "
            "[Net.SecurityProtocolType]::Tls12 -bor [Net.ServicePointManager]::SecurityProtocol\n"
            f"Invoke-WebRequest -UseBasicParsing -Uri {ps_quote(url)} "
            f"-OutFile {ps_quote(native(dest, True))}"
        )
    # validate_url guarantees the URL starts with http(s)://, so it can never
    # be taken for an option.
    u, d = sh_quote(url), sh_quote(dest)
    return (
        "if command -v curl >/dev/null 2>&1; then "
        f"curl -fsSL --retry 2 -o {d} {u}; "
        "elif command -v wget >/dev/null 2>&1; then "
        f"wget -q -O {d} {u}; "
        "else echo 'neither curl nor wget is installed' >&2; exit 127; fi"
    )
