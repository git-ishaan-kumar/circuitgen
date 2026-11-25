"""Phase 6 tests: conservative, opt-in layout optimization."""

import copy
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from circuitgen.engine import (make_routed_svg_from_netlist, make_svg_from_netlist,
                    route_netlist, validate_model)
from circuitgen.optimization import assess_layout, choose_better_layout, compact_candidates
from circuitgen.routing import RoutingError, route_model

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def example(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class TestLayoutOptimization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simple = example('layout_optimization.json')
        cls.wheatstone = example('wheatstone.json')
        cls.rectifier = example('bridge_rectifier.json')
        cls.controller = example('controller.json')

    def test_reduces_whitespace_and_wire_length(self):
        before = route_netlist(self.simple)
        after = route_netlist(self.simple, optimize=True)
        qa = assess_layout(after)
        qb = assess_layout(before)
        self.assertLess(qa.footprint_area, qb.footprint_area)
        self.assertLess(qa.wire_length, qb.wire_length)
        self.assertLess(qa.score, qb.score)
        self.assertEqual(after.pin_to_net, before.pin_to_net)
        self.assertEqual(after.labels, before.labels)
        self.assertEqual(set(after.paths), set(before.paths))

    def test_optimized_svg_is_parseable_and_has_correct_parts(self):
        artwork = make_svg_from_netlist(self.simple, optimize=True)
        ET.fromstring(artwork)
        self.assertEqual(artwork.count('data-component="'), 3)
        self.assertNotIn('class="bg"', artwork)
        self.assertNotIn('class="guide"', artwork)

    def test_does_not_change_default_api(self):
        before = make_svg_from_netlist(self.simple)
        other = make_svg_from_netlist(self.simple, optimize=False)
        self.assertEqual(before, other)
        self.assertNotEqual(before, make_svg_from_netlist(self.simple, optimize=True))

    def test_traditional_diamonds_unchanged_even_when_opted_in(self):
        for raw in (self.wheatstone, self.rectifier):
            with self.subTest(kind=raw['components'][0]['type']):
                self.assertEqual(make_svg_from_netlist(raw),
                                 make_svg_from_netlist(raw, optimize=True))
                self.assertEqual(make_routed_svg_from_netlist(raw),
                                 make_routed_svg_from_netlist(raw, optimize=True))

    def test_controller_optimization_preserves_wired_nets(self):
        model = validate_model(self.controller)
        before = route_model(model)
        after = route_model(model, optimize=True)
        self.assertEqual(after.pin_to_net, before.pin_to_net)
        self.assertEqual(after.labels, ())
        self.assertTrue(all(after.paths.values()))

    def test_optimize_order_independent(self):
        altered = copy.deepcopy(self.simple)
        altered['components'].reverse()
        altered['nets'].reverse()
        for n in altered['nets']:
            n['pins'].reverse()
        self.assertEqual(make_svg_from_netlist(self.simple, optimize=True),
                         make_svg_from_netlist(altered, optimize=True))

    def test_invalid_trial_is_ignored(self):
        model = validate_model(self.simple)
        baseline = route_model(model)
        def fail(model, placement):
            raise RoutingError('intentionally failed candidate')
        self.assertIs(choose_better_layout(model, baseline, fail), baseline)

    def test_max_trials_zero_keeps_baseline(self):
        model = validate_model(self.simple)
        baseline = route_model(model)
        self.assertIs(choose_better_layout(model, baseline, lambda m,p: None,
                                           max_trials=0), baseline)

    def test_score_never_increases(self):
        for raw in (self.simple, self.controller):
            with self.subTest(example=raw['components'][0]['id']):
                self.assertLessEqual(assess_layout(route_netlist(raw, optimize=True)).score,
                                     assess_layout(route_netlist(raw)).score)

    def test_counters_are_nonnegative(self):
        quality = assess_layout(route_netlist(self.simple))
        self.assertGreater(quality.footprint_area, 0)
        self.assertGreater(quality.wire_length, 0)
        self.assertGreaterEqual(quality.bends, 0)
        self.assertGreaterEqual(quality.named_endpoints, 0)


if __name__ == '__main__':
    unittest.main()
