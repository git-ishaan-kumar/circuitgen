import copy
import unittest
import xml.etree.ElementTree as ET

from circuitgen.engine import CircuitError, make_svg_from_netlist, validate_model
from circuitgen.symbols import BUILTIN_SYMBOLS, get_symbol, make_symbol_svg, pin_positions, transform_point


class TestSymbolLibrary(unittest.TestCase):
    def test_every_legacy_part_has_registered_symbol(self):
        from circuitgen.engine import VALID_TYPES
        self.assertTrue(VALID_TYPES.issubset(BUILTIN_SYMBOLS))
        self.assertEqual(get_symbol("resistor").pin_names, ("a", "b"))
        self.assertEqual(get_symbol("battery").pin_names, ("p", "n"))

    def test_basic_pin_locations(self):
        spec = get_symbol("resistor")
        self.assertEqual(pin_positions(spec), {"a": (-2, 0), "b": (2, 0)})
        self.assertEqual(pin_positions(spec, x=5, y=7), {"a": (3, 7), "b": (7, 7)})

    def test_clockwise_rotation(self):
        spec = get_symbol("resistor")
        self.assertEqual(pin_positions(spec, rotation=90), {"a": (0, -2), "b": (0, 2)})
        self.assertEqual(pin_positions(spec, rotation=180), {"a": (2, 0), "b": (-2, 0)})
        self.assertEqual(pin_positions(spec, rotation=270), {"a": (0, 2), "b": (0, -2)})

    def test_mirroring_then_rotation(self):
        spec = get_symbol("resistor")
        self.assertEqual(pin_positions(spec, mirror=True), {"a": (2, 0), "b": (-2, 0)})
        self.assertEqual(pin_positions(spec, mirror=True, rotation=90),
                         {"a": (0, 2), "b": (0, -2)})
        self.assertEqual(transform_point(3, 2, rotation=90, mirror=True), (-2, -3))

    def test_orientation_rejects_invalid_values(self):
        spec = get_symbol("resistor")
        for angle in (-90, 45, 360, 1, True, 90.0):
            with self.subTest(angle=angle), self.assertRaises(ValueError):
                pin_positions(spec, rotation=angle)
        with self.assertRaises(ValueError):
            pin_positions(spec, x=float("nan"))
        with self.assertRaises(ValueError):
            pin_positions(spec, mirror="yes")

    def test_fixed_transistor_pins(self):
        self.assertEqual(set(get_symbol("npn").pin_names), {"C", "B", "E"})
        self.assertEqual(set(get_symbol("nmos").pin_names), {"G", "D", "S"})
        self.assertEqual(len(get_symbol("opamp").pins), 5)

    def test_ne555_pin_numbers(self):
        spec = get_symbol("ne555")
        mapping = {pin.name: pin.number for pin in spec.pins}
        self.assertEqual(mapping, {
            "TRIG": "2", "RESET": "4", "CTRL": "5", "THRES": "6",
            "OUT": "3", "DISCH": "7", "VCC": "8", "GND": "1"
        })

    def test_arduino_is_symbolic_not_board_footprint(self):
        spec = get_symbol("arduino_uno")
        self.assertTrue({"D0", "D13", "A0", "A5", "5V", "GND", "VIN"}.issubset(spec.pin_names))
        self.assertEqual(len(spec.pins), len(set(spec.pin_names)))

    def test_custom_generic_ic(self):
        spec = get_symbol("sensor_xyz", ["VCC", "GND", "SDA", "SCL"])
        self.assertEqual(spec.shape, "ic")
        self.assertEqual(spec.pin_names, ("VCC", "GND", "SDA", "SCL"))
        self.assertEqual(len(pin_positions(spec)), 4)

    def test_known_pinouts_cannot_be_overridden(self):
        with self.assertRaisesRegex(ValueError, "must match"):
            get_symbol("ne555", ["OUT", "VCC"])
        self.assertEqual(get_symbol("npn", ["E", "B", "C"]).pin_names, ("C", "B", "E"))

    def test_invalid_custom_symbols(self):
        for pins in ([], ["X", "X"], ["bad space"], [12], "abc"):
            with self.subTest(pins=pins), self.assertRaises(ValueError):
                get_symbol("custom_ic", pins)
        with self.assertRaises(ValueError):
            get_symbol("unknown_without_pins")

    def test_model_uses_registered_symbols(self):
        raw = {
            "components": [{"id": "U1", "type": "ne555", "value": "NE555"},
                           {"id": "R1", "type": "resistor", "value": "1k"}],
            "nets": [{"name": "SIG", "pins": ["U1.OUT", "R1.a"]},
                     {"name": "GND", "pins": ["U1.GND", "R1.b"]}],
        }
        model = validate_model(raw)
        self.assertEqual(model.symbols["U1"].pin_names, get_symbol("ne555").pin_names)
        self.assertEqual(pin_positions(model.symbols["U1"])["GND"], (0, 3.35))
        self.assertIn('CircuitGen routed schematic', make_svg_from_netlist(raw))

    def test_model_rejects_misdeclared_known_pinout(self):
        raw = {"components": [{"id": "U1", "type": "ne555", "value": "NE555",
                               "pins": ["VCC", "GND", "OUT"]}],
               "nets": [{"name": "POWER", "pins": ["U1.VCC"]}]}
        with self.assertRaisesRegex(CircuitError, "must match"):
            validate_model(raw)

    def test_model_supports_custom_chip(self):
        raw = {"components": [{"id": "U1", "type": "sensor_xyz", "value": "sensor",
                               "pins": ["VCC", "GND", "SDA", "SCL"]}],
               "nets": [{"name": "POWER", "pins": ["U1.VCC"]}]}
        model = validate_model(raw)
        self.assertEqual(model.symbols["U1"].shape, "ic")
        self.assertEqual(len(model.symbols["U1"].pins), 4)

    def test_symbol_svg_is_parseable_and_transparent(self):
        for kind in ("resistor", "battery", "ac_source", "npn", "nmos",
                     "opamp", "ne555", "arduino_uno", "capacitor", "inductor", "led"):
            with self.subTest(kind=kind):
                markup = make_symbol_svg(kind, cid="X1", value="demo")
                root = ET.fromstring(markup)
                self.assertTrue(root.tag.endswith("svg"))
                self.assertNotIn('class="bg"', markup)
                self.assertEqual(markup, make_symbol_svg(kind, cid="X1", value="demo"))

    def test_ground_preserves_explicit_pin_names(self):
        self.assertEqual(get_symbol("ground").pin_names, ("gnd",))
        self.assertEqual(get_symbol("ground", ["GND"]).pin_names, ("GND",))
        self.assertEqual(get_symbol("ground", ["one", "two"]).shape, "ic")

    def test_rotated_and_mirrored_svg_is_parseable(self):
        for rotation in (0, 90, 180, 270):
            for mirror in (False, True):
                markup = make_symbol_svg("ne555", rotation=rotation, mirror=mirror)
                ET.fromstring(markup)
                self.assertIn(f'rotate({rotation})', markup)

    def test_escaped_user_labels(self):
        markup = make_symbol_svg("resistor", cid="A&B", value='<dangerous>&"')
        ET.fromstring(markup)
        self.assertIn("A&amp;B", markup)
        self.assertIn("&lt;dangerous&gt;&amp;", markup)

    def test_pin_labels_face_outward_for_every_orientation(self):
        for kind in ("ne555", "arduino_uno", "opamp", "npn", "resistor"):
            for rotation in (0, 90, 180, 270):
                for mirror in (False, True):
                    with self.subTest(kind=kind, rotation=rotation, mirror=mirror):
                        root = ET.fromstring(make_symbol_svg(kind, rotation=rotation, mirror=mirror))
                        labels = [e for e in root if e.attrib.get("class") == "pin"]
                        self.assertEqual(len(labels), len(get_symbol(kind).pins))
                        self.assertTrue(all(e.attrib.get("text-anchor") in ("start", "end", "middle") for e in labels))

    def test_new_symbols_do_not_change_legacy_svg(self):
        raw = {"components": [
            {"id": "V1", "type": "battery", "value": "9V"},
            {"id": "R1", "type": "resistor", "value": "330Ω"},
            {"id": "D1", "type": "led", "value": "red"},
        ], "nets": [
            {"name": "N1", "pins": ["V1.p", "R1.a"]},
            {"name": "N2", "pins": ["R1.b", "D1.a"]},
            {"name": "N3", "pins": ["D1.b", "V1.n"]},
        ]}
        artwork = make_svg_from_netlist(raw)
        self.assertIn('data-component="V1"', artwork)
        self.assertIn('data-component="R1"', artwork)
        self.assertIn('data-component="D1"', artwork)


if __name__ == "__main__":
    unittest.main()
