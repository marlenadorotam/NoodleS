"""Run actual Serpentine generator commands against private native scenes."""
import math
from types import SimpleNamespace
import unittest

import test_point_native as native_fixture
from noodles.backend.primitive_shapes import register_commands


class NativePrimitiveCommandTests(unittest.TestCase):
    setUpClass = classmethod(native_fixture.NativePointTests.setUpClass.__func__)

    def setUp(self):
        from serpentine3d.plugins import PluginContext
        from serpentine3d.commands import solids, base
        self.base = base
        self.original_cylinder = base.resolve('cylinder')
        self.original_cone = base.resolve('cone')
        register_commands(PluginContext())
        self.scene = self.Scene()
        self.messages = []
        self.ctx = SimpleNamespace(scene=self.scene, echo=self.messages.append,
            cplane=SimpleNamespace(normal=(0., -1., 0.), xdir=(1., 0., 0.)))

    def run_command(self, name, values):
        generator = self.base.resolve(name).fn(self.ctx)
        request = next(generator)
        for value in values:
            try:
                request = generator.send(value)
            except StopIteration:
                return
        self.fail('Native command did not complete.')

    def test_native_commands_share_factories_and_leave_builtin_commands_unchanged(self):
        from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE
        from OCP.BRepCheck import BRepCheck_Analyzer
        for name in ('cylinderparam', 'coneparam', 'paraboloid'):
            for solid in ((True, False) if name != 'paraboloid' else (False,)):
                with self.subTest(name=name, solid=solid):
                    scene = self.Scene()
                    self.ctx.scene = scene
                    values = (['Solid' if solid else 'Shell'] if name != 'paraboloid' else []) + [(2., 3., 4.), (7., 3., 4.), (2., -7., 4.)]
                    self.run_command(name, values)
                    self.assertEqual(len(scene.objects), 1)
                    obj = next(iter(scene.objects.values()))
                    self.assertEqual(obj.shape.ShapeType(), TopAbs_SOLID if solid else TopAbs_FACE)
                    self.assertTrue(BRepCheck_Analyzer(obj.shape).IsValid())
                    low, high = self.geo.bbox(obj.shape)
                    self.assertAlmostEqual(high[1]-low[1], 10, delta=1e-5)
        self.assertIs(self.base.resolve('cylinder'), self.original_cylinder)
        self.assertIs(self.base.resolve('cone'), self.original_cone)
        self.assertIs(self.base.resolve('cylinderex'), self.base.resolve('cylinderparam'))

    def test_invalid_radius_height_or_mode_does_not_create_scene_objects(self):
        self.run_command('cylinderparam', ['unknown'])
        self.run_command('coneparam', ['Solid', (0, 0, 0), (0, 0, 0)])
        self.run_command('coneparam', ['Shell', (0, 0, 0), (5, 0, 0), (0, 0, 0)])
        self.run_command('paraboloid', [(0, 0, 0), (5, 0, 0), (0, 10, 0)])
        self.assertFalse(self.scene.objects)

    def test_cone_commands_build_and_preview_downward_cones_from_text_and_click(self):
        from itertools import product
        import numpy as np
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from serpentine3d.core.cplane import CPlane
        from serpentine3d.ui.viewport import Viewport

        cases = product(('coneparam', 'truncatedcone'), (('Solid', TopAbs_SOLID), ('Shell', TopAbs_FACE)), (False, True))
        for command, (mode, topology), picked in cases:
            with self.subTest(command=command, mode=mode, picked=picked):
                scene = self.Scene()
                selection = self.Selection(scene)
                context = self.base.CommandContext(scene, selection, self.History(scene))
                context.replay_cplane = CPlane()
                processor = self.base.CommandProcessor(context)
                processor.run(command)
                for text in (mode, '0,0,0', '5'):
                    processor.provide_text(text)
                if command == 'truncatedcone':
                    processor.provide_text('2')
                if picked:
                    view = Viewport(scene, selection)
                    try:
                        view.resize(800, 600)
                        view.point_mode = True
                        view.point_axis = processor.request.axis_lock
                        view.pointPicked.connect(processor.provide)
                        x, y, _ = view.camera.project(np.array([(0., 0., -10.)]), view.width(), view.height())[0]
                        pixel = QPoint(round(x), round(y))
                        apex = view.world_point_at(pixel.x(), pixel.y())
                        self.assertLess(apex[2], 0.)
                        preview = processor.preview_for(apex)
                        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=pixel)
                    finally:
                        view.close()
                        view.deleteLater()
                else:
                    apex = (0., 0., -10.)
                    preview = processor.preview_shape('-10')
                    processor.provide_text('-10')
                self.assertIsNotNone(preview)
                self.assertFalse(processor.busy)
                obj, = scene.all()
                if command == 'truncatedcone':
                    from noodles.backend.solid_native import inspect_solid
                    dimensions = inspect_solid(obj, 'test', 'truncated_cone')['recipe']['dimensions']
                    for actual, expected in zip(dimensions, (5., 2., apex[2])):
                        self.assertAlmostEqual(actual, expected, places=6)
                for shape in (preview, obj.shape):
                    self.assertEqual(shape.ShapeType(), topology)
                    self.assertTrue(BRepCheck_Analyzer(shape).IsValid())
                    low, high = self.geo.bbox(shape)
                    self.assertAlmostEqual(low[2], apex[2], places=5)
                    self.assertAlmostEqual(high[2], 0., places=5)

    def test_point_cylindrical_respects_the_construction_plane(self):
        self.ctx.cplane.origin = (1., 2., 3.)
        self.run_command('pointcylindrical', (math.pi / 2, 2., 4.))
        obj = next(iter(self.scene.objects.values()))
        self.assertLess(math.dist(self.geo.point_coords(obj.shape), (1., -2., 5.)), 1e-12)

    def test_pyramid_command_negative_height_matches_node_in_both_modes(self):
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
        from serpentine3d.core.cplane import CPlane
        from noodles.backend.curves import PlaneValue
        from noodles.backend.primitive_shapes import materialize
        from noodles.backend.solid_native import inspect_solid
        from noodles.backend.solids import SolidValue

        for mode, topology in (('Solid', TopAbs_SOLID), ('Shell', TopAbs_SHELL)):
            with self.subTest(mode=mode):
                scene = self.Scene()
                ctx = self.base.CommandContext(scene, self.Selection(scene), self.History(scene))
                ctx.replay_cplane = CPlane()
                processor = self.base.CommandProcessor(ctx)
                processor.run('pyramid')
                for text in (mode, '2,4,6', '10', '6'):
                    processor.provide_text(text)
                preview = processor.preview_shape('-9')
                self.assertIsNotNone(preview)
                processor.provide_text('-9')
                self.assertFalse(processor.busy)
                obj, = scene.all()
                recipe = inspect_solid(obj, 'test', 'pyramid')['recipe']
                self.assertEqual(recipe['dimensions'], [10., 6., -9.])
                node_shape = materialize(SolidValue('test', 'pyramid', PlaneValue((2, 4, 6)),
                                                    (10, 6, -9), mode == 'Solid'))
                for shape in (preview, obj.shape, node_shape):
                    self.assertEqual(shape.ShapeType(), topology)
                    self.assertTrue(BRepCheck_Analyzer(shape).IsValid())
                    self.assertEqual(len(self.geo.faces_of(shape)), 5 if mode == 'Solid' else 4)
                    for result, expected in zip(self.geo.bbox(shape), ((-3, 1, -3), (7, 7, 6))):
                        for a, b in zip(result, expected):
                            self.assertAlmostEqual(a, b, places=5)

    def test_ellipsoid_command_uses_construction_plane_and_publishes_one_shape(self):
        from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
        from serpentine3d.core.cplane import CPlane
        from noodles.backend.ellipsoid_native import inspect_ellipsoid

        for mode, topology in (('Solid', TopAbs_SOLID), ('Shell', TopAbs_SHELL)):
            with self.subTest(mode=mode):
                scene = self.Scene()
                ctx = self.base.CommandContext(scene, self.Selection(scene), self.History(scene))
                ctx.replay_cplane = CPlane(normal=(0, -1, 0))
                processor = self.base.CommandProcessor(ctx)
                processor.run('ellipsoideparam')
                for text in (mode, '2,4,6', '3', '7', '5'):
                    processor.provide_text(text)
                self.assertFalse(processor.busy)
                obj, = scene.all()
                self.assertEqual(obj.shape.ShapeType(), topology)
                recipe = inspect_ellipsoid(obj.shape, 'test')
                for actual, expected in zip(recipe.dimensions, (3, 7, 5)):
                    self.assertAlmostEqual(actual, expected)
                for actual, expected in zip(recipe.frame.normal, (0, -1, 0)):
                    self.assertAlmostEqual(actual, expected)

    def test_native_processor_accepts_typed_and_picked_centers(self):
        import numpy as np
        from serpentine3d.core.cplane import CPlane

        for command in ('coneparam', 'cylinderparam', 'paraboloid'):
            for typed in (True, False):
                with self.subTest(command=command, typed=typed):
                    scene = self.Scene()
                    context = self.base.CommandContext(scene, self.Selection(scene), self.History(scene))
                    context.replay_cplane = CPlane(normal=(0, -1, 0))
                    processor = self.base.CommandProcessor(context)
                    processor.run(command)
                    if command != 'paraboloid':
                        processor.provide_text('Solid')
                    self.assertIsInstance(processor.request, self.base.PointReq)
                    if typed:
                        processor.provide_text('0,0,0')
                    else:
                        processor.provide(np.array((2., 3., 4.)))
                    self.assertIsInstance(processor.request, self.base.PointReq)
                    self.assertIn('Radius', processor.request.prompt)
                    processor.provide_text('5')
                    processor.provide_text('10')
                    self.assertFalse(processor.busy)
                    self.assertEqual(len(scene.objects), 1)
                    low, high = self.geo.bbox(next(iter(scene.objects.values())).shape)
                    self.assertAlmostEqual(high[1] - low[1], 10., places=5)
