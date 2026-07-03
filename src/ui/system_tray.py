"""
system_tray.py – System tray icon and context menu for NEO SSH-Win Manager.
"""

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction
from PyQt6.QtCore import Qt, QSize
import os
from src.i18n import tr
from src.channel import display_name


def _create_tray_icon() -> QIcon:
    """Generate a simple cloud pixmap icon for the tray."""
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#00b4d8"))
    # Draw a simple cloud shape via ellipses
    painter.drawEllipse(2, 14, 12, 12)
    painter.drawEllipse(8, 10, 14, 14)
    painter.drawEllipse(18, 14, 12, 12)
    painter.drawRect(4, 20, 24, 7)
    painter.end()
    return QIcon(pix)


class SystemTray(QSystemTrayIcon):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        
        # Application Icon
        def get_resource_path(relative_path):
            import sys
            if hasattr(sys, '_MEIPASS'):
                return os.path.join(sys._MEIPASS, relative_path)
            # Root is 2 levels up from src/ui/system_tray.py
            return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), relative_path)

        icon_path = get_resource_path(os.path.join("assets", "app_icon.png"))
        if os.path.exists(icon_path):
            self.setIcon(QIcon(icon_path))
        else:
            self.setIcon(QIcon(_create_tray_icon()))
            
        self.setToolTip(display_name())
        self._build_menu()
        self.activated.connect(self._on_activated)

    def _build_menu(self):
        menu = QMenu()
        menu.setObjectName("trayMenu")

        show_act = QAction("▣  " + tr("tray.show_hide"), self)
        show_act.triggered.connect(self._toggle_window)
        menu.addAction(show_act)

        menu.addSeparator()

        quit_act = QAction("✕  " + tr("tray.quit"), self)
        quit_act.triggered.connect(self._main_window.quit_app)
        menu.addAction(quit_act)

        self.setContextMenu(menu)

    def _toggle_window(self):
        if self._main_window.isVisible():
            self._main_window.hide()
        else:
            self._main_window.show()
            self._main_window.raise_()
            self._main_window.activateWindow()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_window()

    def update_connections_menu(self, connections, mounted_set: set):
        """Rebuild the tray menu to include quick-toggle for each connection."""
        menu = self.contextMenu()
        menu.clear()

        show_act = QAction("▣  " + tr("tray.show_hide"), self)
        show_act.triggered.connect(self._toggle_window)
        menu.addAction(show_act)

        if connections:
            menu.addSeparator()
            for conn in connections:
                state = "✓ " if conn.drive_letter in mounted_set else "○ "
                act = QAction(f"{state}{conn.name} ({conn.drive_letter})", self)
                act.setData(conn.id)
                # Slot verbinden (Toggle-Logik)
                is_m = conn.drive_letter in mounted_set
                act.triggered.connect(lambda _, cid=conn.id, m=is_m: self._on_tray_toggle(cid, m))
                menu.addAction(act)

        menu.addSeparator()
        quit_act = QAction("✕  " + tr("tray.quit"), self)
        quit_act.triggered.connect(self._main_window.quit_app)
        menu.addAction(quit_act)

    def _on_tray_toggle(self, conn_id: str, is_mounted: bool):
        if is_mounted:
            self._main_window._on_unmount(conn_id)
        else:
            self._main_window._on_mount(conn_id)
