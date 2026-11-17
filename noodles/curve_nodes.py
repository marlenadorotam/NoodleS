"""Compact Generate/Reference nodes sharing the universal geometry publisher."""
import copy
import uuid
from Qt import QtGui

from .backend.geometry import GEOMETRY_SPECS, normalize_geometry_state
from .node_layout import CompactNode


class CurveStateCommand(QtGui.QUndoCommand):
    def __init__(self, node, state, name):
        super().__init__('Change '+node.NODE_NAME+' '+name)
        self.node, self.before, self.after = node, node.curve_state(), state

    def redo(self):
        self.node._apply_curve_state(self.after)

    def undo(self):
        self.node._apply_curve_state(self.before)


class CurveGeometryNode(CompactNode):
    __identifier__ = 'NoodleS.Geometry'

    def __init__(self):
        super().__init__()
        spec = GEOMETRY_SPECS[self.OPERATION]
        for descriptor in spec['inputs']:
            self.add_input(descriptor.port).view.setToolTip(descriptor.label)
        for port in spec['outputs']:
            self.add_output(port).view.setToolTip({
                'C': 'Curve', 'V': ('Interpolation point branches (Generate only)' if self.OPERATION == 'interpcurve' else 'Control points / vertices'),
                'CP': 'Native control points (computed by OCC)',
                'D': 'Degree', 'Cl': 'Closed', 'Per': 'Periodic', 'L': 'Length', 'Count': 'Curve count',
            }.get(port, port))
        for name, value in normalize_geometry_state(self.OPERATION, {'node_uuid': str(uuid.uuid4())}).items():
            self.create_property(name, value)
        self.reference_error = 'Waiting for Serpentine reference data.'
        self.scene_status, self.scene_status_error = 'Not published', False
        self.parametric_object = None
        self.curve_details = {}  # Exact derived values returned by the native worker; never graph edits.

    def curve_state(self):
        return copy.deepcopy({key: self.get_property(key) for key in
                              ('mode', 'primitive', 'project_uuid', 'node_uuid', 'tree_modes', 'parameters', 'references')})

    def set_property(self, name, value, push_undo=True):
        if name not in ('mode', 'project_uuid', 'node_uuid', 'tree_modes', 'parameters', 'references'):
            return super().set_property(name, value, push_undo)
        before = self.curve_state()
        state = normalize_geometry_state(self.OPERATION, {**before, name: value})
        if before == state:
            return
        if self.graph and push_undo:
            self.graph.undo_stack().push(CurveStateCommand(self, state, name))
        else:
            self._apply_curve_state(state)

    def _apply_curve_state(self, state):
        before = self.curve_state()
        for name, value in state.items():
            self.model.set_property(name, copy.deepcopy(value))
        for descriptor in GEOMETRY_SPECS[self.OPERATION]['inputs']:
            mode = state['tree_modes'].get(descriptor.port, 'none')
            label = descriptor.label
            self.inputs()[descriptor.port].view.setToolTip(label + (' · '+mode.title() if mode != 'none' else ''))
        if self.graph:
            for name, value in state.items():
                if before[name] != value:
                    self.graph.property_changed.emit(self, name, value)

    def update(self):
        self._apply_curve_state(normalize_geometry_state(self.OPERATION, self.curve_state()))
        super().update()


class CircleNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Circle', 'circle'


class EllipseNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Ellipse', 'ellipse'


class RectangleNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Rectangle', 'rectangle'


class LineNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Line', 'line'


class ArcNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Arc', 'arc'


class ArcCenterNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Arc from Center', 'arc_center'


class PolylineNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Polyline', 'polyline'


class CurveNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Curve', 'curve'


class InterpCurveNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'InterpCurve', 'interpcurve'


class CurvesNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Curves', 'curves'


class MeshNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Mesh', 'mesh'


CURVE_NODE_CLASSES = (CircleNode, EllipseNode, RectangleNode, LineNode, PolylineNode, ArcNode, ArcCenterNode,
                      CurveNode, InterpCurveNode, CurvesNode, MeshNode)
