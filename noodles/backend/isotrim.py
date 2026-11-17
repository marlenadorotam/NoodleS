"""DataTree contract for a native, trim-aware UV subset."""
import hashlib

from .curves import CurveInput, input_tree
from .datatree import Branch, DataTree, MAX_ITEMS
from .domain import DomainValue
from .surface_uv import FACE_INDEX, SURFACE, SurfaceUvView, _match, checked_uv_domain, surface_selection


ISOTRIM_SPEC = {
    'class': 'IsotrimNode', 'name': 'Isotrim', 'primary': 'S', 'outputs': ('S',),
    'inputs': (SURFACE, CurveInput('D', 'Trim Domain²', 'domain2', optional=True),
               CurveInput('U', 'Trim U Domain', 'uv_domain', optional=True),
               CurveInput('V', 'Trim V Domain', 'uv_domain', optional=True), FACE_INDEX),
}


def checked_intervals(values):
    if not isinstance(values, (list, tuple)) or len(values) != 4:
        raise ValueError('Isotrim needs increasing U and V intervals.')
    u = checked_uv_domain(DomainValue(*values[:2]))
    v = checked_uv_domain(DomainValue(*values[2:]))
    return u.start, u.end, v.start, v.end


def evaluate(state, inputs):
    from .operations import OperationValue

    has_domain = 'D' in inputs
    uv_ports = {'U', 'V'} & inputs.keys()
    if (has_domain and uv_ports) or (not has_domain and len(uv_ports) != 2):
        raise ValueError('Connect Domain² at D or two Domains at U and V.')
    trees = [input_tree(inputs.get(d.port, state['parameters'].get(d.port)), d,
                        state['tree_modes'].get(d.port, 'none'), d.port not in inputs)
             for d in ISOTRIM_SPEC['inputs'] if not d.optional or d.port in inputs]
    branches, complexity = [], 0
    for path, rows in _match(*trees):
        values, occurrences = [], {}
        for (surface, *intervals, face), provenance in rows:
            source, face = surface_selection(surface, face)
            u, v = (intervals[0].u, intervals[0].v) if has_domain else intervals
            view = surface.domain if isinstance(surface, SurfaceUvView) else None
            repeat = occurrences.get(provenance, 0)
            occurrences[provenance] = repeat + 1
            key = hashlib.sha256(repr((path, provenance, repeat)).encode()).hexdigest()[:24]
            part = OperationValue(key, 'isotrim', (source,), uv_trim=(u.start, u.end, v.start, v.end),
                                  uv_view=(view.u.start, view.u.end, view.v.start, view.v.end) if view else (),
                                  face_index=face)
            complexity += part.complexity
            if complexity > MAX_ITEMS:
                raise ValueError('Isotrim exceeds the 10,000-recipe budget.')
            values.append(part)
        branches.append(Branch(path, tuple(values), tuple(v.key for v in values)))
    return {'S': DataTree(tuple(branches))}
