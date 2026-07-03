"""
frameless_window.py – FramelessMainWindow base class.

Replaces the native Windows titlebar with a custom CustomTitleBar, adds a
DWM drop shadow and Windows-11-style rounded corners, and implements full
resize + drag via WM_NCHITTEST interception through WindowResizer.

Architecture
------------
* FramelessMainWindow(QMainWindow) – the only public class.
* setCentralWidget() is overridden to inject the titlebar above content.
* WindowResizer handles all native-event hit testing.
* DWM effects (shadow, rounded corners) are applied once the HWND exists.

Subclass usage
--------------
    class MainWindow(FramelessMainWindow):
        def __init__(self):
            super().__init__()
            # ... setup ...
            self.setWindowTitle("My App v1.0")
            self._build_ui()          # must call self.setCentralWidget(...)

        def _build_ui(self):
            central = QWidget()
            self.setCentralWidget(central)  # intercepted by FramelessMainWindow
            ...

    # To update the titlebar theme when settings change:
    self.set_app_theme("light")  # or "dark"
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import re
import sys

from PyQt6.QtCore import Qt, QTimer, QEvent, QObject, QPoint
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QApplication
from PyQt6.QtGui import QPixmap, QCursor

from src.ui.custom_titlebar import CustomTitleBar


# ── module-level helpers ─────────────────────────────────────────────────────

def _read_version() -> str:
    """Read version string from src/version.txt (e.g. '1.5.0')."""
    try:
        vpath = os.path.join(os.path.dirname(__file__), "..", "version.txt")
        with open(vpath, encoding="utf-8") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def _load_app_icon() -> QPixmap | None:
    """Return the app icon pixmap from assets/, or None if not found."""
    def _res(rel: str) -> str:
        if hasattr(sys, "_MEIPASS"):
            return os.path.join(sys._MEIPASS, rel)
        root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return os.path.join(root, rel)

    for name in ("assets/app_icon.png", "assets/app_icon.ico"):
        path = _res(name)
        if os.path.exists(path):
            pm = QPixmap(path)
            if not pm.isNull():
                return pm
    return None


def _strip_version_suffix(title: str, version: str) -> str:
    """
    If *title* ends with ' v{version}', strip that suffix so the titlebar
    shows the app name and the version pill separately.
    """
    if version:
        suffix = f" v{version}"
        if title.endswith(suffix):
            return title[: -len(suffix)]
    # Also strip any trailing ' vX.Y.Z' pattern
    return re.sub(r"\s+v\d+[\d.]*$", "", title).strip() or title


# ── main class ───────────────────────────────────────────────────────────────

# Pixels of window edge used as the resize grab-band.
_RESIZE_BORDER = 8

# Map (top, bottom, left, right) edge flags → Qt cursor shape
_EDGE_CURSORS: dict[tuple, Qt.CursorShape] = {
    (False, False, True,  False): Qt.CursorShape.SizeHorCursor,
    (False, False, False, True):  Qt.CursorShape.SizeHorCursor,
    (True,  False, False, False): Qt.CursorShape.SizeVerCursor,
    (False, True,  False, False): Qt.CursorShape.SizeVerCursor,
    (True,  False, True,  False): Qt.CursorShape.SizeFDiagCursor,
    (False, True,  False, True):  Qt.CursorShape.SizeFDiagCursor,
    (True,  False, False, True):  Qt.CursorShape.SizeBDiagCursor,
    (False, True,  True,  False): Qt.CursorShape.SizeBDiagCursor,
}


class FramelessMainWindow(QMainWindow):
    """
    QMainWindow subclass that removes the native Windows titlebar and
    replaces it with a custom CustomTitleBar.  DWM shadow / rounded corners
    are applied via Win32 DWM APIs.  Window dragging uses QWindow.startSystemMove()
    (triggered from CustomTitleBar) and edge resize uses QWindow.startSystemResize()
    (triggered here from mousePressEvent).  No nativeEvent override is needed,
    which avoids ctypes/sip pointer-read crashes on Python 3.14+.

    Call set_app_theme('dark'|'light') whenever the application theme changes.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setMouseTracking(True)

        self._fw_titlebar: CustomTitleBar | None = None
        self._fw_outer:    QWidget | None     = None
        self._fw_outer_layout: QVBoxLayout | None = None
        self._fw_content:  QWidget | None     = None
        self._fw_dwm_done: bool               = False

        # Install app-level filter so we see MouseMove over child widgets too.
        QApplication.instance().installEventFilter(self)

    # ── public API ───────────────────────────────────────────────────────────

    def set_app_theme(self, theme: str) -> None:
        """Update the titlebar colour palette without rebuilding anything."""
        if self._fw_titlebar is not None:
            self._fw_titlebar.set_theme(theme)

    def custom_titlebar(self) -> CustomTitleBar | None:
        """Access the CustomTitleBar instance (may be None before _build_ui)."""
        return self._fw_titlebar

    # ── setCentralWidget interception ────────────────────────────────────────

    def setCentralWidget(self, widget: QWidget) -> None:  # noqa: N802
        """
        On first call: wraps *widget* inside a container with the titlebar on
        top and stores references.  On subsequent calls: replaces only the
        content widget leaving the titlebar untouched.
        """
        if self._fw_outer is not None:
            # Subsequent call – replace content only
            assert self._fw_outer_layout is not None
            if self._fw_content is not None:
                self._fw_outer_layout.removeWidget(self._fw_content)
                self._fw_content.setParent(None)
            self._fw_content = widget
            self._fw_outer_layout.addWidget(widget, stretch=1)
            return

        # ── first call: build outer container with titlebar ───────────────
        outer = QWidget()
        outer.setObjectName("fwOuter")
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        version       = _read_version()
        raw_title     = self.windowTitle() or "NEO SSH-Win Manager"
        display_title = _strip_version_suffix(raw_title, version)
        ver_display   = f"v{version}" if version else ""

        titlebar = CustomTitleBar(
            title     = display_title,
            version   = ver_display,
            theme     = "dark",           # updated via set_app_theme() shortly after
            app_icon  = _load_app_icon(),
            parent    = outer,
        )
        titlebar.minimize_requested.connect(self.showMinimized)
        titlebar.maximize_requested.connect(self._fw_toggle_maximize)
        titlebar.close_requested.connect(self.close)

        outer_layout.addWidget(titlebar)
        outer_layout.addWidget(widget, stretch=1)

        self._fw_titlebar     = titlebar
        self._fw_outer        = outer
        self._fw_outer_layout = outer_layout
        self._fw_content      = widget

        # Hand our wrapper to QMainWindow as the actual central widget
        QMainWindow.setCentralWidget(self, outer)

        # DWM shadow + rounded corners deferred until HWND is ready
        QTimer.singleShot(0, self._fw_apply_dwm)

    # ── window actions ───────────────────────────────────────────────────────

    def _fw_toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ── DWM integration ──────────────────────────────────────────────────────

    def _fw_apply_dwm(self) -> None:
        """
        Re-add WS_THICKFRAME so Windows DWM renders a drop shadow around the
        frameless window, then extend the frame thin into the client area and
        request Windows 11 rounded corners.  Safe to call multiple times.
        """
        if self._fw_dwm_done:
            return
        self._fw_dwm_done = True
        try:
            hwnd = int(self.winId())

            # Re-add resize frame style that FramelessWindowHint removed
            GWL_STYLE     = -16
            WS_THICKFRAME = 0x00040000
            cur_style     = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, cur_style | WS_THICKFRAME)

            # Tell Windows the frame metrics changed
            _SWP_NOSIZE     = 0x0001
            _SWP_NOMOVE     = 0x0002
            _SWP_NOZORDER   = 0x0004
            _SWP_FRAMECHANGED = 0x0020
            ctypes.windll.user32.SetWindowPos(
                hwnd, None, 0, 0, 0, 0,
                _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOZORDER | _SWP_FRAMECHANGED,
            )

            # Extend DWM shadow by 1 px at the bottom
            class MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth",    ctypes.c_int),
                    ("cxRightWidth",   ctypes.c_int),
                    ("cyTopHeight",    ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]
            m = MARGINS(0, 0, 0, 1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                hwnd, ctypes.byref(m)
            )

            # Windows 11 rounded corners (DWMWA_WINDOW_CORNER_PREFERENCE = 33)
            DWMWCP_ROUND = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(DWMWCP_ROUND), ctypes.sizeof(DWMWCP_ROUND)
            )
        except Exception:
            pass  # graceful degradation on Windows 10 / Wine

    # ── edge-resize helpers ──────────────────────────────────────────────────

    def _fw_edge_flags(self, x: int, y: int) -> tuple[bool, bool, bool, bool]:
        """Return (top, bottom, left, right) bool flags for resize-zone hit."""
        b = _RESIZE_BORDER
        w, h = self.width(), self.height()
        return (y < b, y >= h - b, x < b, x >= w - b)

    def _fw_qt_edges(self, flags: tuple[bool, bool, bool, bool]):
        """Convert (top, bottom, left, right) bools to a Qt.Edges value."""
        top, bottom, left, right = flags
        edges = Qt.Edge(0)
        if top:    edges |= Qt.Edge.TopEdge
        if bottom: edges |= Qt.Edge.BottomEdge
        if left:   edges |= Qt.Edge.LeftEdge
        if right:  edges |= Qt.Edge.RightEdge
        return edges

    # ── Qt event overrides ───────────────────────────────────────────────────

    def setWindowTitle(self, title: str) -> None:  # noqa: N802
        super().setWindowTitle(title)
        if self._fw_titlebar is not None:
            version = _read_version()
            self._fw_titlebar.set_title(_strip_version_suffix(title, version))

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if self._fw_titlebar is not None:
                self._fw_titlebar.set_maximized(self.isMaximized())

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._fw_dwm_done:
            self._fw_apply_dwm()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """Start a native system resize when user presses on a window edge."""
        if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            pos = event.position()
            flags = self._fw_edge_flags(int(pos.x()), int(pos.y()))
            if any(flags):
                handle = self.windowHandle()
                if handle is not None:
                    edges = self._fw_qt_edges(flags)
                    if handle.startSystemResize(edges):
                        event.accept()
                        return
        super().mousePressEvent(event)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        """Catch MouseMove on any child widget to update the resize cursor."""
        if event.type() == QEvent.Type.MouseMove and not self.isMaximized():
            # Map the global cursor position into window-local coordinates.
            gpos = QCursor.pos()
            local = self.mapFromGlobal(gpos)
            flags = self._fw_edge_flags(local.x(), local.y())
            shape = _EDGE_CURSORS.get(flags)
            if shape is not None:
                self.setCursor(QCursor(shape))
            else:
                self.unsetCursor()
        return False  # never consume the event

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        """Update cursor shape when hovering over a resize edge."""
        if not self.isMaximized():
            pos = event.position()
            flags = self._fw_edge_flags(int(pos.x()), int(pos.y()))
            shape = _EDGE_CURSORS.get(flags)
            if shape is not None:
                self.setCursor(QCursor(shape))
            else:
                self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()
        super().leaveEvent(event)
