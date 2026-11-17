"""Layout checks with real Qt text, widgets, ports and saved graphs."""
import os
from pathlib import Path
import unittest

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from noodles.nodes import NODE_CLASSES
from noodles.window import MainWindow


class NodeLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        if windows := os.environ.get("WINDIR"):
            for name in ("segoeui.ttf", "segoeuib.ttf", "arial.ttf", "arialbd.ttf"):
                QtGui.QFontDatabase.addApplicationFont(str(Path(windows) / "Fonts" / name))

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.graph.undo_stack().setClean()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def add(self, cls):
        node = self.window.add_node(f"{cls.__identifier__}.{cls.__name__}")
        self.app.processEvents()
        return node

    def check_contents(self, node):
        view = node.view
        title = view.text_item.mapRectToParent(view.text_item.boundingRect())
        icon = view.icon_item.mapRectToParent(view.icon_item.boundingRect())
        self.assertGreaterEqual(title.left(), icon.right())
        self.assertLessEqual(title.right(), view.boundingRect().right())
        inputs = [t.mapRectToParent(t.boundingRect()) for p, t in view._input_items.items()
                  if p.isVisible() and p.display_name]
        outputs = [t.mapRectToParent(t.boundingRect()) for p, t in view._output_items.items()
                   if p.isVisible() and p.display_name]
        for left in inputs:
            for right in outputs:
                self.assertGreaterEqual(right.left() - left.right(), 26)
        for widget in view.widgets.values():
            rect = widget.mapRectToParent(widget.boundingRect())
            self.assertGreaterEqual(rect.left(), 0)
            self.assertLessEqual(rect.right(), view.width)
            for label in inputs:
                self.assertGreaterEqual(rect.left() - label.right(), 26)
            for label in outputs:
                self.assertGreaterEqual(label.left() - rect.right(), 26)

    def test_all_component_contents_fit(self):
        for cls in NODE_CLASSES:
            with self.subTest(node=cls.NODE_NAME):
                self.check_contents(self.add(cls))

    def test_point_is_compact_without_smaller_connection_targets(self):
        point = self.add(next(c for c in NODE_CLASSES if c.OPERATION == "point"))
        self.assertLess(point.view.width, 100)
        for port in point.view.inputs + point.view.outputs:
            self.assertEqual(port.boundingRect().height(), 22)
        self.check_contents(point)

    def test_title_elides_without_resizing_and_keeps_the_full_name_during_native_rename(self):
        point = self.add(next(c for c in NODE_CLASSES if c.OPERATION == "point"))
        width = point.view.width
        name = "A deliberately long name for a referenced point"
        point.set_name(name)
        self.assertEqual(point.view.width, width)
        title = point.view.text_item
        self.assertTrue(title.toPlainText().endswith("…"))
        self.assertIn(name, title.toolTip())
        self.assertIn("Double-click to edit node name", title.toolTip())
        self.check_contents(point)
        self.window.show()
        self.window.graph.center_on([point])
        self.app.processEvents()
        viewer = self.window.graph.viewer()
        click = viewer.mapFromScene(title.mapToScene(title.boundingRect().center()))
        QTest.mouseDClick(viewer.viewport(), QtCore.Qt.LeftButton, pos=click)
        self.assertTrue(title.is_editing)
        proxy = title._editor_proxy
        self.assertEqual(proxy.widget().text(), name)
        self.assertTrue(point.view.title_rect().contains(proxy.geometry()))
        QTest.keyClicks(viewer.viewport(), "This edit will be cancelled")
        QTest.keyClick(viewer.viewport(), QtCore.Qt.Key_Escape)
        self.assertFalse(title.is_editing)
        self.assertFalse(proxy.isVisible())
        self.assertEqual(point.name(), name)
        self.assertTrue(title.toPlainText().endswith("…"))
        QTest.mouseDClick(viewer.viewport(), QtCore.Qt.LeftButton, pos=click)
        self.assertTrue(title.is_editing)
        proxy = title._editor_proxy
        QTest.keyClick(viewer.viewport(), QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QTest.keyClicks(viewer.viewport(), "Another deliberately long Point title")
        self.assertTrue(point.view.title_rect().contains(proxy.geometry()))
        QTest.keyClick(viewer.viewport(), QtCore.Qt.Key_Return)
        self.assertFalse(title.is_editing)
        self.assertFalse(proxy.isVisible())
        self.assertEqual(point.name(), "Another deliberately long Point title")
        self.assertEqual(point.view.width, width)
        self.window.graph.undo_stack().undo()
        self.assertEqual(point.name(), name)
        session = self.window.graph.serialize_session()
        self.window.graph.deserialize_session(session, clear_session=True)
        restored = self.window.graph.all_nodes()[0]
        self.assertEqual(restored.name(), name)
        self.assertEqual(restored.view.width, width)
        self.check_contents(restored)

    def test_compact_titles_keep_at_least_three_letters_when_elided(self):
        for cls in NODE_CLASSES:
            with self.subTest(node=cls.NODE_NAME):
                node = self.add(cls)
                width = node.view.width
                node.set_name("WWWWWWWWWWWWWWWWWWWWWWWW")
                displayed = node.view.text_item.toPlainText()
                self.assertTrue(displayed.startswith("WWW"))
                self.assertTrue(displayed.endswith("…"))
                self.assertEqual(node.view.width, width)

    def test_vector_draws_compact_ports_and_serializes_the_original_connections(self):
        vector = self.add(next(c for c in NODE_CLASSES if c.OPERATION == "vector"))
        watch = self.window.add_node("NoodleS.Data.WatchNode")
        vector.outputs()["Vector"].connect_to(watch.inputs()["Value"])
        outputs = vector.view._output_items
        self.assertEqual({p.name: label.toPlainText() for p, label in outputs.items()},
                         {"Vector": "V", "Length": "L"})
        self.assertEqual({p.name: p.toolTip() for p in outputs},
                         {"Vector": "Vector", "Length": "Length"})
        session = self.window.graph.serialize_session()
        self.assertIn({"out": [vector.id, "Vector"], "in": [watch.id, "Value"]}, session["connections"])

    def test_grid_default_title_fits_body_instead_of_setting_its_width(self):
        grid = self.add(next(c for c in NODE_CLASSES if c.OPERATION == "grid_rectangle"))
        title = grid.view.text_item
        self.assertTrue(title.toPlainText().endswith("…"))
        self.assertIn("Grid Rectangle", title.toolTip())
        grid.view.name = grid.name()
        self.assertTrue(title.toPlainText().endswith("…"))
        width = grid.view.width
        grid.set_name("G")
        self.assertEqual(title.toPlainText(), "G")
        self.assertEqual(grid.view.width, width)
        self.check_contents(grid)
        self.window.graph.undo_stack().undo()
        self.assertEqual(grid.view.width, width)
        self.assertTrue(title.toPlainText().endswith("…"))

    def test_editor_to_output_spacing_is_consistent(self):
        gaps = []
        for operation in ("number", "slider"):
            node = self.add(next(c for c in NODE_CLASSES if c.OPERATION == operation))
            widget = node.get_widget("value")
            label = next(iter(node.view._output_items.values()))
            gaps.append(label.x() - (widget.x() + widget.boundingRect().width()))
        self.assertAlmostEqual(gaps[0], gaps[1])
        self.assertGreaterEqual(gaps[0], 26)

    def test_point_labels_remain_visible_at_working_zoom(self):
        point = self.add(next(c for c in NODE_CLASSES if c.OPERATION == "point"))
        self.window.show()
        self.app.processEvents()
        self.window.graph.set_zoom(-0.3)
        self.window.graph.center_on([point])
        self.window.grab()  # Exercise native zoom-dependent painting.
        self.assertTrue(point.view.text_item.isVisible())
        self.assertTrue(all(t.isVisible() for t in point.view._input_items.values()))

    def test_port_groups_center_on_complete_content_row_including_padding(self):
        for cls in NODE_CLASSES:
            with self.subTest(node=cls.NODE_NAME):
                node = self.add(cls)
                view = node.view
                body_top = view._header_height
                for items in (view._input_items, view._output_items):
                    ports = [p for p in items if p.isVisible()]
                    if not ports:
                        continue
                    top = min(p.y() for p in ports)
                    bottom = max(p.y() + p.boundingRect().height() for p in ports)
                    self.assertAlmostEqual((top + bottom) / 2,
                                           (body_top + view.height) / 2 - 0.5)
                    self.assertGreaterEqual(top, body_top)
                    self.assertLessEqual(bottom, view.height)
                    for port in ports:
                        label = items[port]
                        self.assertGreaterEqual(label.y(), body_top)

    def test_visible_label_pixels_center_on_port_circle(self):
        scale = 8
        for cls in NODE_CLASSES:
            view = self.add(cls).view
            for items in (view._input_items, view._output_items):
                for port, label in items.items():
                    with self.subTest(node=cls.NODE_NAME, port=port.name):
                        image = QtGui.QImage(int(view.width * scale), int(view.height * scale),
                                             QtGui.QImage.Format_ARGB32_Premultiplied)
                        image.fill(QtCore.Qt.transparent)
                        painter = QtGui.QPainter(image)
                        painter.scale(scale, scale)
                        painter.translate(label.pos())
                        label.paint(painter, QtWidgets.QStyleOptionGraphicsItem(), None)
                        painter.end()
                        pixels = QtGui.QRegion(QtGui.QBitmap.fromImage(image.createAlphaMask())).boundingRect()
                        ink_center = (pixels.top() + pixels.bottom() + 1) / (2 * scale)
                        port_center = port.mapToParent(port.boundingRect().center()).y()
                        self.assertAlmostEqual(ink_center, port_center, delta=0.4)

    def test_visible_titles_and_icons_center_on_painted_header(self):
        nodes = [self.add(cls) for cls in NODE_CLASSES]
        nodes.append(self.add(next(cls for cls in NODE_CLASSES if cls.OPERATION == "point")))
        scale = 8
        for node in nodes:
            with self.subTest(title=node.name()):
                view, title = node.view, node.view.text_item
                expected = 3 + (view._header_height - 2) / 2
                image = QtGui.QImage(int(view.width * scale), int(view.height * scale),
                                     QtGui.QImage.Format_ARGB32_Premultiplied)
                image.fill(QtCore.Qt.transparent)
                painter = QtGui.QPainter(image)
                painter.scale(scale, scale)
                painter.translate(title.pos())
                title.paint(painter, QtWidgets.QStyleOptionGraphicsItem(), None)
                painter.end()
                pixels = QtGui.QRegion(QtGui.QBitmap.fromImage(image.createAlphaMask())).boundingRect()
                ink_center = (pixels.top() + pixels.bottom() + 1) / (2 * scale)
                # Rasterized ellipsis combinations can differ by half a
                # logical pixel from the font's outline metrics.
                tolerance = 0.5 if title.toPlainText().endswith("…") else 0.4
                self.assertAlmostEqual(ink_center, expected, delta=tolerance)
                self.assertAlmostEqual(view.icon_item.mapToParent(view.icon_item.boundingRect().center()).y(), expected)

    def test_port_rows_have_shared_pitch_and_keep_native_parent_and_edges(self):
        for cls in NODE_CLASSES:
            with self.subTest(node=cls.NODE_NAME):
                view = self.add(cls).view
                for side, ports in enumerate((view.inputs, view.outputs)):
                    centers = []
                    for port in ports:
                        self.assertIs(port.node, view)
                        center = port.mapToParent(port.boundingRect().center())
                        self.assertAlmostEqual(center.x(), 0 if side == 0 else view.width)
                        centers.append(center.y())
                    for first, second in zip(centers, centers[1:]):
                        self.assertAlmostEqual(second - first, 24)

    def test_wires_follow_grid_cells_after_rename_and_reload(self):
        nodes = {op: self.add(next(c for c in NODE_CLASSES if c.OPERATION == op))
                 for op in ("slider", "point", "watch")}
        nodes["slider"].set_pos(-350, -100)
        nodes["watch"].set_pos(250, 100)
        nodes["slider"].output(0).connect_to(nodes["point"].input(0))
        nodes["point"].output(0).connect_to(nodes["watch"].input(0))

        def check_wires():
            self.app.processEvents()
            for node in self.window.graph.all_nodes():
                for port in node.view.outputs:
                    for pipe in port.connected_pipes:
                        actual = (pipe.path().pointAtPercent(0), pipe.path().pointAtPercent(1))
                        for endpoint in (pipe.input_port, pipe.output_port):
                            expected = endpoint.mapToScene(endpoint.boundingRect().center())
                            self.assertTrue(any((value - expected).manhattanLength() < 0.001 for value in actual))

        check_wires()
        nodes["point"].set_name("A longer Point title")
        check_wires()
        session = self.window.graph.serialize_session()
        self.window.graph.deserialize_session(session, clear_session=True)
        check_wires()

    def test_grid_reflows_when_watch_content_grows(self):
        watch = self.add(next(c for c in NODE_CLASSES if c.OPERATION == "watch"))
        self.window.show()
        self.app.processEvents()
        display = watch.get_widget("display")
        display.set_value("A longer result which wraps across several lines. " * 15)
        self.app.processEvents()
        self.check_contents(watch)
        rect = display.mapRectToParent(display.boundingRect())
        self.assertLessEqual(rect.bottom(), watch.view.height)
        for port in watch.view.inputs + watch.view.outputs:
            self.assertAlmostEqual(port.y() + port.boundingRect().center().y(),
                                   (watch.view._header_height + watch.view.height) / 2 - 0.5)

    def test_point_has_no_footer_space(self):
        point = self.add(next(c for c in NODE_CLASSES if c.OPERATION == "point"))
        view = point.view
        self.assertLessEqual(view.height, 128)
        last = view.outputs[-1]
        self.assertLessEqual(view.height - last.mapRectToParent(last.boundingRect()).bottom(), 6)


if __name__ == "__main__":
    unittest.main()
