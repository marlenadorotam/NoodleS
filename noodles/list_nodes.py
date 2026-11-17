"""Compact, read-only data operators and the Boolean input."""
from .curve_nodes import CurveGeometryNode


class BoolNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Inputs'
    NODE_NAME, OPERATION = 'Bool', 'bool'


class MergeNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Merge', 'merge'


class ListItemNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'List Item', 'list_item'


class ListLengthNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'List Length', 'list_length'


class ShiftListNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Shift List', 'shift_list'


class SortListNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Sort List', 'sort_list'


class SortPointsNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Sort Points', 'sort_points'


class TreeBranchNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Tree Branch', 'tree_branch'


class ReplacePathsNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Replace Paths', 'replace_paths'


class TextNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Inputs'
    NODE_NAME, OPERATION = 'Text', 'text'


class ValueListNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Inputs'
    NODE_NAME, OPERATION = 'Value List', 'value_list'


class ReadCsvNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Read CSV', 'read_csv'


class CrossReferenceNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Cross Reference', 'cross_reference'


class SimplifyNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Simplify', 'simplify'


class FlipMatrixNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Flip Matrix', 'flip_matrix'


class TreeViewerNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Tree Viewer', 'tree_viewer'


class DuplicateDataNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Duplicate Data', 'duplicate_data'


class DispatchNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Dispatch', 'dispatch'


class WeaveNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Weave', 'weave'


class DeconstructPointNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Math'
    NODE_NAME, OPERATION = 'Deconstruct Point', 'deconstruct_point'


class RandomNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Math'
    NODE_NAME, OPERATION = 'Random', 'random'


class CullDuplicatePointsNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Cull Duplicate Points', 'cull_duplicate_points'


class ClosestPointsNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Data'
    NODE_NAME, OPERATION = 'Closest Points', 'closest_points'


LIST_NODE_CLASSES = (BoolNode, MergeNode, ListItemNode, ListLengthNode, ShiftListNode, SortListNode, SortPointsNode,
                     TreeBranchNode, ReplacePathsNode, TextNode, ValueListNode, ReadCsvNode,
                     CrossReferenceNode, SimplifyNode,
                     FlipMatrixNode, TreeViewerNode, DuplicateDataNode, DispatchNode, WeaveNode,
                     DeconstructPointNode, RandomNode, CullDuplicatePointsNode, ClosestPointsNode)
