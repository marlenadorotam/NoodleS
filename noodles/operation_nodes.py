"""Compact surface operations, sharing geometry state, Properties and lifecycle."""
from .curve_nodes import CurveGeometryNode


class PullPointNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Pull Point', 'pull_point'


class CurveDomainNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Curve Domain', 'curve_domain'


class CurveLengthNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Curve Length', 'curve_length'


class ProjectNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Project', 'project'


class SectionNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Section', 'section'


class ContourNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Contour', 'contour'


class ScaleNonUniformNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Scale Non-Uniform', 'scale_non_uniform'


class SurfaceIsocurvesNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Surface Isocurves', 'surface_isocurves'


class CurveCurveNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Curve–Curve', 'curve_curve'


class RegionBooleanNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Region Boolean', 'region_boolean'


class AreaNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Area', 'area'


class VolumeNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Volume', 'volume'


class DivideCurveNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Divide Curve', 'divide_curve'


class DivideByLengthNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Divide by Length', 'divide_by_length'


class ShatterNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Shatter', 'shatter'


class FlipCurveNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Flip Curve', 'flip_curve'


class MoveSeamNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Move Seam', 'move_seam'


class FrameNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Frame', 'frame'


class PerpFramesNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Perp Frames', 'perp_frames'


class CurveCurvatureNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Curve Curvature', 'curve_curvature'


class CurveClosestPointNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Curve Closest Point', 'curve_closest_point'


class SortAlongCurveNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Sort Along Curve', 'sort_along_curve'


class EvaluateCurveNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Evaluate Curve', 'evaluate_curve'


class PointInCurveNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Point In Curve', 'point_in_curve'


class SurfaceDomainNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Surface Domain', 'surface_domain'


class DeconstructDomain2Node(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Deconstruct Domain²', 'deconstruct_domain2'


class DivideDomain2Node(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Divide Domain²', 'divide_domain2'


class ReparameterizeSurfaceNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Reparameterize Surface', 'reparameterize_surface'


class SurfaceEvaluateNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Surface Evaluate', 'surface_evaluate'


class SurfaceClosestPointNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Surface Closest Point', 'surface_closest_point'


class LoftOptionsNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Loft Options', 'loft_options'


class PipeNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Pipe', 'pipe'


class ExtrudeNode(CurveGeometryNode):
    NODE_NAME,OPERATION='Extrude','extrude'


class RevolveNode(CurveGeometryNode):
    NODE_NAME,OPERATION='Revolve','revolve'


class LoftNode(CurveGeometryNode):
    NODE_NAME,OPERATION='Loft','loft'


class PlanarSurfaceNode(CurveGeometryNode):
    NODE_NAME,OPERATION='Planar Surface','planar_surface'


class EdgeSurfaceNode(CurveGeometryNode):
    NODE_NAME,OPERATION='Edge Surface','edge_surface'


class SurfaceFromPointsNode(CurveGeometryNode):
    NODE_NAME,OPERATION='Surface from Points','surface_from_points'


class CapHolesNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Cap Holes', 'cap_holes'


class PatchNode(CurveGeometryNode):
    NODE_NAME,OPERATION='Patch','patch'


class Sweep2Node(CurveGeometryNode):
    NODE_NAME,OPERATION='Sweep 2 Rails','sweep2'


class Sweep1Node(CurveGeometryNode):
    NODE_NAME,OPERATION='Sweep 1 Rail','sweep1'


class BiRailSweepNode(CurveGeometryNode):
    NODE_NAME,OPERATION='BiRail Sweep','birail_sweep'


class MoveNode(CurveGeometryNode):
    NODE_NAME,OPERATION='Move','move'


class MoveGHNode(CurveGeometryNode):
    NODE_NAME,OPERATION='Move GH','move_gh'


class RotateNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Rotate', 'rotate'


class ScaleNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Scale', 'scale'


class OrientNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Orient', 'orient'


class MirrorNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Mirror', 'mirror'


class BooleanUnionParametricNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Boolean Union Parametric', 'boolean_union_parametric'


class BooleanDifferenceParametricNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Boolean Difference Parametric', 'boolean_difference_parametric'


class BooleanIntersectionParametricNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Boolean Intersection Parametric', 'boolean_intersection_parametric'


class BooleanSplitParametricNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Boolean Split Parametric', 'boolean_split_parametric'


class BooleanUnionNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Boolean Union', 'boolean_union'


class BooleanDifferenceNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Boolean Difference', 'boolean_difference'


class BooleanIntersectionNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Boolean Intersection', 'boolean_intersection'


class BooleanSplitNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Boolean Split', 'boolean_split'


class JoinNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Join', 'join'


class BrepJoinNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Brep Join', 'brep_join'


class IsotrimNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Isotrim', 'isotrim'


class UVPanelsNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'UV Panels', 'uv_panels'


class ExplodeNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Explode', 'explode'


class SplitNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Split', 'split'


class TrimNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Trim', 'trim'


class OffsetNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Offset', 'offset'


class FilletEdgeNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Fillet Edge', 'fillet_edge'


class FilletNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Fillet', 'fillet'


class FilletParametricNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Fillet Parametric', 'fillet_parametric'


class ArrayNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Array', 'array'


class ArrayPolarNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Array Polar', 'array_polar'


class ArrayAlongCurveNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Array Along Curve', 'array_along_curve'


class ObjectsOnPointsNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Objects on Points', 'objects_on_points'


class Populate2DNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Populate 2D', 'populate_2d'


class PopulateGeometryNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Populate Geometry', 'populate_geometry'


class MapSurfaceNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Map Surface', 'map_surface'


class BoundingBoxNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Bounding Box', 'bounding_box'


class SurfaceMorphNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Surface Morph', 'surface_morph'


class SurfaceBoxNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Surface Box', 'surface_box'


class BoxMorphNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Box Morph', 'box_morph'


class DelaunayNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Delaunay', 'delaunay'


class VoronoiNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Voronoi', 'voronoi'


class HexagonTilingNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Hexagon Tiling', 'hexagon_tiling'


class PenroseP2Node(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Penrose P2', 'penrose_p2'


class DeconstructBrepNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Deconstruct Brep', 'deconstruct_brep'


class MeshEdgesNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Mesh Edges', 'mesh_edges'


class DeconstructMeshNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Deconstruct Mesh', 'deconstruct_mesh'


class FaceBoundariesNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Face Boundaries', 'face_boundaries'


class DeconstructFaceNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Deconstruct Face', 'deconstruct_face'


class TriangleFaceNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Triangle Face', 'triangle_face'


class FaceNormalsNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Face Normals', 'face_normals'


class DelaunayMeshNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Delaunay Mesh', 'delaunay_mesh'


class ConstructMeshNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Construct Mesh', 'construct_mesh'


class BrepToMeshNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Brep to Mesh', 'brep_to_mesh'


class MeshJoinNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Mesh Join', 'mesh_join'


class WeldMeshNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Weld Mesh', 'weld_mesh'


class FaceNeighboursNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Face Neighbours', 'face_neighbours'


class PlaneSurfaceNode(CurveGeometryNode):
    __identifier__ = 'NoodleS.Operations'
    NODE_NAME, OPERATION = 'Plane Surface', 'plane_surface'


class BracedGrid1DStructureNode(CurveGeometryNode):
    NODE_NAME, OPERATION = 'Braced Grid 1-D Structure', 'braced_grid_1d'


OPERATION_NODE_CLASSES=(PullPointNode,CurveDomainNode,CurveLengthNode,ProjectNode,SectionNode,ContourNode,CurveCurveNode,RegionBooleanNode,
    ScaleNonUniformNode,SurfaceIsocurvesNode,
    AreaNode,VolumeNode,DivideCurveNode,DivideByLengthNode,ShatterNode,FlipCurveNode,MoveSeamNode,
    FrameNode,PerpFramesNode,CurveCurvatureNode,
    CurveClosestPointNode,SortAlongCurveNode,EvaluateCurveNode,PointInCurveNode,LoftOptionsNode,PipeNode,ExtrudeNode,RevolveNode,LoftNode,PlanarSurfaceNode,EdgeSurfaceNode,PatchNode,SurfaceFromPointsNode,CapHolesNode,
    SurfaceDomainNode,DeconstructDomain2Node,DivideDomain2Node,ReparameterizeSurfaceNode,SurfaceEvaluateNode,SurfaceClosestPointNode,
    Sweep1Node,Sweep2Node,BiRailSweepNode,MoveNode,MoveGHNode,RotateNode,ScaleNode,MirrorNode,OrientNode,
    BooleanUnionParametricNode,BooleanDifferenceParametricNode,BooleanIntersectionParametricNode,BooleanSplitParametricNode,
    BooleanUnionNode,BooleanDifferenceNode,BooleanIntersectionNode,BooleanSplitNode,JoinNode,BrepJoinNode,IsotrimNode,UVPanelsNode,
    ExplodeNode,SplitNode,TrimNode,OffsetNode,
    FilletEdgeNode,FilletNode,FilletParametricNode,ArrayNode,ArrayPolarNode,ArrayAlongCurveNode,ObjectsOnPointsNode,
    Populate2DNode,PopulateGeometryNode,MapSurfaceNode,BoundingBoxNode,SurfaceMorphNode,SurfaceBoxNode,BoxMorphNode,
    DelaunayNode,VoronoiNode,HexagonTilingNode,PenroseP2Node,DeconstructBrepNode,MeshEdgesNode,DeconstructMeshNode,DelaunayMeshNode,
    ConstructMeshNode,BrepToMeshNode,MeshJoinNode,WeldMeshNode,FaceNeighboursNode,
    DeconstructFaceNode,TriangleFaceNode,FaceNormalsNode,FaceBoundariesNode,PlaneSurfaceNode,BracedGrid1DStructureNode)
