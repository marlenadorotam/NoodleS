"""Reusable numeric editors shared by nodes and the properties panel."""
import math

from Qt import QtCore, QtGui, QtWidgets

from .numeric import round_integer


S3D_ACTIVE_COLOR = '#5c3921'


def wrapping_label(text=""):
    label = QtWidgets.QLabel(text)
    label.setTextFormat(QtCore.Qt.PlainText)
    label.setWordWrap(True)
    policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    return label


class _FieldLabel(QtWidgets.QLabel):
    def __init__(self, title):
        super().__init__(title)
        self.setTextFormat(QtCore.Qt.PlainText)
        self.setWordWrap(True)
        policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def sizeHint(self):
        # Bound long descriptions without reserving a column for short ones.
        width = min(self.fontMetrics().horizontalAdvance(self.text()) + 1, 90)
        return QtCore.QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        return self.sizeHint()


def add_field(layout, title, editor):
    """Place a label beside its editor or read-only value."""
    row = QtWidgets.QHBoxLayout()
    label = _FieldLabel(title)
    row.setSpacing(round(7 * label.logicalDpiX() / 25.4))
    label.setBuddy(editor)
    row.addWidget(label)
    row.addWidget(editor, 1)
    layout.addLayout(row)
    return label


class InputStack(QtWidgets.QWidget):
    """Show one input page, sized by Qt to that page's actual contents.

    Hidden pages do not reserve space. In particular, a wrapped QLabel drives
    height-for-width through the layout rather than a fixed preview height.
    """
    def __init__(self):
        super().__init__()
        self._pages = []
        self._current = None
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

    def addWidget(self, widget):
        self._pages.append(widget)
        self.layout().addWidget(widget)
        widget.hide()
        if self._current is None:
            self.setCurrentWidget(widget)

    def setCurrentWidget(self, widget):
        if widget not in self._pages:
            raise ValueError("Unknown input page.")
        if self._current is widget:
            return
        self._current = widget
        for page in self._pages:
            page.setVisible(page is widget)

    def currentWidget(self):
        return self._current

    def widget(self, index):
        return self._pages[index]


class NumberField(QtWidgets.QLineEdit):
    """Accept numeric text, then round and clamp on Enter or focus loss.

    Text validation is deliberately independent of the allowed value range:
    users can finish typing an out-of-range number and get the nearest bound.
    """
    valueChanged = QtCore.Signal(float)

    def __init__(self):
        super().__init__()
        self._value = 0.0
        self._minimum, self._maximum = -1e9, 1e9
        self._decimals = 4
        self._step_buttons = []
        self._validator = QtGui.QDoubleValidator(-1e308, 1e308, 12, self)
        self._validator.setNotation(QtGui.QDoubleValidator.Notation.StandardNotation)
        self.setValidator(self._validator)
        self.editingFinished.connect(self._commit)
        self._render_value()

    def enableStepButtons(self):
        """Add compact arrow buttons without restricting text entry to integers."""
        if self._step_buttons:
            return
        for direction, arrow, name in (
            (1, QtCore.Qt.UpArrow, "Increase value"),
            (-1, QtCore.Qt.DownArrow, "Decrease value"),
        ):
            button = QtWidgets.QToolButton(self)
            button.setArrowType(arrow)
            button.setAccessibleName(name)
            button.setToolTip(name)
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            button.setAutoRepeat(True)
            button.setAutoRepeatDelay(400)
            button.setAutoRepeatInterval(80)
            button.setStyleSheet(
                "QToolButton { padding: 0; margin: 0; border: 0;"
                " background: #394149; border-radius: 1px; }"
                "QToolButton:hover { background: #4a5860; }"
                "QToolButton:pressed { background: #35594e; }"
            )
            button.clicked.connect(lambda checked=False, step=direction: self.stepBy(step))
            self._step_buttons.append(button)
            button.show()
        self.setTextMargins(0, 0, 17, 0)
        self._position_step_buttons()

    def stepBy(self, steps):
        self._commit()
        increment = 1 if self._decimals == 0 else 0.1
        self.setValue(self._value + steps * increment)

    def _position_step_buttons(self):
        if self._step_buttons:
            half = (self.height() - 4) // 2
            self._step_buttons[0].setGeometry(self.width() - 17, 2, 15, half)
            self._step_buttons[1].setGeometry(self.width() - 17, 2 + half, 15, self.height() - 4 - half)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_step_buttons()

    def keyPressEvent(self, event):
        if self._step_buttons and event.key() in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down):
            self.stepBy(1 if event.key() == QtCore.Qt.Key_Up else -1)
            event.accept()
            return
        super().keyPressEvent(event)

    def setRange(self, minimum, maximum):
        if not math.isfinite(minimum) or not math.isfinite(maximum) or minimum > maximum:
            raise ValueError("Invalid numeric field range.")
        if (minimum, maximum) == (self._minimum, self._maximum):
            return
        self._minimum, self._maximum = minimum, maximum
        self.setValue(self._value)

    def setDecimals(self, decimals):
        if self._decimals == decimals:
            return
        self._decimals = decimals
        self.setValue(self._value)

    def setValue(self, value):
        value = float(value)
        if not math.isfinite(value):
            self._render_value()
            return
        value = max(self._minimum, min(self._maximum, value))
        if self._decimals == 0:
            value = round_integer(value)
        else:
            value = round(value, self._decimals)
        value = max(self._minimum, min(self._maximum, value))
        changed = value != self._value
        self._value = value
        self._render_value()
        if changed:
            self.valueChanged.emit(value)

    def value(self):
        return self._value

    def _render_value(self):
        text = self.locale().toString(float(self._value), "f", self._decimals)
        if self._decimals:
            text = text.rstrip("0").rstrip(self.locale().decimalPoint())
        if self.text() != text:
            self.setText(text)

    def _commit(self):
        value, valid = self.locale().toDouble(self.text())
        if valid and math.isfinite(value) and self.hasAcceptableInput():
            self.setValue(value)
        else:
            self._render_value()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._commit()
