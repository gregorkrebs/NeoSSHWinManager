"""Pick the FileZilla sites to import (see src/filezilla_import.py)."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from src.filezilla_import import (
    FzSite, NotFileZillaError, default_path, is_duplicate, read_site_manager,
)
from src.i18n import tr
from src.ui.dialog_utils import match_parent_height


class FileZillaImportDialog(QDialog):
    """Lists the sites of a FileZilla Site Manager with a check box each.

    Opens the Site Manager of this computer if there is one; "Choose file…"
    reads another one (a copy from another PC or a FileZilla export). Sites that
    cannot be imported are shown greyed out, sites already in the list start
    unchecked. ``selected()`` returns the checked sites after ``exec()``.
    """

    def __init__(self, existing_connections, parent=None, path: str | None = None):
        super().__init__(parent)
        self.setObjectName("dialogSurface")
        self.setWindowTitle(tr("import.fz.title"))
        self.setMinimumWidth(620)
        self.setModal(True)
        self._existing = list(existing_connections)
        self._sites: list[FzSite] = []
        self._boxes: list[tuple[QCheckBox, FzSite]] = []
        self._path = ""
        self._build_ui()
        start = path if path is not None else default_path()
        if start and os.path.isfile(start):
            self._load(start)
        else:
            self._show_message(tr("import.fz.none_found"))
        match_parent_height(self, parent)

    # ── UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("dialogHeroCard")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(22, 18, 22, 18)
        hero_l.setSpacing(6)
        title = QLabel(tr("import.fz.title"))
        title.setObjectName("dialogTitle")
        hero_l.addWidget(title)
        self._lead = QLabel("")
        self._lead.setObjectName("dialogLead")
        self._lead.setWordWrap(True)
        self._lead.setTextFormat(Qt.TextFormat.PlainText)
        hero_l.addWidget(self._lead)
        outer.addWidget(hero)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self._choose_btn = QPushButton(tr("import.fz.choose_file"))
        self._choose_btn.setObjectName("secondaryBtn")
        self._choose_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._choose_btn.clicked.connect(self._choose_file)
        tools.addWidget(self._choose_btn)
        tools.addStretch()
        self._all_btn = QPushButton(tr("import.fz.select_all"))
        self._none_btn = QPushButton(tr("import.fz.select_none"))
        for b, state in ((self._all_btn, True), (self._none_btn, False)):
            b.setObjectName("tipNextBtn")           # slim link-style button of the theme
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=state: self._set_all(s))
            tools.addWidget(b)
        outer.addLayout(tools)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("aboutScroll")   # transparent in every theme
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setMinimumHeight(260)
        self._list = QWidget()
        self._list.setObjectName("aboutBody")
        self._list_l = QVBoxLayout(self._list)
        self._list_l.setContentsMargins(0, 0, 0, 0)
        self._list_l.setSpacing(6)
        self._scroll.setWidget(self._list)
        outer.addWidget(self._scroll, 1)

        btn_bar = QWidget()
        btn_bar.setObjectName("dialogBtnBar")
        bl = QHBoxLayout(btn_bar)
        bl.setContentsMargins(0, 6, 0, 0)
        bl.setSpacing(10)
        bl.addStretch()
        cancel = QPushButton(tr("dialog.cancel"))
        cancel.setObjectName("secondaryBtn")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        self._import_btn = QPushButton(tr("import.fz.import_btn", n=0))
        self._import_btn.setObjectName("primaryBtn")
        self._import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._import_btn.clicked.connect(self.accept)
        bl.addWidget(cancel)
        bl.addWidget(self._import_btn)
        outer.addWidget(btn_bar)
        self._update_count()

    def _clear_list(self):
        self._boxes = []
        while self._list_l.count():
            item = self._list_l.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _show_message(self, text: str):
        self._clear_list()
        self._sites = []
        self._lead.setText(text)
        self._update_count()

    def _load(self, path: str):
        try:
            sites = read_site_manager(path)
        except NotFileZillaError:
            self._show_message(tr("import.fz.error.not_filezilla"))
            return
        except OSError as e:
            self._show_message(tr("import.fz.error.read", err=str(e)))
            return
        self._path = path
        self._sites = sites
        self._clear_list()
        if not sites:
            self._lead.setText(tr("import.fz.empty", path=path))
            self._update_count()
            return
        self._lead.setText(tr("import.fz.lead", n=len(sites), path=path))
        for site in sites:
            self._list_l.addWidget(self._row(site))
        self._list_l.addStretch()
        self._update_count()

    def _row(self, site: FzSite) -> QWidget:
        row = QFrame()
        row.setObjectName("settingsRow")
        rl = QVBoxLayout(row)
        rl.setContentsMargins(10, 6, 10, 6)
        rl.setSpacing(2)
        box = QCheckBox(site.name)
        box.setCursor(Qt.CursorShape.PointingHandCursor)
        duplicate = site.supported and is_duplicate(site, self._existing)
        box.setChecked(site.supported and not duplicate)
        box.setEnabled(site.supported)
        box.toggled.connect(self._update_count)
        rl.addWidget(box)

        server = f"{site.user}@{site.host}:{site.port}" if site.user else f"{site.host}:{site.port}"
        parts = [server, site.protocol_label]
        if site.group:
            parts.append(tr("import.fz.group", group=site.group))
        notes = [tr(key, **args) for key, args in site.notes]
        if duplicate:
            notes.insert(0, tr("import.fz.note.duplicate"))
        detail = QLabel(" · ".join(parts) + ("\n" + " · ".join(notes) if notes else ""))
        detail.setObjectName("hintLabel")
        detail.setTextFormat(Qt.TextFormat.PlainText)
        detail.setWordWrap(True)
        detail.setContentsMargins(26, 0, 0, 0)
        rl.addWidget(detail)
        self._boxes.append((box, site))
        return row

    def _set_all(self, state: bool):
        for box, site in self._boxes:
            if site.supported:
                box.setChecked(state)

    def _update_count(self):
        n = len(self.selected())
        self._import_btn.setText(tr("import.fz.import_btn", n=n))
        self._import_btn.setEnabled(n > 0)
        has = any(site.supported for _, site in self._boxes)
        self._all_btn.setEnabled(has)
        self._none_btn.setEnabled(has)

    def _choose_file(self):
        start = os.path.dirname(self._path or default_path())
        path, _ = QFileDialog.getOpenFileName(
            self, tr("import.fz.choose_file"), start if os.path.isdir(start) else "",
            tr("import.fz.file_filter"))
        if path:
            self._load(path)

    # ── result ──────────────────────────────────────────────────────────
    def selected(self) -> list[FzSite]:
        return [site for box, site in self._boxes if box.isChecked() and site.supported]
