"""Run exact closest-point queries on the existing OCC worker."""
from .curves import xyz
from .datatree import MAX_ITEMS
from .pull import MAX_COMPARISONS, is_attractor
from .point import PointValue


def measure(plan, wanted):
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from serpentine3d.core import geometry as g
    from .moves import geometry_from_wire
    from .scene_curves import materialize

    rows, groups = plan.get('rows'), plan.get('groups')
    if (not isinstance(rows, list) or not isinstance(groups, list) or len(rows) > MAX_ITEMS
            or len(groups) > MAX_ITEMS or any(not isinstance(group, list) for group in groups)
            or sum(map(len, groups)) > MAX_ITEMS):
        raise ValueError('Invalid Pull Point batch.')
    counts = [len(group) for group in groups]
    requests = []
    total = comparisons = 0
    for row in rows:
        points, index = row['points'], row['group']
        if type(index) is not int or not 0 <= index < len(groups) or not isinstance(points, list):
            raise ValueError('Invalid Pull Point branch.')
        total += len(points)
        comparisons += len(points)*counts[index]
        if total > MAX_ITEMS or comparisons > MAX_COMPARISONS or (points and not counts[index]):
            raise ValueError('Invalid Pull Point branch or comparison limit exceeded.')
        requests.append((tuple(xyz(p) for p in points), index))

    compounds, shapes = {}, {}
    budget = [MAX_ITEMS]
    values = []
    for points, index in requests:
        row = []
        values.append(row)
        if not points:
            continue
        if index not in compounds:
            parts = []
            for wire in groups[index]:
                if not wanted():
                    return []
                value = geometry_from_wire(wire, budget=budget)
                if not is_attractor(value):
                    raise ValueError('Pull Point supports Points and Curves as attractors.')
                if value not in shapes:
                    shapes[value] = materialize(value)
                parts.append(shapes[value])
            compounds[index] = g.make_compound(parts)
        for point in points:
            if not wanted():
                return []
            nearest = BRepExtrema_DistShapeShape(g.make_point(point), compounds[index])
            if not nearest.IsDone() or not nearest.NbSolution():
                raise ValueError('OpenCascade could not find a closest point on the attractors.')
            row.append(g.pnt_tuple(nearest.PointOnShape2(1)))
    return values
