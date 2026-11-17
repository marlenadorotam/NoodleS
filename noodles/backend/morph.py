"""DataTree contracts for oriented bounding boxes and deferred surface morphs."""
import hashlib
import math

from .curves import input_tree, matched_inputs, xyz
from .datatree import Branch, DataTree, aligned, as_tree
from .domain import DomainValue


def is_box(value):
    from .operations import OperationValue
    from .solids import SolidValue

    return (isinstance(value, OperationValue) and value.kind == 'bounding_box'
            or isinstance(value, SolidValue) and value.kind in ('box', 'box_from_center'))


def is_target_box(value):
    from .operations import OperationValue
    from .surface_structure import SURFACE_BOX

    return isinstance(value, OperationValue) and value.kind == SURFACE_BOX


def cage_corners(corners):
    if not isinstance(corners, (list, tuple)) or len(corners) != 8:
        raise ValueError('A target box needs eight ordered corners.')
    return tuple(xyz(point) for point in corners)


def morph_domains(domains):
    if not isinstance(domains, (list, tuple)) or len(domains) != 3:
        raise ValueError('Surface Morph requires U, V and W domain settings.')
    result = []
    for label, domain in zip('UVW', domains):
        if domain is None:
            result.append(None)
            continue
        if not isinstance(domain, (tuple, list)) or len(domain) != 2:
            raise ValueError(f'{label} must be a Domain.')
        interval = DomainValue(*domain)
        a, b = interval.start, interval.end
        if not math.isfinite(b - a) or (label != 'W' and a == b):
            raise ValueError(f'{label} must have a finite, nonzero span.')
        result.append((a, b))
    return tuple(result)


def evaluate(operation, state, inputs):
    from .operations import OPERATION_SPECS, OperationValue
    from .moves import geometry_wire
    from .pull import request_signature

    options = state['parameters']
    trees = []
    for descriptor in OPERATION_SPECS[operation]['inputs']:
        port = descriptor.port
        if port not in inputs and descriptor.optional:
            trees.append(as_tree(None))
        else:
            trees.append(input_tree(inputs.get(port, options.get(port)), descriptor,
                                    state['tree_modes'].get(port, 'none'), port not in inputs))

    branches, occurrences, complexity = [], {}, 0
    shared_sources = {}
    def share(source):
        wire = geometry_wire(source)
        wire.pop('key')
        return shared_sources.setdefault(request_signature(wire), source)

    trees = matched_inputs(trees)
    for path, rows in aligned(*trees):
        widths = [len(next((b for b in tree.branches if b.path == path),
                           tree.branches[0]).items) for tree in trees if tree.branches]
        if any(width not in (0, 1, max(widths)) for width in widths):
            raise ValueError('Match the input branch lengths or connect one shared value.')
        if operation == 'bounding_box' and options['box_mode'] == 'union' and rows:
            plane = rows[0][0][1]
            if any(items[1] != plane for items, _ in rows):
                raise ValueError('Union Bounding Box needs one plane per branch.')
            sources = tuple(dict.fromkeys(share(items[0]) for items, _ in rows))
            rows = [((sources, plane), tuple(keys for _, keys in rows))]
        values = []
        for items, provenance in rows:
            slot = path, provenance
            repeat = occurrences.get(slot, 0)
            occurrences[slot] = repeat + 1
            key = hashlib.sha256(repr((slot, repeat)).encode()).hexdigest()[:24]
            if operation == 'bounding_box':
                source, plane = items
                sources = source if options['box_mode'] == 'union' else (source,)
                value = OperationValue(key, operation, sources, axis=plane)
            elif operation == 'surface_morph':
                source, box, surface, *domains = items
                value = OperationValue(key, operation, (share(source), box, surface), morph_domains=tuple(
                    (d.start, d.end) if d is not None else None for d in domains))
            else:
                source, reference, target = items
                value = OperationValue(key, operation, (share(source), reference, target))
            complexity += value.complexity
            if complexity > 10000:
                raise ValueError('Operation collection exceeds the 10000-recipe budget.')
            values.append(value)
        branches.append(Branch(path, tuple(values), tuple(v.key for v in values)))
    tree = DataTree(tuple(branches))
    return {'B': tree, 'G': tree} if operation == 'bounding_box' else {'G': tree}
