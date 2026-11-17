"""Real Qt edits preserve ownership, expose copies and keep graph serialization valid."""
import tempfile
from pathlib import Path
import unittest
from Qt import QtCore
from PySide6.QtTest import QTest
import test_operations as fixture
from noodles.document import write_document,read_document


class MoveUiTests(unittest.TestCase):
    setUpClass=classmethod(fixture.OperationPropertiesTests.setUpClass.__func__)
    setUp=fixture.OperationPropertiesTests.setUp
    tearDown=fixture.OperationPropertiesTests.tearDown
    settle=fixture.OperationPropertiesTests.settle

    def test_vector_connection_replaces_axis_editor_and_disconnect_restores_it(self):
        grid = self.window.add_node('NoodleS.Geometry.GridRectangleNode')
        vector = self.window.add_node('NoodleS.Math.VectorNode')
        vector.set_property('z', 4)
        moving = self.window.add_node('NoodleS.Geometry.MoveNode')
        moving.set_property('parameters', {'Z': 7})
        grid.outputs()['P'].connect_to(moving.inputs()['G'])
        vector.outputs()['Vector'].connect_to(moving.inputs()['T'])
        self.settle()
        panel = self.window.properties.curve_properties
        self.assertIs(panel.stacks['Z'].currentWidget(), panel.previews['Z'])
        self.assertEqual(panel.previews['Z'].text(), 'Controlled by T')
        self.assertTrue(all(p.xyz[2] == 4 for p in self.window.evaluation.results[moving.id].outputs['G'].values()))
        moving.inputs()['T'].clear_connections()
        self.settle()
        self.assertIs(panel.stacks['Z'].currentWidget(), panel.stacks['Z'].widget(0))
        self.assertTrue(all(p.xyz[2] == 7 for p in self.window.evaluation.results[moving.id].outputs['G'].values()))

    def test_real_height_edit_undo_tree_buttons_copy_and_saved_graph(self):
        grid=self.window.add_node('NoodleS.Geometry.GridRectangleNode')
        grid.set_property('parameters',{**grid.get_property('parameters'),'Ex':2,'Ey':1})
        moving=self.window.add_node('NoodleS.Geometry.MoveNode')
        grid.outputs()['P'].connect_to(moving.inputs()['G'])
        self.settle()
        panel=self.window.properties.curve_properties
        editor=panel.editors['Z'][0]
        editor.setFocus()
        QTest.keyClick(editor,QtCore.Qt.Key_A,QtCore.Qt.ControlModifier)
        QTest.keyClicks(editor,'7')
        QTest.keyClick(editor,QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(moving.get_property('parameters')['Z'],7)
        result=self.window.evaluation.results[moving.id]
        self.assertIsNone(result.error)
        self.assertTrue(all(p.xyz[2]==7 for p in result.outputs['G'].values()))
        self.assertIn(grid.id,self.window.point_service.models)
        self.assertNotIn(moving.id,self.window.point_service.models)
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertTrue(all(p.xyz[2]==0 for p in self.window.evaluation.results[moving.id].outputs['G'].values()))
        QTest.mouseClick(panel.modifiers['G'].buttons['flatten'],QtCore.Qt.LeftButton)
        self.settle()
        self.assertEqual(moving.get_property('tree_modes'),{'G':'flatten'})
        gh=self.window.add_node('NoodleS.Geometry.MoveGHNode')
        grid.outputs()['P'].connect_to(gh.inputs()['G'])
        self.settle()
        self.assertIn(gh.id,self.window.point_service.models)
        self.assertEqual(self.window.point_service.models[gh.id]['model']['node_uuid'],gh.get_property('node_uuid'))
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path=Path(folder)/'moves.noodles'
            write_document(path,self.window.graph.serialize_session())
            loaded=read_document(path,self.window.node_ports)
            self.assertEqual(len(loaded['nodes']),3)
