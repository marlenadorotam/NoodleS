"""Indexed tessellation transport and typed cell contours shared by algorithms."""
from .curves import arc, curve_object_from_wire, polyline, xyz


TESSELLATION = 'tessellation'
MAPPED_TESSELLATION = 'mapped_tessellation'
MAX_CELLS = 4096
MAX_VERTICES = 8192
MAX_CONTOUR_VERTICES = 512


def indexed_cells(parts):
    vertices, indices, cells = [], {}, []
    for part in parts:
        contour = []
        for point in part.points:
            if point not in indices:
                indices[point] = len(vertices)
                vertices.append(point)
            contour.append(indices[point])
        cells.append({'key': part.key, 'indices': contour})
    return vertices, cells


def model_wire(model, header):
    vertices, cells = indexed_cells(model.parts.values())
    if model.kind == 'penrose_p2':
        for part, cell in zip(model.parts.values(), cells):
            if part.kind == 'arc':
                cell['arc'] = True
    values = iter(cells)
    return {**header, 'vertices': [list(v) for v in vertices],
            'branches': [{'path': list(b.path), 'parts': [next(values) for _ in b.items]}
                         for b in model.parts.branches]}


def mapped_model_wire(model, header):
    parts = model.parts.values()
    vertices, cells = indexed_cells(part.sources[0] for part in parts)
    surfaces, index = [], {}
    for part, cell in zip(parts, cells):
        curve, *pair = part.sources
        refs = []
        for surface in pair:
            if surface not in index:
                index[surface] = len(surfaces)
                surfaces.append(surface.to_wire())
            refs.append(index[surface])
        cell.update(key=part.key, curve_key=curve.key, surfaces=refs)
    values = iter(cells)
    return {**header, 'vertices': [list(v) for v in vertices], 'surfaces': surfaces,
            'branches': [{'path': list(b.path), 'parts': [next(values) for _ in b.items]}
                         for b in model.parts.branches]}


def contours(vertices, cells):
    if not isinstance(vertices, list) or len(vertices) > MAX_VERTICES:
        raise ValueError('Invalid tessellation vertex table.')
    if not isinstance(cells, list) or len(cells) > MAX_CELLS:
        raise ValueError('Invalid tessellation cells.')
    points = tuple(xyz(point) for point in vertices)
    return tuple(cell_points(points, cell) for cell in cells)


def cell_points(points, cell):
    if (not isinstance(cell, list) or not 3 <= len(cell) <= MAX_CONTOUR_VERTICES or
            any(type(i) is not int or not 0 <= i < len(points) for i in cell) or
            len(set(cell)) != len(cell)):
        raise ValueError('Invalid tessellation contour indices.')
    return tuple(points[i] for i in cell)


def model_from_wire(data):
    kind = data.get('kind')
    vertices = data.get('vertices')
    if not isinstance(vertices, list) or len(vertices) > MAX_VERTICES:
        raise ValueError('Invalid tessellation vertex table.')
    points = tuple(xyz(point) for point in vertices)
    budget = MAX_CELLS

    def decode(record):
        nonlocal budget
        budget -= 1
        if budget < 0 or not isinstance(record, dict):
            raise ValueError('Invalid tessellation cell budget.')
        contour = cell_points(points, record.get('indices'))
        if kind == 'penrose_p2' and record.get('arc') is True:
            if len(contour) != 3:
                raise ValueError('Invalid Penrose arc.')
            return arc(record.get('key'), *contour)
        return polyline(record.get('key'), contour, True)

    return curve_object_from_wire(data, decoder=decode, kind=kind)


def mapped_model_from_wire(data):
    from .moves import geometry_from_wire
    from .operations import OperationValue

    vertices, raw_surfaces = data.get('vertices'), data.get('surfaces')
    if (not isinstance(vertices, list) or len(vertices) > MAX_VERTICES
            or not isinstance(raw_surfaces, list) or len(raw_surfaces) > 2*MAX_CELLS):
        raise ValueError('Invalid mapped tessellation tables.')
    points = tuple(xyz(p) for p in vertices)
    budget = [10000]
    surfaces = [geometry_from_wire(surface, budget=budget) for surface in raw_surfaces]
    def decode(record):
        budget[0] -= 2
        if budget[0] < 0 or not isinstance(record, dict):
            raise ValueError('Invalid mapped tessellation recipe budget.')
        pair = record.get('surfaces')
        if (not isinstance(pair, list) or len(pair) != 2 or
                any(type(i) is not int or not 0 <= i < len(surfaces) for i in pair)):
            raise ValueError('Invalid mapped tessellation surfaces.')
        curve = polyline(record.get('curve_key'), cell_points(points, record.get('indices')), True)
        return OperationValue(record.get('key'), 'map_surface', (curve, *(surfaces[i] for i in pair)))
    model = curve_object_from_wire(data, decoder=decode, kind=MAPPED_TESSELLATION)
    if model.parts.count > MAX_CELLS:
        raise ValueError('Mapped tessellation exceeds the contour limit.')
    return model
