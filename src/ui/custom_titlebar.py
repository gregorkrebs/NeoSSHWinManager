"""
custom_titlebar.py – Custom window titlebar widget.

Provides _TitlebarButton and CustomTitleBar.
CustomTitleBar emits minimize_requested, maximize_requested, close_requested.
Theme is controlled via set_theme(); set_maximized() toggles the restore icon.
"""
from __future__ import annotations

import ctypes

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QSize, QRect, pyqtSignal
from PyQt6.QtGui import QPixmap, QCursor

from src.ui.titlebar_theme import TitlebarPalette, get_palette
from src.ui.icons import icon as svg_icon
from src.i18n import tr


# ── control button ──────────────────────────────────────────────────────────

class _TitlebarButton(QPushButton):
    """Compact borderless title-bar button with hover / pressed CSS feedback."""

    def __init__(
        self,
        icon_name: str,
        palette: TitlebarPalette,
        *,
        is_close: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._is_close = is_close
        self.setFixedSize(46, CustomTitleBar.HEIGHT)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._repaint(palette)

    # ── public ──────────────────────────────────────────────────────────────

    def apply_theme(self, palette: TitlebarPalette) -> None:
        self._repaint(palette)

    def set_icon_name(self, name: str, palette: TitlebarPalette) -> None:
        self._icon_name = name
        self._repaint(palette)

    # ── private ─────────────────────────────────────────────────────────────

    def _repaint(self, p: TitlebarPalette) -> None:
        if self._is_close:
            ss = (
                f"QPushButton{{background:transparent;border:none;border-radius:0;}}"
                f"QPushButton:hover{{background-color:{p.close_hover};}}"
                f"QPushButton:pressed{{background-color:{p.close_pressed};}}"
            )
        else:
            ss = (
                f"QPushButton{{background:transparent;border:none;border-radius:0;}}"
                f"QPushButton:hover{{background-color:{p.bg_hover};}}"
                f"QPushButton:pressed{{background-color:{p.bg_pressed};}}"
            )
        self.setStyleSheet(ss)
        self.setIcon(svg_icon(self._icon_name, p.icon, 16))
        self.setIconSize(QSize(16, 16))


# ── titlebar widget ─────────────────────────────────────────────────────────

class CustomTitleBar(QWidget):
    """
    Application titlebar: [icon] [title] [version] ··· [─] [□] [✕]

    Signals
    -------
    minimize_requested  – user clicked the minimise button
    maximize_requested  – user clicked the maximise / restore button
    close_requested     – user clicked the close button
    """

    HEIGHT: int = 36   # px – must match WindowResizer.set_titlebar_height()

    minimize_requested = pyqtSignal()
    maximize_requested = pyqtSignal()
    close_requested    = pyqtSignal()

    def __init__(
        self,
        title: str,
        version: str = "",
        theme: str = "dark",
        app_icon: QPixmap | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme     = theme
        self._palette   = get_palette(theme)
        self._maximized = False
        self._drag_pos  = None   # set on left-press, cleared on release/move
        self.setFixedHeight(self.HEIGHT)
        self.setObjectName("customTitlebar")
        self._build(title, version, app_icon)
        self._apply_palette()

    # ── public API ───────────────────────────────────────────────────────────

    def set_theme(self, theme: str) -> None:
        if self._theme == theme:
            return
        self._theme   = theme
        self._palette = get_palette(theme)
        self._apply_palette()

    def set_title(self, title: str) -> None:
        self._title_lbl.setText(title)

    def set_maximized(self, maximized: bool) -> None:
        self._maximized = maximized
        icon_name = "restore" if maximized else "maximize"
        self._max_btn.set_icon_name(icon_name, self._palette)
        self._max_btn.setToolTip(
            tr("window.restore") if maximized else tr("window.maximize")
        )

    def button_rects_global(self) -> list[QRect]:
        """Screen-space bounding rects for all three control buttons."""
        return [
            QRect(btn.mapToGlobal(btn.rect().topLeft()), btn.size())
            for btn in (self._min_btn, self._max_btn, self._close_btn)
        ]

    # Width of the icon zone (left margin + icon label + spacing).
    # Right-click or double-click here triggers system-menu / close.
    _ICON_ZONE_W: int = 38

    # ── system menu ─────────────────────────────────────────────────────────

    def _show_system_menu(self, global_pos) -> None:
        """Display the native Windows system menu at *global_pos*."""
        try:
            hwnd = int(self.window().winId())
            hmenu = ctypes.windll.user32.GetSystemMenu(hwnd, False)
            if not hmenu:
                return
            # Enable/disable items to match actual window state
            win = self.window()
            maximized = win.isMaximized() if win else False
            MF_ENABLED  = 0x0000
            MF_GRAYED   = 0x0001
            SC_RESTORE   = 0xF120
            SC_MOVE      = 0xF010
            SC_SIZE      = 0xF000
            SC_MINIMIZE  = 0xF020
            SC_MAXIMIZE  = 0xF030
            def _set(cmd, grayed):
                ctypes.windll.user32.EnableMenuItem(
                    hmenu, cmd,
                    0x0000 | (MF_GRAYED if grayed else MF_ENABLED)
                )
            _set(SC_RESTORE,  not maximized)
            _set(SC_MOVE,     maximized)
            _set(SC_SIZE,     maximized)
            _set(SC_MAXIMIZE, maximized)
            _set(SC_MINIMIZE, False)
            TPM_RETURNCMD  = 0x0100
            TPM_RIGHTBUTTON = 0x0002
            cmd = ctypes.windll.user32.TrackPopupMenu(
                hmenu,
                TPM_RETURNCMD | TPM_RIGHTBUTTON,
                global_pos.x(), global_pos.y(),
                0, hwnd, None,
            )
            if cmd:
                ctypes.windll.user32.PostMessageW(hwnd, 0x0112, cmd, 0)  # WM_SYSCOMMAND
        except Exception:
            pass

    # ── drag / double-click ──────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        local_x = int(event.position().x())
        in_icon_zone = local_x < self._ICON_ZONE_W

        if event.button() == Qt.MouseButton.RightButton and in_icon_zone:
            self._show_system_menu(event.globalPosition().toPoint())
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._drag_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            delta = event.globalPosition().toPoint() - self._drag_pos
            if delta.manhattanLength() > 5:
                self._drag_pos = None
                win = self.window()
                if win is not None:
                    handle = win.windowHandle()
                    if handle is not None:
                        handle.startSystemMove()
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            local_x = int(event.position().x())
            if local_x < self._ICON_ZONE_W:
                # Double-click on the icon → close (standard Windows behaviour)
                self.close_requested.emit()
            else:
                self.maximize_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self, title: str, version: str, app_icon: QPixmap | None) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(0)

        if app_icon is not None:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(
                app_icon.scaled(
                    16, 16,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            icon_lbl.setFixedSize(22, self.HEIGHT)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(icon_lbl)
            layout.addSpacing(6)

        self._title_lbl = QLabel(title)
        self._title_lbl.setObjectName("customTitlebarTitle")
        self._title_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._title_lbl)

        if version:
            layout.addSpacing(8)
            self._ver_lbl = QLabel(version)
            self._ver_lbl.setObjectName("customTitlebarVersion")
            self._ver_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(self._ver_lbl)
        else:
            self._ver_lbl = None

        layout.addStretch()

        p = self._palette
        self._min_btn = _TitlebarButton("minus", p, parent=self)
        self._min_btn.setToolTip(tr("window.minimize"))
        self._min_btn.clicked.connect(self.minimize_requested)

        self._max_btn = _TitlebarButton("maximize", p, parent=self)
        self._max_btn.setToolTip(tr("window.maximize"))
        self._max_btn.clicked.connect(self.maximize_requested)

        self._close_btn = _TitlebarButton("x", p, is_close=True, parent=self)
        self._close_btn.setToolTip(tr("dialog.close"))
        self._close_btn.clicked.connect(self.close_requested)

        layout.addWidget(self._min_btn)
        layout.addWidget(self._max_btn)
        layout.addWidget(self._close_btn)

    # ── palette ──────────────────────────────────────────────────────────────

    def _apply_palette(self) -> None:
        p = self._palette
        self.setStyleSheet(
            f"#customTitlebar{{"
            f"background-color:{p.bg};"
            f"border-bottom:1px solid {p.border};"
            f"}}"
            f"#customTitlebarTitle{{"
            f'font-family:"Segoe UI",sans-serif;'
            f"font-size:12px;font-weight:600;"
            f"color:{p.text};background:transparent;"
            f"}}"
            f"#customTitlebarVersion{{"
            f'font-family:"Consolas";font-size:10px;'
            f"color:{p.text_dim};background:transparent;"
            f"padding:0 4px;"
            f"}}"
        )
        for btn in (self._min_btn, self._max_btn, self._close_btn):
            btn.apply_theme(p)
        # Refresh maximize/restore icon with new palette colour
        icon_name = "restore" if self._maximized else "maximize"
        self._max_btn.set_icon_name(icon_name, p)
