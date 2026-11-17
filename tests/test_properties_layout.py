"""Real Qt input previews follow text height, wrapping and active pages."""
import os
import unittest

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from noodles.window import MainWindow


class PropertiesLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        self.source = self.window.graph.create_node("NoodleS.Math.RangeNode")
        self.source.set_property("start", 1)
        self.source.set_property("end", 11)

    def settle(self):
        for _ in range(3):
            self.app.processEvents()
        # Exercise the actual rendered layout, including nested height-for-width.
        self.window.grab()
        QTest.qWait(30)

    def tearDown(self):
        self.window.graph.undo_stack().setClean()
        self.window.close()
        self.window.deleteLater()
        self.settle()

    def check_fits_text(self, stack, preview):
        self.assertIs(stack.currentWidget(), preview)
        expected = preview.heightForWidth(preview.width())
        self.assertGreater(expected, 0)
        self.assertAlmostEqual(stack.height(), expected, delta=2)

    def test_point_tree_preview_grows_and_shrinks_without_reserved_blank_space(self):
        point = self.window.add_node("NoodleS.Geometry.PointNode")
        self.source.outputs()["R"].connect_to(point.inputs()["X"])
        self.settle()
        panel = self.window.properties.point_properties
        stack, preview = panel.input_stacks["X"], panel.previews["X"]
        self.check_fits_text(stack, preview)
        short_height = stack.height()
        self.assertLess(short_height, 60)
        generated = panel.generate.layout()
        self.assertAlmostEqual(generated.itemAt(3).geometry().top() -
                               (stack.y() + stack.height()), generated.spacing(), delta=1)
        point.set_property("tree_modes", {"X": "graft"})
        self.settle()
        self.check_fits_text(stack, preview)
        self.assertGreater(stack.height(), short_height)
        point.set_property("tree_modes", {})
        self.settle()
        self.assertEqual(stack.height(), short_height)
        point.inputs()["X"].clear_connections()
        self.settle()
        self.assertIs(stack.currentWidget(), panel.editors["X"])
        self.assertEqual(stack.height(), panel.editors["X"].height())
        self.assertEqual(stack.height(), 36)

    def test_domain_and_range_previews_use_the_same_content_layout(self):
        for kind, property_name, port in (("Domain", "domain_properties", "A"),
                                          ("Range", "range_properties", "N")):
            with self.subTest(node=kind):
                node = self.window.add_node(f"NoodleS.Math.{kind}Node")
                if kind == "Domain":
                    node.set_property("end", 100)
                self.source.outputs()["R"].connect_to(node.inputs()[port])
                self.settle()
                panel = getattr(self.window.properties, property_name)
                stack, preview = panel.stacks[port], panel.previews[port]
                self.check_fits_text(stack, preview)
                self.assertLess(stack.height(), 60)
                node.set_property("tree_modes", {port: "graft"})
                self.settle()
                self.check_fits_text(stack, preview)

    def test_wrapped_preview_reflows_when_properties_width_changes(self):
        point = self.window.add_node("NoodleS.Geometry.PointNode")
        self.source.set_property("start", 12345678.1234)
        self.source.set_property("end", 23456789.1234)
        self.source.outputs()["R"].connect_to(point.inputs()["X"])
        self.window.splitter.setSizes([230, 600, 500])
        self.settle()
        panel = self.window.properties.point_properties
        stack, preview = panel.input_stacks["X"], panel.previews["X"]
        self.check_fits_text(stack, preview)
        wide_height = stack.height()
        self.window.splitter.setSizes([230, 900, 290])
        self.settle()
        self.check_fits_text(stack, preview)
        self.assertGreater(stack.height(), wide_height)

    def test_side_panel_toggles_preserve_canvas_scale_and_center(self):
        viewer = self.window.graph.viewer()
        self.window.graph.set_zoom(-0.5)
        self.window.graph.center_on([self.source])
        transform = viewer.transform()
        center = viewer.mapToScene(viewer.viewport().rect().center())
        original_width = viewer.viewport().width()

        for button, expands in ((self.window.library_button, True), (self.window.properties_button, True),
                                (self.window.library_button, False), (self.window.properties_button, False)):
            width = viewer.viewport().width()
            QTest.mouseClick(button, QtCore.Qt.LeftButton)
            self.settle()
            new_width = viewer.viewport().width()
            if expands:
                self.assertGreater(new_width, width)
            else:
                self.assertLess(new_width, width)
            self.assertEqual(viewer.transform(), transform)
            shifted = viewer.mapToScene(viewer.viewport().rect().center()) - center
            self.assertLessEqual(shifted.manhattanLength() * transform.m11(), 2)

        self.assertEqual(viewer.viewport().width(), original_width)
        viewer.force_update()
        self.assertAlmostEqual(viewer.transform().m11(), transform.m11())

        viewport = viewer.viewport()
        pos = viewport.rect().center()
        wheel = QtGui.QWheelEvent(QtCore.QPointF(pos), QtCore.QPointF(viewport.mapToGlobal(pos)),
                                  QtCore.QPoint(), QtCore.QPoint(0, 120), QtCore.Qt.NoButton,
                                  QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
        self.app.sendEvent(viewport, wheel)
        self.assertGreater(viewer.transform().m11(), transform.m11())


if __name__ == "__main__":
    unittest.main()
