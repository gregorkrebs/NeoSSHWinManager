"""
connection_card.py – Widget representing a single SSH connection in the list.
"""

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QIcon
from src.config import Connection
from src.ui.icons import icon as svg_icon, pixmap as svg_pixmap
from src.i18n import tr


class ConnectionCard(QFrame):
    """A row widget displaying one SSH connection with mount/unmount toggle."""

    mount_requested = pyqtSignal(str)
    unmount_requested = pyqtSignal(str)
    info_requested = pyqtSignal(str)   # [i] button → show info/edit panel
    edit_requested = pyqtSignal(str)
    ssh_requested = pyqtSignal(str)
    open_path_requested = pyqtSignal(str)

    def __init__(self, conn: Connection, mounted: bool = False, theme: str = "dark", parent=None):
        super().__init__(parent)
        self._conn = conn
        self._mounted = mounted
        self._theme = theme
        self._loading = False
        self.setObjectName("connectionCard")
        # Increase height when groups are present
        self.setFixedHeight(68)
        self._build_ui()
        self.update_mount_state(mounted)

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._cloud_lbl = QLabel()
        self._cloud_lbl.setObjectName("cloudIcon")
        self._cloud_lbl.setFixedSize(QSize(32, 32))
        self._cloud_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cloud_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cloud_lbl.mousePressEvent = self._on_cloud_clicked
        layout.addWidget(self._cloud_lbl)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        info_col.setContentsMargins(0, 0, 0, 0)

        # Row 1: Name + Tags (minimal spacing)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_row.setContentsMargins(0, 0, 0, 0)

        self._name_lbl = QLabel(self._conn.name)
        self._name_lbl.setObjectName("connName")
        # Let the name only take what it needs, but allow it to shrink if needed
        self._name_lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        name_row.addWidget(self._name_lbl)

        # Groups/Tags pills (directly behind name)
        self._groups_widget = self._build_groups_pills()
        if self._groups_widget:
            name_row.addWidget(self._groups_widget)
        
        name_row.addStretch() # Push both to the left
        info_col.addLayout(name_row)

        self._detail_lbl = QLabel()
        self._detail_lbl.setObjectName("connDetail")
        self._detail_lbl.setWordWrap(False)
        self._detail_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._update_detail_text()

        info_col.addWidget(self._detail_lbl)

        info_wrapper = QWidget()
        info_wrapper.setObjectName("cardInfoWrapper")
        info_wrapper.setLayout(info_col)
        info_wrapper.setMinimumWidth(60)
        info_wrapper.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(info_wrapper, stretch=1)

        self._drive_badge = QLabel(self._conn.drive_letter)
        self._drive_badge.setObjectName("driveBadge")
        self._drive_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drive_badge.setFixedSize(QSize(42, 30))
        self._drive_badge.mousePressEvent = self._on_drive_badge_clicked
        layout.addWidget(self._drive_badge)

        self._edit_btn = QPushButton()
        self._edit_btn.setObjectName("cardEditBtn")
        self._edit_btn.setFixedSize(QSize(32, 32))
        self._edit_btn.setIconSize(QSize(15, 15))
        self._edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_btn.clicked.connect(lambda: self.edit_requested.emit(self._conn.id))
        layout.addWidget(self._edit_btn)

        self._ssh_btn = QPushButton()
        self._ssh_btn.setObjectName("sshBtn")
        self._ssh_btn.setFixedSize(QSize(32, 32))
        self._ssh_btn.setIconSize(QSize(16, 16))
        self._ssh_btn.setToolTip(tr("card.tooltip.ssh"))
        self._ssh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ssh_btn.clicked.connect(lambda: self.ssh_requested.emit(self._conn.id))
        layout.addWidget(self._ssh_btn)

        self._mount_btn = QPushButton()
        self._mount_btn.setObjectName("mountBtn")
        self._mount_btn.setFixedSize(QSize(32, 32))
        self._mount_btn.setIconSize(QSize(16, 16))
        self._mount_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mount_btn.clicked.connect(self._on_toggle)
        layout.addWidget(self._mount_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def update_mount_state(self, mounted: bool):
        self._mounted = mounted

        self.setProperty("mounted", mounted)
        self._cloud_lbl.setProperty("mounted", mounted)
        self._drive_badge.setProperty("mounted", mounted)
        self._mount_btn.setProperty("mounted", mounted)

        cloud_color = "#00b4d8" if mounted else "#6a7a8a"
        self._cloud_lbl.setPixmap(svg_pixmap("cloud", cloud_color, 32))

        if mounted:
            self._cloud_lbl.setToolTip(tr("card.tooltip.mount_on"))
            self._drive_badge.setToolTip(tr("card.tooltip.sftp_browser"))
            self._drive_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self._cloud_lbl.setToolTip(tr("card.tooltip.mount_off"))
            self._drive_badge.setToolTip("")
            self._drive_badge.setCursor(Qt.CursorShape.ArrowCursor)

        self._ssh_btn.setIcon(svg_icon("terminal", "#aab4c4", 16))
        # Light theme: active icon must be darker (#4a5a6a) to be visible on a light
        # background; disabled icon lighter (#b8c4cf). Dark theme keeps original values.
        if self._theme == "light":
            _edit_active   = "#4a5a6a"
            _edit_disabled = "#b8c4cf"
        else:
            _edit_active   = "#aab4c4"
            _edit_disabled = "#6a7a8a"
        self._edit_btn.setIcon(svg_icon("edit", _edit_active if not mounted else _edit_disabled, 15))
        self._edit_btn.setToolTip(
            tr("card.tooltip.edit_locked") if mounted else tr("card.tooltip.edit")
        )

        self._edit_btn.setCursor(Qt.CursorShape.ArrowCursor if mounted else Qt.CursorShape.PointingHandCursor)
        self._edit_btn.setStyleSheet("QPushButton#cardEditBtn:hover { border:  1px solid #243243; }" if mounted else "QPushButton#cardEditBtn:hover { border: 1px solid #72add6; }")

        if self._loading:
            return

        if mounted:
            self._mount_btn.setIcon(svg_icon("minus", "#00d464", 16))
            self._mount_btn.setText("")
            self._mount_btn.setToolTip(tr("card.tooltip.mount_on"))
        else:
            self._mount_btn.setIcon(svg_icon("arrow-right", "#aab4c4", 16))
            self._mount_btn.setText("")
            self._mount_btn.setToolTip(tr("card.tooltip.mount_off"))

        for w in (self, self._cloud_lbl, self._drive_badge, self._mount_btn):
            w.style().unpolish(w)
            w.style().polish(w)

        self.update()

    def _update_detail_text(self):
        """Set detail label with elided remote_path if it would be very long."""
        drive_text = f"{self._conn.drive_letter}  •  "
        detail = f"{drive_text}{self._conn.user}@{self._conn.host}:{self._conn.port}"
        self._detail_lbl.setText(detail)
        # Full text as tooltip so user can see the whole path
        self._detail_lbl.setToolTip(
            f"{self._conn.user}@{self._conn.host}:{self._conn.remote_path}"
        )

    def _build_groups_pills(self) -> QWidget | None:
        """Build small pill badges for groups/tags. Returns None if no groups."""
        if not self._conn.groups:
            return None
        
        groups = [g.strip() for g in self._conn.groups.split(",") if g.strip()]
        if not groups:
            return None
        
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        # Show max 3 pills, then +N indicator
        max_pills = 3
        for i, group in enumerate(groups[:max_pills]):
            pill = QLabel(group)
            pill.setObjectName("groupPill")
            pill.setStyleSheet(self._get_pill_stylesheet())
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pill.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            layout.addWidget(pill)
        
        if len(groups) > max_pills:
            more = QLabel(f"+{len(groups) - max_pills}")
            more.setObjectName("groupPillMore")
            more.setStyleSheet(self._get_pill_more_stylesheet())
            more.setAlignment(Qt.AlignmentFlag.AlignCenter)
            more.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            layout.addWidget(more)
        
        return widget

    def _get_pill_stylesheet(self) -> str:
        """Get stylesheet for group pills based on theme."""
        if self._theme == "dark":
            return """
                QLabel {
                    background-color: rgba(0, 180, 216, 0.12);
                    color: #7ddfff;
                    border: 1px solid rgba(0, 180, 216, 0.35);
                    border-radius: 8px;
                    padding: 1px 8px;
                    font-size: 9px;
                    font-weight: 600;
                }
            """
        else:
            return """
                QLabel {
                    background-color: rgba(0, 119, 182, 0.10);
                    color: #0077b6;
                    border: 1px solid rgba(0, 119, 182, 0.30);
                    border-radius: 4px;
                    padding: 1px 8px;
                    font-size: 9px;
                    font-weight: 600;
                }
            """
    
    def _get_pill_more_stylesheet(self) -> str:
        """Get stylesheet for +N indicator."""
        if self._theme == "dark":
            return """
                QLabel {
                    background-color: rgba(106, 122, 138, 0.20);
                    color: #8fa4b8;
                    border: 1px solid rgba(106, 122, 138, 0.35);
                    border-radius: 4px;
                    padding: 1px 6px;
                    font-size: 9px;
                    font-weight: 600;
                }
            """
        else:
            return """
                QLabel {
                    background-color: rgba(106, 122, 138, 0.15);
                    color: #617386;
                    border: 1px solid rgba(106, 122, 138, 0.30);
                    border-radius: 4px;
                    padding: 1px 6px;
                    font-size: 9px;
                    font-weight: 600;
                }
            """

    def update_connection(self, conn: Connection):
        self._conn = conn
        self._name_lbl.setText(conn.name)
        self._update_detail_text()
        self._drive_badge.setText(conn.drive_letter)

    def set_info_active(self, active: bool):
        """Highlight card when the info panel is open for this card."""
        self.setProperty("info_active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_terminal_active(self, active: bool):
        """Highlight the SSH button when an integrated terminal session is alive."""
        if active:
            color = "#00b4d8" if self._theme == "dark" else "#0077b6"
        else:
            color = "#aab4c4"
        self._ssh_btn.setIcon(svg_icon("terminal", color, 16))
        self._ssh_btn.setProperty("terminal_active", "true" if active else "false")
        self._ssh_btn.style().unpolish(self._ssh_btn)
        self._ssh_btn.style().polish(self._ssh_btn)

    def _on_cloud_clicked(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._mounted:
            self.show_loading(tr("card.loading.connect"))
            self.mount_requested.emit(self._conn.id)
        else:
            self.open_path_requested.emit(self._conn.id)

    def _on_drive_badge_clicked(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._mounted:
            self.open_path_requested.emit(self._conn.id)

    def _on_toggle(self):
        if self._mounted:
            self.show_loading(tr("card.loading.disconnect"))
            self.unmount_requested.emit(self._conn.id)
        else:
            self.show_loading(tr("card.loading.connect"))
            self.mount_requested.emit(self._conn.id)

    def show_loading(self, text=""):
        self._loading = True
        self.setProperty("loading", "true")
        self._edit_btn.setVisible(False)
        self._ssh_btn.setVisible(False)
        self._mount_btn.setEnabled(False)
        self._mount_btn.setProperty("loading", "true")
        self._mount_btn.setText(text)
        self._mount_btn.setIcon(QIcon())
        self._mount_btn.setFixedSize(QSize(118, 32))
        for widget in (self, self._mount_btn):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def hide_loading(self):
        self._loading = False
        self.setProperty("loading", "false")
        self._edit_btn.setVisible(True)
        self._ssh_btn.setVisible(True)
        self._mount_btn.setEnabled(True)
        self._mount_btn.setProperty("loading", "false")
        self._mount_btn.setText("")
        self._mount_btn.setFixedSize(QSize(32, 32))
        self.update_mount_state(self._mounted)
        for widget in (self, self._mount_btn):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    @property
    def connection(self) -> Connection:
        return self._conn

    @property
    def is_mounted(self) -> bool:
        return self._mounted
