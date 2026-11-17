"""Universal deferred geometry owner. No Qt, OCC or scene objects here."""
from dataclasses import dataclass

from .datatree import DataTree


@dataclass(frozen=True)
class ParametricObject:
    project_uuid: str
    node_uuid: str
    parts: DataTree
    mode: str = "generate"
    source_refs: tuple = ()
    kind: str = "points"

    @property
    def points(self):
        """Compatibility with the first Point-only implementation."""
        return self.parts

    def to_wire(self):
        if self.kind == 'uv_panels':
            from .surface_structure import panel_model_wire
            return panel_model_wire(self, {"schema": 1, "kind": self.kind, "project_uuid": self.project_uuid,
                                           "node_uuid": self.node_uuid, "output_index": 0, "mode": self.mode})
        if self.kind in ('tessellation', 'mapped_tessellation', 'line_network', 'penrose_p2'):
            from .tessellation import mapped_model_wire, model_wire
            encode = mapped_model_wire if self.kind == 'mapped_tessellation' else model_wire
            return encode(self, {"schema": 1, "kind": self.kind, "project_uuid": self.project_uuid,
                                 "node_uuid": self.node_uuid, "output_index": 0, "mode": self.mode})
        leaf_name = "points" if self.kind == "points" else "parts"
        def record(value):
            return {"key": value.key, "xyz": list(value.xyz)} if self.kind == "points" else value.to_wire()
        result = {"schema": 1, "kind": self.kind, "project_uuid": self.project_uuid,
                  "node_uuid": self.node_uuid, "output_index": 0, "mode": self.mode,
                  "branches": [{"path": list(b.path), leaf_name: [record(v) for v in b.items]}
                               for b in self.parts.branches]}
        if self.mode == "reference":
            result["source_refs"] = [{"key": key, "id": oid} for key, oid in self.source_refs]
        return result
