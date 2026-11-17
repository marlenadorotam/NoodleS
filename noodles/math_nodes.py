"""Compact Qt nodes for numeric and vector operations."""
import copy
from Qt import QtGui

from .backend.math_nodes import MATH_SPECS, math_property_names, normalize_math_state
from .node_layout import CompactNode


class MathStateCommand(QtGui.QUndoCommand):
    def __init__(self, node, state, name):
        super().__init__("Change " + node.NODE_NAME + " " + name)
        self.node, self.before, self.after = node, node.math_state(), state
        self.gesture = getattr(node, "_graph_gesture", None) if name == "graph_config" else None

    def id(self):
        return 0x4E474D if self.gesture is not None else -1

    def mergeWith(self, other):
        if (not isinstance(other, MathStateCommand) or other.node is not self.node
                or self.gesture is None or other.gesture is not self.gesture):
            return False
        self.after = other.after
        self.setObsolete(self.before == self.after)
        return True

    def redo(self):
        self.node._apply_math_state(self.after)

    def undo(self):
        self.node._apply_math_state(self.before)


class NumericMathNode(CompactNode):
    __identifier__ = "NoodleS.Math"

    def __init__(self):
        super().__init__()
        spec = MATH_SPECS[self.OPERATION]
        for descriptor in spec["inputs"]:
            description = descriptor.label + (" · Number or Vector" if descriptor.kind == "number_or_vector" else "")
            self.add_input(descriptor.port).view.setToolTip(description)
        for port in spec["outputs"]:
            self.add_output(port)
        for key, value in normalize_math_state(self.OPERATION, {}).items():
            if key not in spec.get("widget_properties", ()):
                self.create_property(key, value)

    def math_state(self):
        keys = math_property_names(self.OPERATION)
        return copy.deepcopy({key: self.get_property(key) for key in keys})

    def set_property(self, name, value, push_undo=True):
        if name not in math_property_names(self.OPERATION):
            return super().set_property(name, value, push_undo)
        before = self.math_state()
        state = normalize_math_state(self.OPERATION, {**before, name: value})
        if before == state:
            return
        if self.graph and push_undo:
            self.graph.undo_stack().push(MathStateCommand(self, state, name))
        else:
            self._apply_math_state(state)

    def _apply_math_state(self, state):
        before = self.math_state()
        for key, value in state.items():
            self.model.set_property(key, copy.deepcopy(value))
        for key in MATH_SPECS[self.OPERATION].get("widget_properties", ()):
            self.get_widget(key).set_value(state[key])
        for descriptor in MATH_SPECS[self.OPERATION]["inputs"]:
            mode = state["tree_modes"].get(descriptor.port, "none")
            description = descriptor.label + (" · Number or Vector" if descriptor.kind == "number_or_vector" else "")
            self.inputs()[descriptor.port].view.setToolTip(description +
                (" · " + mode.title() if mode != "none" else ""))
        if self.graph:
            for key, value in state.items():
                if before[key] != value:
                    self.graph.property_changed.emit(self, key, value)

    def update(self):
        self._apply_math_state(normalize_math_state(self.OPERATION, self.math_state()))
        super().update()


class ExpressionNode(NumericMathNode):
    NODE_NAME, OPERATION = "Expression", "expression"


class SubtractionNode(NumericMathNode):
    NODE_NAME, OPERATION = "Subtraction", "subtraction"


class DivisionNode(NumericMathNode):
    NODE_NAME, OPERATION = "Division", "division"


class EqualityNode(NumericMathNode):
    NODE_NAME, OPERATION = "Equality", "equality"


class LargerThanNode(NumericMathNode):
    NODE_NAME, OPERATION = "Larger Than", "larger_than"


class SumNode(NumericMathNode):
    NODE_NAME, OPERATION = "Sum", "sum"


class AverageNode(NumericMathNode):
    NODE_NAME, OPERATION = "Average", "average"


class MaximumNode(NumericMathNode):
    NODE_NAME, OPERATION = "Maximum", "maximum"


class MinimumNode(NumericMathNode):
    NODE_NAME, OPERATION = "Minimum", "minimum"


class SineNode(NumericMathNode):
    NODE_NAME, OPERATION = "Sine", "sine"


class SquareNode(NumericMathNode):
    NODE_NAME, OPERATION = "Square", "square"


class PowerNode(NumericMathNode):
    NODE_NAME, OPERATION = "Power", "power"


class CrossProductNode(NumericMathNode):
    NODE_NAME, OPERATION = "Cross Product", "cross_product"


class SeriesNode(NumericMathNode):
    NODE_NAME, OPERATION = "Series", "series"


class BoundsNode(NumericMathNode):
    NODE_NAME, OPERATION = "Bounds", "bounds"


class DeconstructDomainNode(NumericMathNode):
    NODE_NAME, OPERATION = "Deconstruct Domain", "deconstruct_domain"


class RemapNumbersNode(NumericMathNode):
    NODE_NAME, OPERATION = "Remap Numbers", "remap_numbers"


class VectorNode(NumericMathNode):
    NODE_NAME, OPERATION = "Vector", "vector"


class Vector2PtNode(NumericMathNode):
    NODE_NAME, OPERATION = "Vector 2Pt", "vector_2pt"


class UnitVectorNode(NumericMathNode):
    NODE_NAME, OPERATION = "Unit Vector", "unit_vector"


class UnitXNode(NumericMathNode):
    NODE_NAME, OPERATION = "Unit X", "unit_x"


class UnitYNode(NumericMathNode):
    NODE_NAME, OPERATION = "Unit Y", "unit_y"


class UnitZNode(NumericMathNode):
    NODE_NAME, OPERATION = "Unit Z", "unit_z"


class AmplitudeNode(NumericMathNode):
    NODE_NAME, OPERATION = "Amplitude", "amplitude"


class ReverseVectorNode(NumericMathNode):
    NODE_NAME, OPERATION = "Reverse Vector", "reverse_vector"


class GraphMapperNode(NumericMathNode):
    NODE_NAME, OPERATION = "Graph Mapper", "graph_mapper"

    def __init__(self):
        super().__init__()
        from .graph_mapper import GraphMapperWidget
        self._graph_gesture = None
        widget = GraphMapperWidget(self.view)
        self.add_custom_widget(widget)
        widget.plot.edit_started.connect(self.begin_graph_edit)
        widget.plot.edit_finished.connect(self.end_graph_edit)

    def begin_graph_edit(self):
        self._graph_gesture = object()

    def end_graph_edit(self):
        self._graph_gesture = None


MATH_NODE_CLASSES = (ExpressionNode, SubtractionNode, DivisionNode, EqualityNode, LargerThanNode, MinimumNode, SumNode,
                     AverageNode, MaximumNode, SineNode, SquareNode,
                     PowerNode, CrossProductNode,
                     SeriesNode, BoundsNode, DeconstructDomainNode, RemapNumbersNode, VectorNode, Vector2PtNode,
                     UnitVectorNode, UnitXNode, UnitYNode, UnitZNode, AmplitudeNode, ReverseVectorNode, GraphMapperNode)
