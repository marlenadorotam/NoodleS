"""Per-input controls for numeric and vector operators."""
from Qt import QtCore, QtWidgets

from .backend.datatree import MAX_ITEMS
from .backend.expression import pretty_expression
from .backend.math_nodes import MATH_SPECS, math_input_tree
from .point_properties import TreeButtons, text
from .widgets import InputStack, NumberField, add_field
from .tree_preview import TreePreview
from .graph_mapper import GraphMapperControls


class MathProperties(QtWidgets.QWidget):
    edited = QtCore.Signal(str, object)

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._operation = None
        self._body = None
        self._node_id = None

    def _build(self, operation):
        if self._body:
            self.layout().removeWidget(self._body)
            self._body.hide()
            self._body.deleteLater()
        self._operation = operation
        self._body = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self._body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.graph_controls = None
        self.formula = None
        if operation == "expression":
            layout.addWidget(text("PARAMETERS", True))
            self.formula = QtWidgets.QLineEdit()
            self.formula.setAccessibleName("Expression")
            self.formula.setMinimumHeight(36)
            self.formula.setMaxLength(256)
            self.formula.setPlaceholderText("x^2 - y^2")
            self.formula.editingFinished.connect(lambda: self.edited.emit("formula", self.formula.text()))
            add_field(layout, "Expression", self.formula)
            self.formula_preview = text("")
            self.formula_preview.setTextFormat(QtCore.Qt.PlainText)
            self.formula_preview.setWordWrap(True)
            self.formula.textChanged.connect(lambda value: self.formula_preview.setText(pretty_expression(value)))
            layout.addWidget(self.formula_preview)
        if operation == "graph_mapper":
            layout.addWidget(text("PARAMETERS", True))
            self.graph_controls = GraphMapperControls()
            self.graph_controls.changed.connect(lambda config: self.edited.emit("graph_config", config))
            self.graph_controls.edit_started.connect(lambda: self._node.begin_graph_edit())
            self.graph_controls.edit_finished.connect(lambda: self._node.end_graph_edit())
            layout.addWidget(self.graph_controls)
        layout.addWidget(text("INPUTS", True))
        self.modifiers, self.previews, self.stacks, self.editors = {}, {}, {}, {}
        if self.formula is not None:
            self.editors["formula"] = self.formula
        self.connected, self.modes = {}, {}
        for descriptor in MATH_SPECS[operation]["inputs"]:
            port = descriptor.port
            modifier = TreeButtons()
            modifier.changed.connect(lambda mode, p=port: self._modifier(p, mode))
            self.modifiers[port] = modifier
            layout.addWidget(modifier)
            stack = InputStack()
            if descriptor.defaults:
                defaults = QtWidgets.QWidget()
                fields = QtWidgets.QVBoxLayout(defaults)
                fields.setContentsMargins(0, 0, 0, 0)
                fields.setSpacing(10)
                for index, key in enumerate(descriptor.defaults):
                    if descriptor.kind == "boolean":
                        editor = QtWidgets.QCheckBox(descriptor.label)
                        editor.toggled.connect(lambda value, p=port, k=key: self._edit(p, k, value))
                    else:
                        editor = NumberField()
                        editor.setDecimals(0 if key == "count" else 4)
                        if key == "count":
                            editor.setRange(1, MAX_ITEMS)
                        editor.valueChanged.connect(lambda value, p=port, k=key: self._edit(p, k, value))
                    editor.setMinimumHeight(36)
                    editor.setAccessibleName(MATH_SPECS[operation]["name"] + " default " + key)
                    self.editors[key] = editor
                    if descriptor.kind == "domain":
                        add_field(fields, "Start" if index == 0 else "End", editor)
                    else:
                        fields.addWidget(editor)
                stack.addWidget(defaults)
            preview = TreePreview()
            preview.setObjectName("ConnectedInputValue")
            preview.setTextFormat(QtCore.Qt.PlainText)
            preview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard)
            preview.setWordWrap(True)
            preview.setAccessibleName(MATH_SPECS[operation]["name"] + " input " + port)
            stack.addWidget(preview)
            self.previews[port], self.stacks[port] = preview, stack
            add_field(layout, port if descriptor.label == port else port + " · " + descriptor.label, stack)
        self.layout().addWidget(self._body)

    def _modifier(self, port, mode):
        modes = dict(self.modes)
        if mode == "none":
            modes.pop(port, None)
        else:
            modes[port] = mode
        self.edited.emit("tree_modes", modes)

    def _edit(self, port, key, value):
        if not self.connected.get(port):
            self.edited.emit(key, value)

    def show_node(self, node, evaluation, formatter):
        if self._operation != node.OPERATION:
            self._build(node.OPERATION)
        changed_node = self._node_id != node.id
        self._node_id = node.id
        self._node = node
        state = node.math_state()
        if self.formula is not None and (changed_node or not self.formula.hasFocus()):
            self.formula.setText(state["formula"])
        if self.graph_controls:
            self.graph_controls.set_config(state["graph_config"])
        self.modes = dict(state["tree_modes"])
        for descriptor in MATH_SPECS[node.OPERATION]["inputs"]:
            port = descriptor.port
            mode = self.modes.get(port, "none")
            self.modifiers[port].set_mode(mode)
            sources = node.inputs()[port].connected_ports()
            was_connected = self.connected.get(port, False)
            self.connected[port] = bool(sources)
            stack, preview = self.stacks[port], self.previews[port]
            full_tree = None
            if sources:
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
                    tree = math_input_tree(result.outputs[source.name()], descriptor, mode)
                    scalar = tree.count == 1 and len(tree.branches) == 1 and tree.branches[0].path == (0,) and mode == "none"
                    display = formatter(tree.values()[0] if scalar else tree)
                    full_tree = None if scalar else tree
                except (ValueError, TypeError, OverflowError) as exc:
                    display = "No valid input"
                    tooltip += "\n" + str(exc)
                preview.setText(display)
                preview.setToolTip(tooltip)
                stack.setCurrentWidget(preview)
            elif descriptor.defaults:
                for key in descriptor.defaults:
                    editor = self.editors[key]
                    blocker = QtCore.QSignalBlocker(editor)
                    if descriptor.kind == "boolean":
                        editor.setChecked(state[key])
                    elif changed_node or was_connected or not editor.hasFocus() or editor.value() != state[key]:
                        editor.setValue(state[key])
                    del blocker
                stack.setCurrentWidget(stack.widget(0))
            else:
                preview.setText("Connect input " + port + ".")
                preview.setToolTip(descriptor.label + " is required.")
                stack.setCurrentWidget(preview)
            preview.set_tree(full_tree, formatter)
