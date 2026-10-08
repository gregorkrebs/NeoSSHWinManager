"""
stepper.py – A number field between two round buttons, − and +, in place
of a spin box's small up and down arrows.
"""

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractSpinBox, QFrame, QHBoxLayout, QPushButton

from src.i18n import tr
from src.ui.icons import icon as svg_icon
from src.ui.theme import dark_tone, is_light
from src.ui.widgets.no_wheel import NoWheelSpinBox


class Stepper(QFrame):
    """[−]  30  [+] in a pill. Holding a button keeps stepping; a button
    turns pale at its end of the range. The number can also be typed."""

    valueChanged = pyqtSignal(int)

    def __init__(self, minimum: int, maximum: int, value: int, *, step: int = 1,
                 theme: str = "dark", parent=None):
        super().__init__(parent)
        self.setObjectName("stepper")
        icon_color = "#4a5a6a" if is_light(theme) else dark_tone(theme, "#c8d6e5")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._spin = NoWheelSpinBox()
        self._spin.setObjectName("stepperValue")
        self._spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin.setRange(minimum, maximum)
        self._spin.setSingleStep(step)
        self._spin.setValue(value)
        self._spin.setFixedWidth(44)
        self._spin.valueChanged.connect(self._on_value_changed)

        self._minus = self._button("minus", -1, tr("stepper.decrease"), icon_color)
        self._plus = self._button("plus", 1, tr("stepper.increase"), icon_color)
        layout.addWidget(self._minus)
        layout.addWidget(self._spin)
        layout.addWidget(self._plus)
        self._update_buttons()

    def _button(self, icon_name: str, direction: int, tip: str, color: str) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("stepperBtn")
        btn.setFixedSize(QSize(24, 24))
        btn.setIcon(svg_icon(icon_name, color, 12))
        btn.setIconSize(QSize(12, 12))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip(tip)
        btn.setAccessibleName(tip)
        btn.setAutoRepeat(True)
        btn.setAutoRepeatDelay(400)
        btn.setAutoRepeatInterval(70)
        btn.clicked.connect(lambda: self._step(direction))
        return btn

    def _step(self, direction: int) -> None:
        self._spin.stepBy(direction)
        # stepBy() selects the number; a click on a button should not
        self._spin.lineEdit().deselect()

    def _on_value_changed(self, value: int) -> None:
        self._update_buttons()
        self.valueChanged.emit(value)

    def _update_buttons(self) -> None:
        self._minus.setEnabled(self._spin.value() > self._spin.minimum())
        self._plus.setEnabled(self._spin.value() < self._spin.maximum())

    # The parts of the QSpinBox interface the settings use.
    def value(self) -> int:
        return self._spin.value()

    def setValue(self, value: int) -> None:  # noqa: N802
        self._spin.setValue(value)

    def setRange(self, minimum: int, maximum: int) -> None:  # noqa: N802
        self._spin.setRange(minimum, maximum)
        self._update_buttons()
