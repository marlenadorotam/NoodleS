"""Viewport helpers share compact port layout and input Properties."""
from NodeGraphQt import NodeBaseWidget
from Qt import QtCore, QtWidgets

from .curve_nodes import CurveGeometryNode
from .node_layout import CompactNode
from .widgets import S3D_ACTIVE_COLOR


class VectorPreviewNode(CurveGeometryNode):
    NODE_NAME, OPERATION='Vector Preview','vector_preview'


class PlaneNormalNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Math'
    NODE_NAME, OPERATION = 'Plane Normal', 'plane_normal'


class ConstructPlaneNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Math'
    NODE_NAME, OPERATION = 'Construct Plane', 'construct_plane'


class DeconstructPlaneNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Math'
    NODE_NAME, OPERATION = 'Deconstruct Plane', 'deconstruct_plane'


class PlaneFitNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Math'
    NODE_NAME, OPERATION = 'Plane Fit', 'plane_fit'


class PointCylindricalNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Point Cylindrical', 'point_cylindrical'


class XYPlaneNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Math'
    NODE_NAME, OPERATION = 'Plane XY', 'xy_plane'


class YZPlaneNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Math'
    NODE_NAME, OPERATION = 'Plane YZ', 'yz_plane'


class XZPlaneNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Math'
    NODE_NAME, OPERATION = 'Plane XZ', 'xz_plane'


class PlanePreviewNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Plane Preview', 'plane_preview'


class ReparameterizeSurfacePreviewNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Reparameterize Surface Preview', 'surface_uv_preview'


class GradientNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Math'
    NODE_NAME, OPERATION = 'Gradient', 'gradient'


class TextTagNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.VisualHelpers'
    NODE_NAME, OPERATION = 'Text Tag', 'text_tag'


class DimensionNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.VisualHelpers'
    NODE_NAME, OPERATION = 'Dimension', 'dimension'


class HideNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.VisualHelpers'
    NODE_NAME, OPERATION = 'Hide', 'hide'


class CadViewportButton(NodeBaseWidget):
    requested = QtCore.Signal()

    def __init__(self, parent):
        super().__init__(parent, name='cad_view_button', label='')
        self.button = QtWidgets.QPushButton()
        self.button.setFixedSize(110, 26)
        self.button.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: #e3e7ed; border: 1px solid #46515e;
                           border-radius: 4px; }}
            QPushButton[cadActive="true"] {{ background: {S3D_ACTIVE_COLOR}; color: white; }}
            QPushButton:enabled:hover {{ border-color: #657484; }}
            QPushButton:disabled {{ color: #929eac; }}
        """)
        self.button.clicked.connect(self.requested.emit)
        self.set_custom_widget(self.button)
        self.show_state(None, False, 'Connect to Serpentine3D.')

    def show_state(self, enabled, pending, tooltip):
        active = enabled is True
        if self.button.property('cadActive') != active:
            self.button.setProperty('cadActive', active)
            style = self.button.style()
            style.unpolish(self.button)
            style.polish(self.button)
            self.button.update()
        self.button.setText('Applying…' if pending else 'Disable CAD View' if enabled else 'Enable CAD View')
        self.button.setEnabled(enabled is not None and not pending)
        self.button.setToolTip(tooltip)

    def get_value(self):
        return None  # CAD View is session state, independent of the saved graph.

    def set_value(self, value):
        pass


class CadViewportNode(CompactNode):
    __identifier__ = 'NoodleS.VisualHelpers'
    NODE_NAME, OPERATION = 'CadViewport', 'cad_viewport'

    def __init__(self):
        super().__init__()
        control = CadViewportButton(self.view)
        self.add_custom_widget(control)
        group = control.widget()
        # Replace NodeGraphQt's asymmetric group-box insets for this unlabeled control.
        group.setStyleSheet('QGroupBox { background: transparent; border: 0; margin: 0; padding: 0; font-size: 8pt; }')
        padding = 4
        group.layout().setContentsMargins(0, padding, 0, padding)
        group.setFixedSize(control.button.size() + QtCore.QSize(0, 2 * padding))
        self.view.draw_node()


PREVIEW_NODE_CLASSES = (VectorPreviewNode, PlaneNormalNode, ConstructPlaneNode, DeconstructPlaneNode, PlaneFitNode,
                        PointCylindricalNode, XYPlaneNode, YZPlaneNode, XZPlaneNode, PlanePreviewNode,
                        ReparameterizeSurfacePreviewNode, GradientNode, TextTagNode, DimensionNode, HideNode,
                        CadViewportNode)
