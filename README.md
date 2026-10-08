<h1 align="center">
  <img src="assets/social-preview.png" alt="NEO SSH-Win Manager — mount SSH servers as Windows drive letters, auto-login SSH terminal (built-in, PuTTY or OpenSSH), dual-pane SFTP/FTP/FTPS file browser, multi-user with encrypted credentials" width="100%"/>
</h1>

<p align="center">
  A modern Windows desktop app for mounting remote SSH filesystems as Windows drive letters with a centralized solution for SSH access<br/>
  Built on top of <a href="https://github.com/winfsp/sshfs-win">sshfs-win</a> and <a href="https://github.com/winfsp/winfsp">WinFsp</a>.
</p>

<p align="center">
  <a href="https://github.com/gregorkrebs/neosshwinmanager/releases/latest">
    <img src="https://img.shields.io/github/v/release/gregorkrebs/neosshwinmanager?label=release&style=for-the-badge" alt="Latest release"/>
  </a>
  <a href="https://github.com/gregorkrebs/neosshwinmanager/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/gregorkrebs/neosshwinmanager?style=for-the-badge" alt="License"/>
  </a>
  <img src="https://img.shields.io/badge/platform-Windows-0078D6?style=for-the-badge" alt="Platform: Windows"/>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"/>
  <img src="https://img.shields.io/badge/PyQt-6-41CD52?style=for-the-badge&logo=qt&logoColor=white" alt="PyQt6"/>
</p>

<p align="center">
  <img src="assets/screenshots/overview.png" alt="NEO SSH-Win Manager — connection list with a host's details, in the four themes Black, Light, Blue (classic) and Gray" width="100%"/>
</p>

<p align="center">
  <a href="https://github.com/gregorkrebs/neosshwinmanager/releases/latest"><b>Download</b></a> ·
  <a href="https://www.neosshwinmanager.org/app"><b>Try the live demo</b></a> ·
  <a href="https://www.neosshwinmanager.org/en/docs/getting-started"><b>Documentation</b></a> ·
  <a href="https://github.com/gregorkrebs/neosshwinmanager/issues"><b>Report a bug</b></a>
</p>

Manage all your SSH servers in one place: mount them as Windows drives with one click, open a terminal that logs in by itself, and move files with a dual-pane file browser — for Linux and Windows servers, with your credentials stored encrypted.

## Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Installation](#installation)
- [Command-line companion](#command-line-companion)
- [Development](#development)
- [Feedback and contributing](#feedback-and-contributing)
- [Credits and history](#credits-and-history)
- [License](#license)

---

## Features

### Drives

- **One-click mounting** of remote SSH filesystems as Windows drive letters via SSHFS-Win / WinFsp.
- **Mount or unmount everything at once**, or only the hosts of one group.
- **Free drive letters are detected automatically**; several hosts can share a letter if you allow it, and ghost drives can be cleaned up.
- **System tray** with a quick toggle for every host; the app can keep running there when you close the window.
- **Start with Windows** and reconnect the drives that were mounted last time.
- **Auto-reconnect on connection loss**: a mounted drive reconnects by itself when the connection drops.

### Terminal

- **Integrated terminal** with as many sessions per host as you like, in tabs. It logs in by itself with the stored password or SSH key.
- **Windows OpenSSH or PuTTY** instead, as the default or, from a host's right-click menu, just this once.

### File browser

- **SFTP, FTPS and FTP**, built into the main window, with every host in its own tab.
- **This PC and the server side by side**, with drag & drop, folder trees and a clickable path bar.
- **A transfer queue** that pauses, resumes and continues interrupted transfers after a reconnect.
- **Undo and redo** for moves, renames and new folders; conflict handling with file comparison.
- **Edit files in your own programs**: saving uploads them back.
- **Folder sync** with a preview, server-side archives, and files fetched from a URL straight onto the server.
- FTP over TLS in explicit (AUTH TLS, port 21) and implicit (port 990) mode, and plain FTP for legacy servers.

### Linux and Windows servers

- **Servers running OpenSSH for Windows** work everywhere: in the terminal, the file browser, the system info and as mounted drives, including subfolders such as `C:\Projects`.
- **Live system info**: OS, CPU, RAM, drives, uptime and load, plus the temperature on Linux.

### Accounts and security

- **No setup at the first start**: the app starts in single-user mode and signs you in automatically; its password is kept in Windows Credential Manager.
- **Accounts with passwords** when several people share the computer, each with their own connections, language and look.
- **Encrypted storage**: passwords, hosts, user names and paths are encrypted with AES-256-GCM, with a key only your account can unlock.
- **Password, public-key or SSH certificate authentication** per host, or ask each time. A certificate is picked up when it lies next to the key as `<key>-cert.pub`.
- Host keys are verified, and a changed key of a known server is reported.

### Interface

- **Six languages**: English, German, Spanish, Russian, Dutch and Arabic (right-to-left), chosen per user — right on the login screen, too.
- **Four themes** — Black, Blue (classic), Gray and Light — with an accent colour of your own and the text colour on it.
- **Filter the connection list** by name, host or user name as you type.
- **Groups and templates** to keep many hosts tidy and set up new ones quickly.
- **Help where you need it**: every field of the connection form links to the [online documentation](https://www.neosshwinmanager.org/en/docs/connections#connection-form), and the empty overview shows tips that fit your setup.

### Automation

- **Command-line companion** (`NeoSSHWinManager-cli.exe`) for scripts and agents, with a history of everything it ran — see [below](#command-line-companion).

## Screenshots

Every picture shows the four themes: **Black** (top left) and **Gray** (bottom right) with the accent colour `#228c2b`, **Light** (top right) and **Blue (classic)** (bottom left) with the default accent. All hosts, users and data are fictional.

<p align="center">
  <img src="assets/screenshots/terminal.png" alt="In-app terminal next to the connection list — Black, Light, Blue (classic) and Gray" width="100%"/><br/>
  <sub><b>Integrated terminal</b></sub>
</p>

<p align="center">
  <img src="assets/screenshots/file-browser.png" alt="Dual-pane file browser — Black, Light, Blue (classic) and Gray" width="100%"/><br/>
  <sub><b>File browser: this PC and the server side by side</b></sub>
</p>

<details>
<summary><b>More screenshots</b>: filter, connection form, system info, user management, settings, login, tray</summary>

<p align="center">
  <img src="assets/screenshots/search.png" alt="The connection list filtered by the user name deploy — Black, Light, Blue (classic) and Gray" width="100%"/><br/>
  <sub><b>Filter by name, host or user</b></sub>
</p>

<p align="center">
  <img src="assets/screenshots/connection-form.png" alt="Connection form with help buttons — Black, Light, Blue (classic) and Gray" width="100%"/><br/>
  <sub><b>Add / edit a connection, with help for every field</b></sub>
</p>

<p align="center">
  <img src="assets/screenshots/system-info.png" alt="Live system info panel — Black, Light, Blue (classic) and Gray" width="100%"/><br/>
  <sub><b>Live system info</b></sub>
</p>

<p align="center">
  <img src="assets/screenshots/users.png" alt="User management with three accounts — Black, Light, Blue (classic) and Gray" width="100%"/><br/>
  <sub><b>User management</b></sub>
</p>

<p align="center">
  <img src="assets/screenshots/settings.png" alt="Settings page — Black, Light, Blue (classic) and Gray" width="100%"/><br/>
  <sub><b>Settings</b></sub>
</p>

<table>
  <tr>
    <td align="center" width="62%">
      <img src="assets/screenshots/login.png" alt="Login screen with language picker — Black, Light, Blue (classic) and Gray" width="100%"/><br/>
      <sub><b>Login with language picker</b></sub>
    </td>
    <td align="center" width="38%">
      <img src="assets/screenshots/tray.png" alt="System tray menu with quick mount toggles — Black, Light, Blue (classic) and Gray" width="70%"/><br/>
      <sub><b>System tray with quick mount toggles</b></sub>
    </td>
  </tr>
</table>

</details>

## Installation

1. **Install the prerequisites** for mounting drives:

   | Tool | Download |
   | --- | --- |
   | **WinFsp** | <https://github.com/winfsp/winfsp/releases> |
   | **SSHFS-Win** | <https://github.com/winfsp/sshfs-win/releases> |

   If one of them is missing, the app says so at the start and links to the download.

2. **Download the app** from the [latest release](https://github.com/gregorkrebs/neosshwinmanager/releases/latest):
   - `NeoSSHWinManager-Setup-<version>.exe` — the installer, with a desktop shortcut, "start with Windows", the language and theme for the first start, and the command-line companion as an optional component.
   - `NeoSSHWinManager.exe` — the portable app, without installation.
   - `sha256sums.txt` — checksums to verify the download.

3. **Start the app.** It starts in single-user mode: it creates an account with a random password, keeps that password in Windows Credential Manager and signs you in automatically. All SSH credentials you enter are encrypted with a key that this password protects. To sign in with a password of your own, create an account under User Management; your connections and settings are kept. If Windows Credential Manager is not available, the app asks you to create an account instead.

Updates are found by the app itself and installed at the next start if you want. Something not working? See [troubleshooting](https://www.neosshwinmanager.org/en/docs/troubleshooting).

## Command-line companion

`NeoSSHWinManager-cli.exe` gives scripts and agents access to saved connections. It does not read the database itself: it asks the running app for a connection that has CLI access enabled. Full reference: [CLI documentation](https://www.neosshwinmanager.org/en/docs/cli).

**Set up:**

1. Start `NeoSSHWinManager.exe` and sign in.
2. Open the connection's form and enable CLI access.
3. Generate or copy the CLI access key shown there.

**Use:**

```powershell
# interactive SSH session in the current terminal
NeoSSHWinManager-cli.exe --connect-cli "<access_key>"

# run one command and print its output
NeoSSHWinManager-cli.exe --connect-cli "<access_key>" --exec "uname -a"
NeoSSHWinManager-cli.exe --connect-cli "<access_key>" --exec "cd /var/www && ls -la"
```

- The exit code is the remote command's exit code, and the output can be redirected to a file.
- Everything run this way is listed in the app under the connection's details → "Show CLI history".
- `--connect-cli -` reads the access key from stdin, so it does not show up in the process list. `-connectssh` is accepted for compatibility.
- If the app is not running, no one is signed in, the key is invalid or CLI access is disabled for that connection, the command exits with an error.

## Development

### Run from source

Requires Python 3.11+ and the [prerequisites](#installation) above.

```powershell
git clone https://github.com/gregorkrebs/neosshwinmanager.git
cd neosshwinmanager

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
python main.py
```

The CLI companion runs from source as `python cli_main.py --connect-cli "<access_key>" --exec "hostname"`.

### Run tests

```powershell
python -m pytest tests/ -v
```

### Build

```powershell
.\build_dual.ps1                    # NeoSSHWinManager.exe + NeoSSHWinManager-cli.exe in dist/
.\installer\build_installer.ps1     # both executables, then the installer (needs Inno Setup 6)
```

- `NeoSSHWinManager.exe` — the GUI app (windowed subsystem), built from `NeoSSHWinManager.spec`.
- `NeoSSHWinManager-cli.exe` — the CLI companion (console subsystem), built from `NeoSSHWinManager-cli.spec`.

### How mounting works

sshfs-win exposes remote SSH paths under a UNC format that Windows `net use` understands:

```
net use X: \\sshfs.r\user@host!22\var\www /persistent:no
```

The app builds this command from the connection settings and tracks the mount state via drive enumeration.

### Project layout

```
neosshwinmanager/
├── main.py                       # GUI entry point
├── cli_main.py                   # CLI entry point (companion exe)
├── build_dual.ps1                # Builds the GUI and the CLI exe
├── installer/                    # Inno Setup script and its build script
├── assets/                       # Icons, terminal page, screenshots
├── src/
│   ├── auth_manager.py           # Accounts, sessions, encrypted connections and settings
│   ├── crypto.py                 # Encryption, Windows Credential Manager
│   ├── database.py               # SQLite schema and migrations
│   ├── config.py                 # Data models
│   ├── sshfs_controller.py       # Mount / unmount via net use
│   ├── drive_utils.py            # Drive letters
│   ├── ssh_launcher.py           # OpenSSH / PuTTY terminals, CLI sessions
│   ├── sftp_client.py            # SFTP for the file browser and system info
│   ├── ftp_client.py             # FTP / FTPS
│   ├── remote_os.py              # Detects Windows OpenSSH servers
│   ├── updater.py                # Update check and installation
│   ├── i18n.py                   # Translation loader, language list
│   ├── tips.py                   # Tips in the empty overview
│   ├── help_links.py             # Links into the online documentation
│   ├── translations/             # en, de, es, ru, nl, ar
│   ├── filebrowser/              # File browser (SFTP / FTP / FTPS)
│   ├── terminal/                 # Integrated terminal (xterm.js bridge)
│   └── ui/                       # Main window, dialogs, theme, widgets
└── tests/                        # pytest suite
```

### Adding a language

Language is stored per user. To add one:

1. Copy `src/translations/en.json` to `src/translations/<code>.json` and translate the values.
2. Add the code to `_SUPPORTED` and its name to `LANGUAGE_NAMES` in `src/i18n.py`.
3. For a right-to-left language, also add the code to `_RTL` in `src/i18n.py`; the app then mirrors its layout.
4. Add the code to `LANGS` in `tests/test_ui_translations.py` and `tests/test_tips.py`, so the tests check the new file for missing texts.

Missing keys fall back to English.

## Feedback and contributing

Found a bug or have an idea? [Open an issue](https://github.com/gregorkrebs/neosshwinmanager/issues) — bug reports and feature requests are equally welcome. For a bug report, "Copy version info" in the app's About window puts the app version and Windows build on the clipboard.

## Credits and history

The idea for this tool was inspired by the original **SSHWinManager**, which was written in JavaScript / Electron by a different author.

**NEO SSH-Win Manager is a complete, from-scratch rewrite in Python (PyQt6)**, developed by [**Gregor Krebs**](https://github.com/gregorkrebs). No code from the original project is reused. The goals, scope and architecture have changed substantially:

- Native Python / PyQt6 stack instead of Electron.
- Multi-user support with per-user encrypted SSH credential storage.
- Per-user language preference.
- Per-connection live system info panel.
- Optional CLI access key for agent / automation integration.
- System tray with quick mount toggles.
- Optional PuTTY / OpenSSH terminal launch per connection.

Single-user mode comes from the community fork [ultrabuild-katzi/neosshwinmanager-single-user](https://github.com/ultrabuild-katzi/neosshwinmanager-single-user) by notstevy.

## License

[MIT](LICENSE) — do whatever you want with it. Attribution is appreciated but not required.
