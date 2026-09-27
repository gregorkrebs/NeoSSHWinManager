"""
permission_repair.py – Detects and repairs a data directory the app can no
longer use, so that database._set_secure_permissions() can keep working.

Two things break access, and both are handled here:

* Wrong DACL. Versions 1.4.0–1.5.5 hardened %APPDATA%\\SSHWinManager down to a
  single ACE granting FILE_GENERIC_READ | FILE_GENERIC_WRITE — no FILE_TRAVERSE,
  no DELETE, no WRITE_DAC, and with SYSTEM and Administrators removed. On
  installs that do not hand out SeChangeNotifyPrivilege ("bypass traverse
  checking") that folder can no longer be opened at all, so the app crashed on
  every start and re-applied the same ACL after any manual icacls reset
  (GitHub issue #22). Fixing this needs WRITE_DAC only, which the owner always
  has implicitly — no elevation, no prompt.

* Wrong owner. Files created while running as the built-in Administrator
  account with UAC Admin Approval Mode disabled end up owned by the
  BUILTIN\\Administrators *group* instead of the user SID. Once Admin Approval
  Mode is enabled (or the account that created them differs from the one now
  running the app), the non-elevated token no longer carries that group, so
  even reading the DACL is denied. Taking ownership back requires
  SeTakeOwnershipPrivilege, which only an elevated token has — hence the UAC
  relaunch here.

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
    """SID of the account we actually run as (see database.current_user_sid)."""
    from src.database import current_user_sid
    return current_user_sid()


def is_accessible(root: Path) -> bool:
    """True if the app can still use its data folder and its database file.

    Ownership is only half the story: a DACL that grants the wrong SID — or
    grants ours too little, which is what older versions wrote — denies access
    to a folder we own perfectly well. Probe what actually matters instead of
    inferring it from the owner field (GitHub issue #22).

    Deliberately narrow: the folder plus data.db are the two paths startup
    needs. Probing every child would turn any unrelated file that happens to be
    locked by another process (updater, virus scanner) into a false alarm that
    pops the repair dialog on every start.
    """
    if sys.platform != "win32" or not root.exists():
        return True
    from src.database import _is_usable
    if not _is_usable(root):
        return False
    db = root / "data.db"
    return _is_usable(db) if db.exists() else True


def _children(root: Path) -> list[Path]:
    """Direct children of `root`, or [] if it cannot even be listed.

    Listing is itself an access-checked operation, and a locked folder is
    exactly the case this module exists for — it must not raise here.
    """
    try:
        return list(root.iterdir())
    except OSError as e:
        logger.warning(f"Datenordner nicht auflistbar: {root}: {e}")
        return []


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


def repair_owner(paths: list[Path], target_sid_str: str | None = None) -> bool:
    """
    Hand each path (recursing into directories) back to `target_sid_str`,
    defaulting to the user running this process: first the owner, then the
    DACL. Both are needed — ownership alone leaves a folder whose DACL still
    denies the user everything but WRITE_DAC, which is exactly the state that
    made the app crash on every start in GitHub issue #22.

    `target_sid_str` exists because the elevated relaunch below may run under a
    *different* administrator account than the user whose data folder is being
    repaired (a standard user typing admin credentials into the UAC prompt).
    Without it the repair would quietly hand the folder to that administrator.

    Taking ownership needs SeTakeOwnershipPrivilege, i.e. an already-elevated
    process; fixing only the DACL works unelevated as long as we own the files.
    This is the function the --repair-permissions relaunch invokes.
    """
    if sys.platform != "win32":
        return True

    _enable_privilege("SeTakeOwnershipPrivilege")
    _enable_privilege("SeRestorePrivilege")

    user_sid = None
    if target_sid_str:
        try:
            user_sid = win32security.ConvertStringSidToSid(target_sid_str)
        except Exception as e:
            logger.warning(f"Ziel-SID {target_sid_str} unbrauchbar: {e}")
    if user_sid is None:
        user_sid = _current_user_sid()
    if user_sid is None:
        logger.error("Rechte-Reparatur abgebrochen: keine Benutzer-SID ermittelbar.")
        return False

    # Only skip the post-write access check when repairing on behalf of someone
    # else — we cannot test their access, and ours would fail by design.
    own_sid = _current_user_sid()
    verify = own_sid is not None and own_sid == user_sid

    from src.database import _is_usable, _set_secure_permissions

    def fix(target: Path) -> bool:
        """Repairs one path and reports whether it is fixed, not whether every
        single step succeeded. Taking ownership is denied when the DACL grants
        us no WRITE_OWNER — including the common case where we already *are*
        the owner and only the DACL was broken — and failing the whole run over
        that would report a repair that plainly worked as a failure."""
        owned = _take_ownership_one(target, user_sid)
        try:
            _set_secure_permissions(target, user_sid=user_sid, verify=verify)
        except Exception as e:
            logger.error(f"ACL-Reparatur fehlgeschlagen für {target}: {e}")
            return False
        if verify:
            return _is_usable(target)
        # Repairing on somebody else's behalf (the elevated helper): their
        # access is not ours to test, so ownership is the only signal left.
        return owned

    ok = True
    for base in paths:
        if not base.exists():
            continue
        # The folder itself first: a folder we are locked out of cannot be
        # walked, so os.walk() would silently return nothing and leave every
        # file inside it broken.
        if not fix(base):
            ok = False
        if not base.is_dir():
            continue
        for root, dirs, files in os.walk(base):
            root_p = Path(root)
            for name in dirs:
                if not fix(root_p / name):
                    ok = False
            for name in files:
                if not fix(root_p / name):
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
    # Tell the elevated child who to repair *for*: if the UAC prompt is answered
    # with another administrator's credentials, the child runs as that account
    # and would otherwise take the folder away from the user who owns it.
    sid = _current_user_sid()
    sid_arg = ""
    if sid is not None:
        try:
            sid_arg = f' "{win32security.ConvertSidToStringSid(sid)}"'
        except Exception:
            sid_arg = ""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = f'--repair-permissions "{joined}"{sid_arg}'
    else:
        exe = sys.executable
        script = os.path.abspath(sys.argv[0])
        params = f'"{script}" --repair-permissions "{joined}"{sid_arg}'

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
    Best-effort: detect a data folder we can no longer use — because an older
    version wrote a DACL that locked us out, or because an install/update left
    the files owned by another account — and fix it before init_db() runs.
    Checked non-recursively (the folder itself plus its direct children), which
    is cheap and enough for this app's flat data folder.

    Repair order matters. Rewriting the DACL needs WRITE_DAC, which the owner
    always holds implicitly, so try that in-process first: in the common case
    (our own files, bad permissions) it fixes everything with no UAC prompt at
    all. The user is only asked for elevation when the folder is still
    unusable afterwards, i.e. when ownership really is the problem — an owner
    that merely differs while everything works is left alone rather than
    turned into a prompt on every start. Never raises — if everything fails,
    database.py's own best-effort hardening still degrades to a warning,
    exactly as before.
    """
    if sys.platform != "win32":
        return

    try:
        if not root.exists():
            return

        blocked = not is_accessible(root)
        if not blocked and not any(
            owner_mismatch(p) for p in [root] + _children(root)
        ):
            return

        logger.warning(
            f"Datenordner nicht nutzbar (Rechte/Eigentümer): {root} "
            f"(blockiert={blocked})"
        )

        from src.database import _set_secure_permissions

        # Step 1 – unelevated DACL repair. Works whenever we still own the
        # files, which covers the self-lockout older versions produced.
        # The folder goes first: while its DACL is broken its contents cannot
        # even be listed, so the children are only reachable afterwards.
        def unlock(p: Path) -> None:
            try:
                _set_secure_permissions(p)
            except Exception as e:
                logger.debug(f"ACL-Selbstreparatur fehlgeschlagen für {p}: {e}")

        unlock(root)
        for child in _children(root):
            unlock(child)
        if is_accessible(root):
            logger.info("Rechte-Reparatur ohne Elevation erfolgreich.")
            return

        # Step 2 – ownership is wrong, which only an elevated token can change.
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
