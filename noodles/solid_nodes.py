"""3D primitives reuse the same compact geometry state, Properties and publication."""
from .curve_nodes import CurveGeometryNode


class BoxNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Box', 'box'


class BoxFromCenterNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Box from Center', 'box_from_center'


class PyramidNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Pyramid', 'pyramid'


class SphereNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Sphere', 'sphere'


class EllipsoidNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Ellipsoid', 'ellipsoid'


class TorusNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Torus', 'torus'


class CylinderNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Cylinder', 'cylinder'


class ConeNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Cone', 'cone'


class TruncatedConeNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Truncated Cone', 'truncated_cone'


class ParaboloidNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Paraboloid', 'paraboloid'


SOLID_NODE_CLASSES = (BoxNode, BoxFromCenterNode, PyramidNode, SphereNode, EllipsoidNode, TorusNode, CylinderNode,
                      ConeNode, TruncatedConeNode, ParaboloidNode)
