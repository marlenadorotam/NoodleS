"""Recover native, still-regular grids from their versioned ParametricObject."""
from dataclasses import replace
import math

from .datatree import DataTree
from .curves import PlaneValue, add, cross, dot, scale, sub, unit
from .grids import GridValue, grid_object_from_wire
from .grid_topology import topology


GRID_REFERENCES = 'NoodleS.grid_references'
INVALID = 'The grid geometry no longer matches its saved topology. Select an intact native grid.'


def children(shape):
    from OCP.TopoDS import TopoDS_Iterator
    iterator = TopoDS_Iterator(shape)
    while iterator.More():
        yield iterator.Value()
        iterator.Next()


def inspect_part(shape, value):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_EDGE, TopAbs_VERTEX
    from OCP.TopoDS import TopoDS
    from serpentine3d.core.geometry import pnt_tuple

    if shape.ShapeType() != TopAbs_COMPOUND:
        raise ValueError(INVALID)
    vertices, edges, _, centres = topology(value.kind, *value.extents)
    xy = [pos for pos, _ in (*vertices.values(), *centres.values())]
    parts = list(children(shape))
    if len(parts) != len(xy) + len(edges):
        raise ValueError(INVALID)
    observed = []
    for item in parts[:len(xy)]:
        if item.ShapeType() != TopAbs_VERTEX:
            raise ValueError(INVALID)
        observed.append(pnt_tuple(BRep_Tool.Pnt_s(TopoDS.Vertex_s(item))))
    x0, y0 = xy[0]
    i = max(range(1, len(xy)), key=lambda i: math.dist(xy[0], xy[i]))
    dx, dy = xy[i][0]-x0, xy[i][1]-y0
    j = max(range(1, len(xy)), key=lambda j: abs(dx*(xy[j][1]-y0)-dy*(xy[j][0]-x0)))
    ex, ey = xy[j][0]-x0, xy[j][1]-y0
    det = dx*ey - dy*ex
    if abs(det) <= 1e-12:
        raise ValueError(INVALID)
    vi, vj = sub(observed[i], observed[0]), sub(observed[j], observed[0])
    x = scale(sub(scale(vi, ey), scale(vj, dy)), 1/det)
    y = scale(sub(scale(vj, dx), scale(vi, ex)), 1/det)
    sx, sy = math.hypot(*x), math.hypot(*y)
    ux, uy = unit(x), unit(y)
    if abs(dot(ux, uy)) > 1e-7 or (value.kind != 'grid_rectangle' and not math.isclose(sx, sy, rel_tol=1e-7)):
        raise ValueError(INVALID)
    origin = sub(observed[0], add(scale(x, x0), scale(y, y0)))
    target = replace(value, frame=PlaneValue(origin, ux, cross(ux, uy)),
                     spacing=(sx, sy) if value.kind == 'grid_rectangle' else (sx,))
    tolerance = max(1e-7, max(sx, sy)*1e-8)
    if any(math.dist(p, target.frame.at(u*sx, v*sy)) > tolerance for p, (u, v) in zip(observed, xy)):
        raise ValueError(INVALID)
    by_role = dict(zip(vertices, observed))
    for item, (role, (a, b, _, circular)) in zip(parts[len(xy):], edges.items()):
        if item.ShapeType() != TopAbs_EDGE:
            raise ValueError(INVALID)
        adaptor = BRepAdaptor_Curve(TopoDS.Edge_s(item))
        if adaptor.GetType() != (GeomAbs_Circle if circular else GeomAbs_Line):
            raise ValueError(INVALID)
        first, last = adaptor.FirstParameter(), adaptor.LastParameter()
        ends = tuple(pnt_tuple(adaptor.Value(t)) for t in (first, last))
        expected = by_role[a], by_role[b]
        if min(max(math.dist(p, q) for p, q in zip(ends, pair)) for pair in (expected, expected[::-1])) > tolerance:
            raise ValueError(INVALID)
        if circular:
            _, ring, sector = role.split(':')
            radius, angle = int(ring)*sx, math.tau*(int(sector)+.5)/value.extents[1]
            mid = target.frame.at(radius*math.cos(angle), radius*math.sin(angle))
            if math.dist(mid, pnt_tuple(adaptor.Value((first+last)/2))) > tolerance:
                raise ValueError(INVALID)
    # Use the saved values exactly when the grid is still at the saved pose.
    if (math.dist(value.frame.origin, target.frame.origin) <= tolerance and
            math.dist(value.frame.axis_x, target.frame.axis_x) < 1e-9 and
            math.dist(value.frame.normal, target.frame.normal) < 1e-9 and
            all(abs(a-b) <= tolerance for a,b in zip(value.spacing, target.spacing))):
        return value
    return target


def inspect_grid(shape, manifest, primitive):
    from OCP.TopAbs import TopAbs_COMPOUND
    if (not isinstance(manifest, dict) or manifest.get('kind') not in ('grids', 'transforms')
            or not hasattr(shape, 'ShapeType') or shape.ShapeType() != TopAbs_COMPOUND):
        raise ValueError('Select grids created by NoodleS or a native NoodleS grid command.')
    if manifest['kind'] == 'grids':
        model = grid_object_from_wire(manifest)
    else:
        from .moves import RigidValue, TranslatedValue, object_from_wire
        model = object_from_wire(manifest)
        def base_grid(part):
            key = part.key
            while isinstance(part, (TranslatedValue, RigidValue)):
                part = part.source
            if not isinstance(part, GridValue):
                raise ValueError('Select intact regular grid geometry.')
            return replace(part, key=key)
        model = replace(model, kind='grids', parts=DataTree(tuple(
            replace(b, items=tuple(base_grid(v) for v in b.items)) for b in model.parts.branches)))
        grid_object_from_wire(model.to_wire())
    recipes = model.parts.values()
    parts = list(children(shape))
    if not recipes or len(parts) != len(recipes) or any(v.kind != primitive for v in recipes):
        raise ValueError('The selected object does not contain matching grids.')
    native_parts = iter(parts)
    return replace(model, parts=DataTree(tuple(
        replace(branch, items=tuple(inspect_part(next(native_parts), value) for value in branch.items))
        for branch in model.parts.branches)))


def grid_records(model, obj, capture_key):
    return [{'key': capture_key+'/'+v.key, 'id': obj.id, 'name': obj.name,
             'path': list(branch.path), 'recipe': replace(v, key=capture_key+'/'+v.key).to_wire()}
            for branch in model.parts.branches for v in branch.items]
