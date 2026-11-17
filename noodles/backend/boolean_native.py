"""Boolean results built on the existing OCC worker, without scene side effects."""
from functools import reduce


def split_solids(shapes, direction):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_SOLID
    from serpentine3d.core import geometry as g

    target, *cutters = shapes
    if g.shape_kind(target) != 'solid' or not BRepCheck_Analyzer(target).IsValid():
        raise ValueError('Boolean Split needs a valid solid target.')
    if any(g.shape_kind(c) not in ('curve', 'surface', 'solid') or not BRepCheck_Analyzer(c).IsValid()
           for c in cutters):
        raise ValueError('Boolean Split needs valid curve, surface or solid cutters.')
    # Native Split may rebuild tolerances on its arguments.
    target = g.copy_shape(target)
    parts = tuple(g.split_shape(target, [g.copy_shape(c) for c in cutters], direction=direction))
    if any(p.ShapeType() != TopAbs_SOLID or not BRepCheck_Analyzer(p).IsValid() or g.volume(p) <= 1e-12
           for p in parts):
        raise ValueError('Boolean Split did not return valid solid pieces.')
    return parts


def boolean_shape(operation, shapes, *, solid_only=True):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopTools import TopTools_ListOfShape
    from serpentine3d.core import geometry as g
    from .grid_reference_native import children

    allowed = (TopAbs_SOLID,) if solid_only else (TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL)

    def pieces(shape):
        if shape.ShapeType() in allowed:
            return [shape]
        if shape.ShapeType() != TopAbs_COMPOUND:
            raise ValueError('Boolean operand or result contains an unsupported shape.')
        return [part for child in children(shape) for part in pieces(child)]

    def checked_parts(shape):
        parts = pieces(shape)
        if not parts:
            detail = 'solid volume' if solid_only else 'solid or surface geometry'
            raise ValueError(f'Boolean operation produced no {detail}.')
        if not BRepCheck_Analyzer(shape).IsValid() or any(
                (g.volume(part) if part.ShapeType() == TopAbs_SOLID else g.surface_area(part)) <= 1e-12
                for part in parts):
            raise ValueError('Boolean operation requires valid, nondegenerate geometry.')
        return parts

    def build(cls, left, right):
        # Source BREP handles can also be in the shared resolver cache.
        args, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
        args.Append(left)
        tools.Append(right)
        task = cls()
        task.SetArguments(args)
        task.SetTools(tools)
        task.SetNonDestructive(True)
        task.Build()
        result = task.Shape() if task.IsDone() else None
        if result is None or result.IsNull():
            raise ValueError('OpenCascade could not complete the Boolean operation.')
        return result

    for shape in shapes:
        checked_parts(shape)
    if operation == 'Union':
        result = reduce(lambda a, b: build(BRepAlgoAPI_Fuse, a, b), shapes)
    elif operation == 'Difference':
        cutter = reduce(lambda a, b: build(BRepAlgoAPI_Fuse, a, b), shapes[1:])
        result = build(BRepAlgoAPI_Cut, shapes[0], cutter)
    elif operation == 'Intersection':
        result = reduce(lambda a, b: build(BRepAlgoAPI_Common, a, b), shapes)
    else:
        raise ValueError('Unknown Boolean operation.')
    parts = checked_parts(result)
    return parts[0] if len(parts) == 1 else result
