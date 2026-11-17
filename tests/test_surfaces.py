"""Surface construction: explicit branch grouping, grid ordering and real Qt edits."""
import copy
import os
from pathlib import Path
import unittest
from Qt import QtCore
from PySide6.QtTest import QTest
import test_operations as fixture
from noodles.backend.operations import evaluate_operation,operation_from_wire,OperationValue
from noodles.backend.curves import line,circle,PlaneValue
from noodles.backend.point import PointValue
from noodles.backend.datatree import Branch,DataTree


def grid(u=4,v=3,fn=lambda x,y:(x,y,x*y)):
    return [PointValue(str(j*u+i),fn(i,j)) for j in range(v) for i in range(u)]


class SurfaceDataTests(unittest.TestCase):
    def value(self,op,data,**changes):
        return evaluate_operation(op,fixture.state(op,**changes),data)

    def test_surface_boundaries_are_grouped_per_branch_and_keep_paths(self):
        outer=circle('a',(0,0,0),10,PlaneValue())
        inner=circle('b',(0,0,0),3,PlaneValue())
        tree=DataTree((Branch((3,4),(outer,inner)),Branch((8,),(outer,))))
        out=self.value('planar_surface',{'C':tree})
        self.assertEqual(out['Count'],2)
        self.assertEqual([b.path for b in out['G'].branches],[(3,4),(8,)])
        self.assertEqual([len(v.sources) for v in out['G'].values()],[2,1])
        joined=self.value('planar_surface',{'C':DataTree((Branch((1,),(outer,)),Branch((2,),(inner,))))},tree_modes={'C':'flatten'})
        self.assertEqual(joined['Count'],1)
        self.assertEqual(len(joined['G'].values()[0].sources),2)
        for boundaries in ([],[outer]*2,[outer]*5):
            if not boundaries:
                self.assertEqual(self.value('edge_surface',{'C':[]})['Count'],0)
            else:
                with self.assertRaises(ValueError):
                    self.value('edge_surface',{'C':boundaries})

    def test_point_grid_roundtrip_branch_options_flatten_and_stable_key(self):
        points=grid()
        tree=DataTree((Branch((7,),tuple(points)),Branch((9,),tuple(grid(3,4)))))
        u=DataTree((Branch((7,),(4,)),Branch((9,),(3,))))
        out=self.value('surface_from_points',{'P':tree,'U':u})
        self.assertEqual(out['Count'],2)
        self.assertEqual(out['U'].values(),(4,3))
        self.assertEqual(out['V'].values(),(3,4))
        value=out['G'].values()[0]
        self.assertEqual(value.points,tuple(p.xyz for p in points))
        self.assertEqual(operation_from_wire(value.to_wire()),value)
        changed=self.value('surface_from_points',{'P':DataTree((Branch((7,),tuple(grid(fn=lambda x,y:(x,y,2*x*y)))),)),
            'U':DataTree((Branch((7,),(4,)),))})['G'].values()[0]
        self.assertEqual(changed.key,value.key)
        rows=DataTree(tuple(Branch((j,),tuple(points[4*j:4*j+4])) for j in range(3)))
        flat=self.value('surface_from_points',{'P':rows,'U':4},tree_modes={'P':'flatten'})
        self.assertEqual(flat['Count'],1)
        with self.assertRaises(ValueError):
            self.value('surface_from_points',{'P':points,'U':4},tree_modes={'P':'graft'})

    def test_invalid_grid_size_noninteger_u_mismatched_options_and_wire_budget(self):
        for u in (1,5,12,2.1,True,float('inf')):
            with self.subTest(u=u),self.assertRaises(ValueError):
                self.value('surface_from_points',{'P':grid(),'U':u})
        for data in ({'P':grid(),'U':[3,4]}, {'P':grid(),'U':DataTree((Branch((5,),(3,)),Branch((6,),(4,))))},
                     {'P':[(0,0,0)]*4}, {'P':grid(51,50),'U':51}):
            with self.assertRaises(ValueError):
                self.value('surface_from_points',data)
        recipe=self.value('surface_from_points',{'P':grid(),'U':4})['G'].values()[0].to_wire()
        bad=copy.deepcopy(recipe)
        bad['points'][0]=[float('nan'),0,0]
        with self.assertRaises(ValueError):
            operation_from_wire(bad)
        with self.assertRaisesRegex(ValueError,'budget'):
            operation_from_wire(recipe,budget=[5])
        with self.assertRaises(ValueError):
            OperationValue('bad','edge_surface',(),points=((0,0,0),))

    def test_auto_u_reads_rows_before_flatten_and_respects_explicit_width(self):
        def row_tree(u, v):
            points = grid(u, v, lambda x, y: (x, y, x*x - y*y))
            return DataTree(tuple(Branch((0, row), tuple(points[row*u:(row+1)*u])) for row in range(v)))

        for u, v in ((11, 17), (13, 17)):
            points = row_tree(u, v)
            out = self.value('surface_from_points', {'P': points}, tree_modes={'P': 'flatten'})
            self.assertEqual(out['Count'], 1)
            self.assertEqual(out['U'].values(), (u,))
            self.assertEqual(out['V'].values(), (v,))
            self.assertEqual(out['G'].values()[0].points, tuple(point.xyz for point in points.values()))
        points = row_tree(4, 3)
        for inputs, changes in (({'P': points, 'U': 3}, {}), ({'P': points}, {'parameters': {'U': 3}})):
            out = self.value('surface_from_points', inputs, tree_modes={'P': 'flatten'}, **changes)
            self.assertEqual(out['U'].values(), (3,))
        for ambiguous in (points.values(), DataTree(tuple(reversed(points.branches))),
                          DataTree((points.branches[0], Branch((0, 1), points.branches[1].items[:2])))):
            with self.assertRaisesRegex(ValueError, 'Auto U'):
                self.value('surface_from_points', {'P': ambiguous}, tree_modes={'P': 'flatten'})
        with self.assertRaisesRegex(ValueError, 'Auto U'):
            self.value('surface_from_points', {'P': points})

    def test_periodic_u_recipe_roundtrip_keeps_auto_row_width(self):
        points = grid(7, 3)
        rows = DataTree(tuple(Branch((0, j), points[j*7:(j+1)*7]) for j in range(3)))
        output = self.value('surface_from_points', {'P': rows}, tree_modes={'P': 'flatten'},
                            parameters={'periodic_u': True})
        part, = output['G'].values()
        self.assertTrue(part.periodic_u)
        self.assertEqual(part.u_count, 7)
        self.assertEqual(operation_from_wire(part.to_wire()), part)
        with self.assertRaisesRegex(ValueError, 'Points per Row'):
            self.value('surface_from_points', {'P': grid(3, 3), 'U': 3}, parameters={'periodic_u': True})


class SurfacePropertiesTests(unittest.TestCase):
    setUpClass=classmethod(fixture.OperationPropertiesTests.setUpClass.__func__)
    setUp=fixture.OperationPropertiesTests.setUp
    tearDown=fixture.OperationPropertiesTests.tearDown
    settle=fixture.OperationPropertiesTests.settle

    def test_surface_and_slider_fit_minimum_properties_width(self):
        from Qt import QtGui, QtWidgets

        if windows := os.environ.get("WINDIR"):
            for name in ("segoeui.ttf", "segoeuib.ttf"):
                QtGui.QFontDatabase.addApplicationFont(str(Path(windows) / "Fonts" / name))
        self.window.show()
        self.window.splitter.setSizes([205, 850, 290])
        surface = self.window.add_node('NoodleS.Geometry.SurfaceFromPointsNode')
        point = self.window.add_node('NoodleS.Geometry.PointNode')
        point.outputs()['P'].connect_to(surface.inputs()['P'])
        surface.set_selected(True)
        point.set_selected(False)
        self.settle()
        inspector = self.window.properties
        scroll = inspector.findChild(QtWidgets.QScrollArea, 'InspectorScroll')
        self.assertEqual(self.window.properties_panel.width(), 290)
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        surface_preview = inspector.curve_properties.previews['P']
        self.assertTrue(surface_preview.isVisible())
        self.assertTrue(surface_preview.wordWrap())

        self.window.add_node('NoodleS.Inputs.SliderNode')
        self.settle()
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        name_left = inspector.name_edit.mapToGlobal(QtCore.QPoint(0, 0)).x()
        name_width = inspector.name_edit.width()
        for editor in (inspector.min_edit, inspector.max_edit, inspector.value_edit):
            field_label = next(label for label in inspector.findChildren(QtWidgets.QLabel)
                               if label.buddy() is editor)
            self.assertTrue(field_label.isVisible())
            field_left = editor.mapToGlobal(QtCore.QPoint(0, 0)).x()
            self.assertEqual(field_left, name_left)
            self.assertEqual(editor.width(), name_width)
            self.assertAlmostEqual(field_label.mapToGlobal(field_label.rect().center()).y(),
                                   editor.mapToGlobal(editor.rect().center()).y(), delta=2)

    def test_u_editor_real_typing_undo_graft_and_library_category(self):
        node=self.window.add_node('NoodleS.Geometry.SurfaceFromPointsNode')
        self.settle()
        panel=self.window.properties.curve_properties
        self.assertFalse(panel.source_modes.isVisible())
        self.assertFalse(panel.periodic_u.isChecked())
        QTest.mouseClick(panel.periodic_u, QtCore.Qt.LeftButton,
                         pos=QtCore.QPoint(8, panel.periodic_u.height()//2))
        self.settle()
        self.assertTrue(node.get_property('parameters')['periodic_u'])
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertFalse(panel.periodic_u.isChecked())
        editor=panel.editors['U'][0]
        self.assertTrue(panel.auto_u.isChecked())
        QTest.mouseClick(panel.auto_u, QtCore.Qt.LeftButton, pos=QtCore.QPoint(8, panel.auto_u.height()//2))
        self.settle()
        editor.setFocus()
        QTest.keyClick(editor,QtCore.Qt.Key_A,QtCore.Qt.ControlModifier)
        QTest.keyClicks(editor,'4')
        QTest.keyClick(editor,QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(node.get_property('parameters')['U'],4)
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(editor.value(),2)
        QTest.mouseClick(panel.modifiers['P'].buttons['flatten'],QtCore.Qt.LeftButton)
        self.settle()
        self.assertEqual(node.get_property('tree_modes'),{'P':'flatten'})
        QTest.mouseClick(panel.modifiers['P'].buttons['flatten'],QtCore.Qt.LeftButton)
        self.settle()
        self.assertEqual(node.get_property('tree_modes'),{})
        library=self.window.palette
        root=library._category_items['NoodleS.Operations']
        from noodles.backend.operations import NATIVE_SCENE_SPECS, OPERATION_SPECS
        from noodles.backend.moves import MOVE_SPECS
        from noodles.backend.curve_sampling import SAMPLING_SPECS
        from noodles.backend.delaunay_node import TESSELLATION_SPECS
        from noodles.backend.surface_uv import SURFACE_UV_SPECS
        from noodles.backend.population import POPULATION_SPECS
        from noodles.backend.surface_structure import SPECS as STRUCTURE_SPECS
        from noodles.backend.mesh_nodes import MESH_SPECS
        from noodles.backend.mass_properties import MASS_SPECS
        from noodles.nodes import NODE_TYPES
        self.assertEqual({root.child(i).text(0) for i in range(root.childCount())},
                         {spec['name'] for spec in (*OPERATION_SPECS.values(), *NATIVE_SCENE_SPECS.values(), *MOVE_SPECS.values(),
                                                   *SAMPLING_SPECS.values(), *SURFACE_UV_SPECS.values(),
                                                   *POPULATION_SPECS.values(), *STRUCTURE_SPECS.values(),
                                                   *MASS_SPECS.values(), *TESSELLATION_SPECS.values())}
                         | {spec['name'] for spec in MESH_SPECS.values()
                            if 'NoodleS.Operations.' + spec['class'] in NODE_TYPES}
                         | {'Loft Options', 'Pull Point', 'Penrose P2', 'Plane Surface'})
