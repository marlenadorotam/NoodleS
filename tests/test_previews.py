"""Vector preview data, real Properties events and viewport-only lifecycle."""
import copy
import math
import unittest
from Qt import QtCore
from PySide6.QtTest import QTest
import test_curves as ui_fixture
from test_curves import PROJECT,NODE
from noodles.backend.previews import normalize_preview_state,evaluate_preview,preview_payload
from noodles.backend.arithmetic import VectorValue
from noodles.backend.point import PointValue
from noodles.backend.datatree import Branch,DataTree
from noodles.backend.domain import DomainValue
from noodles.core import GraphEngine,NodeSpec,Connection,compute


def state(**changes):
    return normalize_preview_state('vector_preview',{'project_uuid':PROJECT,'node_uuid':NODE,**changes})


class AnnotationDataTests(unittest.TestCase):
    def test_gradient_uses_global_bounds_and_preserves_branches(self):
        values = DataTree((Branch((2,), (10., 15.), ('left', 'mid')), Branch((3,), (20.,)), Branch((4,), ())))
        result = compute('gradient', {}, {'V': values, 'A': '#000000', 'M': '#808080', 'B': '#FFFFFF'})
        self.assertEqual(tuple(map(str, result['C'].values())), ('#000000', '#808080', '#FFFFFF'))
        self.assertEqual([b.path for b in result['C'].branches], [(2,), (3,), (4,)])
        self.assertEqual(result['C'].branches[0].keys, ('left', 'mid'))
        self.assertEqual(result['D'].values(), (DomainValue(10, 20),)*3)
        reversed_colors = compute('gradient', {}, {'V': [-1., 0., 1., 2.], 'D': DomainValue(1, 0)})
        self.assertEqual(tuple(map(str, reversed_colors['C'].values())), ('#F0AC50', '#F0AC50', '#3889C7', '#3889C7'))
        flat = compute('gradient', {}, {'V': [5, 5]})['C']
        self.assertEqual(tuple(map(str, flat.values())), ('#73D2B6', '#73D2B6'))

    def test_text_tags_and_dimensions_accept_typed_colors_and_keep_data_when_hidden(self):
        anchors = DataTree((Branch((5,), (PointValue('a', (0, 0, 0)), PointValue('b', (3, 4, 12)))),))
        colors = compute('gradient', {}, {'V': DataTree((Branch((5,), (1, 2)),))})['C']
        tags = evaluate_preview('text_tag', state(), {'P': anchors, 'T': [1, 2], 'C': colors, 'S': False})
        self.assertEqual(tags['T'].branches[0].path, (5,))
        self.assertEqual(tags['T'].values(), ('1', '2'))
        self.assertEqual([item.color for item in tags['_preview'].values()], list(colors.values()))
        self.assertTrue(all(not item.visible for item in tags['_preview'].values()))
        a, b = anchors.values()
        dimension = evaluate_preview('dimension', state(), {'A': a, 'B': b, 'O': VectorValue((0, 10, 0)), 'T': 'Span'})
        self.assertEqual(dimension['L'].values(), (13.,))
        item, = dimension['_preview'].values()
        self.assertEqual(item.text, 'Span')
        self.assertAlmostEqual(math.dist(*item.points[2:]), 13.)
        with self.assertRaisesRegex(ValueError, '160 characters'):
            evaluate_preview('text_tag', state(), {'P': a, 'T': 'x'*161})


class VectorPreviewDataTests(unittest.TestCase):
    def test_independent_origin_vector_length_and_no_parametric_geometry(self):
        out=evaluate_preview('vector_preview',state(parameters={'O':[10,20,30]}),{'V':VectorValue((3,4,0))})
        self.assertEqual(out['V'].values(),(VectorValue((3,4,0)),))
        self.assertEqual(out['L'].values(),(5,))
        self.assertEqual(out['_preview'].values()[0].origin,(10,20,30))
        engine=GraphEngine()
        result=engine.evaluate([NodeSpec('v','unit_x'),NodeSpec('p','vector_preview',state(),{'V':Connection('v','V')})])
        self.assertIsNone(result.results['p'].parametric_object)
        self.assertFalse(result.results['p'].error)

    def test_tree_slots_graft_flatten_keys_empty_and_visible(self):
        values=[VectorValue((1,0,0)),VectorValue((0,2,0))]
        flat=evaluate_preview('vector_preview',state(),{'V':values})
        graft=evaluate_preview('vector_preview',state(tree_modes={'V':'graft'}),{'V':values})
        self.assertEqual([b.path for b in graft['V'].branches],[(0,0),(0,1)])
        self.assertEqual(flat['L'].values(),graft['L'].values())
        self.assertEqual(tuple(v.key for v in flat['_preview'].values()),tuple(v.key for v in graft['_preview'].values()))
        hidden=evaluate_preview('vector_preview',state(),{'V':values,'S':False})
        self.assertFalse(any(v.visible for v in hidden['_preview'].values()))
        self.assertEqual(hidden['V'],flat['V'])
        self.assertEqual(evaluate_preview('vector_preview',state(),{'V':[]})['Count'],0)
        self.assertEqual(len(preview_payload(state(),graft)['items']),2)

    def test_invalid_vector_zero_tip_limits_and_ambiguous_lists(self):
        for vector in ((1,2,3),[1,2,3],PointValue('p',(1,2,3)),VectorValue((0,0,0)),VectorValue((1e10,0,0))):
            with self.subTest(vector=vector),self.assertRaises(ValueError):
                evaluate_preview('vector_preview',state(),{'V':vector})
        with self.assertRaisesRegex(ValueError,'256'):
            evaluate_preview('vector_preview',state(),{'V':[VectorValue((1,0,0))]*257})
        with self.assertRaisesRegex(ValueError,'equal lengths'):
            evaluate_preview('vector_preview',state(),{'V':[VectorValue((1,0,0))]*2,
                'O':[PointValue(str(i),(i,0,0)) for i in range(3)]})


class VectorPreviewUiTests(unittest.TestCase):
    setUpClass=classmethod(ui_fixture.CurveWindowTests.setUpClass.__func__)
    setUp=ui_fixture.CurveWindowTests.setUp
    tearDown=ui_fixture.CurveWindowTests.tearDown
    settle=ui_fixture.CurveWindowTests.settle

    def test_gradient_color_picker_edits_and_undoes_stored_stop(self):
        from unittest.mock import patch
        from Qt import QtGui, QtWidgets

        node = self.window.add_node('NoodleS.Math.GradientNode')
        self.settle()
        button = self.window.properties.curve_properties.editors['A'][0]
        self.assertEqual(button.text(), '#3889C7')
        with patch.object(QtWidgets.QColorDialog, 'getColor', return_value=QtGui.QColor('#ff5319')):
            QTest.mouseClick(button, QtCore.Qt.LeftButton)
        self.settle()
        self.assertEqual(button.text(), '#FF5319')
        self.assertEqual(node.get_property('parameters')['A'], '#FF5319')
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(button.text(), '#3889C7')

    def test_older_bridge_keeps_vector_previews_when_annotations_are_unsupported(self):
        self.window._annotation_preview_supported = False
        source = self.window.add_node('NoodleS.Math.UnitXNode')
        vector = self.window.add_node('NoodleS.Geometry.VectorPreviewNode')
        source.outputs()['V'].connect_to(vector.inputs()['V'])
        point = self.window.add_node('NoodleS.Geometry.PointNode')
        tag = self.window.add_node('NoodleS.VisualHelpers.TextTagNode')
        point.outputs()['P'].connect_to(tag.inputs()['P'])
        self.settle()
        self.assertIn(vector.id, self.window.preview_service.nodes)
        self.assertNotIn(tag.id, self.window.preview_service.nodes)
        self.assertIn('noodlesrefresh', tag.scene_status)

    def test_real_visible_checkbox_tree_toggle_delete_undo_never_queues_cad_model(self):
        source=self.window.add_node('NoodleS.Math.UnitXNode')
        node=self.window.add_node('NoodleS.Geometry.VectorPreviewNode')
        source.outputs()['V'].connect_to(node.inputs()['V'])
        self.settle()
        panel=self.window.properties.curve_properties
        self.assertTrue(panel.source_modes.isHidden())
        self.assertIn(node.id,self.window.preview_service.nodes)
        self.assertNotIn(node.id,self.window.point_service.models)
        visible=panel.editors['S'][0]
        QTest.mouseClick(visible,QtCore.Qt.LeftButton,pos=QtCore.QPoint(8,visible.height()//2))
        self.settle()
        self.assertFalse(node.get_property('parameters')['S'])
        self.assertFalse(self.window.preview_service.nodes[node.id]['items'][0]['visible'])
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertTrue(visible.isChecked())
        QTest.mouseClick(panel.modifiers['V'].buttons['graft'],QtCore.Qt.LeftButton)
        self.settle()
        self.assertEqual(node.get_property('tree_modes'),{'V':'graft'})
        node_id=node.id
        self.window.graph.delete_node(node)
        self.settle()
        self.assertNotIn(node_id,self.window.preview_service.nodes)
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertIn(node_id,self.window.preview_service.nodes)
        self.assertFalse(self.window.point_service.models)

    def test_document_roundtrip_and_new_document_clear_previews(self):
        node=self.window.add_node('NoodleS.Geometry.VectorPreviewNode')
        self.settle()
        session=self.window.graph.serialize_session()
        self.window.load_session(session)
        self.settle()
        self.assertEqual(len(self.window.graph.all_nodes()),1)
        self.window.graph.undo_stack().setClean()
        self.window.new_document()
        self.settle()
        self.assertFalse(self.window.preview_service.nodes)

    def test_plane_normal_and_plane_preview_properties_update_dimensions(self):
        normal = self.window.add_node('NoodleS.Math.PlaneNormalNode')
        preview = self.window.add_node('NoodleS.Geometry.PlanePreviewNode')
        normal.outputs()['P'].connect_to(preview.inputs()['P'])
        self.settle()
        self.assertIn(preview.id, self.window.preview_service.nodes)
        self.assertNotIn(preview.id, self.window.point_service.models)
        width = self.window.properties.curve_properties.editors['W'][0]
        width.setFocus()
        width.selectAll()
        QTest.keyClicks(width, '42')
        QTest.keyClick(width, QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(self.window.preview_service.nodes[preview.id]['items'][0]['width'], 42)

    def test_plane_normal_remains_editable_alongside_world_plane_presets(self):
        library = {name: kind for name, kind, _ in self.window.palette.node_entries()}
        for name, kind in (('Plane Normal', 'PlaneNormal'), ('Plane XY', 'XYPlane'),
                           ('Plane YZ', 'YZPlane'), ('Plane XZ', 'XZPlane')):
            self.assertEqual(library[name], f'NoodleS.Math.{kind}Node')

        normal = self.window.add_node(library['Plane Normal'])
        self.settle()
        result = lambda: self.window.evaluation.results[normal.id].outputs['P'].values()[0]
        self.assertEqual(result().normal, (0, 0, 1))

        vector = self.window.add_node('NoodleS.Math.VectorNode')
        vector.set_property('x', 2)
        vector.set_property('y', 3)
        vector.set_property('z', 6)
        vector.outputs()['Vector'].connect_to(normal.inputs()['Z'])
        self.settle()
        self.assertLess(math.dist(result().normal, (2/7, 3/7, 6/7)), 1e-12)
