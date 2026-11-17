"""A compact Properties label with an on-demand, scrollable DataTree preview."""
from Qt import QtCore, QtGui, QtWidgets

class TreePreview(QtWidgets.QLabel):
    def __init__(self):
        super().__init__()
        self.setWordWrap(True)
        self.setTextFormat(QtCore.Qt.PlainText)
        policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._tree = None
        self._formatter = str
        self._popup = None
        self._hover = QtCore.QTimer(self)
        self._hover.setSingleShot(True)
        self._hover.setInterval(400)
        self._hover.timeout.connect(self._show_tree)
        self._leave = QtCore.QTimer(self)
        self._leave.setInterval(80)
        self._leave.timeout.connect(self._check_pointer)
        self._refresh = QtCore.QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(120)
        self._refresh.timeout.connect(self._fill_popup)

    def set_tree(self, tree, formatter=str):
        changed = tree != self._tree if self._popup and self._popup.isVisible() else False
        self._tree, self._formatter = tree, formatter
        if tree is None:
            self._dismiss()
        elif changed:
            self._refresh.start()

    def event(self, event):
        if event.type() == QtCore.QEvent.ToolTip and self._tree is not None:
            return True  # This label supplies its own, scrollable tooltip.
        return super().event(event)

    def enterEvent(self, event):
        if self._tree is not None and not (self._popup and self._popup.isVisible()):
            self._hover.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover.stop()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._dismiss()
        super().hideEvent(event)

    def _show_tree(self):
        if self._tree is None or not self.isVisible() or not self._contains_pointer():
            return
        if self._popup is None:
            self._popup = QtWidgets.QFrame(self, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
            self._popup.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
            self._popup.setObjectName("DataTreePopup")
            self._popup.setStyleSheet("""
                QFrame#DataTreePopup { background: #24282e; border: 1px solid #536071; }
                QPlainTextEdit { background: #1e2228; border: 0; color: #e3e7ed; padding: 6px; }
            """)
            layout = QtWidgets.QVBoxLayout(self._popup)
            layout.setContentsMargins(8, 8, 8, 8)
            self._heading = QtWidgets.QLabel()
            self._heading.setTextFormat(QtCore.Qt.PlainText)
            layout.addWidget(self._heading)
            self._contents = QtWidgets.QPlainTextEdit()
            self._contents.setAccessibleName("Full DataTree preview")
            self._contents.setReadOnly(True)
            self._contents.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
            self._contents.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
            layout.addWidget(self._contents)
        self._fill_popup(reset_scroll=True)
        area = self.screen().availableGeometry()
        width = min(460, area.width())
        height = min(320, area.height())
        anchor = self.mapToGlobal(self.rect().topLeft())
        x = min(max(anchor.x(), area.left()), area.right() - width + 1)
        below = anchor.y() + self.height()
        y = below if below + height <= area.bottom() + 1 else anchor.y() - height
        y = min(max(y, area.top()), area.bottom() - height + 1)
        QtWidgets.QToolTip.hideText()
        self._popup.setGeometry(x, y, width, height)
        self._popup.show()
        self._leave.start()

    def _fill_popup(self, reset_scroll=False):
        tree = self._tree
        if tree is None:
            return
        lines = []
        for branch in tree.branches:
            path = ";".join(map(str, branch.path))
            items = ", ".join(str(value).removesuffix(".0") if isinstance(value, float) else self._formatter(value)
                              for value in branch.items)
            lines.append(f"{{{path}}}: {items or '(empty)'}")
        self._heading.setText(f"{tree.count} item(s) · {len(tree.branches)} branch(es)")
        scrollbar = self._contents.verticalScrollBar()
        position = scrollbar.value()
        self._contents.setPlainText("\n".join(lines))
        scrollbar.setValue(0 if reset_scroll else position)

    def _contains_pointer(self):
        return self.rect().contains(self.mapFromGlobal(QtGui.QCursor.pos()))

    def _check_pointer(self):
        if (not self.isVisible() or not self._popup.isVisible()
                or not (self._contains_pointer() or self._popup.frameGeometry().contains(QtGui.QCursor.pos()))):
            self._dismiss()

    def _dismiss(self):
        self._hover.stop()
        self._leave.stop()
        self._refresh.stop()
        if self._popup is not None:
            self._popup.hide()
