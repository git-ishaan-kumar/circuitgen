import copy
import unittest

from circuitgen.engine import CircuitError, layout, make_svg_from_netlist, segment_cells, validate


def netlist(parts, nets):
    return {
        "components": [
            {"id": cid, "type": kind, "value": value}
            for cid, kind, value in parts
        ],
        "nets": [
            {"name": f"N{i}", "pins": pins}
            for i, pins in enumerate(nets, 1)
        ],
    }


class TestEngine(unittest.TestCase):
    def check_svg(self, parts, nets):
        raw = netlist(parts, nets)
        artwork = make_svg_from_netlist(raw)
        self.assertIn("<svg", artwork)
        self.assertEqual(artwork.count("data-component="), len(parts))

    def test_series_led(self):
        self.check_svg(
            [("V1", "battery", "9V"), ("R1", "resistor", "330Ω"), ("D1", "led", "red")],
            [["V1.p", "R1.a"], ["R1.b", "D1.a"], ["D1.b", "V1.n"]],
        )

    def test_parallel_resistors(self):
        self.check_svg(
            [("V1", "battery", "5V"), ("R1", "resistor", "1kΩ"), ("R2", "resistor", "2kΩ")],
            [["V1.p", "R1.a", "R2.a"], ["V1.n", "R1.b", "R2.b"]],
        )

    def test_complex_parallel(self):
        self.check_svg(
            [("V1", "dc_source", "12V"), ("R1", "resistor", "100Ω"),
             ("C1", "capacitor", "10µF"), ("R2", "resistor", "220Ω"),
             ("L1", "inductor", "2mH"), ("D1", "diode", "1N4148"),
             ("R3", "resistor", "330Ω")],
            [["V1.p", "R1.a"], ["R1.b", "C1.a", "R2.a", "L1.a"],
             ["C1.b", "R2.b", "D1.a"], ["L1.b", "R3.a"],
             ["R3.b", "D1.b", "V1.n"]],
        )

    def test_reversed_diode(self):
        self.check_svg(
            [("V1", "battery", "3V"), ("D1", "diode", "test")],
            [["V1.p", "D1.b"], ["V1.n", "D1.a"]],
        )

    def test_three_parallel_branches(self):
        self.check_svg(
            [("V1", "battery", "9V"), ("R1", "resistor", "10Ω"),
             ("R2", "resistor", "20Ω"), ("R3", "resistor", "30Ω")],
            [["V1.p", "R1.a", "R2.a", "R3.a"],
             ["V1.n", "R1.b", "R2.b", "R3.b"]],
        )

    def test_parallel_rails_have_no_duplicate_wire_segments(self):
        raw = netlist(
            [("V1", "battery", "9V"), ("R1", "resistor", "WWWWWWWWWWWWWWWWWWWW"),
             ("R2", "resistor", "20k"), ("R3", "resistor", "30k")],
            [["V1.p", "R1.a", "R2.a", "R3.a"],
             ["V1.n", "R1.b", "R2.b", "R3.b"]],
        )
        ink = layout(validate(raw))
        edges = set()
        for net, points in ink.wires:
            for a, b in zip(points, points[1:]):
                cells = segment_cells(a, b)
                for start, end in zip(cells, cells[1:]):
                    edge = (net, *sorted((start, end)))
                    self.assertNotIn(edge, edges)
                    edges.add(edge)
        self.assertEqual({ink.placed[cid].x for cid in ("R1", "R2", "R3")},
                         {ink.placed["R1"].x})
        for cid in ("R1", "R2", "R3"):
            part = ink.placed[cid]
            self.assertEqual({x - part.x for x, _ in part.terminals.values()}, {-2, 2})

    def test_nested_series_parallel(self):
        self.check_svg(
            [("V1", "battery", "9V"), ("R1", "resistor", "1kΩ"),
             ("R2", "resistor", "2kΩ"), ("R3", "resistor", "3kΩ"),
             ("R4", "resistor", "4kΩ"), ("R5", "resistor", "5kΩ"),
             ("R6", "resistor", "6kΩ"), ("C1", "capacitor", "100nF")],
            [["V1.p", "R1.a", "R3.a"], ["R1.b", "R2.a"],
             ["R2.b", "R3.b", "R4.a"],
             ["R4.b", "R5.a", "R6.a", "C1.a"],
             ["R5.b", "R6.b", "C1.b", "V1.n"]],
        )

    def test_deterministic_output(self):
        raw = netlist(
            [("V1", "battery", "9V"), ("R1", "resistor", "330Ω"),
             ("D1", "led", "red")],
            [["V1.p", "R1.a"], ["R1.b", "D1.a"], ["D1.b", "V1.n"]],
        )
        self.assertEqual(make_svg_from_netlist(raw), make_svg_from_netlist(copy.deepcopy(raw)))

    def test_transparent_svg_without_footer(self):
        raw = netlist(
            [("V1", "battery", "9V"), ("R1", "resistor", "330Ω")],
            [["V1.p", "R1.a"], ["R1.b", "V1.n"]],
        )
        artwork = make_svg_from_netlist(raw)
        self.assertNotIn('class="bg"', artwork)
        self.assertNotIn('class="foot"', artwork)

    def test_malformed_netlists_raise_circuit_error(self):
        good = netlist(
            [("V1", "battery", "9V"), ("R1", "resistor", "330Ω")],
            [["V1.p", "R1.a"], ["R1.b", "V1.n"]],
        )
        cases = [None, [], "invalid", 42]
        for kind in [None, [], 123, {}]:
            bad = copy.deepcopy(good)
            bad["components"][1]["type"] = kind
            cases.append(bad)
        for pins in [["V1.p", None], ["V1.p", []], ["V1.p", {}]]:
            bad = copy.deepcopy(good)
            bad["nets"][0]["pins"] = pins
            cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(CircuitError):
                make_svg_from_netlist(bad)

    def test_missing_component_pin(self):
        raw = netlist(
            [("V1", "battery", "9V"), ("R1", "resistor", "330Ω")],
            [["V1.p", "R1.a"], ["V1.n", "R1.a"]],
        )
        with self.assertRaises(CircuitError):
            make_svg_from_netlist(raw)

    def test_invalid_pin_name(self):
        raw = netlist(
            [("V1", "battery", "9V"), ("R1", "resistor", "330Ω")],
            [["V1.p", "R1.x"], ["R1.b", "V1.n"]],
        )
        with self.assertRaisesRegex(CircuitError, "Unknown terminal"):
            make_svg_from_netlist(raw)

    def test_multiple_sources_routed(self):
        raw = netlist(
            [("V1", "battery", "9V"), ("V2", "battery", "5V")],
            [["V1.p", "V2.p"], ["V1.n", "V2.n"]],
        )
        artwork = make_svg_from_netlist(raw)
        self.assertIn('CircuitGen routed schematic', artwork)
        self.assertEqual(artwork.count('data-component="'), 2)

    def test_duplicate_terminal(self):
        raw = netlist(
            [("V1", "battery", "9V"), ("R1", "resistor", "1kΩ")],
            [["V1.p", "R1.a"], ["V1.n", "R1.b", "R1.a"]],
        )
        with self.assertRaises(CircuitError):
            make_svg_from_netlist(raw)

    def test_wheatstone_bridge(self):
        raw = netlist(
            [("V1", "battery", "9V"), ("R1", "resistor", "1kΩ"),
             ("R2", "resistor", "2kΩ"), ("R3", "resistor", "3kΩ"),
             ("R4", "resistor", "4kΩ"), ("R5", "resistor", "5kΩ")],
            [["V1.p", "R1.a", "R3.a"], ["R1.b", "R2.a", "R5.a"],
             ["R3.b", "R4.a", "R5.b"], ["R2.b", "R4.b", "V1.n"]],
        )
        artwork = make_svg_from_netlist(raw)
        self.assertIn('CircuitGen routed schematic', artwork)
        self.assertEqual(artwork.count('data-component="'), 6)

    def test_dangling_terminal_is_visible_as_unconnected(self):
        raw = netlist(
            [("V1", "battery", "9V"), ("R1", "resistor", "1kΩ")],
            [["V1.p", "R1.a"], ["V1.n"]],
        )
        self.assertIn('CircuitGen routed schematic', make_svg_from_netlist(raw))


if __name__ == "__main__":
    unittest.main()

class TestGeneralModel(unittest.TestCase):
    def test_multi_source_model(self):
        from circuitgen.engine import validate_model
        raw = netlist([('V1','battery','9V'),('V2','ac_source','5Vrms'),('R1','resistor','1k')],
                      [['V1.p','R1.a'],['V1.n','V2.n'],['V2.p','R1.b']])
        model = validate_model(raw)
        self.assertEqual(len(model.components), 3)
        self.assertIn('CircuitGen routed schematic', make_svg_from_netlist(raw))

    def test_custom_multipin_component(self):
        from circuitgen.engine import validate_model
        raw = {'components':[{'id':'U1','type':'custom_chip','value':'demo','pins':['VCC','GND','OUT']},
                             {'id':'R1','type':'resistor','value':'1k'}],
               'nets':[{'name':'POWER','pins':['U1.VCC','R1.a']},
                       {'name':'GND','pins':['U1.GND','R1.b']},
                       {'name':'SIGNAL','pins':['U1.OUT']}]}
        model = validate_model(raw)
        self.assertEqual(model.components['U1'].pins['OUT'], 'SIGNAL')
        self.assertIn('CircuitGen routed schematic', make_svg_from_netlist(raw))

    def test_unknown_pin_rejected(self):
        from circuitgen.engine import validate_model
        raw = {'components':[{'id':'Q1','type':'npn','value':'2N3904'}],
               'nets':[{'name':'N1','pins':['Q1.INVALID']}]}
        with self.assertRaisesRegex(CircuitError, 'Unknown terminal'):
            validate_model(raw)

    def test_duplicate_pin_assignment_rejected(self):
        from circuitgen.engine import validate_model
        raw = {'components':[{'id':'R1','type':'resistor','value':'1k'}],
               'nets':[{'name':'N1','pins':['R1.a']},{'name':'N2','pins':['R1.a']}]}
        with self.assertRaisesRegex(CircuitError, 'assigned more than once'):
            validate_model(raw)
