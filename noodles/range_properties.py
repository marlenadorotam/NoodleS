"""Range input defaults and live, read-only connected input previews."""
from Qt import QtCore, QtWidgets

from .backend.datatree import MAX_ITEMS, topology
from .backend.domain import DomainValue
from .backend.range import range_steps
from .point_properties import TreeButtons, text
from .widgets import InputStack, NumberField, add_field
from .tree_preview import TreePreview


def format_range_item(item, port):
    if port == "D":
        if not isinstance(item, DomainValue):
            raise ValueError("Range D requires a Domain.")
        return f"[{item.start:.10g} → {item.end:.10g}]"
    return str(range_steps(item))


def range_preview(value, port, mode):
    tree = topology(value, mode)
    # Validate all values, but build a bounded preview only.
    for branch in tree.branches:
        for item in branch.items:
            format_range_item(item, port)
    collection = tree.count != 1 or len(tree.branches) != 1 or tree.branches[0].path != (0,)
    if not collection:
        return format_range_item(tree.branches[0].items[0], port), False, None
    lines = [f"{tree.count} item(s) · {len(tree.branches)} branch(es)"]
    for branch in tree.branches[:3]:
        items = ", ".join(format_range_item(item, port) for item in branch.items[:3]) or "(empty)"
        lines.append("{" + ";".join(map(str, branch.path)) + "}: " + items + (" …" if len(branch.items) > 3 else ""))
    if len(tree.branches) > 3:
        lines.append("…")
    return "\n".join(lines), True, tree


class RangeProperties(QtWidgets.QWidget):
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
        for port, name in (("D", "Domain"), ("N", "Steps")):
            modifier = TreeButtons()
            modifier.changed.connect(lambda mode, p=port: self._modifier(p, mode))
            self.modifiers[port] = modifier
            layout.addWidget(modifier)
            defaults = QtWidgets.QWidget()
            fields = QtWidgets.QVBoxLayout(defaults)
            fields.setContentsMargins(0, 0, 0, 0)
            fields.setSpacing(10)
            for key, label in (("start", "Start"), ("end", "End")) if port == "D" else (("steps", "Steps"),):
                editor = NumberField()
                editor.setDecimals(0 if key == "steps" else 4)
                if key == "steps":
                    editor.setRange(1, MAX_ITEMS - 1)
                editor.setMinimumHeight(36)
                editor.setAccessibleName("Default Range " + label)
                editor.valueChanged.connect(lambda value, p=port, k=key: self._edit(p, k, value))
                if port == "D":
                    add_field(fields, label, editor)
                else:
                    fields.addWidget(editor)
                self.editors[key] = editor
            preview = TreePreview()
            preview.setObjectName("ConnectedInputValue")
            preview.setTextFormat(QtCore.Qt.PlainText)
            preview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard)
            preview.setWordWrap(True)
            preview.setAccessibleName("Connected Range " + name + " data")
            stack = InputStack()
            stack.addWidget(defaults)
            stack.addWidget(preview)
            self.previews[port], self.stacks[port] = preview, stack
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
        state = node.range_state()
        changed_node = self._node_id != node.id
        self._node_id = node.id
        self.modes = dict(state["tree_modes"])
        for port, keys in (("D", ("start", "end")), ("N", ("steps",))):
            self.modifiers[port].set_mode(self.modes.get(port, "none"))
            sources = node.inputs()[port].connected_ports()
            was_connected = self.connected.get(port, False)
            self.connected[port] = bool(sources)
            stack, preview = self.stacks[port], self.previews[port]
            defaults = stack.widget(0)
            defaults.setEnabled(not sources)
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
                    display, collection, tree = range_preview(result.outputs[source.name()], port, self.modes.get(port, "none"))
                except (ValueError, TypeError, OverflowError) as exc:
                    display = "No valid input"
                    tooltip += "\n" + str(exc)
                tooltip += "\nDefault when disconnected: " + (f"[{state['start']:.10g} → {state['end']:.10g}]" if port == "D" else str(state["steps"]))
                if preview.text() != display:
                    preview.setText(display)
                preview.setToolTip(tooltip)
                preview.setAlignment(QtCore.Qt.AlignLeft | (QtCore.Qt.AlignTop if collection else QtCore.Qt.AlignVCenter))
                stack.setCurrentWidget(preview)
            else:
                for key in keys:
                    editor = self.editors[key]
                    blocker = QtCore.QSignalBlocker(editor)
                    if changed_node or was_connected or not editor.hasFocus() or editor.value() != state[key]:
                        editor.setValue(state[key])
                    editor.setToolTip("Used when this input is disconnected")
                    del blocker
                stack.setCurrentWidget(defaults)
            preview.set_tree(tree, lambda item, p=port: format_range_item(item, p))
