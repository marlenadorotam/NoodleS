"""Select the compact title-bar art independently of the monitor scale."""

from Qt import QtCore, QtGui


class WindowIconEngine(QtGui.QIconEngine):
    def __init__(self, title_icon, taskbar_icon):
        super().__init__()
        self.title_icon = title_icon
        self.taskbar_icon = taskbar_icon

    def clone(self):
        return WindowIconEngine(self.title_icon, self.taskbar_icon)

    def _icon_for_size(self, size):
        # Qt requests the small Windows icon at 16 device-independent pixels.
        if max(size.width(), size.height()) <= 16:
            return self.title_icon
        return self.taskbar_icon

    def paint(self, painter, rect, mode, state):
        self._icon_for_size(rect.size()).paint(
            painter, rect, QtCore.Qt.AlignmentFlag.AlignCenter, mode, state
        )

    def pixmap(self, size, mode, state):
        return self.scaledPixmap(size, mode, state, 1.0)

    def scaledPixmap(self, size, mode, state, scale):
        return self._icon_for_size(size).pixmap(size, scale, mode, state)
