"""
cli_history_panel.py – Right-panel view: CLI-Verlauf für einen Host.

Zeigt Befehle (--exec) und interaktive Sitzungen, die über
NeoSSHWinManager-cli.exe für diesen Host liefen (siehe
src/ssh_launcher.py::launch_ssh_in_current_terminal und den
cli_log-IPC-Handler in src/ui/main_window.py). Rein lokaler,
synchroner SQLite-Read über UserConnectionManager — anders als
SystemInfoPanel keine SSH-Verbindung, daher kein QThread nötig.
"""

import datetime

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QTextEdit, QFileDialog
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont

from src.config import Connection, CliHistoryEntry
from src.ui.icons import icon as svg_icon
from src.ui.dialogs.styled_message_box import StyledMessageBox
from src.i18n import tr


def _format_ts(iso_ts: str | None) -> str:
    """ISO8601-UTC-Zeitstempel für die Anzeige in lokale Zeit umwandeln."""
    if not iso_ts:
        return "—"
    try:
        dt = datetime.datetime.fromisoformat(iso_ts)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_ts


def _safe_filename(name: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)
    return cleaned or "host"


class CliHistoryPanel(QFrame):
    """CLI-Verlauf (Befehle + Sitzungen) für einen Host, neueste zuerst."""

    # Nur die neuesten N Einträge werden als Karten gerendert (Performance);
    # der Download-Export nutzt trotzdem den vollständigen Verlauf.
    _MAX_RENDERED = 150

    def __init__(self, conn: Connection, mgr, parent=None, settings=None):
        super().__init__(parent)
        self._conn = conn
        self._mgr = mgr
        self._settings = settings
        self._entries: list[CliHistoryEntry] = []

        self._theme = (getattr(settings, "theme", None) or "dark")
        self._val_color = "#ffffff" if self._theme == "dark" else "#1a2332"

        self.setObjectName("cliHistoryPanel")
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Hero-Kopfzeile — gleiches Muster wie SystemInfoPanel
        hero = QFrame()
        hero.setObjectName("sysinfoHeroCard")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(18, 16, 18, 16)
        hero_l.setSpacing(8)

        hero_top = QHBoxLayout()
        hero_top.setContentsMargins(0, 0, 0, 0)
        hero_top.setSpacing(8)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)
        title = QLabel(tr("clihistory.title"))
        title.setObjectName("sysinfoHeroTitle")
        title_col.addWidget(title)
        meta = QLabel(f"{self._conn.user}@{self._conn.host}:{self._conn.port}")
        meta.setObjectName("sysinfoHeroMeta")
        title_col.addWidget(meta)
        hero_top.addLayout(title_col)
        hero_top.addStretch()

        refresh_btn = QPushButton()
        refresh_btn.setObjectName("rpHeaderBtn")
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setIcon(svg_icon("refresh", "#aab4c4", 15))
        refresh_btn.setIconSize(QSize(15, 15))
        refresh_btn.setToolTip(tr("sysinfo.refresh"))
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._load)
        hero_top.addWidget(refresh_btn, 0, Qt.AlignmentFlag.AlignTop)
        hero_l.addLayout(hero_top)
        root.addWidget(hero)

        # Aktionsleiste: Verlauf löschen + als TXT herunterladen
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch()

        self._clear_btn = QPushButton(tr("clihistory.clear"))
        self._clear_btn.setObjectName("actionBtn")
        self._clear_btn.setProperty("btn_type", "danger")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self._on_clear)
        actions.addWidget(self._clear_btn)

        self._download_btn = QPushButton(tr("clihistory.download"))
        self._download_btn.setObjectName("actionBtn")
        self._download_btn.setProperty("btn_type", "primary")
        self._download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._download_btn.clicked.connect(self._on_download)
        actions.addWidget(self._download_btn)

        root.addLayout(actions)

        # Liste der Einträge
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        root.addWidget(self._list_container)
        root.addStretch()

    # ------------------------------------------------------------------
    # Daten laden / rendern
    # ------------------------------------------------------------------

    def _load(self):
        self._entries = self._mgr.get_cli_history(self._conn.id)
        self._render()
        has_entries = bool(self._entries)
        self._clear_btn.setEnabled(has_entries)
        self._download_btn.setEnabled(has_entries)

    def _clear_list_widgets(self):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render(self):
        self._clear_list_widgets()

        if not self._entries:
            empty = QLabel(tr("clihistory.empty"))
            empty.setObjectName("sysinfoStateText")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self._list_layout.addWidget(empty)
            return

        for entry in self._entries[: self._MAX_RENDERED]:
            self._list_layout.addWidget(self._build_entry_card(entry))

        remaining = len(self._entries) - self._MAX_RENDERED
        if remaining > 0:
            hint = QLabel(tr("clihistory.more_hint", n=remaining))
            hint.setObjectName("sysinfoStateText")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setWordWrap(True)
            self._list_layout.addWidget(hint)

    def _build_entry_card(self, entry: CliHistoryEntry) -> QFrame:
        """Kompakte Karte: Kopfzeile (+ Befehl bei exec) ist immer sichtbar und
        klickbar; die Ausgabe klappt erst beim Klick auf — dadurch bleibt die
        Übersicht bei vielen Einträgen kompakt, statt jede Ausgabe sofort
        vollständig auszurollen."""
        card = QFrame()
        card.setObjectName("sysinfoSectionCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 8, 14, 8)
        v.setSpacing(2)

        clickable: list[QWidget] = []

        head = QWidget()
        head_l = QHBoxLayout(head)
        head_l.setContentsMargins(0, 4, 0, 4)
        head_l.setSpacing(8)
        clickable.append(head)

        toggle_lbl = QLabel("▸")
        toggle_lbl.setFixedWidth(12)
        toggle_lbl.setStyleSheet("color: #6a7685; font-size: 11px; background: transparent;")
        head_l.addWidget(toggle_lbl)

        if entry.kind == "session":
            ts = f"{_format_ts(entry.started_at)} – {_format_ts(entry.ended_at)}"
            kind_label, kind_color = tr("clihistory.kind.session"), "#0077b6"
        else:
            ts = _format_ts(entry.started_at)
            kind_label, kind_color = tr("clihistory.kind.exec"), "#6a7a8a"

        kind_badge = QLabel(kind_label.upper())
        kind_badge.setStyleSheet(
            f"background-color: {kind_color}; color: #ffffff; font-size: 10px; "
            "font-weight: 700; border-radius: 8px; padding: 2px 8px;"
        )
        head_l.addWidget(kind_badge)
        clickable.append(kind_badge)

        ts_lbl = QLabel(ts)
        ts_lbl.setStyleSheet("color: #6a7685; font-size: 11px; background: transparent;")
        head_l.addWidget(ts_lbl)
        clickable.append(ts_lbl)

        if entry.command:
            # Einzeilig in der Kopfzeile – lange Befehle werden gekürzt, damit
            # die Übersicht kompakt bleibt (voller Befehl steht in der
            # aufgeklappten Ansicht bzw. im TXT-Export).
            preview_text = entry.command if len(entry.command) <= 90 else entry.command[:87] + "…"
            cmd_preview = QLabel(f"$ {preview_text}")
            cmd_preview.setFont(QFont("Consolas", 10))
            cmd_preview.setStyleSheet(f"color: {self._val_color}; background: transparent;")
            head_l.addWidget(cmd_preview, stretch=1)
            clickable.append(cmd_preview)
        else:
            head_l.addStretch()

        if entry.kind == "exec" and entry.exit_code is not None:
            ok = entry.exit_code == 0
            exit_badge = QLabel(f"Exit {entry.exit_code}")
            exit_badge.setStyleSheet(
                f"background-color: {'rgba(0, 212, 100, 0.15)' if ok else 'rgba(239, 68, 68, 0.15)'}; "
                f"color: {'#00d464' if ok else '#ef4444'}; font-size: 10px; font-weight: 700; "
                "border-radius: 8px; padding: 2px 8px;"
            )
            head_l.addWidget(exit_badge)
            clickable.append(exit_badge)

        v.addWidget(head)

        # Ausgabe-Bereich: standardmäßig eingeklappt, minimaler Abstand zur
        # Kopfzeile wenn geöffnet (das war der Hauptkritikpunkt am alten Layout).
        output_container = QWidget()
        out_v = QVBoxLayout(output_container)
        out_v.setContentsMargins(0, 2, 0, 2)
        out_v.setSpacing(4)

        output_view = QTextEdit()
        output_view.setReadOnly(True)
        output_view.setFont(QFont("Consolas", 9))
        output_view.setFixedHeight(150)
        if self._theme == "dark":
            _bg, _fg, _border = "#111822", "#deebf7", "#1f2b3a"
        else:
            _bg, _fg, _border = "#ffffff", "#182536", "#d5dde7"
        output_view.setStyleSheet(
            f"QTextEdit {{ background-color: {_bg}; color: {_fg}; "
            f"border: 1px solid {_border}; border-radius: 10px; padding: 6px 10px; }}"
        )
        output_view.setPlainText(entry.output or tr("clihistory.no_output"))
        out_v.addWidget(output_view)

        if entry.truncated:
            trunc_lbl = QLabel(tr("clihistory.truncated"))
            trunc_lbl.setStyleSheet("color: #f59e0b; font-size: 11px; background: transparent;")
            out_v.addWidget(trunc_lbl)

        output_container.setVisible(False)
        v.addWidget(output_container)

        def _toggle(_event=None):
            expanded = not output_container.isVisible()
            output_container.setVisible(expanded)
            toggle_lbl.setText("▾" if expanded else "▸")

        for w in clickable:
            w.setCursor(Qt.CursorShape.PointingHandCursor)
            w.mousePressEvent = _toggle

        return card

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _on_clear(self):
        if not self._entries:
            return
        if StyledMessageBox.question(
            self, tr("clihistory.clear.title"), tr("clihistory.clear.body"),
            yes_text=tr("clihistory.clear.confirm"), no_text=tr("dialog.cancel"),
        ):
            self._mgr.clear_cli_history(self._conn.id)
            self._load()

    def _on_download(self):
        # Frisch abfragen statt aus den gerenderten Karten zu lesen — die
        # zeigen wegen _MAX_RENDERED ggf. nicht den vollständigen Verlauf.
        entries = self._mgr.get_cli_history(self._conn.id)
        text = self._format_export(entries)
        default_name = f"cli_verlauf_{_safe_filename(self._conn.name)}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, tr("clihistory.download"), default_name,
            "Text-Dateien (*.txt);;Alle Dateien (*)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)

    def _format_export(self, entries: list[CliHistoryEntry]) -> str:
        now = _format_ts(datetime.datetime.now(datetime.timezone.utc).isoformat())
        lines = [
            f"CLI-Verlauf für {self._conn.name} ({self._conn.user}@{self._conn.host}:{self._conn.port})",
            f"Exportiert am {now}",
            "",
        ]
        sep = "=" * 60
        if not entries:
            lines.append(tr("clihistory.empty"))
        for entry in entries:
            lines.append(sep)
            if entry.kind == "session":
                header = f"[{_format_ts(entry.started_at)} – {_format_ts(entry.ended_at)}] " \
                         f"{tr('clihistory.kind.session').upper()}"
            else:
                exit_part = f" — Exit-Code {entry.exit_code}" if entry.exit_code is not None else ""
                header = f"[{_format_ts(entry.started_at)}] {tr('clihistory.kind.exec').upper()}{exit_part}"
            lines.append(header)
            if entry.command:
                lines.append(f"$ {entry.command}")
            lines.append(f"--- {tr('clihistory.output_label')} ---")
            lines.append(entry.output or tr("clihistory.no_output"))
            if entry.truncated:
                lines.append(f"({tr('clihistory.truncated')})")
            lines.append("")
        return "\n".join(lines)
