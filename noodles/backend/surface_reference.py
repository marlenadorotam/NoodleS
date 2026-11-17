"""Exact native BREP snapshots carried as immutable graph values."""
from dataclasses import dataclass

from .curves import xyz

SURFACE_REFERENCE_OPS = frozenset(('planar_surface', 'edge_surface', 'loft'))
ARCHIVED_REFERENCE_OPS = SURFACE_REFERENCE_OPS | {'curves', 'mesh'}
SURFACE_REFERENCE_KIND = 'surface_reference'
MAX_REFERENCE_ARCHIVES = 600_000  # ASCII characters, summed per bridge response.
MAX_REFERENCE_OBJECTS = 64


@dataclass(frozen=True)
class SurfaceReferenceValue:
    key: str
    brep: str
    native_kind: str
    edge_count: int
    normal: tuple | None = None
    kind = SURFACE_REFERENCE_KIND

    def __post_init__(self):
        if not isinstance(self.key, str) or not 0 < len(self.key) <= 256:
            raise ValueError('Invalid surface reference key.')
        if not isinstance(self.brep, str) or not 0 < len(self.brep) <= MAX_REFERENCE_ARCHIVES or not self.brep.isascii():
            raise ValueError('Invalid or oversized surface archive.')
        if self.native_kind not in ('curve', 'surface', 'solid', 'compound') or type(self.edge_count) is not int or self.edge_count < 0:
            raise ValueError('Invalid surface reference measurements.')
        if self.normal is not None:
            object.__setattr__(self, 'normal', xyz(self.normal))

    def to_wire(self):
        result = {'key': self.key, 'kind': self.kind, 'brep': self.brep,
                  'native_kind': self.native_kind, 'edge_count': self.edge_count}
        if self.normal is not None:
            result['normal'] = list(self.normal)
        return result


def surface_reference_from_wire(data):
    if not isinstance(data, dict) or data.get('kind') != SURFACE_REFERENCE_KIND:
        raise ValueError('Invalid native surface reference.')
    return SurfaceReferenceValue(data.get('key'), data.get('brep'), data.get('native_kind'),
                                 data.get('edge_count'), data.get('normal'))


def surface_reference_request(state):
    """Binding reads need durable keys, never a copy of the previous geometry snapshot."""
    return {**{key: state[key] for key in ('project_uuid', 'node_uuid', 'primitive', 'mode')},
            'references': [{'key': ref['key']} for ref in state['references']]}
