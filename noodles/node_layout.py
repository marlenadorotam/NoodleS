"""Qt grid layouts for native NodeGraphQt components and connection targets."""
import math
from html import escape

from NodeGraphQt import BaseNode
from NodeGraphQt.constants import NodeEnum
from NodeGraphQt.qgraphics.node_base import NodeItem
from NodeGraphQt.qgraphics.node_text_item import NodeTextItem
from Qt import QtCore, QtGui, QtWidgets
from shiboken6 import delete

from .port_names import compact_port_name, full_port_name


class GraphicsCell(QtWidgets.QGraphicsLayoutItem):
    """Let a Qt layout place an existing item without changing its parent.

    Ports must remain direct children of NodeItem: NodeGraphQt uses that parent
    for connections, selection and context menus. Only this adapter translates
    Qt's solved cell geometry to the item's position.
    """

    def __init__(self, item=None, size=None, expand=False, ink_center=False, lift=0.0):
        super().__init__()
        self.item = item
        self.preferred = QtCore.QSizeF(size if size is not None else item.boundingRect().size())
        self.expand = expand
        self.ink_center = ink_center
        self.lift = lift
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding if expand else QtWidgets.QSizePolicy.Fixed,
                           QtWidgets.QSizePolicy.Fixed)

    def sizeHint(self, which, constraint=QtCore.QSizeF()):
        if which == QtCore.Qt.MaximumSize and self.expand:
            return QtCore.QSizeF(1_000_000, self.preferred.height())
        return self.preferred

    def setGeometry(self, rect):
        super().setGeometry(rect)
        if self.item is not None:
            center = self.item.boundingRect().center()
            if self.ink_center and self.item.toPlainText() and self.item.document().blockCount() == 1:
                # QTextDocument's line box includes font descent/leading even
                # for capital-only labels. Align visible glyphs, not that box.
                line = self.item.document().begin().layout().lineAt(0)
                outline = QtGui.QPainterPath()
                outline.addText(0, 0, self.item.font(), self.item.toPlainText())
                if not outline.isEmpty():
                    center.setY(line.position().y() + line.ascent() + outline.boundingRect().center().y())
            self.item.setPos(rect.center() - center - QtCore.QPointF(0, self.lift))


class CompactTitle(NodeTextItem):
    """Display an elided title while keeping native rename and undo."""

    def __init__(self, text, parent):
        self._editor_proxy = None
        super().__init__(text, parent)

    def set_editable(self, value=False):
        if not value or self._locked or self.is_editing:
            return
        # A single-line editor scrolls its text within the header while typing.
        editor = QtWidgets.QLineEdit(self.node.name)
        editor.setFont(self.font())
        editor.setStyleSheet("QLineEdit { color: #e3e7ed; background: #1e2228; border: 0; padding: 0; }")
        editor.installEventFilter(self)
        editor.editingFinished.connect(self._finish_edit)
        self._editor_proxy = QtWidgets.QGraphicsProxyWidget(self.node)
        self._editor_proxy.setWidget(editor)
        self._editor_proxy.setZValue(self.zValue() + 1)
        self._editor_proxy.setGeometry(self.node.title_rect())
        # NodeGraphQt also tries to focus the display title on double-click.
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsFocusable, False)
        self._editor_proxy.setFocus()
        editor.setFocus()
        editor.selectAll()
        self.update()

    @property
    def is_editing(self):
        return self._editor_proxy is not None

    def keyPressEvent(self, event):
        # The display item must never replace its elided text or commit it.
        QtWidgets.QGraphicsTextItem.keyPressEvent(self, event)

    def focusOutEvent(self, event):
        QtWidgets.QGraphicsTextItem.focusOutEvent(self, event)

    def _finish_edit(self, accept=True):
        proxy = self._editor_proxy
        if proxy is None:
            return
        name = proxy.widget().text().strip()
        self._editor_proxy = None
        proxy.hide()
        proxy.deleteLater()
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsFocusable, not self._locked)
        if accept and name:
            self.set_node_name(name)
        self.update()

    def eventFilter(self, watched, event):
        if (self.is_editing and watched is self._editor_proxy.widget()
                and event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape):
            self._finish_edit(False)
            return True
        return super().eventFilter(watched, event)

    def paint(self, painter, option, widget=None):
        if not self.is_editing:
            super().paint(painter, option, widget)

    def show_title(self, rect):
        name = self.node.name
        self.setToolTip(f'<b>{escape(name)}</b><br>Double-click to edit node name.')
        if self.is_editing:
            self._editor_proxy.setGeometry(rect)
        display = QtGui.QFontMetricsF(self.font()).elidedText(name, QtCore.Qt.ElideRight, rect.width())
        if display != self.toPlainText():
            self.setPlainText(display)


class CompactNodeItem(NodeItem):
    UNIT = 4.0
    ROW_HEIGHT = 24.0
    HEADER_HEIGHT = 24.0
    PORT_TEXT_GAP = 12.0
    CONTENT_GAP = 26.0
    EDGE_PADDING = 10.0
    CELL_PADDING = 4.0
    PORT_OPTICAL_LIFT = 0.5
    MIN_WIDTH = 64.0

    def __init__(self, name='node', parent=None):
        super().__init__(name, parent)
        original = self._text_item
        self._text_item = CompactTitle(name, self)
        self._text_item.setFont(original.font())
        original.setParentItem(None)
        original.deleteLater()

    def _port_tooltip(self, port, label=None):
        is_input = port in self._input_items
        description = full_port_name(getattr(self, '_noodles_operation', None), port.name, is_input)
        port.setToolTip(description)
        if label is not None:
            label.setToolTip(description)

    def sceneEventFilter(self, watched, event):
        if (watched in self._input_items or watched in self._output_items) and event.type() in (
                QtCore.QEvent.GraphicsSceneHoverEnter, QtCore.QEvent.GraphicsSceneHoverMove):
            # NodeGraphQt rewrites tooltips when ports are locked or reconfigured.
            # Restore our full label on actual hover without patching the library.
            self._port_tooltip(watched)
        return super().sceneEventFilter(watched, event)

    def _build_grid(self):
        # No graphics item is owned or reparented by these layouts. Retain the
        # Python adapters along with the root for the lifetime of the layout.
        cells = []

        def grid():
            layout = QtWidgets.QGraphicsGridLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            cells.append(layout)
            return layout

        def cell(item=None, size=None, expand=False, ink_center=False, lift=0.0):
            adapter = GraphicsCell(item, size, expand, ink_center, lift)
            cells.append(adapter)
            return adapter

        title = self._text_item
        title.document().setDocumentMargin(0)
        font_metrics = QtGui.QFontMetricsF(title.font())
        icon_size = self._icon_item.boundingRect().size()
        icon_width = icon_size.width() + self.UNIT
        header_height = max(self.HEADER_HEIGHT, self._snap(max(font_metrics.height(), icon_size.height()) + self.UNIT))
        root = grid()
        # The header fits the body. Even the original component title elides
        # when the ports and widgets need less width than the title.
        # Reserve three wide letters and an ellipsis for every component,
        # without sizing any node from its actual name.
        title_minimum = math.ceil(font_metrics.horizontalAdvance("WWW…")) + 1
        root.setMinimumWidth(max(self.MIN_WIDTH, title_minimum + 2 * icon_width + 4))
        # Only header and content rows. Padding belongs inside the content
        # cells; no footer row may shift their vertical alignment or add height.
        root.setRowFixedHeight(0, header_height)
        root.setRowStretchFactor(1, 1)

        header = grid()
        # The painted strip runs from y=3 to header_height+1. Give its
        # contents the same center; do not inherit the optical port lift.
        header.setContentsMargins(2, self.UNIT, 2, 0)
        header.setRowFixedHeight(0, header_height - self.UNIT)
        header.setColumnFixedWidth(0, icon_width)
        header.setColumnFixedWidth(2, icon_width)
        header.addItem(cell(self._icon_item), 0, 0, alignment=QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        header.addItem(cell(title, QtCore.QSizeF(0, font_metrics.height()), expand=True, ink_center=True),
                       0, 1, alignment=QtCore.Qt.AlignCenter)
        root.addItem(header, 0, 0, 1, 3)

        port_groups = []
        for side, items in enumerate((self._input_items, self._output_items)):
            ports = [p for p in items if p.isVisible()]
            port_groups.append(bool(ports))
            if not ports:
                continue
            group = grid()
            group.setContentsMargins(0, self.CELL_PADDING, 0, self.CELL_PADDING)
            group.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            anchor_column, label_column = (0, 1) if side == 0 else (1, 0)
            group.setColumnFixedWidth(anchor_column, 0)
            group.setHorizontalSpacing(self.PORT_TEXT_GAP)
            for row, port in enumerate(ports):
                label = items[port]
                display = compact_port_name(getattr(self, '_noodles_operation', None), port.name, side == 0)
                if label.toPlainText() != display:
                    label.setPlainText(display)
                label.document().setDocumentMargin(0)
                group.setRowFixedHeight(row, max(self.ROW_HEIGHT, self._snap(label.boundingRect().height())))
                # Zero-width anchors keep native port centers on the edges,
                # with the original hit areas extending on either side.
                group.addItem(cell(port, QtCore.QSizeF(0, port.boundingRect().height()),
                                   lift=self.PORT_OPTICAL_LIFT), row, anchor_column,
                              alignment=QtCore.Qt.AlignVCenter)
                if port.display_name:
                    group.addItem(cell(label, ink_center=True, lift=self.PORT_OPTICAL_LIFT), row, label_column,
                                  alignment=QtCore.Qt.AlignVCenter | (QtCore.Qt.AlignLeft if side == 0 else QtCore.Qt.AlignRight))
            root.addItem(group, 1, side * 2, alignment=QtCore.Qt.AlignVCenter)

        widgets = [w for w in self._widgets.values() if w.isVisible() or self._proxy_mode]
        if widgets:
            editors = grid()
            editors.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
            editors.setMaximumHeight(1_000_000)
            for row, widget in enumerate(widgets):
                editors.addItem(cell(widget), row, 0, alignment=QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
            root.addItem(editors, 1, 1, alignment=QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter)
            for side, has_ports in enumerate(port_groups):
                if has_ports:
                    root.setColumnSpacing(side, self.CONTENT_GAP)
                else:
                    root.setColumnFixedWidth(side * 2, self.EDGE_PADDING)
        else:
            root.addItem(cell(size=QtCore.QSizeF(self.CONTENT_GAP, 0), expand=True), 1, 1)
        root.setColumnStretchFactor(1, 1)
        root.invalidate()
        return root, cells, header_height

    @classmethod
    def _snap(cls, value):
        return math.ceil(value / cls.UNIT) * cls.UNIT

    def _calc_size_horizontal(self):
        layout, cells, _ = self._build_grid()
        try:
            size = layout.effectiveSizeHint(QtCore.Qt.PreferredSize)
            return size.width(), size.height()
        finally:
            delete(layout)

    def _draw_node_horizontal(self):
        if getattr(self, "_laying_out", False):
            return
        self._laying_out = True
        try:
            self._apply_grid()
        finally:
            self._laying_out = False

    def _apply_grid(self):
        for items in (self._input_items, self._output_items):
            for port, label in items.items():
                self._port_tooltip(port, label)
                if self.scene() is not None and port.scene() is self.scene():
                    port.installSceneEventFilter(self)
                label.setVisible(port.isVisible() and port.display_name and not self._proxy_mode)
        self._set_text_color(self.text_color)
        self._tooltip_disable(self.disabled)
        layout, cells, header_height = self._build_grid()
        try:
            size = layout.effectiveSizeHint(QtCore.Qt.PreferredSize)
            self.prepareGeometryChange()
            self._width, self._height = size.width(), size.height()
            self._header_height = header_height
            self._editor_sizes = {name: widget.boundingRect().size() for name, widget in self._widgets.items()}
            self._text_item.show_title(self.title_rect())
            layout.setGeometry(self.boundingRect())
        finally:
            # The grid has positioned the items. Destroy its temporary Qt
            # style widgets while the Python cell adapters are still alive.
            delete(layout)
        self._proxy_mode_threshold = min(70.0, self._width * 70.0 / 160.0)
        self.update()

    def title_rect(self):
        inset = self._icon_item.boundingRect().width() + self.UNIT + 2
        return QtCore.QRectF(inset, 3, max(0, self._width - 2 * inset), self._header_height - 2)

    def add_widget(self, widget):
        super().add_widget(widget)
        widget.widget().setTitleAlign("left")
        widget.geometryChanged.connect(self._editor_resized)

    def _editor_resized(self):
        if getattr(self, "_laying_out", False):
            return
        previous = getattr(self, "_editor_sizes", {})
        if any(previous.get(name) != widget.boundingRect().size() for name, widget in self._widgets.items()):
            self.draw_node()

    def _paint_horizontal(self, painter, option, widget):
        # Native colors/selection, with a header following its grid row.
        painter.save()
        rect = self.boundingRect().adjusted(1, 1, -1, -1)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(*self.color))
        painter.drawRoundedRect(rect, 4, 4)
        if self.selected:
            painter.setBrush(QtGui.QColor(*NodeEnum.SELECTED_COLOR.value))
            painter.drawRoundedRect(rect, 4, 4)
        painter.setBrush(QtGui.QColor(*NodeEnum.SELECTED_COLOR.value) if self.selected
                         else QtGui.QColor(0, 0, 0, 80))
        # The visible body runs from header+1 to height-1 (the inner outline),
        # symmetrically inset from the grid's content row. Its center therefore
        # defines the geometric center before the shared optical port lift.
        painter.drawRoundedRect(QtCore.QRectF(3, 3, self._width - 6,
                                             getattr(self, "_header_height", self.HEADER_HEIGHT) - 2), 3, 3)
        color = NodeEnum.SELECTED_BORDER_COLOR.value if self.selected else self.border_color
        pen = QtGui.QPen(QtGui.QColor(*color), 1.2 if self.selected else 0.8)
        pen.setCosmetic(self.viewer().get_zoom() < 0.0)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(rect, 4, 4)
        painter.restore()

    def auto_switch_mode(self):
        if not getattr(self.viewer(), 'exporting_graph_image', False):
            super().auto_switch_mode()

    @NodeItem.name.setter
    def name(self, value):
        if value == self.name:
            return
        NodeItem.name.fset(self, value)
        if self.scene():
            self.draw_node()


class CompactNode(BaseNode):
    """Shared grid presentation for all NoodleS components."""

    def __init__(self):
        super().__init__(qgraphics_item=CompactNodeItem)
        self.view._noodles_operation = getattr(self, 'OPERATION', None)
