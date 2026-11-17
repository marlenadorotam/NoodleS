"""Exact closed cell boundaries, including circular arcs, without OCC."""
from dataclasses import dataclass
import math
from .curves import CurveValue, curve_from_wire, line, arc


@dataclass(frozen=True)
class WireValue(CurveValue):
    segments: tuple = ()
    reversed_edges: tuple = ()

    def __post_init__(self):
        if (not isinstance(self.key,str) or not self.key or len(self.key)>256 or self.kind != 'wire'
                or self.closed is not True or not 3 <= len(self.segments) <= 6
                or len(self.reversed_edges) != len(self.segments)
                or any(type(flag) is not bool for flag in self.reversed_edges)
                or any(not isinstance(s,CurveValue) or s.kind not in ('line','arc') for s in self.segments)):
            raise ValueError('Invalid grid cell boundary.')
        starts, ends = [], []
        for s, reverse in zip(self.segments,self.reversed_edges):
            starts.append(s.points[-1] if reverse else s.points[0])
            ends.append(s.points[0] if reverse else s.points[-1])
        if any(math.dist(a,b)>1e-7 for a,b in zip(ends,starts[1:]+starts[:1])):
            raise ValueError('Cell boundary is not closed.')
        object.__setattr__(self,'points',tuple(starts))

    @property
    def length(self):
        return sum(s.length for s in self.segments)

    def to_wire(self):
        return {'key':self.key,'kind':'wire','segments':[s.to_wire() for s in self.segments],
                'reversed':list(self.reversed_edges)}


def wire_from_wire(data):
    segments = data.get('segments')
    if not isinstance(segments,list) or not 3<=len(segments)<=6 or any(not isinstance(s,dict) or s.get('kind') not in ('line','arc') for s in segments):
        raise ValueError('Invalid cell segments.')
    reverse = data.get('reversed')
    if not isinstance(reverse,list):
        raise ValueError('Invalid cell orientations.')
    return WireValue(data.get('key'),'wire',(),closed=True,segments=tuple(curve_from_wire(s) for s in segments),reversed_edges=tuple(reverse))
