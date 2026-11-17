"""Full slot names reached through actual Qt hover/help events."""
import unittest
import test_curves as fixture
from Qt import QtCore, QtGui, QtWidgets
from noodles.nodes import NODE_CLASSES
from noodles.port_names import full_port_name


class PortTooltipTests(unittest.TestCase):
    setUpClass = classmethod(fixture.CurveWindowTests.setUpClass.__func__)
    setUp = fixture.CurveWindowTests.setUp
    tearDown = fixture.CurveWindowTests.tearDown
    settle = fixture.CurveWindowTests.settle

    def test_every_registered_port_has_a_full_name(self):
        for cls in NODE_CLASSES:
            node = self.window.graph.create_node(cls.type_)
            node.view.draw_node()
            for direction, ports in ((True, node.input_ports()), (False, node.output_ports())):
                for port in ports:
                    expected = full_port_name(cls.OPERATION, port.name(), direction)
                    self.assertEqual(port.view.toolTip(), expected)
                    if len(port.name()) <= 2:
                        self.assertGreater(len(expected), len(port.name()), (cls.NODE_NAME, port.name()))

    def test_circle_normal_full_tooltip_after_real_hover_and_port_lock_change(self):
        node = self.window.add_node('NoodleS.Geometry.CircleNode')
        self.settle()
        self.window.graph.fit_to_selection()
        self.settle()
        port = node.outputs()['N']
        port.set_locked(True)
        viewer = self.window.graph.viewer()
        viewport = viewer.viewport()
        position = viewer.mapFromScene(port.view.mapToScene(port.view.boundingRect().center()))
        # Send the moves to this viewport. Earlier offscreen windows may
        # have left the platform cursor or an open tooltip over that point.
        for point in (QtCore.QPoint(4, 4), position):
            move = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, QtCore.QPointF(point),
                                     QtCore.QPointF(viewport.mapToGlobal(point)),
                                     QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier)
            QtWidgets.QApplication.sendEvent(viewport, move)
        self.assertTrue(port.view.hovered)
        self.assertEqual(port.view.toolTip(), 'Normal')
        # Deliver the same help event Qt generates after the hover delay.
        event = QtWidgets.QGraphicsSceneHelpEvent(QtCore.QEvent.GraphicsSceneHelp)
        event.setScenePos(port.view.mapToScene(port.view.boundingRect().center()))
        event.setScreenPos(viewer.viewport().mapToGlobal(position))
        QtWidgets.QApplication.sendEvent(viewer.scene(), event)
        self.app.processEvents()
        self.assertEqual(QtWidgets.QToolTip.text(), 'Normal')
        QtWidgets.QToolTip.hideText()
