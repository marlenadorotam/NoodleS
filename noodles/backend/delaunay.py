"""Pure planar and U-periodic Delaunay kernels. No scene or OCC objects."""
from collections import Counter, defaultdict
import math

from .curves import PlaneValue, cross, dot, sub


EPS = 1e-11


def site_frame(sites, allow_collinear=False):
    origin = sites[0]
    direction = max((sub(p, origin) for p in sites[1:]), key=lambda p: math.hypot(*p), default=(0., 0., 0.))
    normal = max((cross(direction, sub(p, origin)) for p in sites[1:]),
                 key=lambda p: math.hypot(*p), default=(0., 0., 0.))
    if math.hypot(*normal) <= 1e-15:
        if not allow_collinear:
            raise ValueError('Delaunay needs noncollinear points.')
        if math.hypot(*direction) <= 1e-12:
            raise ValueError('Connect a Boundary to build a Voronoi cell from one point.')
        axis = min(((0., 0., 1.), (0., 1., 0.), (1., 0., 0.)), key=lambda v: abs(dot(v, direction)))
        normal = cross(direction, cross(axis, direction))
    return PlaneValue(origin, direction, normal)


def area2(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def polygon_area(points):
    origin = points[0]
    return .5 * sum(area2(origin, a, b) for a, b in zip(points[1:-1], points[2:]))


def _oriented(points, tri):
    a, b, c = tri
    area = area2(points[a], points[b], points[c])
    return (a, b, c) if area > EPS else (a, c, b) if area < -EPS else None


def _circle(a, b, c):
    x, y = a[0]-c[0], a[1]-c[1]
    u, v = b[0]-c[0], b[1]-c[1]
    divisor = 2.*(x*v-y*u)
    if abs(divisor) < EPS:
        return None
    aa, bb = x*x+y*y, u*u+v*v
    cx, cy = (aa*v-bb*y)/divisor, (bb*x-aa*u)/divisor
    r2 = cx*cx+cy*cy
    return cx+c[0], cy+c[1], r2, cx+c[0]+math.sqrt(r2)


def triangulate(points, checkpoint):
    """Incremental circumcircle insertion with completed triangles swept out."""
    n = len(points)
    cloud = [*points, (-1024., -1024.), (1024., -1024.), (0., 1024.)]
    active = [(n, n+1, n+2, *_circle(*cloud[n:]))]
    done = []
    for i in sorted(range(n), key=lambda i: (cloud[i], i)):
        checkpoint()
        x, y = cloud[i]
        boundary = Counter()
        keep = []
        for a, b, c, cx, cy, radius, end in active:
            if end < x-EPS:
                if max(a, b, c) < n:
                    done.append((a, b, c))
            elif (x-cx)**2 + (y-cy)**2 <= radius + 2e-14*max(1., radius):
                for u, v in ((a,b),(b,c),(c,a)):
                    boundary[min(u,v), max(u,v)] += 1
            else:
                keep.append((a, b, c, cx, cy, radius, end))
        for (u, v), count in boundary.items():
            if count == 1:
                circle = _circle(cloud[u], cloud[v], cloud[i])
                if circle is not None:
                    keep.append((u, v, i, *circle))
        active = keep
    done.extend(row[:3] for row in active if max(row[:3]) < n)
    faces = [tri for t in done if (tri := _oriented(points, t)) is not None]
    if not faces or len({i for face in faces for i in face}) != n:
        raise ValueError('Delaunay points are collinear or too close to triangulate reliably.')
    return sorted(faces, key=lambda face: tuple(sorted(face)))


def _inside(point, ring):
    x, y = point
    inside = False
    for a, b in zip(ring, (*ring[1:], ring[0])):
        if abs(area2(a, b, point)) <= EPS and all(
                min(p, q)-EPS <= value <= max(p, q)+EPS for p, q, value in zip(a, b, point)):
            return True
        if (a[1] > y) != (b[1] > y) and x < a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1]):
            inside = not inside
    return inside


def _boundary_vertices(sites, ring):
    spacing = 1.3*math.sqrt(abs(polygon_area(ring))/len(sites))
    vertices = list(sites)
    index = {p: i for i, p in enumerate(vertices)}
    constraints = []
    for a, b in zip(ring, (*ring[1:], ring[0])):
        length = math.dist(a, b)
        if length <= EPS:
            raise ValueError('Delaunay boundary has coincident corners.')
        count = max(1, min(100, math.ceil(length/spacing)))
        dx, dy = b[0]-a[0], b[1]-a[1]
        stations = []
        for i, p in enumerate(sites):
            t = ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(length*length)
            if -EPS <= t < 1.-EPS and abs(area2(a, b, p)) <= EPS*length:
                stations.append((max(0., t), i))
        for step in range(count):
            t = step/count
            if any(abs(t-s)*length < EPS for s, _ in stations):
                continue
            p = (a[0]+dx*t, a[1]+dy*t)
            if p not in index:
                index[p] = len(vertices)
                vertices.append(p)
            stations.append((t, index[p]))
        constraints.extend(i for _, i in sorted(stations))
    return vertices, constraints


def _constrained(points, ring, checkpoint):
    """Ear triangulation plus local Lawson flips with the outline fixed."""
    pending = list(ring)
    faces = []
    while len(pending) > 3:
        checkpoint()
        for i, b in enumerate(pending):
            a, c = pending[i-1], pending[(i+1)%len(pending)]
            if area2(points[a], points[b], points[c]) <= EPS:
                continue
            if any(_contains(points, (a,b,c), points[p]) for p in pending if p not in (a,b,c)):
                continue
            faces.append((a,b,c))
            pending.pop(i)
            break
        else:
            raise ValueError('Delaunay could not triangulate the boundary polygon.')
    faces.append(tuple(pending))
    border = set(ring)
    for i, point in enumerate(points):
        if i in border:
            continue
        checkpoint()
        hit = [(j, tri) for j, tri in enumerate(faces) if _contains(points, tri, point)]
        if not hit or len(hit) > 2:
            raise ValueError('Delaunay could not insert a site inside the boundary.')
        for j, (a,b,c) in reversed(hit):
            faces.pop(j)
            faces.extend(tri for u, v in ((a,b),(b,c),(c,a))
                         if (tri := _oriented(points, (u,v,i))) is not None)
    fixed = {tuple(sorted((a,b))) for a,b in zip(ring, (*ring[1:],ring[0]))}
    for _ in range(160):
        checkpoint()
        edges = defaultdict(list)
        for i, (a,b,c) in enumerate(faces):
            for u,v,w in ((a,b,c),(b,c,a),(c,a,b)):
                edges[tuple(sorted((u,v)))].append((i,u,v,w))
        changed = set()
        for edge, entries in edges.items():
            if edge in fixed or len(entries) != 2:
                continue
            (i,a,b,c),(j,_,_,d) = entries
            if i in changed or j in changed:
                continue
            if (area2(points[d],points[c],points[a]) <= EPS or
                    area2(points[c],points[d],points[b]) <= EPS):
                continue
            ax,ay = (points[a][k]-points[d][k] for k in range(2))
            bx,by = (points[b][k]-points[d][k] for k in range(2))
            cx,cy = (points[c][k]-points[d][k] for k in range(2))
            det = ((ax*ax+ay*ay)*(bx*cy-by*cx) - (bx*bx+by*by)*(ax*cy-ay*cx)
                   + (cx*cx+cy*cy)*(ax*by-ay*bx))
            if det > 1e-14:
                faces[i], faces[j] = (d,c,a), (c,d,b)
                changed.update((i,j))
        if not changed:
            return sorted(faces, key=lambda face: tuple(sorted(face)))
    raise ValueError('Delaunay boundary constraints did not converge.')


def _contains(points, triangle, p):
    a,b,c = (points[i] for i in triangle)
    return min(area2(a,b,p), area2(b,c,p), area2(c,a,p)) >= -EPS


def _check_coverage(points, faces, expected):
    area = .5*sum(area2(*(points[i] for i in tri)) for tri in faces)
    if not math.isclose(area, expected, rel_tol=2e-7, abs_tol=1e-11):
        raise ValueError('Delaunay did not cover the full boundary.')


def bounded(sites, ring, checkpoint):
    if polygon_area(ring) < 0.:
        ring = ring[::-1]
    area = polygon_area(ring)
    if area <= EPS:
        raise ValueError('Delaunay boundary has no usable area.')
    if not all(_inside(p, ring) for p in sites):
        raise ValueError('A Delaunay point is outside the boundary.')
    points, indices = _boundary_vertices(sites, ring)
    if len(points) > 2400:
        raise ValueError('Delaunay boundary subdivision exceeds the vertex budget.')
    convex = all(area2(ring[i-2],ring[i-1],ring[i]) >= -EPS for i in range(len(ring)))
    faces = triangulate(points, checkpoint) if convex else _constrained(points, indices, checkpoint)
    _check_coverage(points, faces, area)
    return points, faces


def _clip(polygon, x, sign):
    result = []
    for a, b in zip(polygon, (*polygon[1:], polygon[0])):
        aa, bb = sign*(a[0]-x), sign*(b[0]-x)
        if aa >= 0.:
            result.append(a)
        if (aa > 0. and bb < 0.) or (aa < 0. and bb > 0.):
            # Always interpolate from smaller U. Adjacent faces then produce
            # bit-identical seam coordinates regardless of edge direction.
            lo, hi = (a,b) if a[0] < b[0] else (b,a)
            t = (x-lo[0])/(hi[0]-lo[0])
            result.append((x, lo[1]+(hi[1]-lo[1])*t))
    return result


def _periodic_sites(sites, width, height, min_rim_sites=3):
    if min(width, height) <= EPS or any(not -EPS <= x <= width+EPS or not -EPS <= y <= height+EPS
                                         for x, y in sites):
        raise ValueError('Periodic U points must be inside the rectangular boundary.')
    base = [(0. if abs(x-width)<=EPS or abs(x)<=EPS else x, min(height,max(0.,y))) for x,y in sites]
    if len({(round(x,11),round(y,11)) for x,y in base}) != len(sites):
        raise ValueError('Delaunay has coincident sites across the U seam.')
    count = max(min_rim_sites,min(100,math.ceil(width/math.sqrt(width*height/len(sites)))))
    known = {(round(x,11),round(y,11)) for x,y in base}
    for i in range(count):
        for y in (0.,height):
            x = width*i/count
            key = round(x,11),round(y,11)
            if key not in known:
                base.append((x,y))
                known.add(key)
    tiles = [(x+delta*width,y) for delta in (-1,0,1) for x,y in base]
    return base, tiles


def periodic_mesh_u(sites, width, height, checkpoint):
    """Keep whole triangles and use the same indices for all copies of a site."""
    vertices, tiles = _periodic_sites(sites, width, height, min_rim_sites=8)
    count = len(vertices)
    faces = []
    area = 0.
    for face in triangulate(tiles, checkpoint):
        checkpoint()
        a, b, c = (tiles[i] for i in face)
        if -EPS <= (a[0]+b[0]+c[0])/3 < width-EPS:
            faces.append(tuple(i % count for i in face))
            area += area2(a, b, c)/2
    edges = Counter()
    for a, b, c in faces:
        edges.update(tuple(sorted(pair)) for pair in ((a, b), (b, c), (c, a)))
    if (not math.isclose(area, width*height, rel_tol=1e-7, abs_tol=EPS)
            or len({tuple(sorted(face)) for face in faces}) != len(faces)
            or any(len(set(face)) != 3 for face in faces)
            or len({i for face in faces for i in face}) != count
            or any(n > 2 or (n == 1 and not vertices[a][1] == vertices[b][1] in (0., height))
                   for (a, b), n in edges.items())):
        raise ValueError('Periodic U could not build a continuous mesh. Add more points or use a wider UV rectangle.')
    return vertices, faces


def periodic_u(sites, width, height, checkpoint):
    _, tiles = _periodic_sites(sites, width, height)
    vertices, indices, faces = [], {}, []
    for face in triangulate(tiles, checkpoint):
        checkpoint()
        polygon = [tiles[i] for i in face]
        if max(x for x,_ in polygon) <= 0. or min(x for x,_ in polygon) >= width:
            continue
        polygon = _clip(polygon,0.,1)
        if polygon:
            polygon = _clip(polygon,width,-1)
        for i in range(1,len(polygon)-1):
            triangle = polygon[0],polygon[i],polygon[i+1]
            if area2(*triangle) <= EPS:
                continue
            row = []
            for x,y in triangle:
                p = (min(width,max(0.,x)), min(height,max(0.,y)))
                key = round(p[0],11),round(p[1],11)
                if key not in indices:
                    indices[key] = len(vertices)
                    vertices.append(p)
                row.append(indices[key])
            faces.append(tuple(row))
    _check_coverage(vertices, faces, width*height)
    left = sorted(y for x,y in vertices if x == 0.)
    right = sorted(y for x,y in vertices if x == width)
    if len(left) != len(right) or any(abs(a-b) > 5e-10 for a,b in zip(left,right)):
        raise ValueError('Delaunay could not reconcile the two U seam borders.')
    return vertices, faces
