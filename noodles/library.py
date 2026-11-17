"""Library display categories stay independent of saved NodeGraphQt type IDs."""
from NodeGraphQt import NodesTreeWidget
from NodeGraphQt.constants import MIME_TYPE, URN_SCHEME
from NodeGraphQt.custom_widgets.nodes_tree import TYPE_CATEGORY
from Qt import QtCore, QtGui, QtWidgets
from .backend.operations import NATIVE_SCENE_SPECS, OPERATION_SPECS
from .backend.previews import PREVIEW_SPECS
from .backend.moves import MOVE_SPECS
from .backend.population import POPULATION_SPECS
from .backend.delaunay_node import TESSELLATION_SPECS
from .backend.surface_structure import SPECS as STRUCTURE_SPECS
from .node_descriptions import NODE_DESCRIPTIONS


class NodeLibrary(NodesTreeWidget):
    def _node_items(self):
        for index in range(self.topLevelItemCount()):
            category = self.topLevelItem(index)
            for child_index in range(category.childCount()):
                yield category.child(child_index)

    def node_entries(self):
        for item in self._node_items():
            yield item.text(0), item.data(0, QtCore.Qt.UserRole), item.toolTip(0)

    def mimeData(self, items):
        node_ids = [item.data(0, QtCore.Qt.UserRole) for item in items]
        payload = URN_SCHEME + ';'.join(f'node:{node_id}' for node_id in node_ids if node_id)
        mime_data = QtCore.QMimeData()
        mime_data.setData(MIME_TYPE, QtCore.QByteArray(payload.encode()))
        return mime_data

    def _build_tree(self):
        super()._build_tree()
        for item in tuple(self._node_items()):
            node_id = item.toolTip(0)
            if node_id == 'NoodleS.VisualHelpers.CadViewportNode':
                # Saved graphs still resolve the registered type.
                item.parent().removeChild(item)
                continue
            item.setData(0, QtCore.Qt.UserRole, node_id)
            item.setToolTip(0, NODE_DESCRIPTIONS.get(node_id.rsplit('.', 1)[-1], ''))
        self._group({**OPERATION_SPECS,**NATIVE_SCENE_SPECS,**MOVE_SPECS,**POPULATION_SPECS,
                     **TESSELLATION_SPECS, **STRUCTURE_SPECS},
                    'NoodleS.Operations','Operations','NoodleS.Geometry')
        self._group(PREVIEW_SPECS,'NoodleS.VisualHelpers','Visual Helpers','NoodleS.Operations')

    def _group(self,specs,identifier,label,after):
        operation_classes={spec['class'] for spec in specs.values()}
        members=[]
        for index in range(self.topLevelItemCount()):
            category=self.topLevelItem(index)
            for child_index in range(category.childCount()-1,-1,-1):
                item=category.child(child_index)
                if item.data(0, QtCore.Qt.UserRole).rsplit('.',1)[-1] in operation_classes:
                    members.append(category.takeChild(child_index))
        if not members:
            return
        category=self._category_items.get(identifier)
        if category is None:
            category=QtWidgets.QTreeWidgetItem([label],type=TYPE_CATEGORY)
            category.setFirstColumnSpanned(True)
            category.setFlags(QtCore.Qt.ItemIsEnabled)
            category.setSizeHint(0,QtCore.QSize(100,26))
            geometry=self._category_items.get(after)
            position=self.indexOfTopLevelItem(geometry)+1 if geometry is not None else self.topLevelItemCount()
            self.insertTopLevelItem(position,category)
            self._category_items[identifier]=category
        # Moving the original items preserves their type IDs and descriptions.
        for item in reversed(members):
            category.addChild(item)
        category.setExpanded(True)


class NodeSearchPopup(QtWidgets.QFrame):
    chosen = QtCore.Signal(str)

    def __init__(self, parent):
        super().__init__(parent, QtCore.Qt.Popup)
        self.setObjectName('NodeSearchPopup')
        self.setFixedSize(300, 264)
        self.entries = []
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.query = QtWidgets.QLineEdit()
        self.query.setObjectName('NodeSearchQuery')
        self.query.setPlaceholderText('Search nodes…')
        self.query.setAccessibleName('Search nodes')
        layout.addWidget(self.query)
        self.results = QtWidgets.QListWidget()
        self.results.setObjectName('NodeSearchResults')
        self.results.setAccessibleName('Matching nodes')
        self.results.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.results)
        self.query.textChanged.connect(self._filter)
        self.query.returnPressed.connect(lambda: self._choose(self.results.currentItem()))
        self.query.installEventFilter(self)
        self.results.itemClicked.connect(self._choose)
        self.results.itemActivated.connect(self._choose)
        self.dismiss = QtGui.QShortcut(QtGui.QKeySequence('Esc'), self)
        self.dismiss.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        self.dismiss.activated.connect(self.hide)

    def open_at(self, position, entries):
        self.entries = sorted(entries, key=lambda entry: entry[0].casefold())
        with QtCore.QSignalBlocker(self.query):
            self.query.clear()
        self._filter('')
        screen = QtGui.QGuiApplication.screenAt(position) or self.parentWidget().screen()
        bounds = screen.availableGeometry()
        self.move(max(bounds.left(), min(position.x(), bounds.right() - self.width() + 1)),
                  max(bounds.top(), min(position.y(), bounds.bottom() - self.height() + 1)))
        self.show()
        self.query.setFocus(QtCore.Qt.PopupFocusReason)

    def _filter(self, text):
        query = text.strip().casefold()
        matches = [entry for entry in self.entries if query in entry[0].casefold()]
        matches.sort(key=lambda entry: (entry[0].casefold() != query,
                                        not entry[0].casefold().startswith(query)))
        self.results.clear()
        for name, kind, description in matches:
            item = QtWidgets.QListWidgetItem(name, self.results)
            item.setData(QtCore.Qt.UserRole, kind)
            item.setToolTip(description)
        self.results.setCurrentRow(0)

    def _choose(self, item):
        if item is not None and self.isVisible():
            kind = item.data(QtCore.Qt.UserRole)
            self.hide()
            self.chosen.emit(kind)

    def eventFilter(self, watched, event):
        if watched is self.query and event.type() == QtCore.QEvent.KeyPress:
            step = {QtCore.Qt.Key_Up: -1, QtCore.Qt.Key_Down: 1}.get(event.key())
            if step is not None and self.results.count():
                self.results.setCurrentRow(max(0, min(self.results.currentRow() + step, self.results.count() - 1)))
                return True
        return super().eventFilter(watched, event)
