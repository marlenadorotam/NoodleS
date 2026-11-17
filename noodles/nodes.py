"""NoodleS components, using the standard NodeGraphQt node presentation."""
from NodeGraphQt import NodeBaseWidget
from Qt import QtCore, QtGui, QtWidgets

from .numeric import normalize_number_state
from .slider import SLIDER_PROPERTIES, clamp_slider_value, normalize_slider_state
from .widgets import NumberField
from .backend.point import normalize_point_state
from .backend.domain import normalize_domain_state
from .backend.range import normalize_range_state
from .backend.arithmetic import normalize_arithmetic_state
from .node_layout import CompactNode
from .math_nodes import MATH_NODE_CLASSES
from .curve_nodes import CURVE_NODE_CLASSES
import copy
import uuid


class NumberWidget(NodeBaseWidget):
    def __init__(self, parent=None):
        super().__init__(parent, name="value", label="")
        self._mode = "double"
        self.spin = NumberField()
        self.spin.setRange(-1_000_000_000, 1_000_000_000)
        self.spin.setDecimals(4)
        self.spin.enableStepButtons()
        self.spin.setFixedWidth(120)
        self.set_custom_widget(self.spin)
        self.widget().layout().setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        self.spin.valueChanged.connect(self.on_value_changed)

    def get_value(self):
        return int(self.spin.value()) if self._mode == "integer" else float(self.spin.value())

    def configure(self, state):
        blocker = QtCore.QSignalBlocker(self.spin)
        self._mode = state["mode"]
        self.spin.setDecimals(0 if self._mode == "integer" else 4)
        self.spin.setValue(state["value"])
        del blocker

    def set_value(self, value):
        self.configure(normalize_number_state({"mode": self._mode, "value": value}))


class SliderWidget(NodeBaseWidget):
    """A standard Qt slider with a numeric field; no custom node painting."""
    edit_started = QtCore.Signal()
    edit_finished = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent, name="value", label="Value")
        self._minimum, self._maximum, self._mode = 0.0, 100.0, "double"
        self._steps = 10000
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 10000)
        self.spin = NumberField()
        self.spin.setRange(0, 100)
        self.spin.setDecimals(2)
        layout.addWidget(self.slider)
        layout.addWidget(self.spin)
        container.setFixedWidth(150)
        self.set_custom_widget(container)
        self.widget().layout().setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        self.slider.valueChanged.connect(self._slide)
        self.spin.valueChanged.connect(self._spin)
        self.slider.sliderPressed.connect(self.edit_started.emit)
        self.slider.sliderReleased.connect(self.edit_finished.emit)

    def _slide(self, value):
        # The handle is already at the requested position. Only synchronize
        # the number field; resetting the slider here adds unnecessary work.
        blocker = QtCore.QSignalBlocker(self.spin)
        if self._mode == "integer":
            number = self._minimum + value
        else:
            number = self._minimum + (self._maximum - self._minimum) * value / max(1, self._steps)
        self.spin.setValue(clamp_slider_value(number, self._minimum, self._maximum, self._mode))
        del blocker
        self.on_value_changed()

    def _spin(self, value):
        self.set_value(value)
        self.on_value_changed()

    def get_value(self):
        value = self.spin.value()
        return int(value) if self._mode == "integer" else value

    def configure(self, state):
        configuration = (state["minimum"], state["maximum"], state["mode"])
        if configuration != (self._minimum, self._maximum, self._mode):
            self._minimum, self._maximum, self._mode = configuration
            span = self._maximum - self._minimum
            self._steps = int(span) if self._mode == "integer" else min(10000, round(span * 100))
            blockers = [QtCore.QSignalBlocker(self.spin), QtCore.QSignalBlocker(self.slider)]
            self.spin.setDecimals(0 if self._mode == "integer" else 2)
            self.spin.setRange(self._minimum, self._maximum)
            self.slider.setRange(0, self._steps)
            self.slider.setEnabled(span > 0)
            del blockers
        if self.get_value() != state["value"] or self._position(state["value"]) != self.slider.value():
            self.set_value(state["value"])

    def _position(self, value):
        if self._mode == "integer":
            return int(value - self._minimum)
        span = self._maximum - self._minimum
        return round((value - self._minimum) / span * self._steps) if span else 0

    def set_value(self, value):
        value = clamp_slider_value(value, self._minimum, self._maximum, self._mode)
        a, b = QtCore.QSignalBlocker(self.spin), QtCore.QSignalBlocker(self.slider)
        self.spin.setValue(value)
        self.slider.setValue(self._position(self.get_value()))
        del a, b


class ResultWidget(NodeBaseWidget):
    def __init__(self, parent=None):
        super().__init__(parent, name="display", label="Result")
        self.label = QtWidgets.QLabel("—")
        self.label.setMinimumWidth(160)
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(240)
        self.label.setTextFormat(QtCore.Qt.PlainText)
        palette = self.label.palette()
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(230, 230, 230))
        self.label.setPalette(palette)
        self.set_custom_widget(self.label)

    def get_value(self):
        return self.label.text()

    def set_value(self, value):
        self.label.setText(str(value))


class NumberStateCommand(QtGui.QUndoCommand):
    def __init__(self, node, state, name):
        super().__init__("Change Number " + name)
        self.node = node
        self.before = node.number_state()
        self.after = state

    def redo(self):
        self.node._apply_number_state(self.after)

    def undo(self):
        self.node._apply_number_state(self.before)


class NumberNode(CompactNode):
    __identifier__ = "NoodleS.Inputs"
    NODE_NAME = "Number"
    OPERATION = "number"

    def __init__(self):
        super().__init__()
        self.create_property("mode", "double")
        self.add_output("Number")
        self.add_custom_widget(NumberWidget(self.view))

    def number_state(self):
        return {name: self.get_property(name) for name in ("mode", "value")}

    def set_property(self, name, value, push_undo=True):
        if name not in ("mode", "value"):
            return super().set_property(name, value, push_undo)
        before = self.number_state()
        after = normalize_number_state({**before, name: value})
        if before == after:
            return
        if self.graph and push_undo:
            self.graph.undo_stack().push(NumberStateCommand(self, after, name))
        else:
            self._apply_number_state(after)

    def _apply_number_state(self, state):
        before = self.number_state()
        for name in ("mode", "value"):
            self.model.set_property(name, state[name])
        self.get_widget("value").configure(state)
        if self.graph:
            for name in ("mode", "value"):
                if type(before[name]) is not type(state[name]) or before[name] != state[name]:
                    self.graph.property_changed.emit(self, name, state[name])

    def update(self):
        widget = self.view.widgets.get("value")
        if widget is not None:
            state = normalize_number_state(self.number_state())
            for name in ("mode", "value"):
                self.model.set_property(name, state[name])
            widget.configure(state)
        super().update()


class SliderStateCommand(QtGui.QUndoCommand):
    """Merge only changes belonging to one physical slider gesture."""
    def __init__(self, node, state, gesture, name):
        super().__init__("Change Slider " + name)
        self.node = node
        self.before = node.slider_state()
        self.after = state
        self.gesture = gesture

    def id(self):
        return 0x4E534C

    def mergeWith(self, other):
        if (not isinstance(other, SliderStateCommand) or other.node is not self.node
                or self.gesture is None or other.gesture is not self.gesture):
            return False
        self.after = other.after
        self.setObsolete(self.before == self.after)
        return True

    def redo(self):
        self.node._apply_slider_state(self.after)

    def undo(self):
        self.node._apply_slider_state(self.before)


class SliderNode(CompactNode):
    __identifier__ = "NoodleS.Inputs"
    NODE_NAME = "Slider"
    OPERATION = "slider"

    def __init__(self):
        super().__init__()
        self._value_gesture = None
        self.create_property("mode", "double")
        self.create_property("minimum", 0.0)
        self.create_property("maximum", 100.0)
        self.add_output("Number")
        widget = SliderWidget(self.view)
        self.add_custom_widget(widget)
        widget.edit_started.connect(self._begin_value_edit)
        widget.edit_finished.connect(self._end_value_edit)

    def _begin_value_edit(self):
        self._value_gesture = object()

    def _end_value_edit(self):
        self._value_gesture = None

    def set_property(self, name, value, push_undo=True):
        if name not in SLIDER_PROPERTIES:
            return super().set_property(name, value, push_undo)
        before = self.slider_state()
        after = normalize_slider_state({**before, name: value}, changed=name)
        if before == after:
            return
        if self.graph and push_undo:
            gesture = self._value_gesture if name == "value" else None
            self.graph.undo_stack().push(SliderStateCommand(self, after, gesture, name))
        else:
            self._apply_slider_state(after)

    def slider_state(self):
        return {name: self.get_property(name) for name in SLIDER_PROPERTIES}

    def _apply_slider_state(self, state):
        before = self.slider_state()
        for name in SLIDER_PROPERTIES:
            self.model.set_property(name, state[name])
        self.get_widget("value").configure(state)
        # A numeric edit does not change ports, dimensions or widget layout.
        # Notify the existing graph adapter without BaseNode's full draw_node.
        if self.graph:
            for name in SLIDER_PROPERTIES:
                if type(before[name]) is not type(state[name]) or before[name] != state[name]:
                    self.graph.property_changed.emit(self, name, state[name])

    def update(self):
        # NodeGraphQt restores custom properties directly before calling update.
        # Configure the widget from the complete restored state, including when
        # a saved value lies outside the old default 0–100 range.
        widget = self.view.widgets.get("value")
        if widget is not None:
            state = normalize_slider_state(self.slider_state())
            for name in SLIDER_PROPERTIES:
                self.model.set_property(name, state[name])
            widget.configure(state)
        super().update()


class ArithmeticStateCommand(QtGui.QUndoCommand):
    def __init__(self, node, state):
        super().__init__("Change " + node.NODE_NAME + " input modifiers")
        self.node, self.before, self.after = node, node.arithmetic_state(), state

    def redo(self):
        self.node._apply_arithmetic_state(self.after)

    def undo(self):
        self.node._apply_arithmetic_state(self.before)


class AdditionNode(CompactNode):
    __identifier__ = "NoodleS.Math"
    NODE_NAME = "Addition"
    OPERATION = "addition"

    def __init__(self):
        super().__init__()
        self.add_input("A")
        self.add_input("B")
        self.add_output("R").view.setToolTip("Result · Number, Vector or Point")
        self.create_property("tree_modes", {})

    def arithmetic_state(self):
        return copy.deepcopy({"tree_modes": self.get_property("tree_modes")})

    def set_property(self, name, value, push_undo=True):
        if name != "tree_modes":
            return super().set_property(name, value, push_undo)
        before = self.arithmetic_state()
        after = normalize_arithmetic_state({name: value})
        if before == after:
            return
        if self.graph and push_undo:
            self.graph.undo_stack().push(ArithmeticStateCommand(self, after))
        else:
            self._apply_arithmetic_state(after)

    def _apply_arithmetic_state(self, state):
        before = self.arithmetic_state()
        self.model.set_property("tree_modes", copy.deepcopy(state["tree_modes"]))
        for port in self.input_ports():
            mode = state["tree_modes"].get(port.name(), "none")
            port.view.setToolTip(port.name() + " · Number, Vector or Point" +
                                 (" · " + mode.title() if mode != "none" else ""))
        if self.graph and before != state:
            self.graph.property_changed.emit(self, "tree_modes", state["tree_modes"])

    def update(self):
        self._apply_arithmetic_state(normalize_arithmetic_state(self.arithmetic_state()))
        super().update()


class MultiplicationNode(AdditionNode):
    NODE_NAME = "Multiplication"
    OPERATION = "multiplication"


class PointStateCommand(QtGui.QUndoCommand):
    def __init__(self, node, state, name):
        super().__init__("Change Point " + name)
        self.node, self.before, self.after = node, node.point_state(), state

    def redo(self):
        self.node._apply_point_state(self.after)

    def undo(self):
        self.node._apply_point_state(self.before)


class PointNode(CompactNode):
    __identifier__ = "NoodleS.Geometry"
    NODE_NAME = "Point"
    OPERATION = "point"

    def __init__(self):
        super().__init__()
        for axis in ("X", "Y", "Z"):
            self.add_input(axis)
        for output in ("P", "X", "Y", "Z"):
            self.add_output(output)
        state = normalize_point_state({"node_uuid": str(uuid.uuid4())})
        for name, value in state.items():
            self.create_property(name, value)
        self.reference_error = "Waiting for Serpentine reference data."
        self.scene_status = "Not published"
        self.scene_status_error = False
        self.parametric_object = None

    def point_state(self):
        return copy.deepcopy({name: self.get_property(name) for name in (
            "mode", "project_uuid", "node_uuid", "x", "y", "z", "tree_modes", "references")})

    def set_property(self, name, value, push_undo=True):
        if name not in ("mode", "project_uuid", "node_uuid", "x", "y", "z", "tree_modes", "references"):
            return super().set_property(name, value, push_undo)
        before = self.point_state()
        after = normalize_point_state({**before, name: value})
        if before == after:
            return
        if self.graph and push_undo:
            self.graph.undo_stack().push(PointStateCommand(self, after, name))
        else:
            self._apply_point_state(after)

    def _apply_point_state(self, state):
        before = self.point_state()
        if before["mode"] != state["mode"] and state["mode"] == "reference":
            self.reference_error = "Reading live Point references…"
        for name, value in state.items():
            self.model.set_property(name, copy.deepcopy(value))
        for port in self.input_ports():
            mode = state["tree_modes"].get(port.name(), "none")
            port.view.setToolTip(port.name() + (" · " + mode.title() if mode != "none" else "") +
                                 (" · drives referenced coordinates" if state["mode"] == "reference" else ""))
        if self.graph:
            for name, value in state.items():
                if before[name] != value:
                    self.graph.property_changed.emit(self, name, value)


class DomainStateCommand(QtGui.QUndoCommand):
    def __init__(self, node, state, name):
        super().__init__("Change Domain " + name)
        self.node, self.before, self.after = node, node.domain_state(), state

    def redo(self):
        self.node._apply_domain_state(self.after)

    def undo(self):
        self.node._apply_domain_state(self.before)


class DomainNode(CompactNode):
    __identifier__ = "NoodleS.Math"
    NODE_NAME = "Domain"
    OPERATION = "domain"

    def __init__(self):
        super().__init__()
        for name, description in (("A", "Start"), ("B", "End")):
            self.add_input(name).view.setToolTip(description)
        for name, description in (("D", "Domain"), ("L", "Length (absolute span)")):
            self.add_output(name).view.setToolTip(description)
        for name, value in normalize_domain_state({}).items():
            self.create_property(name, value)

    def domain_state(self):
        return copy.deepcopy({name: self.get_property(name) for name in ("start", "end", "tree_modes")})

    def set_property(self, name, value, push_undo=True):
        if name not in ("start", "end", "tree_modes"):
            return super().set_property(name, value, push_undo)
        before = self.domain_state()
        after = normalize_domain_state({**before, name: value})
        if before == after:
            return
        if self.graph and push_undo:
            self.graph.undo_stack().push(DomainStateCommand(self, after, name))
        else:
            self._apply_domain_state(after)

    def _apply_domain_state(self, state):
        before = self.domain_state()
        for name, value in state.items():
            self.model.set_property(name, copy.deepcopy(value))
        for port, description in (("A", "Start"), ("B", "End")):
            mode = state["tree_modes"].get(port, "none")
            self.inputs()[port].view.setToolTip(description + (" · " + mode.title() if mode != "none" else ""))
        if self.graph:
            for name, value in state.items():
                if before[name] != value:
                    self.graph.property_changed.emit(self, name, value)

    def update(self):
        self._apply_domain_state(normalize_domain_state(self.domain_state()))
        super().update()


class RangeStateCommand(QtGui.QUndoCommand):
    def __init__(self, node, state, name):
        super().__init__("Change Range " + name)
        self.node, self.before, self.after = node, node.range_state(), state

    def redo(self):
        self.node._apply_range_state(self.after)

    def undo(self):
        self.node._apply_range_state(self.before)


class RangeNode(CompactNode):
    __identifier__ = "NoodleS.Math"
    NODE_NAME = "Range"
    OPERATION = "range"

    def __init__(self):
        super().__init__()
        for name, description in (("D", "Domain"), ("N", "Steps (number of segments)")):
            self.add_input(name).view.setToolTip(description)
        for name, description in (("R", "Range"), ("Flat", "Flattened numbers"), ("Count", "Total number of values")):
            self.add_output(name).view.setToolTip(description)
        for name, value in normalize_range_state({}).items():
            self.create_property(name, value)

    def range_state(self):
        return copy.deepcopy({name: self.get_property(name) for name in ("start", "end", "steps", "tree_modes")})

    def set_property(self, name, value, push_undo=True):
        if name not in ("start", "end", "steps", "tree_modes"):
            return super().set_property(name, value, push_undo)
        before = self.range_state()
        after = normalize_range_state({**before, name: value})
        if before == after:
            return
        if self.graph and push_undo:
            self.graph.undo_stack().push(RangeStateCommand(self, after, name))
        else:
            self._apply_range_state(after)

    def _apply_range_state(self, state):
        before = self.range_state()
        for name, value in state.items():
            self.model.set_property(name, copy.deepcopy(value))
        for port, description in (("D", "Domain"), ("N", "Steps (number of segments)")):
            mode = state["tree_modes"].get(port, "none")
            self.inputs()[port].view.setToolTip(description + (" · " + mode.title() if mode != "none" else ""))
        if self.graph:
            for name, value in state.items():
                if before[name] != value:
                    self.graph.property_changed.emit(self, name, value)

    def update(self):
        self._apply_range_state(normalize_range_state(self.range_state()))
        super().update()


class WatchNode(CompactNode):
    __identifier__ = "NoodleS.Data"
    NODE_NAME = "Watch"
    OPERATION = "watch"

    def __init__(self):
        super().__init__()
        self.add_input("Value")
        self.add_output("Value")
        self.add_custom_widget(ResultWidget(self.view))


from .list_nodes import LIST_NODE_CLASSES
from .solid_nodes import SOLID_NODE_CLASSES
from .grid_nodes import GRID_NODE_CLASSES
from .preview_nodes import PREVIEW_NODE_CLASSES
from .operation_nodes import OPERATION_NODE_CLASSES

NODE_CLASSES = (NumberNode, SliderNode, AdditionNode, MultiplicationNode, DomainNode, RangeNode,
                PointNode, WatchNode) + MATH_NODE_CLASSES + CURVE_NODE_CLASSES + SOLID_NODE_CLASSES + GRID_NODE_CLASSES + PREVIEW_NODE_CLASSES + OPERATION_NODE_CLASSES + LIST_NODE_CLASSES
NODE_TYPES = {f"{cls.__identifier__}.{cls.__name__}": cls for cls in NODE_CLASSES}
