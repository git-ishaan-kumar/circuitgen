"""Conventional layouts activate only for exact matches of known topologies."""

import copy
import hashlib
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from circuitgen.engine import make_routed_svg_from_netlist, make_svg_from_netlist, validate_model
from circuitgen.motifs import match_rectifier, match_wheatstone, recognize_motif

ROOT = Path(__file__).resolve().parents[1]


def example(name):
    return json.loads((ROOT / 'examples' / name).read_text(encoding='utf-8'))


class TestHistoricMotifs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = example('wheatstone.json')
        cls.rectifier = example('bridge_rectifier.json')
        cls.controller = example('controller.json')

    def test_only_known_exact_patterns_match(self):
        self.assertEqual(recognize_motif(validate_model(self.bridge)), 'wheatstone_diamond')
        self.assertEqual(recognize_motif(validate_model(self.rectifier)), 'bridge_rectifier_diamond')
        self.assertIsNone(recognize_motif(validate_model(self.controller)))

    def test_both_diamond_outputs_are_valid_transparent_svg(self):
        for raw, motif in ((self.bridge, 'wheatstone_diamond'),
                           (self.rectifier, 'bridge_rectifier_diamond')):
            output = make_svg_from_netlist(raw)
            root = ET.fromstring(output)
            self.assertEqual(root.attrib['data-motif'], motif)
            self.assertNotIn('class="bg"', output)
            self.assertNotIn('class="guide"', output)
            self.assertEqual(output.count('data-component="'), 6)

    def test_wheatstone_has_four_junctions_and_four_nets(self):
        output = make_routed_svg_from_netlist(self.bridge)
        root = ET.fromstring(output)
        ns = {'svg': 'http://www.w3.org/2000/svg'}
        dots = root.findall('.//svg:circle[@class="junction"]', ns)
        self.assertEqual(len(dots), 4)
        for net in ('TOP', 'BOTTOM', 'LEFT_MID', 'RIGHT_MID'):
            self.assertIn(f'data-net="{net}"', output)

    def test_rectifier_diode_direction_is_checked(self):
        modified = copy.deepcopy(self.rectifier)
        for net in modified['nets']:
            net['pins'] = [
                'D1.b' if ref == 'D1.a' else 'D1.a' if ref == 'D1.b' else ref
                for ref in net['pins']]
        self.assertIsNone(match_rectifier(validate_model(modified)))

    def test_non_resistor_bridge_not_mistaken_for_wheatstone(self):
        modified = copy.deepcopy(self.bridge)
        next(p for p in modified['components'] if p['id'] == 'R5')['type'] = 'capacitor'
        self.assertIsNone(match_wheatstone(validate_model(modified)))

    def test_added_component_disables_pattern(self):
        modified = copy.deepcopy(self.bridge)
        modified['components'].append({'id': 'R6', 'type': 'resistor', 'value': '10k'})
        modified['nets'][0]['pins'].append('R6.a')
        modified['nets'][1]['pins'].append('R6.b')
        self.assertIsNone(recognize_motif(validate_model(modified)))

    def test_wheatstone_reversed_resistor_pins_still_matches(self):
        modified = copy.deepcopy(self.bridge)
        for net in modified['nets']:
            net['pins'] = [
                'R1.b' if ref == 'R1.a' else 'R1.a' if ref == 'R1.b' else
                'R5.b' if ref == 'R5.a' else 'R5.a' if ref == 'R5.b' else ref
                for ref in net['pins']]
        self.assertIsNotNone(match_wheatstone(validate_model(modified)))
        self.assertEqual(ET.fromstring(make_svg_from_netlist(modified)).attrib['data-motif'],
                         'wheatstone_diamond')

    def test_rectifier_reverse_resistor_terminals_still_matches(self):
        modified = copy.deepcopy(self.rectifier)
        for net in modified['nets']:
            net['pins'] = ['RL.b' if ref == 'RL.a' else 'RL.a' if ref == 'RL.b' else ref
                           for ref in net['pins']]
        self.assertIsNotNone(match_rectifier(validate_model(modified)))
        self.assertEqual(ET.fromstring(make_svg_from_netlist(modified)).attrib['data-motif'],
                         'bridge_rectifier_diamond')

    def test_netlist_order_does_not_change_motif_svg(self):
        for raw in (self.bridge, self.rectifier):
            modified = copy.deepcopy(raw)
            modified['components'].reverse()
            modified['nets'].reverse()
            for net in modified['nets']:
                net['pins'].reverse()
            self.assertEqual(make_svg_from_netlist(raw), make_svg_from_netlist(modified))

    def test_controller_uses_general_wire_renderer(self):
        output = make_svg_from_netlist(self.controller)
        self.assertIn("CircuitGen routed schematic", output)
        self.assertNotIn('data-motif=', output)
        self.assertNotIn('class="ground-mark"', output)
        self.assertNotIn('class="power-mark"', output)
        self.assertNotIn('class="netlabel"', output)

    def test_simple_series_svg_snapshot(self):
        raw = {
            'components': [
                {'id':'V1','type':'battery','value':'9V'},
                {'id':'R1','type':'resistor','value':'330Ω'},
                {'id':'D1','type':'led','value':'red'}],
            'nets': [
                {'name':'N1','pins':['V1.p','R1.a']},
                {'name':'N2','pins':['R1.b','D1.a']},
                {'name':'N3','pins':['D1.b','V1.n']}],
        }
        digest = hashlib.sha256(make_svg_from_netlist(raw).encode('utf-8')).hexdigest()
        self.assertEqual(digest, '89121fe7f390d5037259a0f69dbb0a329115ef8e146597225a108173b9984d57')

    def test_xml_escaping_labels(self):
        modified = copy.deepcopy(self.bridge)
        next(p for p in modified['components'] if p['id'] == 'R1')['value'] = '1k < 2k & safe'
        output = make_svg_from_netlist(modified)
        ET.fromstring(output)
        self.assertIn('1k &lt; 2k &amp; safe', output)

    def test_general_render_api_matches_auto_for_motifs(self):
        for raw in (self.bridge, self.rectifier):
            self.assertEqual(make_svg_from_netlist(raw), make_routed_svg_from_netlist(raw))


if __name__ == '__main__':
    unittest.main()
