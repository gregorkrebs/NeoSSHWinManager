"""
titlebar_theme.py – Colour palettes for the custom window titlebar.

Provides two frozen dataclasses (DARK_PALETTE, LIGHT_PALETTE) and a
get_palette() helper so every titlebar widget reads colours from a single
source of truth.  No Qt imports – pure data module.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TitlebarPalette:
    """All colours required to paint the custom titlebar and its buttons."""
    bg: str           # Titlebar background
    bg_hover: str     # Non-close button hover fill
    bg_pressed: str   # Non-close button pressed fill
    close_hover: str  # Close button hover fill (red)
    close_pressed: str  # Close button pressed fill
    text: str         # Window-title text colour
    text_dim: str     # Version-pill text colour
    icon: str         # Default button-icon colour
    icon_hover: str   # Button-icon colour on hover (applied via CSS)
    border: str       # 1-px bottom border of the bar


# ── palettes ───────────────────────────────────────────────────────────────

DARK_PALETTE = TitlebarPalette(
    bg="#0d0d12",
    bg_hover="#182030",
    bg_pressed="#111822",
    close_hover="#c42b1c",
    close_pressed="#9e1b0e",
    text="#c8d6e5",
    text_dim="#8fa4b8",
    icon="#4a6070",
    icon_hover="#c8d6e5",
    border="#1a1a2e",
)

GRAY_PALETTE = TitlebarPalette(
    bg="#181818",
    bg_hover="#2a2d2e",
    bg_pressed="#313131",
    close_hover="#c42b1c",
    close_pressed="#9e1b0e",
    text="#cccccc",
    text_dim="#9d9d9d",
    icon="#8b8b8b",
    icon_hover="#cccccc",
    border="#2b2b2b",
)

LIGHT_PALETTE = TitlebarPalette(
    bg="#f0f2f5",
    bg_hover="#e2e6ec",
    bg_pressed="#d4d8e2",
    close_hover="#c42b1c",
    close_pressed="#9e1b0e",
    text="#1a2332",
    text_dim="#5a6a7a",
    icon="#8090a0",
    icon_hover="#1a2332",
    border="#d4d8df",
)


def get_palette(theme: str) -> TitlebarPalette:
    """Return the palette for *theme* ('dark', 'gray' or 'light')."""
    return {"light": LIGHT_PALETTE, "gray": GRAY_PALETTE}.get(theme, DARK_PALETTE)
