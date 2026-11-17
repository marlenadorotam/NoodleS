"""Compact grid nodes share geometry state, Properties, lifecycle and publisher."""
from .curve_nodes import CurveGeometryNode


class GridRectangleNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Grid Rectangle', 'grid_rectangle'


class GridTriangleNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Grid Triangle', 'grid_triangle'


class GridHexagonNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Grid Hexagon', 'grid_hexagon'


class GridRadialNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Grid Radial', 'grid_radial'


GRID_NODE_CLASSES = (GridRectangleNode,GridTriangleNode,GridHexagonNode,GridRadialNode)
