"""
system_info_panel.py – System info panel for right panel.
Displays SSH-gathered stats in a layout matching the app design.
"""

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QWidget, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from src.ui.icons import icon as svg_icon

import base64
import subprocess
import os
import sys
import shutil
from src.config import Connection
from src.app_logger import logger
from src.i18n import tr
from src.remote_os import detect_remote_os
from src.ui.host_key_utils import ensure_host_known

class AuthLevelError(Exception):
    """Raised when the connection's auth method is not permitted at the current security level."""
    def __init__(self, level: str):
        super().__init__(level)
        self.level = level  # "0", "1", or "2"


def _is_safe_file_path(path: str) -> bool:
    """
    Validate file path to prevent path traversal and command injection.
    """
    if not path or not isinstance(path, str):
        return False

    # Normalize path and check for traversal
    try:
        normalized = os.path.normpath(path)
    except Exception:
        return False

    if '..' in normalized or normalized.startswith('/..'):
        return False

    # Reject shell metacharacters
    dangerous = set(';|&`$(){}[]<>!\\"\'\n\r\t')
    if any(c in dangerous for c in path):
        return False

    return True


def _is_host_known(host: str, port: int, known_hosts_path: str) -> bool:
    """
    SECURITY FIX (FINDING-02): Check whether a host is already verified in known_hosts
    before initiating an SSH connection, to prevent MITM attacks.

    Uses ssh-keygen -F for correct handling of hashed known_hosts entries.
    Falls back to plain text search for unhashed entries.
    """
    if not os.path.exists(known_hosts_path):
        return False

    # Primary: ssh-keygen -F (handles hashed known_hosts correctly)
    ssh_keygen = shutil.which("ssh-keygen") or r"C:\Windows\System32\OpenSSH\ssh-keygen.exe"
    if shutil.which("ssh-keygen") or os.path.exists(ssh_keygen):
        try:
            target = f"[{host}]:{port}" if port != 22 else host
            result = subprocess.run(
                [ssh_keygen, "-F", target, "-f", known_hosts_path],
                capture_output=True, timeout=5,
                creationflags=0x08000000,
            )
            return result.returncode == 0
        except Exception:
            pass

    # Fallback: direct text search (works only for non-hashed entries)
    try:
        target_plain = host
        target_port = f"[{host}]:{port}" if port != 22 else None
        with open(known_hosts_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                hosts_field = parts[0]
                for h in hosts_field.split(','):
                    if h == target_plain or (target_port and h == target_port):
                        return True
    except Exception:
        pass

    return False


def _fmt_kb(kb: int) -> str:
    """Human-readable size from KiB, e.g. 16318464 -> '15.6G'."""
    units = ("K", "M", "G", "T", "P")
    size = float(kb)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.1f}{units[idx]}" if idx else f"{int(size)}K"


def _ssh_host_key_check_option() -> str:
    """
    Use OpenSSH's TOFU mode so a first-time host can be added to known_hosts.
    """
    return "StrictHostKeyChecking=accept-new"


class SSHSystemInfoThread(QThread):
    """Fetches system info via SSH in background."""

    info_ready = pyqtSignal(dict)
    error = pyqtSignal(str, str)  # (error_msg, error_type) where error_type can be "key_missing" or "generic"

    def __init__(self, conn: Connection, settings=None, os_hint: str | None = None):
        super().__init__()
        self._conn = conn
        self._settings = settings
        self._stopped = False
        # "linux" | "windows" | None. Lets a refresh skip OS auto-detection.
        self._os_hint = os_hint

    def run(self):
        try:
            info = self._gather_info()
            if not self._stopped:
                self.info_ready.emit(info)
        except AuthLevelError as e:
            if not self._stopped:
                self.error.emit(e.level, "auth_missing")
        except ValueError as e:
            # ValueError from _build_ssh_command when key is missing
            if not self._stopped:
                self.error.emit(str(e), "key_missing")
        except Exception as e:
            if not self._stopped:
                self.error.emit(str(e), "generic")

    def stop(self):
        self._stopped = True

    def _validate_auth(self) -> None:
        """Raise AuthLevelError if neither key nor password is configured."""
        # Key is only "available" if auth_method is "key" AND key exists
        has_key = self._conn.auth_method == "key" and bool(self._conn.key_path or self._conn.putty_key_path)
        has_password = self._conn.auth_method == "password" and bool(self._conn.password)
        if not has_key and not has_password:
            raise AuthLevelError("missing")

    def _gather_info(self) -> dict:
        self._validate_auth()

        info = {
            "hostname": self._conn.host,
            "user": self._conn.user,
            "connected": False,
            "error": None,
        }

        ssh_client, client_type = self._find_ssh_client()
        if not ssh_client:
            info["error"] = "SSH client not found (ssh.exe or plink.exe)"
            return info

        known_hosts_path = os.path.expanduser("~\\.ssh\\known_hosts")
        # Save the host key up front so the actual data call never surfaces a
        # spurious first-time host-key error to the user.
        ensure_host_known(self._conn.host, self._conn.port, known_hosts_path)

        # Build command based on client type
        if client_type == 'plink':
            cmd_base, target = self._build_plink_command(ssh_client)
        else:
            cmd_base, target = self._build_ssh_command(ssh_client)

        run_opts = {}
        if os.name == "nt":
            run_opts["creationflags"] = subprocess.CREATE_NO_WINDOW

        def _run(remote_cmd: str):
            # Fresh env per call: the SSH_ASKPASS token is single-use, so a
            # second ssh invocation with a consumed token fails with
            # "Permission denied".
            return subprocess.run(
                cmd_base + [target, remote_cmd],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=25, env=self._get_ssh_env(), **run_opts,
            )

        # Pick the command set: the result of an earlier refresh, else the
        # server's SSH banner (no login needed), else Linux first with a
        # Windows fallback.
        if self._os_hint in ("linux", "windows"):
            order = [self._os_hint]
        elif detect_remote_os(self._conn.host, self._conn.port) == "windows":
            order = ["windows"]
        else:
            order = ["linux", "windows"]

        last_result = None
        try:
            for os_kind in order:
                remote_cmd = (
                    self._build_windows_command() if os_kind == "windows"
                    else self._build_linux_command()
                )
                last_result = _run(remote_cmd)
                if self._has_ok(last_result.stdout):
                    info["connected"] = True
                    info["_detected_os"] = os_kind
                    info.update(self._parse_sentinels(last_result.stdout))
                    self._postprocess(info)
                    if "disk_total" not in info or "memory_total" not in info:
                        logger.warning(
                            "sysinfo (%s): incomplete data from %s, raw output: %r",
                            os_kind, self._conn.host, last_result.stdout[:2000],
                        )
                    return info
                # ssh.exe exits with 255 when the connection or login failed.
                # The other command set cannot help then, and trying it would
                # only cost another failed login on the server.
                if client_type == 'ssh' and last_result.returncode == 255:
                    break
        except subprocess.TimeoutExpired:
            info["error"] = "SSH connection timed out (25s)"
            return info
        except Exception as e:
            info["error"] = f"SSH error: {e}"
            return info

        # Neither branch produced the OK sentinel — surface the real error.
        if last_result is not None:
            info["error"] = last_result.stderr or last_result.stdout or "SSH connection failed"
        else:
            info["error"] = "SSH connection failed"
        return info

    @staticmethod
    def _has_ok(raw: str) -> bool:
        """True only when a bare '##SSH_OK##' line is present.

        The exact-line match matters: a Windows cmd.exe echoing the Linux probe
        prints the sentinel *with quotes* ('##SSH_OK##'), which must not count
        as success.
        """
        return any(line.strip() == "##SSH_OK##" for line in raw.splitlines())

    # Sections whose value is a list of records, one per line.
    _MULTILINE_KEYS = frozenset({"drives"})

    @classmethod
    def _parse_sentinels(cls, raw: str) -> dict:
        """Parse ##_key_## delimited sections into a dict."""
        out: dict = {}
        current_key = None
        current_lines: list[str] = []

        def _flush():
            sep = "\n" if current_key in cls._MULTILINE_KEYS else " "
            val = sep.join(l.strip() for l in current_lines if l.strip())
            if val:
                out[current_key] = val

        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("##_") and stripped.endswith("_##"):
                if current_key:
                    _flush()
                current_key = stripped[3:-3]
                current_lines = []
            elif current_key:
                current_lines.append(line)
        if current_key and current_lines:
            _flush()
        return out

    @staticmethod
    def _ints(value, count: int) -> list[int] | None:
        """Parse exactly `count` whitespace-separated numbers, or None."""
        if not value:
            return None
        try:
            nums = [int(float(p)) for p in str(value).split()]
        except ValueError:
            return None
        return nums if len(nums) == count else None

    @classmethod
    def _postprocess(cls, info: dict) -> None:
        """Turn the raw KiB figures both command sets emit into display values.

        Doing the arithmetic here instead of splitting `free -h` / `df -h` text
        keeps the result independent of the server's locale and df's column
        layout (long device names, spaces in filesystem names).
        """
        mem = cls._ints(info.get("mem_kb"), 2)          # total, available
        if mem:
            total, avail = mem
            used = max(total - avail, 0)
            info["memory_total"] = _fmt_kb(total)
            info["memory_used"] = _fmt_kb(used)
            if total > 0:
                info["memory_percent"] = f"{used * 100 / total:.1f}"
        disk = cls._ints(info.get("disk_kb"), 3)        # total, used, available
        if disk:
            total, used, avail = disk
            info["disk_total"] = _fmt_kb(total)
            info["disk_used"] = _fmt_kb(used)
            info["disk_avail"] = _fmt_kb(avail)
            # Same basis as df's Use%: reserved blocks count as neither.
            if used + avail > 0:
                info["disk_use_percent"] = f"{used * 100 / (used + avail):.1f}"

        # drives: "ext|fs|total|used|avail|device|name" records. The name
        # (mount point / volume label) comes last and may contain "|".
        is_windows = info.get("_detected_os") == "windows"
        drives = []
        for line in str(info.get("drives") or "").splitlines():
            parts = line.split("|", 6)
            if len(parts) != 7:
                continue
            ext, fs, d_total, d_used, d_avail, device, name = (p.strip() for p in parts)
            nums = cls._ints(f"{d_total} {d_used} {d_avail}", 3)
            if not nums or nums[0] <= 0:
                continue
            d_total, d_used, d_avail = nums
            if is_windows:
                title, detail = f"{device} {name}".strip(), fs
            else:
                title = name or device
                detail = f"{device} · {fs}" if fs else device
            drives.append({
                "title": title,
                "device": device,
                "detail": detail,
                "external": ext == "1",
                "total": _fmt_kb(d_total),
                "used": _fmt_kb(d_used),
                "percent": d_used * 100 / (d_used + d_avail) if d_used + d_avail > 0 else 0.0,
            })
        if is_windows:
            drives.sort(key=lambda d: d["device"].upper())
        else:
            drives.sort(key=lambda d: (d["title"] != "/", d["title"].lower()))
        info["drives_list"] = drives

    def _build_linux_command(self) -> str:
        """Compound POSIX-sh command; one handshake, sentinel-delimited output."""
        commands = {
            "os": "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"' || uname -s",
            "hostname": "hostname -f 2>/dev/null || hostname",
            "uptime": "uptime -p 2>/dev/null || uptime | awk '{print $3,$4}' | sed 's/,//g'",
            "uptime_seconds": "cat /proc/uptime 2>/dev/null | awk '{print $1}'",
            "last_seen": "who -b 2>/dev/null | awk '{print $3,$4}' | head -1",
            "cpu_model": "cat /proc/cpuinfo | grep 'model name' | head -1 | cut -d: -f2 | sed 's/^ //'",
            "cpu_cores": "nproc",
            "cpu_percent": "top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | sed 's/%us,//' 2>/dev/null || grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$3+$4+$5)} END {printf \"%.1f\", usage}'",
            "load": "cat /proc/loadavg | awk '{print $1}'",
            # Raw KiB numbers; formatting happens in _postprocess().
            # mem_kb: total available (MemFree+Buffers+Cached on kernels < 3.14)
            "mem_kb": "awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} /^MemFree:/{f=$2} /^Buffers:/{b=$2} /^Cached:/{c=$2} END{if(a==\"\")a=f+b+c; print t, a}' /proc/meminfo",
            # disk_kb: total used available. -P = one line per filesystem, no
            # wrapping; fields counted from the right survive spaces in names.
            "disk_kb": "df -Pk / | awk 'NR==2{print $(NF-4), $(NF-3), $(NF-2)}'",
            # drives: one "ext|fstype|total|used|avail|device|mountpoint" line
            # per mounted local block device (KiB). Only /dev/* sources, so
            # tmpfs, network and fuse/sshfs mounts drop out; loop devices
            # (snaps) too. -l keeps a hung NFS mount from blocking df. ext=1
            # when the device sits on a USB bus in sysfs.
            "drives": (
                "{ df -PkTl 2>/dev/null || df -PkT; }"
                " | awk 'NR>1 && $1 ~ \"^/dev/\" && $1 !~ \"^/dev/loop\" && !seen[$1]++"
                " { m=$7; for(i=8;i<=NF;i++) m=m\" \"$i; print $1\"|\"$2\"|\"$3\"|\"$4\"|\"$5\"|\"m }'"
                " | while IFS='|' read -r dev fs total used avail mnt; do"
                " ext=0; case \"$(readlink -f /sys/class/block/$(basename \"$(readlink -f \"$dev\")\") 2>/dev/null)\" in"
                " (*/usb*) ext=1;; esac;"
                " printf '%s|%s|%s|%s|%s|%s|%s\\n' \"$ext\" \"$fs\" \"$total\" \"$used\" \"$avail\" \"$dev\" \"$mnt\"; done"
            ),
            "processes": "ps aux | wc -l",
            "users": "who | wc -l",
            "ip": "hostname -I 2>/dev/null | awk '{print $1}' || ip addr show | grep 'inet ' | grep -v '127.0.0.1' | head -1 | awk '{print $2}' | cut -d/ -f1",
            "temperature": "cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null | awk '{printf \"%.1f°C\", $1/1000}'",
        }
        # printf (not echo) for the OK sentinel: printf is a POSIX shell builtin
        # that does not exist in cmd.exe or PowerShell, so a Windows default
        # shell can never accidentally emit a bare '##SSH_OK##' line here.
        # LC_ALL=C: untranslated, dot-decimal output from top/who/df.
        cmd_parts = ["export LC_ALL=C", "printf '##SSH_OK##\\n'"]
        for key, shell_cmd in commands.items():
            cmd_parts.append(f"echo '##_{key}_##'")
            cmd_parts.append(f"( {shell_cmd} ) 2>/dev/null || true")
        return "; ".join(cmd_parts)

    def _build_windows_command(self) -> str:
        """
        PowerShell equivalent, delivered as -EncodedCommand (UTF-16LE Base64).

        Encoding sidesteps all cmd.exe/PowerShell quoting issues over SSH and
        works regardless of the server's default shell (cmd or PowerShell).
        Emits the same ##_key_## sentinel format and the same raw-KiB mem_kb /
        disk_kb figures as the Linux set, so _postprocess() handles both. All
        numbers are integers or invariant-culture strings, because a German
        server would otherwise print decimal commas.
        """
        stmts = [
            "$ErrorActionPreference='SilentlyContinue'",
            # No progress records: over a redirected stream they arrive as
            # CLIXML noise on stderr.
            "$ProgressPreference='SilentlyContinue'",
            "$inv=[Globalization.CultureInfo]::InvariantCulture",
            "$os=Get-CimInstance Win32_OperatingSystem",
            "$cpu=@(Get-CimInstance Win32_Processor)",
            "$up=(Get-Date)-$os.LastBootUpTime",
            "$sys=Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='$env:SystemDrive'\"",
            "$load=[double](($cpu | Measure-Object -Property LoadPercentage -Average).Average)",
            "Write-Output '##SSH_OK##'",
            "Write-Output '##_os_##'; Write-Output $os.Caption",
            "Write-Output '##_hostname_##'; Write-Output $env:COMPUTERNAME",
            "Write-Output '##_uptime_##'; Write-Output ('{0}d {1}h {2}m' -f $up.Days,$up.Hours,$up.Minutes)",
            "Write-Output '##_uptime_seconds_##'; Write-Output ([int64]$up.TotalSeconds)",
            "Write-Output '##_cpu_model_##'; Write-Output $cpu[0].Name",
            "Write-Output '##_cpu_cores_##'; Write-Output ([int](($cpu | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum))",
            "Write-Output '##_cpu_percent_##'; Write-Output ($load.ToString('0.0',$inv))",
            # Both values are already KiB in Win32_OperatingSystem.
            "Write-Output '##_mem_kb_##'; Write-Output ('{0} {1}' -f [int64]$os.TotalVisibleMemorySize,[int64]$os.FreePhysicalMemory)",
            "Write-Output '##_disk_kb_##'; Write-Output ('{0} {1} {2}' -f [int64]($sys.Size/1KB),[int64](($sys.Size-$sys.FreeSpace)/1KB),[int64]($sys.FreeSpace/1KB))",
            # drives: lettered volumes that sit on a real disk partition
            # (internal, external, USB sticks). Mapped UNC drives, sshfs/WinFsp
            # and subst drives have no partition and drop out. Same
            # "ext|fs|total|used|avail|device|label" lines as on Linux.
            "$l2p=@{}; Get-CimInstance Win32_LogicalDiskToPartition | ForEach-Object { $l2p[$_.Dependent.DeviceID]=$_.Antecedent.DeviceID }",
            "$p2d=@{}; Get-CimInstance Win32_DiskDriveToDiskPartition | ForEach-Object { $p2d[$_.Dependent.DeviceID]=$_.Antecedent.DeviceID }",
            "$dd=@{}; Get-CimInstance Win32_DiskDrive | ForEach-Object { $dd[$_.DeviceID]=$_ }",
            "Write-Output '##_drives_##'",
            "Get-CimInstance Win32_LogicalDisk | Where-Object { ($_.DriveType -eq 2 -or $_.DriveType -eq 3) -and $l2p.ContainsKey($_.DeviceID) -and $_.Size -gt 0 } | ForEach-Object {"
            " $d=$dd[$p2d[$l2p[$_.DeviceID]]];"
            " $ext=[int](($_.DriveType -eq 2) -or ($d.InterfaceType -eq 'USB') -or ([string]$d.MediaType -match 'External|Removable'));"
            " '{0}|{1}|{2}|{3}|{4}|{5}|{6}' -f $ext,$_.FileSystem,[int64]($_.Size/1KB),[int64](($_.Size-$_.FreeSpace)/1KB),[int64]($_.FreeSpace/1KB),$_.DeviceID,$_.VolumeName }",
            "Write-Output '##_processes_##'; Write-Output ((Get-Process).Count)",
            "Write-Output '##_users_##'; Write-Output (@(Get-CimInstance Win32_Process -Filter \"Name='explorer.exe'\" | Select-Object -ExpandProperty SessionId -Unique).Count)",
            "Write-Output '##_ip_##'; Write-Output ((Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -ne '127.0.0.1'} | Select-Object -First 1).IPAddress)",
        ]
        script = "\n".join(stmts)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded}"

    def _find_plink(self) -> str | None:
        """Find plink.exe for PuTTY-based system info."""
        candidates = [
            r"C:\Program Files\PuTTY\plink.exe",
            r"C:\Program Files (x86)\PuTTY\plink.exe",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return shutil.which("plink")

    def _find_ssh_client(self) -> tuple[str | None, str]:
        """Find SSH client (ssh.exe or plink.exe) based on settings.
        Returns (executable_path, client_type) where client_type is 'ssh' or 'plink'."""
        use_putty = getattr(self._settings, 'use_putty', False) if self._settings else False
        sec_level = int(getattr(self._settings, 'security_level', 0) or 0) if self._settings else 0
        # Key is only "available" if auth_method is "key" AND key exists
        has_key = self._conn.auth_method == "key" and bool(self._conn.putty_key_path or self._conn.key_path)

        # Password-only connections at level 2 always use native ssh.exe + SSH_ASKPASS,
        # even when PuTTY is active — plink's -pw flag exposes the password in the process list.
        is_password_only = self._conn.auth_method == "password" and not has_key

        if use_putty and not (is_password_only and sec_level >= 2):
            # Use plink for key-based auth when PuTTY is active
            key_to_use = self._conn.putty_key_path or self._conn.key_path

            # Check if key is .ppk format (required by plink)
            if key_to_use and not key_to_use.lower().endswith('.ppk'):
                logger.warning(f"plink requires .ppk format keys, but '{key_to_use}' is not .ppk. Falling back to ssh.exe.")
                # Fallback to ssh.exe for non-.ppk keys
            else:
                plink_exe = self._find_plink()
                if plink_exe:
                    return plink_exe, 'plink'
                # Fallback to ssh.exe if plink not found

        ssh_exe = self._find_ssh()
        if ssh_exe:
            return ssh_exe, 'ssh'

        return None, 'none'

    def _find_ssh(self) -> str | None:
        candidates = [
            r"C:\Windows\System32\OpenSSH\ssh.exe",
            r"C:\Windows\SysWOW64\OpenSSH\ssh.exe",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    def _build_ssh_command(self, ssh_exe: str) -> tuple[list, str]:
        """Build SSH command for native ssh.exe. Password auth uses SSH_ASKPASS from _get_ssh_env().
        SECURITY FIX (FINDING-02): Uses StrictHostKeyChecking=yes (not accept-new) because
        _gather_info() already verified the host is present in known_hosts."""
        # Key is only "available" if auth_method is "key" AND key exists
        has_key = self._conn.auth_method == "key" and bool(self._conn.key_path)
        known_hosts_path = os.path.expanduser("~\\.ssh\\known_hosts")

        if has_key:
            auth_options = [
                "-o", "BatchMode=yes",
                "-o", "PreferredAuthentications=publickey",
            ]
        else:
            # BatchMode=no required so OpenSSH actually invokes SSH_ASKPASS.
            # With BatchMode=yes OpenSSH suppresses all credential prompts,
            # including the SSH_ASKPASS helper, which causes "Permission denied".
            auth_options = [
                "-o", "BatchMode=no",
                "-o", "PreferredAuthentications=password,keyboard-interactive",
            ]

        cmd_base = [
            ssh_exe,
            "-o", _ssh_host_key_check_option(),
            "-o", f"UserKnownHostsFile={known_hosts_path}",
            "-o", "ConnectTimeout=10",
        ]
        cmd_base.extend(auth_options)
        cmd_base.extend(["-p", str(self._conn.port)])

        if has_key:
            cmd_base.extend(["-i", self._conn.key_path])

        target = f"{self._conn.user}@{self._conn.host}"
        return cmd_base, target

    def _build_plink_command(self, plink_exe: str) -> tuple[list, str]:
        """Build plink command for PuTTY-based system info."""
        # SECURITY: Validate plink path to prevent command injection
        if not _is_safe_file_path(plink_exe):
            raise ValueError(f"Ungültiger plink.exe Pfad: {plink_exe}")

        cmd_base = [
            plink_exe,
            "-batch",  # Non-interactive mode
            "-sshlog", os.devnull,  # Suppress SSH log
            "-P", str(self._conn.port),
        ]

        sec_level = getattr(self._settings, 'security_level', 0) if self._settings else 0
        # Key is only "available" if auth_method is "key" AND key exists
        key_to_use = None
        if self._conn.auth_method == "key":
            key_to_use = self._conn.putty_key_path or self._conn.key_path
        has_password = self._conn.auth_method == "password" and bool(self._conn.password)

        if key_to_use:
            # SECURITY: Validate key path
            if not _is_safe_file_path(key_to_use):
                raise ValueError(f"Ungültiger Key-Pfad: {key_to_use}")
            # plink requires .ppk format
            if not key_to_use.lower().endswith('.ppk'):
                raise ValueError(
                    "plink.exe erfordert .ppk-formatierte Keys. "
                    f"Der Key '{key_to_use}' ist nicht im .ppk Format. "
                    "Bitte konvertieren Sie den Key mit PuTTYgen oder verwenden Sie nativen SSH."
                )
            cmd_base.extend(["-i", key_to_use])
        elif has_password:
            logger.warning("Using password authentication with plink — password briefly visible in process list.")
            cmd_base.extend(["-pw", self._conn.password])
        else:
            raise ValueError("Bitte hinterlegen Sie einen SSH-Key oder Passwort für diese Verbindung.")

        target = f"{self._conn.user}@{self._conn.host}"
        return cmd_base, target

    def _get_ssh_env(self) -> dict:
        env = os.environ.copy()
        if self._conn.auth_method == "password" and self._conn.password:
            is_frozen = getattr(sys, "frozen", False)
            if is_frozen:
                askpass_cmd = f'"{sys.executable}" --pass-helper'
            else:
                import os.path as osp
                main_py = osp.abspath(osp.join(osp.dirname(__file__), "..", "..", "main.py"))
                askpass_cmd = f'"{sys.executable}" "{main_py}" --pass-helper'
            
            from src.askpass_manager import create_token
            token = create_token(self._conn.password)
            env["SSH_ASKPASS_TOKEN"] = token
            env["SSH_ASKPASS"] = askpass_cmd
            env["SSH_ASKPASS_REQUIRE"] = "force"
            env["DISPLAY"] = "dummy:0"
        return env


class SystemInfoPanel(QFrame):
    """System info panel shown in the right panel when a connection is mounted."""

    closed = pyqtSignal()

    def __init__(self, conn: Connection, parent=None, settings=None):
        super().__init__(parent)
        self._conn = conn
        self._settings = settings
        self._info_thread: SSHSystemInfoThread | None = None
        self._loading_anim_timer: QTimer | None = None
        self._loading_anim_phase: int = 0
        # Cached remote OS ("linux"/"windows") so refreshes skip auto-detection.
        self._remote_os: str | None = None

        self.setObjectName("systemInfoPanel")
        self._build_ui()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(120000)
        self._refresh_timer.timeout.connect(self._fetch_info)
        self._refresh_timer.start()

        self._fetch_info()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(18)

        hero = QFrame()
        self._hero_card = hero
        hero.setObjectName("sysinfoHeroCard")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(0, 0, 0, 0)
        hero_l.setSpacing(8)

        hero_top = QHBoxLayout()
        hero_top.setContentsMargins(0, 0, 0, 0)
        hero_top.setSpacing(8)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)
        self._hero_title = QLabel(self._conn.name)
        self._hero_title.setObjectName("sysinfoHeroTitle")
        title_col.addWidget(self._hero_title)
        self._hero_meta = QLabel(f"{self._conn.user}@{self._conn.host}:{self._conn.port}")
        self._hero_meta.setObjectName("sysinfoHeroMeta")
        title_col.addWidget(self._hero_meta)
        hero_top.addLayout(title_col)
        hero_top.addStretch()

        self._state_pill = QLabel(tr("panel.status.connected"))
        self._state_pill.setObjectName("sysinfoStatePill")
        self._state_pill.setProperty("connected", "true")
        hero_top.addWidget(self._state_pill, 0, Qt.AlignmentFlag.AlignTop)

        self._refresh_btn = QPushButton()
        self._refresh_btn.setObjectName("rpHeaderBtn")
        self._refresh_btn.setFixedSize(28, 28)
        self._refresh_btn.setIcon(svg_icon("refresh", "#aab4c4", 15))
        self._refresh_btn.setIconSize(QSize(15, 15))
        self._refresh_btn.setToolTip(tr("sysinfo.refresh"))
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.clicked.connect(self._fetch_info)
        hero_top.addWidget(self._refresh_btn, 0, Qt.AlignmentFlag.AlignTop)
        hero_l.addLayout(hero_top)

        self._hero_path = QLabel(f"{self._conn.remote_path}  ->  {self._conn.drive_letter}")
        self._hero_path.setObjectName("dialogLead")
        self._hero_path.setWordWrap(True)
        hero_l.addWidget(self._hero_path)
        hero_l.addSpacing(10)
        hero_l.addWidget(self._make_divider())
        root.addWidget(hero)

        # Error card only. Loading is shown solely by the overlay popup, so no
        # "loading…" text sits behind it on (re)loads.
        self._state_card = QFrame()
        self._state_card.setObjectName("sysinfoStateCard")
        state_l = QVBoxLayout(self._state_card)
        state_l.setContentsMargins(0, 0, 0, 0)
        state_l.setSpacing(6)
        self._error_lbl = QLabel()
        self._error_lbl.setObjectName("sysinfoErrorText")
        self._error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_lbl.setWordWrap(True)
        state_l.addWidget(self._error_lbl)
        self._state_card.hide()
        root.addWidget(self._state_card)

        self._content = QWidget()
        # Content stays visible to avoid layout jumps; values are placeholders while loading.
        content_v = QVBoxLayout(self._content)
        content_v.setContentsMargins(0, 0, 0, 0)
        content_v.setSpacing(26)

        resources_card, resources_l, self._sys_section = self._make_section_card(tr("sysinfo.os"))

        self._cpu_row = self._make_stat_row(tr("sysinfo.cpu"), "0%")
        self._cpu_bar = self._make_progress_bar()
        resources_l.addWidget(self._cpu_row)
        resources_l.addSpacing(7)
        resources_l.addWidget(self._cpu_bar)
        resources_l.addSpacing(18)

        self._ram_row = self._make_stat_row(tr("sysinfo.ram"), "— / —")
        self._ram_bar = self._make_progress_bar()
        resources_l.addWidget(self._ram_row)
        resources_l.addSpacing(7)
        resources_l.addWidget(self._ram_bar)
        resources_l.addSpacing(18)

        self._disk_row = self._make_stat_row(tr("sysinfo.disk"), "— / —")
        self._disk_bar = self._make_progress_bar()
        resources_l.addWidget(self._disk_row)
        resources_l.addSpacing(7)
        resources_l.addWidget(self._disk_bar)

        self._temp_widget = QWidget()
        temp_v = QVBoxLayout(self._temp_widget)
        temp_v.setContentsMargins(0, 18, 0, 0)
        temp_v.setSpacing(0)
        self._temp_row = self._make_stat_row(tr("sysinfo.temperature"), "—")
        temp_v.addWidget(self._temp_row)
        self._temp_widget.hide()
        resources_l.addWidget(self._temp_widget)
        resources_l.addStretch()
        content_v.addWidget(resources_card)

        # Attached drives (Linux: mounted local block devices; Windows: lettered
        # volumes on a disk partition). Rows are rebuilt on every refresh.
        drives_card, drives_l, _ = self._make_section_card(tr("sysinfo.drives"))
        self._drives_box = QWidget()
        self._drives_box_l = QVBoxLayout(self._drives_box)
        self._drives_box_l.setContentsMargins(0, 0, 0, 0)
        self._drives_box_l.setSpacing(18)
        placeholder = QLabel("—")
        placeholder.setObjectName("sysinfoDriveMeta")
        self._drives_box_l.addWidget(placeholder)
        drives_l.addWidget(self._drives_box)
        content_v.addWidget(drives_card)

        details_card, details_l, self._uptime_section = self._make_section_card(tr("sysinfo.uptime"))

        self._uptime_row = self._make_stat_row(tr("sysinfo.host"), "—", strong=True)
        details_l.addWidget(self._uptime_row)
        details_l.addSpacing(10)
        self._load_row = self._make_stat_row(tr("sysinfo.load"), "—", strong=True)
        details_l.addWidget(self._load_row)
        content_v.addWidget(details_card)

        activity_card, activity_l, self._detail_section = self._make_section_card(
            tr("sysinfo.active_users") + " & " + tr("sysinfo.processes"))
        self._users_row = self._make_stat_row(tr("sysinfo.active_users"), "—", strong=True)
        activity_l.addWidget(self._users_row)
        activity_l.addSpacing(10)
        self._proc_row = self._make_stat_row(tr("sysinfo.processes"), "—", strong=True)
        activity_l.addWidget(self._proc_row)
        activity_l.addSpacing(10)
        self._ip_row = self._make_stat_row(tr("sysinfo.ip"), "—", strong=True)
        activity_l.addWidget(self._ip_row)
        content_v.addWidget(activity_card)
        content_v.addStretch()

        root.addWidget(self._content, stretch=1)

        # Loading overlay (single, styled tile) shown while fetching info
        self._loading_overlay = QWidget(self)
        self._loading_overlay.setObjectName("sysinfoLoadingOverlay")
        self._loading_overlay.hide()

        ov = QVBoxLayout(self._loading_overlay)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(0)
        ov.addStretch(1)

        loading_card = QFrame()
        loading_card.setObjectName("sysinfoLoadingCard")
        loading_l = QVBoxLayout(loading_card)
        loading_l.setContentsMargins(18, 16, 18, 16)
        loading_l.setSpacing(8)

        self._loading_icon = QLabel()
        self._loading_icon.setObjectName("sysinfoLoadingIcon")
        self._loading_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_overlay_icon("hourglass", "info")
        loading_l.addWidget(self._loading_icon)

        self._loading_title = QLabel(tr("sysinfo.loading"))
        self._loading_title.setObjectName("sysinfoLoadingTitle")
        self._loading_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_title.setWordWrap(True)
        loading_l.addWidget(self._loading_title)

        self._loading_dots = QLabel("…")
        self._loading_dots.setObjectName("sysinfoLoadingDots")
        self._loading_dots.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_l.addWidget(self._loading_dots)

        ov.addWidget(loading_card, 0, Qt.AlignmentFlag.AlignHCenter)
        ov.addStretch(1)

        self._loading_anim_timer = QTimer(self)
        self._loading_anim_timer.setInterval(320)
        self._loading_anim_timer.timeout.connect(self._tick_loading_overlay)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_loading_overlay") and self._loading_overlay is not None:
            self._loading_overlay.setGeometry(self.rect())

    def _tick_loading_overlay(self):
        self._loading_anim_phase = (self._loading_anim_phase + 1) % 4
        dots = "." * self._loading_anim_phase
        self._loading_dots.setText(dots if dots else " ")

    def _set_loading_overlay_visible(self, visible: bool):
        if not hasattr(self, "_loading_overlay"):
            return
        if visible:
            self._set_overlay_icon("hourglass", "info")
            self._loading_title.setText(tr("sysinfo.loading"))
            self._loading_dots.setText("…")
            self._loading_dots.show()
        self._loading_overlay.setVisible(visible)
        if self._loading_anim_timer:
            if visible and not self._loading_anim_timer.isActive():
                self._loading_anim_phase = 0
                self._loading_anim_timer.start()
            elif not visible and self._loading_anim_timer.isActive():
                self._loading_anim_timer.stop()

    def _set_overlay_icon(self, name: str, mode: str):
        """Overlay icon: SVG *name* in the colour of message type *mode*."""
        from PyQt6.QtWidgets import QApplication
        from src.ui.dialog_utils import message_color
        from src.ui.icons import pixmap as svg_pixmap
        screen = QApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0
        self._loading_icon.setPixmap(svg_pixmap(name, message_color(mode), 30, dpr))

    def _show_overlay_error(self, icon: str, title: str, body: str):
        """icon: name of an SVG in assets/icons (shown in the warning colour)."""
        if not hasattr(self, "_loading_overlay"):
            return
        self._loading_anim_timer.stop()
        self._set_overlay_icon(icon, "warning")
        self._loading_title.setText(title)
        self._loading_dots.setText(body)
        self._hero_card.hide()
        self._content.hide()
        self._loading_overlay.show()
        self._loading_dots.show()

    def _make_section_card(self, title: str):
        frame = QFrame()
        frame.setObjectName("sysinfoSectionCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        section = self._make_section_label(title)
        layout.addWidget(section)
        layout.addSpacing(14)
        return frame, layout, section

    def _make_section_label(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setObjectName("rpSectionLabel")
        return lbl

    def _make_divider(self) -> QFrame:
        f = QFrame()
        f.setObjectName("rpDivider")
        f.setFixedHeight(1)
        return f

    def _make_stat_row(self, label: str, value: str, strong: bool = False) -> QWidget:
        """Label left, value right. *strong* labels are for key/value lists
        without a bar underneath."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        lbl = QLabel(label)
        lbl.setObjectName("sysinfoStatLabel")
        lbl.setProperty("strong", "true" if strong else "false")
        val = QLabel(value)
        val.setObjectName("sysinfoStatValue")
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(lbl)
        h.addStretch()
        h.addWidget(val)
        # store refs on widget for easy update
        w._label_lbl = lbl
        w._value_lbl = val
        return w

    def _update_drives(self, drives: list[dict]) -> None:
        """Rebuild the drive rows: name + used/total, device line, usage bar."""
        while self._drives_box_l.count():
            item = self._drives_box_l.takeAt(0)
            old = item.widget()
            if old:
                # Detach now: deleteLater alone leaves the old row painted over
                # the new one until the next event-loop pass.
                old.setParent(None)
                old.deleteLater()

        if not drives:
            empty = QLabel(tr("sysinfo.drives.none"))
            empty.setObjectName("sysinfoDriveMeta")
            self._drives_box_l.addWidget(empty)
            return

        for drive in drives:
            row = QWidget()
            v = QVBoxLayout(row)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)

            pct = float(drive.get("percent", 0.0))
            stat = self._make_stat_row(
                drive["title"], f"{drive['used']} / {drive['total']}  ({pct:.0f}%)"
            )
            stat._label_lbl.setToolTip(drive["title"])
            v.addWidget(stat)

            meta_text = drive.get("detail", "")
            if drive.get("external"):
                meta_text = f"{meta_text} · {tr('sysinfo.drive.external')}" if meta_text \
                    else tr("sysinfo.drive.external")
            if meta_text:
                meta = QLabel(meta_text)
                meta.setObjectName("sysinfoDriveMeta")
                v.addSpacing(2)
                v.addWidget(meta)

            bar = self._make_progress_bar()
            v.addSpacing(7)
            bar.setValue(int(min(max(pct, 0.0), 100.0)))
            self._set_bar_color(bar, pct)
            v.addWidget(bar)

            self._drives_box_l.addWidget(row)

    def _make_progress_bar(self) -> QProgressBar:
        bar = QProgressBar()
        bar.setObjectName("sysinfoProgress")
        bar.setMaximum(100)
        bar.setValue(0)
        bar.setFixedHeight(4)
        bar.setTextVisible(False)
        return bar

    def _set_bar_color(self, bar: QProgressBar, pct: float):
        if pct > 80:
            level = "error"
        elif pct > 50:
            level = "warn"
        else:
            level = "ok"
        bar.setProperty("level", level)
        bar.style().unpolish(bar)
        bar.style().polish(bar)

    def _fetch_info(self):
        self._hero_card.show()
        # The overlay popup is the only loading indicator; drop a previous
        # error card so nothing but the popup shows while reloading.
        self._state_card.hide()
        self._content.show()
        self._refresh_btn.setEnabled(False)
        self._set_loading_overlay_visible(True)

        if self._info_thread:
            self._info_thread.stop()
            self._info_thread.wait()

        self._info_thread = SSHSystemInfoThread(
            self._conn, settings=self._settings, os_hint=self._remote_os
        )
        self._info_thread.info_ready.connect(self._on_info_ready)
        self._info_thread.error.connect(self._on_error)
        self._info_thread.start()

    def _on_info_ready(self, info: dict):
        self._state_card.hide()
        self._refresh_btn.setEnabled(True)
        self._set_loading_overlay_visible(False)

        if info.get("error") and not info.get("connected"):
            self._on_error(info["error"])
            return

        # Remember the detected OS so the next refresh queries it directly.
        detected = info.get("_detected_os")
        if detected:
            self._remote_os = detected

        self._content.show()
        self._state_pill.setText(tr("panel.status.connected"))
        self._state_pill.setProperty("connected", "true")
        self._state_pill.style().unpolish(self._state_pill)
        self._state_pill.style().polish(self._state_pill)
        self._hero_title.setText(self._conn.name)
        self._hero_meta.setText(info.get("os", f"{self._conn.user}@{self._conn.host}:{self._conn.port}"))

        # Section header: "SYSTEM · <hostname>"
        hostname = info.get("hostname", self._conn.host)
        self._sys_section.setText(f"SYSTEM · {hostname}".upper())

        # CPU
        try:
            cpu_pct = float(info.get("cpu_percent", "0").replace("%", ""))
        except Exception:
            cpu_pct = 0.0
        cores = info.get("cpu_cores", "?")
        self._cpu_row._value_lbl.setText(f"{cpu_pct:.0f}%  ({cores} cores)")
        self._cpu_bar.setValue(int(cpu_pct))
        self._set_bar_color(self._cpu_bar, cpu_pct)

        # RAM
        mem_used = info.get("memory_used", "—")
        mem_total = info.get("memory_total", "—")
        self._ram_row._value_lbl.setText(f"{mem_used} / {mem_total}")
        try:
            mem_pct = float(info.get("memory_percent", "0"))
        except Exception:
            mem_pct = 0.0
        self._ram_bar.setValue(int(mem_pct))
        self._set_bar_color(self._ram_bar, mem_pct)

        # Disk
        disk_used = info.get("disk_used", "—")
        disk_total = info.get("disk_total", "—")
        try:
            disk_pct = float(str(info.get("disk_use_percent", "0")).replace("%", ""))
        except Exception:
            disk_pct = 0.0
        self._disk_row._value_lbl.setText(f"{disk_used} / {disk_total}")
        self._disk_bar.setValue(int(disk_pct))
        self._set_bar_color(self._disk_bar, disk_pct)

        # Temperature (optional)
        temp = info.get("temperature", "")
        if temp and temp != "0.0°C":
            self._temp_row._value_lbl.setText(temp)
            self._temp_widget.show()
        else:
            self._temp_widget.hide()

        # Uptime
        uptime = info.get("uptime", "—").replace("up ", "")
        self._uptime_row._value_lbl.setText(uptime)

        # Load
        load = info.get("load", "—")
        self._load_row._value_lbl.setText(load)

        # Active users
        users = info.get("users", "—")
        self._users_row._value_lbl.setText(users)

        # Processes — Linux' "ps aux | wc -l" includes a header line; Windows'
        # (Get-Process).Count is already exact.
        procs = info.get("processes", "—")
        if info.get("_detected_os") == "linux":
            try:
                procs = str(int(procs) - 1)
            except Exception:
                pass
        self._proc_row._value_lbl.setText(procs)

        # IP
        ip = info.get("ip", "—")
        self._ip_row._value_lbl.setText(ip)

        # Drives
        self._update_drives(info.get("drives_list") or [])

    def _on_error(self, msg: str, error_type: str = "generic"):
        self._set_loading_overlay_visible(False)
        if error_type == "auth_missing":
            self._state_card.hide()
            self._show_overlay_error(
                "key",
                tr("sysinfo.auth.missing.title"),
                tr("sysinfo.auth.missing.desc"),
            )
            self._refresh_btn.setEnabled(True)
            return
        if error_type == "key_missing":
            self._state_card.hide()
            self._show_overlay_error(
                "key-off",
                tr("sysinfo.key_missing.title"),
                tr("sysinfo.key_missing.desc"),
            )
            self._refresh_btn.setEnabled(True)
            return
        self._content.hide()
        self._state_card.show()
        self._state_pill.setText(tr("dialog.error"))
        self._state_pill.setProperty("connected", "false")
        self._state_pill.style().unpolish(self._state_pill)
        self._state_pill.style().polish(self._state_pill)
        self._error_lbl.setText(f"{tr('sysinfo.error')} {msg}")
        self._error_lbl.show()
        self._refresh_btn.setEnabled(True)

    def _on_close(self):
        self.closed.emit()

    def closeEvent(self, event):
        if self._refresh_timer:
            self._refresh_timer.stop()
        if self._info_thread:
            self._info_thread.stop()
            self._info_thread.wait()
        if self._loading_anim_timer and self._loading_anim_timer.isActive():
            self._loading_anim_timer.stop()
        event.accept()
