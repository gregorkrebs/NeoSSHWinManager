# Changelog

All notable changes to NEO SSH-Win Manager are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.5.1] — 2026-05-13

### Added
- Title bar in a unified design, matching the selected Dark/Light Theme

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
