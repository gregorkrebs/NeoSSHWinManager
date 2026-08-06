"""
permission_repair.py – Detects and repairs broken file ownership in the app's
data directory so that database._set_secure_permissions() can keep working.

Background: files/folders created while running as the built-in Administrator
account with UAC Admin Approval Mode disabled for it (Windows' default state
for that account) end up owned by the BUILTIN\\Administrators *group* instead
of the actual user SID. Once Admin Approval Mode is enabled for that account
(or on any machine where the account that created these files differs from
the one now running the app), the non-elevated token no longer carries that
group, so ACL hardening on those files starts failing with ERROR_ACCESS_DENIED.
Taking ownership back requires SeTakeOwnershipPrivilege, which only a properly
elevated token has — hence the UAC relaunch here.

This is written defensively: every public entry point is best-effort and never
raises past its own boundary. A user declining or a repair failing must not
block app startup — src.database's own permission hardening already degrades
to a warning log if this module doesn't fix things first.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from src.app_logger import logger

if sys.platform == "win32":
    import ctypes
    import win32api
    import win32security


def _current_user_sid():
    username = os.environ.get("USERNAME") or os.environ.get("USER")
    if not username:
        return None
    try:
        return win32security.LookupAccountName(None, username)[0]
    except Exception:
        return None


def owner_mismatch(path: Path) -> bool:
    """True if `path` exists on Windows and isn't owned by the current user."""
    if sys.platform != "win32" or not path.exists():
        return False
    try:
        sd = win32security.GetFileSecurity(
            str(path), win32security.OWNER_SECURITY_INFORMATION
        )
        owner_sid = sd.GetSecurityDescriptorOwner()
        current_sid = _current_user_sid()
        return current_sid is not None and owner_sid != current_sid
    except Exception as e:
        logger.debug(f"Eigentümer-Prüfung fehlgeschlagen für {path}: {e}")
        return False


def is_elevated() -> bool:
    if sys.platform != "win32":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _enable_privilege(name: str) -> None:
    try:
        htoken = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32security.TOKEN_ADJUST_PRIVILEGES | win32security.TOKEN_QUERY,
        )
        luid = win32security.LookupPrivilegeValue(None, name)
        win32security.AdjustTokenPrivileges(
            htoken, False, [(luid, win32security.SE_PRIVILEGE_ENABLED)]
        )
    except Exception as e:
        logger.warning(f"Privileg {name} konnte nicht aktiviert werden: {e}")


def _take_ownership_one(path: Path, user_sid) -> bool:
    try:
        sd = win32security.SECURITY_DESCRIPTOR()
        sd.SetSecurityDescriptorOwner(user_sid, False)
        win32security.SetFileSecurity(
            str(path), win32security.OWNER_SECURITY_INFORMATION, sd
        )
        return True
    except Exception as e:
        logger.error(f"Eigentümer-Übernahme fehlgeschlagen für {path}: {e}")
        return False


def repair_owner(paths: list[Path]) -> bool:
    """
    Take ownership of each path (recursing into directories) back to the
    current user. Must run from an already-elevated process — relies on
    SeTakeOwnershipPrivilege/SeRestorePrivilege being available in the token.
    This is the function the --repair-permissions relaunch below invokes.
    """
    if sys.platform != "win32":
        return True

    _enable_privilege("SeTakeOwnershipPrivilege")
    _enable_privilege("SeRestorePrivilege")

    user_sid = _current_user_sid()
    if user_sid is None:
        logger.error("Rechte-Reparatur abgebrochen: kein Benutzername ermittelbar.")
        return False

    ok = True
    for base in paths:
        if not base.exists():
            continue
        targets = [base]
        if base.is_dir():
            for root, dirs, files in os.walk(base):
                root_p = Path(root)
                targets.extend(root_p / d for d in dirs)
                targets.extend(root_p / f for f in files)
        for t in targets:
            if not _take_ownership_one(t, user_sid):
                ok = False
    return ok


def request_elevated_repair(paths: list[Path]) -> bool:
    """Relaunch this program with --repair-permissions via a UAC consent
    prompt, wait for it to finish, and report whether it succeeded."""
    if sys.platform != "win32":
        return True

    try:
        from win32com.shell import shell, shellcon
        import win32con
        import win32event
        import win32process
    except Exception as e:
        logger.warning(f"UAC-Relaunch-Module nicht verfügbar: {e}")
        return False

    joined = ";".join(str(p) for p in paths)
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = f'--repair-permissions "{joined}"'
    else:
        exe = sys.executable
        script = os.path.abspath(sys.argv[0])
        params = f'"{script}" --repair-permissions "{joined}"'

    try:
        proc_info = shell.ShellExecuteEx(
            nShow=win32con.SW_HIDE,
            fMask=shellcon.SEE_MASK_NOCLOSEPROCESS,
            lpVerb="runas",
            lpFile=exe,
            lpParameters=params,
        )
    except Exception as e:
        # Includes the user declining the UAC prompt (ERROR_CANCELLED).
        logger.warning(f"UAC-Elevation abgelehnt oder fehlgeschlagen: {e}")
        return False

    hproc = proc_info["hProcess"]
    try:
        win32event.WaitForSingleObject(hproc, 60_000)
        exit_code = win32process.GetExitCodeProcess(hproc)
    finally:
        win32api.CloseHandle(hproc)
    return exit_code == 0


def run_startup_check(root: Path) -> None:
    """
    Best-effort: detect broken ownership left over from an older install/
    update anywhere in `root` (checked non-recursively: the folder itself
    plus its direct children — cheap and enough for this app's flat data
    folder), offer a one-time elevated repair, then get out of the way.
    Never raises — any failure here just leaves database.py's existing
    best-effort permission hardening in its current (possibly degraded)
    state, exactly as before this module existed.
    """
    if sys.platform != "win32":
        return

    try:
        if not root.exists():
            return
        candidates = [root] + list(root.iterdir())
        if not any(owner_mismatch(p) for p in candidates):
            return

        logger.warning(f"Eigentümer-Problem erkannt (Update/altes Profil?): {root}")

        from src.i18n import tr
        from src.ui.dialogs.styled_message_box import StyledMessageBox

        confirmed = StyledMessageBox.question(
            None,
            tr("permrepair.title"),
            tr("permrepair.body"),
            yes_text=tr("dialog.yes"),
            no_text=tr("dialog.no"),
        )
        if not confirmed:
            logger.info("Nutzer hat die Rechte-Reparatur abgelehnt.")
            return

        ok = repair_owner([root]) if is_elevated() else request_elevated_repair([root])
        logger.info(f"Rechte-Reparatur {'erfolgreich' if ok else 'fehlgeschlagen'}.")
    except Exception as e:
        logger.error(f"Rechte-Reparatur-Check fehlgeschlagen: {e}")
