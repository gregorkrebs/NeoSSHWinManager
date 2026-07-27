# Changelog

All notable changes to NEO SSH-Win Manager are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [1.5.2] — 2026-07-27

### Added
- **CLI companion executable restored:** `NeoSSHWinManager-cli.exe` (console subsystem, `cli_main.py`) is back in the build (`NeoSSHWinManager-cli.spec`, `build_dual.ps1`) after being dropped from distribution in 1.5.1. Lets a saved connection with CLI access enabled be reached non-interactively via `NeoSSHWinManager-cli.exe --connect-cli <access_key> [--exec "command"]` while the main GUI is running and logged in. The GUI's own build stays a standalone onefile executable, unaffected.
- **FTP and FTPS support:** Connections now carry a protocol (SFTP / FTPS / FTP). The file browser speaks all three — the new `src/ftp_client.py` implements FTP over `ftplib` with explicit TLS (AUTH TLS, port 21), implicit TLS (port 990) and plain unencrypted FTP, MLSD listings with a LIST fallback for older servers, passive/active mode, progress-reporting up- and downloads and automatic re-login after an idle timeout.
- Add/Edit form gained a protocol selector plus FTP options (implicit TLS, passive mode, certificate verification); the port follows the protocol default (22 / 21 / 990) unless a custom port was entered, and SSH-only fields (key file, drive letter, CLI access, PuTTY key) are hidden for FTP connections.
- Plain-FTP connections can be handed to the on-board Windows Explorer FTP client from the card context menu (the password stays out of the URL — Explorer asks for it).

### Changed
- FTP/FTPS connections cannot be mounted as a drive and have no SSH terminal: their card shows a protocol badge and opens the file browser, and mount/terminal/system-info actions report that they are unavailable instead of failing later.
- Database migrations now run each `ALTER TABLE` independently, so one column that SQLite refuses (e.g. adding a `UNIQUE` column to an old table) no longer silently skips every migration after it.

### Fixed
- **SSHFS write corruption:** Files could end up as pure NUL bytes after writing/overwriting through a mounted drive. Caused by `FileInfoTimeout=-1`, which turns on WinFsp's write-back file *data* caching; a hard-killed `sshfs.exe` (e.g. on unmount) could drop not-yet-flushed pages and leave the server-side zero-fill in place. Mounts now use a finite `FileInfoTimeout`, synchronous SFTP writes (`sshfs_sync`) and disabled read-ahead (`no_readahead`) instead.
- **New folders/files invisible until refresh:** `sshfs.exe` carries its own directory-entry cache (`dir_cache`/`dcache_dir_timeout`, default 20s) entirely separate from — and underneath — the WinFsp-side cache timeouts this app already sets, so the existing "disable directory cache" setting never fully applied. Mounts now also tune the sshfs-side cache (fully disabled when that setting is on, tightened to match otherwise).
- **"New Folder"/new file silently duplicated 4x in Explorer:** on a mounted drive, creating an item in Windows Explorer could appear to fail (no rename prompt) and then show up to 4 times after a manual refresh. Root cause is an upstream WinFsp/Windows security-token mismatch (`TokenUser` vs `TokenOwner`) that only affects the built-in Administrator account when UAC Admin Approval Mode is disabled for it (Windows' default for that account) — not fixable from the app's mount options. Documented for anyone else hitting it: enable "User Account Control: Admin Approval Mode for the Built-in Administrator account" (`secpol.msc` or `FilterAdministratorToken=1`) and log back in.
- **Startup crash after fixing the account-token issue above:** files created earlier under the affected account end up owned by the `BUILTIN\Administrators` group instead of the user; once that account's token no longer carries the group, the app's own permission-hardening (`SetFileSecurity`) started failing with access denied and crashing startup. That call is now best-effort (logs a warning instead of crashing), and the app now detects this exact ownership mismatch on its own at startup and offers a one-time, UAC-elevated automatic repair (`src/permission_repair.py`) — so anyone hitting this after an update or reinstall gets a guided fix instead of a crash.
- **CLI access key could never match, for any connection:** `get_by_cli_key()` re-encrypted the incoming key with a fresh random AES-GCM IV and compared the result against the stored ciphertext — which uses a different random IV from when the key was originally saved, so the comparison could never succeed even for the correct key. Lookup now uses a deterministic `cli_access_key_hash` (SHA-256 of the plaintext key) instead; existing connections get this hash backfilled automatically on next login.
- **CLI SSH connections always rejected:** `launch_ssh_in_current_terminal()` (used by `--connect-cli`) set a `RejectPolicy` host-key policy but never actually loaded `known_hosts` into paramiko first, so every connection was rejected as "unknown host" regardless of what was already trusted on disk. Now loads the same `known_hosts` file the rest of the app uses before checking the policy.

### Security
- CLI access over `--connect-cli` now also works for password-authenticated connections: the local IPC response includes the password (previously withheld per an earlier finding). The pipe was already restricted to the current user's SID (`_make_pipe_security_attributes`), the 64-byte access key itself is a strong bearer secret, and requests are already rate-limited per PID — sending the password over this already-restricted channel was the missing piece for a CLI feature whose whole purpose is unattended access to saved connections, not an added exposure.

---

## [1.5.1] — 2026-07-04

### Added
- **Integrated in-app terminal:** New `xterm.js`-based SSH terminal embedded directly in the app (via `QWebEngineView`/`QWebChannel`, bridged to a local WebSocket server), selectable in Settings alongside the existing external SSH/PuTTY launchers. Supports multiple concurrent sessions per connection with a tab bar, background persistence when switching panels, and a reconnect button after disconnect.
- **Native SFTP browser:** New file-browser window (`src/ui/sftp_browser.py`) reachable from the connection card once a host is mounted — directory navigation, upload/download with progress, rename, delete and new-folder, all run off the UI thread via dedicated worker threads.
- **Pro license system:** Machine-fingerprint based activation (`src/pro_manager.py`) with an offline, HMAC-verified license check and a new "Pro License" section in Settings. The free tier is capped at 3 concurrent integrated-terminal sessions; exceeding it surfaces an upgrade prompt.
- **Connection templates & duplicate-name detection:** Add/Edit dialog gained a template dropdown (save/apply/delete) and now blocks duplicate connection/template names, auto-suggesting a unique alternative.
- **Connection card context menu:** Right-click menu for mount/unmount, open in Explorer, open SFTP browser, and connect via OpenSSH/PuTTY/integrated terminal.
- **Logout confirmation dialog:** Choose between staying logged in, quitting while keeping drives mounted, or quitting and unmounting everything.
- **Startup prerequisite check:** Blocks launch with download links if WinFsp and/or SSHFS-Win are not installed.
- **Settings:** New terminal-backend selector (SSH/PuTTY/integrated xterm) and a toggle to disable SSHFS attribute/directory caching for hosts where stale cache data is an issue.
- New GitHub Actions release-build workflow and a nightly version/push helper script for the release process.

### Changed
- The connection card's SSH button now opens the integrated terminal when that backend is selected in Settings, falling back to the external client otherwise; "open mounted path" now opens the new SFTP browser instead of the system file explorer directly.
- Title bar redesigned with a unified look matching the selected Dark/Light theme; accent color updated app-wide (`#00b4d8` → `#0077b6`).
- SSHFS mounts now set explicit WinFsp attribute/directory/volume-info cache timeouts (tightened further when caching is disabled), and unmounting escalates to force-killing a stuck `sshfs.exe` process after a 10s grace period.
- Password-based `SSH_ASKPASS` hardening (one-time IPC token instead of plaintext env var) now applies starting at security level 1 instead of requiring level 2, for both the native SSH launcher and PuTTY.
- System tray "Quit" now routes through the same mount-cleanup/logout confirmation flow as the main window instead of calling `QApplication.quit()` directly.
- Frameless window resize-cursor handling now works correctly when the mouse is over child widgets, not just the window frame itself.
- Build: CLI companion executable dropped from `build_dual.ps1` (GUI-only distribution going forward); PyInstaller build now strips symbols and excludes unused stdlib modules (tkinter, unittest, pytest, etc.) to reduce executable size.

### Security
- `get_user_by_username` no longer selects sensitive columns (password hash/salt, encrypted key) it doesn't need, reducing accidental exposure of credential material in memory.
- Admin-only account operations (password reset, delete user, list users) now enforce authorization at the `auth_manager` layer instead of relying solely on UI-level gating.
- Login lockout timers switched from monotonic to wall-clock time so a lockout can no longer be bypassed by restarting the app.
- The updater validates executable/update file paths before embedding them in its self-replace script, and now verifies a SHA-256 checksum of the downloaded update before applying it (falls back to a warning if the release provides no checksum).
- Telemetry action parameters are now URL-encoded before being sent, closing a parameter-injection edge case in the query string.
- Terminal and SFTP sessions use single-use, expiring session tokens, wipe passwords from memory immediately after use, and bind the local bridge server to loopback only; both features share the same TOFU host-key verification and confirmation dialog used elsewhere in the app.
- The Pro license validation secret (`neo_pro_validate.php`) is excluded from the repository.

### Fixed
- Second app launch now correctly restores/focuses the main window even when it was hidden to the system tray, instead of doing nothing.

---

## [1.5.0] — 2026-05-11

### Added
- Connection groups/tags and reusable templates across the data model, database migration, add/edit flows and translations
- Bulk mount/dismount actions and a group filter in the main connection header
- Dedicated profile panel for end users to review their account and change their password
- Manual GitHub update checks with download progress and an install-on-exit flow
- Telemetry opt-in prompt, persisted telemetry settings and asynchronous telemetry submission

### Changed
- Reworked the main window, settings screen and right-panel forms for the 1.5.0 release layout
- Connection cards now show group pills and compact host details with the drive letter in the subtitle
- Add/Edit connection flows now support templates explicitly and surface group metadata in the UI
- Replaced many native message boxes with a themed custom dialog for warnings, confirmations and success messages
- Pinned core Python dependency versions for the 1.5.0 release environment
- Updated visible application version strings in the main window, about dialog and single-instance mutex
- Reduced debug logging of sensitive command-line arguments in the PuTTY launcher
- Hardened in-memory handling of temporary password tokens used by SSH ASKPASS

### Security
- Hardened SSH_ASKPASS password exchange by replacing plaintext environment transfer with one-time IPC tokens
- Relaxed first-contact host-key handling to OpenSSH `accept-new` for SSH and sysinfo flows while keeping changed-host failures
- Increased minimum password length from 6 to 8 characters in registration and user-management flows
- Restricted crash report file permissions so stack traces are no longer world-readable
- Masked PuTTY password arguments in debug logs to prevent credential leakage

### Fixed
- Added password fallback when a stored SSH key fails but a password is still available for the same connection
- Unified destructive confirmation prompts and dirty-form handling through the styled dialog layer
- Corrected multiple German translation strings and save-label spellings used in the 1.5.0 UI

---

## [1.4.0] — 2026-05-09

### Security
- **Comprehensive Security Audit:** Hardened credential storage, session handling, encryption routines and key derivation across `auth_manager`, `crypto`, `database`, `ssh_launcher` and `sshfs_controller`
- **CWE-312 · Connection Metadata Encryption:** Host, username, connection name and remote path are now encrypted with AES-256-GCM (using the per-user `enc_key`) before being stored in the database. Existing entries are migrated automatically on first login. Plaintext columns are zeroed out after migration — the SQLite file no longer exposes server addresses or usernames at rest.
- **CWE-732 · Windows ACL hardened:** `win32security` is now a hard module-level import (was: optional with silent fallback). A missing `pywin32` installation now raises an explicit `ImportError` on startup rather than leaving the database file world-readable. 5 new unit tests verify ACL correctness.
- **CWE-307 · Brute-Force Protection:** Login attempts are now rate-limited per username. After 5 consecutive failures the account is locked for 30 seconds; each subsequent block escalates (10 attempts → 10 min, 5 → 1 h, and further). The counter resets on successful login.
- **CWE-362 · Session Race Condition fixed:** `Session._current_user` is now protected by a `threading.RLock`. The `enc_key` update after a password change is performed atomically via `Session.update_enc_key()` — concurrent access can no longer observe a partially updated session object.
- **CWE-591 · Memory-Lock failures now visible:** `mlock_memory()` / `munlock_memory()` previously returned `False` silently on failure. Both functions now emit a `WARNING` log entry explaining that secrets may be swapped to disk.
- **CWE-214 · CLI Key via stdin:** `--connect-cli -` now reads the access key from stdin instead of the command line, preventing exposure in process listings and shell history. The argument form still works for backwards compatibility.
- **CWE-78 · Shell Injection Prevention:** Removed unsafe shell interpolation in `ssh_launcher`; added `_is_safe_label()` validation in `sshfs_controller` to block injection via mount labels. SSH terminal now launched via `cmd.exe` + `CREATE_NEW_CONSOLE` instead of `shell=True`.
- **CLI Keys Migration:** Plaintext CLI-access-keys are automatically encrypted on first login after the update — closes the legacy plaintext storage path.
- **SSH_ASKPASS for Password Auth:** Password-based SSH connections pass the password via the `SSH_ASKPASS` environment mechanism — the password is never exposed in the process list.
- **Connection Name Validation:** Connection names are validated on save; names containing shell metacharacters are rejected before database insertion.
- **MITM Fix (v1.3.1 omission corrected):** The change from `StrictHostKeyChecking=no` to `StrictHostKeyChecking=yes` in `ssh_launcher.py` was applied in v1.3.1 but not documented. Any installation running v1.3.0 or earlier is vulnerable to trivial MITM attacks on SSH connections — upgrade immediately.

### Features
- **PuTTY PPK Integration:** Auto-detection and configurable PPK key path for PuTTY-based connections
- **Native SSH Terminal Improvements:** Overhauled terminal launch logic in `main_window` for both PuTTY and native OpenSSH
- **SysInfo available with key or password:** System information is now retrieved whenever an SSH key or stored password is configured — the security level setting no longer gates sysinfo access. Password auth uses `SSH_ASKPASS_REQUIRE=force` for non-interactive, secure credential passing.
- **SysInfo Auth Overlay:** When neither key nor password is configured, a 🔑 overlay with a clear explanation is shown instead of a generic error.
- **Login Lockout Countdown:** After a tier-boundary lockout, the login form shows a live countdown (1 s tick) with human-readable time remaining. Input fields and the submit button are disabled for the full lockout duration.
- **Login Button gated on input:** The Sign-in button is disabled until both username (≥ 1 char) and password (≥ 1 char) fields are filled, preventing the misleading "fill all fields" error when submitting wrong credentials.
- **About Dialog Redesign:** Card layout with grouped clickable link buttons for project, documentation, GitHub and author links
- **Sidebar About Button:** Persistent About button added to the sidebar (always visible between Debug and Logout)

### Fixed
- **SSHFS Mass Disconnect Bug:** Fixed a race condition in `sshfs_controller` that caused all mounted drives to disconnect simultaneously
- **Drive Unmount Crash:** Prevented a crash when a drive was unmounted while the UI still held a reference to it (#1)
- **QMessageBox Dark Mode:** Corrected background color of message boxes in dark mode (#3)
- **F2 Crash on Non-Standard Widgets:** Prevented crash when pressing F2 on widgets that don't support the debug inspector (#4)
- **Form Scroll Behavior:** Fixed scrolling in Add/Edit connection dialog on smaller screens
- **Copy Button in Error Popup:** Icon in the error popup copy button was misaligned due to incorrect CSS object name — fixed to use icon-only button style
- **PuTTY Error Messages:** PuTTY terminal error messages (password login disabled, password missing) are now fully translated and available in English and German
- **Crash Report Path:** Crash reports are now written to `%APPDATA%\SSHWinManager\crash_report.txt` instead of the working directory
- **Worker Thread Error Propagation:** Mount and unmount worker threads now catch exceptions and emit a `MountResult` error instead of crashing silently

### Changed
- **Add/Edit Dialog:** Live validation and allowed-character hint for connection name field
- **Theme:** Extended styling for new UI components; corrected dark mode inconsistencies; THEME_COLORS dict extracted for native Qt popup palette sync
- **Translations (EN/DE):** Added i18n keys for brute-force lockout countdown, sysinfo auth-missing state, PuTTY errors, About dialog and new overlay states
- **Removed:** Legacy build spec files (`NeoSSHWinManager-cli.spec`, `NeoSSHWinManager.spec`)

---

## [1.3.1] — Earlier

(Earlier releases documented separately if needed)
