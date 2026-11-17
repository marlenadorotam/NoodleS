"""Shared typed input previews and local topology for arithmetic nodes."""
from Qt import QtCore, QtWidgets

from .backend.arithmetic import arithmetic_tree
from .point_properties import TreeButtons, text
from .widgets import add_field
from .tree_preview import TreePreview


class ArithmeticProperties(QtWidgets.QWidget):
    edited = QtCore.Signal(str, object)

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(text("INPUTS", True))
        self.modifiers, self.previews, self.modes = {}, {}, {}
        for port in ("A", "B"):
            modifier = TreeButtons()
            modifier.changed.connect(lambda mode, p=port: self._modifier(p, mode))
            self.modifiers[port] = modifier
            layout.addWidget(modifier)
            preview = TreePreview()
            preview.setObjectName("ConnectedInputValue")
            preview.setTextFormat(QtCore.Qt.PlainText)
            preview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard)
            preview.setWordWrap(True)
            preview.setAccessibleName("Arithmetic input " + port)
            self.previews[port] = preview
            add_field(layout, port, preview)

    def _modifier(self, port, mode):
        modes = dict(self.modes)
        if mode == "none":
            modes.pop(port, None)
        else:
            modes[port] = mode
        self.edited.emit("tree_modes", modes)

    def show_node(self, node, evaluation, formatter):
        self.modes = dict(node.arithmetic_state()["tree_modes"])
        for port in ("A", "B"):
            mode = self.modes.get(port, "none")
            self.modifiers[port].set_mode(mode)
            sources = node.inputs()[port].connected_ports()
            tooltip = "Connect Number, Vector or Point data."
            display = "Connect input " + port + "."
            full_tree = None
            if sources:
                source = sources[0]
                tooltip = f"Connected to {source.node().name()} · {source.name()}\nEdit the source node to change this input."
                result = evaluation.results.get(source.node().id) if evaluation else None
                try:
                    if result is None:
                        raise ValueError("Waiting for input data.")
                    if result.error:
                        raise ValueError(result.error)
                    if source.name() not in result.outputs:
                        raise ValueError("Connected output is unavailable.")
                    value = result.outputs[source.name()]
                    tree, kind = arithmetic_tree(value, mode)
                    scalar = tree.count == 1 and len(tree.branches) == 1 and tree.branches[0].path == (0,) and mode == "none"
                    display = formatter(tree.values()[0] if scalar else tree)
                    full_tree = None if scalar else tree
                    tooltip += "\nData type: " + (kind.title() if kind else "Empty")
                except (ValueError, TypeError, OverflowError) as exc:
                    display = "No valid input"
                    tooltip += "\n" + str(exc)
            self.previews[port].setText(display)
            self.previews[port].setToolTip(tooltip)
            self.previews[port].set_tree(full_tree, formatter)
