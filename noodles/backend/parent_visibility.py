"""Combine persistent Show Parent claims with temporary Hide leases."""
import json
import uuid


CLAIMS = 'NoodleS.hidden_parents'
BASELINE = 'NoodleS.parent_visibility'


def validated_targets(targets):
    if not isinstance(targets, list) or len(targets) > 10000:
        raise ValueError('Invalid visibility targets.')
    result = set()
    for target in targets:
        if not isinstance(target, (list, tuple)) or len(target) != 4:
            raise ValueError('Invalid visibility target.')
        kind, project, node, part = target
        if (kind not in ('owner', 'reference') or not isinstance(part, str)
                or len(part) > 256 or (kind == 'reference') != bool(part)):
            raise ValueError('Invalid visibility target.')
        result.add((kind, str(uuid.UUID(project)), str(uuid.UUID(node)), part))
    return sorted(result)


def claim_text(obj, targets):
    from serpentine3d.core.user_text import with_value
    return with_value(obj.user_text, CLAIMS, json.dumps(targets) if targets else '')


def reconcile(adapter, scene=None):
    """Release a parent's hide only after its last result releases the claim."""
    from serpentine3d.core.user_text import with_value
    from .move_native import reference_tags
    from .scene_points import OWNER

    scene = adapter.ctx.scene if scene is None else scene
    objects = scene.all()
    targets = {tuple(target) for obj in objects for target in adapter._json(obj, CLAIMS, [])}
    targets.update(adapter.preview_hide_targets(scene))
    references = {(f'{project}:{node}:0', part): (kind, project, node, part)
                  for kind, project, node, part in targets if kind == 'reference'}
    matched = {}
    for obj in objects:
        owner = adapter._json(obj, OWNER)
        if owner and owner.get('output_index') == 0:
            target = ('owner', owner.get('project_uuid'), owner.get('node_uuid'), '')
            if target in targets:
                matched.setdefault(target, set()).add(obj.id)
        if references:
            for tag in reference_tags(adapter, obj):
                if tag in references:
                    matched.setdefault(references[tag], set()).add(obj.id)
    if any(len(ids) != 1 for ids in matched.values()):
        raise ValueError('Duplicate visibility binding. Resolve copied binding metadata.')
    hidden = {oid for ids in matched.values() for oid in ids}
    for obj in objects:
        baseline = adapter._json(obj, BASELINE)
        if obj.id in hidden and baseline is None:
            scene.update(obj.id, visible=False, user_text=with_value(obj.user_text, BASELINE, json.dumps(obj.visible)))
        elif obj.id in hidden and obj.visible:
            scene.update(obj.id, visible=False)
        elif obj.id not in hidden and baseline is not None:
            scene.update(obj.id, visible=baseline, user_text=with_value(obj.user_text, BASELINE, ''))
    if scene is adapter.ctx.scene:
        adapter._missing_parent_targets = bool(targets - matched.keys())
