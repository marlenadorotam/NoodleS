import unittest

from noodles.core import Connection, GraphEngine, NodeSpec


def ref(node, port="Number"):
    return Connection(node, port)


class GraphEngineTests(unittest.TestCase):
    def example(self, value=2):
        return [
            NodeSpec("a", "number", {"value": value}),
            NodeSpec("b", "number", {"value": 3}),
            NodeSpec("sum", "addition", inputs={"A": ref("a"), "B": ref("b")}),
            NodeSpec("watch", "watch", inputs={"Value": ref("sum", "R")}),
            NodeSpec("independent", "number", {"value": 99}),
        ]

    def test_topological_order_and_incremental_update(self):
        engine = GraphEngine()
        first = engine.evaluate(list(reversed(self.example())))
        self.assertEqual(first.results["watch"].outputs, {"Value": 5})
        unchanged = engine.evaluate(self.example())
        self.assertEqual(unchanged.computed, ())
        changed = engine.evaluate(self.example(8))
        self.assertEqual(set(changed.computed), {"a", "sum", "watch"})
        self.assertEqual(changed.results["watch"].outputs, {"Value": 11})

    def test_error_and_disconnect_clear_downstream_outputs(self):
        engine = GraphEngine()
        engine.evaluate(self.example())
        broken = engine.evaluate(self.example(float("nan")))
        self.assertTrue(broken.results["a"].error)
        self.assertEqual(broken.results["watch"].outputs, {})
        self.assertTrue(broken.results["watch"].blocked)
        self.assertEqual(engine.evaluate(self.example()).results["watch"].outputs, {"Value": 5})
        nodes = self.example()
        nodes[2] = NodeSpec("sum", "addition", inputs={"A": ref("a")})
        self.assertEqual(engine.evaluate(nodes).results["watch"].outputs, {})

    def test_cycles_report_failure_without_hiding_independent_results(self):
        nodes = [
            NodeSpec("a", "watch", inputs={"Value": ref("b", "Value")}),
            NodeSpec("b", "watch", inputs={"Value": ref("a", "Value")}),
            NodeSpec("c", "number", {"value": 7}),
        ]
        result = GraphEngine().evaluate(nodes)
        self.assertTrue(result.results["a"].blocked)
        self.assertEqual(result.results["c"].outputs, {"Number": 7})

    def test_disabled_source_invalidates_dependents(self):
        engine = GraphEngine()
        engine.evaluate(self.example())
        nodes = self.example()
        nodes[0] = NodeSpec("a", "number", {"value": 2}, disabled=True)
        result = engine.evaluate(nodes)
        self.assertTrue(result.results["watch"].blocked)
        self.assertFalse(result.results["watch"].outputs)

    def test_scalar_contract_does_not_flatten_lists_or_accept_boolean(self):
        for value in ([1, 2], True, "4", float("inf")):
            result = GraphEngine().evaluate([NodeSpec("a", "number", {"value": value})])
            self.assertTrue(result.results["a"].error)

    def test_multiple_inputs_can_share_one_parent(self):
        result = GraphEngine().evaluate([
            NodeSpec("n", "number", {"value": 4}),
            NodeSpec("p", "point", inputs={axis: ref("n") for axis in ("X", "Y", "Z")}),
        ])
        self.assertEqual(result.results["p"].outputs, {"Point": (4, 4, 4)})


if __name__ == "__main__":
    unittest.main()
