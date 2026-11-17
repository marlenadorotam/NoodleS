"""Typed movement and source ownership: whole grid, points, edges and copies."""
import unittest
import uuid
from noodles.core import GraphEngine,NodeSpec,Connection
from noodles.backend.moves import normalize_move_state,GridEditValue,TranslatedValue
from noodles.backend.grids import normalize_grid_state
from noodles.backend.datatree import Branch,DataTree
from noodles.backend.arithmetic import VectorValue
from noodles.backend.point import object_from_wire

PROJECT='af96bbf5-d242-4876-bebb-15d8de7a8991'


def state(operation,parameters=None,tree_modes=None):
    return normalize_move_state(operation,{'project_uuid':PROJECT,'node_uuid':str(uuid.uuid4()),
        'parameters':parameters or {},'tree_modes':tree_modes or {}})


def grid():
    return NodeSpec('grid','grid_rectangle',normalize_grid_state('grid_rectangle',{
        'project_uuid':PROJECT,'node_uuid':str(uuid.uuid4()),'parameters':{'Ex':2,'Ey':1}}))


def move(port='P',z=5,operation='move'):
    return NodeSpec('move',operation,state(operation,{'Z':z} if operation=='move' else {'T':[0,0,z]}),{'G':Connection('grid',port)})


class MoveDataTests(unittest.TestCase):
    def evaluate(self,*nodes):
        result=GraphEngine().evaluate(list(nodes))
        for node in nodes:
            self.assertIsNone(result.results[node.id].error,result.results[node.id].error)
        return result

    def test_points_are_typed_and_modify_only_original_grid_points(self):
        result=self.evaluate(grid(),move())
        source,moved=result.results['grid'],result.results['move']
        self.assertIsNone(moved.parametric_object)
        self.assertEqual(moved.outputs['Count'],6)
        self.assertTrue(all(p.xyz[2]==5 for p in moved.outputs['G'].values()))
        value=source.parametric_object.parts.values()[0]
        self.assertIsInstance(value,GridEditValue)
        self.assertEqual({kind for kind,_,_ in value.edits},{'point'})
        self.assertEqual(source.outputs['P'].values()[0].xyz[2],0)
        self.assertEqual(object_from_wire(source.parametric_object.to_wire()),source.parametric_object)

    def test_whole_grid_and_cell_boundaries_have_distinct_effects(self):
        result=self.evaluate(grid(),move('G'))
        value=result.results['grid'].parametric_object.parts.values()[0]
        self.assertIsInstance(value,TranslatedValue)
        self.assertEqual(value.vector,(0,0,5))
        for port in ('C','E'):
            result=self.evaluate(grid(),move(port))
            value=result.results['grid'].parametric_object.parts.values()[0]
            self.assertEqual({kind for kind,_,_ in value.edits},{'edge'})
            self.assertEqual(len(value.edits),7)

    def test_move_gh_owns_copies_without_modifying_the_grid(self):
        source=grid()
        result=self.evaluate(source,move(operation='move_gh'))
        self.assertEqual(result.results['grid'].parametric_object.kind,'grids')
        owner=result.results['move'].parametric_object
        self.assertIsNotNone(owner)
        self.assertEqual(owner.parts.count,6)
        self.assertNotEqual(owner.node_uuid,source.parameters['node_uuid'])
        self.assertEqual(object_from_wire(owner.to_wire()),owner)
        transform=result.results['move'].outputs['X'].values()[0]
        self.assertEqual(transform.matrix[2],(0.,0.,1.,5))

    def test_chained_move_composes_without_accumulation_and_removal_restores_base(self):
        source,first=grid(),move()
        second=NodeSpec('second','move',state('move',{'Z':3}),{'G':Connection('move','G')})
        engine=GraphEngine()
        for _ in range(3):
            result=engine.evaluate([source,first,second])
            self.assertFalse(result.frozen_owners)
            self.assertTrue(all(v==(0,0,8) for _,_,v in result.results['grid'].parametric_object.parts.values()[0].edits))
            self.assertTrue(all(p.xyz[2]==8 for p in result.results['second'].outputs['G'].values()))
        restored=engine.evaluate([source])
        self.assertEqual(restored.results['grid'].parametric_object.kind,'grids')

    def test_distinct_point_vectors_keep_tree_paths_and_shared_edge_conflict_is_explicit(self):
        source=grid()
        # Backend contracts below exercise list values directly with bound grid data.
        base=GraphEngine().evaluate([source]).results['grid']
        from noodles.backend.moves import evaluate_move
        xyz=DataTree((Branch((0,),tuple(range(3))),Branch((1,),tuple(range(3,6)))))
        outputs,_,_,effects=evaluate_move('move',state('move'),{'G':base.outputs['P'],'Z':xyz},base.bindings['P'],'m')
        self.assertEqual([p.xyz[2] for p in outputs['G'].values()],list(range(6)))
        self.assertEqual([b.path for b in outputs['G'].branches],[(0,),(1,)])
        # Two neighbouring cells cannot put their shared edge in two positions.
        cells=move('C')
        other=NodeSpec('other','move',state('move',{'Z':9}),{'G':Connection('grid','C')})
        result=GraphEngine().evaluate([source,cells,other])
        self.assertIn('grid',result.frozen_owners)
        self.assertIn('Conflicting',result.results['move'].error)

    def test_vector_tree_replaces_xyz_and_preserves_point_bindings(self):
        from noodles.backend.moves import evaluate_move
        base = GraphEngine().evaluate([grid()]).results['grid']
        vectors = DataTree(tuple(Branch((row,), tuple(VectorValue((0, 0, 3*row + i))
                                                     for i in range(3))) for row in range(2)))
        outputs, model, _, effects = evaluate_move('move', state('move', {'Z': 90}),
            {'G': base.outputs['P'], 'T': vectors, 'Z': 'ignored'}, base.bindings['P'], 'move')
        self.assertIsNone(model)
        self.assertEqual([p.xyz[2] for p in outputs['G'].values()], list(range(6)))
        self.assertEqual([b.path for b in outputs['G'].branches], [(0,), (1,)])
        self.assertTrue(all(effect.owner == 'grid' for effect in effects))

    def test_connected_vector_ignores_invalid_axis_source_and_respects_local_axes(self):
        from noodles.backend.curves import PlaneValue, circle
        from noodles.backend.moves import evaluate_move
        vector = VectorValue((2, 0, 0))
        surface_frame = PlaneValue((0, 0, 0), (0, 1, 0), (0, 0, 1))
        curve = circle('circle', (0, 0, 0), 5, surface_frame)
        outputs, *_ = evaluate_move('move', state('move', {'W': False}), {'G': curve, 'T': vector})
        self.assertEqual(outputs['G'].values()[0].frame.origin, (0, 2, 0))
        source = grid()
        driver = NodeSpec('vector', 'vector', {'x': 0., 'y': 0., 'z': 4.})
        bad = NodeSpec('bad', 'unknown', {})
        moving = NodeSpec('move', 'move', state('move'), {'G': Connection('grid', 'P'),
            'T': Connection('vector', 'Vector'), 'Z': Connection('bad', 'Number')})
        results = GraphEngine().evaluate([source, driver, bad, moving]).results
        self.assertIsNone(results['move'].error)
        self.assertTrue(all(p.xyz[2] == 4 for p in results['move'].outputs['G'].values()))

    def test_one_shared_point_multiple_positions_freezes_source_before_publication(self):
        source=grid()
        from noodles.backend.moves import evaluate_move,MoveConflict
        base=GraphEngine().evaluate([source]).results['grid']
        point=base.outputs['P'].values()[0]
        with self.assertRaises(MoveConflict):
            evaluate_move('move',state('move'),{'G':point,'Z':[1,2]},base.bindings['P'],'m')

    def test_bad_parameter_freezes_owner_but_disabling_move_restores_the_base(self):
        source=grid()
        bad=move()
        data=NodeSpec('bad','number',{'value':float('nan')})
        bad=NodeSpec(bad.id,bad.operation,bad.parameters,{**bad.inputs,'Z':Connection('bad','Number')})
        result=GraphEngine().evaluate([source,data,bad])
        self.assertTrue(result.results['move'].error)
        self.assertIn('grid',result.frozen_owners)
        disabled=NodeSpec(bad.id,bad.operation,bad.parameters,bad.inputs,True)
        result=GraphEngine().evaluate([source,disabled])
        self.assertFalse(result.frozen_owners)
        self.assertEqual(result.results['grid'].parametric_object.kind,'grids')
