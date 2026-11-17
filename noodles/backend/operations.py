"""Deferred curve/surface operations; matching is independent of OCC/Qt."""
from dataclasses import dataclass
import hashlib
import json
import math
from .curves import (CurveInput,CurveValue,PlaneValue,input_tree,normalize_curve_state,
                     matched_inputs,curve_object_from_wire,curve_from_wire,is_curve_recipe,rectangle,dot,scale,sub,unit)
from .arithmetic import VectorValue,finite_number
from .booleans import (BOOLEAN_SPLIT, BOOLEAN_SPLIT_PARAMETRIC, NATIVE_BOOLEANS, PARAMETRIC_BOOLEANS,
                       SHOW_PARENT_OPERATIONS, SPLIT_OPERANDS, SPLIT_PLANE, boolean_slots, is_boolean_operand)
from . import fillet_curves, fillet_edges
from . import map_surface, placement
from .surface_structure import DECONSTRUCT, SURFACE_BOX, SPECS as STRUCTURE_SPECS
from .datatree import Branch, DataTree, MAX_ITEMS, aligned, finite, rectangular_row_width, topology
from .parametric import ParametricObject
from .point import PointValue
from .profile_operations import PROFILE_SPECS, SHATTER, evaluate_profiles, profile_options
from .surface_modules import (ISOCURVE_SPEC, SCALE_NON_UNIFORM, SCALE_SPEC, SURFACE_ISOCURVES,
                              evaluate_isocurves, iso_span, scale_factors, scale_point)
from .splines import signature,PendingGeometry
from .topology_operations import (BREP_INPUT, PIECE_KINDS, SPLIT_INPUTS, TRIM_INPUTS, TOPOLOGY_INPUT, TOPOLOGY_OPERATIONS,
                                  TOPOLOGY_SOURCE_LIMITS, SECTION, SECTION_INPUTS, CONTOUR, CONTOUR_INPUTS,
                                  CURVE_CURVE, CURVE_CURVE_INPUTS, REGION_BOOLEAN, REGION_INPUTS, REGION_MODES,
                                  evaluate_intersections, evaluate_section, evaluate_topology, region_parameters)
from .surface_reference import (
    MAX_REFERENCE_ARCHIVES, MAX_REFERENCE_OBJECTS, SURFACE_REFERENCE_KIND, SURFACE_REFERENCE_OPS,
    SurfaceReferenceValue, surface_reference_from_wire,
)
from .isotrim import ISOTRIM_SPEC

PLANE_SURFACE_SPEC = {'class': 'PlaneSurfaceNode', 'name': 'Plane Surface', 'category': 'Operations',
    'reference': False, 'primary': 'P', 'inputs': (CurveInput('P', 'Plane', 'plane', 'XY'),
        CurveInput('X', 'X Size / Domain', 'dimension', 10.),
        CurveInput('Y', 'Y Size / Domain', 'dimension', 10.)), 'outputs': ('P',)}

OPERATION_SPECS={
    DECONSTRUCT: STRUCTURE_SPECS[DECONSTRUCT],
    SURFACE_BOX: STRUCTURE_SPECS[SURFACE_BOX],
    'isotrim': ISOTRIM_SPEC,
    'project': {'class': 'ProjectNode', 'name': 'Project', 'category': 'Operations',
                'inputs': (CurveInput('G', 'Points or Curves', 'move_geometry'),
                           CurveInput('P', 'Projection Plane', 'plane', 'XY'),
                           CurveInput('D', 'Projection Direction', 'vector', optional=True)),
                'outputs': ('G',)},
    'bounding_box': {'class': 'BoundingBoxNode', 'name': 'Bounding Box', 'primary': 'B',
                     'inputs': (CurveInput('C', 'Geometry', 'move_geometry'),
                                CurveInput('P', 'Box Plane', 'plane', 'XY')),
                     'outputs': ('B', 'G')},
    'surface_morph': {'class': 'SurfaceMorphNode', 'name': 'Surface Morph',
                      'inputs': (CurveInput('G', 'Geometry', 'move_geometry'),
                                 CurveInput('R', 'Reference Box', 'morph_box'),
                                 CurveInput('S', 'Target Surface', 'geometry'),
                                 CurveInput('U', 'Target U Domain', 'morph_domain', optional=True),
                                 CurveInput('V', 'Target V Domain', 'morph_domain', optional=True),
                                 CurveInput('W', 'Normal Offset Domain', 'morph_domain', optional=True)),
                      'outputs': ('G',)},
    'box_morph': {'class': 'BoxMorphNode', 'name': 'Box Morph', 'category': 'Operations',
                  'inputs': (CurveInput('G', 'Module Geometry', 'move_geometry'),
                             CurveInput('R', 'Reference Box', 'morph_box'),
                             CurveInput('T', 'Target Box', 'target_box')),
                  'outputs': ('G',)},
    **placement.PLACEMENT_SPECS,
    map_surface.MAP_SURFACE: map_surface.MAP_SPEC,
    fillet_curves.FILLET_PARAMETRIC: {'class': 'FilletParametricNode', 'name': 'Fillet Parametric',
                                    'inputs': fillet_curves.FILLET_INPUTS, 'outputs': ('G', 'R', 'Count', 'Flat')},
    'fillet_edge': {'class': 'FilletEdgeNode', 'name': 'Fillet Edge', 'inputs': (
        CurveInput('G', 'Solid Geometry', 'boolean_solid'), CurveInput('R', 'Fillet Radius', 'number', 1.),
        CurveInput('E', 'Edge Points', 'points', optional=True)), 'outputs': ('G', 'K', 'Count')},
    'offset': {'class': 'OffsetNode', 'name': 'Offset', 'inputs': (
        CurveInput('G', 'Curve or Surface', 'geometry'), CurveInput('D', 'Signed Distance', 'number', 1.),
        CurveInput('P', 'Offset Plane', 'plane', optional=True)), 'outputs': ('G', 'D', 'K', 'Count')},
    'pipe': {'class':'PipeNode', 'name':'Pipe', 'inputs':(
        CurveInput('C','Rail Curve','curve'), CurveInput('R','Radius','number'),
        CurveInput('S','Cap Ends','boolean',True)), 'outputs':('G','K','Count')},
    'extrude':{'class':'ExtrudeNode','name':'Extrude','inputs':(
        CurveInput('G','Geometry (Curve / Surface)','geometry'),
        CurveInput('V','Extrusion Vector','vector',(0.,0.,10.)),
        CurveInput('C','Cap Closed Planar Profiles','boolean',True)),
        'outputs':('G','K','Count')},
    'revolve':{'class':'RevolveNode','name':'Revolve','inputs':(
        CurveInput('C','Profile Curve','curve'),CurveInput('A','Axis (Line / Plane)','axis','XY'),
        CurveInput('D','Angle (Degrees)','number',360.)), 'outputs':('G','K','Count')},
    'loft':{'class':'LoftNode','name':'Loft','inputs':(
        CurveInput('C','Sections (One Loft per Branch)','curve'),
        CurveInput('T','Loft Type','loft_type',0,('Smooth','Ruled')),
        CurveInput('Cl','Closed Section Cycle','boolean',False),
        CurveInput('A','Adjust Section Compatibility','boolean',True),
        CurveInput('O','Loft Options','loft_options',optional=True)),
        'outputs':('G','K','SC','Count')},
    'planar_surface':{'class':'PlanarSurfaceNode','name':'Planar Surface','inputs':(
        CurveInput('C','Closed Boundaries (One Region Set per Branch)','curve'),),
        'outputs':('G','K','N','EC','Count')},
    'edge_surface':{'class':'EdgeSurfaceNode','name':'Edge Surface','inputs':(
        CurveInput('C','Boundary Curves (2–4 per Branch)','curve'),),
        'outputs':('G','K','EC','Count')},
    'patch':{'class':'PatchNode','name':'Patch','inputs':(
        CurveInput('C','Boundary Curves (One Closed Outline per Branch)','curve'),),
        'outputs':('G','K','EC','Count')},
    'surface_from_points':{'class':'SurfaceFromPointsNode','name':'Surface from Points','inputs':(
        CurveInput('P','Ordered Grid Points (One Surface per Branch)','points'),
        CurveInput('U','Points per Row','surface_u','auto')),
        'outputs':('G','K','U','V','Count')},
    'cap_holes': {'class': 'CapHolesNode', 'name': 'Cap Holes', 'category': 'Operations',
                  'primary': 'B', 'inputs': (CurveInput('B', 'Open Breps', 'native_boolean_operand'),),
                  'outputs': ('B', 'K')},
    'sweep1':{'class':'Sweep1Node','name':'Sweep 1 Rail','inputs':(
        CurveInput('R','Rail Curve','curve'),CurveInput('P','Profile Curve','curve')),
        'outputs':('G','K','Count')},
    'sweep2':{'class':'Sweep2Node','name':'Sweep 2 Rails','inputs':(
        CurveInput('R1','Rail 1 (Main Spine)','curve'),CurveInput('R2','Rail 2 (Orientation Guide)','curve'),
        CurveInput('P','Profile Curve','curve')), 'outputs':('G','K','Count')},
    'birail_sweep':{'class':'BiRailSweepNode','name':'BiRail Sweep','inputs':(
        CurveInput('R1','Rail 1 (Boundary)','curve'),CurveInput('R2','Rail 2 (Boundary)','curve'),
        CurveInput('P','Profile Curve','curve'),
        CurveInput('Rs','Rail Samples','sweep_samples',33),CurveInput('Ps','Profile Samples','sweep_samples',25)),
        'outputs':('G','K','Count')},
}
OPERATION_SPECS.update({
    key: {'class': f'Boolean{name}ParametricNode', 'name': f'Boolean {name} Parametric',
          'inputs': inputs, 'outputs': ('G', 'K', 'Count', 'Flat')}
    for key, (name, inputs) in PARAMETRIC_BOOLEANS.items()
})
OPERATION_SPECS.update({
    operation: {'class': operation.title() + 'Node', 'name': operation.title(),
                'inputs': {'split': SPLIT_INPUTS, 'trim': TRIM_INPUTS}.get(operation, (TOPOLOGY_INPUT,)),
                'outputs': ('G', 'Count')}
    for operation in TOPOLOGY_OPERATIONS if operation not in (
        'brep_join', BOOLEAN_SPLIT_PARAMETRIC, SECTION, CONTOUR, CURVE_CURVE,
        REGION_BOOLEAN, SURFACE_ISOCURVES, *PROFILE_SPECS)
})
OPERATION_SPECS[BOOLEAN_SPLIT_PARAMETRIC] = {
    'class': 'BooleanSplitParametricNode', 'name': 'Boolean Split Parametric',
    'inputs': (*SPLIT_OPERANDS, SPLIT_PLANE), 'outputs': ('G', 'Count'),
}
OPERATION_SPECS.update({operation: {**spec, 'primary': 'C'} for operation, spec in PROFILE_SPECS.items()})
OPERATION_SPECS.update({SCALE_NON_UNIFORM: SCALE_SPEC, SURFACE_ISOCURVES: ISOCURVE_SPEC})
OPERATION_SPECS[SECTION] = {'class': 'SectionNode', 'name': 'Section', 'primary': 'C',
                            'inputs': SECTION_INPUTS, 'outputs': ('C', 'R')}
OPERATION_SPECS[CONTOUR] = {'class': 'ContourNode', 'name': 'Contour', 'primary': 'C',
                           'inputs': CONTOUR_INPUTS, 'outputs': ('C', 'R')}
OPERATION_SPECS[CURVE_CURVE] = {'class': 'CurveCurveNode', 'name': 'Curve–Curve', 'primary': 'P',
                               'inputs': CURVE_CURVE_INPUTS, 'outputs': ('P', 'tA', 'tB', 'C')}
OPERATION_SPECS[REGION_BOOLEAN] = {'class': 'RegionBooleanNode', 'name': 'Region Boolean', 'primary': 'R',
                                  'inputs': REGION_INPUTS, 'outputs': ('R', 'C')}
SECONDARY_GEOMETRY_PORTS = {SECTION: 'R', CONTOUR: 'R', CURVE_CURVE: 'C', REGION_BOOLEAN: 'C',
                            SURFACE_ISOCURVES: 'V'}
OPERATION_SPECS['brep_join'] = {'class': 'BrepJoinNode', 'name': 'Brep Join', 'primary': 'B',
                                'inputs': (BREP_INPUT,), 'outputs': ('B', 'C')}
NATIVE_BOOLEAN_SPECS = {
    key: {'class': f'Boolean{name}Node', 'name': f'Boolean {name}', 'inputs': inputs,
          'outputs': ('G', 'Count') if key == BOOLEAN_SPLIT else ('G',), 'primary': 'G', 'reference': False}
    for key, (name, inputs) in NATIVE_BOOLEANS.items()
}
NATIVE_SCENE_SPECS = {**NATIVE_BOOLEAN_SPECS, fillet_curves.FILLET: {
    'class': 'FilletNode', 'name': 'Fillet', 'inputs': fillet_curves.FILLET_INPUTS,
    'outputs': ('G', 'R'), 'primary': 'G', 'reference': False,
}}
for operation, spec in OPERATION_SPECS.items():
    spec.setdefault('primary', 'G')
    spec['reference'] = operation in SURFACE_REFERENCE_OPS


@dataclass(frozen=True)
class OperationValue:
    key:str
    kind:str
    sources:tuple
    vector:tuple=(0.,0.,10.)
    axis:PlaneValue=PlaneValue()
    angle:float=360.
    cap:bool=True
    closed:bool=False
    ruled:bool=False
    adjust:bool=True
    points:tuple=()
    u_count:int=2
    rail_samples:int=33
    profile_samples:int=25
    radius:float=1.
    piece_index: int | None = None
    result_kind: str | None = None
    remove_at: tuple | None = None
    distance: float | None = None
    fill: bool = False
    solid: bool = False
    offset_normal: tuple | None = None
    fillet_points: tuple = ()
    fillet_selection: tuple | None = None
    fillet_corner: tuple | None = None
    placement: tuple = ()
    morph_domains: tuple = ()
    uv_trim: tuple = ()
    uv_view: tuple = ()
    face_index: int = 0
    periodic_u: bool = False
    region: tuple | None = None
    profile: tuple | None = None
    iso: tuple = ()
    box_corners: tuple = ()

    def __post_init__(self):
        from .solids import SolidValue
        from .moves import TranslatedValue, RigidValue, is_geometry
        if not isinstance(self.key,str) or not 0<len(self.key)<=256 or self.kind not in OPERATION_SPECS:
            raise ValueError('Invalid geometry operation recipe.')
        if self.kind not in TOPOLOGY_SOURCE_LIMITS and (self.piece_index is not None or self.result_kind is not None):
            raise ValueError('Unexpected topology piece fields.')
        if self.kind == REGION_BOOLEAN:
            if not isinstance(self.region, (tuple, list)) or len(self.region) != 2:
                raise ValueError('Invalid Region Boolean options.')
            object.__setattr__(self, 'region', region_parameters(*self.region, len(self.sources)))
        elif self.region is not None:
            raise ValueError('Unexpected region options.')
        if self.kind == 'trim':
            from .curves import xyz
            object.__setattr__(self, 'remove_at', xyz(self.remove_at))
        elif self.remove_at is not None:
            raise ValueError('Only Trim accepts a Remove At point.')
        if not isinstance(self.sources, tuple) or not all(
                is_geometry(v) if self.kind in (*placement.PLACEMENT_SPECS, 'bounding_box', 'surface_morph', 'box_morph',
                                                SCALE_NON_UNIFORM, *PROFILE_SPECS) else
                isinstance(v, (CurveValue, SolidValue, OperationValue, TranslatedValue, RigidValue, SurfaceReferenceValue))
                for v in self.sources):
            raise ValueError('Operation sources must be deferred geometry.')
        if self.kind != fillet_edges.FILLET_EDGE and (self.fillet_points or self.fillet_selection is not None):
            raise ValueError('Unexpected Fillet Edge fields.')
        if any(type(v) is not bool for v in (self.cap,self.closed,self.ruled,self.adjust)):
            raise ValueError('Operation flags must be Boolean.')
        if not isinstance(self.axis,PlaneValue):
            raise ValueError('Invalid revolution axis.')
        if self.kind == 'surface_morph':
            from .morph import is_box, morph_domains
            if len(self.sources) != 3 or not is_box(self.sources[1]):
                raise ValueError('Surface Morph requires geometry, a reference box and a target surface.')
            object.__setattr__(self, 'morph_domains', morph_domains(self.morph_domains))
        elif self.morph_domains:
            raise ValueError('Only Surface Morph accepts morph domains.')
        if self.kind == SURFACE_BOX:
            from .morph import cage_corners
            if self.sources:
                raise ValueError('Surface Box stores measured corners.')
            object.__setattr__(self, 'box_corners', cage_corners(self.box_corners))
        elif self.box_corners:
            raise ValueError('Only Surface Box stores box corners.')
        if self.kind == 'box_morph':
            from .morph import is_box, is_target_box
            if len(self.sources) != 3 or not is_box(self.sources[1]) or not is_target_box(self.sources[2]):
                raise ValueError('Box Morph requires geometry, a reference box and a target box.')
        if self.kind == 'project':
            if len(self.sources) != 1 or not is_curve_recipe(self.sources[0]):
                raise ValueError('Project needs one curve per deferred recipe.')
            projection_direction(self.axis, self.vector)
        if self.kind == 'isotrim':
            from .isotrim import checked_intervals
            from .splines import integer
            object.__setattr__(self, 'uv_trim', checked_intervals(self.uv_trim))
            if self.uv_view:
                object.__setattr__(self, 'uv_view', checked_intervals(self.uv_view))
            object.__setattr__(self, 'face_index', integer(self.face_index, 'Face Index', 0, MAX_ITEMS))
        elif self.kind == SURFACE_ISOCURVES:
            from .splines import integer
            from .surface_uv import is_uv_geometry
            if (len(self.sources) != 1 or not is_uv_geometry(self.sources[0])
                    or is_curve_recipe(self.sources[0]) or self.uv_trim or self.uv_view):
                raise ValueError('Surface Isocurves needs one BREP surface and a native span.')
            object.__setattr__(self, 'face_index', integer(self.face_index, 'Face Index', 0, MAX_ITEMS))
            object.__setattr__(self, 'iso', iso_span(self.iso))
        elif self.uv_trim or self.uv_view or self.face_index:
            raise ValueError('Unexpected surface UV selection.')
        if self.kind != SURFACE_ISOCURVES and self.iso:
            raise ValueError('Unexpected isocurve span.')
        if self.kind == SCALE_NON_UNIFORM:
            object.__setattr__(self, 'vector', scale_factors(self.vector))
        if self.kind == 'offset':
            from .curves import unit, xyz
            distance = finite_number(self.distance)
            if not 1e-8 <= abs(distance) <= 1e7:
                raise ValueError('Offset Distance must be nonzero and have magnitude 1e-8 to 1e7.')
            if type(self.fill) is not bool or type(self.solid) is not bool or self.fill and self.solid:
                raise ValueError('Offset needs one result mode. Choose Fill or Solid.')
            object.__setattr__(self, 'distance', distance)
            if self.offset_normal is not None:
                normal = xyz(self.offset_normal)
                if abs(math.hypot(*normal) - 1.) > 8 * math.ulp(1.):
                    normal = unit(normal)
                object.__setattr__(self, 'offset_normal', normal)
        if type(self.periodic_u) is not bool or self.periodic_u and self.kind != 'surface_from_points':
            raise ValueError('Periodic U is a Boolean option for Surface from Points.')
        if self.kind=='surface_from_points':
            from .curves import xyz
            from .splines import integer
            if self.sources or not isinstance(self.points,tuple) or not 4<=len(self.points)<=2500:
                raise ValueError('Surface from Points requires 4..2500 ordered points per branch.')
            points=tuple(xyz(p) for p in self.points)
            u=integer(self.u_count,'Points per Row',4 if self.periodic_u else 2,1250)
            if len(points)%u or len(points)//u<2:
                raise ValueError('Point count must be U × V, with U and V at least 2.')
            object.__setattr__(self,'points',points)
            object.__setattr__(self,'u_count',u)
        elif self.points:
            raise ValueError('Only Surface from Points stores point samples.')
        if self.kind == 'cap_holes' and (
                len(self.sources) != 1 or not is_boolean_operand(self.sources[0], solid_only=False)):
            raise ValueError('Cap Holes needs one open BREP per item.')
        if self.kind=='sweep1':
            if len(self.sources)!=2 or not all(map(is_curve_recipe, self.sources)):
                raise ValueError('Sweep 1 Rail needs one Rail Curve and one Profile Curve per item.')
        elif self.kind in ('sweep2','birail_sweep'):
            if len(self.sources)!=3 or not all(map(is_curve_recipe, self.sources)):
                raise ValueError('Sweep needs Rail 1, Rail 2 and one Profile Curve per item.')
            if self.kind=='birail_sweep':
                from .splines import integer
                object.__setattr__(self,'rail_samples',integer(self.rail_samples,'Rail Samples',4,129))
                object.__setattr__(self,'profile_samples',integer(self.profile_samples,'Profile Samples',4,129))
                if self.rail_samples*self.profile_samples>10000:
                    raise ValueError('BiRail Sweep exceeds the 10000-sample grid limit per part.')
        elif self.kind in ('planar_surface','edge_surface','patch'):
            low,high=(2,4) if self.kind=='edge_surface' else (1,240)
            if not low<=len(self.sources)<=high or not all(map(is_curve_recipe, self.sources)):
                raise ValueError(f'{OPERATION_SPECS[self.kind]["name"]} needs {low}..{high} curves per branch.')
            if len({signature(v) for v in self.sources})!=len(self.sources):
                raise ValueError('Duplicate boundary in one surface branch.')
        elif self.kind=='loft':
            if not (3 if self.closed else 2)<=len(self.sources)<=240 or not all(map(is_curve_recipe, self.sources)):
                raise ValueError('Loft needs 2..240 curves per branch; Closed needs at least 3.')
            # Part keys are scoped to their source owner, not globally unique:
            # two independent curve nodes can use the same local slot key.
            if len({signature(v) for v in self.sources})!=len(self.sources):
                raise ValueError('Duplicate section in one Loft branch.')
        elif self.kind == map_surface.MAP_SURFACE:
            if len(self.sources) != 3 or not is_curve_recipe(self.sources[0]):
                raise ValueError('Map Surface requires a curve and two surfaces.')
        elif self.kind in ('bounding_box', 'surface_morph'):
            if not 1 <= len(self.sources) <= 240:
                raise ValueError('Bounding Box needs 1–240 geometry items per box.')
        elif self.kind == fillet_curves.FILLET_PARAMETRIC:
            from .curves import xyz
            if len(self.sources) != 2 or not all(map(is_curve_recipe, self.sources)):
                raise ValueError('Fillet requires two curves.')
            object.__setattr__(self, 'fillet_corner', xyz(self.fillet_corner))
            object.__setattr__(self, 'radius', fillet_curves.checked_radius(self.radius))
        elif self.kind in PARAMETRIC_BOOLEANS:
            max_operands = 101 if self.kind == 'boolean_difference_parametric' else 100
            if not 2 <= len(self.sources) <= max_operands or not all(map(is_boolean_operand, self.sources)):
                raise ValueError('Boolean recipes require a valid collection of solid operands.')
        elif self.kind in TOPOLOGY_SOURCE_LIMITS:
            if (type(self.piece_index) is not int or not 0 <= self.piece_index < 10000
                    or self.result_kind not in PIECE_KINDS):
                raise ValueError('Invalid topology piece.')
            minimum, maximum = TOPOLOGY_SOURCE_LIMITS[self.kind]
            if not minimum <= len(self.sources) <= maximum:
                raise ValueError('Invalid topology operation sources.')
            if self.kind == SECTION and (self.result_kind not in ('curve', 'surface')
                    or not is_boolean_operand(self.sources[0], solid_only=False)):
                raise ValueError('Section needs a surface or solid BREP.')
            if self.kind == BOOLEAN_SPLIT_PARAMETRIC and (
                    self.result_kind != 'solid' or not is_boolean_operand(self.sources[0])):
                raise ValueError('Boolean Split needs a solid target and solid result pieces.')
            if self.kind == REGION_BOOLEAN and self.result_kind not in ('curve', 'surface'):
                raise ValueError('Region Boolean only returns regions and outlines.')
            if self.kind == CURVE_CURVE and self.result_kind != 'curve':
                raise ValueError('Only Curve–Curve overlaps require a topology recipe.')
            if self.kind in PROFILE_SPECS:
                if self.result_kind != 'curve' or not all(map(is_curve_recipe, self.sources)):
                    raise ValueError('Curve profiles need curve sources and results.')
                options = profile_options(self.kind, self.profile)
                if self.kind == SHATTER and (options[0] or len(options[1]) != 2 or options[1][0] >= options[1][1]):
                    raise ValueError('Shatter fragments need an increasing native parameter interval.')
                object.__setattr__(self, 'profile', options)
        elif self.kind not in ('surface_from_points', SURFACE_BOX, 'box_morph') and len(self.sources)!=1:
            raise ValueError('This operation requires one source per item.')
        if self.kind not in PROFILE_SPECS and self.profile is not None:
            raise ValueError('Unexpected curve profile parameters.')
        if self.kind in ('array', 'objects_on_points'):
            from .curves import xyz
            object.__setattr__(self, 'vector', xyz(self.vector))
            if self.kind == 'objects_on_points':
                if not isinstance(self.placement, (list, tuple)) or len(self.placement) != 2:
                    raise ValueError('Invalid placement settings.')
                normal, factors = self.placement
                normal = xyz(normal)
                if abs(math.hypot(*normal)-1.) > 1e-12:
                    normal = unit(normal)
                object.__setattr__(self, 'placement', (normal, placement.placement_scale(factors)))
        if self.kind == 'array_polar':
            object.__setattr__(self, 'angle', finite(self.angle))
            if abs(self.angle) > 360:
                raise ValueError('Invalid polar copy angle.')
        if self.kind == 'pipe':
            radius = finite(self.radius)
            if radius <= 1e-9 or not is_curve_recipe(self.sources[0]):
                raise ValueError('Pipe requires a rail curve and a positive radius.')
            object.__setattr__(self, 'radius', radius)
        if self.kind == fillet_edges.FILLET_EDGE:
            from .curves import xyz
            radius = finite(self.radius)
            if radius < 0 or not is_boolean_operand(self.sources[0]):
                raise ValueError('Fillet Edge needs a closed solid and a nonnegative radius.')
            if (not isinstance(self.fillet_points, (tuple, list)) or len(self.fillet_points) > fillet_edges.MAX_PICKS
                    or self.fillet_points and self.fillet_selection is not None):
                raise ValueError('Invalid Fillet Edge picks.')
            object.__setattr__(self, 'radius', radius)
            object.__setattr__(self, 'fillet_points', tuple(xyz(p) for p in self.fillet_points))
            if self.fillet_selection is not None:
                object.__setattr__(self, 'fillet_selection', fillet_edges.selection(self.fillet_selection))
        if self.kind=='revolve':
            if not is_curve_recipe(self.sources[0]):
                raise ValueError('Revolve requires a profile Curve.')
            angle=finite_number(self.angle)
            if not 1e-9<abs(angle)<=360:
                raise ValueError('Revolve requires 0 < abs(angle) <= 360 degrees.')
            object.__setattr__(self,'angle',angle)
        if self.kind=='extrude':
            vector=tuple(finite(v) for v in VectorValue(self.vector).xyz)
            if math.hypot(*vector)<=1e-9:
                raise ValueError('Extrude needs a nonzero Vector.')
            source = self.sources[0]
            if isinstance(source,SolidValue) and source.solid or isinstance(source,SurfaceReferenceValue) and source.native_kind == 'solid':
                raise ValueError('Extrude accepts Curve or Surface, not Solid.')
            object.__setattr__(self,'vector',vector)
        if self.depth>16 or self.complexity>10000:
            raise ValueError('Geometry operation exceeds the depth/recipe budget.')

    @property
    def depth(self):
        return 1+max((getattr(v,'depth',0) for v in self.sources),default=0)

    @property
    def complexity(self):
        samples = len(self.fillet_selection[1]) * fillet_edges.SAMPLE_COUNT if self.fillet_selection else 0
        return 1+len(self.points)+len(self.fillet_points)+samples+sum(getattr(v,'complexity',1) for v in self.sources)

    def to_wire(self):
        from .moves import geometry_wire
        result={'key':self.key,'kind':self.kind,'sources':[geometry_wire(v) for v in self.sources]}
        if self.kind=='extrude':
            result.update(vector=list(self.vector),cap=self.cap)
        elif self.kind == 'bounding_box':
            result['axis'] = self.axis.to_wire()
        elif self.kind == 'project':
            result.update(axis=self.axis.to_wire(), vector=list(self.vector))
        elif self.kind == 'surface_morph':
            result['morph_domains'] = self.morph_domains
        elif self.kind == SURFACE_BOX:
            result['box_corners'] = self.box_corners
        elif self.kind == 'isotrim':
            result.update(uv_trim=list(self.uv_trim), uv_view=list(self.uv_view), face_index=self.face_index)
        elif self.kind == SURFACE_ISOCURVES:
            result.update(iso=list(self.iso), face_index=self.face_index)
        elif self.kind == SCALE_NON_UNIFORM:
            result.update(axis=self.axis.to_wire(), vector=list(self.vector))
        elif self.kind == 'pipe':
            result.update(radius=self.radius, cap=self.cap)
        elif self.kind == fillet_curves.FILLET_PARAMETRIC:
            result.update(radius=self.radius, fillet_corner=list(self.fillet_corner))
        elif self.kind in ('array', 'objects_on_points'):
            result['vector'] = list(self.vector)
            if self.kind == 'objects_on_points':
                result['placement'] = [list(v) for v in self.placement]
        elif self.kind == 'array_polar':
            result.update(axis=self.axis.to_wire(), angle=self.angle)
        elif self.kind == fillet_edges.FILLET_EDGE:
            result['radius'] = self.radius
            if self.fillet_points:
                result['fillet_points'] = [list(p) for p in self.fillet_points]
            if self.fillet_selection is not None:
                result['fillet_selection'] = self.fillet_selection
        elif self.kind=='revolve':
            result.update(axis=self.axis.to_wire(),angle=self.angle)
        elif self.kind=='loft':
            result.update(closed=self.closed,ruled=self.ruled,adjust=self.adjust)
        elif self.kind=='surface_from_points':
            result.update(points=[list(p) for p in self.points],u_count=self.u_count)
            if self.periodic_u:
                result['periodic_u'] = True
        elif self.kind == 'offset':
            result.update(distance=self.distance, fill=self.fill, solid=self.solid)
            if self.offset_normal is not None:
                result['offset_normal'] = list(self.offset_normal)
        elif self.kind=='birail_sweep':
            result.update(rail_samples=self.rail_samples,profile_samples=self.profile_samples)
        elif self.kind in TOPOLOGY_SOURCE_LIMITS:
            result.update(piece_index=self.piece_index, result_kind=self.result_kind)
            if self.kind == 'trim':
                result['remove_at'] = list(self.remove_at)
            if self.kind in (SECTION, BOOLEAN_SPLIT_PARAMETRIC):
                result['axis'] = self.axis.to_wire()
            if self.kind == REGION_BOOLEAN:
                result['region'] = list(self.region)
            if self.profile is not None:
                result['profile'] = self.profile
        return result


def operation_from_wire(data,*,depth=0,budget=None):
    if depth>16 or not isinstance(data,dict) or data.get('kind') not in OPERATION_SPECS:
        raise ValueError('Invalid or excessively nested operation recipe.')
    budget=[10000] if budget is None else budget
    budget[0]-=1
    sources=data.get('sources')
    maximum = TOPOLOGY_SOURCE_LIMITS.get(data['kind'], (0, 240))[1]
    if not isinstance(sources,list) or len(sources)>maximum or len(sources)>budget[0]:
        raise ValueError('Invalid operation sources/budget.')
    from .solids import SOLID_SPECS,solid_from_wire
    from .grids import GRID_SPECS
    values=[]
    for source in sources:
        if not isinstance(source,dict):
            raise ValueError('Invalid operation source.')
        if source.get('kind') in ('translated','rigid_transform','grid_edit','point',*GRID_SPECS):
            from .moves import geometry_from_wire
            values.append(geometry_from_wire(source,depth+1,budget))
        elif source.get('kind') in OPERATION_SPECS:
            values.append(operation_from_wire(source,depth=depth+1,budget=budget))
        else:
            budget[0]-=1
            if budget[0]<0:
                raise ValueError('Operation recipe budget exceeded.')
            if source.get('kind') == SURFACE_REFERENCE_KIND:
                values.append(surface_reference_from_wire(source))
            else:
                values.append((solid_from_wire if source.get('kind') in SOLID_SPECS else curve_from_wire)(source))
    kind=data['kind']
    points=data.get('points',[])
    if not isinstance(points,list) or len(points)>2500 or len(points)>budget[0]:
        raise ValueError('Invalid point grid/recipe budget.')
    budget[0]-=len(points)
    axis=data.get('axis',{})
    if not isinstance(axis,dict):
        raise ValueError('Invalid revolution axis.')
    return OperationValue(data.get('key'),kind,tuple(values),tuple(data.get('vector',(0,0,10))),
        PlaneValue(**axis),data.get('angle',360.),data.get('cap',True),data.get('closed',False),
        data.get('ruled',False),data.get('adjust',True),tuple(points),data.get('u_count',2),
        data.get('rail_samples',33),data.get('profile_samples',25),data.get('radius',1.),
        data.get('piece_index'), data.get('result_kind'), data.get('remove_at'),
        data.get('distance'), data.get('fill', False), data.get('solid', False), data.get('offset_normal'),
        data.get('fillet_points', ()), data.get('fillet_selection'), data.get('fillet_corner'), data.get('placement', ()),
        data.get('morph_domains', ()), data.get('uv_trim', ()), data.get('uv_view', ()), data.get('face_index', 0),
        periodic_u=data.get('periodic_u', False), region=data.get('region'), profile=data.get('profile'),
        iso=data.get('iso', ()), box_corners=data.get('box_corners', ()))


def projection_direction(frame, direction=None):
    direction = frame.normal if direction is None else unit(VectorValue(direction).xyz)
    if abs(dot(direction, frame.normal)) <= 1e-12:
        raise ValueError('Project direction cannot be parallel to the plane.')
    return direction


def project_point(point, frame, direction):
    height = dot(sub(point, frame.origin), frame.normal)
    return sub(point, scale(direction, height / dot(direction, frame.normal)))


def normalize_operation_state(operation,data):
    if operation in SURFACE_REFERENCE_OPS:
        state = normalize_curve_state(operation, data, spec=OPERATION_SPECS[operation],
                                      decoder=surface_reference_from_wire, reference_kind=SURFACE_REFERENCE_KIND)
        refs = state['references']
        if len(refs) > MAX_REFERENCE_OBJECTS or sum(len(r['recipe']['brep']) for r in refs) > MAX_REFERENCE_ARCHIVES:
            raise ValueError('Surface references exceed the archive or object limit.')
        if any(operation != 'loft' and r['recipe']['native_kind'] != 'surface'
               or operation == 'planar_surface' and 'normal' not in r['recipe'] for r in refs):
            raise ValueError('Reference geometry does not match this surface operation.')
        return state
    state=normalize_curve_state(operation,data,spec=OPERATION_SPECS[operation],decoder=operation_from_wire)
    if operation == 'surface_from_points':
        periodic = data.get('parameters', {}).get('periodic_u', False)
        if type(periodic) is not bool:
            raise ValueError('Periodic U must be Boolean.')
        state['parameters']['periodic_u'] = periodic
    if operation == 'bounding_box':
        mode = data.get('parameters', {}).get('box_mode', 'per_object')
        if mode not in ('per_object', 'union'):
            raise ValueError('Invalid Bounding Box mode.')
        state['parameters']['box_mode'] = mode
    if operation == REGION_BOOLEAN:
        mode = data.get('parameters', {}).get('region_mode', 'Union')
        if mode not in REGION_MODES:
            raise ValueError('Invalid Region Boolean mode.')
        state['parameters']['region_mode'] = mode
    if operation == fillet_edges.FILLET_EDGE:
        state['parameters'].update(fillet_edges.normalize_parameters(data.get('parameters', {})))
    if operation == 'offset':
        raw = data.get('parameters', {})
        fill, solid = raw.get('fill', False), raw.get('solid', False)
        if type(fill) is not bool or type(solid) is not bool or fill and solid:
            raise ValueError('Offset needs one result mode. Choose Fill or Solid.')
        state['parameters'].update(fill=fill, solid=solid)
    if operation in SHOW_PARENT_OPERATIONS:
        show_parent = data.get('parameters', {}).get('show_parent', True)
        if type(show_parent) is not bool:
            raise ValueError('Show Parent must be Boolean.')
        state['parameters']['show_parent'] = show_parent
    if state['mode']!='generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Operations use connected geometry; capture source curves with their Reference nodes.')
    return state


def _surface_reference_outputs(operation, state, error):
    if error:
        raise ValueError(error)
    values = tuple(surface_reference_from_wire(ref['recipe']) for ref in state['references'])
    if not values:
        raise ValueError('Select matching native objects, then click Set reference.')
    tree = topology(DataTree((Branch((0,), values, tuple(v.key for v in values)),)),
                    state['tree_modes'].get('References', 'none'))

    def mapped(fn):
        return DataTree(tuple(Branch(b.path, tuple(fn(v) for v in b.items), b.keys) for b in tree.branches))

    result = {'G': tree, 'K': mapped(lambda v: v.native_kind), 'Count': tree.count}
    if operation == 'loft':
        result['SC'] = DataTree(tuple(Branch(b.path, ()) for b in tree.branches))
    else:
        result['EC'] = mapped(lambda v: v.edge_count)
        if operation == 'planar_surface':
            result['N'] = mapped(lambda v: VectorValue(v.normal))
    return result


def axis_frame(value):
    if isinstance(value,PlaneValue):
        return value
    direction=unit(sub(value.points[1],value.points[0]))
    seed=min(((1,0,0),(0,1,0),(0,0,1)),key=lambda v:abs(sum(a*b for a,b in zip(v,direction))))
    return PlaneValue(value.points[0],seed,direction)


def plane_surface(key, frame, x, y):
    boundary = rectangle(key + ':boundary', x, y, frame.origin, frame)
    return OperationValue(key, 'planar_surface', (boundary,))


def evaluate_plane_surface(state, inputs):
    trees = [input_tree(inputs.get(d.port, state['parameters'][d.port]), d,
                        state['tree_modes'].get(d.port, 'none'), d.port not in inputs)
             for d in PLANE_SURFACE_SPEC['inputs']]
    branches = []
    for path, rows in aligned(*matched_inputs(trees)):
        surfaces = tuple(plane_surface(hashlib.sha256(repr((path, i, keys)).encode()).hexdigest()[:24], *args)
                         for i, (args, keys) in enumerate(rows))
        branches.append(Branch(path, surfaces, tuple(s.key for s in surfaces)))
    return {'P': DataTree(tuple(branches))}


def evaluate_operation(operation,parameters,inputs,bindings=None):
    if operation == DECONSTRUCT:
        from .surface_structure import evaluate
        return evaluate(operation, parameters, inputs)
    state=normalize_operation_state(operation,parameters)
    if operation in (SECTION, CONTOUR):
        return evaluate_section(operation, state, inputs, parameters.get('sampling_details') or {})
    if operation in (CURVE_CURVE, REGION_BOOLEAN):
        return evaluate_intersections(operation, state, inputs, parameters.get('sampling_details') or {})
    if operation in PROFILE_SPECS:
        return evaluate_profiles(operation, state, inputs, parameters.get('sampling_details') or {})
    if operation == SURFACE_ISOCURVES:
        return evaluate_isocurves(state, inputs, parameters.get('sampling_details') or {})
    if operation in TOPOLOGY_OPERATIONS:
        return evaluate_topology(operation, state, inputs, parameters.get('sampling_details') or {})
    if state['mode'] == 'reference':
        return _surface_reference_outputs(operation, state, parameters.get('reference_error'))
    if operation in ('bounding_box', 'surface_morph', 'box_morph'):
        from .morph import evaluate
        return evaluate(operation, state, inputs)
    if operation == 'isotrim':
        from .isotrim import evaluate
        return evaluate(state, inputs)
    if operation in (*placement.PLACEMENT_SPECS, map_surface.MAP_SURFACE):
        occurrences = {}
        def key(provenance):
            count = occurrences.get(provenance, 0)
            occurrences[provenance] = count + 1
            return hashlib.sha256(repr((provenance, count)).encode()).hexdigest()[:24]
        if operation == map_surface.MAP_SURFACE:
            return map_surface.evaluate(state, inputs, key)
        return placement.evaluate(operation, {**state, 'name': parameters.get('node_name', 'Objects on Points')}, inputs, key)
    spec=OPERATION_SPECS[operation]
    trees = []
    for descriptor in spec['inputs']:
        port = descriptor.port
        if operation == fillet_edges.FILLET_EDGE and port == 'E' and state['parameters']['fillet_mode'] == 'all':
            continue
        if descriptor.optional and port not in inputs:
            continue
        value = inputs.get(port, state['parameters'].get(port))
        if descriptor.kind == 'surface_u' and port not in inputs and value == 'auto':
            if not trees[0].count:
                trees.append(DataTree(()))
                continue
            # Read the row layout from the incoming tree, retaining U in the
            # recipe even though the P modifier has joined the point branches.
            value = (rectangular_row_width(inputs['P'])
                     if state['tree_modes'].get('P') == 'flatten' else None)
            if value is None:
                raise ValueError('Auto U needs consecutive rows with equal point counts and Flatten on P. Set U manually for other point data.')
        trees.append(input_tree(value, descriptor, state['tree_modes'].get(port, 'none'), port not in inputs))
    records=[]
    occurrences={}
    def key(provenance):
        text=json.dumps(provenance)
        count=occurrences.get(text,0)
        occurrences[text]=count+1
        return hashlib.sha256(f'{text}:{count}'.encode()).hexdigest()[:24]
    if operation == fillet_edges.FILLET_EDGE:
        records.extend(fillet_edges.recipe_branches(state['parameters'], trees, bindings or {}, key))
    elif operation == fillet_curves.FILLET_PARAMETRIC:
        for path, rows in fillet_curves.slots(trees):
            values = []
            for (a, b, near, radius), provenance in rows:
                if a == b:
                    raise ValueError('A curve cannot be filleted with itself.')
                values.append(OperationValue(key((path, *provenance)), operation, (a, b),
                                             radius=radius, fillet_corner=near.xyz))
            records.append(Branch(path, tuple(values), tuple(v.key for v in values)))
    elif operation in PARAMETRIC_BOOLEANS:
        slots = 0
        for path, group in boolean_slots(operation, trees, bindings or {}):
            slots += len(group)
            if slots > 250:
                raise ValueError('Boolean operations support up to 250 result slots.')
            values = tuple(OperationValue(key((path, provenance)), operation, operands)
                           for operands, provenance in group)
            records.append(Branch(path, values, tuple(v.key for v in values)))
    elif operation in ('loft','planar_surface','edge_surface','surface_from_points','patch'):
        sections=trees[0]
        # Section input is a list per branch; options are single items per branch.
        paths={b.path for b in sections.branches}
        option_trees=trees[1:]
        for tree in option_trees:
            if len(tree.branches)>1 and {b.path for b in tree.branches}!=paths:
                    raise ValueError('Operation option branches must match source paths explicitly.')
        for branch in sections.branches:
            if not branch.items:
                records.append(Branch(branch.path,()))
                continue
            args=[]
            provenance=list(branch.keys)
            for tree in option_trees:
                option=next((b for b in tree.branches if b.path==branch.path),tree.branches[0] if len(tree.branches)==1 else None)
                if option is None or len(option.items)!=1:
                    raise ValueError('Operation needs one value per option and source branch.')
                args.append(option.items[0])
                provenance.extend(option.keys)
            if operation=='loft':
                kind, closed, adjust = args[:3]
                if len(args) == 4:
                    options = args[3]
                    if options.rebuild or options.refit:
                        raise ValueError('Loft does not support native Rebuild or Refit.')
                    kind = kind if 'T' in inputs else options.loft_type
                    closed = closed if 'Cl' in inputs else options.closed
                    adjust = adjust if 'A' in inputs else options.adjust
                value=OperationValue(key(provenance),operation,branch.items,closed=closed,ruled=bool(kind),adjust=adjust)
            elif operation=='surface_from_points':
                value=OperationValue(key(provenance),operation,(),points=tuple(p.xyz for p in branch.items),
                                     u_count=args[0], periodic_u=state['parameters']['periodic_u'])
            else:
                value=OperationValue(key(provenance),operation,branch.items)
            records.append(Branch(branch.path,(value,),(value.key,)))
    else:
        trees=matched_inputs(trees)
        for path,rows in aligned(*trees):
            widths=[len((next((b for b in t.branches if b.path==path),None) or t.branches[0]).items) for t in trees if t.branches]
            if widths and any(w not in (0,1,max(widths)) for w in widths):
                raise ValueError('Operation lists must have equal lengths or one item. Match the DataTree explicitly.')
            values=[]
            for items,provenance in rows:
                if operation=='extrude':
                    source,vector,cap=items
                    value=OperationValue(key(provenance),operation,(source,),vector=vector.xyz,cap=cap)
                elif operation == 'pipe':
                    rail, radius, cap = items
                    value = OperationValue(key(provenance), operation, (rail,), cap=cap, radius=radius)
                elif operation == 'offset':
                    source, distance, *plane = items
                    value = OperationValue(key(provenance), operation, (source,), distance=distance,
                        fill=state['parameters']['fill'], solid=state['parameters']['solid'],
                        offset_normal=plane[0].normal if plane else None)
                elif operation == 'project':
                    source, frame, *direction = items
                    direction = projection_direction(frame, direction[0].xyz if direction else None)
                    slot = key(provenance)
                    value = (PointValue(slot, project_point(source.xyz, frame, direction))
                             if isinstance(source, PointValue) else
                             OperationValue(slot, operation, (source,), vector=direction, axis=frame))
                elif operation == SCALE_NON_UNIFORM:
                    source, frame, *factors = items
                    factors = scale_factors(factors)
                    slot = key(provenance)
                    value = (PointValue(slot, scale_point(source.xyz, frame, factors))
                             if isinstance(source, PointValue) else
                             OperationValue(slot, operation, (source,), vector=factors, axis=frame))
                elif operation == 'cap_holes':
                    value = OperationValue(key(provenance), operation, tuple(items))
                elif operation=='sweep1':
                    value=OperationValue(key(provenance),operation,tuple(items))
                elif operation in ('sweep2','birail_sweep'):
                    value=OperationValue(key(provenance),operation,tuple(items[:3]),
                        rail_samples=items[3] if operation=='birail_sweep' else 33,
                        profile_samples=items[4] if operation=='birail_sweep' else 25)
                else:
                    source,axis,angle=items
                    value=OperationValue(key(provenance),operation,(source,),axis=axis_frame(axis),angle=angle)
                values.append(value)
            records.append(Branch(path,tuple(values),tuple(v.key for v in values)))
    tree=DataTree(tuple(records))
    if sum(getattr(v, 'complexity', 1) for v in tree.values())>10000:
        raise ValueError('Operation collection exceeds the 10000-recipe budget.')
    if operation in ('project', SCALE_NON_UNIFORM):
        return {'G': tree}
    def mapped(fn):
        return DataTree(tuple(Branch(b.path,tuple(fn(v) for v in b.items),b.keys) for b in tree.branches))
    def native_kind(value):
        record=parameters.get('curve_details',{}).get(value.key,{})
        return record['kind'] if record.get('signature')==signature(value) else PendingGeometry('Waiting for native geometry classification')
    if operation == 'cap_holes':
        return {'B': tree, 'K': mapped(native_kind)}
    result={'G':tree,'K':mapped(native_kind),'Count':tree.count}
    if operation == 'offset':
        result['D'] = mapped(lambda value: value.distance)
    if operation in PARAMETRIC_BOOLEANS:
        result['Flat'] = topology(tree, 'flatten')
    if operation == fillet_curves.FILLET_PARAMETRIC:
        return {'G': tree, 'R': mapped(lambda v: v.radius), 'Count': tree.count,
                'Flat': topology(tree, 'flatten')}
    if operation=='loft':
        result['SC']=mapped(lambda v:len(v.sources))
    if operation in ('planar_surface','edge_surface','patch'):
        def detail(value,name):
            record=parameters.get('curve_details',{}).get(value.key,{})
            if record.get('signature')!=signature(value) or name not in record:
                return PendingGeometry('Waiting for native surface measurement')
            return VectorValue(tuple(record[name])) if name=='normal' else record[name]
        result['EC']=mapped(lambda v:detail(v,'edge_count'))
        if operation=='planar_surface':
            result['N']=mapped(lambda v:detail(v,'normal'))
    if operation=='surface_from_points':
        result.update(U=mapped(lambda v:v.u_count),V=mapped(lambda v:len(v.points)//v.u_count))
    return result


def operation_object_from_outputs(parameters,outputs):
    if parameters['primitive'] == DECONSTRUCT:
        return None
    mode = parameters.get('mode', 'generate')
    refs = tuple((r['key'], r['id']) for r in parameters.get('references', ())) if mode == 'reference' else ()
    port = OPERATION_SPECS[parameters['primitive']]['primary']
    parts = outputs[port]
    secondary = SECONDARY_GEOMETRY_PORTS.get(parameters['primitive'])
    if secondary is not None:
        parts = DataTree(tuple(Branch(a.path, a.items+b.items, a.keys+b.keys)
                               for a, b in zip(parts.branches, outputs[secondary].branches, strict=True)))
    indexed = (parameters['primitive'] == map_surface.MAP_SURFACE and parts.count and
               map_surface.is_indexable(tuple(part.sources[0] for part in parts.values())))
    return ParametricObject(parameters['project_uuid'],parameters['node_uuid'],parts,mode,refs,
                            kind='mapped_tessellation' if indexed else 'operations')


def operation_object_from_wire(data):
    budget=[10000]
    from .moves import geometry_from_wire

    def decode(part):
        if isinstance(part, dict) and part.get('kind') == 'point':
            return geometry_from_wire(part, budget=budget)
        return operation_from_wire(part, budget=budget)

    return curve_object_from_wire(data, decoder=decode, kind='operations')
