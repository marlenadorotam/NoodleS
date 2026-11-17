"""Workbench chrome and a selection-based inspector, separate from the canvas."""
from pathlib import Path

from Qt import QtCore, QtGui, QtWidgets

from .widgets import NumberField, S3D_ACTIVE_COLOR, add_field, wrapping_label
from .point_properties import PointProperties
from .domain_properties import DomainProperties
from .range_properties import RangeProperties
from .arithmetic_properties import ArithmeticProperties
from .math_properties import MathProperties
from .curve_properties import CurveProperties
from .backend.geometry import GEOMETRY_SPECS
from .backend.math_nodes import MATH_SPECS
from .backend.operations import OPERATION_SPECS
from .backend.moves import MOVE_SPECS


def apply_theme(app):
    QtCore.QLocale.setDefault(QtCore.QLocale("en_US"))
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(QtCore.Qt.ColorScheme.Dark)
    app.setFont(QtGui.QFont("Segoe UI", 10))
    palette = QtGui.QPalette()
    colors = {
        QtGui.QPalette.Window: "#24282e", QtGui.QPalette.WindowText: "#e3e7ed",
        QtGui.QPalette.Base: "#1e2228", QtGui.QPalette.AlternateBase: "#282d34",
        QtGui.QPalette.Text: "#e3e7ed", QtGui.QPalette.Button: "#2d333b",
        QtGui.QPalette.ButtonText: "#e3e7ed", QtGui.QPalette.Highlight: "#35594e",
        QtGui.QPalette.HighlightedText: "#f2fff9", QtGui.QPalette.ToolTipBase: "#303740",
        QtGui.QPalette.ToolTipText: "#e3e7ed", QtGui.QPalette.PlaceholderText: "#89939f",
    }
    for role, color in colors.items():
        palette.setColor(role, QtGui.QColor(color))
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, QtGui.QColor("#77818c"))
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, QtGui.QColor("#77818c"))
    app.setPalette(palette)


LIBRARY_COLORS = "background: #24282e; color: #d7dee7;"
LIBRARY_SELECTION = "background: #35594e; color: #edfff7;"
COMBO_ARROW = Path(__file__).resolve().with_name("combo-arrow.svg").as_posix()
MENU_CHECK = Path(__file__).resolve().with_name("menu-check.svg").as_posix()
CANVAS_MENU_STYLE = """
QMenu { """ + LIBRARY_COLORS + """ border: 1px solid #3b444e; padding: 6px; }
QMenu::item { padding: 7px 28px 7px 12px; border-radius: 4px; }
QMenu::item:selected { """ + LIBRARY_SELECTION + """ }
QMenu::item:disabled { color: #77818c; }
QMenu::separator { height: 1px; background: #3b444e; margin: 5px 8px; }
"""
CAD_VIEW_MENU_STYLE = CANVAS_MENU_STYLE + """
QMenu::item { padding-left: 32px; }
QMenu::indicator { width: 14px; height: 14px; left: 10px; border: 1px solid #7e8b9b;
    border-radius: 3px; background: #1e2228; }
QMenu::indicator:disabled { border-color: #48525e; }
""" + f'QMenu::indicator:checked {{ image: url("{MENU_CHECK}"); }}'


STYLESHEET = """
QMainWindow#NoodleSWindow { background: #1b1e23; color: #e3e7ed; }
QMenu::item:selected { background: #353c45; color: #fff; }
QMenu { background: #282d34; color: #e3e7ed; border: 1px solid #3b444e; padding: 6px; }
QMenu::item { padding: 7px 28px 7px 12px; border-radius: 4px; }
QMenu::separator { height: 1px; background: #3b444e; margin: 5px 8px; }
QToolBar#MainToolbar { background: #1b1e23; border: 0; border-bottom: 1px solid #343a43;
    spacing: 6px; padding: 9px 16px; }
QToolBar#MainToolbar QToolButton { color: #c7cfd9; background: transparent; border: 0;
    border-radius: 5px; padding: 7px 13px; }
QToolBar#MainToolbar QToolButton:hover { background: #303740; color: white; }
QToolBar#MainToolbar QToolButton:checked { background: #304b43; color: #c6ebdc; }
QToolBar#MainToolbar QToolButton#S3DPanelToggle:checked,
QToolBar#MainToolbar QToolButton#CadViewToggle:checked { background: """ + S3D_ACTIVE_COLOR + """; color: white; }
QToolBar#MainToolbar QToolButton#S3DPanelToggle:disabled,
QToolBar#MainToolbar QToolButton#CadViewToggle:disabled { color: #697581; }
QLabel#NodeError { background: #342c25; }
QToolBar#MainToolbar QToolButton#MenuButton { padding: 0; }
QToolButton#MenuButton::menu-indicator { image: none; width: 0; }
QLabel#Brand { color: #eef5f1; font-size: 19px; font-weight: 600; padding-right: 22px; }
QToolButton#Connection { color: #9da7b3; font-size: 11px; padding: 5px 12px;
    background: #282d34; border: 0; border-radius: 5px; }
QToolButton#Connection:hover { background: #303740; }
QToolButton#Connection[connected="true"] { color: #b4dfcd; background: #293d37; }
QFrame#WorkbenchPanel { background: #24282e; border: 0; }
QFrame#PanelHeading { background: #24282e; border: 0; border-bottom: 1px solid #353b44; }
QLabel#PanelTitle { color: #d9dfe7; font-size: 12px; font-weight: 600; }
QLabel#CanvasHint { color: #8e98a5; font-size: 11px; }
QSplitter#Workbench::handle { background: #353b44; }
QSplitter#Workbench::handle:hover { background: #75bda5; }
QWidget#LibraryBody, QWidget#InspectorContent, QWidget#InspectorEmpty,
QWidget#InspectorBody { background: #24282e; }
QLineEdit#LibrarySearch, QLineEdit#NodeSearchQuery, QWidget#InspectorContent QLineEdit,
QWidget#InspectorContent QDoubleSpinBox, QWidget#InspectorContent QPlainTextEdit {
    color: #e3e7ed; background: #1e2228; border: 1px solid #3b444e;
    border-radius: 5px; padding: 7px 9px; selection-background-color: #35594e;
}
QLineEdit#LibrarySearch:focus, QLineEdit#NodeSearchQuery:focus, QWidget#InspectorContent QLineEdit:focus,
QWidget#InspectorContent QDoubleSpinBox:focus { border-color: #8bcbb4; }
QWidget#InspectorContent QComboBox {
    background: #1e2228; border: 1px solid #3b444e; border-radius: 5px;
    /* Match the input's 9px padding plus its 2px text inset. */
    padding: 7px 0 7px 11px; min-height: 20px; combobox-popup: 0;
}
QWidget#InspectorContent QComboBox:focus { border-color: #8bcbb4; }
QWidget#InspectorContent QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: top right; width: 20px;
    background: #242930; border-left: 1px solid #303840;
    border-top-right-radius: 4px; border-bottom-right-radius: 4px;
}
QWidget#InspectorContent QComboBox::down-arrow {
    image: url('""" + COMBO_ARROW + """'); width: 9px; height: 6px;
}
QWidget#InspectorContent QComboBox QAbstractItemView::item {
    padding-top: 3px; padding-bottom: 3px; padding-left: 9px;
}
QWidget#InspectorContent QWidget#SliderMode { background: #1e2228; border: 1px solid #3b444e;
    border-radius: 6px; }
QWidget#InspectorContent QWidget#SliderMode QPushButton { background: transparent;
    border: 0; border-radius: 4px; padding: 7px 10px; color: #9da9b6; }
QWidget#InspectorContent QWidget#SliderMode QPushButton:checked { background: #34574c; color: #d5f1e5; }
QWidget#InspectorContent QDoubleSpinBox QLineEdit {
    padding: 0; border: 0; border-radius: 0; background: transparent;
}
QWidget#InspectorContent QPushButton { background: #303840; color: #d3dce5;
    border: 1px solid #424d58; border-radius: 5px; padding: 7px 10px; }
QWidget#InspectorContent QPushButton:hover { background: #394650; border-color: #739c8f; }
QWidget#InspectorContent QCheckBox { spacing: 8px; padding: 4px 0; }
QWidget#InspectorContent QCheckBox::indicator { width: 14px; height: 14px;
    border: 1px solid #596673; border-radius: 3px; background: #1e2228; }
QWidget#InspectorContent QCheckBox::indicator:checked { background: #8bcbb4;
    border: 3px solid #38594e; }
QTreeWidget#NodeLibrary, QFrame#NodeSearchPopup,
QListWidget#NodeSearchResults { """ + LIBRARY_COLORS + """ }
QFrame#NodeSearchPopup { border: 1px solid #3b444e; border-radius: 4px; }
QTreeWidget#NodeLibrary, QListWidget#NodeSearchResults { border: 0; outline: 0; }
QTreeWidget#NodeLibrary { padding: 4px 8px; }
QTreeWidget#NodeLibrary::item, QListWidget#NodeSearchResults::item {
    border: 0; padding: 3px 6px; border-radius: 4px; }
QTreeWidget#NodeLibrary::item:hover, QListWidget#NodeSearchResults::item:hover { background: #2e353e; }
QTreeWidget#NodeLibrary::item:selected, QListWidget#NodeSearchResults::item:selected {
    """ + LIBRARY_SELECTION + """ }
QTreeWidget#NodeLibrary::branch { background: transparent; }
QLabel#SecondaryText { color: #929dab; font-size: 12px; }
QLabel#ConnectedInputValue { color: #c6d6d0; background: transparent; border: 0; padding: 0; }
QLabel#SectionLabel { color: #99a5b4; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLabel#NodeTitle { color: #edf2f7; font-size: 20px; font-weight: 600; }
QLabel#OutputValue { color: #b4dfcd; padding: 14px;
    background: #1e2427; border: 1px solid #35463f; border-radius: 6px; }
QLabel#NodeError { color: #edc28f; padding: 12px;
    border: 1px solid #564436; border-radius: 6px; }
QScrollArea#InspectorScroll { border: 0; background: #24282e; }
QStatusBar { background: #1b1e23; color: #909ca9; border-top: 1px solid #353b44;
    padding: 3px 12px; font-size: 11px; }
QStatusBar::item { border: 0; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 0; }
/* Keep the 9px thumb and match the search popup's 8px outer inset. */
QListWidget#NodeSearchResults QScrollBar:vertical { width: 17px; margin-left: 8px; }
QScrollBar::handle:vertical { background: #46515e; min-height: 30px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { color: #e3e7ed; background: #303740; border: 1px solid #46515e; padding: 6px; }
"""


def label(text, name="SecondaryText"):
    widget = wrapping_label(text)
    widget.setObjectName(name)
    return widget


class WorkbenchPanel(QtWidgets.QFrame):
    def __init__(self, title, body, hint=None):
        super().__init__()
        self.setObjectName("WorkbenchPanel")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.heading = QtWidgets.QFrame()
        self.heading.setObjectName("PanelHeading")
        self.heading.setFixedHeight(42)
        row = QtWidgets.QHBoxLayout(self.heading)
        row.setContentsMargins(16, 0, 16, 0)
        self.title_label = label(title, "PanelTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        row.addWidget(self.title_label, 1)
        if hint:
            hint_label = label(hint, "CanvasHint")
            hint_label.setWordWrap(False)
            row.addWidget(hint_label)
        layout.addWidget(self.heading)
        layout.addWidget(body, 1)


class InspectorPanel(QtWidgets.QWidget):
    """Edit the selected node through its public API; all edits are undoable."""
    property_edited = QtCore.Signal(str, object)
    reference_requested = QtCore.Signal()
    boolean_requested = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("InspectorBody")
        self.node_id = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.stack)

        empty = QtWidgets.QWidget()
        empty.setObjectName("InspectorEmpty")
        empty_layout = QtWidgets.QVBoxLayout(empty)
        empty_layout.setContentsMargins(24, 38, 24, 24)
        empty_layout.setSpacing(14)
        empty_layout.addWidget(label("Select a node", "NodeTitle"))
        empty_layout.addWidget(label("Its parameters, state and output will appear here."))
        empty_layout.addStretch()
        self.stack.addWidget(empty)

        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("InspectorScroll")
        scroll.setWidgetResizable(True)
        self.content = QtWidgets.QWidget()
        self.content.setObjectName("InspectorContent")
        fields = QtWidgets.QVBoxLayout(self.content)
        fields.setContentsMargins(20, 24, 20, 24)
        fields.setSpacing(10)
        self.title = label("", "NodeTitle")
        self.kind = label("")
        fields.addWidget(self.title)
        fields.addWidget(self.kind)
        fields.addSpacing(18)
        fields.addWidget(label("NODE", "SectionLabel"))
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setMinimumHeight(36)
        self.name_edit.setAccessibleName("Node name")
        self.name_label = add_field(fields, "Name", self.name_edit)
        self.enabled = QtWidgets.QCheckBox("Enabled")
        fields.addWidget(self.enabled)
        fields.addSpacing(18)

        self.value_section = QtWidgets.QWidget()
        value_layout = QtWidgets.QVBoxLayout(self.value_section)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(10)
        value_layout.addWidget(label("PARAMETERS", "SectionLabel"))
        self.mode_switch = QtWidgets.QWidget()
        self.mode_switch.setObjectName("SliderMode")
        mode_layout = QtWidgets.QHBoxLayout(self.mode_switch)
        mode_layout.setContentsMargins(3, 3, 3, 3)
        mode_layout.setSpacing(3)
        self.double_button = QtWidgets.QPushButton("Double")
        self.integer_button = QtWidgets.QPushButton("Integer")
        self.mode_group = QtWidgets.QButtonGroup(self)
        for index, button in enumerate((self.double_button, self.integer_button)):
            button.setCheckable(True)
            self.mode_group.addButton(button, index)
            mode_layout.addWidget(button)
        self.double_button.setChecked(True)
        value_layout.addWidget(self.mode_switch)

        self.min_section = QtWidgets.QWidget()
        min_layout = QtWidgets.QVBoxLayout(self.min_section)
        min_layout.setContentsMargins(0, 0, 0, 0)
        min_layout.setSpacing(10)
        self.min_edit = NumberField()
        self.min_edit.setMinimumHeight(38)
        self.min_edit.setAccessibleName("Slider minimum")
        self.min_label = add_field(min_layout, "Min", self.min_edit)
        value_layout.addWidget(self.min_section)

        self.max_section = QtWidgets.QWidget()
        max_layout = QtWidgets.QVBoxLayout(self.max_section)
        max_layout.setContentsMargins(0, 0, 0, 0)
        max_layout.setSpacing(10)
        self.max_edit = NumberField()
        self.max_edit.setMinimumHeight(38)
        self.max_edit.setAccessibleName("Slider maximum")
        self.max_label = add_field(max_layout, "Max", self.max_edit)
        value_layout.addWidget(self.max_section)

        self.value_edit = NumberField()
        self.value_edit.setMinimumHeight(38)
        self.value_edit.setAccessibleName("Node value")
        self.value_label = add_field(value_layout, "Value", self.value_edit)
        fields.addWidget(self.value_section)

        self.point_properties = PointProperties()
        self.point_properties.edited.connect(self.property_edited.emit)
        self.point_properties.set_reference.connect(self.reference_requested.emit)
        self.point_properties.hide()
        fields.addWidget(self.point_properties)
        self.curve_properties = CurveProperties()
        self.curve_properties.edited.connect(self.property_edited.emit)
        self.curve_properties.set_reference.connect(self.reference_requested.emit)
        self.curve_properties.apply_boolean.connect(self.boolean_requested.emit)
        self.curve_properties.hide()
        fields.addWidget(self.curve_properties)

        self.domain_properties = DomainProperties()
        self.domain_properties.edited.connect(self.property_edited.emit)
        self.domain_properties.hide()
        fields.addWidget(self.domain_properties)

        self.range_properties = RangeProperties()
        self.range_properties.edited.connect(self.property_edited.emit)
        self.range_properties.hide()
        fields.addWidget(self.range_properties)

        self.arithmetic_properties = ArithmeticProperties()
        self.arithmetic_properties.edited.connect(self.property_edited.emit)
        self.arithmetic_properties.hide()
        fields.addWidget(self.arithmetic_properties)

        self.math_properties = MathProperties()
        self.math_properties.edited.connect(self.property_edited.emit)
        self.math_properties.hide()
        fields.addWidget(self.math_properties)

        self.text_edit = QtWidgets.QPlainTextEdit()
        self.text_edit.setPlaceholderText("Backdrop description")
        self.text_edit.setMaximumHeight(160)
        fields.addWidget(self.text_edit)
        self.color_button = QtWidgets.QPushButton("Node color…")
        self.color_button.setMinimumHeight(32)
        fields.addWidget(self.color_button)
        fields.addSpacing(18)
        fields.addWidget(label("OUTPUT", "SectionLabel"))
        self.output = label("", "OutputValue")
        self.output.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.output.setAccessibleName("Node output")
        fields.addWidget(self.output)
        self.error = label("", "NodeError")
        fields.addWidget(self.error)
        self.hint = label("")
        fields.addWidget(self.hint)
        fields.addStretch()
        scroll.setWidget(self.content)
        self.stack.addWidget(scroll)

        self.name_edit.editingFinished.connect(self._rename)
        self.enabled.toggled.connect(lambda value: self.property_edited.emit("disabled", not value))
        self.value_edit.valueChanged.connect(lambda value: self.property_edited.emit("value", value))
        self.min_edit.valueChanged.connect(lambda value: self.property_edited.emit("minimum", value))
        self.max_edit.valueChanged.connect(lambda value: self.property_edited.emit("maximum", value))
        self.mode_group.idClicked.connect(
            lambda index: self.property_edited.emit("mode", "integer" if index else "double")
        )
        self.text_edit.textChanged.connect(lambda: self.property_edited.emit("backdrop_text", self.text_edit.toPlainText()))
        self.color_button.clicked.connect(self._choose_color)
        self._color = (13, 18, 23, 255)

    def _rename(self):
        name = self.name_edit.text().strip()
        if name:
            self.property_edited.emit("name", name)

    def _choose_color(self):
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(*self._color), self, "Node color",
            options=QtWidgets.QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
        if color.isValid():
            self.property_edited.emit("color", color.getRgb())

    def clear_bin(self):
        self.show_node(None)

    def show_node(self, node, result=None, formatter=str, evaluation=None):
        self.node_id = node.id if node else None
        if node is None:
            self.point_properties.reset_status()
            self.curve_properties.reset_status()
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        self.title.setText(node.name())
        operation = getattr(node, "OPERATION", "backdrop")
        descriptions = {
            "number": "Inputs / Number", "slider": "Inputs / Slider",
            "addition": "Math / Addition", "multiplication": "Math / Multiplication",
            "point": "Geometry / Point", "watch": "Data / Watch",
            "domain": "Math / Domain",
            "range": "Math / Range",
            "backdrop": "Layout / Backdrop",
            "cad_viewport": "Visual Helpers / CadViewport",
        }
        self.kind.setText(descriptions.get(operation, operation))
        if operation in MATH_SPECS:
            self.kind.setText("Math / " + MATH_SPECS[operation]["name"])
        if operation in GEOMETRY_SPECS:
            spec = GEOMETRY_SPECS[operation]
            category = spec.get('category') or ('Visual Helpers' if spec.get('preview') else
                'Operations' if operation in OPERATION_SPECS or operation in MOVE_SPECS else 'Geometry')
            self.kind.setText(category+' / '+spec['name'])
        widgets = (self.name_edit, self.enabled, self.value_edit, self.text_edit,
                   self.min_edit, self.max_edit, self.double_button, self.integer_button)
        blockers = [QtCore.QSignalBlocker(widget) for widget in widgets]
        if not self.name_edit.hasFocus():
            self.name_edit.setText(node.name())
        self.enabled.setChecked(not node.disabled())
        self.enabled.setVisible(operation != 'cad_viewport')
        self.value_section.setVisible(operation in ("number", "slider"))
        self.point_properties.setVisible(operation == "point")
        self.curve_properties.setVisible(operation in GEOMETRY_SPECS)
        if operation in GEOMETRY_SPECS:
            self.curve_properties.show_node(node, evaluation, formatter)
        else:
            self.curve_properties.reset_status()
        self.domain_properties.setVisible(operation == "domain")
        if operation == "domain":
            self.domain_properties.show_node(node, evaluation)
        self.range_properties.setVisible(operation == "range")
        self.arithmetic_properties.setVisible(operation in ("addition", "multiplication"))
        self.math_properties.setVisible(operation in MATH_SPECS)
        if operation in MATH_SPECS:
            self.math_properties.show_node(node, evaluation, formatter)
        if operation in ("addition", "multiplication"):
            self.arithmetic_properties.show_node(node, evaluation, formatter)
        if operation == "range":
            self.range_properties.show_node(node, evaluation)
        if operation == "point":
            self.point_properties.show_node(node, evaluation)
        else:
            self.point_properties.reset_status()
        self.mode_switch.setVisible(operation in ("number", "slider"))
        for section in (self.min_section, self.max_section):
            section.setVisible(operation == "slider")
        if operation == "slider":
            label_width = self.name_label.sizeHint().width()
            for field_label in (self.min_label, self.max_label, self.value_label):
                field_label.setFixedWidth(label_width)
            state = node.slider_state()
            decimals = 0 if state["mode"] == "integer" else 2
            self.double_button.setChecked(state["mode"] == "double")
            self.integer_button.setChecked(state["mode"] == "integer")
            for editor, key in ((self.min_edit, "minimum"), (self.max_edit, "maximum")):
                editor.setDecimals(decimals)
                editor.setValue(state[key])
            self.value_edit.setRange(state["minimum"], state["maximum"])
            self.value_edit.setDecimals(decimals)
            self.value_edit.setValue(state["value"])
        elif operation == "number":
            self.value_label.setMaximumWidth(self.name_label.maximumWidth())
            self.value_label.setMinimumWidth(0)
            state = node.number_state()
            self.double_button.setChecked(state["mode"] == "double")
            self.integer_button.setChecked(state["mode"] == "integer")
            self.value_edit.setRange(-1e9, 1e9)
            self.value_edit.setDecimals(0 if state["mode"] == "integer" else 4)
            self.value_edit.setValue(state["value"])
        self.text_edit.setVisible(operation == "backdrop")
        if operation == "backdrop" and not self.text_edit.hasFocus():
            self.text_edit.setPlainText(node.get_property("backdrop_text"))
        del blockers
        self._color = node.get_property("color")
        self.error.setVisible(bool(result and result.error))
        self.output.setVisible(bool(result and not result.error))
        if result and result.error:
            self.error.setText(result.error)
        elif result:
            if operation in ('deconstruct_brep', 'braced_grid_1d', 'mesh_edges', 'deconstruct_mesh', 'face_neighbours',
                             'deconstruct_face', 'face_normals') and '_sampling' not in result.outputs:
                from .port_names import full_port_name
                self.output.setText('\n'.join(f'{full_port_name(operation, port, False)} · {tree.count}'
                                              for port, tree in result.outputs.items()))
            elif operation == 'array_along_curve' and '_sampling' not in result.outputs:
                self.output.setText(f"Copies · {result.outputs['G'].count}\nTransforms · {result.outputs['X'].count}")
            elif operation == 'tree_viewer':
                lines = result.outputs['V'].splitlines()
                self.output.setText('\n'.join(lines[:6] + (['…'] if len(lines) > 6 else [])))
            elif operation == 'list_length':
                self.output.setText(formatter(result.outputs['L']) + '\nTotal · ' + str(result.outputs['T'])
                                    + '\nBranches · ' + str(result.outputs['B']))
            elif operation == 'sort_list':
                self.output.setText('Keys · ' + formatter(result.outputs['K']) + '\nValues · ' + formatter(result.outputs['A']))
            elif operation == 'sort_points':
                self.output.setText('Points · ' + formatter(result.outputs['P']) + '\nIndices · ' + formatter(result.outputs['I']))
            elif operation == 'read_csv':
                self.output.setText('Rows · ' + formatter(result.outputs['N']) + '\nHeaders · ' + formatter(result.outputs['H']))
            elif operation == 'pull_point':
                self.output.setText("P · " + formatter(result.outputs["P"]) + "\nD · " + formatter(result.outputs["D"]))
            elif operation == 'surface_evaluate':
                self.output.setText(formatter(result.outputs['P']) + '\nCount · ' + str(result.outputs['Count'])
                                    + '\nSkipped · ' + str(result.outputs['Skipped']))
            elif operation == 'brep_join':
                self.output.setText(formatter(result.outputs['B']) + '\nClosed · ' + formatter(result.outputs['C']))
            elif operation in ('dispatch', 'cross_reference'):
                self.output.setText('A · ' + formatter(result.outputs['A']) + '\nB · ' + formatter(result.outputs['B']))
            elif operation == 'point_in_curve':
                self.output.setText('Relationship · ' + formatter(result.outputs['R']) + '\nInside · ' + formatter(result.outputs['I']))
            elif operation in ('section', 'contour'):
                self.output.setText('Curves · ' + formatter(result.outputs['C']) + '\nRegions · ' + formatter(result.outputs['R']))
            elif operation == 'curve_curve':
                self.output.setText('Points · ' + formatter(result.outputs['P']) + '\nOverlaps · ' + formatter(result.outputs['C']))
            elif operation == 'region_boolean':
                self.output.setText('Regions · ' + formatter(result.outputs['R']) + '\nOutlines · ' + formatter(result.outputs['C']))
            elif operation == 'surface_isocurves':
                self.output.setText('Along U · ' + formatter(result.outputs['U']) + '\nAlong V · ' + formatter(result.outputs['V']))
            elif operation in ('area', 'volume'):
                port = GEOMETRY_SPECS[operation]['primary']
                self.output.setText(formatter(result.outputs[port]) + '\nCentroid · ' + formatter(result.outputs['C']))
            elif operation in GEOMETRY_SPECS and 'Count' in result.outputs:
                primary = GEOMETRY_SPECS[operation].get('primary', 'C')
                count = 'Count · ' + str(result.outputs['Count'])
                self.output.setText(count if primary == 'Count' else formatter(result.outputs[primary]) + '\n' + count)
            elif operation in ('domain', 'curve_domain'):
                self.output.setText("D · " + formatter(result.outputs["D"]) + "\nL · " + formatter(result.outputs["L"]))
            elif operation in ('surface_domain', 'deconstruct_domain2'):
                self.output.setText('U · ' + formatter(result.outputs['U']) + '\nV · ' + formatter(result.outputs['V']))
            elif operation == 'deconstruct_domain':
                self.output.setText('Start · ' + formatter(result.outputs['S']) + '\nEnd · ' + formatter(result.outputs['E']))
            elif operation == 'equality':
                self.output.setText('Equal · ' + formatter(result.outputs['=']) + '\nNot Equal · ' + formatter(result.outputs['≠']))
            elif operation == 'larger_than':
                self.output.setText('> · ' + formatter(result.outputs['>']) + '\n≥ · ' + formatter(result.outputs['≥']))
            elif operation in ("range", "graph_mapper"):
                self.output.setText(formatter(result.outputs["R"]) + "\nCount · " + str(result.outputs["Count"]))
            elif operation == "remap_numbers":
                self.output.setText("R · " + formatter(result.outputs["R"]) + "\nC · " + formatter(result.outputs["C"]))
            elif operation == "series":
                self.output.setText(formatter(result.outputs["S"]) + "\nCount · " + str(result.outputs["Count"]))
            elif operation == "vector":
                self.output.setText(formatter(result.outputs["Vector"]) + "\nLength · " + formatter(result.outputs["Length"]))
            elif operation == "vector_2pt":
                self.output.setText(formatter(result.outputs["V"]) + "\nLength · " + formatter(result.outputs["L"]))
            else:
                self.output.setText(formatter(next(iter(result.outputs.values()))))
        self.hint.setText({
            "vector": "Construct a Vector from X/Y/Z. Length is its magnitude; zero vectors are valid. Values are mathematical data.",
            "graph_mapper": "Values are clamped to Input Domain, mapped by the displayed curve, then scaled to Output Domain. Drag handles or edit precise parameters. Domains must have nonzero length.",
            "vector_2pt": "V points from A to B. Unitize changes V to unit length; L always gives the original distance. Coincident points give a zero vector.",
            "unit_vector": "Normalize V to length 1. Vectors of length 1e-15 or less are invalid.",
            "unit_x": "X-axis vector scaled by Factor; default 1. Negative factors reverse direction.",
            "unit_y": "Y-axis vector scaled by Factor; default 1. Negative factors reverse direction.",
            "unit_z": "Z-axis vector scaled by Factor; default 1. Negative factors reverse direction.",
            "amplitude": "Set vector length to A (default 1). Negative A reverses direction. A zero vector stays zero.",
            "reverse_vector": "Reverse vector direction while preserving length and tree structure.",
            "subtraction": "Number − Number or Vector − Vector, component by component. Both inputs must have compatible types.",
            "division": "A ÷ B. Division by zero clears the result and reports an error.",
            "minimum": "Element-wise minimum of A and B; this does not reduce a list to one value.",
            "sine": "sin(X), with X in radians.",
            "square": "X². Each input number is multiplied by itself.",
            "series": "Start + index × Step. Count is the number of values, not the number of segments.",
            "bounds": "One overall interval enclosing all input numbers. Equal numbers give a zero-length interval.",
            "remap_numbers": "R extrapolates from Source to Target Domain; C clips to Target. Both domains must have nonzero length.",
            "addition": "Number + Number, or coordinate addition for Point/Vector pairs. Both inputs are required.",
            "multiplication": "Numbers multiply; Number × Point/Vector scales coordinates; two Point/Vector values give a dot product. Both inputs are required.",
            "number": "Integer mode rounds values to the nearest whole number.",
            "slider": "Values outside Min–Max are clamped to the nearest bound.",
            "domain": "A and B keep their order; L is the absolute span. A and B must differ. Graft/Flatten changes input structure only.",
            "range": "N segments produce N+1 values, including both ends. Each matched Domain/Steps pair produces its own list; Flat combines the lists.",
            "point": "Generate: one ParametricObject. Reference: connect X/Y/Z to drive existing points; unconnected axes follow Serpentine. Graft/Flatten changes data structure only.",
            "backdrop": "A backdrop organizes the canvas and does not take part in calculations.",
            "cad_viewport": "Use the canvas button to change the display mode for the current Serpentine session.",
        }.get(operation, "Undo: Ctrl+Z. Redo: Ctrl+Shift+Z."))
        if operation in GEOMETRY_SPECS:
            self.hint.setText('Generate: one ParametricObject with deferred geometry. Reference: native objects remain editable in Serpentine. Graft/Flatten changes data structure only.')
            if operation == 'curves':
                self.hint.setText('Generate passes through connected curves. Reference uses the selection order in Serpentine.')
            if not GEOMETRY_SPECS[operation].get('reference',True):
                self.hint.setText('One ParametricObject for all grid geometry. Cells, points and edges remain DataTree values. Graft/Flatten changes input structure only.')
            if GEOMETRY_SPECS[operation].get('preview'):
                self.hint.setText('Viewport-only arrows, without CAD objects. Origin and Vector are independent. Length uses scene units. Graft/Flatten changes input structure only.')
            if operation in OPERATION_SPECS:
                self.hint.setText('Deferred geometry on the common OCC worker; one ParametricObject per node. K is the actual native geometry kind after publication. Reference source curves through their original nodes.')
            if operation == 'deconstruct_brep':
                self.hint.setText('Extracts exact native faces, edges and vertices as graph data.')
            if operation == 'deconstruct_mesh':
                self.hint.setText('Each face contains three zero-based indices into Vertices on the same branch. '
                                  'Vertex Colors is empty for Serpentine meshes.')
            if operation == 'deconstruct_face':
                self.hint.setText('Indices start at zero. For triangular faces, D repeats C.')
            if operation in ('curve_closest_point', 'evaluate_curve', 'construct_plane', 'surface_closest_point'):
                self.hint.setText('Returns graph data. Graft/Flatten changes input structure only.')
            if operation == 'cull_duplicate_points':
                self.hint.setText('Keeps points in input order within each branch. T is the distance tolerance. I gives zero-based indices.')
            if operation == 'closest_points':
                self.hint.setText('Finds up to N candidates per query, ordered by distance. I is zero-based within the candidate branch.')
            if operation == 'sort_along_curve':
                self.hint.setText('Sorts original points by native curve parameter. Use one guide curve per point branch.')
            if operation == 'orient':
                self.hint.setText('Copies geometry from Source Plane to Target Plane. The copies publish as one ParametricObject.')
            if operation == 'point_cylindrical':
                self.hint.setText('Angle is in radians. Elevation follows the base plane normal. Points publish as one ParametricObject.')
            if operation == 'construct_mesh':
                self.hint.setText('Use matching Vertices and Faces branches. Each face uses zero-based indices. '
                                  'Vertex colors are unavailable in Serpentine meshes.')
            if operation == 'uv_panels':
                self.hint.setText('Trimmed UV panels publish together as one ParametricObject.')
            elif operation == 'surface_box':
                self.hint.setText('Target box frames publish together as one ParametricObject.')
            elif operation == 'braced_grid_1d':
                self.hint.setText('Straight members follow the UV grid at their endpoints. The primary and brace lines publish as one ParametricObject.')
            elif operation == 'voronoi':
                self.hint.setText('One ParametricObject for all Voronoi contours. Periodic U requires a rectangular boundary.')
            elif operation == 'hexagon_tiling':
                self.hint.setText('C includes clipped cells. H and P contain complete hexagons and their centers. '
                                  'Periodic U fits the cell size to a rectangular boundary.')
