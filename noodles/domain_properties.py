"""Domain defaults and per-input topology controls, matching Point Properties."""
from Qt import QtCore, QtWidgets

from .widgets import InputStack, NumberField, add_field
from .point_properties import TreeButtons, input_preview, text
from .backend.datatree import topology
from .tree_preview import TreePreview


class DomainProperties(QtWidgets.QWidget):
    edited = QtCore.Signal(str, object)

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(text("INPUTS", True))
        self.editors, self.previews, self.stacks, self.modifiers = {}, {}, {}, {}
        self.connected, self.modes = {}, {}
        self._node_id = None
        for port, name, key in (("A", "Start", "start"), ("B", "End", "end")):
            modifier = TreeButtons()
            modifier.changed.connect(lambda mode, p=port: self._modifier(p, mode))
            self.modifiers[port] = modifier
            layout.addWidget(modifier)
            editor = NumberField()
            editor.setDecimals(4)
            editor.setMinimumHeight(36)
            editor.setAccessibleName("Default Domain " + name)
            editor.valueChanged.connect(lambda value, p=port, k=key: self._edit(p, k, value))
            preview = TreePreview()
            preview.setObjectName("ConnectedInputValue")
            preview.setTextFormat(QtCore.Qt.PlainText)
            preview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard)
            preview.setWordWrap(True)
            preview.setAccessibleName("Connected Domain " + name + " data")
            stack = InputStack()
            stack.addWidget(editor)
            stack.addWidget(preview)
            self.editors[port], self.previews[port], self.stacks[port] = editor, preview, stack
            add_field(layout, port + " · " + name, stack)

    def _edit(self, port, key, value):
        if not self.connected.get(port):
            self.edited.emit(key, value)

    def _modifier(self, port, mode):
        modes = dict(self.modes)
        if mode == "none":
            modes.pop(port, None)
        else:
            modes[port] = mode
        self.edited.emit("tree_modes", modes)

    def show_node(self, node, evaluation=None):
        state = node.domain_state()
        changed_node = self._node_id != node.id
        self._node_id = node.id
        self.modes = dict(state["tree_modes"])
        for port, key in (("A", "start"), ("B", "end")):
            self.modifiers[port].set_mode(self.modes.get(port, "none"))
            sources = node.inputs()[port].connected_ports()
            was_connected = self.connected.get(port, False)
            self.connected[port] = bool(sources)
            editor, preview, stack = self.editors[port], self.previews[port], self.stacks[port]
            blocker = QtCore.QSignalBlocker(editor)
            editor.setEnabled(not sources)
            tree = None
            if sources:
                source = sources[0]
                result = evaluation.results.get(source.node().id) if evaluation else None
                tooltip = f"Connected to {source.node().name()} · {source.name()}\nEdit the source node to change this input."
                collection = False
                try:
                    if result is None:
                        raise ValueError("Waiting for input data.")
                    if result.error:
                        raise ValueError(result.error)
                    if source.name() not in result.outputs:
                        raise ValueError("Connected output is unavailable.")
                    mode = self.modes.get(port, "none")
                    incoming = topology(result.outputs[source.name()], mode)
                    scalar, display = input_preview(incoming, mode)
                    collection = display is not None
                    tree = incoming if collection else None
                    if display is None:
                        display = format(scalar, ".15g")
                except (ValueError, TypeError, OverflowError) as exc:
                    display = "No valid input"
                    tooltip += "\n" + str(exc)
                tooltip += "\nDefault when disconnected: " + format(state[key], ".10g")
                if preview.text() != display:
                    preview.setText(display)
                preview.setAlignment(QtCore.Qt.AlignLeft | (QtCore.Qt.AlignTop if collection else QtCore.Qt.AlignVCenter))
                preview.setToolTip(tooltip)
                stack.setCurrentWidget(preview)
            else:
                if changed_node or was_connected or not editor.hasFocus():
                    editor.setValue(state[key])
                editor.setToolTip("Used when this input is disconnected")
                stack.setCurrentWidget(editor)
            preview.set_tree(tree)
            del blocker
