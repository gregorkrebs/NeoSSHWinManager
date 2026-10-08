"""
about_dialog.py – About dialog for NEO SSH-Win Manager.

Layout: an accent-coloured banner (app icon, name, version), a grid of
feature tiles, link cards for the project and the author, and a credits
line for the two programs the app builds on.
"""

import os
import platform
import sys

from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QColor, QDesktopServices, QLinearGradient, QPainter, QPainterPath,
    QPixmap,
)

from src.channel import display_name, display_version
from src.ui.dialog_utils import dialog_icon, tint_dialog_icon
from src.ui.frameless_dialog import FramelessDialog
from src.ui.icons import icon as svg_icon, pixmap as svg_pixmap
from src.ui.node_network import paint_node_network
from src.ui.theme import accent_tone, current_accent, is_light, text_on_accent
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
_URL_WINFSP          = "https://winfsp.dev/"
_URL_SSHFS_WIN       = "https://github.com/winfsp/sshfs-win"

# The documentation exists in German and English; every other UI language
# gets the English pages.
_URL_DOCS_DE = "https://www.neosshwinmanager.org/de/docs/erste-schritte"
_URL_DOCS_EN = "https://www.neosshwinmanager.org/en/docs/getting-started"

AUTHOR_NAME = "Gregor Krebs"

# QPushButton has no icon-to-text spacing setting; a leading gap does the job.
_ICON_GAP = "  "

# (translation key, icon) for the feature grid, two tiles per row.
_FEATURES = (
    ("mount",      "folder-open"),
    ("terminal",   "terminal"),
    ("files",      "folder"),
    ("sysinfo",    "cpu"),
    ("security",   "shield-check"),
    ("automation", "keyboard"),
)


def docs_url() -> str:
    """Getting-started page in the UI language (a language switch needs a restart)."""
    return _URL_DOCS_DE if current_language() == "de" else _URL_DOCS_EN


def version_info() -> str:
    """What "copy version info" puts on the clipboard, e.g. for bug reports."""
    return (
        f"{display_name()} {display_version(APP_VERSION)}\n"
        f"Windows {platform.version()} ({platform.machine()})\n"
        f"Language: {current_language()}"
    )


def _open(url: str):
    QDesktopServices.openUrl(QUrl(url))


def _host(url: str) -> str:
    """"https://www.example.org/a/b" -> "example.org/a/b" for the link hint."""
    host = url.split("://", 1)[-1].rstrip("/")
    return host[4:] if host.startswith("www.") else host


def _resource(rel: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(root, rel)


class _ElidedLabel(QLabel):
    """One line that ends in "…" instead of being cut off when too narrow."""

    def __init__(self, text: str, obj_name: str):
        super().__init__(text)
        self._full = text
        self.setObjectName(obj_name)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        elided = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, self.width())
        if elided != self.text():
            self.setText(elided)


def _label(text: str, obj_name: str, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName(obj_name)
    lbl.setWordWrap(wrap)
    return lbl


# ── Banner ───────────────────────────────────────────────────────────────────

class _Banner(QFrame):
    """Accent gradient with a faint network of linked nodes on the right –
    a nod to the remote hosts the app connects to."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aboutBanner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        row = QHBoxLayout(self)
        row.setContentsMargins(24, 24, 24, 22)
        row.setSpacing(18)

        self._icon_tile = QLabel()
        self._icon_tile.setFixedSize(80, 80)
        self._icon_tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_path = _resource(os.path.join("assets", "app_icon.png"))
        pix = QPixmap(icon_path) if os.path.exists(icon_path) else QPixmap()
        if not pix.isNull():
            dpr = self.devicePixelRatioF()
            pix = pix.scaled(int(56 * dpr), int(56 * dpr),
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            pix.setDevicePixelRatio(dpr)
            self._icon_tile.setPixmap(pix)
        self._has_app_icon = not pix.isNull()
        row.addWidget(self._icon_tile, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(6)
        self._name = QLabel(display_name())
        self._tagline = QLabel(tr("about.desc"))
        self._tagline.setWordWrap(True)
        text.addWidget(self._name)
        text.addWidget(self._tagline)

        pills = QHBoxLayout()
        pills.setSpacing(6)
        pills.setContentsMargins(0, 6, 0, 0)
        self._version = QLabel(display_version(APP_VERSION))
        self._license = QLabel(tr("about.open_source"))
        for pill in (self._version, self._license):
            pills.addWidget(pill)
        pills.addStretch()
        text.addLayout(pills)
        row.addLayout(text, 1)

        self.apply_colors()

    def apply_colors(self) -> None:
        on = QColor(text_on_accent())
        r, g, b = on.red(), on.green(), on.blue()
        self._name.setStyleSheet(
            f"color: rgb({r},{g},{b}); font-size: 21px; font-weight: 700; background: transparent;")
        self._tagline.setStyleSheet(
            f"color: rgba({r},{g},{b},0.82); font-size: 13px; background: transparent;")
        pill = (f"color: rgb({r},{g},{b}); background-color: rgba({r},{g},{b},0.14);"
                f" border: 1px solid rgba({r},{g},{b},0.28); border-radius: 9px;"
                f" padding: 3px 10px; font-size: 11px; font-weight: 600;")
        self._version.setStyleSheet(pill + ' font-family: "Consolas";')
        self._license.setStyleSheet(pill)
        self._icon_tile.setStyleSheet(
            f"background-color: rgba({r},{g},{b},0.16); border: 1px solid rgba({r},{g},{b},0.30);"
            f" border-radius: 22px;")
        if not self._has_app_icon:
            self._icon_tile.setPixmap(svg_pixmap("cloud", on.name(), 48, self.devicePixelRatioF()))
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 16, 16)
        p.setClipPath(clip)

        accent = QColor(current_accent())
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, accent.darker(150))
        grad.setColorAt(0.55, accent)
        grad.setColorAt(1.0, accent.lighter(118))
        p.fillPath(clip, grad)

        # The text sits on the leading side, so the network goes to the other.
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        paint_node_network(p, QRectF(0, 0, rect.width(), rect.height()),
                           QColor(text_on_accent()), mirrored=rtl)
        p.end()


# ── Building blocks ──────────────────────────────────────────────────────────

class _LinkRow(QPushButton):
    """A full-width link: icon, label, the target's address, and an arrow."""

    def __init__(self, label: str, url: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("aboutLinkRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(url)
        self.setFixedHeight(44)
        self._icon_name = icon_name
        self.clicked.connect(lambda: _open(url))

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(10)
        self._icon = QLabel()
        self._icon.setFixedSize(18, 18)
        row.addWidget(self._icon)

        text = QVBoxLayout()
        text.setSpacing(0)
        text.setContentsMargins(0, 0, 0, 0)
        text.addStretch()
        text.addWidget(_label(label, "aboutLinkLabel"))
        text.addWidget(_ElidedLabel(_host(url), "aboutLinkHint"))
        text.addStretch()
        row.addLayout(text, 1)

        self._arrow = QLabel()
        self._arrow.setFixedSize(14, 14)
        row.addWidget(self._arrow)

        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def apply_colors(self, accent: str, muted: str) -> None:
        dpr = self.devicePixelRatioF()
        self._icon.setPixmap(svg_pixmap(self._icon_name, accent, 18, dpr))
        self._arrow.setPixmap(svg_pixmap("arrow-up-right", muted, 14, dpr))


def _card(obj_name: str = "aboutCard") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName(obj_name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 14, 14, 10)
    layout.setSpacing(4)
    return frame, layout


# ── Dialog ───────────────────────────────────────────────────────────────────

class AboutDialog(FramelessDialog):
    def __init__(self, parent=None):
        super().__init__(parent, show_maximize=True)
        self.setObjectName("dialogSurface")
        self.setWindowTitle(tr("about.title"))
        self.setMinimumWidth(560)
        self.setMaximumWidth(680)
        self.resize(600, 10)
        self.setModal(True)
        self._feature_icons: list[tuple[QLabel, str]] = []
        self._link_rows: list[_LinkRow] = []
        self._fitted = False
        self._build_ui()
        self._apply_colors()

    # ── public ───────────────────────────────────────────────────────────────

    def set_dialog_theme(self, theme: str) -> None:
        super().set_dialog_theme(theme)
        if hasattr(self, "_banner"):
            self._apply_colors()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            self._fit_height()

    def _fit_height(self) -> None:
        """Grow to show everything without scrolling, up to 95 % of the screen."""
        # The scroll area spans the full width, so the body is as wide as the
        # dialog; measure from the parts instead of the not yet resized viewport.
        body_h = self._body.heightForWidth(self.width())
        if body_h <= 0:
            body_h = self._body.sizeHint().height()
        self._set_height(self._fdlg_titlebar.sizeHint().height()
                         + self._btn_bar.sizeHint().height() + body_h)
        # Wrapped text can come out a few lines taller once laid out at the
        # final width; whatever still scrolls then is added in a second pass.
        QTimer.singleShot(0, self._grow_by_overflow)

    def _grow_by_overflow(self) -> None:
        overflow = self._scroll.verticalScrollBar().maximum()
        if overflow > 0:
            self._set_height(self.height() + overflow)

    def _set_height(self, want: int) -> None:
        """Resize to *want* (capped to the screen), keeping the dialog centred."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            want = min(want, int(screen.availableGeometry().height() * 0.95))
        delta = want - self.height()
        if not delta:
            return
        self.setGeometry(self.x(), self.y() - delta // 2, self.width(), want)
        if screen is not None:
            top = screen.availableGeometry().top()
            if self.y() < top:
                self.move(self.x(), top)

    # ── build ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self._fdlg_content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = NoWheelScrollArea()
        scroll.setObjectName("aboutScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll, stretch=1)
        self._scroll = scroll

        body = QWidget()
        body.setObjectName("aboutBody")
        scroll.setWidget(body)
        self._body = body
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(0)

        self._banner = _Banner()
        layout.addWidget(self._banner)

        # ── Features ─────────────────────────────────────────────────────
        layout.addSpacing(20)
        layout.addWidget(_label(tr("about.what_it_does.title").upper(), "sectionLabel"))
        layout.addSpacing(10)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for i, (key, icon_name) in enumerate(_FEATURES):
            grid.addWidget(self._feature_tile(key, icon_name), i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        # ── Links ────────────────────────────────────────────────────────
        layout.addSpacing(20)
        layout.addWidget(_label(tr("about.links.title").upper(), "sectionLabel"))
        layout.addSpacing(10)
        links = QHBoxLayout()
        links.setSpacing(10)

        proj, proj_l = _card()
        proj_l.addWidget(_label(tr("about.project.links"), "aboutCardTitle"))
        proj_l.addWidget(_label(tr("about.project.hint"), "aboutCardHint", wrap=True))
        proj_l.addSpacing(6)
        for label, url, icon_name in (
            (tr("about.website.btn"), _URL_PROJECT_WEBSITE, "globe"),
            (tr("about.docs.btn"),    docs_url(),           "file-text"),
            (tr("about.github.btn"),  _URL_PROJECT_GITHUB,  "code"),
        ):
            proj_l.addWidget(self._link_row(label, url, icon_name))
        proj_l.addStretch()
        links.addWidget(proj, 1)

        auth, auth_l = _card()
        who = QHBoxLayout()
        who.setSpacing(10)
        self._avatar = QLabel("".join(part[0] for part in AUTHOR_NAME.split()))
        self._avatar.setObjectName("aboutAvatar")
        self._avatar.setFixedSize(36, 36)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        who.addWidget(self._avatar)
        who_text = QVBoxLayout()
        who_text.setSpacing(0)
        who_text.addWidget(_label(AUTHOR_NAME, "aboutCardTitle"))
        who_text.addWidget(_label(tr("about.author.section"), "aboutCardHint"))
        who.addLayout(who_text, 1)
        auth_l.addLayout(who)
        auth_l.addSpacing(6)
        for label, url, icon_name in (
            (tr("about.author.website.btn"), _URL_AUTHOR_WEBSITE, "globe"),
            (tr("about.author.github.btn"),  _URL_AUTHOR_GITHUB,  "code"),
        ):
            auth_l.addWidget(self._link_row(label, url, icon_name))
        auth_l.addStretch()
        links.addWidget(auth, 1)
        layout.addLayout(links)

        # ── Credits ──────────────────────────────────────────────────────
        layout.addSpacing(18)
        credits = QLabel()
        credits.setObjectName("aboutCredits")
        credits.setTextFormat(Qt.TextFormat.RichText)
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits.setWordWrap(True)
        credits.setOpenExternalLinks(True)
        self._credits = credits
        layout.addWidget(credits)
        layout.addStretch()

        # ── Button bar ───────────────────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setObjectName("dialogBtnBar")
        bar = QHBoxLayout(btn_bar)
        bar.setContentsMargins(20, 12, 20, 14)
        bar.setSpacing(8)

        self._copy_btn = QPushButton(_ICON_GAP + tr("about.copy_info"))
        self._copy_btn.setObjectName("secondaryBtn")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setIconSize(QSize(15, 15))
        self._copy_btn.setToolTip(tr("about.copy_info.hint"))
        self._copy_btn.clicked.connect(self._copy_version_info)
        bar.addWidget(self._copy_btn)
        bar.addStretch()

        close_btn = QPushButton(tr("dialog.close"))
        close_btn.setObjectName("primaryBtn")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setMinimumWidth(120)
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        bar.addWidget(close_btn)

        self.layout().addWidget(btn_bar)
        self._btn_bar = btn_bar

    def _feature_tile(self, key: str, icon_name: str) -> QFrame:
        tile = QFrame()
        tile.setObjectName("aboutFeatureTile")
        row = QHBoxLayout(tile)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(12)
        tile_icon = dialog_icon(icon_name, current_accent(), box=36, glyph=19)
        row.addWidget(tile_icon, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(_label(tr(f"about.feature.{key}.title"), "aboutFeatureTitle"))
        text.addWidget(_label(tr(f"about.feature.{key}.body"), "aboutFeatureBody", wrap=True))
        text.addStretch()
        row.addLayout(text, 1)
        self._feature_icons.append((tile_icon, icon_name))
        return tile

    def _link_row(self, label: str, url: str, icon_name: str) -> _LinkRow:
        row = _LinkRow(label, url, icon_name)
        self._link_rows.append(row)
        return row

    # ── colours ──────────────────────────────────────────────────────────────

    def _apply_colors(self) -> None:
        """Paint everything that follows the accent and the theme outside the QSS."""
        light = is_light(self._fdlg_theme)
        accent = current_accent() if light else accent_tone("#00b4d8")
        muted = "#8a9aab" if light else "#6a7a8a"

        self._banner.apply_colors()
        for tile_icon, icon_name in self._feature_icons:
            tint_dialog_icon(tile_icon, icon_name, accent, glyph=19)
        for link in self._link_rows:
            link.apply_colors(accent, muted)

        c = QColor(accent)
        self._avatar.setStyleSheet(
            f"QLabel#aboutAvatar {{ color: {accent}; font-size: 13px; font-weight: 700;"
            f" background-color: rgba({c.red()}, {c.green()}, {c.blue()}, 0.14);"
            f" border: 1px solid rgba({c.red()}, {c.green()}, {c.blue()}, 0.32);"
            f" border-radius: 18px; }}"
        )
        link = f'<a style="color: {accent}; text-decoration: none;" href="{{}}">{{}}</a>'
        self._credits.setText(tr("about.credits").format(
            winfsp=link.format(_URL_WINFSP, "WinFsp"),
            sshfs=link.format(_URL_SSHFS_WIN, "SSHFS-Win"),
        ))
        self._copy_btn.setIcon(svg_icon("copy", "#4a5d70" if light else "#aab4c4", 15))

    def _copy_version_info(self) -> None:
        QApplication.clipboard().setText(version_info())
        light = is_light(self._fdlg_theme)
        self._copy_btn.setText(_ICON_GAP + tr("about.copy_info.done"))
        self._copy_btn.setIcon(svg_icon("check-circle", "#16a34a" if light else "#22c55e", 15))
        QTimer.singleShot(1800, self._reset_copy_btn)

    def _reset_copy_btn(self) -> None:
        try:
            self._copy_btn.setText(_ICON_GAP + tr("about.copy_info"))
            self._copy_btn.setIcon(svg_icon("copy", "#4a5d70" if is_light(self._fdlg_theme) else "#aab4c4", 15))
        except RuntimeError:
            pass  # dialog already closed

