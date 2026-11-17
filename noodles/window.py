"""Application shell; the canvas and node styling belong to NodeGraphQt."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
import logging
import threading
import uuid
from pathlib import Path

from NodeGraphQt import NodeGraph
from NodeGraphQt.qgraphics.node_abstract import AbstractNodeItem
from NodeGraphQt.widgets.viewer import NodeViewer
from Qt import QtCore, QtGui, QtWidgets

from . import __version__
from .core import Connection, GraphEngine, NodeSpec, REQUIRED_INPUTS
from .document import DocumentError, read_document, write_document
from .connection import SerpentineConnection
from .bridge import BridgeError, scene_matches_graph
from .point_service import GeometryService
from .backend.datatree import DataTree
from .backend.point import PointValue, reference_drive
from .backend.domain import DomainValue
from .backend.arithmetic import VectorValue
from .backend.math_nodes import MATH_SPECS
from .backend.geometry import GEOMETRY_SPECS, MEASUREMENT_METHODS
from .backend.curves import CurveValue, PlaneValue
from .backend.curve_collection import CURVES
from .backend.mesh_nodes import BREP_TO_MESH, MESH_SPECS
from .backend.delaunay_node import HEXAGON_TILING, TESSELLATION_SPECS, VORONOI
from .backend.penrose_node import PENROSE
from .backend.surface_structure import BRACED_GRID, SURFACE_BOX, UV_PANELS
from .backend.array_along_curve import ARRAY_ALONG_CURVE
from .backend.solids import SolidValue
from .backend.grids import GridValue
from .evaluation import GraphWorker
from .library import NodeLibrary, NodeSearchPopup
from .preview_service import PreviewService
from .backend.previews import HIDE, PREVIEW_SPECS, UV_GRID_PREVIEW, preview_payload
from .backend.annotations import ANNOTATIONS
from .backend.data_helpers import DATA_HELPER_SPECS
from .backend.moves import MOVE_SPECS,RigidValue,TranslationValue,TranslatedValue
from .backend.operations import OPERATION_SPECS,OperationValue
from .backend.fillet_edges import FILLET_EDGE, capture_target, target_key
from .backend.booleans import NATIVE_SCENE_OPERATIONS
from .backend.topology_operations import TOPOLOGY_OPERATIONS
from .backend.surface_reference import SurfaceReferenceValue
from .graph_mapper import GraphMapperMenuFilter
from .graph_image import save_graph_image
from .nodes import NODE_CLASSES, NODE_TYPES
from .workbench import CAD_VIEW_MENU_STYLE, CANVAS_MENU_STYLE, InspectorPanel, WorkbenchPanel, STYLESHEET, apply_theme, label


LOG = logging.getLogger(__name__)
FILE_FILTER = "NoodleS graph (*.noodles);;All files (*)"
UNGROUPED_STATUS = 'Ungrouped · native objects in Serpentine'


class CanvasViewer(NodeViewer):
    context_node = QtCore.Signal(object)
    exporting_graph_image = False

    def contextMenuEvent(self, event):
        items = self._items_near(self.mapToScene(event.pos()))
        node = next((item for item in items if isinstance(item, AbstractNodeItem)), None)
        self.context_node.emit(node.id if node else None)
        super().contextMenuEvent(event)

    def get_zoom(self):
        return 0.0 if self.exporting_graph_image else super().get_zoom()

    def frame_graph(self):
        """Center the visible graph and zoom out only as far as needed."""
        bounds = QtCore.QRectF()
        for item in (*self.all_nodes(), *self.all_pipes()):
            if item.isVisible():
                bounds = bounds.united(item.sceneBoundingRect())
        viewport = self.viewport().rect().adjusted(2, 2, -2, -2)
        if bounds.isEmpty() or viewport.isEmpty():
            return

        bounds.adjust(-16, -16, 16, 16)
        inverse, _ = self.transform().inverted()
        visible = inverse.mapRect(QtCore.QRectF(viewport))
        factor = max(1.0, bounds.width() / visible.width(), bounds.height() / visible.height())
        frame = QtCore.QRectF(QtCore.QPointF(), visible.size() * factor)
        frame.moveCenter(bounds.center())
        self.set_scene_rect(frame.getRect())

    def resizeEvent(self, event):
        # NodeViewer refits on resize. Keep its scene range in sync without
        # changing the transform, so the existing zoom and pan still work.
        QtWidgets.QGraphicsView.resizeEvent(self, event)
        # QGraphicsView.fitInView uses a two-pixel inset on each side.
        viewport_rect = self.viewport().rect().adjusted(2, 2, -2, -2)
        if viewport_rect.isEmpty() or not hasattr(self, "_scene_range"):
            return
        center = self._scene_range.center()
        inverse, _ = self.transform().inverted()
        self._scene_range = inverse.mapRect(QtCore.QRectF(viewport_rect))
        self._scene_range.moveCenter(center)
        self.setSceneRect(self._scene_range)
        self.centerOn(center)


class MainWindow(QtWidgets.QMainWindow):
    _cad_response = QtCore.Signal(str, object, str)
    _panel_response = QtCore.Signal(str, object, object, str)
    _scene_link_saved = QtCore.Signal(object, object)

    def __init__(self, *, example: bool = False, bridge_session=None):
        super().__init__()
        apply_theme(QtWidgets.QApplication.instance())
        self.setLocale(QtCore.QLocale("en_US"))
        self.setObjectName("NoodleSWindow")
        self.setStyleSheet(STYLESHEET)
        self.resize(1360, 860)
        self.setMinimumSize(980, 580)
        self.setWindowTitle("NoodleS")
        self.path: Path | None = None
        self.project_uuid = str(uuid.uuid4())
        self._scene_link = None
        self._authorized_scene = None
        self._declined_scene = None
        self._opening_graph = False
        self._scene_requests = ThreadPoolExecutor(max_workers=1, thread_name_prefix='NoodleS-SceneLink')
        self._scene_link_saved.connect(self._show_scene_link_result)
        self.engine = GraphEngine()
        self._graph_worker = None
        self.evaluation = None
        self._loading = False
        self._pending = False
        self._inspector_refresh_pending = False
        self._closing = False
        self._cad_session = None
        self._cad_view = None
        self._cad_pending = False
        self._ungrouped_owners = set()
        self._ungroup_pending = set()
        self._cad_response.connect(self._cad_finished)
        self._panel_session = None
        self._panel_state = None
        self._panel_requests = {}
        self._panel_response.connect(self._panel_finished)
        undo_stack = QtWidgets.QUndoStack(self)
        self.graph = NodeGraph(undo_stack=undo_stack, viewer=CanvasViewer(undo_stack=undo_stack))
        self.graph.setParent(self)
        self.graph.set_acyclic(True)
        self.graph.register_nodes(list(NODE_CLASSES))
        self._graph_mapper_menu_filter = GraphMapperMenuFilter(self.graph.viewer())
        self._set_canvas_background()
        self._library_width = 230
        self._properties_width = 320

        self.node_ports = {}
        for kind, cls in NODE_TYPES.items():
            if cls.OPERATION == 'cad_viewport':
                self.node_ports[kind] = ((), ())
                continue
            output = {"point": "Point", "watch": "Value"}.get(cls.OPERATION, "Number")
            outputs = {"point": ("P", "X", "Y", "Z"), "domain": ("D", "L"),
                       "addition": ("R",), "multiplication": ("R",),
                       "range": ("R", "Flat", "Count")}.get(cls.OPERATION, (output,))
            if cls.OPERATION in MATH_SPECS:
                outputs = MATH_SPECS[cls.OPERATION]["outputs"]
            if cls.OPERATION in GEOMETRY_SPECS:
                outputs = GEOMETRY_SPECS[cls.OPERATION]['outputs']
            self.node_ports[kind] = (REQUIRED_INPUTS[cls.OPERATION], outputs)
        self.node_ports["nodeGraphQt.nodes.BackdropNode"] = ((), ())

        self.palette = NodeLibrary(node_graph=self.graph)
        self.palette.set_category_label("nodeGraphQt.nodes", "Layout")
        for category, category_label in (
            ("NoodleS.Inputs", "Inputs"), ("NoodleS.Math", "Math"),
            ("NoodleS.Geometry", "Geometry"), ("NoodleS.Data", "Data"),
            ("NoodleS.Operations", "Operations"),
            ("NoodleS.VisualHelpers", "Visual Helpers"),
        ):
            self.palette.set_category_label(category, category_label)
        self._build_workspace()
        self.statusBar().setSizeGripEnabled(False)
        self._build_actions()
        self._build_toolbar()
        self.serpentine = SerpentineConnection(self, session_id=bridge_session)
        self.geometry_service = GeometryService(self)
        self.point_service = self.geometry_service  # Existing Point integrations use this alias.
        self.preview_service = PreviewService(self)
        self._preview_bridge_session = None
        self._annotation_preview_supported = None
        self._hide_supported = None
        self.preview_service.result.connect(self._preview_event)
        self._point_bridge_session = None
        self.point_service.result.connect(self._point_event)
        self.serpentine.changed.connect(self._connection_changed)
        self.connection_status.clicked.connect(self.serpentine.reconnect)
        self.connection_status.setToolTip("Click to connect to Serpentine3D.")
        self.properties.reference_requested.connect(self._capture_points)
        self.properties.boolean_requested.connect(self._apply_native_boolean)
        self.graph.node_created.connect(self._initialize_point)
        self.graph.undo_stack().indexChanged.connect(self._changed)
        self.graph.undo_stack().cleanChanged.connect(self._update_title)
        self.graph.property_changed.connect(self._changed)
        self.graph.node_created.connect(self._changed)
        self.graph.nodes_deleted.connect(self._changed)
        self.graph.port_connected.connect(self._changed)
        self.graph.port_disconnected.connect(self._changed)
        # node_selected is a raw canvas press notification, including presses
        # on embedded controls that never change the actual node selection.
        self.graph.scene().selectionChanged.connect(self._queue_inspector_refresh)
        self.graph.node_selection_changed.connect(self._queue_inspector_refresh)
        self.graph.node_double_clicked.connect(self._queue_inspector_refresh)
        if example:
            self._build_example()
        self.graph.undo_stack().setClean()
        self._update_title()
        self.evaluate_now()

    def _set_canvas_background(self):
        # Sampled from the user's Serpentine viewport reference: charcoal at
        # the top, slightly darker at the bottom. Device coordinates keep
        # the gradient fixed while panning and zooming the graph.
        self.graph.set_background_color(34, 35, 39)
        self.graph.set_grid_color(49, 51, 55)
        gradient = QtGui.QLinearGradient(0, 0, 0, 1)
        gradient.setCoordinateMode(QtGui.QGradient.StretchToDeviceMode)
        gradient.setColorAt(0, QtGui.QColor(42, 43, 47))
        gradient.setColorAt(1, QtGui.QColor(25, 27, 31))
        self.graph.scene().setBackgroundBrush(QtGui.QBrush(gradient))

    def _build_workspace(self):
        # A single horizontal splitter guarantees the same top/bottom edges
        # for the library, graph and inspector, including after window resize.
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.splitter.setObjectName("Workbench")
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        self.setCentralWidget(self.splitter)

        library_body = QtWidgets.QWidget()
        library_body.setObjectName("LibraryBody")
        library_layout = QtWidgets.QVBoxLayout(library_body)
        library_layout.setContentsMargins(12, 14, 12, 16)
        library_layout.setSpacing(12)
        self.library_search = QtWidgets.QLineEdit()
        self.library_search.setObjectName("LibrarySearch")
        self.library_search.setPlaceholderText("Search nodes…")
        self.library_search.setAccessibleName("Search the node library")
        self.library_search.setClearButtonEnabled(True)
        library_layout.addWidget(self.library_search)
        self.palette.setObjectName("NodeLibrary")
        self.palette.setIndentation(14)
        self.palette.setFrameShape(QtWidgets.QFrame.NoFrame)
        for index in range(self.palette.topLevelItemCount()):
            category = self.palette.topLevelItem(index)
            category.setForeground(0, QtGui.QColor("#929eac"))
            font = category.font(0)
            font.setPointSize(9)
            font.setBold(True)
            category.setFont(0, font)
            category.setSizeHint(0, QtCore.QSize(0, 34))
            for child_index in range(category.childCount()):
                category.child(child_index).setSizeHint(0, QtCore.QSize(0, 32))
        library_layout.addWidget(self.palette, 1)
        library_layout.addWidget(label("Drag onto the canvas\nor double-click to add."))
        self.library_panel = WorkbenchPanel("Library", library_body)
        self.library_panel.setMinimumWidth(205)
        self.splitter.addWidget(self.library_panel)
        self.library_search.textChanged.connect(self._filter_library)
        self.library_search.returnPressed.connect(self._add_search_result)
        self.palette.itemDoubleClicked.connect(self._add_library_item)
        self.node_search = NodeSearchPopup(self)
        self.node_search.chosen.connect(self._add_popup_result)

        self.canvas_panel = WorkbenchPanel("Untitled", self.graph.widget)
        self.connection_status = QtWidgets.QToolButton()
        self.connection_status.setObjectName("Connection")
        self.connection_status.setText("Serpentine  ·  Disconnected")
        self.connection_status.setAccessibleName("Serpentine connection status; click to reconnect")
        self.connection_status.setFixedHeight(28)
        self.connection_status.setMinimumWidth(
            self.connection_status.fontMetrics().horizontalAdvance(self.connection_status.text()) + 28
        )
        self.canvas_panel.heading.layout().addWidget(self.connection_status)
        self.canvas_panel.setMinimumWidth(430)
        self.splitter.addWidget(self.canvas_panel)

        self.properties = InspectorPanel()
        self.properties.property_edited.connect(self._edit_inspected_property)
        self.properties_panel = WorkbenchPanel("Properties", self.properties)
        self.properties_panel.setMinimumWidth(290)
        self.splitter.addWidget(self.properties_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([230, 810, 320])

    def createPopupMenu(self):
        # Qt would offer a checkable visibility action for the main toolbar.
        return None

    def _build_toolbar(self):
        toolbar = QtWidgets.QToolBar("Document", self)
        toolbar.setObjectName("MainToolbar")
        self.toolbar = toolbar
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setFixedHeight(58)
        self.menu_button = QtWidgets.QToolButton()
        self.menu_button.setObjectName("MenuButton")
        self.menu_button.setAccessibleName("NoodleS menu")
        self.menu_button.setToolTip("NoodleS menu")
        self.menu_button.setFixedSize(34, 34)
        self.menu_button.setIcon(self._menu_icon())
        self.menu_button.setIconSize(QtCore.QSize(20, 20))
        self.menu_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.menu_button.setMenu(self.application_menu)
        toolbar.addWidget(self.menu_button)
        brand = label("NoodleS", "Brand")
        brand.setWordWrap(False)
        toolbar.addWidget(brand)
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        self.cad_view_button = QtWidgets.QToolButton()
        self.cad_view_button.setObjectName("CadViewToggle")
        self.cad_view_button.setText("CAD View")
        self.cad_view_button.setCheckable(True)
        self.cad_view_button.clicked.connect(self._toggle_cad_view)
        self.cad_view_button.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.cad_view_menu = QtWidgets.QMenu(self.cad_view_button)
        self.cad_view_menu.setStyleSheet(CAD_VIEW_MENU_STYLE)
        self.high_smooth_action = self.cad_view_menu.addAction("High Smooth")
        self.high_smooth_action.setCheckable(True)
        self.high_smooth_action.triggered.connect(self._set_high_smooth)
        self.cad_view_button.customContextMenuRequested.connect(self._show_cad_view_menu)
        self.cad_view_menu.aboutToShow.connect(self._show_cad_toolbar_button)
        self._show_cad_toolbar_button()
        toolbar.addWidget(self.cad_view_button)
        self.s3d_panel_buttons = {}
        for panel, title in (('properties', 'S3D Properties'), ('layers', 'S3D Layers')):
            button = QtWidgets.QToolButton()
            button.setObjectName("S3DPanelToggle")
            button.setText(title)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, name=panel: self._toggle_s3d_panel(name))
            self.s3d_panel_buttons[panel] = button
            toolbar.addWidget(button)
        self._show_s3d_panels()
        self.library_button = QtWidgets.QToolButton()
        self.library_button.setObjectName("LibraryToggle")
        self.library_button.setText("Library")
        self.library_button.setAccessibleName("Show or hide the library panel")
        self.library_button.setToolTip("Toggle the library panel")
        self.library_button.setCheckable(True)
        self.library_button.setChecked(True)
        self.library_button.toggled.connect(self._set_library_visible)
        toolbar.addWidget(self.library_button)
        self.properties_button = QtWidgets.QToolButton()
        self.properties_button.setObjectName("PropertiesToggle")
        self.properties_button.setText("Properties")
        self.properties_button.setAccessibleName("Show or hide the properties panel")
        self.properties_button.setToolTip("Toggle the properties panel")
        self.properties_button.setCheckable(True)
        self.properties_button.setChecked(True)
        self.properties_button.toggled.connect(self._set_properties_visible)
        toolbar.addWidget(self.properties_button)
        self.addToolBar(toolbar)

    def _connection_changed(self, state, payload):
        scope = self._check_scene_access(payload) if state == 'connected' else None
        owners = {tuple(pair) for pair in payload.get('ungrouped_owners', ())} if state == 'connected' else set()
        if owners != self._ungrouped_owners:
            self._ungrouped_owners = owners
            self._update_ungroup_statuses()
            self._queue_inspector_refresh()
        if state != 'connected':
            self._ungroup_pending.clear()
        hide_supported = ('previews.hide' in payload.get('capabilities', ()) if state == 'connected' else None)
        if self._hide_supported != hide_supported:
            self._hide_supported = hide_supported
            self._changed()
        self._annotation_preview_supported = ('previews.annotations' in payload.get('capabilities', ())
                                              if state == 'connected' else None)
        panels = payload.get('panels') if state == 'connected' else None
        panel_session = payload['session_id'] if panels is not None else None
        if panel_session != self._panel_session:
            self._panel_session = panel_session
            self._panel_state = None
            self._panel_requests.clear()
        self._show_s3d_panels(panels)
        view = payload.get('viewport') if state == 'connected' else None
        session = payload['session_id'] if view is not None else None
        if session != self._cad_session:
            self._cad_session = session
            self._cad_view = None
            self._cad_pending = False
        self._show_cad_state(view)
        scene_status = ('Scene updates paused' if payload.get('scene', {}).get('token') else
                        'Update NoodleSBridge to enable scene updates' if state == 'connected' else
                        'Serpentine disconnected')
        if scope and 'previews.vector' in payload.get('capabilities',[]):
            if scope != self._preview_bridge_session:
                self.preview_service.stop()
                self._preview_bridge_session = scope
            if not self.preview_service.active:
                self.preview_service.start(scope)
                self._changed()
        else:
            self.preview_service.stop()
            self._preview_bridge_session = None
            for node in self.graph.all_nodes():
                if getattr(node,'OPERATION',None) in PREVIEW_SPECS:
                    node.scene_status = scene_status
                    node.scene_status_error = state=='connected'
        names = {"connected": "Connected", "connecting": "Connecting…",
                 "disconnected": "Disconnected", "incompatible": "Incompatible"}
        status = names[state] if state != 'connected' or scope or not payload['scene'].get('token') else scene_status
        self.connection_status.setText("Serpentine  ·  " + status)
        self.connection_status.setProperty("connected", state == "connected")
        self.connection_status.style().unpolish(self.connection_status)
        self.connection_status.style().polish(self.connection_status)
        if state == "connected":
            scene = payload["scene"]
            tooltip = (f"Serpentine3D {payload['serpentine_version']} · NoodleSBridge {payload['plugin_version']}\n"
                       f"{scene['object_count']} objects · Scene revision {scene['revision']}\n"
                       f"{scene['path'] or 'Unsaved document'}\nClick to reconnect.")
            if not scope:
                tooltip = scene_status + '\n' + tooltip
        else:
            tooltip = payload["message"] + "\nClick to reconnect."
        self.connection_status.setToolTip(tooltip)
        if scope and {"points.generate", "points.reference", "events"}.issubset(payload.get("capabilities", [])):
            if scope != self._point_bridge_session:
                self.point_service.stop()
                self._point_bridge_session = scope
                for node in self.graph.all_nodes():
                    if getattr(node, 'OPERATION', None) == FILLET_EDGE:
                        node.fillet_capture_pending = False
                    if getattr(node, 'OPERATION', None) in NATIVE_SCENE_OPERATIONS:
                        node.boolean_records = ()
                        node.boolean_ready = node.boolean_pending = False
                    if (getattr(node, 'measurement_details', None) or {}).get('error'):
                        node.measurement_details = None
            if not self.point_service.active:
                self.point_service.start(scope)
                self._changed()
        else:
            self._point_bridge_session = None
            self.point_service.stop()
            for node in self.graph.all_nodes():
                if getattr(node, 'OPERATION', None) == FILLET_EDGE:
                    node.fillet_capture_pending = False
                if getattr(node, 'OPERATION', None) in NATIVE_SCENE_OPERATIONS:
                    node.boolean_records = ()
                    node.boolean_ready = node.boolean_pending = False
                if getattr(node, "OPERATION", None) == "point" or getattr(node, 'OPERATION', None) in GEOMETRY_SPECS:
                    node.scene_status = scene_status
                    node.reference_error = node.scene_status
            self._changed()

    def _show_s3d_panels(self, panels=None):
        if panels is not None and (self._panel_state is None or panels['revision'] >= self._panel_state['revision']):
            self._panel_state = panels
        visibility = self._panel_state['visible'] if self._panel_state is not None else {}
        for panel, button in self.s3d_panel_buttons.items():
            visible = visibility.get(panel)
            button.setChecked(visible is True)
            button.setEnabled(visible is not None and panel not in self._panel_requests)
            if visible is None:
                tooltip = 'Connect to Serpentine3D with the updated NoodleSBridge.'
            else:
                action = 'Hide' if visible else 'Show'
                tooltip = f'{action} the {panel.title()} panel in Serpentine3D.'
            button.setToolTip(tooltip)

    def _toggle_s3d_panel(self, panel):
        visible = self._panel_state['visible'].get(panel) if self._panel_state else None
        if visible is None or panel in self._panel_requests:
            self._show_s3d_panels()
            return
        client = self.serpentine.client_for_session(self._panel_session)
        ticket = object()
        params = {'panel': panel, 'visible': not visible, 'session_id': self._panel_session}
        self._panel_requests[panel] = ticket
        self._show_s3d_panels()

        def request():
            panels, error = None, ''
            try:
                panels = client.call('ui.panels.set', params).get('panels')
            except BridgeError as exc:
                error = str(exc)
            try:
                self._panel_response.emit(panel, ticket, panels, error)
            except RuntimeError:
                pass

        threading.Thread(target=request, daemon=True, name='NoodleS-S3D-Panel').start()

    def _panel_finished(self, panel, ticket, panels, error):
        if self._closing or self._panel_requests.get(panel) is not ticket:
            return
        del self._panel_requests[panel]
        self._show_s3d_panels(panels)
        if error:
            self.statusBar().showMessage(error, 5000)

    def _show_cad_state(self, view=None):
        if view is not None and (self._cad_view is None or view['revision'] >= self._cad_view['revision']):
            self._cad_view = view
        self._show_cad_toolbar_button()
        for node in self.graph.all_nodes():
            if getattr(node, 'OPERATION', None) == 'cad_viewport':
                self._configure_cad_button(node)

    def _show_cad_toolbar_button(self):
        button = self.cad_view_button
        active = self._cad_view is not None and self._cad_view['enabled']
        button.setChecked(active)
        button.setEnabled(self._cad_view is not None and not self._cad_pending)
        high_smooth = self._cad_view.get('high_smooth') if self._cad_view else None
        self.high_smooth_action.setChecked(high_smooth is True)
        self.high_smooth_action.setEnabled(type(high_smooth) is bool and not self._cad_pending)
        if self._cad_pending:
            tooltip = 'Applying CAD View in Serpentine3D…'
        elif self._cad_view is None:
            tooltip = 'Connect to Serpentine3D with NoodleSBridge to use CAD View.'
        else:
            action = 'Disable' if active else 'Enable'
            tooltip = f'{action} CAD View in Serpentine3D.'
        button.setToolTip(tooltip)

    def _show_cad_view_menu(self, position):
        self.cad_view_menu.popup(self.cad_view_button.mapToGlobal(position))

    def _configure_cad_button(self, node):
        widget = node.get_widget('cad_view_button')
        if not getattr(widget, '_noodles_connected', False):
            widget.requested.connect(self._toggle_cad_view)
            widget._noodles_connected = True
        enabled = self._cad_view['enabled'] if self._cad_view is not None else None
        tooltip = ('Toggle CAD display for the current Serpentine session.' if enabled is not None else
                   'Connect to Serpentine3D with the updated NoodleSBridge.')
        widget.show_state(enabled, self._cad_pending, tooltip)

    @QtCore.Slot()
    def _toggle_cad_view(self):
        if self._cad_view is None or self._cad_pending:
            return
        self._request_cad_view({'enabled': not self._cad_view['enabled']})

    def _set_high_smooth(self, checked):
        if self._cad_view is None or 'high_smooth' not in self._cad_view or self._cad_pending:
            return
        self._request_cad_view({'high_smooth': checked})

    def _request_cad_view(self, params):
        session = self._cad_session
        client = self.serpentine.client_for_session(session)
        self._cad_pending = True
        self._show_cad_state()

        def request():
            view, error = None, ''
            try:
                view = client.call('viewport.set', {**params, 'session_id': session})['viewport']
            except BridgeError as exc:
                error = str(exc)
            try:
                self._cad_response.emit(session, view, error)
            except RuntimeError:
                pass

        threading.Thread(target=request, daemon=True, name='NoodleS-CAD-View').start()

    def _cad_finished(self, session, view, error):
        if session != self._cad_session or self._closing:
            return
        self._cad_pending = False
        self._show_cad_state(view)
        if error:
            self.statusBar().showMessage(error, 5000)

    def _initialize_point(self, node):
        if getattr(node, 'OPERATION', None) == 'cad_viewport':
            self._configure_cad_button(node)
            return
        if getattr(node, "OPERATION", None) != "point" and getattr(node, 'OPERATION', None) not in GEOMETRY_SPECS:
            return
        state = node.curve_state() if node.OPERATION in GEOMETRY_SPECS else node.point_state()
        if not state["project_uuid"]:
            node.set_property("project_uuid", self.project_uuid, push_undo=False)
        if not self._loading and any((getattr(other, "OPERATION", None) == "point" or getattr(other, 'OPERATION', None) in GEOMETRY_SPECS) and other is not node and
                                     other.get_property("node_uuid") == state["node_uuid"] for other in self.graph.all_nodes()):
            node.set_property("node_uuid", str(uuid.uuid4()), push_undo=False)
            node.set_property("references", [], push_undo=False)

    def _capture_points(self):
        node = self.graph.get_node_by_id(self.properties.node_id)
        if node and getattr(node, 'OPERATION', None) == FILLET_EDGE:
            self._capture_fillet_edges(node)
            return
        if node and getattr(node, 'OPERATION', None) in GEOMETRY_SPECS and node.get_property('mode') == 'reference':
            node.scene_status = 'Reading selected native objects…'
            self.point_service.capture(node.id, node.curve_state())
            self._refresh_inspector()
            return
        if node and getattr(node, "OPERATION", None) == "point" and node.get_property("mode") == "reference":
            node.scene_status = "Reading selected points…"
            self.point_service.capture(node.id, node.point_state())
            self._refresh_inspector()

    def _fillet_targets(self, node):
        ports = node.inputs()['G'].connected_ports()
        if not ports or not self.evaluation:
            raise ValueError('Connect a published or referenced solid to G.')
        port = ports[0]
        result = self.evaluation.results.get(port.node().id)
        if not result or result.error or port.name() not in result.outputs:
            raise ValueError('Wait for the solid source to finish evaluating.')
        from .backend.curves import input_tree
        descriptor = OPERATION_SPECS[FILLET_EDGE]['inputs'][0]
        tree = input_tree(result.outputs[port.name()], descriptor)
        bindings = result.bindings.get(port.name(), {})
        targets = {}
        for solid in tree.values():
            target = capture_target(bindings.get(solid.key))
            if target is None:
                raise ValueError('Set Edges needs published or referenced solid parts.')
            targets[target_key(target)] = target
        if not targets:
            raise ValueError('Connect one or more solid sources before setting edges.')
        return [targets[key] for key in sorted(targets)]

    def _capture_fillet_edges(self, node):
        state = node.curve_state()
        if (state['parameters']['fillet_mode'] != 'selected' or node.inputs()['E'].connected_ports()
                or getattr(node, 'fillet_capture_pending', False)):
            return
        try:
            if not self.point_service.active:
                raise ValueError('Connect to Serpentine first.')
            if self._pending or (self._graph_worker and self._graph_worker.running):
                raise ValueError('Wait for the graph to finish evaluating.')
            targets = self._fillet_targets(node)
        except ValueError as exc:
            self._point_event(node.id, 'fillet_capture_error', {'error': str(exc)})
            return
        node.fillet_capture_pending = True
        node.scene_status_error = False
        node.scene_status = 'Reading selected edges…'
        request = {key: state[key] for key in ('project_uuid', 'node_uuid', 'primitive')}
        self.point_service.capture(node.id, {**request, 'fillet_targets': targets})
        self._refresh_inspector()

    def _apply_native_boolean(self):
        node = self.graph.get_node_by_id(self.properties.node_id)
        if node is None or node.OPERATION not in NATIVE_SCENE_OPERATIONS or not getattr(node, 'boolean_ready', False):
            return
        if getattr(node, 'boolean_pending', False) or self._pending or (self._graph_worker and self._graph_worker.running):
            self.statusBar().showMessage('Wait for the graph to finish evaluating.')
            return
        result = self.evaluation.results.get(node.id)
        if not result or not result.boolean_plan:
            return
        node.boolean_pending = True
        node.scene_status_error = False
        node.scene_status = 'Preparing native ' + NATIVE_SCENE_OPERATIONS[node.OPERATION][0] + '…'
        self.point_service.apply_boolean(node.id, {**result.boolean_plan, 'scene_token': node.boolean_scene_token})
        self._refresh_inspector()

    def _preview_event(self, nodes, error):
        for node in self.graph.all_nodes():
            if getattr(node,'OPERATION',None) in PREVIEW_SPECS:
                if node.OPERATION in ANNOTATIONS and self._annotation_preview_supported is False:
                    continue
                if node.OPERATION == HIDE:
                    if self._hide_supported is not False:
                        node.scene_status = error or ('Visibility override active' if node.id in nodes else 'No visibility override')
                        node.scene_status_error = bool(error)
                    continue
                result = self.evaluation.results.get(node.id)
                if node.OPERATION == UV_GRID_PREVIEW and result and (result.error or '_sampling' in result.outputs):
                    continue
                visible = node.id in nodes
                if visible and node.OPERATION == UV_GRID_PREVIEW:
                    visible = bool(nodes[node.id]['items'])
                elif visible and node.OPERATION in ANNOTATIONS:
                    visible = any(item['visible'] for item in nodes[node.id]['items'])
                node.scene_status = error or ('Preview ready' if visible else 'Preview hidden')
                node.scene_status_error = bool(error)
        self._refresh_inspector()

    def _point_event(self, node_id, kind, data):
        if kind in ('ungroup', 'ungroup_error'):
            self._ungroup_pending.discard(node_id)
            self.statusBar().showMessage(data.get('error') or
                                         f"Ungrouped into {data.get('ungrouped')} native object(s).", 6000)
            return
        node = self.graph.get_node_by_id(node_id)
        if kind == 'remove_error':
            self.statusBar().showMessage('Unable to remove generated geometry: '+str(data))
            return
        if node is None or (getattr(node, "OPERATION", None) != "point" and getattr(node, 'OPERATION', None) not in GEOMETRY_SPECS):
            return
        if isinstance(data, dict) and data.get("node_uuid", node.get_property("node_uuid")) != node.get_property("node_uuid"):
            return
        if kind in ('fillet_capture', 'fillet_capture_error'):
            node.fillet_capture_pending = False
            try:
                if kind == 'fillet_capture_error':
                    raise ValueError(data['error'])
                parameters = node.get_property('parameters')
                if (parameters['fillet_mode'] != 'selected' or node.inputs()['E'].connected_ports()
                        or self._fillet_targets(node) != data.get('request_keys')):
                    raise ValueError('Fillet Edge inputs changed during selection. Click Set Edges again.')
                node.scene_status_error = False
                node.scene_status = 'Edges set'
                node.set_property('parameters', {**parameters, 'fillet_selection': data['measurements']})
            except ValueError as exc:
                node.scene_status_error = True
                node.scene_status = str(exc)
                self.statusBar().showMessage(str(exc), 6000)
            self._refresh_inspector()
            return
        if kind.startswith('boolean_'):
            if kind in ('boolean_apply', 'boolean_apply_error'):
                node.boolean_pending = False
            previous = getattr(node, 'boolean_records', ())
            if kind.endswith('_error'):
                node.scene_status_error = True
                node.scene_status = data['error']
                if kind == 'boolean_read_error':
                    node.boolean_ready = False
                    node.boolean_records = ()
            else:
                node.boolean_records = tuple(data.get('records', ()))
                node.boolean_scene_token = data.get('scene_token')
                node.boolean_ready = bool(node.boolean_scene_token) and not (data.get('consumed') or data.get('missing'))
                if node.boolean_records or not node.boolean_ready or previous or not node.scene_status_error:
                    node.scene_status_error = False
                    node.scene_status = ('Native result · Undo in Serpentine' if node.boolean_records else
                                         'Result consumed by another operation' if data.get('consumed') else
                                         'Native result missing · Undo in Serpentine' if data.get('missing') else
                                         'Ready to apply')
            if previous != getattr(node, 'boolean_records', ()):
                self._changed()
            self._refresh_inspector()
            return
        if kind == 'measured':
            node.measurement_details = data
            self._changed()
            return
        if kind in ('references', 'reference_error', 'reference_driven', 'reference_drive_error'):
            current = tuple(ref['key'] for ref in node.get_property('references'))
            incoming = tuple(ref['key'] for ref in data['references']) if kind == 'references' else data['request_keys']
            if node.get_property('mode') != 'reference' or incoming != current:
                return
        if kind in ("capture", "references"):
            if node.get_property("mode") != "reference":
                return
            node.reference_error = None
            if kind == "capture":
                node.reference_drive_error = None
            drive_error = getattr(node, 'reference_drive_error', None)
            node.scene_status_error = bool(drive_error)
            node.scene_status = drive_error or ("Live reference · edit native objects in Serpentine" if node.OPERATION in GEOMETRY_SPECS else
                                                "Live reference · move individual points in Serpentine")
            if kind == "capture":
                node.set_property("references", data["references"])
            else:
                # Coordinate snapshots are external source data, not graph edits.
                node.model.set_property("references", data["references"])
            self._changed()
        elif kind in ('reference_driven', 'reference_drive_error'):
            node.reference_drive_error = data.get('error')
            node.scene_status_error = bool(node.reference_error or node.reference_drive_error)
            node.scene_status = node.reference_error or node.reference_drive_error or 'Live reference · edit native objects in Serpentine'
        elif kind == "reference_error":
            node.scene_status_error = True
            node.reference_error = data['error']
            node.scene_status = node.reference_error
            self._changed()
        elif kind == 'moved':
            node.scene_status_error=False
            node.scene_status='Moved · source geometry retained'
        elif kind == "published":
            node.scene_status_error = False
            node.scene_status = (UNGROUPED_STATUS if data.get('detached') else
                                 "Consumed by native Boolean" if data.get('consumed') else
                                 "Published · one ParametricObject" if data.get("object_id") else
                                 "Empty result · no scene geometry")
            if node.OPERATION in ('curve', 'interpcurve',*OPERATION_SPECS) and node.get_property('mode') == 'generate':
                details = data.get('curve_details', {})
                if node.curve_details != details:
                    node.curve_details = details
                    self._changed()
        elif kind == "publishing":
            node.scene_status_error = False
            node.scene_status = str(data)
        elif kind == "error":
            node.scene_status_error = True
            node.scene_status = data.get("error", "Publication superseded") if isinstance(data, dict) else str(data)
        self._refresh_inspector()

    @staticmethod
    def _menu_icon():
        pixmap = QtGui.QPixmap(20, 20)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor("#d9e2eb"), 1.6, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
        painter.setPen(pen)
        for x in (4, 10, 16):
            painter.drawLine(x, 4, x, 16)
        painter.end()
        return QtGui.QIcon(pixmap)

    def _set_properties_visible(self, visible):
        self._set_side_panel_visible(2, self.properties_panel, "_properties_width", 290, visible)

    def _set_library_visible(self, visible):
        self._set_side_panel_visible(0, self.library_panel, "_library_width", 205, visible)

    def _set_side_panel_visible(self, index, panel, width_attr, minimum, visible):
        sizes = self.splitter.sizes()
        if not visible:
            if sizes[index] > 0:
                setattr(self, width_attr, sizes[index])
            panel.hide()
        else:
            panel.show()
            side_panels = (self.library_panel, self.properties_panel)
            visible_sides = sum(not side.isHidden() for side in side_panels)
            available = self.splitter.width() - self.splitter.handleWidth() * visible_sides
            other_width = sizes[2 if index == 0 else 0]
            width = min(getattr(self, width_attr), max(minimum, available - other_width - 430))
            sizes[index] = width
            sizes[1] = max(430, available - other_width - width)
            self.splitter.setSizes(sizes)

    def _filter_library(self, text):
        query = text.strip().casefold()
        for index in range(self.palette.topLevelItemCount()):
            category = self.palette.topLevelItem(index)
            matches = False
            for child_index in range(category.childCount()):
                child = category.child(child_index)
                visible = not query or query in child.text(0).casefold() or query in category.text(0).casefold()
                child.setHidden(not visible)
                matches = matches or visible
            category.setHidden(not matches)
            if query:
                category.setExpanded(True)

    def _add_library_item(self, item, _column=0):
        kind = item.data(0, QtCore.Qt.UserRole)
        if kind in self.node_ports:
            self.add_node(kind)

    def _add_search_result(self):
        for index in range(self.palette.topLevelItemCount()):
            category = self.palette.topLevelItem(index)
            if category.isHidden():
                continue
            for child_index in range(category.childCount()):
                child = category.child(child_index)
                if not child.isHidden():
                    self._add_library_item(child)
                    return

    def _show_node_search(self, graph):
        viewer = graph.viewer()
        self._search_node_position = graph.cursor_pos()
        anchor = viewer.viewport().mapToGlobal(viewer.mapFromScene(*self._search_node_position))
        self.node_search.open_at(anchor, self.palette.node_entries())

    def _add_popup_result(self, kind):
        self.graph.create_node(kind, pos=self._search_node_position)

    def _inspect_node(self, node):
        result = self.evaluation.results.get(node.id) if self.evaluation else None
        self.properties.show_node(node, result, self._format_value, self.evaluation)

    def _queue_inspector_refresh(self, *_args):
        if self._closing or self._inspector_refresh_pending:
            return
        self._inspector_refresh_pending = True
        # Read selection after Qt finishes handling the press, not during an
        # intermediate deselect/select notification within the same event.
        QtCore.QTimer.singleShot(0, self._flush_inspector_refresh)

    def _flush_inspector_refresh(self):
        self._inspector_refresh_pending = False
        if not self._closing:
            self._refresh_inspector()

    def _refresh_inspector(self, *_args):
        selected = self.graph.selected_nodes()
        node = selected[-1] if selected else None
        result = self.evaluation.results.get(node.id) if node and self.evaluation else None
        self.properties.show_node(node, result, self._format_value, self.evaluation)

    def _edit_inspected_property(self, name, value):
        node = self.graph.get_node_by_id(self.properties.node_id)
        if node is not None:
            node.set_property(name, value)

    def _action(self, menu, title, callback, shortcut=None):
        action = QtGui.QAction(title, self)
        if shortcut:
            action.setShortcut(shortcut)
            self.addAction(action)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def _build_actions(self):
        self.menuBar().hide()
        self.application_menu = QtWidgets.QMenu(self)
        menu = self.application_menu
        self._action(menu, "New document", self.new_document, "Ctrl+N")
        self._action(menu, "Open…", self.open_document, "Ctrl+O")
        self._action(menu, "Save", self.save_document, "Ctrl+S")
        self._action(menu, "Save as…", self.save_as, "Ctrl+Shift+S")
        menu.addSeparator()
        # Context-menu commands own canvas shortcuts. Avoid registering a second
        # Ctrl+Z on the main window, which would make Qt shortcuts ambiguous.
        self._action(menu, "Undo", self.graph.undo_stack().undo)
        self._action(menu, "Redo", self.graph.undo_stack().redo)
        self._action(menu, "Copy", self.graph.copy_nodes)
        self._action(menu, "Paste", self.graph.paste_nodes)
        self._action(menu, "Delete selected", self._delete_selected)
        menu.addSeparator()
        frame_graph = self.graph.viewer().frame_graph
        self._action(menu, "Frame graph", frame_graph)
        self.fit_shortcut = QtGui.QShortcut(QtGui.QKeySequence("F"), self.graph.widget)
        self.fit_shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        self.fit_shortcut.activated.connect(frame_graph)
        menu.addSeparator()
        self._action(menu, "Reconnect to Serpentine", lambda: self.serpentine.reconnect())
        self._action(menu, "Disconnect from Serpentine", lambda: self.serpentine.stop())
        menu.addSeparator()
        self._action(menu, "Help", self.show_help, "F1")
        self._action(menu, "About NoodleS", self.show_about)
        menu.addSeparator()
        self._action(menu, "Exit", self.close, "Ctrl+Q")

        context = self.graph.get_context_menu("graph")
        canvas_menu = context.qmenu
        canvas_menu.setObjectName("CanvasContextMenu")
        canvas_menu.setStyleSheet(CANVAS_MENU_STYLE)
        first_action = canvas_menu.actions()[0]
        search = context.add_command("Search Nodes…", self._show_node_search)
        canvas_menu.insertAction(first_action, search.qaction)
        export = context.add_command("Export Graph Image…", lambda graph: self.export_graph_image())
        canvas_menu.insertAction(first_action, export.qaction)
        canvas_menu.insertSeparator(first_action)
        # NodeGraphQt already supplies native QUndoStack actions here. A second
        # Ctrl+Z action makes Qt reject the ambiguous shortcut after deletion.
        redo = self.graph.viewer()._redo_action
        if redo is not None:
            keys = QtGui.QKeySequence.keyBindings(QtGui.QKeySequence.Redo)
            keys.append(QtGui.QKeySequence('Ctrl+Shift+Z'))
            redo.setShortcuts(list({key.toString(): key for key in keys}.values()))
        context.add_command("Copy", lambda graph: graph.copy_nodes(), "Ctrl+C")
        context.add_command("Paste", lambda graph: graph.paste_nodes(), "Ctrl+V")
        context.add_command("Delete selected", lambda graph: self._delete_selected(), "Delete")
        context.add_command("Select all", lambda graph: graph.select_all(), "Ctrl+A")
        self._ungroup_separator = canvas_menu.addSeparator()
        self._ungroup_action = self._action(canvas_menu, "Ungroup Parametric Object", self._ungroup_context_node)
        self._ungroup_node_id = None
        self._ungroup_action.setVisible(False)
        self._ungroup_separator.setVisible(False)
        self.graph.viewer().context_node.connect(self._set_ungroup_target)

    def _set_ungroup_target(self, node_id):
        self._ungroup_node_id = node_id
        node = self.graph.get_node_by_id(node_id) if node_id is not None else None
        model = getattr(node, 'parametric_object', None)
        generated = model is not None and model.mode == 'generate' and model.parts.count > 0
        self._ungroup_action.setVisible(generated)
        self._ungroup_separator.setVisible(generated)
        info = self.serpentine.info or {}
        self._ungroup_action.setEnabled(
            generated and 'geometry.ungroup' in info.get('capabilities', ())
            and self.point_service.active and node_id not in self._ungroup_pending
            and (model.project_uuid, model.node_uuid) not in self._ungrouped_owners)

    def _ungroup_context_node(self):
        node_id = self._ungroup_node_id
        self._set_ungroup_target(node_id)
        if not self._ungroup_action.isEnabled():
            return
        model = self.graph.get_node_by_id(node_id).parametric_object
        self._ungroup_pending.add(node_id)
        self.point_service.ungroup(node_id, {'project_uuid': model.project_uuid, 'node_uuid': model.node_uuid})

    def _update_ungroup_statuses(self):
        for node in self.graph.all_nodes():
            model = getattr(node, 'parametric_object', None)
            if model and model.mode == 'generate' and (model.project_uuid, model.node_uuid) in self._ungrouped_owners:
                node.scene_status = UNGROUPED_STATUS
                node.scene_status_error = False
            elif getattr(node, 'scene_status', None) == UNGROUPED_STATUS:
                node.scene_status = 'Published · one ParametricObject'

    def add_node(self, kind):
        node = self.graph.create_node(kind)
        self.graph.clear_selection()
        node.set_selected(True)
        return node

    def _delete_selected(self):
        nodes = self.graph.selected_nodes()
        if nodes:
            self.graph.delete_nodes(nodes)

    def _changed(self, *_args):
        if self._loading or self._closing:
            return
        if self._graph_worker:
            self._graph_worker.invalidate()
        self._update_title()
        # Editable parameters (especially Undo) reflect the current model at
        # once; their refresh must not wait for a busy data/OCC dependency.
        self._queue_inspector_refresh()
        if not self._pending:
            self._pending = True
            # One event-loop handoff collects signals from a single graph edit.
            # No time-based debounce or guessed geometry delay.
            QtCore.QTimer.singleShot(0, self._evaluate_pending)

    def _evaluate_pending(self):
        if self._pending:
            self._pending = False
            if not self._loading and not self._closing:
                self.evaluate_now()

    def snapshot(self):
        nodes = []
        point_ids = set()
        for node in self.graph.all_nodes():
            operation = getattr(node, "OPERATION", None)
            if operation in (None, 'cad_viewport'):
                continue
            if operation == "point" or operation in GEOMETRY_SPECS:
                if node.get_property("node_uuid") in point_ids:
                    # Clipboard deserialization may restore custom properties
                    # after node_created. A copy must never inherit ownership.
                    node.set_property("node_uuid", str(uuid.uuid4()), push_undo=False)
                    node.set_property("references", [], push_undo=False)
                point_ids.add(node.get_property("node_uuid"))
            inputs = {}
            for port in node.input_ports():
                connected = port.connected_ports()
                if connected:
                    source = connected[0]
                    inputs[port.name()] = Connection(source.node().id, source.name())
            parameters = {"value": node.get_property("value")} if operation in ("number", "slider") else {}
            if operation == "slider":
                parameters = node.slider_state()
            elif operation == "number":
                parameters = node.number_state()
            elif operation == "point":
                parameters = node.point_state()
                parameters["reference_error"] = node.reference_error
            elif operation in GEOMETRY_SPECS:
                parameters = node.curve_state()
                if operation == 'objects_on_points':
                    parameters['node_name'] = node.name()
                elif operation == 'read_csv' and self.path is not None:
                    parameters['graph_directory'] = Path(self.path).absolute().parent
                parameters['reference_error'] = node.reference_error
                parameters['curve_details'] = node.curve_details
                if operation in NATIVE_SCENE_OPERATIONS:
                    parameters['boolean_records'] = getattr(node, 'boolean_records', ())
                if operation == 'pull_point':
                    parameters['pull_details'] = getattr(node, 'measurement_details', None)
                elif operation in MEASUREMENT_METHODS:
                    parameters['sampling_details'] = getattr(node, 'measurement_details', None)
            elif operation == "domain":
                parameters = node.domain_state()
            elif operation == "range":
                parameters = node.range_state()
            elif operation in ("addition", "multiplication"):
                parameters = node.arithmetic_state()
            elif operation in MATH_SPECS:
                parameters = node.math_state()
            nodes.append(NodeSpec(node.id, operation, parameters, inputs, node.disabled()))
        return nodes

    @staticmethod
    def _format_value(value):
        if isinstance(value,TranslationValue):
            return 'Translation ('+', '.join(format(v,'.7g') for v in value.vector)+')'
        if isinstance(value,TranslatedValue):
            return 'Moved '+value.source.kind.replace('_',' ').title()
        if isinstance(value, RigidValue):
            return 'Transformed '+value.source.kind.replace('_',' ').title()
        if isinstance(value,OperationValue):
            return value.kind.title()+' · deferred geometry'
        if isinstance(value, SurfaceReferenceValue):
            return value.native_kind.title()+' · live reference'
        if isinstance(value, GridValue):
            return value.kind.removeprefix('grid_').title()+' Grid ('+' × '.join(map(str,value.extents))+')'
        if isinstance(value, SolidValue):
            return value.kind.title()+' · '+('Solid' if value.solid else 'Shell')
        if isinstance(value, CurveValue):
            if value.kind in ('curve', 'interpcurve'):
                return value.kind.title()+' · degree '+str(value.degree)
            return value.kind.title()+' · length '+format(value.length, '.7g')
        if isinstance(value, PlaneValue):
            return 'Plane · O '+str(tuple(round(v, 6) for v in value.origin))+' · N '+str(tuple(round(v, 6) for v in value.normal))
        if isinstance(value, VectorValue):
            return "Vector(" + ", ".join(format(v, ".7g") for v in value.xyz) + ")"
        if isinstance(value, DomainValue):
            return "[" + format(value.start, ".10g") + " → " + format(value.end, ".10g") + "]"
        if isinstance(value, PointValue):
            return "(" + ", ".join(format(v, ".7g") for v in value.xyz) + ")"
        if isinstance(value, DataTree):
            preview = []
            for branch in value.branches[:3]:
                items = ", ".join(MainWindow._format_value(v) for v in branch.items[:3])
                preview.append("{" + ";".join(map(str, branch.path)) + "}: " + items + (" …" if len(branch.items) > 3 else ""))
            return f"{value.count} item(s) · {len(value.branches)} branch(es)\n" + "\n".join(preview)
        if type(value) is float:
            return format(value, ".10g")
        if isinstance(value, tuple):
            return "(" + ", ".join(MainWindow._format_value(v) for v in value) + ")"
        return str(value)

    def evaluate_now(self):
        snapshot = self.snapshot()
        if self._graph_worker is None and any(
                n.operation.startswith('grid_') or n.operation in OPERATION_SPECS
                or n.operation in NATIVE_SCENE_OPERATIONS or n.operation in MOVE_SPECS
                or n.operation in MEASUREMENT_METHODS or n.operation in MESH_SPECS for n in snapshot):
            self._graph_worker = GraphWorker(self.engine,self)
            self._graph_worker.ready.connect(self._apply_evaluation)
            self._graph_worker.failed.connect(lambda error: self.statusBar().showMessage('Evaluation error: '+error))
        if self._graph_worker:
            self._graph_worker.request(snapshot)
        else:
            self._apply_evaluation(self.engine.evaluate(snapshot))

    def _apply_evaluation(self, evaluation):
        if self._closing:
            return
        self.evaluation = evaluation
        models, references, previews, measurements = {}, {}, {}, {}
        failures = 0
        for node in self.graph.all_nodes():
            if getattr(node, 'OPERATION', None) == 'cad_viewport':
                self._configure_cad_button(node)
                continue
            result = self.evaluation.results.get(node.id)
            if result is None:
                continue
            if result.error:
                failures += 1
                display = result.error
                summary = node.name() + " — " + display
            else:
                display = self._format_value(next(iter(result.outputs.values())))
                summary = node.name() + " = " + display
            node.view.setToolTip(summary)
            if getattr(node, "OPERATION", None) == "watch":
                node.get_widget("display").set_value(display)
            if getattr(node, 'OPERATION', None) in GEOMETRY_SPECS:
                node.parametric_object = result.parametric_object
                state = node.curve_state()
                if node.OPERATION in NATIVE_SCENE_OPERATIONS:
                    references[node.id] = state
                    continue
                method = MEASUREMENT_METHODS.get(node.OPERATION)
                if method:
                    publishes = node.OPERATION in (*TOPOLOGY_OPERATIONS, *TESSELLATION_SPECS, BRACED_GRID,
                                                   UV_PANELS, SURFACE_BOX, ARRAY_ALONG_CURVE, PENROSE, BREP_TO_MESH)
                    pull = method == 'geometry.pull'
                    request = result.outputs.get('_pull' if pull else '_sampling')
                    if request is not None:
                        measurements[node.id] = {**request, 'method': method}
                        message = {'geometry.pull': 'Measuring closest points…',
                                   'geometry.sample': 'Sampling native curves…',
                                   'geometry.surface_domain': 'Reading native surface UV bounds…',
                                   'geometry.surface_closest': 'Finding closest points on native surfaces…',
                                   'geometry.topology': 'Preparing native topology…',
                                   'geometry.mass_properties': 'Measuring native geometry…',
                                   'geometry.population': 'Sampling native geometry…',
                                   'geometry.tessellation': 'Triangulating point branches…',
                                   'geometry.surface_structure': 'Preparing native surface structure…',
                                   'geometry.uv_grid': 'Preparing UV preview…'}[method]
                        if node.OPERATION == 'surface_evaluate':
                            message = 'Sampling native surfaces…'
                        elif node.OPERATION == VORONOI:
                            message = 'Preparing Voronoi cells…'
                        elif node.OPERATION == HEXAGON_TILING:
                            message = 'Preparing hexagon tiling…'
                        elif node.OPERATION == PENROSE:
                            message = 'Preparing Penrose P2 tiles…'
                        elif node.OPERATION == BREP_TO_MESH:
                            message = 'Meshing native Breps…'
                        node.scene_status = (message if self.point_service.active else
                                             'Connect to Serpentine to measure geometry.')
                    elif not publishes and node.OPERATION != UV_GRID_PREVIEW:
                        node.scene_status = ''
                    if node.OPERATION == UV_GRID_PREVIEW and request is None:
                        if result.error:
                            node.scene_status = result.error
                            node.scene_status_error = True
                        elif not node.disabled():
                            node.scene_status = 'Preview ready' if result.outputs['Count'] else 'Preview hidden'
                            node.scene_status_error = False
                    elif not publishes and node.OPERATION != UV_GRID_PREVIEW:
                        node.scene_status_error = False
                        continue
                    if request is not None:
                        node.scene_status_error = False
                        if node.OPERATION == UV_GRID_PREVIEW and node.id in self.preview_service.nodes:
                            previews[node.id] = self.preview_service.nodes[node.id]
                        elif node.id in self.point_service.models:
                            models[node.id] = self.point_service.models[node.id]
                        continue
                if node.OPERATION in DATA_HELPER_SPECS and node.OPERATION != 'point_cylindrical':
                    node.scene_status = ''
                    continue
                if node.OPERATION in PREVIEW_SPECS:
                    if node.OPERATION == HIDE:
                        targets = result.outputs.get('_hide_targets')
                        if self._hide_supported is False:
                            node.scene_status = 'Run noodlesrefresh in Serpentine to enable Hide.'
                            node.scene_status_error = True
                        elif targets:
                            previews[node.id] = {'project_uuid': state['project_uuid'], 'node_uuid': state['node_uuid'],
                                                 'items': [], 'hide_targets': [list(target) for target in targets]}
                        else:
                            node.scene_status = 'No visibility override'
                            node.scene_status_error = False
                        continue
                    if node.OPERATION in ANNOTATIONS and self._annotation_preview_supported is False:
                        node.scene_status = 'Run noodlesrefresh in Serpentine to enable annotations.'
                        node.scene_status_error = True
                        continue
                    if not node.disabled():
                        if not result.error:
                            previews[node.id] = preview_payload(state,result.outputs)
                        elif node.id in self.preview_service.nodes:
                            previews[node.id] = self.preview_service.nodes[node.id]
                    continue
                if not node.disabled() and state['mode'] == 'reference' and state['references']:
                    if result.reference_drive is not None:
                        state['drive'] = result.reference_drive
                    elif node.reference_error:
                        state['drive_paused'] = True
                    elif getattr(node, 'reference_drive_error', None):
                        node.reference_drive_error = None
                        node.scene_status_error = False
                        node.scene_status = 'Live reference · edit native objects in Serpentine'
                    references[node.id] = state
                elif not node.disabled() and state['mode'] == 'generate':
                    if not result.error and node.id not in evaluation.frozen_owners:
                        if result.parametric_object is None:
                            if node.OPERATION == 'move' and not any(binding.reference_id for binding in result.movements):
                                node.scene_status_error = False
                                node.scene_status = 'Uses source geometry'
                            elif node.OPERATION == CURVES:
                                node.scene_status_error = False
                                node.scene_status = 'Passing input curves'
                            elif node.OPERATION == ARRAY_ALONG_CURVE:
                                node.scene_status_error = False
                                node.scene_status = 'Transforms ready'
                            continue
                        models[node.id] = {'model': result.parametric_object.to_wire(), 'name': node.name()}
                        if result.hidden_parents:
                            models[node.id]['hidden_parents'] = [list(target) for target in result.hidden_parents]
                    elif node.id in self.point_service.models:
                        # Invalid edits must not delete the last valid owner or its attributes.
                        previous = self.point_service.models[node.id]
                        models[node.id] = {k: v for k, v in previous.items() if k != 'hidden_parents'}
            if getattr(node, "OPERATION", None) == "point":
                node.parametric_object = result.parametric_object
                state = node.point_state()
                if not node.disabled() and state["mode"] == "reference" and state["references"]:
                    if not result.error:
                        incoming = {}
                        for port in node.input_ports():
                            sources = port.connected_ports()
                            if sources:
                                source = sources[0]
                                incoming[port.name()] = self.evaluation.results[source.node().id].outputs[source.name()]
                        state["drive"] = reference_drive(state, incoming)
                    references[node.id] = state
                elif state["mode"] == "generate" and not result.error and node.id not in evaluation.frozen_owners:
                    models[node.id] = {"model": result.parametric_object.to_wire(), "name": node.name()}
                elif state['mode']=='generate' and node.id in evaluation.frozen_owners and node.id in self.point_service.models:
                    models[node.id]=self.point_service.models[node.id]
        self._update_ungroup_statuses()
        self.point_service.sync(models, references, measurements)
        self.point_service.sync_movements(evaluation.reference_moves,evaluation.frozen_owners)
        self.preview_service.sync(previews)
        total = len(self.evaluation.results)
        message = "Ready" if not total else f"Nodes: {total}"
        message += f" · needs attention: {failures}" if failures else ""
        self.statusBar().showMessage(message)
        self._refresh_inspector()

    def _reset_engine(self):
        self.preview_service.sync({})
        if self._graph_worker:
            self._graph_worker.stop()
            self._graph_worker.deleteLater()
            self._graph_worker = None
        self.engine = GraphEngine()

    @contextmanager
    def _load_guard(self):
        self._loading = True
        try:
            yield
        finally:
            self._loading = False

    def _build_example(self):
        with self._load_guard():
            a = self.graph.create_node("NoodleS.Inputs.SliderNode", pos=(-600, -100))
            a.set_property("value", 25.0)
            b = self.graph.create_node("NoodleS.Inputs.NumberNode", pos=(-600, 120))
            b.set_property("value", 10.0)
            add = self.graph.create_node("NoodleS.Math.AdditionNode", pos=(-120, -50))
            multiply = self.graph.create_node("NoodleS.Math.MultiplicationNode", pos=(160, -50))
            watch = self.graph.create_node("NoodleS.Data.WatchNode", pos=(520, -50))
            a.output(0).connect_to(add.input(0))
            b.output(0).connect_to(add.input(1))
            add.output(0).connect_to(multiply.input(0))
            b.output(0).connect_to(multiply.input(1))
            multiply.output(0).connect_to(watch.input(0))
            self.graph.clear_selection()
            self.graph.undo_stack().clear()
        QtCore.QTimer.singleShot(0, self.graph.fit_to_selection)

    def _confirm_discard(self):
        if self.graph.undo_stack().isClean():
            return True
        buttons = QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel
        dialog = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.NoIcon, "Unsaved changes",
            "Save changes to the current document?", buttons, self,
        )
        dialog.setDefaultButton(QtWidgets.QMessageBox.Save)
        answer = dialog.exec()
        dialog.deleteLater()
        if answer == QtWidgets.QMessageBox.Cancel:
            return False
        return self.save_document() if answer == QtWidgets.QMessageBox.Save else True

    def _update_title(self, *_args):
        if self._closing:
            return
        name = self.path.name if self.path else "Untitled"
        marker = " *" if not self.graph.undo_stack().isClean() else ""
        self.setWindowTitle(f"{name}{marker} — NoodleS")
        self.canvas_panel.title_label.setText(name + marker)

    def new_document(self):
        if not self._confirm_discard():
            return
        self.point_service.clear_context()
        self.project_uuid = str(uuid.uuid4())
        with self._load_guard():
            self.graph.clear_session()
        self.path = None
        self._scene_link = None
        self.serpentine.graph_target = None
        self._declined_scene = None
        self._authorize_scene(self._scene_scope(self.serpentine.info))
        self._reset_engine()
        self.properties.clear_bin()
        self.graph.undo_stack().setClean()
        self._update_title()
        self.evaluate_now()
        self._refresh_scene_access()

    def example_document(self):
        if not self._confirm_discard():
            return
        self.point_service.clear_context()
        self.project_uuid = str(uuid.uuid4())
        with self._load_guard():
            self.graph.clear_session()
        self.path = None
        self._scene_link = None
        self.serpentine.graph_target = None
        self._declined_scene = None
        self._authorize_scene(self._scene_scope(self.serpentine.info))
        self._reset_engine()
        self.properties.clear_bin()
        self._build_example()
        # An explicit example command creates a new, unsaved document.
        self.graph.undo_stack().resetClean()
        self._update_title()
        self.evaluate_now()
        self._refresh_scene_access()

    @staticmethod
    def _scene_scope(info):
        if info and (token := info['scene'].get('token')):
            return (info['session_id'], token)
        return None

    @staticmethod
    def _scene_mismatch(scene, project_uuid, link):
        if not link:
            if scene['path'] or scene['object_count'] or scene.get('graph_link'):
                return 'This graph has no saved link to the current Serpentine document.'
        elif link['document_uuid'] != scene.get('document_uuid'):
            return 'This graph is linked to a different Serpentine document.'
        elif not scene_matches_graph(scene, project_uuid, link):
            return 'The current Serpentine document was paired with a different graph or saved version.'
        return None

    def _authorize_scene(self, scope):
        if scope != self._authorized_scene:
            self.point_service.clear_context(restart=False)
            self.preview_service.stop()
            self.preview_service.sync({})
            self._authorized_scene = scope

    def _check_scene_access(self, info):
        scope = self._scene_scope(info)
        if scope is None or scope == self._authorized_scene:
            return scope
        if self._opening_graph or self._closing or scope == self._declined_scene:
            return None
        if self.path is None and (self._authorized_scene is None or not self.graph.all_nodes()):
            self._authorize_scene(scope)
            return scope
        if self.path is not None and not self._scene_mismatch(info['scene'], self.project_uuid, self._scene_link):
            self._authorize_scene(scope)
            return scope
        QtCore.QTimer.singleShot(0, self._confirm_active_scene)
        return None

    def _refresh_scene_access(self):
        if not self._closing and self.serpentine.info:
            self._connection_changed('connected', self.serpentine.info)

    def _confirm_active_scene(self):
        info = self.serpentine.info
        scope = self._scene_scope(info)
        if self._closing or self._opening_graph or not scope or scope in (self._authorized_scene, self._declined_scene):
            return
        reason = (self._scene_mismatch(info['scene'], self.project_uuid, self._scene_link) if self.path else
                  'The Serpentine document changed while this graph was open.')
        self._opening_graph = True
        try:
            choice = self._ask_scene_mismatch(self.path, self._scene_link, info['scene'], reason) if reason else 'continue'
            if choice == 'continue' and scope == self._scene_scope(self.serpentine.info):
                self._authorize_scene(scope)
            else:
                self._declined_scene = scope
        finally:
            self._opening_graph = False
        if choice == 'choose':
            self.open_document()
        self._refresh_scene_access()

    def _ask_scene_mismatch(self, path, link, scene, reason):
        dialog = QtWidgets.QMessageBox(self)
        dialog.setIcon(QtWidgets.QMessageBox.Warning)
        dialog.setWindowTitle('Graph and Serpentine document mismatch')
        dialog.setTextFormat(QtCore.Qt.PlainText)
        dialog.setText(reason)
        graph_name = path.name if path else 'Untitled'
        scene_name = Path(scene['path']).name if scene['path'] else 'Unsaved document'
        saved_scene = f"\nLinked Serpentine document: {link['scene_name']}" if link else ''
        dialog.setInformativeText(f'Graph: {graph_name}\nCurrent Serpentine document: {scene_name}{saved_scene}\n\n'
                                  'Continue Anyway allows this graph to change the current scene.')
        proceed = dialog.addButton('Continue Anyway', QtWidgets.QMessageBox.AcceptRole)
        choose = dialog.addButton('Choose Another Graph…', QtWidgets.QMessageBox.ActionRole)
        cancel = dialog.addButton(QtWidgets.QMessageBox.Cancel)
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        return {proceed: 'continue', choose: 'choose'}.get(dialog.clickedButton(), 'cancel')

    def open_document(self, path=None):
        if self._opening_graph:
            return
        self._opening_graph = True
        try:
            self._open_graph(path)
        finally:
            self._opening_graph = False
            self._refresh_scene_access()

    def _find_open_scene(self, current, project, link, *, recheck=False):
        client = self.serpentine.client
        error = None
        if current:
            active = self.serpentine.client_for_session(current["session_id"])
            try:
                current = active.call("status")
            except BridgeError as exc:
                current, error = None, exc
        if link and not recheck and getattr(client, "discover", False):
            if not current or self._scene_mismatch(current["scene"], project, link):
                exclude = (current["session_id"],) if current else ()
                match = client.find_scene(project, link, exclude=exclude)
                if match:
                    return match
        if error:
            raise error
        return current

    def _check_open_scene(self, project, link, *, checked=...):
        # Confirm against the active document, even immediately after CAD Open.
        # Serialize with saves so a just-saved graph uses the latest link.
        current = self.serpentine.info if checked is ... else checked
        query = self._scene_requests.submit(self._find_open_scene, current, project, link, recheck=checked is not ...)
        loop = QtCore.QEventLoop()
        timer = QtCore.QTimer()
        timer.timeout.connect(lambda: loop.quit() if query.done() else None)
        timer.start(10)
        loop.exec(QtCore.QEventLoop.ExcludeUserInputEvents)
        timer.stop()
        info = query.result()
        visible = self.serpentine.info
        if not self._closing and info and visible and info["session_id"] == visible["session_id"]:
            self.serpentine.observe_status(info)
        return info

    def _open_graph(self, path):
        while not self._closing:
            if not path:
                filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Open graph', str(self.path or ''), FILE_FILTER)
                if not filename:
                    return
                path = Path(filename)
            try:
                session = read_document(path, self.node_ports)
            except (OSError, DocumentError, TypeError, OverflowError) as exc:
                self._error('Unable to open graph', exc)
                return
            project = session['graph']['project_uuid']
            link = session['graph'].get('scene_link')
            try:
                info = self._check_open_scene(project, link)
            except BridgeError as exc:
                self._error('Unable to check the current Serpentine document', exc)
                return
            scope = self._scene_scope(info)
            reason = self._scene_mismatch(info['scene'], project, link) if scope else None
            if reason:
                choice = self._ask_scene_mismatch(path, link, info['scene'], reason)
                if choice != 'continue' and scope != self._authorized_scene:
                    self._declined_scene = scope
                if choice == 'choose':
                    path = None
                    continue
                if choice == 'cancel':
                    return
            was_dirty = not self.graph.undo_stack().isClean()
            if self._closing or not self._confirm_discard():
                return
            if reason or was_dirty:
                try:
                    current = self._check_open_scene(project, link, checked=info)
                    if (scope != self._scene_scope(current) or (scope and not reason and
                            self._scene_mismatch(current['scene'], project, link))):
                        continue  # The decision applied to a different open scene.
                except BridgeError as exc:
                    self._error('Unable to check the current Serpentine document', exc)
                    return
            try:
                self.load_session(session, path, scene_scope=scope)
                self._declined_scene = None
                if info:
                    self.serpentine.observe_status(info)
            except Exception as exc:
                LOG.exception('Graph load failed')
                self._error('Unable to open graph', exc)
            return

    def load_session(self, session, path=None, *, scene_scope=...):
        """Validate first; restore the prior graph if library loading fails."""
        previous = self.graph.serialize_session()
        previous_project = self.project_uuid
        self.point_service.clear_context()
        self.project_uuid = session.get("graph", {}).get("project_uuid", self.project_uuid)
        try:
            with self._load_guard():
                self.graph.deserialize_session(copy.deepcopy(session))
                self.graph.set_acyclic(True)
        except Exception:
            self.project_uuid = previous_project
            with self._load_guard():
                self.graph.deserialize_session(previous)
            raise
        if scene_scope is not ...:
            self._authorize_scene(scene_scope)
        self.path = path
        self._scene_link = session.get('graph', {}).get('scene_link')
        self.serpentine.graph_target = (self.project_uuid, self._scene_link) if self._scene_link else None
        self._reset_engine()
        self.properties.clear_bin()
        self.evaluate_now()
        self.graph.clear_selection()
        self.graph.fit_to_selection()
        self.graph.undo_stack().setClean()
        self._update_title()

    def save_document(self):
        return self._save_to(self.path) if self.path else self.save_as()

    def export_graph_image(self):
        viewer = self.graph.viewer()
        if not any(item.isVisible() for item in viewer.all_nodes()):
            self._error("Unable to export graph image", "Add a node before exporting an image.")
            return False
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Graph Image", str(self.path.with_suffix(".png") if self.path else "Untitled.png"),
            "PNG Image (*.png)",
        )
        if not filename:
            return False
        path = Path(filename)
        if path.suffix.lower() != ".png":
            path = path.with_suffix(".png")
            if path.exists() and QtWidgets.QMessageBox.question(
                    self, "Replace file?", f"{path.name} already exists. Replace it?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
                return False
        try:
            save_graph_image(viewer, path)
        except (OSError, ValueError) as exc:
            self._error("Unable to export graph image", exc)
            return False
        self.statusBar().showMessage("Exported: " + str(path), 5000)
        return True

    def save_as(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save graph", str(self.path or "Untitled.noodles"), FILE_FILTER,
        )
        if not filename:
            return False
        path = Path(filename)
        if path.suffix.lower() != ".noodles":
            path = path.with_suffix(".noodles")
            if path.exists():
                answer = QtWidgets.QMessageBox.question(
                    self, "Replace file?", f"{path.name} already exists. Replace it?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No,
                )
                if answer != QtWidgets.QMessageBox.Yes:
                    return False
        return self._save_to(path)

    def _save_to(self, path):
        info = self.serpentine.info
        scope = self._scene_scope(info)
        scene = info['scene'] if scope and scope == self._authorized_scene else None
        link = self._scene_link
        if scene and (not link or link['document_uuid'] != scene['document_uuid']):
            link = {
                'document_uuid': scene['document_uuid'],
                'revision': uuid.uuid4().hex,
                'accept_unpaired_scene': (
                    scene.get('persistent_document_uuid', False) and not scene.get('graph_link')
                ),
            }
        elif link and (path != self.path or not self.graph.undo_stack().isClean()):
            link = {**link, 'revision': uuid.uuid4().hex,
                    'previous_revisions': [*link.get('previous_revisions', ()), link['revision']]}
        if scene:
            link = {**link, 'scene_name': Path(scene['path']).name if scene['path'] else 'Unsaved document'}
        try:
            session = self.graph.serialize_session()
            graph = session.setdefault('graph', {})
            graph['project_uuid'] = self.project_uuid
            if link:
                graph['scene_link'] = link
            write_document(path, session)
        except (OSError, ValueError, TypeError) as exc:
            self._error("Unable to save graph", exc)
            return False
        path_changed = self.path != path
        self.path = path
        self._scene_link = link
        self.serpentine.graph_target = (self.project_uuid, link) if link else None
        self.graph.undo_stack().setClean()
        self._update_title()
        self.statusBar().showMessage("Saved: " + str(path), 5000)
        if scene:
            record = {'document_uuid': link['document_uuid'], 'project_uuid': self.project_uuid,
                      'revision': link['revision']}
            if scene.get('graph_link') != record:
                client = self.serpentine.client.for_scene(scope)
                self._scene_requests.submit(self._write_scene_link, client, record)
        if path_changed and any(getattr(node, 'OPERATION', None) == 'read_csv' for node in self.graph.all_nodes()):
            self._changed()
        return True

    def _write_scene_link(self, client, record):
        error = None
        try:
            client.call('scene.link_graph', record)
        except BridgeError as exc:
            error = str(exc)
        try:
            self._scene_link_saved.emit(record, error)
        except RuntimeError:
            pass  # The saved graph can outlive its editor window.

    def _show_scene_link_result(self, record, error):
        if not self._closing and self._scene_link and record['revision'] == self._scene_link['revision']:
            message = ('Graph saved.' if error is None else
                       f'Graph saved. Serpentine document link could not be saved: {error}')
            self.statusBar().showMessage(message, 8000)

    def _error(self, title, error):
        QtWidgets.QMessageBox.warning(self, title, str(error))

    def show_help(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("NoodleS — Help")
        dialog.resize(650, 640)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)

        guide = QtWidgets.QTextBrowser(dialog)
        guide.setAccessibleName("NoodleS quick guide")
        guide.setFrameShape(QtWidgets.QFrame.NoFrame)
        palette = guide.palette()
        palette.setColor(QtGui.QPalette.Base, palette.color(QtGui.QPalette.Window))
        guide.setPalette(palette)
        guide.document().setDefaultStyleSheet("""
            h2 { font-size: 13pt; font-weight: 600; margin: 14px 0 5px; }
            p { margin: 0 0 8px; line-height: 125%; }
        """)
        guide.setHtml("""
            <h2>Build a graph</h2>
            <p>Drag a node from <b>Library</b> onto the canvas or double-click it in the list.
            You can also use <b>Search Nodes…</b> in the canvas right-click menu.</p>
            <p>Drag a wire from an output port to an input port. Hover over a port to see its
            full name. Select a node to edit its parameters and inspect its output in
            <b>Properties</b>. Use <b>Graft</b> or <b>Flatten</b> on supported inputs to
            regroup incoming data.</p>
            <p>Right-click the canvas and choose <b>Export Graph Image…</b> to save the entire
            graph as a PNG, including nodes outside the current view.</p>

            <h2>Keyboard and mouse</h2>
            <p>Zoom with the mouse wheel. Pan by dragging with the middle mouse button or
            by holding <b>Alt</b> and dragging with the left mouse button.
            Press <b>F</b> on the canvas or choose <b>Frame graph</b> from the menu
            to bring the entire graph into view.</p>
            <p><b>Ctrl+Z</b> undoes an edit. <b>Ctrl+Y</b> or <b>Ctrl+Shift+Z</b> redoes it.
            <b>Delete</b> removes selected nodes. <b>Ctrl+O</b> opens a graph and
            <b>Ctrl+S</b> saves it.</p>

            <h2>Work with Serpentine3D</h2>
            <p>Start Serpentine3D with NoodleSBridge and look for <b>Serpentine · Connected</b>
            above the canvas. Click the status to retry the connection.</p>
            <p>On supported nodes, <b>Generate</b> publishes one ParametricObject per node.
            In <b>Reference</b> mode, select the source geometry in Serpentine3D, then click
            <b>Set reference</b> or <b>Set reference points</b> in Properties.</p>
            <p>While the apps are connected, save the <b>.noodles</b> graph and its
            <b>.serp</b> model in either order. If you open the wrong graph, use
            <b>Choose Another Graph…</b> to find the matching one.</p>
        """)
        layout.addWidget(guide)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def show_about(self):
        QtWidgets.QMessageBox.about(self, "About NoodleS", (
            f"NoodleS {__version__}\n\n"
            "Visual scripting for parametric design with Serpentine3D.\n"
            "The graph editor interface is built on NodeGraphQt.\n\n"
            "Build graphs with DataTree, publish CAD geometry, and reference existing scene objects "
            "through NoodleSBridge.\n\n"
            "MIT License"
        ))

    def closeEvent(self, event):
        if self._confirm_discard():
            self._closing = True
            self._pending = False
            self._scene_requests.shutdown(wait=False)
            self.serpentine.stop()
            self.point_service.stop()
            self.preview_service.stop()
            if self._graph_worker:
                self._graph_worker.stop()
            event.accept()
        else:
            event.ignore()
