# Changelog

What changed in each version of NEO SSH-Win Manager, newest first.

Each release starts with what changes for you when you update. The full technical notes, for contributors and anyone tracking a particular fix, are in the "Technical details" block below it.

Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html): the middle number goes up for new features, the last one for fixes only. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.6.0] — 2026-09-27

The biggest update so far: Windows servers now work throughout the app, and the file browser has been rebuilt from scratch and moved into the main window.

### Highlights

- **Full support for Windows servers.** Servers running OpenSSH for Windows now work everywhere in the app, not only in the terminal:
  - Browse, upload and download files. The file browser opens in your Windows home folder and understands Windows paths such as `C:\Users\me` or `W:\data`.
  - Mount a Windows server as a drive, including a subfolder such as `C:\Projects`. Mounting `/` now gives you your home folder instead of a list of drive letters that Explorer cannot show.
  - System info shows the Windows version, CPU, memory and the server's drives, just like on Linux.
  - Packing and extracting archives, "Fetch from URL" and "Open terminal here" use PowerShell on Windows servers.
- **A completely new file browser, built into the main window.** Open it with the new folder button in the sidebar, or from any host.
  - All your hosts in one place, each in its own tab. "Connect" (Ctrl+Shift+O) opens another saved host without leaving the browser.
  - This PC and the server side by side (F9), with drag & drop between them, optional folder trees and a clickable path bar that also accepts dropped files.
  - A transfer queue you can pause, resume, cancel and retry. Interrupted transfers continue where they stopped, and a dropped connection reconnects on its own.
  - Undo and redo (Ctrl+Z / Ctrl+Y) for moves, renames and new folders.
  - When a file already exists, you choose: overwrite, skip, keep both, or compare the two files first.
  - Files open in the program of your choice, and saving uploads them back to the server.
  - Folder sync with a preview, archives packed and extracted on the server, files fetched from a web address straight onto the server, permissions and folder sizes.
- **No more limit on terminal sessions.** The integrated terminal used to allow three sessions at a time. That limit is gone, and the Pro licence section has been removed from the settings.
- **No more crash on startup on security-hardened Windows systems** ([#22](https://github.com/gregorkrebs/neosshwinmanager/issues/22)). Versions 1.4.0 to 1.5.5 could lock themselves out of their own data folder and then crash on every start. 1.6.0 repairs the folder permissions on its own, usually without asking anything.

### Also new

- A "..." row at the top of every folder list takes you one level up.
- Moving files or folders by drag & drop asks before it moves anything. You can switch the question off, and back on under Settings → View.
- The server folder tree starts at the connection's folder, so it also works for hosting accounts that may not open `/` or `/home`.
- If you agreed to the anonymous usage statistics, they now also include which interface language you use, so we can see which translations matter. Nothing is sent without your consent. The consent dialog now lists exactly what is sent and appears in your language.

### Improved

- The status row in the connection panel:
  - The green "Connected" badge and the green folder open the drive in Explorer.
  - A grey folder means "not mounted"; one click mounts the connection.
  - A second folder marked "FTP" opens the file browser.
- The unmount button is now red, so it is clear that it disconnects.
- System info on Linux reads memory and disk sizes more reliably, and no longer shows "Loading…" behind its loading popup.
- The first system info request to a new host no longer ends in an error.

### Fixed

- The file browser turned many hosts away with "Host key was rejected" without asking. It now asks, showing the fingerprint of the key the server actually presents, and warns clearly when a known host's key has changed.
- Opening the file browser again for a host that failed to connect now tries again.
- The permission repair offered at startup could not fix the problem behind the crash above. When it was confirmed with a different administrator's password, it could also hand the data folder to that administrator. Both are fixed. If the folder still cannot be opened, the app now explains how to fix it instead of crashing.

### Removed

- The old SFTP browser window, replaced by the new file browser.

<details>
<summary>Technical details</summary>

1.5.6-dev was a test build for issue #22; its fixes are part of this release.

#### File browser (`src/filebrowser/`)

- **A page of the main window.** `FileBrowserView` (`src/filebrowser/ui/view.py`, a `QWidget`) is page 2 of the main window's stack, created on first use and kept until the app quits. Leaving the page only hides it: connections and transfers keep running, also while the window is minimised to the tray. `shutdown()` disconnects everything when the app quits, after the main window has asked about running transfers.
  - While the page is shown, the main window's own shortcuts (F2, Del, Esc, Ctrl+S/N/E) are disabled; otherwise Qt would treat the browser's F2/Del as ambiguous and trigger neither.
  - "Open terminal here" switches back to the connections page, where the terminal lives.
  - A theme switch re-colours the browser in place (`set_theme()`); hosts stay connected.
  - Sidebar button with the host panel's "FTP" folder icon, tooltip `sidebar.file_browser`.
- **One browser for all hosts.** "Connect" (Ctrl+Shift+O) opens any saved connection in a new tab. Opening the browser from the main window adds the host as a tab, or brings its tab to the front if it is open already.
  - Tabs of the same host share one login, one transfer queue and one undo history. The transfer list and log show the host of every job.
  - Closing a host's last tab logs out of it; the browser stays open and can connect again.
  - A host that fails to connect keeps its tab, with the error and a "Connect again" button.
- **Split mode** (one click or F9): this PC on the left (starts in `C:\`), the server on the right, transfers by drag & drop, F6 or context menu. The divider goes all the way to either edge and folds that side away. Both sides shrink to about the same width: the path bar moves leading segments into a "…" menu instead of demanding the width of the whole path.
- **Optional folder trees** on the outer sides, loaded lazily and showing folders and files.
- Tabs, clickable breadcrumbs with typed paths, per-connection bookmarks, a filter field, multi-selection, and mouse back/forward buttons.
- A "..." row at the top of every list leads one level up (double-click or Enter), and files dropped onto it go to the parent folder. It stays on top in every sort order, is never filtered away, and is not counted or selected as a file.
- The full set of standard shortcuts: F2, F5, Del, F7, Alt+Enter, Ctrl+L, Ctrl+F and more; F1 lists them all.
- **Transfer queue** with separate limits for parallel uploads and downloads, and upload/download speed limits. Pause, resume, cancel and retry are available per job, alongside a transfer log with CSV export.
  - SFTP transfers run over extra channels of one SSH login; FTP uses a small session pool.
  - Interrupted transfers resume from their offset (SFTP seek, FTP `REST`/`APPE`), and a dropped connection is re-established automatically.
  - Timestamps are preserved; optional SHA-256 verification runs after each transfer.
- **Conflict dialog** with overwrite, skip, keep both (`name_1.ext`, counting up), resume, and "apply to all" for the current action.
  - "Compare" shows both files side by side with metadata on top: text files as a line diff, images as previews, binaries as an identical/different check.
- **Open with**: files open in the program chosen for their extension. The program is asked for once per extension and remembered; the mapping can be edited under Settings → Programs. Saving a file uploads it back, with a warning if the server copy changed in the meantime.
- **Fetch from URL** (upload menu, Ctrl+Shift+L) puts a file from the web onto the server. The server downloads the file itself (curl/wget, PowerShell on Windows) or it is streamed through the PC without a temporary file. Only `http`/`https` URLs are accepted.
- **Server-side archives** via SSH exec for Linux and Windows servers: pack, extract, upload a folder as one archive, and download as an archive.
  - Windows commands are shipped as PowerShell `-EncodedCommand` and call `System32\tar.exe` explicitly, never a GNU tar from `PATH`.
- **Folder sync** (upload, download or both directions, optional mirror delete) with a preview list before anything runs.
- **Other tools:** properties dialog with a chmod editor and folder size; duplicate; copy path; new empty file; "Open terminal here", which starts an integrated terminal session already `cd`'d into the folder.
- **Drag & drop onto the path bar and the folder tree.** Files and folders can be dropped onto any path segment, for example the parent folder, or onto a folder in the tree; the target is highlighted while dragging. Collapsed tree folders open when the drag rests on them. The same move works on the local side in split mode.
- **Undo / redo** (Ctrl+Z, Ctrl+Y / Ctrl+Shift+Z, toolbar and context menu) for moves, renames, and new folders or empty files. Undoing a new folder or file only removes it while it is still empty. Items that can no longer be undone are reported and dropped from the history. Panes and tabs inside a moved folder follow it.
- **Confirmation before moving by drag & drop**, with "Don't ask again". The question can be switched back on under Settings → View.
- The server folder tree starts at the connection's path, or the account's login folder when none is set, instead of `/`. Many hosting accounts may not list `/` or `/home`, so the tree could never be opened down to their own folder. A setting shows the tree from `/` again.
- Browser settings are stored per user in two new encrypted `app_settings` columns (`sftp_browser_enc`/`_iv`), separate from the regular settings form so that neither can overwrite the other.
- Tab close buttons are drawn in the theme's colours with room to their right; Qt's white tab-bar base line is switched off.
- A listing that finishes after its tab was closed no longer shows a "Server connection dropped" error.
- `src/ui/sftp_browser.py` and `src/ui/sftp_worker.py` are removed (superseded by `src/filebrowser/`).

#### Windows servers

- **Windows OpenSSH servers are detected** from the SSH banner without logging in (`src/remote_os.py`).
  - The file browser starts in the user's home and accepts Windows paths (`W:\data`, `src/remote_path.py`).
  - SSHFS mounts accept Windows subpaths; mounting `/` on a Windows server mounts the home folder instead of the drive list, whose `C:`-style names Explorer cannot display.
- **System info supports Windows servers** (PowerShell/CIM) and lists attached drives with usage:
  - Linux: mounted block devices; tmpfs, loop, network and FUSE mounts are skipped.
  - Windows: lettered volumes on a disk partition; mapped UNC, SSHFS/WinFsp and `subst` drives are skipped.
  - USB devices are marked as external.
- Linux system info reads memory and disk as raw KiB figures and formats them itself, instead of splitting localized `free -h`/`df -h` output.
- The host key is added to `known_hosts` before the system-info SSH call, so a first-time host no longer shows an error.

#### Host keys

- **The file browser rejected hosts whose key it could have verified or asked about.** Unknown hosts were fingerprinted with a separate `ssh-keyscan` run. When that run returned nothing, for example after a timeout, the connection failed with "Host key was rejected" without asking. The fingerprint it did show was of whichever key `ssh-keyscan` listed first, not necessarily the key that was then trusted. The question now shows the fingerprint of the key the server actually presented during the connection.
  - Every key type stored in `known_hosts` for the host is preferred during negotiation. paramiko's own check only prefers the first stored type and fails when the server picks another one.
  - A changed key is refused with an explicit warning that names the `known_hosts` file.
  - New entries are written with LF line endings on a fresh line.

#### Pro, telemetry, About

- Pro is switched off in the UI: `SHOW_PRO_UI = False` hides the licence section in the settings, and `FREE_TERMINAL_SESSION_LIMIT = None` removes the three-session limit of the integrated terminal (both in `src/pro_manager.py`). Activation, the licence check and the `pro_licenses` table are unchanged, so both can be switched on again there. Opening the settings no longer runs the licence check (it queries `wmic`).
- Telemetry sends a `language` query parameter (`i18n.current_language()`: `en`, `de`, `es`, `ru`, `nl` or `ar`) with every event. The stats server stores it in a new `events.language` column, added automatically to existing databases; values that are not a language code are stored empty rather than rejected.
- The telemetry consent dialog is translated into all six languages (it was German only) and, like the settings hint, lists everything that is sent: install/login/update counters, app version and interface language.
- About window: author website `https://www.gregorkrebs.dev`; the docs link is `/de/docs/erste-schritte` for a German interface and `/en/docs/getting-started` otherwise (`docs_url()`). The "Additional contributors" entry and the second author link are gone.

#### Connection panel

- The status row in the connection panel now works like this:
  - The green "Connected" pill and the green folder open the mounted drive in Explorer.
  - The folder is always shown: grey while unmounted, where a click mounts the connection.
  - A second, always-visible folder marked "FTP" opens the file browser.
- The unmount dash is red, both in the list and in the panel header.
- System info no longer shows a "Loading…" text behind the loading popup.

#### Fixed (issue #22 and permission repair)

- **The app locked itself out of its own data folder on startup and then crashed on every launch (GitHub issue #22, affects 1.4.0–1.5.5).** The CWE-732 ACL hardening introduced in 1.4.0 replaced the DACL on `%APPDATA%\SSHWinManager` and `data.db` with a single ACE granting the owner `FILE_GENERIC_READ | FILE_GENERIC_WRITE` — a mask that omits `FILE_TRAVERSE`, `DELETE` and `WRITE_DAC`, and that removed SYSTEM and Administrators entirely. Without `FILE_TRAVERSE` nothing inside the folder can be opened on any installation that does not hand out `SeChangeNotifyPrivilege` ("bypass traverse checking"), which security-hardened Windows 10 policies routinely withhold: startup died with `GetFileSecurity: Access denied` (1.5.2) or `sqlite3.OperationalError: unable to open database file` (1.5.3–1.5.5). Without `WRITE_DAC` the next start could not undo it, and because the app re-applied the same ACL on every launch, a manual `icacls /reset` held only until the next start. Removing Administrators is why launching as administrator did not help either. The owner ACE now grants full access (SYSTEM included — it can take ownership of any file regardless, so excluding it bought no security), directory ACEs are inheritable, and hardening that would cost the app access to its own data is detected and rolled back instead of persisted. Other users on the machine still have no access to the credential database.
- **The permission repair could not repair permissions.** `repair_owner()` only ever rewrote the *owner* field, never the DACL, so it had no effect on the failure above — hence "regardless of whether you click Yes or No, the app crashes" in the report. It now resets the DACL as well. The startup check also tests whether the folder is actually usable instead of inferring it from the owner field, and repairs what it can in-process first: rewriting a DACL only needs `WRITE_DAC`, which the owner always holds implicitly, so the common case is fixed silently with no UAC prompt and no dialog at all.
- **An elevated repair could hand the data folder to the wrong account.** If the UAC prompt was answered with a *different* administrator's credentials, the elevated helper took ownership for that administrator, since it read `%USERNAME%` from its own environment. The user's SID is now passed to the helper explicitly (`--repair-permissions "<paths>" "<sid>"`).
- The current user's SID is read from the process token instead of being looked up from `%USERNAME%`. The environment variable is inherited from whatever started the app and can resolve to a different account (renamed account, a domain account sharing the name, `runas`, a scheduled task) — writing an owner-only DACL for the wrong SID is what makes the lockout permanent.
- A data folder that still cannot be opened after the repair now explains the problem, names the folder and gives the `takeown`/`icacls` commands to fix it, instead of crashing with a stack trace into `crash_report.txt`.
- Opening the file browser again for a connection whose first attempt failed now retries the connection instead of only raising the old window.

</details>

---

## [1.5.5] — 2026-08-16

### What changes for you

- **See what ran over the command-line tool.** A new "View CLI history" button in the connection details lists every command run through `NeoSSHWinManager-cli.exe` with its output and exit code, and complete interactive sessions. The history can be downloaded as a text file and is stored encrypted.
- **Mounted drives stay mounted.** Drives no longer disappear on their own, and disconnecting works reliably.
- **The command-line tool is dependable in scripts.** It now reports failures through its exit code, its output can be redirected to a file, and long commands are no longer cut off after 30 seconds.

<details>
<summary>Technical details</summary>

#### Added

- **CLI history: what was run over the CLI companion is now visible in the app.** Every `NeoSSHWinManager-cli.exe` invocation against a saved connection is recorded and can be reviewed inside the GUI — both `--exec` calls (command, output, exit code) and interactive sessions (full screen transcript). A new "View CLI history" button in the connection details opens a dedicated panel (`src/ui/cli_history_panel.py`) listing entries newest first — a Session/Command badge, timestamp (start–end for sessions), the command line and its exit code, with the output collapsed until clicked so long histories stay scannable — plus "Download as .txt" for the complete history and "Clear history". UI strings ship in all six supported languages.
- History entries are stored in a new encrypted `cli_history` table: command and output are encrypted with the same per-user key as connection passwords, never written in plaintext, and are capped at 500 entries per host (oldest pruned by insertion order) and 256 KB per entry to bound database growth. The CLI process never holds the GUI session's encryption key, so it hands the entry to the running GUI instance over the existing user-restricted IPC pipe (new `cli_log` action, same access-key check and per-PID rate limit as `cli_connect`), which does the encrypting and storing.
- Interactive session transcripts are rendered the way the screen actually looked rather than dumped as a raw byte stream: backspace and DEL now delete the character to the left instead of leaving `\x08` litter in the log after a typo, and a bare carriage return repositions the cursor instead of being treated as a newline — so progress bars (pip, apt, curl, docker pull, npm) show their end state instead of one line per redraw. ANSI/VT100 escape sequences are stripped. Recording is strictly best-effort and fully exception-swallowed; it can never affect the SSH session, its exit code, or its runtime.
- `NEOSSH_EXEC_TIMEOUT` (seconds) sets an optional time limit for `--exec`; unset means no limit.

#### Fixed

- SSHFS drives no longer disappear because their long-running process lost or blocked on GUI-owned debug pipes. Mounts now run in foreground mode with parent-independent standard handles, retain their process handle, and require a free drive letter that becomes stably available.
- Disconnect now finds the exact SSHFS process through the bundled psutil dependency instead of the deprecated WMIC command, treats an already absent drive as success, and cancels stale Explorer label updates that could create ghost-drive entries.
- **The CLI tool always exited with code 0, even when nothing worked.** `launch_ssh_in_current_terminal()` returned nothing and `cli_main.py` reported success unconditionally, so a failed connection, a rejected host key or a failed authentication was indistinguishable from a successful run — scripts calling the CLI could not detect failure at all. The function now returns an exit code, and `--exec` propagates the *remote command's* exit status (via `recv_exit_status()`) instead of discarding it.
- **`--exec` output was lost whenever the caller redirected stdout.** Output was written to the `CONOUT$` console screen buffer through `WriteFile`, which is not the process's stdout: `NeoSSHWinManager-cli.exe --connect-cli … --exec "…" > out.txt` reported success and produced an empty file. Non-interactive mode now writes exclusively to the real process streams, and the interactive path falls back to them if no valid console handle exists instead of writing into the void.
- **`--exec` aborted after 30 seconds.** The hardcoded timeout was too short for anything substantial (test runs, `npm install`, backups) and cut execution off mid-command; `ssh` itself imposes no such limit. There is no default limit anymore — see `NEOSSH_EXEC_TIMEOUT` above.
- `--exec` status messages ("Connecting to …") went to stdout and contaminated the command output that scripts parse; they now go to stderr, leaving stdout to the remote command alone. Execution errors with an empty `str(e)` — common for `socket.timeout` — no longer produce a bare "Error executing command:" with no cause, and a timeout now says so explicitly and points at `NEOSSH_EXEC_TIMEOUT`.
- **The IPC listener silently dropped any request larger than 64 KB.** A single `ReadFile` against a message-mode pipe signals an oversized message with `ERROR_MORE_DATA` rather than an error, so the GUI just saw a truncated payload fail to parse and handled no request at all. The listener now drains the full message (with a 2 MB ceiling) and the pipe buffers were raised to 1 MB — required for `cli_log` entries carrying command output, and a latent bug for any future large request.

</details>

---

## [1.5.4]

### What changes for you

- **Updates actually install.** Before, the update function could download a new version and then silently keep starting the old one. Updates are now installed with the Windows installer on the next start, or right away with "Restart and install now".
- Downloaded updates are checked against a checksum before they are installed.
- If you agreed to the anonymous usage statistics, they now also count how the update function is used.

<details>
<summary>Technical details</summary>

#### Added
- **Use of the update function is now part of opt-in telemetry.** Users who have consented to telemetry transmit additional information regarding whether they use the update function, how they access it, and whether an update was actually performed: `update_check` (with `source=startup|settings` and `result=available|uptodate|failed`), `update_action` (which button was pressed: Download, Browser, Later, Install Now, Enable/Disable for next startup), `update_download` (`ok|failed`), and `update_result`. Each event also includes the currently running version. No new personal data is collected; the events act as counters without any identifying markers, and the entire transmission remains subject to the `telemetry_enabled` setting.
- It is not possible to determine whether an update was actually successful while the process is underway: the installer provides no feedback and only executes after the application has closed. Therefore, `launch_pending_installer()` creates a file named `update_attempt.json` alongside the pending update marker. Upon the next startup, the running version is compared with the recorded target version: the result is `installed` if they match, and `not_installed` if the installation was aborted or failed. Entries older than one week are discarded without analysis rather than being included in the statistics for the wrong day.

#### Changed
- **Auto-update now installs via the Windows installer instead of swapping the exe.** The update check downloads the release's `Setup.exe` (never the portable exe again) into `%APPDATA%\SSHWinManager\updates` and remembers it in `pending_update.json`. If the update is armed, the *next* program start hands over to a helper script that waits for the app to exit, runs the installer, and starts the app again afterwards — whether the installer completed or was cancelled. This guarantees the update is actually applied and keeps the installed copy's registry entries, shortcuts and uninstall information in sync.
- Releases now ship a `sha256sums.txt` asset, so the SHA-256 verification the updater has always attempted actually runs — a downloaded installer whose hash does not match is discarded instead of installed.
- The update dialog now offers "Install update at next program start" (a checkbox that can be toggled at any time) and "Restart and install now". A running update check also reports an installer that was already downloaded earlier, so a declined update can be armed later without downloading again — including when the app is offline and the GitHub check fails.

#### Fixed
- **Auto-update silently did nothing; the old version kept starting.** The settings screens called `install_on_exit()` immediately after the download finished, not on exit: the generated batch script waited 3 seconds and then tried to `del` the *running* executable, which Windows refuses. The subsequent `move` failed too, so the old exe was simply restarted. Every step was unchecked and its output discarded, so nothing was logged or shown. On top of that, an installed copy usually lives in a directory the user may not write to at all, and the path validation used to reject perfectly normal paths (anything containing `(`, `)` or `~`, e.g. `C:\Program Files (x86)\…`) without any user-visible error. The whole exe-swap mechanism is gone — see above.
- The update check picked the portable `NeoSSHWinManager.exe` release asset, so even a successful swap left an installed copy registered under the old version. It now looks for the `Setup` asset and falls back to the release page in the browser if a release does not ship one.

</details>

---

## [1.5.3] — 2026-07-31

### What changes for you

- Fixed a crash on startup when the app's data folder had broken permissions.
- Activating a Pro licence works again (it always failed with a network error).

<details>
<summary>Technical details</summary>

#### Fixed
- **Startup crash on broken/orphaned ACLs:** `_set_secure_permissions()` in `src/database.py` only treated the DACL *write* step as best-effort; the *read* step right before it (`GetFileSecurity`) was unguarded and crashed the whole app with `pywintypes.error: Access is denied` whenever the data directory had a broken ACL that `permission_repair.py` couldn't fully resolve (ownership repair alone doesn't fix a broken DACL). Now degrades to a logged warning instead, matching the existing best-effort handling of the write step.
- **Pro activation always failed with a network error:** `VALIDATION_ENDPOINT` pointed at the apex domain (`neosshwinmanager.org`), which 301-redirects to `www.neosshwinmanager.org`. Python's `urllib` never replays a POST body across that redirect (it either downgrades to a bodyless GET, or refuses outright on 307/308), so every activation attempt failed before reaching the validation endpoint. Now points directly at `https://www.neosshwinmanager.org/neo_pro_validate.php`, no redirect involved.

</details>

---

## [1.5.2] — 2026-07-27

### What changes for you

- **Windows installer.** A regular `Setup.exe` with desktop shortcut, "start with Windows", and your choice of language and light or dark theme before the first start.
- **FTP and FTPS.** Connections can use FTP or FTPS instead of SFTP; the file browser handles all three.
- **The command-line tool is back** as an optional part of the installation.
- **Fixed:** files written through a mounted drive could end up as empty zeros; new files and folders on a drive only appeared after a manual refresh; command-line access to saved connections never worked; the integrated terminal froze the window while connecting.

<details>
<summary>Technical details</summary>

#### Added
- **Windows installer** (`installer/NeoSSHWinManager.iss`, built with Inno Setup 6): a proper `Setup.exe` alongside the existing standalone executables, with a setup wizard offering desktop shortcut and "start with Windows" tasks, an optional CLI component (`NeoSSHWinManager-cli.exe` can be excluded via a Compact install), and an app-preferences page to pre-select the application's language and dark/light theme before first launch. The installer's own UI is available in English, German, Spanish, Russian and Dutch. Preferences chosen in the wizard are written to `install_prefs.json` and applied by `AuthManager.register()` when the first local user account is created, instead of the hardcoded `en`/`dark` defaults.
- **CLI companion executable restored:** `NeoSSHWinManager-cli.exe` (console subsystem, `cli_main.py`) is back in the build (`NeoSSHWinManager-cli.spec`, `build_dual.ps1`) after being dropped from distribution in 1.5.1. Lets a saved connection with CLI access enabled be reached non-interactively via `NeoSSHWinManager-cli.exe --connect-cli <access_key> [--exec "command"]` while the main GUI is running and logged in. The GUI's own build stays a standalone onefile executable, unaffected.
- **FTP and FTPS support:** Connections now carry a protocol (SFTP / FTPS / FTP). The file browser speaks all three — the new `src/ftp_client.py` implements FTP over `ftplib` with explicit TLS (AUTH TLS, port 21), implicit TLS (port 990) and plain unencrypted FTP, MLSD listings with a LIST fallback for older servers, passive/active mode, progress-reporting up- and downloads and automatic re-login after an idle timeout.
- Add/Edit form gained a protocol selector plus FTP options (implicit TLS, passive mode, certificate verification); the port follows the protocol default (22 / 21 / 990) unless a custom port was entered, and SSH-only fields (key file, drive letter, CLI access, PuTTY key) are hidden for FTP connections.
- Plain-FTP connections can be handed to the on-board Windows Explorer FTP client from the card context menu (the password stays out of the URL — Explorer asks for it).

#### Changed
- FTP/FTPS connections cannot be mounted as a drive and have no SSH terminal: their card shows a protocol badge and opens the file browser, and mount/terminal/system-info actions report that they are unavailable instead of failing later.
- Database migrations now run each `ALTER TABLE` independently, so one column that SQLite refuses (e.g. adding a `UNIQUE` column to an old table) no longer silently skips every migration after it.

#### Fixed
- **SSHFS write corruption:** Files could end up as pure NUL bytes after writing/overwriting through a mounted drive. Caused by `FileInfoTimeout=-1`, which turns on WinFsp's write-back file *data* caching; a hard-killed `sshfs.exe` (e.g. on unmount) could drop not-yet-flushed pages and leave the server-side zero-fill in place. Mounts now use a finite `FileInfoTimeout`, synchronous SFTP writes (`sshfs_sync`) and disabled read-ahead (`no_readahead`) instead.
- **New folders/files invisible until refresh:** `sshfs.exe` carries its own directory-entry cache (`dir_cache`/`dcache_dir_timeout`, default 20s) entirely separate from — and underneath — the WinFsp-side cache timeouts this app already sets, so the existing "disable directory cache" setting never fully applied. Mounts now also tune the sshfs-side cache (fully disabled when that setting is on, tightened to match otherwise).
- **"New Folder"/new file silently duplicated 4x in Explorer:** on a mounted drive, creating an item in Windows Explorer could appear to fail (no rename prompt) and then show up to 4 times after a manual refresh. Root cause is an upstream WinFsp/Windows security-token mismatch (`TokenUser` vs `TokenOwner`) that only affects the built-in Administrator account when UAC Admin Approval Mode is disabled for it (Windows' default for that account) — not fixable from the app's mount options. Documented for anyone else hitting it: enable "User Account Control: Admin Approval Mode for the Built-in Administrator account" (`secpol.msc` or `FilterAdministratorToken=1`) and log back in.
- **Startup crash after fixing the account-token issue above:** files created earlier under the affected account end up owned by the `BUILTIN\Administrators` group instead of the user; once that account's token no longer carries the group, the app's own permission-hardening (`SetFileSecurity`) started failing with access denied and crashing startup. That call is now best-effort (logs a warning instead of crashing), and the app now detects this exact ownership mismatch on its own at startup and offers a one-time, UAC-elevated automatic repair (`src/permission_repair.py`) — so anyone hitting this after an update or reinstall gets a guided fix instead of a crash.
- **CLI access key could never match, for any connection:** `get_by_cli_key()` re-encrypted the incoming key with a fresh random AES-GCM IV and compared the result against the stored ciphertext — which uses a different random IV from when the key was originally saved, so the comparison could never succeed even for the correct key. Lookup now uses a deterministic `cli_access_key_hash` (SHA-256 of the plaintext key) instead; existing connections get this hash backfilled automatically on next login.
- **CLI SSH connections always rejected:** `launch_ssh_in_current_terminal()` (used by `--connect-cli`) set a `RejectPolicy` host-key policy but never actually loaded `known_hosts` into paramiko first, so every connection was rejected as "unknown host" regardless of what was already trusted on disk. Now loads the same `known_hosts` file the rest of the app uses before checking the policy.
- **Embedded terminal froze the whole window while connecting:** opening an SSH session in the integrated xterm.js terminal (`terminal_client` setting = "xterm") called `TerminalBridgeServer.create_session_token()` — which runs a blocking `paramiko.SSHClient.connect()` — directly on the Qt main thread. A slow or unresponsive host could freeze the entire UI for the length of paramiko's auth timeout (30s by default) on top of the connect timeout. Connection setup now runs in a background `TerminalConnectWorker` (`src/ui/worker.py`), matching the existing `MountWorker`/`UnmountWorker` pattern; the tab is only created once the SSH session is actually up.

#### Security
- CLI access over `--connect-cli` now also works for password-authenticated connections: the local IPC response includes the password (previously withheld per an earlier finding). The pipe was already restricted to the current user's SID (`_make_pipe_security_attributes`), the 64-byte access key itself is a strong bearer secret, and requests are already rate-limited per PID — sending the password over this already-restricted channel was the missing piece for a CLI feature whose whole purpose is unattended access to saved connections, not an added exposure.

</details>

---

## [1.5.1] — 2026-07-04

### What changes for you

- **Integrated terminal.** SSH sessions can run inside the app, several per connection, in tabs.
- **File browser** for mounted connections: browse, upload, download, rename, delete.
- **Connection templates**, and a warning when two connections would get the same name.
- A right-click menu on connection cards, a logout dialog that asks whether to keep drives mounted, and a check at startup for WinFsp and SSHFS-Win.
- Security hardening for passwords, session tokens and user management.

<details>
<summary>Technical details</summary>

#### Added
- **Integrated in-app terminal:** New `xterm.js`-based SSH terminal embedded directly in the app (via `QWebEngineView`/`QWebChannel`, bridged to a local WebSocket server), selectable in Settings alongside the existing external SSH/PuTTY launchers. Supports multiple concurrent sessions per connection with a tab bar, background persistence when switching panels, and a reconnect button after disconnect.
- **Native SFTP browser:** New file-browser window (`src/ui/sftp_browser.py`) reachable from the connection card once a host is mounted — directory navigation, upload/download with progress, rename, delete and new-folder, all run off the UI thread via dedicated worker threads.
- **Pro license system:** Machine-fingerprint based activation (`src/pro_manager.py`) with an offline, HMAC-verified license check and a new "Pro License" section in Settings. The free tier is capped at 3 concurrent integrated-terminal sessions; exceeding it surfaces an upgrade prompt.
- **Connection templates & duplicate-name detection:** Add/Edit dialog gained a template dropdown (save/apply/delete) and now blocks duplicate connection/template names, auto-suggesting a unique alternative.
- **Connection card context menu:** Right-click menu for mount/unmount, open in Explorer, open SFTP browser, and connect via OpenSSH/PuTTY/integrated terminal.
- **Logout confirmation dialog:** Choose between staying logged in, quitting while keeping drives mounted, or quitting and unmounting everything.
- **Startup prerequisite check:** Blocks launch with download links if WinFsp and/or SSHFS-Win are not installed.
- **Settings:** New terminal-backend selector (SSH/PuTTY/integrated xterm) and a toggle to disable SSHFS attribute/directory caching for hosts where stale cache data is an issue.
- New GitHub Actions release-build workflow and a nightly version/push helper script for the release process.

#### Changed
- The connection card's SSH button now opens the integrated terminal when that backend is selected in Settings, falling back to the external client otherwise; "open mounted path" now opens the new SFTP browser instead of the system file explorer directly.
- Title bar redesigned with a unified look matching the selected Dark/Light theme; accent color updated app-wide (`#00b4d8` → `#0077b6`).
- SSHFS mounts now set explicit WinFsp attribute/directory/volume-info cache timeouts (tightened further when caching is disabled), and unmounting escalates to force-killing a stuck `sshfs.exe` process after a 10s grace period.
- Password-based `SSH_ASKPASS` hardening (one-time IPC token instead of plaintext env var) now applies starting at security level 1 instead of requiring level 2, for both the native SSH launcher and PuTTY.
- System tray "Quit" now routes through the same mount-cleanup/logout confirmation flow as the main window instead of calling `QApplication.quit()` directly.
- Frameless window resize-cursor handling now works correctly when the mouse is over child widgets, not just the window frame itself.
- Build: CLI companion executable dropped from `build_dual.ps1` (GUI-only distribution going forward); PyInstaller build now strips symbols and excludes unused stdlib modules (tkinter, unittest, pytest, etc.) to reduce executable size.

#### Security
- `get_user_by_username` no longer selects sensitive columns (password hash/salt, encrypted key) it doesn't need, reducing accidental exposure of credential material in memory.
- Admin-only account operations (password reset, delete user, list users) now enforce authorization at the `auth_manager` layer instead of relying solely on UI-level gating.
- Login lockout timers switched from monotonic to wall-clock time so a lockout can no longer be bypassed by restarting the app.
- The updater validates executable/update file paths before embedding them in its self-replace script, and now verifies a SHA-256 checksum of the downloaded update before applying it (falls back to a warning if the release provides no checksum).
- Telemetry action parameters are now URL-encoded before being sent, closing a parameter-injection edge case in the query string.
- Terminal and SFTP sessions use single-use, expiring session tokens, wipe passwords from memory immediately after use, and bind the local bridge server to loopback only; both features share the same TOFU host-key verification and confirmation dialog used elsewhere in the app.
- The Pro license validation secret (`neo_pro_validate.php`) is excluded from the repository.

#### Fixed
- Second app launch now correctly restores/focuses the main window even when it was hidden to the system tray, instead of doing nothing.

</details>

---

## [1.5.0] — 2026-05-11

### What changes for you

- **Groups and templates** for connections, a group filter, and mounting or unmounting several connections at once.
- A profile page where you change your own password.
- A manual update check with download progress.
- Optional anonymous usage statistics, asked for once and switchable in the settings.
- A redesigned main window and settings, and consistent themed dialogs.

<details>
<summary>Technical details</summary>

#### Added
- Connection groups/tags and reusable templates across the data model, database migration, add/edit flows and translations
- Bulk mount/dismount actions and a group filter in the main connection header
- Dedicated profile panel for end users to review their account and change their password
- Manual GitHub update checks with download progress and an install-on-exit flow
- Telemetry opt-in prompt, persisted telemetry settings and asynchronous telemetry submission

#### Changed
- Reworked the main window, settings screen and right-panel forms for the 1.5.0 release layout
- Connection cards now show group pills and compact host details with the drive letter in the subtitle
- Add/Edit connection flows now support templates explicitly and surface group metadata in the UI
- Replaced many native message boxes with a themed custom dialog for warnings, confirmations and success messages
- Pinned core Python dependency versions for the 1.5.0 release environment
- Updated visible application version strings in the main window, about dialog and single-instance mutex
- Reduced debug logging of sensitive command-line arguments in the PuTTY launcher
- Hardened in-memory handling of temporary password tokens used by SSH ASKPASS

#### Security
- Hardened SSH_ASKPASS password exchange by replacing plaintext environment transfer with one-time IPC tokens
- Relaxed first-contact host-key handling to OpenSSH `accept-new` for SSH and sysinfo flows while keeping changed-host failures
- Increased minimum password length from 6 to 8 characters in registration and user-management flows
- Restricted crash report file permissions so stack traces are no longer world-readable
- Masked PuTTY password arguments in debug logs to prevent credential leakage

#### Fixed
- Added password fallback when a stored SSH key fails but a password is still available for the same connection
- Unified destructive confirmation prompts and dirty-form handling through the styled dialog layer
- Corrected multiple German translation strings and save-label spellings used in the 1.5.0 UI

</details>

---

## [1.4.0] — 2026-05-09

### What changes for you

- **Important security update.** Server addresses, user names and paths are now stored encrypted, logins are protected against password guessing, and passwords never appear in the process list. Anyone still on 1.3.0 or earlier should update: those versions are open to man-in-the-middle attacks on SSH connections.
- PuTTY key (`.ppk`) support, and system info with either a key or a stored password.
- A redesigned About window and a countdown after too many failed logins.
- **Fixed:** all drives disconnecting at once, a crash when unmounting, dark-mode message boxes.

<details>
<summary>Technical details</summary>

#### Security
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

#### Features
- **PuTTY PPK Integration:** Auto-detection and configurable PPK key path for PuTTY-based connections
- **Native SSH Terminal Improvements:** Overhauled terminal launch logic in `main_window` for both PuTTY and native OpenSSH
- **SysInfo available with key or password:** System information is now retrieved whenever an SSH key or stored password is configured — the security level setting no longer gates sysinfo access. Password auth uses `SSH_ASKPASS_REQUIRE=force` for non-interactive, secure credential passing.
- **SysInfo Auth Overlay:** When neither key nor password is configured, a 🔑 overlay with a clear explanation is shown instead of a generic error.
- **Login Lockout Countdown:** After a tier-boundary lockout, the login form shows a live countdown (1 s tick) with human-readable time remaining. Input fields and the submit button are disabled for the full lockout duration.
- **Login Button gated on input:** The Sign-in button is disabled until both username (≥ 1 char) and password (≥ 1 char) fields are filled, preventing the misleading "fill all fields" error when submitting wrong credentials.
- **About Dialog Redesign:** Card layout with grouped clickable link buttons for project, documentation, GitHub and author links
- **Sidebar About Button:** Persistent About button added to the sidebar (always visible between Debug and Logout)

#### Fixed
- **SSHFS Mass Disconnect Bug:** Fixed a race condition in `sshfs_controller` that caused all mounted drives to disconnect simultaneously
- **Drive Unmount Crash:** Prevented a crash when a drive was unmounted while the UI still held a reference to it (#1)
- **QMessageBox Dark Mode:** Corrected background color of message boxes in dark mode (#3)
- **F2 Crash on Non-Standard Widgets:** Prevented crash when pressing F2 on widgets that don't support the debug inspector (#4)
- **Form Scroll Behavior:** Fixed scrolling in Add/Edit connection dialog on smaller screens
- **Copy Button in Error Popup:** Icon in the error popup copy button was misaligned due to incorrect CSS object name — fixed to use icon-only button style
- **PuTTY Error Messages:** PuTTY terminal error messages (password login disabled, password missing) are now fully translated and available in English and German
- **Crash Report Path:** Crash reports are now written to `%APPDATA%\SSHWinManager\crash_report.txt` instead of the working directory
- **Worker Thread Error Propagation:** Mount and unmount worker threads now catch exceptions and emit a `MountResult` error instead of crashing silently

#### Changed
- **Add/Edit Dialog:** Live validation and allowed-character hint for connection name field
- **Theme:** Extended styling for new UI components; corrected dark mode inconsistencies; THEME_COLORS dict extracted for native Qt popup palette sync
- **Translations (EN/DE):** Added i18n keys for brute-force lockout countdown, sysinfo auth-missing state, PuTTY errors, About dialog and new overlay states
- **Removed:** Legacy build spec files (`NeoSSHWinManager-cli.spec`, `NeoSSHWinManager.spec`)

</details>

---

## [1.3.1] — Earlier

(Earlier releases documented separately if needed)
