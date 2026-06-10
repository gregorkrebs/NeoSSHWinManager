<h1 align="center">NEO SSH-Win Manager</h1>

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
  <img src="assets/screenshots/app-preview-dark.png" alt="NEO SSH-Win Manager — dark mode" width="49%"/>
  <img src="assets/screenshots/app-preview-light.png" alt="NEO SSH-Win Manager — light mode" width="49%"/>
</p>

<p align="center">
  <a href="https://www.neosshwinmanager.org/app">
    <img src="https://img.shields.io/badge/Interactive%20Demo-Live%20in%20Browser-%2300b4d8?style=for-the-badge&logo=html5&logoColor=white" alt="Interactive browser demo"/>
  </a>
</p>

Manage multiple SSH connections, mount them with one click, switch languages per user, and browse remote paths in Windows Explorer as if they were local drives.

---

## Features

- **One-click mounting** of remote SSH filesystems as Windows drive letters via SSHFS-Win / WinFsp.
- **Built-in SSH terminal** access per connection — uses Windows OpenSSH or PuTTY.
- **Password authentication** with stored credentials — passwordless login without using SSH keys.
- **Public key authentication.**
- **SSH certificate authentication.**
- **Live remote system info panel** (OS, CPU, RAM, disk, uptime, load, temperature).
- **Multi-user accounts** with encrypted credential storage (SQLite + cryptography).
- **Per-user language** (English / German, easily extensible).
- **System tray** with quick mount toggles, minimize to tray.
- **Auto drive-letter detection** (free letters only) and ghost-drive cleanup.
- "Start with Windows" and "Auto-reconnect on connection loss" options.
- **Optional CLI companion** for scripting / agent integration.

## Screenshots

<table>
  <tr>
    <td align="center">
      <img src="assets/screenshots/app-preview-dark.png" alt="Dark mode — connection list" width="380"/><br/>
      <sub><b>Dark mode</b></sub>
    </td>
    <td align="center">
      <img src="assets/screenshots/app-preview-light.png" alt="Light mode — connection list" width="380"/><br/>
      <sub><b>Light mode</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="assets/screenshots/add-edit-dialog.png" alt="Add / Edit connection dialog" width="380"/><br/>
      <sub><b>Add / edit a connection</b></sub>
    </td>
    <td align="center">
      <img src="assets/screenshots/system-info.png" alt="Live system info panel" width="380"/><br/>
      <sub><b>Live system info panel</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="assets/screenshots/tray.png" alt="System tray quick toggles" width="380"/><br/>
      <sub><b>System tray with quick mount toggles</b></sub>
    </td>
    <td align="center">
      <img src="assets/screenshots/login.png" alt="Per-user login" width="380"/><br/>
      <sub><b>Per-user login</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="assets/screenshots/user_management.png" alt="User management" width="380"/><br/>
      <sub><b>User management</b></sub>
    </td>
    <td align="center">
      <img src="assets/screenshots/settings.png" alt="Settings dialog" width="380"/><br/>
      <sub><b>Settings dialog</b></sub>
    </td>
  </tr>
</table>

## Browser Demo
👉 **<https://www.neosshwinmanager.org/app>**

## Prerequisites

Install these before running the app:

| Tool | Download |
| --- | --- |
| **WinFsp** | <https://github.com/winfsp/winfsp/releases> |
| **SSHFS-Win** | <https://github.com/winfsp/sshfs-win/releases> |
| **Python 3.11+** *(only when running from source)* | <https://www.python.org/downloads/> |

## Quick Start (development)

```powershell
git clone https://github.com/gregorkrebs/neosshwinmanager.git
cd neosshwinmanager

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
python main.py
```

On first launch you will be prompted to create an admin user. All SSH credentials you enter afterwards are encrypted with a key derived from that user's password.

## Build as `.exe`

A PyInstaller spec file (`NeoSSHWinManager.spec`) and a PowerShell build script (`build_dual.ps1`) are included. The dual build produces both:

- `NeoSSHWinManager.exe` — the GUI app (windowed subsystem).
- `NeoSSHWinManager-cli.exe` — the CLI companion (console subsystem) used for scripted CLI access.

```powershell
.\build_dual.ps1
```

Outputs land in `dist/`.

## CLI Companion

The CLI companion (`NeoSSHWinManager-cli.exe`) does not read the database directly. It asks the already running GUI app for a connection that has CLI access enabled.

Before using it:

1. Start `NeoSSHWinManager.exe` and log in.
2. Open the target connection in the add/edit dialog.
3. Enable CLI access for that connection.
4. Generate or copy the CLI access key shown there.

Open an interactive SSH session in the current terminal:

```powershell
.\dist\NeoSSHWinManager-cli.exe --connect-cli "<access_key>"
```

Run a single remote command and return its output to the current terminal:

```powershell
.\dist\NeoSSHWinManager-cli.exe --connect-cli "<access_key>" --exec "uname -a"
```

More examples:

```powershell
.\dist\NeoSSHWinManager-cli.exe --connect-cli "<access_key>" --exec "whoami"
.\dist\NeoSSHWinManager-cli.exe --connect-cli "<access_key>" --exec "hostname"
.\dist\NeoSSHWinManager-cli.exe --connect-cli "<access_key>" --exec "cd /var/www && ls -la"
```

You can use the same interface from source during development:

```powershell
python cli_main.py --connect-cli "<access_key>" --exec "hostname"
```

Notes:

- `--connect-cli` is the preferred flag. `-connectssh` is also accepted for compatibility.
- If you omit `--exec`, the CLI opens an interactive shell in the current terminal.
- If the GUI app is not running, no user is logged in, the key is invalid, or CLI access is disabled for that connection, the command exits with an error.

## How mounting works

sshfs-win exposes remote SSH paths under a UNC format that Windows `net use` understands:

```
net use X: \\sshfs.r\user@host!22\var\www /persistent:no
```

The app builds this command automatically from the connection settings and tracks mount state via drive enumeration.

## Project layout

```
neosshwinmanager/
├── main.py                        # GUI entry point
├── cli_main.py                    # CLI entry point (companion exe)
├── requirements.txt
├── NeoSSHWinManager.spec          # PyInstaller spec (GUI)
├── NeoSSHWinManager-cli.spec      # PyInstaller spec (CLI)
├── build_dual.ps1                 # Dual-build helper (GUI + CLI exe)
├── assets/                        # App icons and screenshots
├── src/
│   ├── config.py                  # Data models + JSON config
│   ├── database.py                # SQLite schema + migrations
│   ├── auth_manager.py            # Users, sessions, encrypted credentials
│   ├── connection_manager.py     # Connection CRUD
│   ├── sshfs_controller.py       # Mount / unmount via net use
│   ├── drive_utils.py            # Drive letter helpers
│   ├── i18n.py                   # Translation loader
│   ├── translations/
│   │   ├── en.json               # English (default)
│   │   └── de.json               # German
│   └── ui/
│       ├── main_window.py
│       ├── connection_card.py
│       ├── system_info_panel.py
│       ├── system_tray.py
│       ├── theme.py
│       └── dialogs/
│           ├── add_edit_dialog.py
│           ├── settings_dialog.py
│           ├── about_dialog.py
│           ├── login_dialog.py
│           └── system_info_dialog.py
└── tests/
    └── test_config.py
```

## Adding a language

Language is stored per user. To add a new language:

1. Copy `src/translations/en.json` to `src/translations/<code>.json` and translate the values.
2. Add the code to `_SUPPORTED` in `src/i18n.py` and the label map in `src/ui/dialogs/settings_dialog.py`.
3. Restart the app.

Missing keys automatically fall back to English.

## Run tests

```powershell
python -m pytest tests/ -v
```

## Credits & history

The idea for this tool was inspired by the original **SSHWinManager**, which was written in JavaScript / Electron by a different author.

**NEO SSH-Win Manager is a complete, from-scratch rewrite in Python (PyQt6)**, developed jointly by [**Den4ik53**](https://github.com/Den4ik53) and [**Gregor Krebs**](https://github.com/gregorkrebs). No code from the original project is reused. The goals, scope and architecture have changed substantially:

- Native Python / PyQt6 stack instead of Electron.
- Multi-user support with per-user encrypted SSH credential storage.
- Per-user language preference.
- Per-connection live system info panel.
- Optional CLI access key for agent / automation integration.
- System tray with quick mount toggles.
- Optional PuTTY / OpenSSH terminal launch per connection.

## License

[MIT](LICENSE) — do whatever you want with it. Attribution is appreciated but not required.
