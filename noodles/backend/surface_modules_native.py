"""OpenCascade factories shared by graph nodes and Serpentine commands."""
from .surface_modules import (ISO_DIRECTIONS, MAX_ISO_LOCI, SURFACE_ISOCURVES, scale_factors, scale_matrix,
                              scale_point)


MAX_ISO_PIECES = 2500


def nonuniform_scale(shape, frame, factors):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.gp import gp_GTrsf, gp_Mat, gp_XYZ
    from serpentine3d.core import geometry as g
    from .curves import dot

    factors = scale_factors(factors)
    kind = g.shape_kind(shape)
    if kind == 'point' and shape.ShapeType() == g.occ.VERTEX:
        return g.make_point(scale_point(tuple(map(float, g.point_coords(shape))), frame, factors))
    if kind not in ('point', 'curve', 'surface', 'solid', 'compound'):
        raise ValueError('Scale Non-Uniform requires native point, curve, surface or solid geometry.')
    if factors[0] == factors[1] == factors[2]:
        return g.scale(shape, frame.origin, factors[0])
    matrix = scale_matrix(frame, factors)
    translation = tuple(origin - dot(row, frame.origin)
                        for origin, row in zip(frame.origin, matrix, strict=True))
    transform = gp_GTrsf()
    transform.SetVectorialPart(gp_Mat(*(value for row in matrix for value in row)))
    transform.SetTranslationPart(gp_XYZ(*translation))
    # The native helper cleans triangulation in place. Never give it the
    # source or the handle cached by the graph resolver.
    result = g._gtransform(g.copy_shape(shape), transform)
    if result.IsNull() or not BRepCheck_Analyzer(result).IsValid():
        raise ValueError('OpenCascade returned invalid scaled geometry.')
    return result


def _trimmed_face(shape, index):
    from OCP.BRep import BRep_Tool
    from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from serpentine3d.core import geometry as g
    from .surface_grid_native import trim_curves
    from .surface_uv_native import select_face, uv_bounds

    face = select_face(g.faces_of(shape), index)
    bounds = uv_bounds(face)
    classifier = BRepTopAdaptor_FClass2d(face, 1e-9)
    return BRep_Tool.Surface_s(face), bounds, trim_curves(face), lambda point: (
        classifier.Perform(point) in (TopAbs_IN, TopAbs_ON))


def _iso_curve(surface, axis, fixed):
    return surface.VIso(fixed) if axis == 'U' else surface.UIso(fixed)


def _make_edge(curve, start, end):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.GCPnts import GCPnts_AbscissaPoint
    from OCP.GeomAdaptor import GeomAdaptor_Curve
    from serpentine3d.core import geometry as g

    if curve is None or GCPnts_AbscissaPoint.Length_s(GeomAdaptor_Curve(curve, start, end), start, end, 1e-9) <= g.tol():
        return None
    builder = BRepBuilderAPI_MakeEdge(curve, start, end)
    if not builder.IsDone() or not BRepCheck_Analyzer(builder.Edge()).IsValid():
        raise ValueError('OpenCascade could not construct the trimmed isocurve.')
    return builder.Edge()


def isocurve_edge(shape, index, span):
    from OCP.BRep import BRep_Tool
    from serpentine3d.core import geometry as g
    from .surface_uv_native import select_face

    axis, fixed, start, end = span
    face = select_face(g.faces_of(shape), index)
    edge = _make_edge(_iso_curve(BRep_Tool.Surface_s(face), axis, fixed), start, end)
    if edge is None:
        raise ValueError('The isocurve span became degenerate. Recompute the graph.')
    return edge


def isocurves(prepared, row):
    from .surface_grid_native import clipped_intervals
    from .surface_uv_native import _exposed_bounds, _parameter

    surface, bounds, trims, classify = prepared
    exposed = _exposed_bounds(bounds, row)
    direction = row.get('direction')
    if type(direction) is not int or not 0 <= direction < len(ISO_DIRECTIONS):
        raise ValueError('Invalid isocurve direction.')
    for index, axis in enumerate(('U', 'V')):
        if direction not in (0, index + 1):
            continue
        fixed_axis = 1 - index
        offset = 2 * fixed_axis
        fixed, _ = _parameter(row.get('uv'[fixed_axis]), bounds[offset:offset+2],
                              exposed[offset:offset+2], 'UV'[fixed_axis])
        start, end = bounds[2*index:2*index+2]
        curve = _iso_curve(surface, axis, fixed)
        for a, b in clipped_intervals(trims, classify, fixed_axis, fixed, start, end):
            edge = _make_edge(curve, a, b)
            if edge is not None:
                yield (axis, fixed, a, b), edge


def measure_isocurves(plan, wanted, cache):
    from .curves import is_curve_recipe
    from .datatree import MAX_ITEMS
    from .moves import geometry_from_wire
    from .scene_curves import materialize
    from .surface_uv import is_uv_geometry

    sources, rows = plan.get('sources'), plan.get('rows')
    if (not isinstance(sources, list) or not isinstance(rows, list)
            or not 1 <= len(sources) <= len(rows) <= MAX_ISO_LOCI):
        raise ValueError('Invalid Surface Isocurves request.')
    budget = [MAX_ITEMS]
    values = [geometry_from_wire(source, budget=budget) for source in sources]
    if any(not is_uv_geometry(source) or is_curve_recipe(source) for source in values):
        raise ValueError('Surface Isocurves requires geometry with native faces.')
    shapes, faces, prepared_edges, results = {}, {}, {}, []

    def resolve(value):
        if value not in shapes:
            shapes[value] = materialize(value, resolve=resolve, topology_cache=cache)
        return shapes[value]

    count = 0
    for row in rows:
        if not wanted():
            return []
        if not isinstance(row, dict):
            raise ValueError('Invalid isocurve query.')
        index, face = row.get('source'), row.get('face')
        if type(index) is not int or not 0 <= index < len(values) or type(face) is not int:
            raise ValueError('Invalid isocurve source or face index.')
        if (index, face) not in faces:
            faces[index, face] = _trimmed_face(resolve(values[index]), face)
        spans = []
        key = SURFACE_ISOCURVES, values[index], face
        edges = prepared_edges.setdefault(key, {})
        for span, edge in isocurves(faces[index, face], row):
            count += 1
            if count > MAX_ISO_PIECES:
                raise ValueError(f'Surface Isocurves exceeds {MAX_ISO_PIECES:,} trimmed curves.')
            spans.append(span)
            edges.setdefault(span, edge)
        results.append(spans)
    if cache is not None:
        for key, edges in prepared_edges.items():
            cache[key] = edges
            cache.move_to_end(key)
        while len(cache) > 128 or sum(map(len, cache.values())) > MAX_ITEMS:
            cache.popitem(last=False)
    return results


def register_commands(ctx):
    from .curves import PlaneValue
    from .operation_native import native_job
    from .splines import integer

    req = ctx.requests()

    @ctx.command('scalelocal', mutates=False, label='Scale Non-Uniform')
    def scale_local(command):
        sources = yield req.SelectReq('Select geometry to copy and scale', kinds=('point', 'curve', 'surface', 'solid', 'compound'),
                                      min_count=1, max_count=240)
        origin = yield req.PointReq('Base point')
        frame = PlaneValue(tuple(map(float, origin)), tuple(map(float, command.cplane.xdir)),
                           tuple(map(float, command.cplane.normal)))
        factors = []
        for axis in 'XYZ':
            factors.append((yield req.NumberReq(f'Local {axis} factor', default=1.)))
        native_job(ctx, command, sources, lambda shapes: [nonuniform_scale(s, frame, factors) for s in shapes],
                   'Scale Non-Uniform')

    @ctx.command('surfaceisocurves', mutates=False, label='Surface Isocurves')
    def extract(command):
        source = yield req.SelectReq('Select the surface or BREP', kinds=('surface', 'solid', 'compound'),
                                     min_count=1, max_count=1)
        face = integer((yield req.NumberReq('Face index (0 = Auto)', default=0.)), 'Face Index', 0, 10000)
        direction = yield req.OptionReq('Directions', options=list(ISO_DIRECTIONS), default='Both')
        mode = yield req.OptionReq('Parameter space', options=['Normalized', 'Native'], default='Normalized')
        row = {'direction': ISO_DIRECTIONS.index(direction), 'normalized': mode == 'Normalized'}
        for axis in 'uv':
            if direction != 'Along ' + axis.upper():
                row[axis] = yield req.NumberReq(f'Fixed {axis.upper()} coordinate', default=.5)

        def build(shapes):
            result = [edge for _, edge in isocurves(_trimmed_face(shapes[0], face), row)]
            if not result:
                raise ValueError('No isocurves remain inside the selected face.')
            return result

        native_job(ctx, command, source, build, 'Surface Isocurves')
