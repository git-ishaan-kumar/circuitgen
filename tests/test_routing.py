import copy
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from circuitgen.engine import (CircuitError, make_routed_svg_from_netlist,
                    make_svg_from_netlist, route_netlist, validate_model)
from circuitgen.optimization import assess_layout
from circuitgen.placement import place_model
from circuitgen.routing import (_MeshRouter, RoutingError, _intersects_rect,
                     _segment_clearance, _segments, _unjoined_crossing, route_model,
                     verify_display_connectivity)

ROOT = Path(__file__).resolve().parent.parent


def example(name):
    return json.loads((ROOT / 'examples' / name).read_text(encoding='utf-8'))


PLANT_MONITOR_NETLIST = {
    "components": [
        {"id": "U1", "type": "arduino_uno", "value": "Arduino Uno"},
        {"id": "S1", "type": "soil_sensor", "value": "Soil moisture module", "pins": ["VCC", "GND", "OUT"]},
        {"id": "S2", "type": "oled_module", "value": "SSD1306", "pins": ["VCC", "GND", "SDA", "SCL"]},
        {"id": "R1", "type": "resistor", "value": "Photoresistor"},
        {"id": "R2", "type": "resistor", "value": "10k"},
        {"id": "R3", "type": "resistor", "value": "330"},
        {"id": "R4", "type": "resistor", "value": "330"},
        {"id": "R5", "type": "resistor", "value": "330"},
        {"id": "D1", "type": "led", "value": "red"},
        {"id": "D2", "type": "led", "value": "yellow"},
        {"id": "D3", "type": "led", "value": "green"},
        {"id": "BZ1", "type": "piezo_buzzer", "value": "Passive buzzer", "pins": ["+", "-"]},
        {"id": "SW1", "type": "switch", "value": "Button"},
        {"id": "C1", "type": "capacitor", "value": "100nF"},
    ],
    "nets": [
        {"name": "VCC", "pins": ["U1.5V", "S1.VCC", "S2.VCC", "R1.a", "C1.a"]},
        {"name": "GND", "pins": ["U1.GND", "S1.GND", "S2.GND", "R2.b", "D1.b", "D2.b", "D3.b", "BZ1.-", "SW1.b", "C1.b"]},
        {"name": "SOIL", "pins": ["U1.A0", "S1.OUT"]},
        {"name": "LIGHT", "pins": ["U1.A1", "R1.b", "R2.a"]},
        {"name": "I2C_SDA", "pins": ["U1.A4", "S2.SDA"]},
        {"name": "I2C_SCL", "pins": ["U1.A5", "S2.SCL"]},
        {"name": "NET_D3", "pins": ["U1.D3", "R3.a"]},
        {"name": "LED_RED", "pins": ["R3.b", "D1.a"]},
        {"name": "NET_D4", "pins": ["U1.D4", "R4.a"]},
        {"name": "LED_YELLOW", "pins": ["R4.b", "D2.a"]},
        {"name": "NET_D5", "pins": ["U1.D5", "R5.a"]},
        {"name": "LED_GREEN", "pins": ["R5.b", "D3.a"]},
        {"name": "NET_D6", "pins": ["U1.D6", "BZ1.+"]},
        {"name": "NET_D7", "pins": ["U1.D7", "SW1.a"]},
    ],
}

USER_SHARED_GROUND_MONITOR_NETLIST = {
    "components": [
        {"id": "U1", "type": "arduino_uno", "value": "Arduino Uno"},
        {"id": "MS1", "type": "soil_moisture_sensor", "value": "generic", "pins": ["VCC", "GND", "OUT"]},
        {"id": "PR1", "type": "photoresistor", "value": "generic", "pins": ["a", "b"]},
        {"id": "R1", "type": "resistor", "value": "10k"},
        {"id": "DISP1", "type": "ssd1306_oled", "value": "generic", "pins": ["VCC", "GND", "SDA", "SCL"]},
        {"id": "LED1", "type": "led", "value": "Red"},
        {"id": "R2", "type": "resistor", "value": "330"},
        {"id": "LED2", "type": "led", "value": "Yellow"},
        {"id": "R3", "type": "resistor", "value": "330"},
        {"id": "LED3", "type": "led", "value": "Green"},
        {"id": "R4", "type": "resistor", "value": "330"},
        {"id": "BZ1", "type": "buzzer", "value": "piezo", "pins": ["pos", "neg"]},
        {"id": "SW1", "type": "switch", "value": "push button"},
        {"id": "C1", "type": "capacitor", "value": "100nF"},
    ],
    "nets": [
        {"name": "VCC_RAIL", "pins": ["U1.5V", "MS1.VCC", "DISP1.VCC", "PR1.a", "C1.a"]},
        {"name": "GND_RAIL", "pins": ["U1.GND", "MS1.GND", "DISP1.GND", "R1.b", "LED1.b", "LED2.b", "LED3.b", "BZ1.neg", "SW1.b", "C1.b"]},
        {"name": "MOISTURE_SIG", "pins": ["MS1.OUT", "U1.A0"]},
        {"name": "PHOTO_DIV", "pins": ["PR1.b", "R1.a", "U1.A1"]},
        {"name": "I2C_SDA", "pins": ["DISP1.SDA", "U1.A4"]},
        {"name": "I2C_SCL", "pins": ["DISP1.SCL", "U1.A5"]},
        {"name": "LED_RED_NET", "pins": ["U1.D3", "R2.a"]},
        {"name": "LED_RED_SERIES", "pins": ["R2.b", "LED1.a"]},
        {"name": "LED_YEL_NET", "pins": ["U1.D4", "R3.a"]},
        {"name": "LED_YEL_SERIES", "pins": ["R3.b", "LED2.a"]},
        {"name": "LED_GRN_NET", "pins": ["U1.D5", "R4.a"]},
        {"name": "LED_GRN_SERIES", "pins": ["R4.b", "LED3.a"]},
        {"name": "BUZZER_NET", "pins": ["U1.D6", "BZ1.pos"]},
        {"name": "BUTTON_NET", "pins": ["U1.D7", "SW1.a"]},
    ],
}

USER_BUZZER_CROSSOVER_NETLIST = {
    "components": [
        {"id": "U1", "type": "arduino_uno", "value": "Arduino Uno"},
        {"id": "M1", "type": "soil_moisture_sensor", "value": "Module", "pins": ["SIG", "VCC", "GND"]},
        {"id": "R_LDR", "type": "resistor", "value": "10k"},
        {"id": "LDR1", "type": "resistor", "value": "Photoresistor"},
        {"id": "OLED1", "type": "ssd1306_oled", "value": "5V", "pins": ["SDA", "SCL", "VCC", "GND"]},
        {"id": "LED_R", "type": "led", "value": "Red"},
        {"id": "R_R", "type": "resistor", "value": "330"},
        {"id": "LED_Y", "type": "led", "value": "Yellow"},
        {"id": "R_Y", "type": "resistor", "value": "330"},
        {"id": "LED_G", "type": "led", "value": "Green"},
        {"id": "R_G", "type": "resistor", "value": "330"},
        {"id": "BZ1", "type": "buzzer", "value": "Piezo", "pins": ["POS", "NEG"]},
        {"id": "SW1", "type": "switch", "value": "Button"},
        {"id": "C1", "type": "capacitor", "value": "100nF"},
    ],
    "nets": [
        {"name": "NET_5V", "pins": ["U1.5V", "M1.VCC", "OLED1.VCC", "R_LDR.a", "C1.a"]},
        {"name": "NET_GND", "pins": ["U1.GND", "M1.GND", "OLED1.GND", "LDR1.b", "LED_R.b", "LED_Y.b", "LED_G.b", "BZ1.NEG", "SW1.b", "C1.b"]},
        {"name": "NET_MOISTURE", "pins": ["U1.A0", "M1.SIG"]},
        {"name": "NET_DIVIDER", "pins": ["U1.A1", "R_LDR.b", "LDR1.a"]},
        {"name": "NET_SDA", "pins": ["U1.A4", "OLED1.SDA"]},
        {"name": "NET_SCL", "pins": ["U1.A5", "OLED1.SCL"]},
        {"name": "NET_D3", "pins": ["U1.D3", "R_R.a"]},
        {"name": "NET_LED_R", "pins": ["R_R.b", "LED_R.a"]},
        {"name": "NET_D4", "pins": ["U1.D4", "R_Y.a"]},
        {"name": "NET_LED_Y", "pins": ["R_Y.b", "LED_Y.a"]},
        {"name": "NET_D5", "pins": ["U1.D5", "R_G.a"]},
        {"name": "NET_LED_G", "pins": ["R_G.b", "LED_G.a"]},
        {"name": "NET_BUZZER", "pins": ["U1.D6", "BZ1.POS"]},
        {"name": "NET_BUTTON", "pins": ["U1.D7", "SW1.a"]},
    ],
}

USER_YELLOW_BRANCH_NETLIST = {
    "components": [
        {"id": "U1", "type": "arduino_uno", "value": "Arduino Uno"},
        {"id": "MS1", "type": "soil_moisture_sensor", "value": "generic", "pins": ["SIG", "VCC", "GND"]},
        {"id": "LDR1", "type": "resistor", "value": "photoresistor"},
        {"id": "R1", "type": "resistor", "value": "10k"},
        {"id": "DISP1", "type": "ssd1306_oled", "value": "5V", "pins": ["SDA", "SCL", "VCC", "GND"]},
        {"id": "LED_RED", "type": "led", "value": "red"},
        {"id": "R_RED", "type": "resistor", "value": "330"},
        {"id": "LED_YEL", "type": "led", "value": "yellow"},
        {"id": "R_YEL", "type": "resistor", "value": "330"},
        {"id": "LED_GRN", "type": "led", "value": "green"},
        {"id": "R_GRN", "type": "resistor", "value": "330"},
        {"id": "BZ1", "type": "buzzer", "value": "passive", "pins": ["POS", "NEG"]},
        {"id": "BTN1", "type": "switch", "value": "push_button"},
        {"id": "C1", "type": "capacitor", "value": "100nF"},
    ],
    "nets": [
        {"name": "MOISTURE_SIG", "pins": ["U1.A0", "MS1.SIG"]},
        {"name": "DIVIDER_NODE", "pins": ["U1.A1", "LDR1.b", "R1.a"]},
        {"name": "I2C_SDA", "pins": ["U1.A4", "DISP1.SDA"]},
        {"name": "I2C_SCL", "pins": ["U1.A5", "DISP1.SCL"]},
        {"name": "LED_RED_DRV", "pins": ["U1.D3", "R_RED.a"]},
        {"name": "LED_RED_SEQ", "pins": ["R_RED.b", "LED_RED.a"]},
        {"name": "LED_YEL_DRV", "pins": ["U1.D4", "R_YEL.a"]},
        {"name": "LED_YEL_SEQ", "pins": ["R_YEL.b", "LED_YEL.a"]},
        {"name": "LED_GRN_DRV", "pins": ["U1.D5", "R_GRN.a"]},
        {"name": "LED_GRN_SEQ", "pins": ["R_GRN.b", "LED_GRN.a"]},
        {"name": "BUZZER_SIG", "pins": ["U1.D6", "BZ1.POS"]},
        {"name": "BUTTON_SIG", "pins": ["U1.D7", "BTN1.a"]},
        {"name": "POWER_5V", "pins": ["U1.5V", "MS1.VCC", "LDR1.a", "DISP1.VCC", "C1.a"]},
        {"name": "SYSTEM_GND", "pins": ["U1.GND", "MS1.GND", "R1.b", "DISP1.GND", "LED_RED.b", "LED_YEL.b", "LED_GRN.b", "BZ1.NEG", "BTN1.b", "C1.b"]},
    ],
}

USER_PIN_ORDER_VARIATION_NETLIST = copy.deepcopy(USER_YELLOW_BRANCH_NETLIST)
_component_names = {
    "DISP1": "DIS1", "LED_RED": "LED_R", "R_RED": "R_R",
    "LED_YEL": "LED_Y", "R_YEL": "R_Y", "LED_GRN": "LED_G", "R_GRN": "R_G",
}
_net_names = {
    "MOISTURE_SIG": "NET_MOISTURE_SIG", "DIVIDER_NODE": "NET_DIVIDER_MID",
    "I2C_SDA": "NET_SDA", "I2C_SCL": "NET_SCL",
    "LED_RED_DRV": "NET_D3", "LED_RED_SEQ": "NET_LED_R_SERIES",
    "LED_YEL_DRV": "NET_D4", "LED_YEL_SEQ": "NET_LED_Y_SERIES",
    "LED_GRN_DRV": "NET_D5", "LED_GRN_SEQ": "NET_LED_G_SERIES",
    "BUZZER_SIG": "NET_D6", "BUTTON_SIG": "NET_D7",
    "POWER_5V": "NET_5V", "SYSTEM_GND": "NET_GND",
}
for _component in USER_PIN_ORDER_VARIATION_NETLIST["components"]:
    _component["id"] = _component_names.get(_component["id"], _component["id"])
    if _component["id"] == "LDR1":
        _component.update(type="photoresistor", pins=["a", "b"])
    elif _component["id"] == "DIS1":
        _component.update(type="oled_display", value="SSD1306", pins=["VCC", "GND", "SCL", "SDA"])
    elif _component["id"] == "BZ1":
        _component.update(pins=["pos", "neg"])
for _net in USER_PIN_ORDER_VARIATION_NETLIST["nets"]:
    _net["name"] = _net_names.get(_net["name"], _net["name"])
    remapped_pins = []
    for ref in _net["pins"]:
        cid, pin = ref.split(".", 1)
        cid = _component_names.get(cid, cid)
        if cid == "BZ1":
            pin = pin.lower()
        remapped_pins.append(f"{cid}.{pin}")
    _net["pins"] = remapped_pins

class TestRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = example('wheatstone.json')
        cls.bridge_routes = route_netlist(cls.bridge)
        cls.controller = example('controller.json')
        cls.controller_routes = route_netlist(cls.controller)

    def test_wheatstone_all_nets_have_physical_wires(self):
        result = self.bridge_routes
        self.assertEqual(set(result.paths), {x['name'] for x in self.bridge['nets']})
        self.assertEqual(result.labels, ())
        self.assertEqual(set(result.pin_to_net),
                         {ref for net in self.bridge['nets'] for ref in net['pins']})
        self.assertEqual(sum(len(p) for p in result.paths.values()), 8)

    def test_wheatstone_has_valid_branch_junctions(self):
        # The rail branches may meet at component pins; midpoint junctions
        # must be explicit dots where the bridge resistor joins each arm.
        self.assertTrue(self.bridge_routes.junctions['LEFT_MID'])
        self.assertTrue(self.bridge_routes.junctions['RIGHT_MID'])
        self.assertEqual(self.bridge_routes.labels, ())

    def test_every_wire_is_manhattan(self):
        for result in (self.bridge_routes, self.controller_routes):
            for paths in result.paths.values():
                for path in paths:
                    for a, b in _segments(path):
                        self.assertNotEqual(a, b)
                        self.assertTrue(abs(a[0]-b[0]) < 1e-5 or abs(a[1]-b[1]) < 1e-5)

    def test_no_unrelated_wire_intersections(self):
        for result in (self.bridge_routes, self.controller_routes):
            line_segments = [(net, a, b) for net, paths in result.paths.items()
                             for path in paths for a, b in _segments(path)]
            for i, (net, a, b) in enumerate(line_segments):
                for other, c, d in line_segments[i+1:]:
                    if net != other:
                        self.assertTrue(
                            _segment_clearance(a, b, c, d) > 0.14
                            or _unjoined_crossing(a, b, c, d, edge_margin=0.60),
                            f"{net} touches {other}",
                        )

    def test_wires_do_not_cross_symbol_bodies(self):
        for raw, result in ((self.bridge, self.bridge_routes),
                            (self.controller, self.controller_routes)):
            router = _MeshRouter(validate_model(raw), result.placement, 11)
            for paths in result.paths.values():
                for path in paths:
                    for a, b in _segments(path):
                        self.assertFalse(any(_intersects_rect(a,b,rect)
                                             for rect in router.rects))

    def test_controller_power_and_signal_pins_are_physically_wired(self):
        result = self.controller_routes
        self.assertEqual(result.labels, ())
        self.assertTrue(all(result.paths.values()))
        self.assertTrue(result.junctions["GND"])
        verify_display_connectivity(validate_model(self.controller), result)

    def test_ne555_power_and_ground_reach_battery_terminals(self):
        raw = example("ne555.json")
        model = validate_model(raw)
        result = route_model(model)
        self.assertEqual(result.labels, ())
        self.assertTrue(result.junctions["VCC"])
        self.assertTrue(result.junctions["GND"])
        self.assertEqual(result.pin_to_net["B1.p"], "VCC")
        self.assertEqual(result.pin_to_net["B1.n"], "GND")
        verify_display_connectivity(model, result)
        for net, paths in result.paths.items():
            pins = {result.placement.symbols[cid].pin_positions[pin]
                    for cid, pin in (ref.split('.') for ref in model.nets[net])}
            for index, path in enumerate(paths):
                for point in (path[0], path[-1]):
                    self.assertTrue(any(_segment_clearance(point, point, p, p) < 1e-6 for p in pins)
                                    or any(_segment_clearance(point, point, a, b) < 1e-6
                                           for j, branch in enumerate(paths) if j != index
                                           for a, b in _segments(branch)), (net, point))

    def test_default_layout_compacts_non_ic_circuit(self):
        model = validate_model(example("layout_optimization.json"))
        baseline = route_model(model, place_model(model))
        result = route_model(model)
        self.assertLess(assess_layout(result).footprint_area, assess_layout(baseline).footprint_area)
        self.assertLess(assess_layout(result).wire_length, assess_layout(baseline).wire_length)
        verify_display_connectivity(model, result)

    def test_external_pin_labels_leave_room_for_wires(self):
        raw = {
            "components": [
                {"id": "V1", "type": "battery", "value": "5V"},
                {"id": "R1", "type": "resistor", "value": "1k"},
                {"id": "Q1", "type": "npn", "value": "2N3904"},
            ],
            "nets": [
                {"name": "VCC", "pins": ["V1.p", "R1.a", "Q1.C"]},
                {"name": "BASE", "pins": ["R1.b", "Q1.B"]},
                {"name": "GND", "pins": ["V1.n", "Q1.E"]},
            ],
        }
        model = validate_model(raw)
        result = route_model(model)
        router = _MeshRouter(model, result.placement, 11)
        for net, paths in result.paths.items():
            for path in paths:
                for a, b in _segments(path):
                    self.assertFalse(any(_intersects_rect(a, b, rect) for rect in router.rects), net)
        verify_display_connectivity(model, result)

    def test_shared_return_and_explicit_ground_keep_distinct_supplies(self):
        raw = {
            "components": [
                {"id": "V1", "type": "dc_source", "value": "5V"},
                {"id": "V2", "type": "current_source", "value": "1mA"},
                {"id": "R1", "type": "resistor", "value": "1k"},
                {"id": "R2", "type": "resistor", "value": "2k"},
                {"id": "G1", "type": "ground", "value": ""},
            ],
            "nets": [
                {"name": "VCC", "pins": ["V1.p", "R1.a"]},
                {"name": "VDD", "pins": ["V2.p", "R2.a"]},
                {"name": "GND", "pins": ["V1.n", "V2.n", "R1.b", "R2.b", "G1.gnd"]},
            ],
        }
        model = validate_model(raw)
        result = route_model(model)
        self.assertEqual(result.labels, ())
        self.assertNotEqual(result.pin_to_net["V1.p"], result.pin_to_net["V2.p"])
        self.assertEqual({result.pin_to_net[ref] for ref in raw["nets"][2]["pins"]}, {"GND"})
        self.assertTrue(result.junctions["GND"])
        verify_display_connectivity(model, result)

        svg = ET.fromstring(make_svg_from_netlist(raw))
        grounds = [element for element in svg.iter() if element.get("data-type") == "ground"]
        self.assertEqual([element.get("data-component") for element in grounds], ["G1"])
        self.assertEqual(len(list(grounds[0].iter("{http://www.w3.org/2000/svg}line"))), 4)

    def test_controller_svg_labels_pins_inside_symbols(self):
        svg = make_routed_svg_from_netlist(self.controller)
        ET.fromstring(svg)
        self.assertIn('data-net="SDA"', svg)
        self.assertIn('data-net="SCL"', svg)
        self.assertIn('>A4<', svg)
        self.assertIn('>GND<', svg)

    def test_auto_api_falls_back_only_when_needed(self):
        bridge_svg = make_svg_from_netlist(self.bridge)
        self.assertIn('CircuitGen routed schematic', bridge_svg)
        self.assertEqual(bridge_svg.count('data-component="'), 6)
        small = {'components': [
            {'id':'V1', 'type':'battery', 'value':'9V'},
            {'id':'R1', 'type':'resistor', 'value':'330Ω'}],
            'nets': [
                {'name':'A', 'pins':['V1.p','R1.a']},
                {'name':'B', 'pins':['R1.b','V1.n']}]}
        self.assertNotIn('CircuitGen routed schematic', make_svg_from_netlist(small))

    def test_svg_contains_real_wires_not_dashed_guides(self):
        svg = make_routed_svg_from_netlist(self.bridge)
        ET.fromstring(svg)
        self.assertIn('class="wire"', svg)
        self.assertNotIn('class="guide"', svg)
        self.assertNotIn('class="bg"', svg)
        self.assertNotIn('class="foot"', svg)
        self.assertIn('data-net="LEFT_MID"', svg)

    def test_deterministic_when_netlist_order_changes(self):
        original = make_routed_svg_from_netlist(self.bridge)
        permuted = copy.deepcopy(self.bridge)
        permuted['components'].reverse()
        permuted['nets'].reverse()
        for net in permuted['nets']:
            net['pins'].reverse()
        self.assertEqual(original, make_routed_svg_from_netlist(permuted))

    def test_multiple_source_circuit(self):
        raw = {'components': [
            {'id':'V1','type':'battery','value':'9V'},
            {'id':'V2','type':'ac_source','value':'3V'},
            {'id':'R1','type':'resistor','value':'1k'}],
            'nets': [
                {'name':'A','pins':['V1.p','R1.a']},
                {'name':'B','pins':['R1.b','V2.p']},
                {'name':'C','pins':['V2.n','V1.n']}]}
        routed = route_netlist(raw)
        self.assertEqual(set(routed.placement.symbols), {'V1','V2','R1'})
        self.assertEqual(routed.labels, ())
        self.assertTrue(all(routed.paths.values()))
        verify_display_connectivity(validate_model(raw), routed)

    def test_invalid_pin_is_rejected_before_route(self):
        raw = copy.deepcopy(self.bridge)
        raw['nets'][0]['pins'].append('R5.not_a_pin')
        with self.assertRaisesRegex(CircuitError, 'Unknown terminal'):
            route_netlist(raw)

    def test_grid_budget_is_explicit_failure_not_partial_svg(self):
        from unittest.mock import patch
        with patch('circuitgen.routing.MAX_TRACK_NODES', 1):
            with self.assertRaisesRegex(RoutingError, 'grid limit'):
                route_netlist(self.bridge)

    def test_dense_two_button_branches_route_with_verified_wires(self):
        raw = {
            "components": [
                {"id": "V1", "type": "battery", "value": "9V"},
                {"id": "SW1", "type": "switch", "value": "BTN1"},
                {"id": "SW2", "type": "switch", "value": "BTN2"},
                {"id": "R1", "type": "resistor", "value": "10k"},
                {"id": "R2", "type": "resistor", "value": "10k"},
                {"id": "C1", "type": "capacitor", "value": "100nF"},
                {"id": "C2", "type": "capacitor", "value": "100nF"},
            ],
            "nets": [
                {"name": "VCC", "pins": ["V1.p", "R1.a", "R2.a"]},
                {"name": "GND", "pins": ["V1.n", "SW1.b", "SW2.b", "C1.b", "C2.b"]},
                {"name": "NET_BTN1", "pins": ["SW1.a", "R1.b", "C1.a"]},
                {"name": "NET_BTN2", "pins": ["SW2.a", "R2.b", "C2.a"]},
            ],
        }
        model = validate_model(raw)

        result = route_model(model)

        self.assertEqual(set(result.paths), set(model.nets))
        self.assertEqual(result.labels, ())
        verify_display_connectivity(model, result)

    def test_arduino_plant_monitor_routes_buzzer_and_dense_io(self):
        model = validate_model(PLANT_MONITOR_NETLIST)
        result = route_model(model)
        self.assertEqual(result.pin_to_net["U1.D6"], "NET_D6")
        self.assertIn("NET_D6", result.paths)
        verify_display_connectivity(model, result)

    def test_user_reported_monitor_netlist_routes_without_overlaps(self):
        model = validate_model(USER_SHARED_GROUND_MONITOR_NETLIST)
        result = route_model(model)
        self.assertEqual(result.pin_to_net["U1.D7"], "BUTTON_NET")
        self.assertEqual(result.pin_to_net["U1.A5"], "I2C_SCL")
        verify_display_connectivity(model, result)

    def test_user_reported_buzzer_crossing_renders_with_clear_wire_jumps(self):
        svg = make_svg_from_netlist(USER_BUZZER_CROSSOVER_NETLIST)
        self.assertIn("<svg", svg)
        self.assertIn('data-net="NET_BUZZER"', svg)

    def test_user_reported_yellow_branch_netlist_routes(self):
        svg = make_svg_from_netlist(USER_YELLOW_BRANCH_NETLIST)
        self.assertIn("<svg", svg)
        self.assertIn('data-net="LED_YEL_DRV"', svg)

    def test_user_reported_pin_order_variation_routes(self):
        svg = make_svg_from_netlist(USER_PIN_ORDER_VARIATION_NETLIST)
        self.assertIn("<svg", svg)
        self.assertIn('data-net="NET_D5"', svg)

    def test_route_reconsiders_placement_after_initial_spacing_fails(self):
        from unittest.mock import patch
        from circuitgen import routing

        model = validate_model(self.controller)
        original_placement = place_model(model)
        route_once = routing._route_model_base
        tried = []

        def fail_initial_spacing_then_route(candidate_model, placement=None):
            tried.append(placement)
            if len(tried) <= 4:
                raise RoutingError("test forces spacing and placement recovery")
            return route_once(candidate_model, placement)

        with patch("circuitgen.routing._route_model_base", side_effect=fail_initial_spacing_then_route):
            result = route_model(model)

        self.assertGreater(len(tried), 4)
        self.assertNotEqual(tried[4].symbols, original_placement.symbols)
        verify_display_connectivity(model, result)


if __name__ == '__main__':
    unittest.main()
