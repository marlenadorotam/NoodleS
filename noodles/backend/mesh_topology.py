"""Topology operations on indexed triangle meshes."""
from collections import defaultdict
from dataclasses import replace
from itertools import product
import math

from .arithmetic import finite_number
from .curves import dot
from .datatree import MAX_ITEMS


NEIGHBOR_CELLS = tuple(product((-1, 0, 1), repeat=3))


def weld_settings(tolerance, angle):
    tolerance, angle = map(finite_number, (tolerance, angle))
    if not 0 <= tolerance <= 1e9 or not 0 <= angle <= 180:
        raise ValueError('Weld Mesh needs a nonnegative tolerance and an angle from 0 to 180 degrees.')
    return tolerance, angle


def join_meshes(key, meshes):
    from .mesh_nodes import MAX_MESH_ELEMENTS, MeshValue, _vertex_normals

    if (sum(len(mesh.vertices) for mesh in meshes) > MAX_MESH_ELEMENTS
            or sum(len(mesh.triangles) for mesh in meshes) > MAX_MESH_ELEMENTS):
        raise ValueError('Mesh Join exceeds the 10,000-vertex or triangle limit.')
    vertices, triangles, normals = [], [], []
    keep_normals = any(mesh.normals for mesh in meshes)
    for mesh in meshes:
        offset = len(vertices)
        vertices.extend(mesh.vertices)
        triangles.extend((a+offset, b+offset, c+offset) for a, b, c in mesh.triangles)
        if keep_normals:
            normals.extend(_vertex_normals(mesh))
    return MeshValue(key, tuple(vertices), tuple(triangles), tuple(normals))


def weld_mesh(key, mesh, tolerance, angle):
    from .mesh_nodes import MeshValue, _vertex_normals

    tolerance, angle = weld_settings(tolerance, angle)
    threshold = math.cos(math.radians(angle)) - 1e-12
    normals = _vertex_normals(replace(mesh, normals=())) if angle < 180 else None
    buckets, vertices, remap = defaultdict(list), [], []
    # A bin size of one tolerance permits a strict Euclidean check in the
    # adjacent 27 cells. Integer ratios avoid overflow for tiny tolerances.
    numerator, denominator = tolerance.as_integer_ratio()
    tests = 0
    for index, point in enumerate(mesh.vertices):
        if tolerance:
            x, y, z = cell = tuple(a*denominator // (b*numerator)
                                   for a, b in (coord.as_integer_ratio() for coord in point))
            nearby = ((x+dx, y+dy, z+dz) for dx, dy, dz in NEIGHBOR_CELLS)
        else:
            cell = point
            nearby = (cell,)
        target = None
        for bucket in nearby:
            for candidate, original in buckets.get(bucket, ()):
                tests += 1
                if tests > 2_000_000:
                    raise ValueError('Weld Mesh found too many overlapping candidates. Reduce the tolerance.')
                if (math.dist(point, vertices[candidate]) <= tolerance
                        and (normals is None or dot(normals[index], normals[original]) >= threshold)):
                    target = candidate if target is None else min(target, candidate)
                    break  # Representatives are stored in input order.
        if target is None:
            target = len(vertices)
            vertices.append(point)
            buckets[cell].append((target, index))
        remap.append(target)
    triangles = tuple(face for face in (tuple(remap[i] for i in face) for face in mesh.triangles)
                      if len(set(face)) == 3)
    if not triangles:
        raise ValueError('Weld Mesh collapsed all triangles. Reduce the tolerance.')
    if len(vertices) == len(mesh.vertices) and triangles == mesh.triangles:
        return replace(mesh, key=key)
    used = sorted({i for face in triangles for i in face})
    compact = {index: new for new, index in enumerate(used)}
    result = MeshValue(key, tuple(vertices[i] for i in used),
                       tuple(tuple(compact[i] for i in face) for face in triangles))
    return replace(result, normals=tuple(_vertex_normals(result)))


def face_neighbours(mesh, remaining):
    """Return face adjacency by indexed edges, with boundary/overlap counts."""
    incidents = defaultdict(list)
    for index, (a, b, c) in enumerate(mesh.triangles):
        if len({a, b, c}) == 3:
            for edge in ((a, b), (b, c), (c, a)):
                incidents[tuple(sorted(edge))].append(index)
    count = len(mesh.triangles)
    neighbours = [set() for _ in range(count)]
    boundary, nonmanifold = [0]*count, [0]*count
    for faces in incidents.values():
        length = len(faces)
        if length == 1:
            boundary[faces[0]] += 1
            continue
        if length*(length-1) > MAX_ITEMS:
            raise ValueError('Face Neighbours exceeds the 10,000-link budget.')
        shared = set(faces)
        for face in faces:
            if length > 2:
                nonmanifold[face] += 1
            added = shared.difference(neighbours[face], (face,))
            remaining -= len(added)
            if remaining < 0:
                raise ValueError('Face Neighbours exceeds the 10,000-link budget.')
            neighbours[face].update(added)
    return tuple(tuple(sorted(row)) for row in neighbours), tuple(boundary), tuple(nonmanifold), remaining
