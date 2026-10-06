"""
frameless_dialog.py – FramelessDialog base class.

Replaces the native title bar of a QDialog with a compact custom titlebar
(_DialogTitleBar).  Works identically to FramelessMainWindow but for dialogs:
  • no nativeEvent override (avoids ctypes/sip crash on Python 3.14)
  • drag via QWindow.startSystemMove()
  • DWM drop-shadow + rounded corners via Win32 DWM APIs

Usage
-----
    class MyDialog(FramelessDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("My Dialog")
            self._build_ui()

        def _build_ui(self):
            layout = QVBoxLayout(self)   # intercepted – titlebar is injected above
            ...

Theme
-----
    Call set_dialog_theme('dark'|'light') at any point to repaint the titlebar.
    FramelessDialog.__init__ auto-detects the theme from a FramelessMainWindow
    parent if one exists.
"""
from __future__ import annotations

import ctypes
import os
import sys

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QApplication
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QCursor, QPixmap

from src.ui.titlebar_theme import get_palette, TitlebarPalette
from src.i18n import tr


# ── compact dialog titlebar ──────────────────────────────────────────────────

class _DialogTitleBar(QWidget):
    """
    Slim (32 px) titlebar:
      [app-icon] [title] ··· [□ maximize (optional)] [✕]

    Right-click on the icon zone → native Windows system menu.
    Double-click on the icon zone → close (reject).
    Double-click elsewhere → toggle maximize (if enabled).
    """

    HEIGHT: int = 32
    _ICON_ZONE_W: int = 32   # left margin + icon label width

    close_requested    = pyqtSignal()
    maximize_requested = pyqtSignal()   # only emitted when show_maximize=True

    def __init__(
        self,
        title:         str            = "",
        theme:         str            = "dark",
        app_icon:      QPixmap | None = None,
        show_maximize: bool           = False,
        parent:        QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette       = get_palette(theme)
        self._drag_pos      = None
        self._show_maximize = show_maximize
        self._maximized     = False
        self.setFixedHeight(self.HEIGHT)
        self.setObjectName("dlgTitlebar")
        self._build(title, app_icon)
        self._apply_palette()

    # ── public ───────────────────────────────────────────────────────────────

    def set_title(self, title: str) -> None:
        self._title_lbl.setText(title)

    def set_theme(self, theme: str) -> None:
        self._palette = get_palette(theme)
        self._apply_palette()

    def set_maximized(self, maximized: bool) -> None:
        self._maximized = maximized
        if self._max_btn is not None:
            from src.ui.icons import icon as svg_icon
            icon_name = "restore" if maximized else "maximize"
            self._max_btn.setIcon(svg_icon(icon_name, self._palette.icon, 13))
            self._max_btn.setIconSize(QSize(13, 13))
            self._max_btn.setToolTip(tr("window.restore") if maximized else tr("window.maximize"))

    # ── private ──────────────────────────────────────────────────────────────

    def _build(self, title: str, app_icon: QPixmap | None) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # App icon zone (always present; shows icon or empty padding)
        self._icon_lbl = QLabel()
        self._icon_lbl.setFixedSize(self._ICON_ZONE_W, self.HEIGHT)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if app_icon is not None:
            self._icon_lbl.setPixmap(
                app_icon.scaled(16, 16,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
            )
        layout.addWidget(self._icon_lbl)
        layout.addSpacing(6)

        self._title_lbl = QLabel(title)
        self._title_lbl.setObjectName("dlgTitlebarTitle")
        self._title_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._title_lbl)
        layout.addStretch()

        self._max_btn: QPushButton | None = None
        if self._show_maximize:
            self._max_btn = QPushButton()
            self._max_btn.setFixedSize(40, self.HEIGHT)
            self._max_btn.setCursor(Qt.CursorShape.ArrowCursor)
            self._max_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._max_btn.setToolTip(tr("window.maximize"))
            self._max_btn.clicked.connect(self.maximize_requested)
            layout.addWidget(self._max_btn)

        self._close_btn = QPushButton()
        self._close_btn.setFixedSize(46, self.HEIGHT)
        self._close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._close_btn.clicked.connect(self.close_requested)
        layout.addWidget(self._close_btn)

    def _apply_palette(self) -> None:
        from src.ui.icons import icon as svg_icon
        p = self._palette
        self._close_btn.setIcon(svg_icon("x", p.icon, 14))
        self._close_btn.setIconSize(QSize(14, 14))
        self._close_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;}}"
            f"QPushButton:hover{{background-color:{p.close_hover};}}"
            f"QPushButton:pressed{{background-color:{p.close_pressed};}}"
        )
        if self._max_btn is not None:
            icon_name = "restore" if self._maximized else "maximize"
            self._max_btn.setIcon(svg_icon(icon_name, p.icon, 13))
            self._max_btn.setIconSize(QSize(13, 13))
            self._max_btn.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;}}"
                f"QPushButton:hover{{background-color:{p.bg_hover};}}"
                f"QPushButton:pressed{{background-color:{p.bg_pressed};}}"
            )
        self.setStyleSheet(
            f"#dlgTitlebar{{"
            f"background-color:{p.bg};"
            f"border-bottom:1px solid {p.border};"
            f"}}"
            f"#dlgTitlebarTitle{{"
            f'font-family:"Segoe UI",sans-serif;'
            f"font-size:11px;font-weight:600;"
            f"color:{p.text};background:transparent;"
            f"}}"
        )

    # ── system menu ──────────────────────────────────────────────────────────

    def _show_system_menu(self, global_pos) -> None:
        try:
            win = self.window()
            hwnd = int(win.winId())
            hmenu = ctypes.windll.user32.GetSystemMenu(hwnd, False)
            if not hmenu:
                return
            maximized = win.isMaximized() if hasattr(win, "isMaximized") else False
            MF_GRAYED = 0x0001
            def _set(cmd, grayed):
                ctypes.windll.user32.EnableMenuItem(
                    hmenu, cmd, 0x0000 | (MF_GRAYED if grayed else 0x0000)
                )
            _set(0xF120, not maximized)  # SC_RESTORE
            _set(0xF010, maximized)      # SC_MOVE
            _set(0xF000, maximized)      # SC_SIZE
            _set(0xF030, maximized)      # SC_MAXIMIZE
            _set(0xF020, False)          # SC_MINIMIZE
            cmd = ctypes.windll.user32.TrackPopupMenu(
                hmenu, 0x0100 | 0x0002,
                global_pos.x(), global_pos.y(), 0, hwnd, None,
            )
            if cmd:
                ctypes.windll.user32.PostMessageW(hwnd, 0x0112, cmd, 0)
        except Exception:
            pass

    # ── drag / mouse ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        local_x = int(event.position().x())
        in_icon = local_x < self._ICON_ZONE_W

        if event.button() == Qt.MouseButton.RightButton and in_icon:
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
                self.close_requested.emit()
            elif self._show_maximize:
                self.maximize_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


# ── base class ───────────────────────────────────────────────────────────────

class FramelessDialog(QDialog):
    """
    QDialog base class with a custom titlebar.

    Subclasses build content into ``self._fdlg_content``:

        def _build_ui(self):
            layout = QVBoxLayout(self._fdlg_content)
            ...

    Parameters
    ----------
    show_maximize : bool
        If True the titlebar shows a maximize/restore button that toggles
        the dialog height between sizeHint and full screen height.
    """

    def __init__(self, parent=None, *, show_maximize: bool = False) -> None:
        super().__init__(parent)

        # Auto-detect theme from a FramelessMainWindow parent
        theme = "dark"
        try:
            from src.ui.frameless_window import FramelessMainWindow
            p = parent
            while p is not None:
                if isinstance(p, FramelessMainWindow) and p.custom_titlebar() is not None:
                    theme = p.custom_titlebar()._theme
                    break
                p = p.parent() if hasattr(p, "parent") else None
        except Exception:
            pass
        self._fdlg_theme:       str  = theme
        self._fdlg_dwm_done:    bool = False
        self._fdlg_natural_h:   int  = 0    # remembered compact height for toggle

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)

        # Load app icon
        app_icon = self._fdlg_load_icon()

        # ── Build wrapper immediately ─────────────────────────────────────
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._fdlg_titlebar = _DialogTitleBar(
            title         = "",
            theme         = theme,
            app_icon      = app_icon,
            show_maximize = show_maximize,
            parent        = self,
        )
        self._fdlg_titlebar.close_requested.connect(self.reject)
        if show_maximize:
            self._fdlg_titlebar.maximize_requested.connect(self._fdlg_toggle_height)
        outer.addWidget(self._fdlg_titlebar)

        self._fdlg_content = QWidget()
        self._fdlg_content.setObjectName("fdlgContent")
        outer.addWidget(self._fdlg_content, stretch=1)

        QDialog.setLayout(self, outer)

    # ── icon helper ──────────────────────────────────────────────────────────

    @staticmethod
    def _fdlg_load_icon() -> QPixmap | None:
        def _res(rel: str) -> str:
            if hasattr(sys, "_MEIPASS"):
                return os.path.join(sys._MEIPASS, rel)
            # Walk up to repo root from src/ui/
            here = os.path.dirname(os.path.abspath(__file__))
            root = os.path.dirname(os.path.dirname(here))
            return os.path.join(root, rel)
        for name in ("assets/app_icon.png", "assets/app_icon.ico"):
            path = _res(name)
            if os.path.exists(path):
                pm = QPixmap(path)
                if not pm.isNull():
                    return pm
        return None

    # ── maximize toggle ──────────────────────────────────────────────────────

    def _fdlg_toggle_height(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        max_h = int(screen.availableGeometry().height() * 0.95)
        if self.height() < max_h - 10:
            # going to full height
            self._fdlg_natural_h = self.height()
            geo = screen.availableGeometry()
            self.setGeometry(self.x(), geo.y() + int(geo.height() * 0.025),
                             self.width(), max_h)
            self._fdlg_titlebar.set_maximized(True)
        else:
            # restoring
            target_h = self._fdlg_natural_h or self.sizeHint().height()
            self.resize(self.width(), target_h)
            self._fdlg_titlebar.set_maximized(False)

    # ── public API ───────────────────────────────────────────────────────────

    def set_dialog_theme(self, theme: str) -> None:
        self._fdlg_theme = theme
        if self._fdlg_titlebar is not None:
            self._fdlg_titlebar.set_theme(theme)

    # ── Qt overrides ─────────────────────────────────────────────────────────

    def layout(self):  # noqa: N802
        """Return the CONTENT widget's layout so subclass code works unchanged."""
        if hasattr(self, "_fdlg_content"):
            inner = self._fdlg_content.layout()
            if inner is not None:
                return inner
        return QDialog.layout(self)

    def setWindowFlags(self, flags) -> None:  # noqa: N802
        TYPE_MASK = (
            Qt.WindowType.Window
            | Qt.WindowType.Dialog
            | Qt.WindowType.Tool
            | Qt.WindowType.Sheet
            | Qt.WindowType.Popup
        )
        type_part = Qt.WindowType(int(flags) & int(TYPE_MASK))
        super().setWindowFlags(type_part | Qt.WindowType.FramelessWindowHint)

    def setWindowTitle(self, title: str) -> None:  # noqa: N802
        super().setWindowTitle(title)
        if self._fdlg_titlebar is not None:
            self._fdlg_titlebar.set_title(title)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._fdlg_dwm_done:
            self._fdlg_dwm_done = True
            self._fdlg_apply_dwm()

    def _fdlg_apply_dwm(self) -> None:
        try:
            hwnd = int(self.winId())
            GWL_STYLE     = -16
            WS_THICKFRAME = 0x00040000
            cur = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, cur | WS_THICKFRAME)
            SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0020
            ctypes.windll.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FLAGS)
            class MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth",    ctypes.c_int),
                    ("cxRightWidth",   ctypes.c_int),
                    ("cyTopHeight",    ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                hwnd, ctypes.byref(MARGINS(0, 0, 0, 1))
            )
            DWMWCP_ROUND = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(DWMWCP_ROUND), ctypes.sizeof(DWMWCP_ROUND)
            )
        except Exception:
            pass


