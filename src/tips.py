"""
tips.py – The tips in the empty right panel ("Did you know?").

Every tip is a text ("tip.<id>" in the translations) and a condition on what
the user has set up, so a tip only shows up where it helps: single-user mode
only for the one account that signs in with a password, the FTP tips only
with FTP hosts, the hint at a setting only while it is off. A few jokes are
mixed in.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from src.config import PROTOCOL_FTP, AppSettings, Connection


@dataclass(frozen=True)
class TipContext:
    """What the tips depend on; see collect()."""
    settings: AppSettings = field(default_factory=AppSettings)
    connections: int = 0            # saved connections, templates not counted
    ssh_connections: int = 0        # of those SFTP: drive, terminal, system info
    mounted: int = 0
    has_groups: bool = False
    has_templates: bool = False
    has_plain_ftp: bool = False
    password_auth: bool = False     # an SFTP connection signs in with a password
    key_auth: bool = False          # … with a private key
    cli_access: bool = False        # a connection has CLI access switched on
    single_user: bool = False       # single-user mode: automatic login
    can_go_single: bool = False     # single-user mode can be switched on now
    is_admin: bool = False

    @classmethod
    def collect(cls, settings: AppSettings, connections: Sequence[Connection],
                templates: Sequence[Connection] = (), mounted_ids: Iterable[str] = (), *,
                single_user: bool = False, can_go_single: bool = False,
                is_admin: bool = False) -> "TipContext":
        ssh = [c for c in connections if not c.is_ftp]
        ids = {c.id for c in connections}
        return cls(
            settings=settings,
            connections=len(connections),
            ssh_connections=len(ssh),
            mounted=len(ids & set(mounted_ids)),
            has_groups=any(g.strip() for c in connections for g in (c.groups or "").split(",")),
            has_templates=bool(templates),
            has_plain_ftp=any(c.protocol == PROTOCOL_FTP for c in connections),
            password_auth=any(c.auth_method == "password" for c in ssh),
            key_auth=any(c.auth_method == "key" for c in ssh),
            cli_access=any(c.cli_access_enabled for c in ssh),
            single_user=single_user,
            can_go_single=can_go_single,
            is_admin=is_admin,
        )


def _always(_ctx: TipContext) -> bool:
    return True


@dataclass(frozen=True)
class Tip:
    id: str
    when: Callable[[TipContext], bool] = _always
    funny: bool = False
    first: bool = False     # shown before any other tip while it applies

    @property
    def key(self) -> str:
        return f"tip.{self.id}"

    @property
    def title_key(self) -> str:
        """Every joke has a heading of its own; the other tips share one."""
        return f"{self.key}.title" if self.funny else "tip.title"


def _hosts(n: int = 1) -> Callable[[TipContext], bool]:
    return lambda c: c.connections >= n


def _ssh(n: int = 1) -> Callable[[TipContext], bool]:
    return lambda c: c.ssh_connections >= n


TIPS: tuple[Tip, ...] = (
    # the connection list
    Tip("first_connection", lambda c: c.connections == 0, first=True),
    Tip("list_shortcuts", _hosts()),
    Tip("filter", _hosts(6)),
    Tip("groups_intro", lambda c: c.connections >= 4 and not c.has_groups),
    Tip("groups_mount", lambda c: c.has_groups and c.ssh_connections >= 2),
    Tip("groups_state", _ssh(3)),
    Tip("mount_all", _ssh(2)),
    Tip("templates_intro", lambda c: c.connections >= 2 and not c.has_templates),
    Tip("templates_use", lambda c: c.has_templates),
    Tip("context_menu", _ssh()),
    Tip("ask_auth", _ssh()),
    # drives
    Tip("status_folder", _ssh()),
    Tip("tray", _ssh()),
    Tip("close_to_tray", lambda c: c.ssh_connections >= 1 and not c.settings.minimize_to_tray),
    Tip("start_with_windows", lambda c: c.ssh_connections >= 1 and not c.settings.start_with_windows),
    Tip("auto_connect", lambda c: c.ssh_connections >= 1 and not c.settings.auto_reconnect),
    Tip("dir_cache", lambda c: c.ssh_connections >= 1 and not c.settings.sshfs_disable_cache),
    Tip("shared_letters", lambda c: c.ssh_connections >= 2 and not c.settings.allow_shared_drive_letters),
    Tip("ghost_drives", _ssh()),
    Tip("windows_servers"),
    Tip("quit_keep_mounted", lambda c: c.mounted >= 1),
    # terminal
    Tip("terminal_tabs", lambda c: c.ssh_connections >= 1 and c.settings.terminal_client == "xterm"),
    Tip("terminal_choice", _ssh()),
    Tip("putty_ppk", lambda c: c.settings.terminal_client == "putty"),
    # file browser
    Tip("file_browser", _hosts()),
    Tip("fb_split", _hosts()),
    Tip("fb_shortcuts", _hosts()),
    Tip("fb_undo", _hosts()),
    Tip("fb_bookmarks", _hosts()),
    Tip("fb_url", _hosts()),
    Tip("fb_archive", _ssh()),          # packs and unpacks over SSH
    Tip("fb_sync", _hosts()),
    Tip("fb_terminal", _ssh()),
    Tip("fb_open_with", _hosts()),
    Tip("fb_checksum", _ssh()),         # sha256sum / PowerShell on the server
    Tip("fb_resume", _hosts()),
    Tip("fb_hidden", _hosts()),
    Tip("fb_speed", _hosts()),
    Tip("ftp_explorer", lambda c: c.has_plain_ftp),
    Tip("ftp_plain", lambda c: c.has_plain_ftp),
    Tip("system_info", _ssh()),
    # accounts and security
    Tip("single_user_on", lambda c: c.is_admin and not c.single_user and c.can_go_single),
    Tip("single_user_account", lambda c: c.is_admin and c.single_user),
    Tip("encryption"),
    Tip("login_lockout", lambda c: not c.single_user),
    Tip("key_auth", lambda c: c.password_auth and not c.key_auth),
    Tip("host_key", _ssh()),
    Tip("login_language", lambda c: not c.single_user),
    Tip("cli", lambda c: c.ssh_connections >= 1 and not c.cli_access),
    Tip("cli_history", lambda c: c.cli_access),
    # appearance
    Tip("themes"),
    Tip("accent", lambda c: not c.settings.accent_color),
    Tip("background_network", lambda c: c.settings.background_network),
    Tip("languages"),
    # the project
    Tip("github"),
    Tip("copy_version"),
    Tip("help_buttons"),
    Tip("demo"),
    Tip("telemetry", lambda c: not c.settings.telemetry_enabled),
    Tip("updates"),
    # just for fun
    Tip("fun_vim", funny=True),
    Tip("fun_udp", funny=True),
    Tip("fun_localhost", funny=True),
    Tip("fun_rm_rf", funny=True),
    Tip("fun_lightbulb", funny=True),
    Tip("fun_pills", funny=True),
    Tip("fun_binary", funny=True),
)


def eligible(ctx: TipContext) -> list[Tip]:
    """The tips that apply to *ctx*."""
    return [t for t in TIPS if t.when(ctx)]


def pick_tip(ctx: TipContext, recent: Sequence[str] = (),
             rng: random.Random | None = None) -> Tip:
    """A tip for *ctx*, preferring one that is not among the *recent* ids
    (oldest first) and never the last one shown while there is another."""
    rng = rng or random
    pool = eligible(ctx)
    fresh = [t for t in pool if t.id not in recent]
    for tip in fresh:
        if tip.first:
            return tip
    if not fresh:
        fresh = [t for t in pool if not recent or t.id != recent[-1]] or pool
    return rng.choice(fresh)
