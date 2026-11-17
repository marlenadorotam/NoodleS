"""Penrose editor, bridge and native OCC in a private document."""
import unittest

import test_curve_native as fixture


class PenroseNativeTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativeCurveTests.setUpClass.__func__)
    setUp = fixture.NativeCurveTests.setUp
    tearDown = fixture.NativeCurveTests.tearDown
    wait_for = fixture.NativeCurveTests.wait_for

    def test_rectangle_pattern_keeps_one_owner_when_arcs_are_disabled(self):
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GeomAbs import GeomAbs_Circle
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.backend.scene_points import MODEL
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            rectangle = editor.add_node('NoodleS.Geometry.RectangleNode')
            penrose = editor.add_node('NoodleS.Operations.PenroseP2Node')
            rectangle.outputs()['C'].connect_to(penrose.inputs()['B'])
            identity = (editor.project_uuid, penrose.curve_state()['node_uuid'], 0)
            self.wait_for(lambda: self.bridge.points.owner(identity) is not None)
            owner = self.bridge.points.owner(identity)
            self.assertTrue(owner.mesh_ready)
            self.assertEqual(len(self.window.scene.objects), 2)
            circles = lambda obj: sum(BRepAdaptor_Curve(edge).GetType() == GeomAbs_Circle
                                      for edge in self.geo.edges_of(obj.shape))
            self.assertGreater(circles(owner), 0)
            low, high = self.geo.bbox(owner.shape)
            for actual, expected in zip((*low, *high), (-5., -5., 0., 5., 5., 0.)):
                self.assertAlmostEqual(actual, expected, places=5)
            panel = editor.properties.curve_properties
            self.wait_for(panel.matching_arcs.isVisible)
            QTest.mouseClick(panel.matching_arcs, QtCore.Qt.LeftButton, pos=QtCore.QPoint(6, 8))
            self.wait_for(lambda: not any(
                part.get('arc') for branch in self.bridge.points._json(self.bridge.points.owner(identity), MODEL)['branches']
                for part in branch['parts']))
            updated = self.bridge.points.owner(identity)
            self.assertEqual(updated.id, owner.id)
            self.assertEqual(circles(updated), 0)
            self.assertEqual(len(self.window.scene.objects), 2)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_native_command_publishes_one_pattern_without_the_editor(self):
        from types import SimpleNamespace
        from serpentine3d.commands.base import resolve
        from noodles.backend.penrose_native import register_commands

        self.window._noodles_bridge = self.bridge
        register_commands(self.ctx)
        scene = self.window.scene
        boundary = scene.add(self.geo.make_rectangle((0, 0, 0), (20, 12, 0)))
        messages = []
        command = resolve('penrosep2').fn(SimpleNamespace(echo=messages.append))
        next(command)
        command.send('Boundary')
        command.send([boundary])
        command.send(3)
        with self.assertRaises(StopIteration):
            command.send('On')
        self.wait_for(lambda: any(message.startswith('Created ') for message in messages))
        self.assertEqual(len(scene.objects), 2)
        self.assertTrue(scene.all()[-1].mesh_ready)
