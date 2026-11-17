"""Shared Qt curve editor for the compact canvas node and Properties."""
import copy
import math

from NodeGraphQt import NodeBaseWidget
from Qt import QtCore, QtGui, QtWidgets

from .backend.graph_mapper import (
    KINDS, KIND_PARAMS, PARAM_LIMITS, exponential, logistic, normalize_config, unit_value,
)
from .widgets import NumberField

Qt = QtCore.Qt


class GraphPlot(QtWidgets.QWidget):
    changed = QtCore.Signal(object)
    edit_started = QtCore.Signal()
    edit_finished = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = normalize_config()
        self._drag_handle = None
        self._path_key = None
        self.setMinimumSize(150, 140)
        self.setMouseTracking(True)
        self.setAccessibleName('Graph Mapper curve editor')
        self.setToolTip('Drag handles to edit the curve. Right-click for functions and flips. Double-click to reset this function.')

    def sizeHint(self):
        return QtCore.QSize(240, 190)

    def set_config(self, config):
        config = normalize_config(config)
        if config != self.config:
            self.config = config
            self.update()

    def _emit_change(self):
        self.config = normalize_config(self.config)
        self.update()
        self.changed.emit(copy.deepcopy(self.config))

    def _plot(self):
        return QtCore.QRectF(20., 24., max(45., self.width() - 32.), max(45., self.height() - 42.))

    def _px(self, x, y):
        rect = self._plot()
        return QtCore.QPointF(rect.left() + x * rect.width(), rect.bottom() - y * rect.height())

    def _unit_at(self, position):
        rect = self._plot()
        return (max(0., min(1., (position.x() - rect.left()) / rect.width())),
                max(0., min(1., (rect.bottom() - position.y()) / rect.height())))

    @staticmethod
    def _event_pos(event):
        return event.position()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor('#1d2226'))
        rect = self._plot()
        painter.setPen(QtGui.QPen(QtGui.QColor('#424b50'), 1))
        painter.drawRect(rect)
        painter.setPen(QtGui.QPen(QtGui.QColor('#30383d'), 1))
        for k in range(1, 5):
            t = k / 5.
            painter.drawLine(self._px(t, 0), self._px(t, 1))
            painter.drawLine(self._px(0, t), self._px(1, t))
        font = painter.font()
        font.setPointSizeF(8)
        painter.setFont(font)
        painter.setPen(QtGui.QColor('#b4c3c6'))
        title = 'Cubic Bezier' if self.config['kind'] == 'Bezier' else self.config['kind']
        painter.drawText(6, 15, title + (' ↔' if self.config['flip_x'] else '') + (' ↕' if self.config['reverse'] else ''))
        painter.drawText(5, int(rect.top() + 5), '1')
        painter.drawText(5, int(rect.bottom() + 2), '0')
        painter.drawText(int(rect.right() - 3), int(rect.bottom() + 14), '1')
        key = (self.width(), self.height(), tuple(self.config.items()))
        if key != self._path_key:
            path = QtGui.QPainterPath()
            for i in range(161):
                x = i / 160.
                point = self._px(x, unit_value(x, self.config))
                path.moveTo(point) if i == 0 else path.lineTo(point)
            self._path, self._path_key = path, key
        painter.setPen(QtGui.QPen(QtGui.QColor('#88cbb7'), 1.8))
        painter.drawPath(self._path)
        for name, x, y in self._handles():
            painter.setPen(QtGui.QPen(QtGui.QColor('#12242a'), 1.2))
            painter.setBrush(QtGui.QColor('#efc56d' if name == self._drag_handle else '#e1ece9'))
            painter.drawEllipse(self._px(x, y), 4., 4.)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        pos = self._event_pos(event)
        nearest, best = None, 12. ** 2
        for name, x, y in self._handles():
            handle = self._px(x, y)
            distance = (handle.x() - pos.x()) ** 2 + (handle.y() - pos.y()) ** 2
            if distance < best:
                nearest, best = name, distance
        if nearest:
            self._drag_handle = nearest
            self.edit_started.emit()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_handle is not None:
            self.mouseMoveEvent(event)  # Commit the final cursor location too.
            self._drag_handle = None
            self.unsetCursor()
            self.edit_finished.emit()
            self.update()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def reset_kind(self):
        defaults = normalize_config()
        for key in KIND_PARAMS[self.config['kind']]:
            self.config[key] = defaults[key]
        self._emit_change()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.reset_kind()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        event.accept()
        self.show_curve_menu(event.globalPos(), self.window())

    def show_curve_menu(self, position, window):
        # Parent the menu to the editor window so Qt keeps it above the canvas.
        QtWidgets.QToolTip.hideText()
        menu = QtWidgets.QMenu(window)
        menu.setObjectName('GraphMapperCurveMenu')
        for kind in KINDS:
            action = menu.addAction('Cubic Bezier' if kind == 'Bezier' else kind)
            action.setCheckable(True)
            action.setChecked(self.config['kind'] == kind)
            action.triggered.connect(lambda checked=False, k=kind: self._set_kind(k))
        menu.addSeparator()
        for key, label in (('flip_x', 'Flip X'), ('reverse', 'Flip Y')):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.config[key])
            action.triggered.connect(lambda checked, k=key: self._set_flag(k, checked))
        menu.addAction('Reset current function').triggered.connect(self.reset_kind)
        menu.exec(position)
        menu.deleteLater()

    def _set_kind(self, kind):
        self.config['kind'] = kind
        self._emit_change()

    def _set_flag(self, key, checked):
        self.config[key] = bool(checked)
        self._emit_change()

    def _handles(self):
        """Editable handles in screen coordinates; the drawing is authoritative.

        Unlike fixed presets, every graph type now exposes at least one
        interactive handle. Some handles move only in one dimension because
        that dimension maps unambiguously to the underlying parameter.
        """
        c = self.config
        kind = c['kind']
        shown_y = (lambda y: 1.-y) if c['reverse'] else (lambda y: y)
        shown_x = (lambda x: 1.-x) if c['flip_x'] else (lambda x: x)
        if kind == 'Linear':
            return [('linear_a', shown_x(0.), shown_y(c['linear_a'])),
                    ('linear_b', shown_x(1.), shown_y(c['linear_b']))]
        if kind == 'Bezier':
            return [('bezier_1', shown_x(c['bezier_x1']), shown_y(c['bezier_y1'])),
                    ('bezier_2', shown_x(c['bezier_x2']), shown_y(c['bezier_y2']))]
        if kind == 'Quadratic Bezier':
            return [('quadratic', shown_x(c['quadratic_x']), shown_y(c['quadratic_y']))]
        if kind == 'Power':
            # Fixed horizontal position; vertical drag edits the exponent.
            return [('power', shown_x(.5), shown_y(.5 ** c['power_exponent']))]
        if kind == 'Parabola':
            # Only the peak HEIGHT is draggable. Preserve saved legacy X
            # positions, but do not let dragging move the vertex sideways.
            return [('parabola_peak', shown_x(c['parabola_peak_x']),
                     shown_y(c['parabola_peak_y']))]
        if kind == 'Smoothstep':
            # The midpoint of the configured range always has base value
            # .5. One vertical handle controls the bias/exponent.
            mid = .5 * (c['smoothstep_start'] + c['smoothstep_end'])
            return [('smoothstep_shape', shown_x(mid),
                     shown_y(.5 ** c['smoothstep_shape']))]
        if kind == 'Sigmoid':
            x = shown_x(.25)
            return [('sigmoid', x, unit_value(x, c))]
        if kind == 'Square Root':
            x = shown_x(.5)
            return [('sqrt', x, unit_value(x, c))]
        if kind == 'Exponential':
            x = shown_x(.5)
            return [('exponential', x, unit_value(x, c))]
        if kind == 'Sine':
            x = 1. / (1. + c['sine_frequency'])
            return [('sine_frequency', shown_x(x), unit_value(shown_x(x), c)),
                    ('sine_amplitude', shown_x(0.), shown_y(.5 - c['sine_amplitude']))]
        if kind == 'Sine Summation':
            f = c['sine_sum_frequency']
            # Frequency control is placed at an always-visible point on curve.
            xf = 1. / (1. + f)
            return [('sine_sum_frequency', shown_x(xf),
                     unit_value(shown_x(xf), c)),
                    ('sine_sum_a1', shown_x(0.),
                     unit_value(shown_x(0.), c)),
                    ('sine_sum_a2', shown_x(min(1., .25/f)),
                     unit_value(shown_x(min(1., .25/f)), c))]
        if kind == 'Gaussian':
            peak = c['gaussian_center']
            # A fixed X anchor gives a valid width handle even for sigma=1,
            # when no one-sigma point fits inside the plot. Its Y stays on curve.
            side = peak + .25 if peak <= .5 else peak - .25
            return [('gaussian_peak', shown_x(peak), shown_y(1.)),
                    ('gaussian_sigma', shown_x(side), unit_value(shown_x(side), c))]
        return []

    def mouseMoveEvent(self, event):
        if not self._drag_handle:
            return super().mouseMoveEvent(event)
        x, y = self._unit_at(self._event_pos(event))
        c = self.config
        # Convert displayed cursor coordinates back to unflipped math space.
        if c['flip_x']:
            x = 1. - x
        if c['reverse']:
            y = 1. - y
        handle = self._drag_handle
        if handle in ('linear_a', 'linear_b'):
            c[handle] = y
        elif handle == 'bezier_1':
            c['bezier_x1'] = min(x, c['bezier_x2'])
            c['bezier_y1'] = y
        elif handle == 'bezier_2':
            c['bezier_x2'] = max(x, c['bezier_x1'])
            c['bezier_y2'] = y
        elif handle == 'quadratic':
            c['quadratic_x'], c['quadratic_y'] = x, y
        elif handle == 'power':
            # The handle stays at x=0.5; its Y equals 0.5**exponent.
            # Horizontal pointer motion is intentionally ignored.
            y = max(.5**10., min(.5**.1, y))
            c['power_exponent'] = max(.1, min(10., math.log(y) / math.log(.5)))
        elif handle == 'parabola_peak':
            # Keep the existing peak X fixed, including old saved projects.
            c['parabola_peak_y'] = max(.05, min(1., y))
        elif handle == 'smoothstep_shape':
            # Classic smoothstep(t)**shape; at interval midpoint the value
            # is 0.5**shape, so the parameter has an exact Y inverse.
            y = max(.5**4., min(.5**.6, y))
            c['smoothstep_shape'] = max(.6, min(4., math.log(y) / math.log(.5)))
        elif handle == 'sigmoid':
            # Normalized sigmoid at x=.25 decreases as steepness increases.
            # Binary search avoids an arbitrary linear Y-to-k approximation.
            low, high = .5, 24.
            for _ in range(32):
                mid = (low+high)*.5
                a = logistic(-mid*.5)
                b = logistic(mid*.5)
                sample = (logistic(-mid*.25)-a)/(b-a)
                if sample > y:
                    low = mid
                else:
                    high = mid
            c['sigmoid_steepness'] = .5*(low+high)
        elif handle == 'sqrt':
            # sqrt is a variable-exponent root family; dragging UP increases
            # the output at x=.5 and therefore lowers the exponent.
            y = max(.5, min(.5**.1, y))
            c['sqrt_exponent'] = max(.1, min(1., math.log(y) / math.log(.5)))
        elif handle == 'exponential':
            low, high = -12., 12.
            for _ in range(32):
                mid = (low+high)*.5
                if exponential(.5, mid) > y:
                    low = mid
                else:
                    high = mid
            c['exponential_rate'] = .5*(low+high)
        elif handle == 'sine_frequency':
            c['sine_frequency'] = max(.25, min(6., 1. / max(.001, x) - 1.))
        elif handle == 'sine_amplitude':
            c['sine_amplitude'] = max(0., min(.5, .5 - y))
        elif handle == 'sine_sum_frequency':
            c['sine_sum_frequency'] = max(.25, min(6., 1. / max(.001, x) - 1.))
        elif handle == 'sine_sum_a1':
            # At x=0: y=.5-a1-a2, provided the result does not clip.
            c['sine_sum_a1'] = max(0., min(.5, .5 - c['sine_sum_a2'] - y))
        elif handle == 'sine_sum_a2':
            # At x=.25/f: first cosine=0, second cosine=-1, y=.5+a2.
            c['sine_sum_a2'] = max(-.5, min(.5, y - .5))
        elif handle == 'gaussian_peak':
            c['gaussian_center'] = x
        elif handle == 'gaussian_sigma':
            c['gaussian_sigma'] = (.01 if y <= 0 else 1. if y >= 1 else
                                   max(.01, min(1., .25 / math.sqrt(-2. * math.log(y)))))
        self._emit_change()
        event.accept()



class GraphMapperWidget(NodeBaseWidget):
    def __init__(self, parent=None):
        super().__init__(parent, name='graph_config', label='')
        self.plot = GraphPlot()
        self.plot.setFixedSize(176, 152)
        self.set_custom_widget(self.plot)
        self.widget().layout().setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        self.plot.changed.connect(self.on_value_changed)

    def get_value(self):
        return copy.deepcopy(self.plot.config)

    def set_value(self, value):
        self.plot.set_config(value)


class GraphMapperMenuFilter(QtCore.QObject):
    """Route curve menus before NodeGraphQt's view consumes context events."""
    def __init__(self, viewer):
        super().__init__(viewer.viewport())
        self.viewer = viewer
        viewer.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.ContextMenu:
            scene_pos = self.viewer.mapToScene(event.pos())
            for item in self.viewer.items(event.pos()):
                if not isinstance(item, GraphMapperWidget) or not item.isVisible():
                    continue
                local = item.plot.mapFrom(item.widget(), item.mapFromScene(scene_pos).toPoint())
                if item.plot.rect().contains(local):
                    self.viewer.RMB_state = False
                    event.accept()
                    item.plot.show_curve_menu(event.globalPos(), self.viewer.window())
                    return True
        return super().eventFilter(watched, event)


class GraphMapperControls(QtWidgets.QWidget):
    changed = QtCore.Signal(object)
    edit_started = QtCore.Signal()
    edit_finished = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.config = normalize_config()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.kind = QtWidgets.QComboBox()
        self.kind.setAccessibleName('Graph Mapper function')
        for kind in KINDS:
            self.kind.addItem('Cubic Bezier' if kind == 'Bezier' else kind, kind)
        layout.addWidget(self.kind)
        self.plot = GraphPlot()
        self.plot.setMinimumHeight(190)
        layout.addWidget(self.plot)
        row = QtWidgets.QHBoxLayout()
        self.flip_x, self.flip_y = QtWidgets.QPushButton('Flip X'), QtWidgets.QPushButton('Flip Y')
        for button in (self.flip_x, self.flip_y):
            button.setCheckable(True)
            row.addWidget(button)
        self.reset = QtWidgets.QPushButton('Reset')
        row.addWidget(self.reset)
        layout.addLayout(row)
        self.parameters = QtWidgets.QWidget()
        self.form = QtWidgets.QFormLayout(self.parameters)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.fields = {}
        for key, (low, high) in PARAM_LIMITS.items():
            editor = NumberField()
            editor.setMinimumHeight(36)
            editor.setRange(low, high)
            editor.setDecimals(4)
            editor.setAccessibleName('Graph Mapper ' + key.replace('_', ' '))
            label = key.replace('_', ' ').title().replace('Bezier ', '')
            self.form.addRow(label, editor)
            self.fields[key] = editor
            editor.valueChanged.connect(lambda value, k=key: self._parameter(k, value))
        layout.addWidget(self.parameters)
        self.plot.changed.connect(self._commit)
        self.plot.edit_started.connect(self.edit_started.emit)
        self.plot.edit_finished.connect(self.edit_finished.emit)
        self.kind.currentIndexChanged.connect(lambda index: self._commit({**self.config, 'kind': self.kind.itemData(index)}))
        self.flip_x.clicked.connect(lambda checked: self._commit({**self.config, 'flip_x': checked}))
        self.flip_y.clicked.connect(lambda checked: self._commit({**self.config, 'reverse': checked}))
        self.reset.clicked.connect(self.plot.reset_kind)
        self.set_config(self.config)

    def set_config(self, config):
        self.config = normalize_config(config)
        self.plot.set_config(self.config)
        blockers = [QtCore.QSignalBlocker(w) for w in (self.kind, self.flip_x, self.flip_y, *self.fields.values())]
        self.kind.setCurrentIndex(self.kind.findData(self.config['kind']))
        self.flip_x.setChecked(self.config['flip_x'])
        self.flip_y.setChecked(self.config['reverse'])
        for key, editor in self.fields.items():
            if not editor.hasFocus() or editor.value() != round(self.config[key], 4):
                editor.setValue(self.config[key])
            self.form.setRowVisible(editor, key in KIND_PARAMS[self.config['kind']])
        del blockers

    def _parameter(self, key, value):
        candidate = {**self.config, key: value}
        # Editing one constrained handle should stop at its partner, not throw.
        if key == 'bezier_x1':
            candidate[key] = min(value, candidate['bezier_x2'])
        elif key == 'bezier_x2':
            candidate[key] = max(value, candidate['bezier_x1'])
        elif key == 'smoothstep_start':
            candidate[key] = min(value, candidate['smoothstep_end'] - .05)
        elif key == 'smoothstep_end':
            candidate[key] = max(value, candidate['smoothstep_start'] + .05)
        self._commit(candidate)

    def _commit(self, config):
        self.set_config(config)
        self.changed.emit(copy.deepcopy(self.config))
