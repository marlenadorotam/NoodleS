"""Immutable DataTree topology. Topology edits never materialize geometry.

Matching follows the tested former engine: exact multi-branch paths,
single-branch broadcast, and repeat-last within a branch. Unsupported path
matching fails explicitly. Leaf keys survive graft/flatten and carry provenance.
"""
from dataclasses import dataclass
import math
import re

MAX_ITEMS = 10000
MAX_BRANCHES = 10000


@dataclass(frozen=True)
class Branch:
    path: tuple
    items: tuple
    keys: tuple = ()

    def __post_init__(self):
        path, items = tuple(self.path), tuple(self.items)
        if not path or any(type(i) is not int or i < 0 for i in path):
            raise ValueError("Tree paths require nonnegative integer indices.")
        keys = tuple(self.keys) or tuple(f"{'.'.join(map(str, path))}:{i}" for i in range(len(items)))
        if len(keys) != len(items) or any(not isinstance(k, str) for k in keys):
            raise ValueError("Invalid tree item keys.")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "keys", keys)


@dataclass(frozen=True)
class DataTree:
    branches: tuple

    def __post_init__(self):
        branches = tuple(self.branches)
        if any(not isinstance(b, Branch) for b in branches):
            raise ValueError("Expected tree branches.")
        if len(branches) > MAX_BRANCHES or sum(len(b.items) for b in branches) > MAX_ITEMS:
            raise ValueError(f"DataTree exceeds the {MAX_ITEMS:,} item limit.")
        if len({b.path for b in branches}) != len(branches):
            raise ValueError("Duplicate tree path.")
        object.__setattr__(self, "branches", branches)

    @property
    def count(self):
        return sum(len(b.items) for b in self.branches)

    def values(self):
        return tuple(v for b in self.branches for v in b.items)


def as_tree(value):
    if isinstance(value, DataTree):
        return value
    return DataTree((Branch((0,), tuple(value) if isinstance(value, list) else (value,)),))


def topology(value, mode="none"):
    tree = as_tree(value)
    if mode == "none":
        return tree
    if mode == "flatten":
        return DataTree((Branch((0,), tree.values(), tuple(k for b in tree.branches for k in b.keys)),))
    if mode == "graft":
        return DataTree(tuple(Branch(b.path + (i,), (v,), (b.keys[i],))
                              for b in tree.branches for i, v in enumerate(b.items)) +
                        tuple(Branch(b.path + (0,), ()) for b in tree.branches if not b.items))
    raise ValueError("Unknown tree modifier.")


def tree_diagnostics(tree):
    """Expose each path as one data item, including paths of empty branches."""
    paths = DataTree(tuple(Branch(branch.path, (branch.path,)) for branch in tree.branches))
    return {'P': paths, 'B': len(tree.branches), 'N': tree.count}


def branch_path(value):
    """Accept an existing path value, a single index, or notation such as {1;2}."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith('{') and text.endswith('}'):
            text = text[1:-1]
        if re.fullmatch(r'\s*[0-9]+\s*(?:[;,]\s*[0-9]+\s*)*', text):
            return tuple(map(int, re.split(r'[;,]', text)))
    elif type(value) in (tuple, list) and value and all(type(i) is int and i >= 0 for i in value):
        return tuple(value)
    elif type(value) is int and value >= 0:
        return (value,)
    elif type(value) is float and math.isfinite(value) and value >= 0 and value.is_integer():
        return (int(value),)
    raise ValueError('Expected a nonnegative tree path such as {0;2}.')


def simplify(tree):
    """Remove the shared prefix while keeping every structured path nonempty."""
    if not tree.branches:
        return tree
    if len(tree.branches) == 1:
        branch = tree.branches[0]
        return DataTree((Branch((0,), branch.items, branch.keys),))
    paths = tuple(branch.path for branch in tree.branches)
    limit = min(map(len, paths)) - 1
    prefix = 0
    while prefix < limit and all(path[prefix] == paths[0][prefix] for path in paths):
        prefix += 1
    if not prefix:
        return tree
    return DataTree(tuple(Branch(branch.path[prefix:], branch.items, branch.keys)
                          for branch in tree.branches))


def flip_matrix(tree):
    """Transpose regular branches while keeping a common parent path."""
    rows = tree.branches
    width = len(rows[0].items) if rows else 0
    if not width or any(len(row.items) != width for row in rows):
        raise ValueError("Flip Matrix requires nonempty branches of equal length.")
    prefix = []
    if len(rows) > 1:
        for indices in zip(*(row.path for row in rows)):
            if any(index != indices[0] for index in indices):
                break
            prefix.append(indices[0])
    parent = tuple(prefix)
    item_columns = zip(*(row.items for row in rows))
    key_columns = zip(*(row.keys for row in rows))
    return DataTree(tuple(Branch(parent + (column,), items, keys)
                          for column, (items, keys) in enumerate(zip(item_columns, key_columns))))


def rectangular_row_width(tree):
    """Read U from an ordered rectangular row layout before flattening."""
    branches = as_tree(tree).branches
    if len(branches) < 2:
        return None
    first = branches[0]
    width = len(first.items)
    if width < 2:
        return None
    parent, start = first.path[:-1], first.path[-1]
    if any(branch.path != parent + (start + index,) or len(branch.items) != width
           for index, branch in enumerate(branches)):
        return None
    return width


def aligned(*values):
    trees = [as_tree(value) for value in values]
    if not trees:
        return
    multi = [tree for tree in trees if len(tree.branches) > 1]
    if multi:
        paths = tuple(b.path for b in multi[0].branches)
        if any({b.path for b in tree.branches} != set(paths) for tree in multi[1:]):
            raise ValueError("Input tree paths differ. Match their structure explicitly.")
    else:
        # A singleton is broadcastable, but must not erase a deeper Graft path
        # just because its input happens to be listed before that tree.
        deepest = max(trees, key=lambda tree: (len(tree.branches[0].path), tree.branches[0].path != (0,))
                      if tree.branches else (-1, False))
        paths = tuple(b.path for b in deepest.branches)
    if any(not t.branches for t in trees):
        return
    by_path = [{b.path: b for b in tree.branches} for tree in trees]
    total = 0
    for path in paths:
        branches = [tree.branches[0] if len(tree.branches) == 1 else
                    index[path] for tree, index in zip(trees, by_path)]
        count = max(len(b.items) for b in branches)
        if any(not b.items for b in branches):
            yield path, ()
            continue
        total += count
        if total > MAX_ITEMS:
            raise ValueError(f"Matching would exceed {MAX_ITEMS:,} items.")
        yield path, tuple((tuple(b.items[min(i, len(b.items) - 1)] for b in branches),
                           tuple(b.keys[min(i, len(b.items) - 1)] for b in branches)) for i in range(count))


def map_values(function, *values):
    return DataTree(tuple(Branch(path, tuple(function(*items) for items, _ in rows),
                                 tuple("|".join(keys) for _, keys in rows))
                          for path, rows in aligned(*values)))


def finite(value):
    if type(value) not in (int, float) or abs(value) > 1e9 or not math.isfinite(value):
        raise ValueError("Coordinates must be finite numbers between -1e9 and 1e9.")
    return value
