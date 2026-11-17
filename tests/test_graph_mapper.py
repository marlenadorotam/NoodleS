"""Independent math identities, parameter boundaries and real Qt curve editing."""
import copy
import itertools
import math
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

os.environ['QT_PREFERRED_BINDING'] = 'PySide6'
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from Qt import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from noodles.backend.arithmetic import VectorValue
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.domain import DomainValue
from noodles.backend.graph_mapper import KINDS, KIND_PARAMS, PARAM_LIMITS, normalize_config, unit_value
from noodles.backend.math_nodes import evaluate_math
from noodles.core import Connection, GraphEngine, NodeSpec
from noodles.document import DocumentError, read_document, validate_document, write_document
from noodles.graph_mapper import GraphPlot
from noodles.window import MainWindow


def curve(kind, x, **parameters):
    return unit_value(x, normalize_config({'kind': kind, **parameters}))


def mapping(value, config=None, **inputs):
    return evaluate_math('graph_mapper', {'graph_config': config or {}}, {'V': value, **inputs})


class GraphMapperMathTests(unittest.TestCase):
    def test_linear_endpoints_slopes_and_input_clipping(self):
        for a, b in ((0, 1), (1, 0), (.2, .8), (.6, .6)):
            for x in (-1, 0, .2, .5, .9, 1, 2):
                self.assertAlmostEqual(curve('Linear', x, linear_a=a, linear_b=b), a + (b-a)*min(1, max(0, x)))

    def test_cubic_bezier_inverts_x_and_has_exact_endpoints(self):
        for x1, x2, y1, y2 in ((.1, .4, .9, .2), (0, 0, 1, 1), (1, 1, 0, 0), (.5, .5, .1, .9)):
            config = dict(bezier_x1=x1, bezier_x2=x2, bezier_y1=y1, bezier_y2=y2)
            self.assertEqual(curve('Bezier', 0, **config), 0)
            self.assertEqual(curve('Bezier', 1, **config), 1)
            for t in (.001, .05, .2, .5, .8, .99):
                s = 1-t
                x, y = 3*s*s*t*x1+3*s*t*t*x2+t**3, 3*s*s*t*y1+3*s*t*t*y2+t**3
                self.assertAlmostEqual(curve('Bezier', x, **config), y, delta=1e-9)

    def test_quadratic_bezier_inverts_x_and_has_exact_endpoints(self):
        for cx, cy in ((0, 1), (1, 0), (.2, .8), (.5, .5)):
            for t in (0, .01, .2, .5, .9, 1):
                x, y = 2*(1-t)*t*cx+t*t, 2*(1-t)*t*cy+t*t
                self.assertAlmostEqual(curve('Quadratic Bezier', x, quadratic_x=cx, quadratic_y=cy), y, delta=1e-9)
            self.assertEqual(curve('Quadratic Bezier', 0, quadratic_x=cx, quadratic_y=cy), 0)
            self.assertEqual(curve('Quadratic Bezier', 1, quadratic_x=cx, quadratic_y=cy), 1)

    def test_power_and_square_root_families(self):
        for x in (0, .01, .25, .5, 1):
            self.assertAlmostEqual(curve('Power', x), x**2.5)
            self.assertAlmostEqual(curve('Square Root', x), math.sqrt(x))
            for exponent in (.1, 1, 10):
                self.assertAlmostEqual(curve('Power', x, power_exponent=exponent), x**exponent)
            for exponent in (.1, .3, 1):
                self.assertAlmostEqual(curve('Square Root', x, sqrt_exponent=exponent), x**exponent)

    def test_parabola_default_and_shifted_peak(self):
        for x in (0, .1, .25, .5, .9, 1):
            self.assertAlmostEqual(curve('Parabola', x), 4*x*(1-x))
        for peak in (.05, .3, .95):
            self.assertEqual(curve('Parabola', peak, parabola_peak_x=peak, parabola_peak_y=.7), .7)
            self.assertAlmostEqual(curve('Parabola', 0, parabola_peak_x=peak), 0)
            self.assertAlmostEqual(curve('Parabola', 1, parabola_peak_x=peak), 0)

    def test_smoothstep_interval_and_shape(self):
        for exponent in (.6, 1, 4):
            for x in (0, .2, .35, .5, .8, 1):
                t = min(1, max(0, (x-.2)/.6))
                self.assertAlmostEqual(curve('Smoothstep', x, smoothstep_start=.2, smoothstep_end=.8,
                                           smoothstep_shape=exponent), (t*t*(3-2*t))**exponent)

    def test_sigmoid_normalization_symmetry_and_steepness(self):
        for k in (.5, 10, 24):
            self.assertEqual(curve('Sigmoid', 0, sigmoid_steepness=k), 0)
            self.assertEqual(curve('Sigmoid', 1, sigmoid_steepness=k), 1)
            self.assertAlmostEqual(curve('Sigmoid', .5, sigmoid_steepness=k), .5)
            for x in (.1, .25, .7):
                low, high = 1/(1+math.exp(k/2)), 1/(1+math.exp(-k/2))
                expected = (1/(1+math.exp(-k*(x-.5)))-low)/(high-low)
                self.assertAlmostEqual(curve('Sigmoid', x, sigmoid_steepness=k), expected)
                self.assertAlmostEqual(curve('Sigmoid', 1-x, sigmoid_steepness=k), 1-expected)

    def test_exponential_both_signs_and_zero_limit(self):
        for rate in (-12, -4, -1e-11, 0, 1e-11, 4, 12):
            for x in (0, .2, .5, .9, 1):
                expected = x if abs(rate) < 1e-10 else (math.exp(rate*x)-1)/(math.exp(rate)-1)
                self.assertAlmostEqual(curve('Exponential', x, exponential_rate=rate), expected)
        self.assertAlmostEqual(curve('Exponential', .5, exponential_rate=-4), 1-curve('Exponential', .5, exponential_rate=4))

    def test_sine_frequency_amplitude_and_summation_clipping(self):
        for f in (.25, 1, 6):
            for amplitude in (0, .2, .5):
                for x in (0, .1, .25, .5, 1):
                    self.assertAlmostEqual(curve('Sine', x, sine_frequency=f, sine_amplitude=amplitude),
                                           .5-amplitude*math.cos(2*math.pi*f*x))
            for a1, a2 in ((.3, .12), (.5, .5), (0, -.5)):
                for x in (0, .2, .5, 1):
                    y = .5-a1*math.cos(2*math.pi*f*x)-a2*math.cos(4*math.pi*f*x)
                    self.assertAlmostEqual(curve('Sine Summation', x, sine_sum_frequency=f, sine_sum_a1=a1, sine_sum_a2=a2),
                                           min(1, max(0, y)))

    def test_gaussian_center_sigma_and_narrow_underflow(self):
        for center, sigma in itertools.product((0, .5, 1), (.01, .18, 1)):
            self.assertEqual(curve('Gaussian', center, gaussian_center=center, gaussian_sigma=sigma), 1)
            for x in (0, .1, .7, 1):
                self.assertEqual(curve('Gaussian', x, gaussian_center=center, gaussian_sigma=sigma),
                                 math.exp(-.5*((x-center)/sigma)**2))

    def test_all_parameter_extremes_and_flips_stay_finite_and_bounded(self):
        rng = random.Random(20261101)
        configs = []
        for kind in KINDS:
            configs.append(normalize_config({'kind': kind}))
            for key in KIND_PARAMS[kind]:
                for bound in PARAM_LIMITS[key]:
                    data = {'kind': kind, key: bound}
                    if key == 'bezier_x1':
                        data['bezier_x2'] = 1
                    if key == 'bezier_x2':
                        data['bezier_x1'] = 0
                    if key == 'smoothstep_start':
                        data['smoothstep_end'] = 1
                    if key == 'smoothstep_end':
                        data['smoothstep_start'] = 0
                    configs.append(normalize_config(data))
        for config in configs:
            for x in [0, 1, .5, *[rng.random() for _ in range(8)]]:
                with self.subTest(kind=config['kind'], x=x):
                    value = unit_value(x, config)
                    self.assertTrue(math.isfinite(value))
                    self.assertTrue(0 <= value <= 1)
                    self.assertAlmostEqual(unit_value(x, {**config, 'reverse': True}), 1-value)
                    self.assertAlmostEqual(unit_value(1-x, {**config, 'flip_x': True}), value, delta=1e-9)

    def test_invalid_config_is_rejected_including_hidden_parameters(self):
        for raw in ([], True, 'Sine', {'kind': 'Code'}, {'reverse': 1}, {'flip_x': 'false'},
                    {'bezier_x1': .8, 'bezier_x2': .2}, {'smoothstep_start': .7, 'smoothstep_end': .71}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_config(raw)
        for key, (low, high) in PARAM_LIMITS.items():
            for value in (low-1, high+1, float('nan'), float('inf'), True):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    normalize_config({key: value})
        with self.assertRaises(ValueError):
            unit_value(float('nan'), normalize_config())

    def test_domains_clamp_reverse_interpolate_and_handle_large_finite_bounds(self):
        self.assertEqual(mapping([-5, 0, 5, 10, 15], I=DomainValue(0, 10), O=DomainValue(10, 20))['R'].values(),
                         (10, 10, 15, 20, 20))
        self.assertEqual(mapping([0, 5, 10], I=DomainValue(10, 0), O=DomainValue(20, 10))['R'].values(), (10, 15, 20))
        extreme = mapping([-1e308, 0, 1e308], I=DomainValue(-1e308, 1e308), O=DomainValue(1e308, -1e308))
        self.assertEqual(extreme['R'].values(), (1e308, 0, -1e308))
        self.assertEqual(mapping(5e-324, I=DomainValue(0, 1e-323))['R'], .5)
        for port in ('I', 'O'):
            with self.assertRaisesRegex(ValueError, 'nonzero'):
                mapping(.5, **{port: DomainValue(1, 1)})
        for value in (True, float('nan'), VectorValue((1, 2, 3))):
            with self.assertRaises(ValueError):
                mapping(value)

    def test_tree_paths_keys_domains_graft_flatten_count_and_empty(self):
        source = DataTree((Branch((4,), (0, .5), ('a', 'b')), Branch((9,), (1,), ('c',))))
        domains = DataTree((Branch((9,), (DomainValue(0, 2),)), Branch((4,), (DomainValue(0, 1),))))
        result = mapping(source, I=domains)
        self.assertEqual(result['R'].values(), (0, .5, .5))
        self.assertEqual(result['Count'], 3)
        self.assertEqual(tuple(b.path for b in result['R'].branches), ((4,), (9,)))
        self.assertEqual(result['Flat'].branches[0].keys, tuple(k for b in result['R'].branches for k in b.keys))
        for port in ('V', 'I', 'O'):
            result = evaluate_math('graph_mapper', {'tree_modes': {port: 'graft'}}, {'V': .5})
            self.assertEqual(result['R'].branches[0].path, (0, 0))
        flat = evaluate_math('graph_mapper', {'tree_modes': {'V': 'flatten'}}, {'V': source})
        self.assertEqual(tuple(b.path for b in flat['R'].branches), ((0,),))
        for value in ([], DataTree(()), DataTree((Branch((7,), ()),))):
            empty = mapping(value)
            self.assertEqual(empty['R'].count, 0)
            self.assertEqual(empty['Count'], 0)
        self.assertIsInstance(mapping([.5])['R'], DataTree)
        self.assertIsInstance(mapping(.5)['R'], float)
        with self.assertRaisesRegex(ValueError, '10,000'):
            mapping([0]*10001)

    def test_engine_cache_invalid_input_failure_recovery_and_no_geometry(self):
        engine = GraphEngine()
        def graph(end):
            return [NodeSpec('v', 'range', {'steps': 4}),
                    NodeSpec('m', 'graph_mapper', {'input_end': end, 'graph_config': {'kind': 'Power', 'power_exponent': 2}},
                             inputs={'V': Connection('v', 'R')}),
                    NodeSpec('w', 'watch', inputs={'Value': Connection('m', 'R')})]
        good = engine.evaluate(graph(1))
        self.assertEqual(good.results['w'].outputs['Value'].values(), (0, .0625, .25, .5625, 1))
        self.assertIsNone(good.results['m'].parametric_object)
        self.assertEqual(engine.evaluate(graph(1)).computed, ())
        bad = engine.evaluate(graph(0))
        self.assertEqual(bad.results['m'].outputs, {})
        self.assertTrue(bad.results['w'].blocked)
        self.assertEqual(engine.evaluate(graph(1)).results['m'].outputs['Count'], 5)


class GraphMapperWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        if windows := os.environ.get("WINDIR"):
            for font in ('segoeui.ttf', 'segoeuib.ttf', 'arial.ttf', 'arialbd.ttf'):
                QtGui.QFontDatabase.addApplicationFont(str(Path(windows) / "Fonts" / font))

    def setUp(self):
        self.window = MainWindow()
        self.window.resize(1440, 1000)
        self.window.show()
        self.node = self.window.add_node('NoodleS.Math.GraphMapperNode')
        self.settle()

    def settle(self):
        self.app.processEvents()
        self.window.grab()
        QTest.qWait(30)

    def tearDown(self):
        self.window.graph.undo_stack().setClean()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def controls(self):
        return self.window.properties.math_properties.graph_controls

    def set_curve(self, kind, **parameters):
        self.node.set_property('graph_config', normalize_config({'kind': kind, **parameters}))
        self.settle()

    def drag_plot(self, plot, name, x, y):
        handle = next((hx, hy) for hn, hx, hy in plot._handles() if hn == name)
        start, end = plot._px(*handle).toPoint(), plot._px(x, y).toPoint()
        QTest.mousePress(plot, QtCore.Qt.LeftButton, pos=start)
        QTest.mouseMove(plot, QtCore.QPoint((start.x()+end.x())//2, (start.y()+end.y())//2))
        self.settle()
        QTest.mouseMove(plot, end)
        QTest.mouseRelease(plot, QtCore.Qt.LeftButton, pos=end)
        self.settle()

    def type_field(self, field, value):
        field.setFocus()
        QTest.keyClick(field, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QTest.keyClicks(field, str(value))
        QTest.keyClick(field, QtCore.Qt.Key_Return)
        self.settle()

    def test_properties_function_selection_flips_precise_parameters_and_reset(self):
        controls = self.controls()
        controls.kind.setFocus()
        QTest.keyClick(controls.kind, QtCore.Qt.Key_Down)
        self.settle()
        self.assertEqual(self.node.get_property('graph_config')['kind'], 'Bezier')
        self.type_field(controls.fields['bezier_x1'], .9)
        self.assertEqual(self.node.get_property('graph_config')['bezier_x1'], .75)
        for button, key in ((controls.flip_x, 'flip_x'), (controls.flip_y, 'reverse')):
            QTest.mouseClick(button, QtCore.Qt.LeftButton)
            self.settle()
            self.assertTrue(self.node.get_property('graph_config')[key])
        QTest.mouseClick(controls.reset, QtCore.Qt.LeftButton)
        self.settle()
        config = self.node.get_property('graph_config')
        self.assertEqual(config['bezier_x1'], .25)
        self.assertTrue(config['flip_x'] and config['reverse'])
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(self.node.get_property('graph_config')['bezier_x1'], .75)

    def test_every_handle_real_mouse_events_changes_valid_state_and_one_undo(self):
        for kind in KINDS:
            self.set_curve(kind)
            names = [name for name, _, _ in self.controls().plot._handles()]
            for name in names:
                self.set_curve(kind)
                plot = self.controls().plot
                hx, hy = next((x, y) for n, x, y in plot._handles() if n == name)
                before = copy.deepcopy(plot.config)
                self.window.graph.undo_stack().clear()
                with self.subTest(kind=kind, handle=name):
                    target_y = hy+.2 if hy < .2 else hy-.2
                    self.drag_plot(plot, name, min(.85, hx+.15), min(.95, max(.05, target_y)))
                    state = self.node.get_property('graph_config')
                    self.assertNotEqual(state, before)
                    self.assertEqual(normalize_config(state), state)
                    self.assertEqual(self.window.graph.undo_stack().count(), 1)
                    self.assertEqual(self.node.get_widget('graph_config').get_value(), state)
                    self.window.graph.undo_stack().undo()
                    self.settle()
                    self.assertEqual(self.node.get_property('graph_config'), before)

    def test_flipped_handles_change_underlying_parameters_in_correct_direction(self):
        for flip_x, flip_y in itertools.product((False, True), repeat=2):
            self.set_curve('Quadratic Bezier', flip_x=flip_x, reverse=flip_y)
            plot = self.controls().plot
            shown_x, shown_y = (.8, .2) if flip_x else (.2, .8)
            if flip_y:
                shown_y = 1-shown_y
            self.drag_plot(plot, 'quadratic', shown_x, shown_y)
            config = self.node.get_property('graph_config')
            self.assertAlmostEqual(config['quadratic_x'], 1-shown_x if flip_x else shown_x, delta=.01)
            self.assertAlmostEqual(config['quadratic_y'], 1-shown_y if flip_y else shown_y, delta=.01)

    def test_sine_and_gaussian_handles_stay_on_curve_at_previously_broken_limits(self):
        plot = self.controls().plot
        for kind, parameters in (('Sine', {'sine_frequency': .25}), ('Sine', {'sine_frequency': 6}),
                                 ('Gaussian', {'gaussian_center': .5, 'gaussian_sigma': 1}),
                                 ('Gaussian', {'gaussian_center': 1, 'gaussian_sigma': .01})):
            for flip_x, reverse in itertools.product((False, True), repeat=2):
                config = normalize_config({'kind': kind, **parameters, 'flip_x': flip_x, 'reverse': reverse})
                plot.set_config(config)
                for name, x, y in plot._handles():
                    self.assertAlmostEqual(y, unit_value(x, config), msg=name)
                plot.grab()

    def test_nonlinear_handle_inverses_match_requested_curve_height(self):
        cases = (('Power', 'power', .5, .4), ('Smoothstep', 'smoothstep_shape', .5, .4),
                 ('Sigmoid', 'sigmoid', .25, .15), ('Square Root', 'sqrt', .5, .7),
                 ('Exponential', 'exponential', .5, .6), ('Gaussian', 'gaussian_sigma', .75, .7))
        for kind, handle, x, y in cases:
            for flip_x, reverse in itertools.product((False, True), repeat=2):
                self.set_curve(kind, flip_x=flip_x, reverse=reverse)
                plot = self.controls().plot
                shown_x, shown_y = (1-x if flip_x else x), (1-y if reverse else y)
                self.drag_plot(plot, handle, shown_x, shown_y)
                self.assertAlmostEqual(unit_value(shown_x, self.node.get_property('graph_config')), shown_y,
                                       delta=.012, msg=(kind, flip_x, reverse))

    def test_canvas_viewport_drag_keeps_inspector_on_other_node_and_undoes_once(self):
        other = self.window.add_node('NoodleS.Inputs.NumberNode')
        self.node.set_pos(0, 0)
        other.set_pos(350, 0)
        self.window.graph.clear_selection()
        other.set_selected(True)
        self.window.graph.set_zoom(0)
        self.window.graph.center_on([self.node, other])
        self.settle()
        proxy = self.node.get_widget('graph_config')
        plot = proxy.plot
        view = self.window.graph.viewer()
        def position(x, y):
            local = plot.mapTo(proxy.widget(), plot._px(x, y).toPoint())
            return view.mapFromScene(proxy.mapToScene(QtCore.QPointF(local)))
        start, end = position(0, 0), position(0, .6)
        self.window.graph.undo_stack().clear()
        before_size = (self.node.view.width, self.node.view.height)
        with patch.object(self.node.view, 'draw_node', wraps=self.node.view.draw_node) as draw:
            QTest.mousePress(view.viewport(), QtCore.Qt.LeftButton, pos=start)
            QTest.mouseMove(view.viewport(), QtCore.QPoint((start.x()+end.x())//2, (start.y()+end.y())//2))
            self.settle()
            QTest.mouseRelease(view.viewport(), QtCore.Qt.LeftButton, pos=end)
            self.settle()
            self.assertGreater(self.node.get_property('graph_config')['linear_a'], .5)
            self.assertEqual(self.window.properties.node_id, other.id)
            self.assertEqual(self.window.graph.undo_stack().count(), 1)
            self.assertEqual((self.node.view.width, self.node.view.height), before_size)
            draw.assert_not_called()
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(plot.config['linear_a'], 0)

    def test_live_output_tree_modifiers_disconnect_and_parameter_undo(self):
        source = self.window.graph.create_node('NoodleS.Math.RangeNode')
        source.set_property('steps', 4)
        source.outputs()['R'].connect_to(self.node.inputs()['V'])
        self.window.graph.clear_selection()
        self.node.set_selected(True)
        self.set_curve('Power', power_exponent=2)
        output = self.window.evaluation.results[self.node.id].outputs
        self.assertEqual(output['R'].values(), (0, .0625, .25, .5625, 1))
        panel = self.window.properties.math_properties
        for mode in ('graft', 'flatten', 'flatten'):
            QTest.mouseClick(panel.modifiers['V'].buttons[mode], QtCore.Qt.LeftButton)
            self.settle()
        self.assertEqual(self.node.get_property('tree_modes'), {})
        self.assertIs(panel.stacks['V'].currentWidget(), panel.previews['V'])
        source.outputs()['R'].clear_connections()
        self.settle()
        self.assertEqual(self.window.evaluation.results[self.node.id].outputs, {})
        self.assertTrue(self.window.evaluation.results[self.node.id].error)
        self.assertTrue(self.controls().isVisible())

    def test_final_release_position_and_return_to_start_do_not_lose_edits(self):
        plot = self.controls().plot
        stack = self.window.graph.undo_stack()
        stack.clear()
        QTest.mousePress(plot, QtCore.Qt.LeftButton, pos=plot._px(0, 0).toPoint())
        QTest.mouseRelease(plot, QtCore.Qt.LeftButton, pos=plot._px(0, .5).toPoint())
        self.settle()
        self.assertAlmostEqual(self.node.get_property('graph_config')['linear_a'], .5, delta=.01)
        self.assertEqual(stack.count(), 1)
        stack.undo()
        self.settle()
        stack.clear()
        QTest.mousePress(plot, QtCore.Qt.LeftButton, pos=plot._px(0, 0).toPoint())
        QTest.mouseMove(plot, plot._px(0, .5).toPoint())
        self.settle()
        QTest.mouseRelease(plot, QtCore.Qt.LeftButton, pos=plot._px(0, 0).toPoint())
        self.settle()
        self.assertEqual(stack.count(), 0)
        self.assertTrue(stack.isClean())

    def test_canvas_context_menu_selects_function_without_graph_menu(self):
        other = self.window.add_node('NoodleS.Geometry.PointNode')
        self.node.set_pos(0, 0)
        other.set_pos(240, 125)
        self.window.graph.set_zoom(0)
        self.window.graph.center_on([self.node, other])
        self.settle()
        proxy = self.node.get_widget('graph_config')
        plot = proxy.plot
        view = self.window.graph.viewer()
        local = plot.mapTo(proxy.widget(), plot._px(.5, .5).toPoint())
        pos = view.mapFromScene(proxy.mapToScene(QtCore.QPointF(local)))
        seen = []
        popup_layer = []

        def choose():
            popup = next((w for w in self.app.allWidgets() if isinstance(w, QtWidgets.QMenu)
                          and w.objectName() == 'GraphMapperCurveMenu' and w.isVisible()), None)
            if popup is None:
                seen.append('No curve menu')
                return
            popup_layer.append((popup is self.app.activePopupWidget(), popup.graphicsProxyWidget()))
            seen.extend(action.text() for action in popup.actions())
            action = next((action for action in popup.actions() if action.text() == 'Gaussian'), None)
            if action:
                QTest.mouseClick(popup, QtCore.Qt.LeftButton, pos=popup.actionGeometry(action).center())
            popup.close()
        QtCore.QTimer.singleShot(25, choose)
        def close_leftover_menu():
            for popup in self.app.allWidgets():
                if isinstance(popup, QtWidgets.QMenu) and popup.isVisible():
                    seen.append('Unexpected second menu')
                    popup.close()
        fallback = QtCore.QTimer(self.window)
        fallback.setSingleShot(True)
        fallback.timeout.connect(close_leftover_menu)
        fallback.start(250)
        event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, pos, view.viewport().mapToGlobal(pos))
        self.app.sendEvent(view.viewport(), event)
        fallback.stop()
        self.settle()
        self.assertEqual(popup_layer, [(True, None)])
        self.assertIn('Gaussian', seen)
        self.assertNotIn('Unexpected second menu', seen)
        self.assertEqual(self.node.get_property('graph_config')['kind'], 'Gaussian')
        self.assertEqual(self.window.properties.node_id, other.id)

    def test_save_reload_each_function_and_reject_invalid_graph_config(self):
        source = self.window.graph.create_node('NoodleS.Inputs.NumberNode')
        source.set_property('value', .25)
        source.outputs()['Number'].connect_to(self.node.inputs()['V'])
        watch = self.window.graph.create_node('NoodleS.Data.WatchNode')
        self.node.outputs()['R'].connect_to(watch.inputs()['Value'])
        for kind in KINDS:
            self.node.set_property('graph_config', normalize_config({'kind': kind, 'flip_x': True, 'reverse': True}))
            self.node.set_property('tree_modes', {'O': 'graft'})
            self.window.evaluate_now()
            before = self.window.evaluation.results[self.node.id].outputs
            session = self.window.graph.serialize_session()
            with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
                path = Path(folder) / 'graph-mapper.noodles'
                write_document(path, session)
                clean = read_document(path, self.window.node_ports)
            self.window.load_session(clean)
            self.node = next(n for n in self.window.graph.all_nodes() if n.OPERATION == 'graph_mapper')
            self.window.evaluate_now()
            self.assertEqual(self.window.evaluation.results[self.node.id].outputs, before)
            self.assertEqual(self.node.get_widget('graph_config').get_value(), self.node.get_property('graph_config'))
        record = next(record for record in session['nodes'].values() if record['type_'].endswith('.GraphMapperNode'))
        for invalid in (None, {'kind': 'eval'}, {'gaussian_sigma': 0}, {'reverse': 1}):
            record['custom']['graph_config'] = invalid
            with self.assertRaises(DocumentError):
                validate_document({'format': 'NoodleS', 'schema_version': 1, 'session': session}, self.window.node_ports)


if __name__ == '__main__':
    unittest.main()
