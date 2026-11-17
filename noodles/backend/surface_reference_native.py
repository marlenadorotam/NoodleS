"""Snapshot native BREP topology and UV without rebuilding input profiles."""
import base64
import io
import zlib

from .curves import cross, dot, sub
from .surface_reference import SurfaceReferenceValue

MAX_BREP_BYTES = 8 * 1024 * 1024


def inspect_surface(shape, key, operation):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from serpentine3d.core import geometry as g

    kind = g.shape_kind(shape) if hasattr(shape, 'ShapeType') and not shape.IsNull() else None
    if kind != 'surface' and not (operation == 'loft' and kind == 'solid'):
        raise ValueError('Select native surface objects. Loft also accepts solid results.')
    faces = g.faces_of(shape)
    if not faces:
        raise ValueError('The selected object has no native faces.')
    normal = None
    if operation == 'edge_surface' and len(faces) != 1:
        raise ValueError('Edge Surface requires a single-face surface object.')
    if operation == 'planar_surface':
        support = []
        for face in faces:
            adaptor = BRepAdaptor_Surface(face)
            if adaptor.GetType() != GeomAbs_Plane:
                raise ValueError('Planar Surface requires coplanar native faces.')
            plane = adaptor.Plane()
            support.append((g.pnt_tuple(plane.Location()), g.pnt_tuple(plane.Axis().Direction())))
        origin, direction = support[0]
        if any(abs(dot(sub(location, origin), direction)) > 1e-6
               or max(map(abs, cross(axis, direction))) > 1e-8 for location, axis in support[1:]):
            raise ValueError('Planar Surface requires coplanar native faces.')
        normal = g.face_normal(faces[0])
    return archive_shape(shape, key, kind, normal)


def inspect_archived_curve(shape, key):
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_WIRE

    if (not hasattr(shape, 'ShapeType') or shape.IsNull() or
            shape.ShapeType() not in (TopAbs_EDGE, TopAbs_WIRE)):
        raise ValueError('Select whole native curves only. Curves accepts edges and wires.')
    value = archive_shape(shape, key, 'curve')
    if not value.edge_count:
        raise ValueError('The selected curve has no native edges.')
    return value


def archive_shape(shape, key, kind, normal=None):
    from OCP.BinTools import BinTools, BinTools_FormatVersion
    from serpentine3d.core import geometry as g
    stream = io.BytesIO()
    BinTools.Write_s(shape, stream, False, False, BinTools_FormatVersion.BinTools_FormatVersion_CURRENT)
    if stream.tell() > MAX_BREP_BYTES:
        raise ValueError('The native geometry archive exceeds the reference size limit.')
    archive = base64.b64encode(zlib.compress(stream.getbuffer())).decode('ascii')
    return SurfaceReferenceValue(key, archive, kind, len(g.edges_of(shape)), normal)


def materialize_surface(value):
    from OCP.BinTools import BinTools
    from OCP.TopoDS import TopoDS_Shape
    from serpentine3d.core import geometry as g

    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(base64.b64decode(value.brep, validate=True), MAX_BREP_BYTES + 1)
    except (ValueError, zlib.error) as exc:
        raise ValueError('Invalid native geometry archive.') from exc
    if len(raw) > MAX_BREP_BYTES or not decoder.eof or decoder.unused_data:
        raise ValueError('Invalid or oversized native geometry archive.')
    shape = TopoDS_Shape()
    BinTools.Read_s(shape, io.BytesIO(raw))
    if shape.IsNull() or g.shape_kind(shape) != value.native_kind:
        raise ValueError('The archive does not contain the expected native geometry.')
    if not (g.edges_of(shape) if value.native_kind == 'curve' else g.faces_of(shape)):
        raise ValueError('The native geometry archive is empty.')
    return shape
