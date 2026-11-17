"""Shared grid topology for native commands and deferred nodes. No scene objects."""
from functools import lru_cache
import math


@lru_cache(maxsize=8)
def topology(kind, ex, ey):
    """(vertices, unique edges, cells, centres), with stable logical roles.

    Each record includes its local DataTree path. Cell edges are ordered and
    oriented; neighbouring cells share canonical edge records.
    """
    vertices, edges, cells, centres = {}, {}, [], {}
    def vertex(role, xy, path):
        vertices[role] = (xy, path)
        return role
    def edge(role, a, b, path, arc=False):
        edges[role] = (a, b, path, arc)
        return role
    def cell(role, corners, boundary, path):
        cells.append((role, tuple(corners), tuple(boundary), path))
    if kind in ('grid_rectangle', 'grid_triangle'):
        triangle = kind == 'grid_triangle'
        def p(i, j):
            return f'P:{i}:{j}'
        for j in range(ey+1):
            for i in range(ex+1):
                vertex(p(i,j), (i+.5*j if triangle else i, math.sqrt(3)*.5*j if triangle else j), (j,))
        for j in range(ey+1):
            for i in range(ex):
                edge(f'H:{i}:{j}', p(i,j), p(i+1,j), (1,j))
        for j in range(ey):
            for i in range(ex+1):
                edge(f'V:{i}:{j}', p(i,j), p(i,j+1), (2,j))
        for j in range(ey):
            for i in range(ex):
                h, v, top, left = f'H:{i}:{j}', f'V:{i+1}:{j}', f'H:{i}:{j+1}', f'V:{i}:{j}'
                if triangle:
                    d = edge(f'D:{i}:{j}', p(i+1,j), p(i,j+1), (0,j))
                    definitions = (([p(i,j),p(i+1,j),p(i,j+1)], [(h,False),(d,False),(left,True)]),
                                   ([p(i+1,j),p(i+1,j+1),p(i,j+1)], [(v,False),(top,True),(d,True)]))
                    for t, (corners, boundary) in enumerate(definitions):
                        role = f'C:{i}:{j}:{t}'
                        cell(role, corners, boundary, (j,))
                        xy = tuple(sum(vertices[p][0][k] for p in corners)/3 for k in range(2))
                        centres[f'M:{i}:{j}:{t}'] = (xy, (j,))
                else:
                    cell(f'C:{i}:{j}', [p(i,j),p(i+1,j),p(i+1,j+1),p(i,j+1)],
                         [(h,False),(v,False),(top,True),(left,True)], (j,))
    elif kind == 'grid_hexagon':
        dx, dy = (2,1,-1,-2,-1,1), (0,1,1,0,-1,-1)
        for j in range(ey):
            for i in range(ex):
                corners, boundary = [], []
                coords = [(3*i+x, i+2*j+y) for x,y in zip(dx,dy)]
                for x,y in coords:
                    corners.append(vertex(f'Q:{x}:{y}', (.5*x, math.sqrt(3)*.5*y), (x+2,)))
                for a,b in zip(coords,coords[1:]+coords[:1]):
                    lo, hi = sorted((a,b))
                    name = f'E:{lo[0]}:{lo[1]}:{hi[0]}:{hi[1]}'
                    edge(name, f'Q:{lo[0]}:{lo[1]}', f'Q:{hi[0]}:{hi[1]}', (lo[0]+2,))
                    boundary.append((name, a != lo))
                cell(f'C:{i}:{j}', corners, boundary, (j,))
                centres[f'M:{i}:{j}'] = ((1.5*i,math.sqrt(3)*(j+.5*i)), (j,))
        vertices = dict(sorted(vertices.items(), key=lambda item: tuple(map(int,item[0].split(':')[1:]))))
        edges = dict(sorted(edges.items(), key=lambda item: tuple(map(int,item[0].split(':')[1:]))))
    elif kind == 'grid_radial':
        vertex('O', (0.,0.), (0,))
        def p(r,a):
            return f'P:{r}:{a}' if r else 'O'
        for r in range(1,ex+1):
            for a in range(ey):
                angle = math.tau*a/ey
                vertex(p(r,a), (r*math.cos(angle),r*math.sin(angle)), (r,))
        for r in range(ex):
            for a in range(ey):
                edge(f'R:{r}:{a}', p(r,a), p(r+1,a), (0,r))
        for r in range(1,ex+1):
            for a in range(ey):
                edge(f'A:{r}:{a}', p(r,a), p(r,(a+1)%ey), (1,r), True)
        for r in range(ex):
            for a in range(ey):
                nxt = (a+1)%ey
                corners = [p(r,a),p(r+1,a),p(r+1,nxt)] + ([p(r,nxt)] if r else [])
                boundary = [(f'R:{r}:{a}',False),(f'A:{r+1}:{a}',False),(f'R:{r}:{nxt}',True)]
                if r:
                    boundary.append((f'A:{r}:{a}',True))
                cell(f'C:{r}:{a}',corners,boundary,(r,))
    else:
        raise ValueError('Unknown grid kind.')
    return vertices, edges, tuple(cells), centres
