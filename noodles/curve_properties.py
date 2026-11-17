"""Generate parameters and live Reference capture, following Point Properties."""
import copy
from Qt import QtCore, QtGui, QtWidgets

from .backend.geometry import GEOMETRY_SPECS
from .backend.curves import POPULATION_COUNT_LIMITS, input_tree
from .backend.grids import GRID_SPECS, POINT_GROUPINGS
from .backend.list_nodes import CROSS_REFERENCE_MODES, POINT_SORT_ORDERS
from .backend.curve_sampling import MAX_DIVISIONS
from .backend.surface_reference import ARCHIVED_REFERENCE_OPS
from .backend.curve_collection import CURVES
from .backend.delaunay_node import HEXAGON_TILING, TESSELLATION_SPECS
from .backend.mesh_nodes import DELAUNAY_MESH
from .backend.penrose import MAX_GENERATIONS
from .backend.penrose_node import PENROSE
from .backend.surface_structure import MAX_DIVISIONS as MAX_BRACED_DIVISIONS
from .backend.datatree import MAX_ITEMS
from .backend.moves import inactive_motion_ports
from .backend.fillet_edges import FILLET_EDGE, inactive_ports as inactive_fillet_ports
from .backend.booleans import (BOOLEAN_SPLIT, BOOLEAN_SPLIT_PARAMETRIC, NATIVE_SCENE_OPERATIONS,
                               PARAMETRIC_BOOLEANS, SHOW_PARENT_OPERATIONS)
from .backend.fillet_curves import FILLET
from .backend.topology_operations import REGION_BOOLEAN, REGION_MODES
from .backend.table_data import choice_entries
from .backend.previews import MAX_UV_GRID_DIVISIONS, UV_GRID_PREVIEW
from .point_properties import PointProperties, TreeButtons, text
from .widgets import InputStack, NumberField, add_field
from .tree_preview import TreePreview


class CurveProperties(QtWidgets.QWidget):
    edited = QtCore.Signal(str, object)
    set_reference = QtCore.Signal()
    apply_boolean = QtCore.Signal()
    _show_status = PointProperties._show_status
    _apply_status = PointProperties._apply_status
    reset_status = PointProperties.reset_status

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(text('PARAMETERS', True))
        source = QtWidgets.QWidget()
        self.source_modes = source
        source.setObjectName('SliderMode')
        row = QtWidgets.QHBoxLayout(source)
        row.setContentsMargins(3, 3, 3, 3)
        self.sources = {}
        for mode in ('generate', 'reference'):
            button = QtWidgets.QPushButton(mode.title())
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, m=mode: self.edited.emit('mode', m))
            row.addWidget(button)
            self.sources[mode] = button
        layout.addWidget(source)
        self.grid_grouping_row = QtWidgets.QWidget()
        grouping_layout = QtWidgets.QVBoxLayout(self.grid_grouping_row)
        grouping_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_grouping = QtWidgets.QComboBox()
        self.grid_grouping.setAccessibleName('Point grouping')
        for grouping in POINT_GROUPINGS:
            self.grid_grouping.addItem(grouping.title(), grouping)
        self.grid_grouping.currentIndexChanged.connect(self._point_grouping)
        add_field(grouping_layout, 'Point grouping', self.grid_grouping)
        self.grid_grouping_row.hide()
        layout.addWidget(self.grid_grouping_row)
        self.box_mode_row = QtWidgets.QWidget()
        box_layout = QtWidgets.QVBoxLayout(self.box_mode_row)
        box_layout.setContentsMargins(0, 0, 0, 0)
        self.box_mode = QtWidgets.QComboBox()
        self.box_mode.setAccessibleName('Bounding Box mode')
        self.box_mode.addItem('Per Object', 'per_object')
        self.box_mode.addItem('Union', 'union')
        self.box_mode.currentIndexChanged.connect(lambda: self._parameter('box_mode', self.box_mode.currentData()))
        add_field(box_layout, 'Mode', self.box_mode)
        self.box_mode_row.hide()
        layout.addWidget(self.box_mode_row)
        self.region_mode_row = QtWidgets.QWidget()
        region_layout = QtWidgets.QVBoxLayout(self.region_mode_row)
        region_layout.setContentsMargins(0, 0, 0, 0)
        self.region_mode = QtWidgets.QComboBox()
        self.region_mode.setAccessibleName('Region Boolean mode')
        self.region_mode.addItems(REGION_MODES)
        self.region_mode.currentTextChanged.connect(lambda mode: self._parameter('region_mode', mode))
        add_field(region_layout, 'Mode', self.region_mode)
        self.region_mode_row.hide()
        layout.addWidget(self.region_mode_row)
        self.cross_pairing_row = QtWidgets.QWidget()
        pairing_layout = QtWidgets.QVBoxLayout(self.cross_pairing_row)
        pairing_layout.setContentsMargins(0, 0, 0, 0)
        self.cross_pairing = QtWidgets.QComboBox()
        self.cross_pairing.setAccessibleName('Cross Reference pairing')
        for value, label in CROSS_REFERENCE_MODES.items():
            self.cross_pairing.addItem(label, value)
        self.cross_pairing.currentIndexChanged.connect(
            lambda: self._parameter('pairing', self.cross_pairing.currentData()))
        add_field(pairing_layout, 'Pairing', self.cross_pairing)
        self.cross_pairing_row.hide()
        layout.addWidget(self.cross_pairing_row)
        self.point_sort_row = QtWidgets.QWidget()
        sort_layout = QtWidgets.QVBoxLayout(self.point_sort_row)
        sort_layout.setContentsMargins(0, 0, 0, 0)
        self.point_sort_order = QtWidgets.QComboBox()
        self.point_sort_order.setAccessibleName('Axis Order')
        self.point_sort_order.addItems(POINT_SORT_ORDERS)
        self.point_sort_order.currentTextChanged.connect(lambda order: self._parameter('axis_order', order))
        add_field(sort_layout, 'Axis Order', self.point_sort_order)
        self.point_sort_row.hide()
        layout.addWidget(self.point_sort_row)
        self.show_parent = QtWidgets.QCheckBox('Show Parent')
        self.show_parent.setToolTip('Show the source objects in Serpentine.')
        self.show_parent.toggled.connect(lambda checked: self._parameter('show_parent', checked))
        self.show_parent.hide()
        layout.addWidget(self.show_parent)
        self.periodic_u = QtWidgets.QCheckBox('Periodic U')
        self.periodic_u.setToolTip('Wrap the U sides of a rectangular boundary.')
        self.periodic_u.toggled.connect(lambda checked: self._parameter('periodic_u', checked))
        self.periodic_u.hide()
        layout.addWidget(self.periodic_u)
        self.matching_arcs = QtWidgets.QCheckBox('Matching Arcs')
        self.matching_arcs.setToolTip('Add circular matching marks to the tiles.')
        self.matching_arcs.toggled.connect(lambda checked: self._parameter('matching_arcs', checked))
        self.matching_arcs.hide()
        layout.addWidget(self.matching_arcs)
        self.offset_modes = QtWidgets.QWidget()
        offset_row = QtWidgets.QHBoxLayout(self.offset_modes)
        offset_row.setContentsMargins(0, 0, 0, 0)
        self.offset_checks = {}
        for mode, tip in (('fill', 'Create a surface between the curve and its offset.'),
                          ('solid', 'Thicken an open surface into a solid.')):
            box = QtWidgets.QCheckBox(mode.title())
            box.setToolTip(tip)
            box.toggled.connect(lambda checked, name=mode: self._offset_mode(name, checked))
            self.offset_checks[mode] = box
            offset_row.addWidget(box)
        self.offset_modes.hide()
        layout.addWidget(self.offset_modes)
        self.fillet_modes = QtWidgets.QWidget()
        self.fillet_modes.setObjectName('SliderMode')
        fillet_row = QtWidgets.QHBoxLayout(self.fillet_modes)
        fillet_row.setContentsMargins(3, 3, 3, 3)
        self.fillet_buttons = {}
        for mode in ('all', 'selected'):
            button = QtWidgets.QPushButton(mode.title())
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, m=mode: self._parameter('fillet_mode', m))
            fillet_row.addWidget(button)
            self.fillet_buttons[mode] = button
        layout.addWidget(self.fillet_modes)
        self.fillet_capture = QtWidgets.QPushButton('Set Edges')
        self.fillet_capture.setMinimumHeight(36)
        self.fillet_capture.setToolTip('Ctrl+Shift+click the edges in Serpentine, then click Set Edges.')
        self.fillet_capture.clicked.connect(self.set_reference.emit)
        layout.addWidget(self.fillet_capture)
        self.fillet_modes.hide()
        self.fillet_capture.hide()
        self.boolean_apply = QtWidgets.QPushButton('Apply Boolean')
        self.boolean_apply.setMinimumHeight(36)
        self.boolean_apply.clicked.connect(self.apply_boolean.emit)
        self.boolean_apply.hide()
        layout.addWidget(self.boolean_apply)
        self.native_action_error = text('')
        self.native_action_error.setWordWrap(True)
        self.native_action_error.hide()
        layout.addWidget(self.native_action_error)
        self.generate = QtWidgets.QWidget()
        self.generate_layout = QtWidgets.QVBoxLayout(self.generate)
        self.generate_layout.setContentsMargins(0, 0, 0, 0)
        self.generate_layout.setSpacing(10)
        self.reference = QtWidgets.QWidget()
        ref = QtWidgets.QVBoxLayout(self.reference)
        ref.setContentsMargins(0, 0, 0, 0)
        ref.setSpacing(10)
        ref.addWidget(text('REFERENCE', True))
        self.capture = QtWidgets.QPushButton('Set reference')
        self.capture.setMinimumHeight(36)
        self.capture.clicked.connect(self.set_reference.emit)
        ref.addWidget(self.capture)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(text('Objects'))
        self.reference_modifier = TreeButtons()
        self.reference_modifier.changed.connect(lambda mode: self._modifier('References', mode))
        row.addWidget(self.reference_modifier, 1)
        ref.addLayout(row)
        self.reference_count = text('')
        ref.addWidget(self.reference_count)
        self.reference_note = text('')
        self.reference_note.setWordWrap(True)
        ref.addWidget(self.reference_note)
        layout.addWidget(self.reference)
        layout.addWidget(self.generate)
        self.status = text('')
        self.status.setWordWrap(True)
        self.status.setObjectName('SecondaryText')
        layout.addWidget(self.status)
        self._node_id = None
        self._operation = None
        self._pending_status = None
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(180)
        self._status_timer.timeout.connect(self._apply_status)

    def _build(self, operation):
        while self.generate_layout.count():
            item = self.generate_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        body = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if GEOMETRY_SPECS[operation]['inputs']:
            layout.addWidget(text('INPUTS', True))
        if operation == 'value_list':
            self.choice_picker = QtWidgets.QComboBox()
            self.choice_picker.currentIndexChanged.connect(lambda index: self._parameter('selection', index))
            add_field(layout, 'Selected', self.choice_picker)
            self.choice_options = QtWidgets.QPlainTextEdit()
            self.choice_options.setAccessibleName('Value List options')
            self.choice_options.setPlaceholderText('Label = Value, one per line')
            self.choice_options.setFixedHeight(100)
            layout.addWidget(self.choice_options)
            self.choice_error = text('')
            self.choice_error.setWordWrap(True)
            self.choice_error.hide()
            layout.addWidget(self.choice_error)
            apply = QtWidgets.QPushButton('Apply Options')
            apply.clicked.connect(self._apply_choices)
            layout.addWidget(apply)
            self._loaded_options = None
        if operation in ('tree_branch', 'replace_paths'):
            note = text('Enter a path like {0;2} or connect paths from Tree Viewer.'
                        if operation == 'tree_branch' else
                        'Leave Source Paths empty to replace all paths in tree order. Branches with the same new path are combined.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation == 'array_along_curve':
            note = text('Place the source relative to the start of the rail. Leave G empty for transforms only.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation == UV_GRID_PREVIEW:
            note = text('Draw U in turquoise and V in amber. Divisions count intervals, including the ends of each domain.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation == 'hide':
            note = text('Hides whole Serpentine objects, including every part of a compound. Disconnect or disable this node to restore visibility.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('surface_domain', 'deconstruct_domain2'):
            note = text('Face Index 0 selects the only face. For multiple faces, enter an index starting at 1.'
                        if operation == 'surface_domain' else
                        'Split a Domain² into U and V. Face Index applies when a surface is connected directly.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation == 'divide_domain2':
            note = text('Produces U × V domain segments. Connect S to Deconstruct Domain² or Isotrim. '
                        'Face Index applies when a surface is connected directly.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation == 'uv_panels':
            note = text('U and V count equal intervals in parameter space. Panels are clipped to the face. '
                        'Empty cells are skipped. Use Face Index for geometry with multiple faces.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('surface_box', 'box_morph'):
            note = text('Partial or collapsed cells are skipped. A full wrap needs at least three divisions along the seam direction.'
                        if operation == 'surface_box' else
                        'Connect Bounding Box to R and Surface Box to T. Non-affine boxes support points, curves and geometry with planar faces.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('reparameterize_surface', 'surface_evaluate'):
            note = text('With neither U nor V connected, both become 0–1. Connect one Domain to change only that axis.'
                        if operation == 'reparameterize_surface' else
                        'Unconnected U/V use the domain midpoint. Normalized uses 0–1. Samples outside the trim or without a tangent plane are skipped.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation == 'surface_closest_point':
            note = text('Returns the closest point on the selected trimmed face. Connect U and V to Surface Evaluate. '
                        'Use the same Surface, Face Index and Normalized setting on both nodes.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('curve_domain', 'divide_curve', 'frame', 'perp_frames', 'curve_curvature',
                         'curve_closest_point', 'evaluate_curve', 'point_in_curve'):
            note = text({
                'curve_domain': 'L is the width of the native parameter interval.',
                'divide_curve': 'Count sets equal arc-length divisions. Kinks includes wire joints. Closed curves omit the repeated endpoint.',
                'frame': 'Normalized maps 0–1 to the native curve domain. Turn it off for Curve Domain → Range or the t output of Divide Curve.',
                'perp_frames': 'Planes are spaced by arc length. Align uses the Guide for orientation. Turn it off to follow curvature where available.',
                'curve_curvature': 'Turn off Normalized when t comes from Divide Curve. K is zero on straight portions.',
                'curve_closest_point': 'Normalized returns t in 0–1. Match this setting on Evaluate Curve and Curve Curvature.',
                'evaluate_curve': 'Normalized interprets input t in 0–1. Output t is always native.',
                'point_in_curve': 'Relationship: 0 outside, 1 on the boundary, 2 inside. I is True strictly inside the planar region.',
            }[operation])
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation == 'loft':
            note = text('Turn off Adjust Section Compatibility to preserve the alignment of matching sections from Orient.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('move','move_gh'):
            note=text('Move changes the source geometry in place. Connected T supplies the translation instead of X/Y/Z. World unchecked uses the source frame. Grid G moves everything; P/V move points; C/E move boundaries or edges.'
                if operation=='move' else 'Create independent translated copies. The source geometry stays unchanged. One Vector per geometry item or a single shared Vector. Graft/Flatten controls input structure.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('rotate', 'scale', 'mirror'):
            note = text({
                'rotate': 'Rotate about the plane normal through Center. Connected Angle takes precedence over Target Point. Enable Copy for independent results.',
                'scale': 'Scale uniformly about Center. Connected Factor takes precedence over Target Point. Otherwise, a connected Target Point sets the factor by its distance from Center. Enable Copy for independent results.',
                'mirror': 'Connect M to reflect directly across that plane. Without M, use the line and Work Plane. Enable Keep Original for a copy.',
            }[operation])
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in PARAMETRIC_BOOLEANS:
            note = text('Cut every base with the cutters on its branch. A single cutter branch can be shared.'
                        if operation == 'boolean_difference_parametric' else
                        'Combine solids within each branch. Use Merge to collect independent sources.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation == BOOLEAN_SPLIT_PARAMETRIC:
            note = text('Keep all solid pieces and preserve the inputs. The cutting plane sets the sweep direction for curve cutters.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in NATIVE_SCENE_OPERATIONS:
            note = text({
                FILLET: 'Apply replaces Curve 1 and removes Curve 2. Update rebuilds from the original curves. Use Undo in Serpentine to restore them.',
                BOOLEAN_SPLIT: 'Apply replaces the target solids with their pieces and keeps the cutters. Use Undo in Serpentine to restore the targets.',
            }.get(operation, 'Apply consumes the input scene objects. Use Undo in Serpentine to restore them.'))
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('join', 'explode'):
            note = text('Join connected curves or sew surfaces within each branch. Use Merge to collect separate inputs.'
                        if operation == 'join' else
                        'Extract edges, faces or compound parts. Use List Item to select a piece.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('duplicate_data', 'dispatch', 'weave', 'shift_list', 'cross_reference'):
            note = text({
                'duplicate_data': 'Repeat each branch N times. Retain List Order repeats the whole list in order.',
                'dispatch': 'True goes to A and False goes to B. The default pattern alternates True and False.',
                'weave': 'The pattern picks the next item from stream 0 (False) or 1 (True). The default alternates, skipping exhausted streams.',
                'shift_list': 'Positive shifts move the start forward. Wrap keeps the shifted items at the opposite end of each branch.',
                'cross_reference': 'Holistic pairs all items. Lower keeps B indices up to A; Upper keeps B indices from A onward. '
                                   'Strict, Diagonal and Coincident exclude equal indices.',
            }[operation])
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('brep_join', 'isotrim'):
            note = text('Sew shared edges within each branch. Use Merge to collect faces from separate nodes.'
                        if operation == 'brep_join' else
                        'Connect a Domain² to D, or one Domain each to U and V. '
                        'Use the input surface domain, including any Reparameterize Surface view.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation == 'split':
            note = text('Cut each target with its matching branch or one shared branch. Curve cutters sweep along World Z when cutting surfaces or solids.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation == 'trim':
            note = text('Remove the piece closest to P. Supply a shared point or one point per target. Curve cutters sweep along World Z when cutting surfaces or solids.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('cylinder', 'cone'):
            note = text('Shell is the lateral surface without caps. Connected S: True / 1 = Solid; False / 0 = Shell.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('curve', 'interpcurve'):
            note = text('One curve per point branch. Flatten joins branches; Graft separates individual points and may leave too few points to construct a curve.'
                        + (' Periodic also closes the curve. Knot Style: Uniform / Chord / Square Root Chord.' if operation == 'interpcurve' else ' Closed creates a periodic control-point curve.'))
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation == 'loft_options':
            note = text('Connect O to Loft. Native Loft does not support Rebuild or Refit.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('extrude','revolve','loft'):
            note=text({'extrude':'Curve or Surface + Vector. Cap closes planar closed profiles; open profiles remain surfaces.',
                'revolve':'Axis: Line or Plane normal. Angle is in degrees; negative values reverse the rotation.',
                'loft':'One Loft per section branch, in item order. Closed joins the last section to the first (at least 3). Rebuild/Refit are not supported.'}[operation])
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('contour', 'curve_curve', REGION_BOOLEAN):
            note = text({
                'contour': 'The first cut uses the base plane. Each next level moves by Spacing along its normal.',
                'curve_curve': 'Parameters use the native curve domains. Overlap endpoints are also returned as points.',
                REGION_BOOLEAN: 'Operands must lie in the same plane. Use filled regions to carry existing holes into the operation.',
            }[operation])
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('scale_non_uniform', 'surface_isocurves'):
            note = text(
                'The plane origin stays fixed. Factors act along its local axes. Negative factors reflect the copy.'
                if operation == 'scale_non_uniform' else
                'Fixed u gives curves along V. Fixed v gives curves along U. Face Index 0 requires a single face.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('gradient', 'text_tag', 'dimension'):
            note = text({
                'gradient': 'With no Domain, uses the minimum and maximum of all values. Connect C to the Color input of Text Tag or Dimension.',
                'text_tag': 'Shows a screen-sized label at each Point. Connect a Series to label points with numbers.',
                'dimension': 'Measures the 3D distance. The offset moves the displayed dimension line away from the measured points.',
            }[operation])
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('brep_to_mesh', 'mesh_join', 'weld_mesh', 'face_neighbours'):
            note = text({
                'brep_to_mesh': 'Smaller deflections increase density. Relative mode measures linear deflection as a fraction of the bounding-box diagonal.',
                'mesh_join': 'Combines the meshes in each branch. Use Weld Mesh to connect coincident boundaries.',
                'weld_mesh': 'Tolerance is measured in model units. Lower angles preserve sharp seams; 180° ignores normal direction.',
                'face_neighbours': 'Uses shared vertex indices. Each N branch lists the neighbours of one face; B and X count its boundary and non-manifold edges.',
            }[operation])
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('plane_fit', 'divide_by_length', 'shatter', 'flip_curve', 'move_seam'):
            note = text({
                'plane_fit': 'Fits one plane per branch of at least three noncollinear points. D is the maximum deviation and R is RMS.',
                'divide_by_length': 'Spacing is measured along the curve. Include Remainder adds the end of an open curve.',
                'shatter': 'Supply a parameter list per curve or one list shared across curves. Parameters 0–1 are normalized.',
                'flip_curve': 'Without a guide, reverses each curve. With a guide, matches direction or orientation.',
                'move_seam': 'Works on closed curves. Use a 0–1 normalized parameter or the native curve domain.',
            }[operation])
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('planar_surface','edge_surface','surface_from_points'):
            note=text({'planar_surface':'One region set per branch. Closed coplanar boundaries; inner loops form holes. Flatten combines boundaries.',
                'edge_surface':'One surface per branch of 2–4 single-edge curves. For 3–4 curves the boundaries must form a closed loop.',
                'surface_from_points':'Flatten consecutive point rows of equal width to use Auto U. With an explicit U, each branch can define its own surface. A connected U takes precedence.'}[operation])
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation=='patch':
            note=text('Fill one closed connected outline per branch, including non-planar outlines. Requires 2–240 edges; a multi-edge Polyline is allowed. Native positional (G0) fitting; no holes or tangent/curvature constraints. Flatten combines boundary curves. This is not a U/V curve-network surface.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation=='sweep1':
            note=text('One rail and one profile per result. Native transport uses the supplied profile position and orientation. Closed profiles produce a surface/shell without automatic caps. Align the profile with the rail before sweeping.')
            note.setWordWrap(True)
            layout.addWidget(note)
        if operation in ('sweep2','birail_sweep'):
            note=text('Rail 1 drives the profile. Rail 2 controls orientation and is not required to become a surface boundary. Curve directions are used as supplied.'
                if operation=='sweep2' else
                'Open rails and one open profile. Profile ends must touch rail ends. Directions are matched automatically. Sampled interpolation: increase Rail/Profile Samples for tighter curved boundaries; this is not an exact copy of the source curves.')
            note.setWordWrap(True)
            layout.addWidget(note)
        self.modifiers, self.editors, self.stacks, self.previews = {}, {}, {}, {}
        self.auto_u = None
        for descriptor in GEOMETRY_SPECS[operation]['inputs']:
            port = descriptor.port
            modifier = TreeButtons()
            modifier.changed.connect(lambda mode, p=port: self._modifier(p, mode))
            self.modifiers[port] = modifier
            layout.addWidget(modifier)
            stack = InputStack()
            if descriptor.default is not None:
                fields = QtWidgets.QWidget()
                fields_layout = QtWidgets.QVBoxLayout(fields)
                fields_layout.setContentsMargins(0, 0, 0, 0)
                fields_layout.setSpacing(6)
                self.editors[port] = []
                for index in range(3 if descriptor.kind in ('point', 'center','vector') else 1):
                    if descriptor.kind in ('plane','axis'):
                        editor = QtWidgets.QComboBox()
                        editor.addItems(('XY', 'XZ', 'YZ'))
                        editor.currentTextChanged.connect(lambda value, p=port: self._parameter(p, value))
                    elif descriptor.choices:
                        editor = QtWidgets.QComboBox()
                        editor.addItems(descriptor.choices)
                        editor.currentIndexChanged.connect(lambda value, p=port: self._parameter(p, value))
                    elif descriptor.kind in ('boolean', 'bool_cast'):
                        editor = QtWidgets.QCheckBox(descriptor.label)
                        editor.toggled.connect(lambda value, p=port: self._parameter(p, value))
                    elif descriptor.kind == 'color':
                        editor = QtWidgets.QPushButton()
                        editor.setMinimumHeight(36)
                        editor.clicked.connect(lambda checked=False, field=editor, p=port: self._pick_color(p, field))
                    elif descriptor.kind in ('text', 'path_text', 'label_text'):
                        editor = QtWidgets.QLineEdit()
                        if descriptor.kind == 'path_text':
                            editor.setPlaceholderText('All paths in tree order' if operation == 'replace_paths' and port == 'S' else '{0;2}')
                        editor.editingFinished.connect(lambda field=editor, p=port: self._text_parameter(p, field))
                    else:
                        editor = NumberField()
                        editor.setDecimals(0 if descriptor.kind.startswith('degree_')
                            or descriptor.kind in POPULATION_COUNT_LIMITS or descriptor.kind in (
                            'grid_count', 'polar_count', 'surface_u', 'sweep_samples', 'list_index', 'division_count',
                            'uv_grid_count', 'braced_grid_count', 'face_index', 'array_count', 'polar_array_count',
                            'population_seed', 'penrose_generations') else 4)
                        if descriptor.kind == 'penrose_generations':
                            editor.setRange(0, MAX_GENERATIONS)
                            editor.enableStepButtons()
                        if descriptor.kind=='sweep_samples':
                            editor.setRange(4,129)
                            editor.enableStepButtons()
                        if descriptor.kind == 'list_index':
                            editor.enableStepButtons()
                        if descriptor.kind=='surface_u':
                            editor.setRange(2,1250)
                            editor.enableStepButtons()
                            self.auto_u = QtWidgets.QCheckBox('Auto')
                            self.auto_u.toggled.connect(lambda checked, field=editor:
                                self._parameter('U', 'auto' if checked else field.value()))
                            fields_layout.addWidget(self.auto_u)
                        if descriptor.kind in ('grid_count','polar_count'):
                            editor.setRange(3 if descriptor.kind == 'polar_count' else 1,10000)
                            editor.enableStepButtons()
                        if descriptor.kind == 'array_count':
                            editor.setRange(1, 1600)
                        if descriptor.kind == 'polar_array_count':
                            editor.setRange(2, 360)
                        if descriptor.kind in POPULATION_COUNT_LIMITS:
                            editor.setRange(0, POPULATION_COUNT_LIMITS[descriptor.kind])
                        if descriptor.kind == 'population_seed':
                            editor.setRange(-2147483648, 2147483647)
                        if descriptor.kind == 'division_count':
                            editor.setRange(1, MAX_DIVISIONS)
                            editor.enableStepButtons()
                        if descriptor.kind == 'uv_grid_count':
                            editor.setRange(1, MAX_UV_GRID_DIVISIONS)
                            editor.enableStepButtons()
                        if descriptor.kind == 'braced_grid_count':
                            editor.setRange(1, MAX_BRACED_DIVISIONS)
                            editor.enableStepButtons()
                        if descriptor.kind == 'face_index':
                            editor.setRange(0, MAX_ITEMS)
                            editor.enableStepButtons()
                        if descriptor.kind.startswith('degree_'):
                            editor.setRange(2 if descriptor.kind == 'degree_control' else 1,
                                            10 if descriptor.kind == 'degree_control' else 5)
                            editor.enableStepButtons()
                        editor.setMinimumHeight(36)
                        editor.valueChanged.connect(lambda value, p=port, i=index, k=descriptor.kind:
                            self._parameter(p, value, i if k in ('point', 'center','vector') else None))
                    editor.setAccessibleName(GEOMETRY_SPECS[operation]['name']+' '+descriptor.label+' '+str(index))
                    self.editors[port].append(editor)
                    if descriptor.kind in ('point', 'center', 'vector'):
                        add_field(fields_layout, 'XYZ'[index], editor)
                    else:
                        fields_layout.addWidget(editor)
                if descriptor.kind == 'center':
                    fields.setToolTip('Offset from the input plane origin when Center is unconnected; a connected Point is an absolute center.')
                stack.addWidget(fields)
            preview = TreePreview()
            preview.setTextFormat(QtCore.Qt.PlainText)
            preview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            preview.setWordWrap(True)
            stack.addWidget(preview)
            self.stacks[port], self.previews[port] = stack, preview
            description = 'Points' if operation == 'surface_from_points' and port == 'P' else descriptor.label
            stack.setToolTip(descriptor.label)
            add_field(layout, port + ' · ' + description, stack)
        if operation == 'read_csv':
            row = QtWidgets.QHBoxLayout()
            self.csv_browse = QtWidgets.QPushButton('Browse…')
            self.csv_browse.clicked.connect(self._browse_csv)
            row.addWidget(self.csv_browse)
            reload = QtWidgets.QPushButton('Reload CSV')
            reload.clicked.connect(lambda: self._parameter('reload', self.state['parameters']['reload'] + 1))
            row.addWidget(reload)
            layout.addLayout(row)
        self.generate_layout.addWidget(body)
        self._operation = operation

    def _modifier(self, port, mode):
        modes = dict(self.state['tree_modes'])
        modes.pop(port, None)
        if mode != 'none':
            modes[port] = mode
        self.edited.emit('tree_modes', modes)

    def _parameter(self, port, value, index=None):
        if self.state['mode'] == 'reference' or self.connected.get(port):
            return
        parameters = copy.deepcopy(self.state['parameters'])
        if index is None:
            parameters[port] = value
        else:
            parameters[port][index] = value
        self.edited.emit('parameters', parameters)

    def _text_parameter(self, port, field):
        field.setModified(False)
        self._parameter(port, field.text())

    def _pick_color(self, port, field):
        selected = QtWidgets.QColorDialog.getColor(QtGui.QColor(field.text()), self, 'Choose Color')
        if selected.isValid():
            self._parameter(port, selected.name().upper())

    @staticmethod
    def _show_color(field, value):
        if field.text() == value:
            return
        swatch = QtGui.QPixmap(14, 14)
        swatch.fill(QtGui.QColor(value))
        field.setIcon(QtGui.QIcon(swatch))
        field.setText(value)

    def _browse_csv(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Choose CSV File', self.state['parameters']['P'], 'Delimited Tables (*.csv *.tsv);;All Files (*)')
        if filename:
            self._parameter('P', filename)

    def _apply_choices(self):
        options = self.choice_options.toPlainText()
        try:
            entries = choice_entries(options)
        except ValueError as exc:
            self.choice_error.setText(str(exc))
            self.choice_error.show()
            return
        previous = self.choice_picker.currentText()
        selection = next((i for i, (label, _) in enumerate(entries) if label == previous), 0)
        self.choice_error.hide()
        self.edited.emit('parameters', {'options': options, 'selection': selection})

    def _show_choices(self, parameters, changed):
        options = parameters['options']
        with QtCore.QSignalBlocker(self.choice_picker):
            if changed or options != self._loaded_options:
                self.choice_options.setPlainText(options)
                self.choice_picker.clear()
                self.choice_picker.addItems([label for label, _ in choice_entries(options)])
                self._loaded_options = options
                self.choice_error.hide()
            self.choice_picker.setCurrentIndex(parameters['selection'])

    def _point_grouping(self, _index):
        self.edited.emit('parameters', {**self.state['parameters'],
                                       'point_grouping': self.grid_grouping.currentData()})

    def _offset_mode(self, mode, checked):
        parameters = {**self.state['parameters'], mode: checked}
        if checked:
            parameters['solid' if mode == 'fill' else 'fill'] = False
        self.edited.emit('parameters', parameters)

    def show_node(self, node, evaluation, formatter):
        if self._operation != node.OPERATION:
            self._build(node.OPERATION)
        changed = self._node_id != node.id
        self._node_id = node.id
        self.state = node.curve_state()
        state = self.state
        if node.OPERATION == 'value_list':
            self._show_choices(state['parameters'], changed)
        self.box_mode_row.setVisible(node.OPERATION == 'bounding_box')
        if node.OPERATION == 'bounding_box':
            with QtCore.QSignalBlocker(self.box_mode):
                self.box_mode.setCurrentIndex(self.box_mode.findData(state['parameters']['box_mode']))
        self.region_mode_row.setVisible(node.OPERATION == REGION_BOOLEAN)
        if node.OPERATION == REGION_BOOLEAN:
            with QtCore.QSignalBlocker(self.region_mode):
                self.region_mode.setCurrentText(state['parameters']['region_mode'])
        self.cross_pairing_row.setVisible(node.OPERATION == 'cross_reference')
        if node.OPERATION == 'cross_reference':
            with QtCore.QSignalBlocker(self.cross_pairing):
                self.cross_pairing.setCurrentIndex(self.cross_pairing.findData(state['parameters']['pairing']))
        self.point_sort_row.setVisible(node.OPERATION == 'sort_points')
        if node.OPERATION == 'sort_points':
            with QtCore.QSignalBlocker(self.point_sort_order):
                self.point_sort_order.setCurrentText(state['parameters']['axis_order'])
        has_periodic_u = node.OPERATION in TESSELLATION_SPECS or node.OPERATION in (DELAUNAY_MESH, 'surface_from_points')
        self.periodic_u.setVisible(has_periodic_u)
        if has_periodic_u:
            self.periodic_u.setToolTip({
                HEXAGON_TILING: 'Fit a whole number of columns across a rectangular boundary and match both U edges.',
                DELAUNAY_MESH: 'Connect Rectangle to B. U and V are normalized and follow the mesh vertex order.',
                'surface_from_points': 'Close the surface around each point row. Supply its first point only once.',
            }.get(node.OPERATION, 'Wrap the U sides of a rectangular boundary.'))
            with QtCore.QSignalBlocker(self.periodic_u):
                self.periodic_u.setChecked(state['parameters']['periodic_u'])
        self.matching_arcs.setVisible(node.OPERATION == PENROSE)
        if node.OPERATION == PENROSE:
            with QtCore.QSignalBlocker(self.matching_arcs):
                self.matching_arcs.setChecked(state['parameters']['matching_arcs'])
        self.offset_modes.setVisible(node.OPERATION == 'offset')
        if node.OPERATION == 'offset':
            for mode, box in self.offset_checks.items():
                with QtCore.QSignalBlocker(box):
                    box.setChecked(state['parameters'][mode])
        is_fillet = node.OPERATION == FILLET_EDGE
        self.fillet_modes.setVisible(is_fillet)
        self.fillet_capture.setVisible(is_fillet and state['parameters']['fillet_mode'] == 'selected')
        if is_fillet:
            for mode, button in self.fillet_buttons.items():
                button.setChecked(state['parameters']['fillet_mode'] == mode)
            wired = bool(node.inputs()['E'].connected_ports())
            self.fillet_capture.setEnabled(not wired and not getattr(node, 'fillet_capture_pending', False))
            self.fillet_capture.setToolTip('Disconnect E to use selection from the scene.' if wired else
                                           'Ctrl+Shift+click the edges in Serpentine, then click Set Edges.')
        has_show_parent = node.OPERATION in SHOW_PARENT_OPERATIONS
        self.show_parent.setVisible(has_show_parent)
        if has_show_parent:
            with QtCore.QSignalBlocker(self.show_parent):
                self.show_parent.setChecked(state['parameters']['show_parent'])
        native_edit = node.OPERATION in NATIVE_SCENE_OPERATIONS
        applied_fillet = node.OPERATION == FILLET and bool(getattr(node, 'boolean_records', ()))
        self.boolean_apply.setVisible(native_edit)
        action_error = None
        if native_edit:
            result = evaluation.results.get(node.id) if evaluation else None
            self.boolean_apply.setText(('Update Fillet' if applied_fillet else 'Apply Fillet')
                                       if node.OPERATION == FILLET else
                                       'Apply Boolean Split' if node.OPERATION == BOOLEAN_SPLIT else 'Apply Boolean')
            self.boolean_apply.setEnabled(bool(result and result.boolean_plan
                and getattr(node, 'boolean_ready', False) and not getattr(node, 'boolean_pending', False)))
            action_error = result.action_error if result else None
        self.native_action_error.setVisible(bool(action_error))
        self.native_action_error.setText(action_error or '')
        is_grid = node.OPERATION in GRID_SPECS
        self.grid_grouping_row.setVisible(is_grid)
        if is_grid:
            note = 'Group output P separately for each grid.'
            if node.OPERATION == 'grid_radial':
                note += ' Rows follow rings. Columns follow rays and keep the center in its own branch.'
            self.grid_grouping.setToolTip(note)
            with QtCore.QSignalBlocker(self.grid_grouping):
                self.grid_grouping.setCurrentIndex(self.grid_grouping.findData(state['parameters']['point_grouping']))
        spec = GEOMETRY_SPECS[node.OPERATION]
        self.source_modes.setVisible(spec.get('reference', True) and not spec.get('reference_only', False))
        for mode, button in self.sources.items():
            button.setChecked(state['mode'] == mode)
        reference = state['mode'] == 'reference'
        read_only_reference = reference and node.OPERATION in ARCHIVED_REFERENCE_OPS
        self.reference.setVisible(reference)
        self.generate.setVisible(not read_only_reference)
        if read_only_reference and node.OPERATION == CURVES:
            note = 'Select whole curves in section order. Geometry follows edits in Serpentine.'
        elif read_only_reference and node.OPERATION == 'mesh':
            note = 'Select whole mesh objects in Serpentine. The reference follows edits to the source mesh.'
        elif read_only_reference and node.OPERATION == 'loft':
            note = 'Select whole surface or solid objects. Geometry follows edits in Serpentine. Section Count is available in Generate.'
        elif read_only_reference:
            note = 'Select whole surface objects. Geometry follows edits in Serpentine.'
        else:
            note = 'Connect inputs to edit these native objects. Unconnected inputs keep their current scene values.'
            if node.OPERATION == 'interpcurve':
                note += ' Connect P to change spline construction settings.'
        self.reference_note.setText(note)
        self.reference_count.setText(str(len(state['references']))+' referenced object(s)')
        self.reference_modifier.set_mode(state['tree_modes'].get('References', 'none'))
        self.connected = {}
        if read_only_reference:
            self._show_status(node, changed)
            return
        connected_ports = {name for name, port in node.inputs().items() if port.connected_ports()}
        if node.OPERATION == 'read_csv':
            self.csv_browse.setEnabled('P' not in connected_ports)
        inactive_ports = (*inactive_motion_ports(node.OPERATION, connected_ports),
                          *inactive_fillet_ports(node.OPERATION, state['parameters']))
        if node.OPERATION == DELAUNAY_MESH:
            inactive_ports += ('Pl' if state['parameters']['periodic_u'] else 'B',)
        for descriptor in GEOMETRY_SPECS[node.OPERATION]['inputs']:
            port = descriptor.port
            sources = node.inputs()[port].connected_ports()
            stored_curve = applied_fillet and port in ('A', 'B')
            inactive = port in inactive_ports or stored_curve
            self.connected[port] = bool(sources) or inactive
            self.modifiers[port].setEnabled(not inactive)
            self.modifiers[port].set_mode(state['tree_modes'].get(port, 'none'))
            stack, preview = self.stacks[port], self.previews[port]
            tree = None
            if stored_curve:
                preview.setText('Original curve saved')
                preview.setToolTip('Undo Apply Fillet in Serpentine to use different source curves.')
                stack.setCurrentWidget(preview)
            elif inactive and is_fillet:
                preview.setText('Used in Selected mode')
                preview.setToolTip('Switch to Selected to use Edge Points.')
                stack.setCurrentWidget(preview)
            elif inactive and node.OPERATION == DELAUNAY_MESH:
                preview.setText('Used in planar mode' if port == 'Pl' else 'Used with Periodic U')
                preview.setToolTip('The rectangle defines the UV axes in Periodic U mode.')
                stack.setCurrentWidget(preview)
            elif inactive:
                controller = 'To'
                if node.OPERATION == 'move':
                    controller = 'T'
                elif port == 'To':
                    controller = 'F' if node.OPERATION == 'scale' else 'A'
                preview.setText('Controlled by ' + controller)
                preview.setToolTip('Disconnect ' + controller + ' to use this input.')
                stack.setCurrentWidget(preview)
            elif sources:
                source = sources[0]
                result = evaluation.results.get(source.node().id) if evaluation else None
                tooltip = 'Connected to '+source.node().name()+' · '+source.name()
                try:
                    if result is None or result.error or source.name() not in result.outputs:
                        raise ValueError('Connected output is unavailable.')
                    value = input_tree(result.outputs[source.name()], descriptor, state['tree_modes'].get(port, 'none'))
                    preview.setText(formatter(value))
                    tree = value
                except (ValueError, TypeError, OverflowError) as exc:
                    preview.setText('No valid input')
                    tooltip += '\n'+str(exc)
                preview.setToolTip(tooltip)
                stack.setCurrentWidget(preview)
            elif reference or descriptor.default is None:
                if node.OPERATION == 'surface_morph' and descriptor.optional:
                    preview.setText('Source thickness' if port == 'W' else 'Full target domain')
                else:
                    preview.setText('From scene' if reference else 'Optional' if descriptor.optional else 'Connect input '+port+'.')
                preview.setToolTip('Connect this input to drive the reference.' if reference else '')
                stack.setCurrentWidget(preview)
            else:
                value = state['parameters'][port]
                if descriptor.kind == 'surface_u':
                    automatic = value == 'auto'
                    result = evaluation.results.get(node.id) if evaluation else None
                    widths = result.outputs['U'].values() if automatic and result and 'U' in result.outputs else ()
                    value = widths[0] if widths else (2 if automatic else value)
                    with QtCore.QSignalBlocker(self.auto_u):
                        self.auto_u.setText(f'Auto ({value})' if widths else 'Auto')
                        self.auto_u.setChecked(automatic)
                    self.editors[port][0].setVisible(not automatic)
                for index, editor in enumerate(self.editors[port]):
                    blocker = QtCore.QSignalBlocker(editor)
                    if descriptor.kind in ('plane','axis'):
                        editor.setCurrentText(value)
                    elif descriptor.choices:
                        editor.setCurrentIndex(value)
                    elif descriptor.kind in ('boolean', 'bool_cast'):
                        editor.setChecked(value)
                        if descriptor.kind == 'bool_cast':
                            editor.setText(str(editor.isChecked()))
                    elif descriptor.kind == 'color':
                        self._show_color(editor, value)
                    elif descriptor.kind in ('text', 'path_text', 'label_text'):
                        if changed or not editor.hasFocus() or not editor.isModified():
                            editor.setText(value)
                    else:
                        target = value[index] if descriptor.kind in ('point', 'center','vector') else value
                        if changed or not editor.hasFocus() or editor.value() != target:
                            editor.setValue(target)
                    del blocker
                stack.setCurrentWidget(stack.widget(0))
            preview.set_tree(tree, formatter)
        self._show_status(node, changed)
