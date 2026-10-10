  # Changelog

  What changed in each version of NEO SSH-Win Manager, newest first.

  Each release starts with what changes for you when you update. The full technical notes, for contributors and anyone tracking a particular fix, are in the "Technical details" block below it.

  Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html): the middle number goes up for new features, the last one for fixes only. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

  ---

  ### What changes for you
  =======
  ## [1.7.3]

  ### What changes for you

  - **Import your sites from FileZilla.** "Import from FileZilla…" at the top of the form for a new connection reads FileZilla's Site Manager on this computer, or a file you pick, for example a copy from another computer or a FileZilla export. You see every site with its server, protocol and folder and choose which ones to add. FileZilla's folders become groups, SFTP sites get a free drive letter, and sites already in your list start unchecked. Nothing changes in FileZilla.
    - Stored passwords come along. If FileZilla protects them with a master password, the connection asks for the password when it connects.
    - SFTP, FTP and FTPS are imported; other protocols of FileZilla Pro, such as S3 or WebDAV, are listed but cannot be imported. 
  - **Mounting checks the server's key against your known servers again.** Because of a path mistake, mounting never read the list of known servers (`known_hosts`) that the rest of the app uses. Depending on your Windows account it kept a list of its own or accepted any server key. Now a server whose key has changed is refused when you mount it, and the error window says so.
  - **Servers that accept SSH keys only can be mounted.** For a connection with a password, mounting and the system info now try your SSH keys first (`id_ed25519`, `id_ecdsa` and `id_rsa` in your `.ssh` folder), as the terminal and the file browser always did. Keys with a passphrase are left out.
  - **The error window says why mounting failed**, for example "Permission denied (publickey)", instead of only "code 1".
  >>>>>>> dev-1.7.3

  <details>
  <summary>Technical details</summary>

  #### FileZilla import

  - `src/filezilla_import.py` parses `%APPDATA%\FileZilla\sitemanager.xml` (or an export, both `<FileZilla3><Servers>`), walking nested `<Folder>` elements; the folder path ("A / B") becomes the connection's group, with commas removed because they separate groups.
  - Protocols: 1 → SFTP; 0 (FTP, TLS if offered) and 4 (explicit TLS) → FTPS with explicit TLS, 0 with a note that plain FTP is the fallback; 3 → FTPS with implicit TLS (port 990 by default); 6 → FTP. Others (HTTP, S3, WebDAV, cloud storage) are listed as not supported. `PasvMode` `MODE_ACTIVE` turns passive mode off.
  - Logon types: anonymous → user `anonymous`; normal with a base64 or plain password → password; a password encrypted with the master password (`encoding="crypt"`), "Ask for password" and "Interactive" → `ask`; key file → `key`, a `.ppk` going to `putty_key_path`, any other key to `key_path`.
  - `RemoteDir` ("1 0 4 home 4 user") is decoded with its length-prefixed segments into `/home/user`, or `C:\Users\me` for DOS paths.
  - `FileZillaImportDialog` lists the sites with a check box each and the remarks above; a site with the same host, port, user and protocol as an existing connection starts unchecked. `MainWindow._import_from_filezilla()` keeps names unique ("Name (2)") and gives SFTP sites a drive letter that is free on the system and not configured for another host.
  - Tests in `tests/test_filezilla_import.py` cover the protocols, logon types, folders, remote paths, files that are not from FileZilla, duplicates and the dialog.
  =======
  #### Fixed: sshfs never used the user's known_hosts

  - sshfs treats a backslash in an `-o` value as an escape and drops it, so `-oUserKnownHostsFile=C:\Users\me\.ssh\known_hosts` became the relative `C:Usersme.sshknown_hosts`, resolved from the SSHFS-Win folder. Running as administrator, ssh kept its own list there (`C:\Program Files\SSHFS-Win\C?Users….sshknown_hosts`). Without write access to that folder it could not save one and, with `StrictHostKeyChecking=accept-new`, accepted any host key on every mount.
  - The path now uses forward slashes, as the `IdentityFile` path already did. Verified against a real server: with wrong keys for it in `known_hosts`, 1.7.2 mounted anyway; 1.7.3 refuses with "REMOTE HOST IDENTIFICATION HAS CHANGED".

  #### Fixed: password connections on servers that accept keys only

  - The terminal and the file browser log in with paramiko, which tries `~/.ssh/id_*` before the password. sshfs and the system info tried the password only. Both now pass the user's default keys first (`src/ssh_identities.py`: only keys that load without a passphrase, `IdentitiesOnly=yes`, `PreferredAuthentications=publickey,password,keyboard-interactive`). Without such keys the command is unchanged.
  - Verified against Ubuntu 26.04 (OpenSSH 10.2, `PasswordAuthentication no`): a password connection with a wrong password mounted through `id_ed25519`, and the system info showed the server.

  #### Improved: the mount error shows sshfs's own message

  - sshfs's error output goes to `%TEMP%\NeoSSHWinManager\sshfs-<letter>.log` (a file, not a pipe, because a mount outlives the GUI). When a mount fails, the dialog shows its last lines, and for a changed host key also ssh's headline.
  - New tests in `tests/test_ssh_identities.py`.

  </details>

  ---

  ## Version 1.7.2

  ### What changes for you

  - **New servers work in the terminal straight away.** For a server you had just added, the terminal did not ask whether to trust the server's key, and after half a minute it reported that the connection had failed, as if the host or the password were wrong. It now asks, and the terminal opens once you confirm.

  <details>
  <summary>Technical details</summary>

  #### Fixed: no host-key question in the embedded terminal

  - Since 1.5.2 the SSH handshake of the embedded terminal runs in `TerminalConnectWorker`. For an unknown host key, `MainWindow._terminal_tofu_callback()` is called from that thread. It scheduled the dialog with `QTimer.singleShot(0, ...)`, which never fires in a thread without an event loop, waited 30 s and returned "rejected", so the user only saw "SSH connection failed. Check host, credentials, and network."
  - The question now runs on the main thread through `MainThreadInvoker`, as in the file browser, and the worker waits for the answer without a time limit. `quit_app()` closes the invoker, so a waiting worker gives up.
  - Verified with the app against a local SSH server and an empty `known_hosts`: 1.7.1 failed after 30 s without a question. With the fix the question appears at once; Yes opens the terminal and saves the key, No refuses, an answer after 40 s still connects, and a second session does not ask again.
  - New tests in `tests/test_terminal_host_key.py`.

  </details>

  ---

  ## Version 1.7.1

  A small update that makes updating smooth again. It also brings everything that is new in 1.7.0 – you find it below.

  ### What changes for you

  - **The app starts again on its own after an update.** After the in-app update to 1.7.0 the installation went through, but starting the new version failed with the message "Failed to load Python DLL", and you had to start the app yourself. From 1.7.1 on, the app opens again by itself after every update, also when you update from 1.7.0 or 1.6.1.
    - If you saw that message: nothing is broken, the update was installed. Start NEO SSH-Win Manager once by hand; all your connections and settings are there.

  <details>
  <summary>Technical details</summary>

  #### Fixed: "Failed to load Python DLL" after an in-app update (1.6.1 to 1.7.0)

  - The app hands over to the installer with its own environment, which included the PyInstaller onefile variables (`_PYI_*`). The installer passed them on to the app it starts again. The new app has the same exe path, so the PyInstaller 6 bootloader took it for a child of the old process and loaded `python314.dll` from the old process's `_MEI…` folder, which was gone by then.
  - `updater.installer_environment()` now starts the installer without the `_PYI_*` variables.
  - Because 1.6.1 to 1.7.0 still pass them on, the installer's `DeinitializeSetup` starts the app through `cmd /d /c set "PYINSTALLER_RESET_ENVIRONMENT=1" & start "" "<exe>"`, which makes the bootloader start fresh. `ShellExec` cannot set a variable, hence `cmd`.
  - Verified end to end with frozen builds and installers under an own AppId, folder and `APPDATA`, the handing-over app running from the install folder: a 1.7.0 client updating with the old installer showed the error (reproduced); with the fixed installer the new version started and created its database; a fixed client updating to a newer fixed build started as well.
  - New test in `tests/test_updater.py`: the installer gets no `_PYI_*` variables.

  #### Release notes in the update window

  - The update window shows the `CHANGELOG.md` sections of every version newer than the installed one. Clients on 1.7.0 would therefore have shown 1.7.1 only, although their update to 1.7.0 ended in the error above. The 1.7.0 heading is written without brackets ("## Version 1.7.0"), so every client — the ones already released included — reads it as part of the 1.7.1 section: coming from 1.7.0 or 1.6.1, the window shows 1.7.1 and then 1.7.0, each once. Tests in `tests/test_updater.py` check both cases.
  >>>>>>> dev-1.7.3

  </details>

  ---

  ## [1.7.0] — 2026-10-09
  =======
  ## Version 1.7.0

  Quicker to get started and easier to find your way around: a new installation is ready without setting up an account, a filter finds any connection as you type, and the login screen and the dark look have been redesigned. NEO SSH-Win Manager is now free and open source in full: the Pro licence is gone.

  ### Highlights

  - **Start right away, no account to set up.** A new installation signs you in automatically (single-user mode). Its password is a random one, kept in Windows Credential Manager and protected by your Windows sign-in.
    - If several people use the computer, or you would rather sign in with a password, create an account under User Management → "Application login mode". Your connections and settings stay as they are.
    - An installation with one account can switch to single-user mode in the same place. The account is then renamed to "default".
    - Installations that sign in with a password keep doing so after the update. If Windows Credential Manager is not available, the app asks you to create an account as before.
  - **Find any connection as you type.** The magnifier above the connection list, or Ctrl+F, opens a filter field. It looks at the name, the host and the user name, several words narrow the list further, and you see how many connections match. What you type stays there, across restarts too, until you clear it with the × in the field.
  - **A redesigned login screen.** A cleaner layout with icons in the fields, a button to show the password you are typing, a warning when Caps Lock is on, and error messages in a clearly visible box.
    - A language menu at the top right switches the login screen at once. The language you pick there becomes your language in the app.
    - The login screen uses the theme, the accent colour and the language of the user who signed in last.
  - **Black replaces Dark.** A classic dark mode in plain black and gray, without the blue tint. If you used Dark, you now have Black. The previous blue look is still there as "Blue (classic)", in the settings and in the installer.
  - **Free and open source, with everything.** The Pro licence is gone for good. The app no longer contains a licence check and no longer contacts the licence server.

  ### Also new

  - **Tips in the empty overview.** Where "Ready for the next step" used to stand, you now get a tip ("Did you know?"): 60 short notes on features, shortcuts and settings, and a few jokes, in all six languages. You only see tips that fit your setup, a new one each time the overview comes back, and "Next tip" shows another one.
  - **Help right in the connection form.** A ? at the top of the form and beside every field opens the online documentation at the explanation of that field. Below the remote path, a tip says that it is usually your home directory on the server and that the command `pwd` shows it after an SSH login.
  - **Choose the text colour on your accent colour.** The accent colour picker has a new row for the text on accent-coloured buttons: automatic, white, black or a colour of your own, with a sample. The automatic choice is better too: bright accents such as orange, a vivid green or cyan now get dark text, while blue, violet, red or pink keep white text.
  - **A network of linked nodes in the background** of the empty overview, a connection's details, User Management, your profile and the login screen. Every page, and every connection, has a pattern of its own, and the text stays easy to read. You can switch it off under Settings → Appearance.

  ### Improved

  - **The whole interface follows your language.** Some texts stayed in German or English whatever language you had chosen: the tooltips of the window buttons, "Cancel" when you rename or create a file in the file browser, the buttons of some confirmations, "Copy details" after an unexpected error, the error prefix in the status bar and the number of CPU cores in the system info. They are now translated.
  - **Confirmations that delete something are red in every language.** Deleting a connection, user or template, deleting files on the server and clearing the CLI history showed the red confirm button only in English and German.
  - **A tidier header and title bar.** The buttons above the connection list sit in the middle of their bar, and the "… active · … mounted" badge is no longer cut off. The header bar runs on across the gap between the connection list and the right panel, and in every theme the title bar takes the darker tone of the sidebar.
  - **A friendlier check interval field.** In the settings, the check interval sits between two round buttons, − and +. Holding a button keeps counting, and the number can still be typed.
  - **The login window appears a little sooner.** The main window is now loaded after you have signed in.
  - **In single-user mode, the profile button is hidden**, because there is no password to change. It comes back when you create an account.

  ### Fixed

  - **No more small windows flashing up after the login.** While the main window was being built, a small empty window appeared and vanished again for every SFTP host in your list.
  - Button texts with "&", such as "Create account & start", no longer lose the "&".

  Single-user mode comes from the community fork [ultrabuild-katzi/neosshwinmanager-single-user](https://github.com/ultrabuild-katzi/neosshwinmanager-single-user) by notstevy. Thank you!

  <details>
  <summary>Technical details</summary>

  #### Adopted from the fork

  Taken from [ultrabuild-katzi/neosshwinmanager-single-user](https://github.com/ultrabuild-katzi/neosshwinmanager-single-user), which is based on 1.6.1, in its final state (branch `newmain2`):

  - [`04241d7`](https://github.com/ultrabuild-katzi/neosshwinmanager-single-user/commit/04241d7a1c4809d6b14385304ee145bc2e69b5f1) / [`26256dc`](https://github.com/ultrabuild-katzi/neosshwinmanager-single-user/commit/26256dc6f1ae11ea674a1bc10ae37f87e4fc8322) "Single-user, automatic login": a new `application_mode` table (one row with a `single_user` flag) in `init_db()`; `AuthManager.authenticate_single_user()`, `initialize_single_user_mode()`, `enable_single_user_mode()` and `migrate_single_user_to_multi_user()`; `main.py` tries the automatic login before it shows `LoginDialog`; a first-run button in the login dialog and a login mode card in the users panel. Switching modes re-wraps the existing encryption key with the new password (a random `secrets.token_urlsafe(32)` in single-user mode), so the account id and all encrypted data stay untouched.
  - [`b77e06f`](https://github.com/ultrabuild-katzi/neosshwinmanager-single-user/commit/b77e06f042c958d8ba782d4a610b45cc45948bd1) "Fix security issues with the single-user/multi-user mode switching": single-user mode can no longer be switched on from the login dialog with a freely chosen username and password. It is switched on only from a signed-in administrator session, and only when exactly one account exists. The users panel then shows neither the user list nor the form for new users.
  - [`4970ab3`](https://github.com/ultrabuild-katzi/neosshwinmanager-single-user/commit/4970ab39864c9a3ad77cb85d38403834a99287be) "Improve translation": wording of `login.single_unavailable_users`.
  - [`e105613`](https://github.com/ultrabuild-katzi/neosshwinmanager-single-user/commit/e1056134dc467ce7a28a2147c609b18fa3f14667) "Improve startup performance": `src.auth_manager`, `LoginDialog` and `MainWindow` are imported inside `main()`. Importing `src.auth_manager` reads the stored login attempts from the database; this now happens after the permission repair and `init_db()` instead of before them. Measured from source, the login dialog appears about 50 ms sooner; the time until the main window is shown is unchanged.
  - `crypto.is_keyring_available()` asks the keyring backend instead of only checking that the `keyring` package can be imported.

  The identifiers are the same as in the fork (table `application_mode`, Credential Manager entry `NeoSSHWinManager` / `single_user_password`, account `default`). An installation that ran the fork keeps signing in automatically after the update; this was checked against a copy of such a database.

  #### Changed while adopting

  - Translations for all six languages; the fork had English only.
  - Switching back to multi-user login asks for the new password twice, in fields on the users panel. The fork used two plain input boxes without confirmation, so a typo would have locked the account at the next start.
  - Switching to single-user mode asks for confirmation first.
  - In single-user mode, the profile shows a hint instead of the password change form, which needs the current password and so could not work.
  - The main window keeps its `UserConnectionManager` when the mode changes, because the account id and key stay the same. Components that hold it, such as the file browser, are not left with a second instance.
  - After a mode change the users panel is rebuilt in place; `_open_users_panel()` alone would close it, since it toggles an open panel.
  - In single-user mode, a missing Credential Manager entry or an unavailable keyring is logged before the login dialog is shown.
  - `Session` is now imported in `main()` before its first use. Before, the import inside the `USERNAME` block made `Session` a local name of `main()`, so starting without a `USERNAME` environment variable raised `UnboundLocalError`.
  - Not adopted, because nothing used them: `AuthManager.set_single_user_mode()` and the strings `login.enable_single`, `login.single_title`, `login.single_username` and `login.single_password`.
  - New tests in `tests/test_single_user_mode.py` cover the first setup, the automatic login, both switches with an existing connection, the rollback when Credential Manager cannot store the password, input checks and the import order in `main.py`.

  #### Login screen

  - `LoginDialog` is rebuilt: a frame with a soft glow in the accent colour, a card with the form, leading icons in the fields (`QLineEdit.addAction`, new `user.svg` and `eye-off.svg` in the style of the other icons), a show/hide action in password fields, and errors in a box with the `alert-triangle` icon instead of a "⚠" prefix. A Caps Lock hint (`GetKeyState(VK_CAPITAL)`) appears while a password field has the focus. The first-run form puts single-user mode below an "or" divider.
  - A language menu (names from the new `i18n.LANGUAGE_NAMES`, which the settings page now uses too) rebuilds the form in the picked language, keeps what was typed and switches the layout direction for Arabic. A successful login stores the picked language for that user (`AuthManager.set_user_language()`); a registration always stores the language shown.
  - New column `users.last_login_at`, set by `AuthManager.record_login()` after every sign-in in `main.py`, including single-user mode. `AuthManager.login_screen_appearance()` returns theme, accent colour and language of the user who signed in last; accounts from before the column count as never signed in, so the oldest account decides until someone signs in. Before the first account exists, the installer's choices apply. `main.py` applies them before it shows the dialog, and `LoginDialog(theme=…)` passes the theme on to the dialog's title bar. Theme, accent colour and language are stored unencrypted, so no password is needed to read them.
  - The styles are in the dark and light stylesheets; the gray theme derives them as usual. `primaryBtn` and `secondaryBtn` have a `size="large"` variant. The language menu draws its chevron in the theme's icon colour, because the shared chevron uses `currentColor`, which renders black in a stylesheet `url()`.
  - The lockout countdown writes days as "d" instead of the German "T", and keeps running when the language is switched.
  - The network of linked nodes from the About banner moved to `src/ui/node_network.py` (`paint_node_network()`). The banner draws it from there, pixel for pixel as before; the login screen's backdrop draws two copies in the accent colour, offset against each other and running past the window edges beside the header.
  - New README screenshot of the login screen.
  - `NodeFieldBackdrop` (also in `node_network.py`) draws a field of node clusters behind the content of a widget: a child that follows the host's size and is lowered below its other children. The user management and the profile use one on the scroll area's viewport, so it stays put while the cards scroll over it (checked in a real window: after scrolling, the screen matches a full repaint pixel for pixel); the right panel keeps one on its scroll viewport for the empty overview and a connection's details, where the seed is the connection's id (`host:<id>`), so every connection has a pattern of its own; `show_field()` takes the widget to keep clear (`quiet`). `node_field()` builds the field from a seed per page: two opposite corners and one or two edges get a cluster each, in one of three styles (a mesh with shaded triangles, a star around a hub, a winding chain with side shoots), the other corners often a smaller, paler one; dashed long links join some clusters, and loose dots sit near the edges. Clusters are laid out in px from their anchor, so they keep their shape at any window size, and some of their nodes lie beyond the edge, so links run out of the page. The opacity falls from the edges towards the middle; around the overview's text it drops to nothing, and links that would cross the text are left out. Right-to-left layouts mirror the field. Tests in `tests/test_node_network.py`.
  - New tests in `tests/test_login_dialog.py` cover the look of the last user, the installer fallback, the language switch, storing the picked language, the password toggle, the Caps Lock hint and the error box.

  #### Themes, header and title bar

  - The theme id `dark` now means black: `build_stylesheet("dark")` returns `BLACK_STYLESHEET = _to_black(STYLESHEET)`, derived from the navy sheet like the gray one, through `_BLACK_MAP` and `_BLACK_RGBA`. Every neutral becomes an untinted gray (r = g = b): black (`#000000`) for the frame (title bar, sidebar, headers, status bar), `#0a0a0a` for the content and `#121212` for cards, all darker than in the gray theme. Accent shades, accent tints and the semantic colours stay as in the navy sheet, which is now the theme `blue` ("Blue (classic)").
  - Settings and `install_prefs.json` that store `dark` get black without a migration, and so do new installations, where `dark` was and stays the default. `THEMES` is `("dark", "blue", "gray", "light")`; `THEME_COLORS`, `dark_tone()` (unchanged colours only for `blue`), the title bar palettes (`DARK_PALETTE` black, `BLUE_PALETTE` navy) and the file browser palettes (`DARK`, `BLUE`) follow. The settings and the installer list Black, Blue (classic), Gray and Light; the installer writes `dark`, `blue`, `gray` or `light`.
  - The title bar painted no background of its own: `CustomTitleBar` is a `QWidget` subclass, which draws a stylesheet background only with `WA_StyledBackground`. What showed was `#fwOuter`, the window colour (gray: `#1f1f1f` against the `#181818` frame). It now sets the attribute, and the title bar palettes take the sidebar's colour: `#000000` (black), `#0a0a0f` (blue), `#181818` (gray), `#e4e8ef` (light, with darker hover and pressed fills). A test compares the palette with the `#sidebar` colour of every sheet.
  - The header rows above the connection list and the right panel are 52 px high but had 12 px margins at the top and bottom, which left 28 px for 30–32 px controls: they sank onto the bottom border and the badge was cut off. The margins are now 0, so the controls are centred. The badge is hidden while there are no connections instead of showing as an empty pill.
  - The splitter handle (`_PillHandle`) carries a `#splitterHeaderBand` child, 53 px high (the 52 px header plus its border), in the header colour and border, so the window colour no longer shows between the two headers. The connection list's header border has the right panel's colour (`#1f2b3a`) instead of a darker one. The handle's pill follows the accent colour.
  - New setting `background_network` (column `app_settings.background_network`, default 1, a checkbox under Appearance): `node_network.set_background_enabled()` switches every `NodeFieldBackdrop` and the login screen's networks off; the About banner keeps its network. `AuthManager.login_screen_appearance()` returns it as well, so the login screen follows the user who signed in last.
  - In single-user mode the sidebar hides the profile button (`_sync_profile_btn()`, also run after switching the login mode).
  - New `Stepper` widget (`src/ui/widgets/stepper.py`) for the check interval: a `QSpinBox` without its buttons between two round 24 px buttons with the `minus` and `plus` icons, which repeat while held and turn pale at the ends of the range. It offers `value()`, `setValue()`, `setRange()` and `valueChanged`, so the settings form reads and checks it as before. Styles `#stepper` and `#stepperBtn` in the dark and light sheets; tests in `tests/test_stepper.py`.
  - `accent_text_color()` finds the text colour on the accent with APCA (SAPC 0.0.98G): white while its lightness contrast is 65 or more, otherwise white or near-black (`#111111`), whichever has the higher WCAG contrast. The old rule (relative luminance above 0.36 gives dark text) put white text on orange `#f97316` (2.8:1) and on green `#00b62f` (2.7:1); now every tested accent gets at least 3:1.
  - A text colour of the user's own: setting `accent_text_color` (column `app_settings.accent_text_color`, "" = automatic), passed with the accent through `set_current_accent(accent, text_color)` and `build_stylesheet(theme, accent, text_color)`. `text_on_accent()` returns the colour in use for the current accent; the About banner, the "Active" pill, the file browser's selected rows and the primary buttons use it. `AccentColorDialog` has radio buttons for automatic (naming its pick), white, black and custom with a HEX field, a sample, `textColorChanged` for the live preview, and `pick()` returns (colour, text colour); "Standard" also resets the text to automatic, and Cancel restores both. The accent button in the settings shows an "A" in the text colour. The login screen takes the text colour of the user who signed in last.
  - Tests in `tests/test_theme_accent.py` cover the black sheet (untinted, darker than gray, every navy neutral mapped), `dark` showing black and `blue` the navy look, the palettes, the title bar storing the new settings, the automatic and the chosen text colour on the accent and the picker's text colour row; `tests/test_node_network.py` covers switching the network off.

  #### Help links and screenshots

  - `src/help_links.py` builds the docs URLs: a page (`connections`, `settings`, `interface`, `users`) and an anchor, on the German site while the UI speaks German and on the English one otherwise. The connection form has a help button in the right panel's header (anchor `connection-form`) and a 16 px "?" (`#fieldHelpBtn`) beside the label of every field and section; their anchors are listed in `help_links.CONNECTION_FIELDS`, and a test checks that the form uses no other. New hint `addedit.path.hint` below the path.
  - New README screenshots: every screen in the four themes as one 2x2 picture (Black and Gray with the accent `#228c2b`, Light and Blue (classic) with the default accent), with fictional hosts and data. They were taken from the running app against a local demo SSH/SFTP server; the old single-theme pictures are gone.

  #### Connection filter

  - A new `magnifier.svg`, drawn for this button (a lens with a glint and a heavier grip), opens the filter field below the connection list's header; Ctrl+F does the same and is switched off on the file browser page like the other main window shortcuts, so the browser's own Ctrl+F stays unambiguous.
  - `src/connection_filter.py`: a connection matches when every word of the query appears, ignoring case, in its name, host, user or "user@host". `_apply_list_filters()` replaces `_apply_group_filter()` and applies the group filter and the text filter together on every keystroke; the field shows "3 of 8" (out of the connections in the selected group) or "No matches".
  - The filter text is stored per user in `app_settings.connection_filter_enc`/`connection_filter_iv`, encrypted with the user's key like the connections it may name, in columns of their own that saving the settings never overwrites (`get_connection_filter()`, `save_connection_filter()`). It is saved with every change and restored at the start, with the field open. It is cleared only by hand: the × in the field. A second click on the magnifier or Esc closes the field only while it is empty; Esc in a filled field just leaves it.
  - Tests in `tests/test_connection_filter.py` cover matching, the encrypted storage and that saving the settings keeps the filter.

  #### Tips in the empty overview

  - `src/tips.py` holds the tips: each is a translation key (`tip.<id>`) and a condition on a `TipContext`, which holds the user's settings, the number of connections and of SFTP connections, mounted drives, groups, templates, plain FTP hosts, password or key login, CLI access, single-user mode, whether single-user mode could be switched on, and admin rights. `TipContext.collect()` derives it from the connections; the main window builds it in `_tip_context()` and asks `AuthManager.can_enable_single_user_mode()`, which probes Credential Manager, only for an admin with password login.
  - The tips share the heading `tip.title`; every joke has one of its own (`tip.<id>.title`, see `Tip.title_key`).
  - `pick_tip()` picks at random among the tips that apply and avoids the last 20 shown; while there is no connection, the tip on adding one comes first. The texts `panel.placeholder.title` and `panel.placeholder.body` are gone.
  - The overview's body text has a minimum height instead of a fixed 45 px, so longer tips are not cut off. New style `#tipNextBtn` in the dark and light sheets, in the accent colour.
  - Tests in `tests/test_tips.py` cover the translations (every tip in every language, no texts left without a tip), the conditions (single-user mode, settings that are already on, the chosen terminal, no connections, FTP hosts) and that tips do not repeat.

  #### Single-user mode by default

  - `main.py` starts with `AuthManager.sign_in_automatically()`. It signs in single-user mode as before; when no account exists yet, it sets single-user mode up through `initialize_single_user_mode()`, so the first start shows no login dialog. If that fails (Windows Credential Manager unavailable, or the password cannot be stored), it logs why and the registration form appears as before. Installations with password login are not affected.
  - The new account takes the installer's language and theme, like any first account.
  - In the users panel and the profile, single-user mode now talks about creating an account: the button reads "Create account" instead of "Enable multi-user login", in all six languages.
  - New tests in `tests/test_single_user_mode.py` cover the first start with and without Credential Manager, a failed store and an installation with password login.

  #### Fixed: texts that bypassed the translations

  - Texts written into the code instead of going through `tr()` now have translation keys in all six languages: the tooltips of the window buttons (`custom_titlebar.py`, `frameless_dialog.py`) and of the dialog height button (`dialog_utils.py`); "Cancel"/"OK" in `StyledInputDialog` and "OK" in `StyledMessageBox`; the confirm buttons for deleting a user and resetting a password; the "Copy error message" tooltip; the "Error:" prefix in the status bar; "Copy details" in the crash dialog; the "Exit {code}" badge in the CLI history; the debug window titles.
  - `StyledMessageBox.question()` defaulted to the German "Ja"/"Nein". The defaults are now `tr("dialog.yes")`/`tr("dialog.no")`, resolved when the dialog opens, because the language is only known at runtime. This affected the confirmation for deleting a template.
  - `StyledMessageBox` chose the red confirm button by looking for "löschen", "delete", "entfernen" or "remove" in the message, so it worked only in German and English. A `destructive` parameter replaces the word list; the six confirmations that were red in English pass `destructive=True`. Deleting local files, which go to the Recycle Bin, stays blue as before.
  - The CPU line in the system info used a hard-coded "cores"; it now uses the existing `sysinfo.cores` key.
  - The warning shown when the GUI exe is started with `--connect-cli` uses the language chosen in the installer (`install_prefs.json`), since no user is signed in at that point.
  - `QPushButton` reads "&" as a shortcut marker. The texts of `login.create_account`, `logout.quit_unmount` and `update.btn.install_now` are escaped to "&&", as the file browser already did for `fb.settings.confirm_move`.
  - Errors from switching the login mode are raised as `SingleUserModeError` with a translation key instead of English messages. Unexpected errors show a translated sentence with the technical detail in brackets.
  - Adding a user whose name already exists showed SQLite's "UNIQUE constraint failed" text; it now says that the name is taken.
  - `tests/test_ui_translations.py` checks that all languages have the same keys, that every `tr()` key exists, that no live module passes a fixed text to a widget, and that the dialogs, title bar and message boxes show translated texts in English, Spanish and Russian. Three modules that nothing imports any more (`settings_dialog.py`, `add_edit_dialog.py`, `loading_overlay.py`) and the unused `UserManagementDialog` are left out of the text check; a test fails if one of them is used again.

  #### Fixed: windows flashing up after the login

  - `ConnectionCard._build_ui()` made the SSH button visible before adding it to the card's layout. A widget shown without a parent is a top-level window, so every SFTP card showed a 32×32 window until the layout adopted it a moment later; FTP cards hide the button and were not affected. `setVisible()` now comes after `addWidget()`.
  - Found by logging every window shown (`SetWinEventHook`) while the app started without a console, the way the built exe does, and by recording each widget shown as a window inside the app. The automatic reconnect started `sshfs.exe` and `label` with `CREATE_NO_WINDOW` and showed no window; after the fix, the login, the telemetry question and the main window are the only windows left.
  - `tests/test_no_flashing_windows.py` fails if building a connection card (SFTP, SFTP mounted, FTP) shows any window.

  #### Removed: Pro licence

  - `src/pro_manager.py` is deleted: the licence activation against `neo_pro_validate.php`, the local HMAC check, the machine ID read via `wmic` and the switches `SHOW_PRO_UI` and `FREE_TERMINAL_SESSION_LIMIT`.
  - The hidden licence section of the settings (`_build_pro_settings`, `_sf_activate_pro`) and the terminal session limit (`_terminal_limit_reached`, `_show_pro_session_limit_dialog`) are removed from `src/ui/main_window.py`. `_add_terminal_session()` now opens the session directly.
  - The `pro_licenses` table is no longer created, and a migration drops it from existing databases together with any stored licence token.
  - The translation keys `settings.section.pro`, `settings.pro.*` and `pro.session_limit.*` are removed from all six languages.

  </details>

  ---

  ## [1.6.1] — 2026-09-28

  ### What changes for you

  - **Updates install themselves again.** Since version 1.5.4, an update that was downloaded and set to install at the next start was never installed: the installer did not start. From 1.6.1 on, the app hands over to the installer, which installs the update in the background and then starts the app again.
    - If you are still on 1.6.0 or older, install 1.6.1 once by hand: click "Download in browser" in the update window, or download the setup from the [releases page](https://github.com/gregorkrebs/NeoSSHWinManager/releases/latest) and run it. Your connections and settings are kept.
  - **The update window is easy to read.** Headings, lists and bold text are shown formatted instead of as raw markup, and you see the changes of every version since the one you have installed.
  - **Drag & drop in the file browser works again.** In 1.6.0, dropping files onto the file list or the folder tree showed an error message and nothing was transferred, whether the files came from the other side of the browser, from Windows Explorer or from a mounted drive. Uploads, downloads and moves by drag & drop now work as intended. Dropping onto the path bar was not affected.

  <details>
  <summary>Technical details</summary>

  #### Fixed

  - **In-app updates never installed (1.5.4 to 1.6.0).** `launch_pending_installer()` handed over to a hidden `cmd.exe` script that waited for the app to exit and then ran the installer. Started from the windowed app, which has no console, the script inherited invalid standard handles and died at the first `find` of its wait loop. The installer never ran, and the script never started the app again. A frozen stand-in app reproduced this; with valid standard handles, the same script ran through.
    - The script is gone. The app now starts the installer itself with `/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /WAITPID=… /RELAUNCH=… /LOG=…`, with valid (`DEVNULL`) standard handles, and quits.
    - The installer's `[Code]` section waits in `InitializeSetup` until the app's processes have exited: the app itself and, in the onefile build, its bootloader, which keeps the exe locked a little longer. It waits up to 60 seconds for each. `DeinitializeSetup` starts the app again, also when the installation failed or was cancelled.
    - The installer writes its log to `%APPDATA%\SSHWinManager\updates\install.log`. A `run_update.cmd` left over by an older version is removed.
  - A silent installation (an in-app update) no longer overwrites `install_prefs.json` with the default language and theme. The preferences page is not shown in a silent run, so there is nothing to save.
  - **The update dialog showed release notes as plain text**, so Markdown and the `<details>` block of the technical notes appeared as raw markup. The dialog now renders Markdown (`Qt.TextFormat.MarkdownText`) with clickable links, leaves out the technical details, and uses the better readable `dialogLead` style. In the light theme, the notes no longer sit on a dark background.
  - **Release notes cover every version between the installed and the new one.** They are taken from `CHANGELOG.md` at the release tag, with the release text as a fallback.
  - New tests in `tests/test_updater.py` cover the installer command line, the one-time handover at startup and the release notes.
  - `FileView.dropEvent` (`src/filebrowser/ui/pane.py`) and `FsTree.dropEvent` (`src/filebrowser/ui/tree.py`) called `QAbstractItemView.stopAutoScroll()`, which PyQt6 does not expose. Every drop onto a file list or folder tree raised `AttributeError` before the transfer or move was queued. Both now reset the view through the base class's `dragLeaveEvent()`, which stops the auto-scroll timer and returns the view to `NoState`.
  - A new UI test drops files from the PC side and as Explorer URLs onto the server's file list and folder tree and checks that they arrive.

  </details>

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
