"""
about_dialog.py – About dialog for NEO SSH-Win Manager.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QScrollArea, QWidget, QFrame, QApplication
)
from PyQt6.QtCore import Qt, QSize, QUrl
from PyQt6.QtGui import QIcon, QPixmap, QDesktopServices

import os
from src.channel import display_name, display_version
from src.ui.dialog_utils import match_parent_height
from src.ui.frameless_dialog import FramelessDialog
from src.ui.theme import accent_tone
from src.ui.widgets.no_wheel import NoWheelScrollArea
from src.i18n import current_language, tr

try:
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "version.txt"), "r", encoding="utf-8") as f:
        APP_VERSION = f.read().strip()
except Exception:
    APP_VERSION = "?"

_URL_PROJECT_WEBSITE = "https://www.neosshwinmanager.org/"
_URL_PROJECT_GITHUB  = "https://github.com/gregorkrebs/neosshwinmanager"
_URL_AUTHOR_WEBSITE  = "https://www.gregorkrebs.dev"
_URL_AUTHOR_GITHUB   = "https://github.com/gregorkrebs"

# The documentation exists in German and English; every other UI language
# gets the English pages.
_URL_DOCS_DE = "https://www.neosshwinmanager.org/de/docs/erste-schritte"
_URL_DOCS_EN = "https://www.neosshwinmanager.org/en/docs/getting-started"


def docs_url() -> str:
    """Getting-started page in the UI language (a language switch needs a restart)."""
    return _URL_DOCS_DE if current_language() == "de" else _URL_DOCS_EN


def _open(url: str):
    QDesktopServices.openUrl(QUrl(url))


def _link_btn(label: str, url: str, icon_name: str = "", obj_name: str = "") -> QPushButton:
    """Gleichgestalteter Link-Button für alle Sektionen (icon_name: SVG in assets/icons)."""
    btn = QPushButton(label)
    if icon_name:
        from src.ui.icons import icon as svg_icon
        btn.setIcon(svg_icon(icon_name, accent_tone("#0077b6"), 15))
        btn.setIconSize(QSize(15, 15))
    btn.setObjectName(obj_name or "aboutLinkBtn")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedHeight(34)
    btn.clicked.connect(lambda: _open(url))
    return btn


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("sectionLabel")
    return lbl


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("dialogSectionCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(10)
    return frame, layout


def _divider() -> QFrame:
    sep = QFrame()
    sep.setObjectName("divider")
    sep.setFixedHeight(1)
    return sep


class AboutDialog(FramelessDialog):
    def __init__(self, parent=None):
        super().__init__(parent, show_maximize=True)
        self.setObjectName("dialogSurface")
        self.setWindowTitle(tr("about.title"))
        self.setMinimumWidth(440)
        self.setMaximumWidth(540)
        self.setModal(True)
        self._build_ui()
        # Always start at full available screen height
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            full_h = int(geo.height() * 0.95)
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)  # reset QWIDGETSIZE_MAX
            self.resize(self.width(), full_h)
            self._fdlg_titlebar.set_maximized(True)

    def _build_ui(self):
        outer = QVBoxLayout(self._fdlg_content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = NoWheelScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, stretch=1)

        inner = QWidget()
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 20, 20, 12)
        layout.setSpacing(12)

        # ── Hero ─────────────────────────────────────────────────────────
        hero = QFrame()
        hero.setObjectName("dialogHeroCard")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(22, 22, 22, 18)
        hero_l.setSpacing(8)

        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def _resource(rel):
            import sys
            if hasattr(sys, '_MEIPASS'):
                return os.path.join(sys._MEIPASS, rel)
            return os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                rel
            )

        icon_path = _resource(os.path.join("assets", "app_icon.png"))
        if os.path.exists(icon_path):
            pix = QPixmap(icon_path).scaled(
                64, 64,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon_lbl.setPixmap(pix)
        else:
            from src.ui.icons import pixmap as svg_pixmap
            icon_lbl.setPixmap(svg_pixmap("cloud", accent_tone("#00b4d8"), 64))
        hero_l.addWidget(icon_lbl)

        title_lbl = QLabel(display_name())
        title_lbl.setObjectName("dialogTitle")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_l.addWidget(title_lbl)

        ver_lbl = QLabel(display_version(APP_VERSION))
        ver_lbl.setObjectName("dialogPill")
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_l.addWidget(ver_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        desc = QLabel(tr("about.desc"))
        desc.setObjectName("dialogLead")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        hero_l.addWidget(desc)

        oss = QLabel(tr("about.open_source"))
        oss.setObjectName("accentLabel")
        oss.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_l.addWidget(oss)

        layout.addWidget(hero)

        # ── What It Does ──────────────────────────────────────────────────
        what_card, what_l = _card()

        what_title = _section_label(tr("about.what_it_does.title").upper())
        what_l.addWidget(what_title)
        what_l.addWidget(_divider())

        what_desc = QLabel(tr("about.what_it_does.body"))
        what_desc.setObjectName("dialogBody")
        what_desc.setWordWrap(True)
        what_l.addWidget(what_desc)

        layout.addWidget(what_card)

        # ── Project links ────────────────────────────────────────────────
        proj_card, proj_l = _card()

        proj_lbl = _section_label(tr("about.project.links").upper())
        proj_l.addWidget(proj_lbl)
        proj_l.addWidget(_divider())

        proj_btns = QHBoxLayout()
        proj_btns.setSpacing(8)

        wb = _link_btn(tr("about.website.btn"), _URL_PROJECT_WEBSITE, "globe", "aboutWebBtn")
        db = _link_btn(tr("about.docs.btn"),    docs_url(),           "file-text", "aboutDocsBtn")
        gb = _link_btn(tr("about.github.btn"),  _URL_PROJECT_GITHUB,  "keyboard", "aboutGithubBtn")

        for btn in (wb, db, gb):
            proj_btns.addWidget(btn, stretch=1)

        proj_l.addLayout(proj_btns)
        layout.addWidget(proj_card)

        # ── Author ───────────────────────────────────────────────────────
        auth_card, auth_l = _card()

        auth_hdr = QHBoxLayout()
        auth_hdr.setSpacing(8)
        auth_title = _section_label(tr("about.author.section").upper())
        auth_name = QLabel("Gregor Krebs")
        auth_name.setObjectName("dialogLead")
        auth_hdr.addWidget(auth_title)
        auth_hdr.addWidget(auth_name)
        auth_hdr.addStretch()
        auth_l.addLayout(auth_hdr)
        auth_l.addWidget(_divider())

        auth_btns = QHBoxLayout()
        auth_btns.setSpacing(8)
        awb = _link_btn(tr("about.author.website.btn"), _URL_AUTHOR_WEBSITE, "globe", "aboutWebBtn")
        agb = _link_btn(tr("about.author.github.btn"),  _URL_AUTHOR_GITHUB,  "keyboard", "aboutGithubBtn")
        for btn in (awb, agb):
            auth_btns.addWidget(btn, stretch=1)
        auth_l.addLayout(auth_btns)

        layout.addWidget(auth_card)

        # ── Requirements ─────────────────────────────────────────────────
        req_card, req_l = _card()
        req_lbl = QLabel(tr("about.requires"))
        req_lbl.setObjectName("accentLabel")
        req_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        req_l.addWidget(req_lbl)
        layout.addWidget(req_card)

        layout.addStretch()

        # ── Button bar ───────────────────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setObjectName("dialogBtnBar")
        btn_bar_layout = QVBoxLayout(btn_bar)
        btn_bar_layout.setContentsMargins(20, 8, 20, 16)
        btn_bar_layout.setSpacing(8)
        btn_bar_layout.addWidget(_divider())

        ok_btn = QPushButton(tr("dialog.close"))
        ok_btn.setObjectName("primaryBtn")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setFixedWidth(120)
        ok_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 10, 0, 0)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addStretch()
        btn_bar_layout.addLayout(btn_row)

        self.layout().addWidget(btn_bar)
