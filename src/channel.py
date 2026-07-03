"""
channel.py - Branch/channel helpers for development branding.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


APP_NAME = "NEO SSH-Win Manager"
_DEV_CHANNELS = {"dev", "nightly"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _git_branch_name() -> str:
    head_path = _repo_root() / ".git" / "HEAD"
    if not head_path.exists():
        return ""

    try:
        head_value = head_path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""

    if not head_value.startswith("ref:"):
        return ""

    return head_value.rsplit("/", 1)[-1].strip().lower()


@lru_cache(maxsize=1)
def current_channel() -> str:
    env_channel = os.environ.get("NEOSSH_CHANNEL", "").strip().lower()
    if env_channel:
        return env_channel

    branch_name = _git_branch_name()
    if branch_name in _DEV_CHANNELS:
        return branch_name

    return ""


def channel_badge() -> str:
    channel = current_channel()
    return f"[{channel.upper()}]" if channel else ""


def display_name(base_name: str = APP_NAME) -> str:
    badge = channel_badge()
    return f"{base_name} {badge}".strip()


def display_version(version: str) -> str:
    channel = current_channel()
    if channel:
        return f"v{version} ({channel.upper()})"
    return f"v{version}"