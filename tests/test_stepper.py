"""
tests/test_stepper.py – The number field with round − and + buttons.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_buttons_step_and_stop_at_the_ends(app):
    from src.ui.widgets.stepper import Stepper
    stepper = Stepper(5, 7, 6)
    seen = []
    stepper.valueChanged.connect(seen.append)
    stepper._plus.click()
    assert stepper.value() == 7 and not stepper._plus.isEnabled() and stepper._minus.isEnabled()
    stepper._plus.click()                       # disabled at the top: no change
    assert stepper.value() == 7
    stepper._minus.click()
    stepper._minus.click()
    assert stepper.value() == 5 and not stepper._minus.isEnabled()
    assert seen == [7, 6, 5]


def test_value_is_kept_in_range(app):
    from src.ui.widgets.stepper import Stepper
    stepper = Stepper(5, 300, 30, theme="light")
    stepper.setValue(1000)
    assert stepper.value() == 300 and not stepper._plus.isEnabled()
    stepper.setRange(5, 600)
    assert stepper._plus.isEnabled()


def test_no_spin_arrows_and_translated_tips(app):
    from PyQt6.QtWidgets import QAbstractSpinBox
    from src.i18n import tr
    from src.ui.widgets.stepper import Stepper
    stepper = Stepper(5, 300, 30)
    assert stepper._spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
    assert stepper._minus.toolTip() == tr("stepper.decrease")
    assert stepper._plus.toolTip() == tr("stepper.increase")


def test_a_click_leaves_the_number_unselected(app):
    from src.ui.widgets.stepper import Stepper
    stepper = Stepper(5, 300, 30)
    stepper._plus.click()
    assert stepper._spin.lineEdit().selectedText() == ""

