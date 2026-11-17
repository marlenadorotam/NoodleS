"""Properties for Point. Canvas nodes remain native and compact."""
from Qt import QtCore, QtWidgets

from .widgets import InputStack, NumberField, add_field
from .tree_preview import TreePreview
from .backend.datatree import finite, topology


def input_preview(tree, mode):
    """Bounded preview of this input, before cross-axis matching/broadcast."""
    for branch in tree.branches:
        for item in branch.items:
            finite(item)
    if (mode == "none" and len(tree.branches) == 1
            and tree.branches[0].path == (0,) and tree.count == 1):
        return tree.branches[0].items[0], None
    lines = [f"{tree.count} item(s) · {len(tree.branches)} branch(es)"]
    for branch in tree.branches[:3]:
        path = ";".join(map(str, branch.path))
        values = ", ".join(format(v, ".10g") for v in branch.items[:3]) or "(empty)"
        lines.append("{" + path + "}: " + values + (" …" if len(branch.items) > 3 else ""))
    if len(tree.branches) > 3:
        lines.append("…")
    return None, "\n".join(lines)


def text(value, section=False):
    widget = QtWidgets.QLabel(value)
    if section:
        widget.setObjectName("SectionLabel")
    return widget


class TreeButtons(QtWidgets.QWidget):
    changed = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("SliderMode")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.mode = "none"
        self.buttons = {}
        for mode in ("graft", "flatten"):
            button = QtWidgets.QPushButton(mode.title())
            button.setCheckable(True)
            button.setToolTip("One branch per item" if mode == "graft" else "Combine all branches into one list")
            button.clicked.connect(lambda checked=False, m=mode: self._click(m))
            layout.addWidget(button)
            self.buttons[mode] = button

    def _click(self, mode):
        selected = "none" if self.mode == mode else mode
        self.set_mode(selected)
        self.changed.emit(selected)

    def set_mode(self, mode):
        self.mode = mode
        for key, button in self.buttons.items():
            button.setChecked(key == mode)


class PointProperties(QtWidgets.QWidget):
    edited = QtCore.Signal(str, object)
    set_reference = QtCore.Signal()

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(text("PARAMETERS", True))
        source = QtWidgets.QWidget()
        source.setObjectName("SliderMode")
        row = QtWidgets.QHBoxLayout(source)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(3)
        self.sources = {}
        for mode in ("generate", "reference"):
            button = QtWidgets.QPushButton(mode.title())
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, m=mode: self._source(m))
            row.addWidget(button)
            self.sources[mode] = button
        layout.addWidget(source)
        self.generate = QtWidgets.QWidget()
        generated = QtWidgets.QVBoxLayout(self.generate)
        generated.setContentsMargins(0, 0, 0, 0)
        generated.setSpacing(10)
        generated.addWidget(text("INPUTS", True))
        self.editors, self.modifiers = {}, {}
        self.input_stacks, self.previews = {}, {}
        self.connected = {}
        self._node_id = None
        self.modes = {}
        for axis in ("X", "Y", "Z"):
            modifier = TreeButtons()
            modifier.changed.connect(lambda mode, a=axis: self._modifier(a, mode))
            self.modifiers[axis] = modifier
            generated.addWidget(modifier)
            editor = NumberField()
            editor.setDecimals(4)
            editor.setMinimumHeight(36)
            editor.setAccessibleName("Default Point " + axis)
            editor.valueChanged.connect(lambda value, a=axis: self._coordinate(a, value))
            self.editors[axis] = editor
            preview = TreePreview()
            preview.setObjectName("ConnectedInputValue")
            preview.setTextFormat(QtCore.Qt.PlainText)
            preview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard)
            preview.setWordWrap(True)
            preview.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            preview.setAccessibleName("Connected Point " + axis + " data")
            self.previews[axis] = preview
            stack = InputStack()
            stack.addWidget(editor)
            stack.addWidget(preview)
            self.input_stacks[axis] = stack
            add_field(generated, axis, stack)
        self.reference = QtWidgets.QWidget()
        reference = QtWidgets.QVBoxLayout(self.reference)
        reference.setContentsMargins(0, 0, 0, 0)
        reference.setSpacing(10)
        reference.addWidget(text("REFERENCE", True))
        self.capture = QtWidgets.QPushButton("Set reference points")
        self.capture.setMinimumHeight(36)
        self.capture.clicked.connect(self.set_reference.emit)
        reference.addWidget(self.capture)
        header = QtWidgets.QHBoxLayout()
        header.addWidget(text("Points"))
        modifier = TreeButtons()
        modifier.changed.connect(lambda mode: self._modifier("Points", mode))
        self.modifiers["Points"] = modifier
        header.addWidget(modifier, 1)
        reference.addLayout(header)
        self.reference_count = text("")
        reference.addWidget(self.reference_count)
        layout.addWidget(self.reference)
        layout.addWidget(self.generate)
        self.status = text("")
        self.status.setObjectName("SecondaryText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._pending_status = None
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(180)
        self._status_timer.timeout.connect(self._apply_status)

    def reset_status(self):
        self._status_timer.stop()
        self._node_id = None
        self._pending_status = None

    def _apply_status(self):
        if self._pending_status is not None and self.status.text() != self._pending_status:
            self.status.setText(self._pending_status)

    def _show_status(self, node, changed_node):
        value = node.scene_status
        if changed_node or getattr(node, "scene_status_error", False):
            self._status_timer.stop()
            self._pending_status = value
            self._apply_status()
        elif value != self._pending_status:
            self._pending_status = value
            if value == self.status.text():
                self._status_timer.stop()
            else:
                # Presentation only: coalesce short prepare/complete cycles.
                # A sustained update appears after 180 ms; errors bypass it.
                self._status_timer.start()

    def _source(self, mode):
        for key, button in self.sources.items():
            button.setChecked(key == mode)
        self.edited.emit("mode", mode)

    def _modifier(self, name, mode):
        modes = dict(self.modes)
        if mode == "none":
            modes.pop(name, None)
        else:
            modes[name] = mode
        self.edited.emit("tree_modes", modes)

    def _coordinate(self, axis, value):
        if not self.connected.get(axis):
            self.edited.emit(axis.lower(), value)

    def _show_input(self, node, axis, state, evaluation, changed_node):
        editor = self.editors[axis]
        preview = self.previews[axis]
        stack = self.input_stacks[axis]
        sources = node.inputs()[axis].connected_ports()
        connected = bool(sources)
        was_connected = self.connected.get(axis, False)
        self.connected[axis] = connected
        blocker = QtCore.QSignalBlocker(editor)
        editor.setEnabled(not connected)
        editor.setAccessibleName(("Connected" if connected else "Default") + " Point " + axis)
        display, collection, tree = None, False, None
        if connected:
            source = sources[0]
            result = evaluation.results.get(source.node().id) if evaluation else None
            tooltip = f"Connected to {source.node().name()} · {source.name()}\nEdit the source node to change this input."
            try:
                if result is None:
                    raise ValueError("Waiting for input data.")
                if result.error:
                    raise ValueError(result.error)
                if source.name() not in result.outputs:
                    raise ValueError("Connected output is unavailable.")
                mode = self.modes.get(axis, "none")
                incoming = topology(result.outputs[source.name()], mode)
                scalar, display = input_preview(incoming, mode)
                if display is None:
                    display = format(scalar, ".15g")
                else:
                    collection = True
                    tree = incoming
            except (ValueError, TypeError, OverflowError) as exc:
                display = "No valid input"
                tooltip += "\n" + str(exc)
            tooltip += "\nDefault when disconnected: " + format(state[axis.lower()], ".10g")
        elif state["mode"] == "reference":
            editor.setEnabled(False)
            tooltip = "Live referenced coordinate. Move the point in Serpentine, or connect this axis to drive it."
            result = evaluation.results.get(node.id) if evaluation else None
            if result and not result.error and axis in result.outputs:
                incoming = topology(result.outputs[axis])
                scalar, display = input_preview(incoming, "none")
                if display is None:
                    display = format(scalar, ".15g")
                else:
                    collection = True
                    tree = incoming
            else:
                display = "No valid reference"
        else:
            tooltip = "Used when this input is disconnected"
            if changed_node or was_connected or not editor.hasFocus():
                editor.setValue(state[axis.lower()])
        if display is None:
            stack.setCurrentWidget(editor)
        else:
            if preview.text() != display:
                preview.setText(display)
            preview.setAlignment(QtCore.Qt.AlignLeft | (QtCore.Qt.AlignTop if collection else QtCore.Qt.AlignVCenter))
            stack.setCurrentWidget(preview)
        editor.setToolTip(tooltip)
        preview.setToolTip(tooltip)
        preview.set_tree(tree)
        del blocker

    def show_node(self, node, evaluation=None):
        state = node.point_state()
        changed_node = node.id != self._node_id
        self._node_id = node.id
        self.modes = dict(state["tree_modes"])
        for mode, button in self.sources.items():
            button.setChecked(state["mode"] == mode)
        self.generate.setVisible(True)
        self.reference.setVisible(state["mode"] == "reference")
        for axis in self.editors:
            self._show_input(node, axis, state, evaluation, changed_node)
        for name, modifier in self.modifiers.items():
            modifier.set_mode(self.modes.get(name, "none"))
        self.reference_count.setText(f"{len(state['references'])} referenced point(s)")
        self._show_status(node, changed_node)
