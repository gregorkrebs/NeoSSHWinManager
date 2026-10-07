"""
color_picker.py – Accent colour picker in the app's own style.

A saturation/brightness field, a hue bar, a free HEX field, preset swatches
and a "Standard" button that restores the default teal. Below them, the text
colour on the accent: automatic (see theme.accent_text_color), white, black
or a custom one, with a sample. While the user picks, ``colorChanged``
(throttled) and ``textColorChanged`` fire so the caller can preview live;
``pick()`` returns (colour, text colour), or None when the dialog was
cancelled. A text colour of "" means automatic.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QRegularExpression, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRegularExpressionValidator,
)
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
    QVBoxLayout, QWidget,
)

from src.i18n import tr
from src.ui.frameless_dialog import FramelessDialog
from src.ui.theme import DEFAULT_ACCENT, accent_text_color, normalize_hex

PRESETS = (
    DEFAULT_ACCENT,  # Türkis (default)
    "#3b82f6", "#6366f1", "#8b5cf6", "#ec4899",
    "#e11d48", "#f97316", "#eab308", "#10b981", "#64748b",
)

# Live preview restyles the whole application; at most this often (ms).
_PREVIEW_INTERVAL = 120

# The fixed text colour choices; "" is automatic.
_WHITE, _BLACK = "#ffffff", "#111111"


def _hex(color: QColor) -> str:
    return color.name(QColor.NameFormat.HexRgb).lower()


class _SVField(QWidget):
    """Saturation (x) / brightness (y) field for the current hue."""

    changed = pyqtSignal()
    released = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 170)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hue = 0.0
        self.sat = 1.0
        self.val = 1.0

    def set_hsv(self, h: float, s: float, v: float) -> None:
        self.hue, self.sat, self.val = h, s, v
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        p.setClipPath(path)
        p.fillRect(rect, QColor.fromHsvF(self.hue, 1.0, 1.0))
        white = QLinearGradient(rect.topLeft(), rect.topRight())
        white.setColorAt(0, QColor(255, 255, 255, 255))
        white.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(rect, white)
        black = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        black.setColorAt(0, QColor(0, 0, 0, 0))
        black.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(rect, black)
        p.setClipping(False)
        x = rect.left() + self.sat * rect.width()
        y = rect.top() + (1.0 - self.val) * rect.height()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 160), 3))
        p.drawEllipse(QRectF(x - 7, y - 7, 14, 14))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawEllipse(QRectF(x - 7, y - 7, 14, 14))

    def _pick(self, pos) -> None:
        w, h = max(self.width(), 1), max(self.height(), 1)
        self.sat = min(max(pos.x() / w, 0.0), 1.0)
        self.val = 1.0 - min(max(pos.y() / h, 0.0), 1.0)
        self.update()
        self.changed.emit()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._pick(e.position())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._pick(e.position())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.released.emit()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        step = 0.02
        moves = {
            Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0),
            Qt.Key.Key_Up: (0, step), Qt.Key.Key_Down: (0, -step),
        }
        if e.key() not in moves:
            super().keyPressEvent(e)
            return
        ds, dv = moves[e.key()]
        self.sat = min(max(self.sat + ds, 0.0), 1.0)
        self.val = min(max(self.val + dv, 0.0), 1.0)
        self.update()
        self.changed.emit()
        self.released.emit()


class _HueBar(QWidget):
    """Vertical hue bar, red at the top."""

    changed = pyqtSignal()
    released = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(20)
        self.setMinimumHeight(170)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hue = 0.0

    def set_hue(self, h: float) -> None:
        self.hue = h
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(3, 0.5, -3, -0.5)
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        for i in range(7):
            grad.setColorAt(i / 6, QColor.fromHsvF((i / 6) % 1.0, 1.0, 1.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(rect, 5, 5)
        y = rect.top() + self.hue * rect.height()
        marker = QRectF(0.5, y - 3, self.width() - 1, 6)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 160), 3))
        p.drawRoundedRect(marker, 3, 3)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawRoundedRect(marker, 3, 3)

    def _pick(self, pos) -> None:
        h = max(self.height(), 1)
        self.hue = min(max(pos.y() / h, 0.0), 0.999)
        self.update()
        self.changed.emit()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._pick(e.position())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._pick(e.position())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.released.emit()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        delta = {Qt.Key.Key_Up: -0.01, Qt.Key.Key_Down: 0.01}.get(e.key())
        if delta is None:
            super().keyPressEvent(e)
            return
        self.hue = (self.hue + delta) % 1.0
        self.update()
        self.changed.emit()
        self.released.emit()


def _swatch_style(color: str, radius: int = 6) -> str:
    return (
        f"QPushButton {{ background-color: {color}; border: 1px solid rgba(128,128,128,0.45);"
        f" border-radius: {radius}px; }}"
        f"QPushButton:hover {{ border: 2px solid rgba(255,255,255,0.85); }}"
    )


class AccentColorDialog(FramelessDialog):
    """Pick an accent colour; see the module docstring."""

    colorChanged = pyqtSignal(str)
    textColorChanged = pyqtSignal(str)

    @classmethod
    def pick(cls, parent, initial: str,
             preview: Optional[Callable[[str, str], None]] = None,
             initial_text: str = "") -> Optional[tuple[str, str]]:
        """Show the dialog; *preview* is called with (colour, text colour)
        at every change while picking. Returns (colour, text colour), or
        None if cancelled."""
        dlg = cls(initial, parent, initial_text)
        if preview is not None:
            dlg.colorChanged.connect(lambda color: preview(color, dlg.text_color()))
            dlg.textColorChanged.connect(lambda text: preview(dlg.color(), text))
        if dlg.exec() == FramelessDialog.DialogCode.Accepted:
            return dlg.color(), dlg.text_color()
        return None

    def __init__(self, initial: str, parent=None, initial_text: str = "") -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(tr("colorpicker.title"))
        self.setObjectName("dialogSurface")
        self._initial = normalize_hex(initial) or DEFAULT_ACCENT
        self._color = self._initial
        self._emitted = self._initial
        self._initial_text = normalize_hex(initial_text) or ""
        self._text = self._initial_text
        self._throttle = QTimer(self)
        self._throttle.setSingleShot(True)
        self._throttle.setInterval(_PREVIEW_INTERVAL)
        self._throttle.timeout.connect(self._emit_now)
        self._build()
        self._show_text(self._initial_text)
        self._show_color(self._initial)

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = QVBoxLayout(self._fdlg_content)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        title = QLabel(tr("colorpicker.title"))
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        pick_row = QHBoxLayout()
        pick_row.setSpacing(10)
        self._sv = _SVField()
        self._sv.changed.connect(self._on_sv)
        self._sv.released.connect(self._emit_now)
        self._hue = _HueBar()
        self._hue.changed.connect(self._on_hue)
        self._hue.released.connect(self._emit_now)
        pick_row.addWidget(self._sv, stretch=1)
        pick_row.addWidget(self._hue)
        root.addLayout(pick_row)

        presets_lbl = QLabel(tr("colorpicker.presets"))
        presets_lbl.setObjectName("fieldLabel")
        root.addWidget(presets_lbl)
        presets = QHBoxLayout()
        presets.setSpacing(6)
        for color in PRESETS:
            btn = QPushButton()
            btn.setFixedSize(24, 24)
            btn.setAutoDefault(False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(color + ("  (" + tr("settings.accent.reset") + ")" if color == DEFAULT_ACCENT else ""))
            btn.setStyleSheet(_swatch_style(color))
            btn.clicked.connect(lambda _=False, c=color: self._set_from_outside(c))
            presets.addWidget(btn)
        presets.addStretch(1)
        root.addLayout(presets)

        hex_row = QHBoxLayout()
        hex_row.setSpacing(10)
        hex_lbl = QLabel(tr("colorpicker.hex"))
        hex_lbl.setObjectName("fieldLabel")
        hex_row.addWidget(hex_lbl)
        self._hex = QLineEdit()
        self._hex.setFixedWidth(110)
        self._hex.setMaxLength(7)
        self._hex.setPlaceholderText("#0077b6")
        self._hex.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"#?[0-9A-Fa-f]{0,6}"), self._hex))
        self._hex.textEdited.connect(self._on_hex_edited)
        self._hex.editingFinished.connect(self._on_hex_finished)
        hex_row.addWidget(self._hex)
        hex_row.addStretch(1)

        # Before / after
        compare = QFrame()
        compare.setFixedSize(96, 30)
        cmp_l = QHBoxLayout(compare)
        cmp_l.setContentsMargins(0, 0, 0, 0)
        cmp_l.setSpacing(0)
        self._old_sw = QLabel()
        self._old_sw.setToolTip(self._initial)
        self._new_sw = QLabel()
        cmp_l.addWidget(self._old_sw)
        cmp_l.addWidget(self._new_sw)
        self._old_sw.setStyleSheet(
            f"background-color: {self._initial}; border-top-left-radius: 8px;"
            " border-bottom-left-radius: 8px;")
        hex_row.addWidget(compare)
        root.addLayout(hex_row)

        # Text colour on the accent
        text_lbl = QLabel(tr("colorpicker.text.label"))
        text_lbl.setObjectName("fieldLabel")
        root.addWidget(text_lbl)
        choices = QHBoxLayout()
        choices.setSpacing(14)
        self._text_group = QButtonGroup(self)
        self._text_auto = QRadioButton(tr("colorpicker.text.auto"))
        self._text_white = QRadioButton(tr("colorpicker.text.white"))
        self._text_black = QRadioButton(tr("colorpicker.text.black"))
        self._text_custom = QRadioButton(tr("colorpicker.text.custom"))
        for i, rb in enumerate((self._text_auto, self._text_white, self._text_black, self._text_custom)):
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            self._text_group.addButton(rb, i)
            choices.addWidget(rb)
        choices.addStretch(1)
        root.addLayout(choices)
        self._text_group.idClicked.connect(self._on_text_choice)

        sample_row = QHBoxLayout()
        sample_row.setSpacing(10)
        self._text_hex = QLineEdit()
        self._text_hex.setFixedWidth(110)
        self._text_hex.setMaxLength(7)
        self._text_hex.setPlaceholderText(_WHITE)
        self._text_hex.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"#?[0-9A-Fa-f]{0,6}"), self._text_hex))
        self._text_hex.textEdited.connect(self._on_text_hex_edited)
        sample_row.addWidget(self._text_hex)
        self._sample = QLabel(tr("colorpicker.text.sample"))
        self._sample.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sample.setFixedHeight(32)
        self._sample.setMinimumWidth(150)
        sample_row.addWidget(self._sample)
        sample_row.addStretch(1)
        root.addLayout(sample_row)

        div = QFrame()
        div.setObjectName("divider")
        div.setFixedHeight(1)
        root.addWidget(div)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self._reset_btn = QPushButton(tr("settings.accent.reset"))
        self._reset_btn.setObjectName("secondaryBtn")
        self._reset_btn.setToolTip(DEFAULT_ACCENT)
        self._reset_btn.clicked.connect(self._reset)
        btns.addWidget(self._reset_btn)
        btns.addStretch(1)
        cancel = QPushButton(tr("dialog.cancel"))
        cancel.setObjectName("secondaryBtn")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        ok = QPushButton(tr("colorpicker.apply"))
        ok.setObjectName("primaryBtn")
        ok.clicked.connect(self.accept)
        btns.addWidget(ok)
        for b in (self._reset_btn, cancel, ok):
            b.setAutoDefault(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addLayout(btns)
        self.setMinimumWidth(400)

    # ── state ───────────────────────────────────────────────────────────────

    def color(self) -> str:
        return self._color

    def text_color(self) -> str:
        """The chosen text colour on the accent; "" = automatic."""
        return self._text

    def _show_color(self, color: str, *, hex_field: bool = True, fields: bool = True) -> None:
        """Make *color* current and reflect it in every part of the dialog."""
        self._color = color
        if fields:
            q = QColor(color)
            h, s, v, _ = q.getHsvF()
            if h < 0:            # grays have no hue: keep the bar where it is
                h = self._hue.hue
            self._hue.set_hue(h)
            self._sv.set_hsv(h, s, v)
        if hex_field:
            self._hex.setText(color)
        self._set_hex_invalid(False)
        self._new_sw.setStyleSheet(
            f"background-color: {color}; border-top-right-radius: 8px;"
            " border-bottom-right-radius: 8px;")
        self._new_sw.setToolTip(color)
        self._update_sample()

    def _show_text(self, text: str) -> None:
        """Make *text* ("" = automatic) the text colour and reflect it."""
        self._text = text
        button = {"": self._text_auto, _WHITE: self._text_white,
                  _BLACK: self._text_black}.get(text, self._text_custom)
        button.setChecked(True)
        if button is self._text_custom:
            self._text_hex.setText(text)
        self._text_hex.setStyleSheet("")
        self._update_sample()

    def _update_sample(self) -> None:
        auto = accent_text_color(self._color)
        # "Automatic · White": which one automatic picks for this colour
        self._text_auto.setText(tr("colorpicker.text.auto") + " · "
                                + tr("colorpicker.text.white" if auto == _WHITE else "colorpicker.text.black"))
        self._sample.setStyleSheet(
            f"background-color: {self._color}; color: {self._text or auto};"
            " border-radius: 10px; padding: 0 14px; font-weight: 600;")
        self._reset_btn.setEnabled(self._color != DEFAULT_ACCENT or bool(self._text))

    def _set_text(self, text: str) -> None:
        if text != self._text:
            self._show_text(text)
            self.textColorChanged.emit(text)

    def _on_text_choice(self, choice: int) -> None:
        if choice < 3:
            self._set_text(("", _WHITE, _BLACK)[choice])
            return
        # Custom: the colour in the field, else the one in use now.
        text = normalize_hex(self._text_hex.text()) or self._text or accent_text_color(self._color)
        self._text_hex.setText(text)
        if text != self._text:
            self._text = text
            self._update_sample()
            self.textColorChanged.emit(text)

    def _on_text_hex_edited(self, text: str) -> None:
        digits = text.lstrip("#")
        if len(digits) == 6:
            self._text_hex.setStyleSheet("")
            self._text_custom.setChecked(True)
            color = normalize_hex(digits)
            if color != self._text:
                self._text = color
                self._update_sample()
                self.textColorChanged.emit(color)
        else:
            self._text_hex.setStyleSheet("border: 1px solid #ef4444;" if digits else "")

    def _reset(self) -> None:
        """Standard: the default teal with automatic text."""
        self._set_text("")
        self._set_from_outside(DEFAULT_ACCENT)

    def _set_hex_invalid(self, invalid: bool) -> None:
        self._hex.setStyleSheet("border: 1px solid #ef4444;" if invalid else "")

    def _set_from_outside(self, color: str) -> None:
        self._show_color(color)
        self._emit_now()

    def _on_sv(self) -> None:
        self._show_color(_hex(QColor.fromHsvF(self._hue.hue, self._sv.sat, self._sv.val)),
                         fields=False)
        self._schedule()

    def _on_hue(self) -> None:
        self._sv.set_hsv(self._hue.hue, self._sv.sat, self._sv.val)
        self._show_color(_hex(QColor.fromHsvF(self._hue.hue, self._sv.sat, self._sv.val)),
                         fields=False)
        self._schedule()

    def _on_hex_edited(self, text: str) -> None:
        digits = text.lstrip("#")
        if len(digits) == 6:
            self._show_color(normalize_hex(digits), hex_field=False)
            self._emit_now()
        else:
            # Shorter input may still become valid; #abc is accepted on Enter.
            self._set_hex_invalid(len(digits) not in (0, 3))

    def _on_hex_finished(self) -> None:
        color = normalize_hex(self._hex.text())
        if color is None:
            self._set_hex_invalid(True)
            return
        if color != self._color:
            self._show_color(color)
            self._emit_now()
        else:
            self._hex.setText(color)

    # ── preview ─────────────────────────────────────────────────────────────

    def _schedule(self) -> None:
        if not self._throttle.isActive():
            self._throttle.start()

    def _emit_now(self) -> None:
        self._throttle.stop()
        if self._color != self._emitted:
            self._emitted = self._color
            self.colorChanged.emit(self._color)

    def reject(self) -> None:
        # Undo the live preview before closing.
        self._throttle.stop()
        if self._text != self._initial_text:
            self._text = self._initial_text
            self.textColorChanged.emit(self._initial_text)
        if self._emitted != self._initial:
            self._emitted = self._initial
            self.colorChanged.emit(self._initial)
        super().reject()

    def accept(self) -> None:
        self._emit_now()
        super().accept()
