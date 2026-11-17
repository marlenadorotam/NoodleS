"""Session-only undo records for owned objects, never whole-scene undo replay."""
import copy
from dataclasses import dataclass, fields
from weakref import WeakKeyDictionary


def clone_object(obj, scene=None):
    result = obj.clone()
    # BREP and native display caches are immutable across scene replacements.
    # Attribute dictionaries need independent copies, unlike SceneObject.clone.
    for field in fields(result):
        if field.name not in ('_shape', '_mesh', '_bounds', '_scene'):
            setattr(result, field.name, copy.deepcopy(getattr(result, field.name)))
    result._scene = scene
    return result


@dataclass
class DeletedObject:
    obj: object
    index: int
    layers: tuple
    details: dict


class DeletedGeometry:
    def __init__(self, ctx):
        self.ctx = ctx
        # Survives adapter refresh/reconnection, expires with the native document.
        # Saved objects have no _scene back-reference, so weak keys stay weak.
        storage = getattr(ctx.window, '_noodles_deleted_geometry', None)
        if storage is None:
            storage = WeakKeyDictionary()
            ctx.window._noodles_deleted_geometry = storage
        self.storage = storage

    def records(self):
        return self.storage.setdefault(self.ctx.scene, {})

    def remember(self, identity, obj, details=None):
        scene = self.ctx.scene
        ancestry, seen = [], set()
        layer_id = obj.layer_id
        while layer_id is not None:
            if layer_id in seen:
                raise ValueError('Cannot retain geometry with cyclic layer ancestry.')
            seen.add(layer_id)
            layer = scene.layers.get(layer_id)
            ancestry.append((copy.deepcopy(layer), scene.layers._order.index(layer_id)))
            layer_id = layer.parent
        record = DeletedObject(clone_object(obj), scene._order.index(obj.id),
                               tuple(reversed(ancestry)), copy.deepcopy(details or {}))
        self.records()[identity] = record
        return record

    def peek(self, identity):
        return self.records().get(identity)

    def forget(self, identity, record=None):
        if record is None or self.records().get(identity) is record:
            self.records().pop(identity, None)

    def restore(self, record, shape, mesh):
        """Called only inside the publisher's Qt checkpoint/batch/rollback."""
        scene = self.ctx.scene
        if scene.get(record.obj.id) is not None:
            raise ValueError('The original object ID is occupied. Geometry was not overwritten.')
        for layer, index in record.layers:
            if layer.id not in scene.layers._layers:
                scene.layers._add(copy.deepcopy(layer))
                scene.layers._order.remove(layer.id)
                scene.layers._order.insert(min(index, len(scene.layers._order)), layer.id)
                scene.notify('layers')
        obj = clone_object(record.obj, scene)
        obj._shape, obj._mesh = shape, mesh
        obj._bounds = record.obj._bounds if shape is record.obj._shape else None
        from serpentine3d.core.geometry import shape_kind
        obj.kind = shape_kind(shape)
        # Serpentine 0.12.2 has no single-object restore API. Mirror its native
        # store/order/notification contract, preserving the original runtime ID.
        scene.objects[obj.id] = obj
        scene._order.insert(min(record.index, len(scene._order)), obj.id)
        scene.notify('objects')
        return obj
