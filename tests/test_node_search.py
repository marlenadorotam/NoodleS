"""Canvas search via the actual context menu and Qt popup."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ['QT_PREFERRED_BINDING'] = 'PySide6'
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from Qt import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from noodles.graph_image import DPI, MARGIN_PIXELS, PIXELS_PER_SCENE_UNIT, render_graph_image
from noodles.window import MainWindow


class NodeSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.node_search.hide()
        self.window.graph.undo_stack().setClean()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_context_menu_first_item_opens_search_at_canvas_position(self):
        graph = self.window.graph
        menu = graph.get_context_menu('graph').qmenu
        self.assertEqual(menu.actions()[0].text(), 'Search Nodes…')
        self.assertEqual(menu.actions()[1].text(), 'Export Graph Image…')
        view = graph.viewer()
        pos = view.viewport().rect().center()
        QTest.mousePress(view.viewport(), QtCore.Qt.RightButton, pos=pos)
        QtCore.QTimer.singleShot(0, lambda: QTest.mouseClick(
            menu, QtCore.Qt.LeftButton, pos=menu.actionGeometry(menu.actions()[0]).center()))
        fallback = QtCore.QTimer(menu)
        fallback.setSingleShot(True)
        fallback.timeout.connect(menu.close)
        fallback.start(500)
        event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, pos, view.viewport().mapToGlobal(pos))
        self.app.sendEvent(view.viewport(), event)
        fallback.stop()
        QTest.mouseRelease(view.viewport(), QtCore.Qt.RightButton, pos=pos)
        self.app.processEvents()

        popup = self.window.node_search
        self.assertTrue(popup.isVisible())
        self.assertTrue(popup.query.hasFocus())
        QTest.keyClicks(popup.query, 'deLaunay')
        self.assertEqual([popup.results.item(i).text() for i in range(popup.results.count())],
                         ['Delaunay', 'Delaunay Mesh'])
        self.assertEqual(popup.results.currentItem().text(), 'Delaunay')
        QTest.keyClick(popup.query, QtCore.Qt.Key_Return)
        self.app.processEvents()
        self.assertFalse(popup.isVisible())
        node, = graph.selected_nodes()
        self.assertEqual(node.type_, 'NoodleS.Geometry.DelaunayNode')
        self.assertEqual(tuple(node.pos()), view.mapToScene(pos).toTuple())
        graph.undo_stack().undo()
        self.assertFalse(graph.all_nodes())

    def test_empty_search_cancel_and_click_result_with_library_hidden(self):
        self.window.library_button.setChecked(False)
        graph = self.window.graph
        command = graph.get_context_menu('graph').get_command('Search Nodes…')
        popup = self.window.node_search
        command.run_command()
        self.app.processEvents()
        QTest.keyClicks(popup.query, 'no matches here')
        QTest.keyClick(popup.query, QtCore.Qt.Key_Return)
        self.assertEqual(popup.results.count(), 0)
        self.assertTrue(popup.isVisible())
        QTest.keyClick(popup.query, QtCore.Qt.Key_Escape)
        self.assertFalse(popup.isVisible())
        self.assertFalse(graph.all_nodes())

        command.run_command()
        self.app.processEvents()
        self.assertEqual(popup.query.text(), '')
        QTest.keyClicks(popup.query, 'point')
        self.assertEqual(popup.results.currentItem().text(), 'Point')
        QTest.keyClick(popup.query, QtCore.Qt.Key_Down)
        self.assertEqual(popup.results.currentRow(), 1)
        QTest.keyClick(popup.query, QtCore.Qt.Key_Up)
        item = popup.results.currentItem()
        QTest.mouseClick(popup.results.viewport(), QtCore.Qt.LeftButton,
                         pos=popup.results.visualItemRect(item).center())
        self.assertFalse(popup.isVisible())
        node, = graph.all_nodes()
        self.assertEqual(node.type_, 'NoodleS.Geometry.PointNode')

    def test_export_command_saves_full_resolution_png_without_changing_the_view(self):
        graph = self.window.graph
        view = graph.viewer()
        number = self.window.add_node('NoodleS.Inputs.NumberNode')
        point = self.window.add_node('NoodleS.Geometry.PointNode')
        number.set_pos(-220, -80)
        point.set_pos(680, 90)
        number.outputs()['Number'].connect_to(point.inputs()['X'])
        view.setTransform(QtGui.QTransform.fromScale(1.6, 1.6))
        view.centerOn(point.view)
        self.app.processEvents()
        self.assertFalse(view.mapToScene(view.viewport().rect()).boundingRect().intersects(number.view.sceneBoundingRect()))
        first = render_graph_image(view)
        min_width = (point.x_pos() - number.x_pos()) * PIXELS_PER_SCENE_UNIT + 2 * MARGIN_PIXELS
        self.assertGreater(first.width(), min_width)

        view.setTransform(QtGui.QTransform.fromScale(.14, .14))
        view.centerOn(number.view)
        self.app.processEvents()
        self.assertTrue(number.view._proxy_mode)
        transform = view.viewportTransform()
        selected = graph.selected_nodes()
        undo_index = graph.undo_stack().index()
        action = graph.get_context_menu('graph').qmenu.actions()[1]
        with TemporaryDirectory(prefix="noodles-test-") as folder:
            filename = Path(folder) / 'graph'
            with patch.object(QtWidgets.QFileDialog, 'getSaveFileName', return_value=(str(filename), '')) as dialog:
                action.trigger()
                dialog.assert_called_once()
            exported = QtGui.QImage(str(filename.with_suffix('.png')))
            self.assertFalse(exported.isNull())
            self.assertEqual(exported, first)
            self.assertEqual(exported.dotsPerMeterX(), round(DPI / .0254))
            self.assertEqual(exported.dotsPerMeterY(), round(DPI / .0254))
        self.assertEqual(view.viewportTransform(), transform)
        self.assertTrue(number.view._proxy_mode)
        self.assertEqual(graph.selected_nodes(), selected)
        self.assertEqual(graph.undo_stack().index(), undo_index)
