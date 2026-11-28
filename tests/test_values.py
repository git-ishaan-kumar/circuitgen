from __future__ import annotations

import unittest

from circuitgen import from_netlist, validate
from circuitgen.erc import check_electrical_rules
from circuitgen.values import (format_component_value, nearest_preferred_value,
                               next_preferred_value, normalize_netlist_values)


class TestComponentValueFormatting(unittest.TestCase):
    def test_engineering_values_and_aliases(self):
        cases = (
            ("resistor", "330ohms", "330 Ω"),
            ("resistor", "330 Ω", "330 Ω"),
            ("resistor", "10000 ohms", "10 kΩ"),
            ("resistor", "1.5k", "1.5 kΩ"),
            ("resistor", "3k", "3 kΩ"),
            ("resistor", "1.6k", "1.6 kΩ"),
            ("resistor", "4k7", "4.7 kΩ"),
            ("resistor", "470_ohm", "470 \u03a9"),
            ("resistor", "10k_ohm", "10 k\u03a9"),
            ("resistor", "5k1_ohm", "5.1 k\u03a9"),
            ("resistor", "1k5_ohm", "1.5 k\u03a9"),
            ("resistor", "4R7", "4.7 \u03a9"),
            ("resistor", "2M2-ohms", "2.2 M\u03a9"),
            ("capacitor", "100nf", "100 nF"),
            ("capacitor", "4u7", "4.7 \u00b5F"),
            ("capacitor", "100n_F", "100 nF"),
            ("inductor", "10mh", "10 mH"),
            ("inductor", "1h", "1 H"),
            ("capacitor", "1f", "1 F"),
            ("battery", "9V", "9 V"),
            ("current_source", "0.02A", "20 mA"),
            ("dc_source", "9000 mV", "9 V"),
            ("ac_source", "60hz", "60 Hz"),
        )
        for kind, value, expected in cases:
            with self.subTest(kind=kind, value=value):
                self.assertEqual(format_component_value(kind, value), expected)

    def test_rkm_values_and_repeated_formatting_preserve_numeric_meaning(self):
        from circuitgen.values import parse_component_quantity, parse_quantity

        cases = (
            ("resistor", "470R", 470.0, "\u03a9"),
            ("resistor", "470 R\u03a9", 470.0, "\u03a9"),
            ("resistor", "4R7", 4.7, "\u03a9"),
            ("resistor", "4k7", 4700.0, "\u03a9"),
            ("resistor", "5k1_ohm", 5100.0, "\u03a9"),
            ("resistor", "1k5_ohm", 1500.0, "\u03a9"),
            ("resistor", "470-ohm", 470.0, "\u03a9"),
            ("capacitor", "4u7", 4.7e-6, "F"),
            ("capacitor", "100n_F", 100e-9, "F"),
            ("inductor", "10mH", 10e-3, "H"),
            ("battery", "9000_mV", 9.0, "V"),
            ("current_source", "20_mA", 20e-3, "A"),
        )
        for kind, raw, magnitude, unit in cases:
            with self.subTest(kind=kind, raw=raw):
                parsed = parse_component_quantity(kind, raw)
                formatted = format_component_value(kind, raw)
                formatted_again = format_component_value(kind, formatted)
                reparsed = parse_component_quantity(kind, formatted)
                self.assertEqual(parsed[1], unit)
                self.assertAlmostEqual(parsed[0], magnitude)
                self.assertEqual(reparsed[1], unit)
                self.assertAlmostEqual(reparsed[0], magnitude)
                self.assertEqual(formatted_again, formatted)

        self.assertEqual(parse_quantity("-470_ohm"), (-470.0, "\u03a9"))
        self.assertEqual(format_component_value("resistor", "470-ohm"), "470 \u03a9")

    def test_values_without_a_clear_unit_or_matching_component_are_preserved(self):
        self.assertEqual(format_component_value("resistor", "1k"), "1 kΩ")
        self.assertEqual(format_component_value("resistor", "510"), "510 Ω")
        self.assertEqual(format_component_value("sensor_module", "1k"), "1k")
        self.assertEqual(format_component_value("resistor", "5V"), "5V")
        self.assertEqual(format_component_value("sensor_module", "Part-X7"), "Part-X7")
        self.assertEqual(format_component_value("capacitor", "custom timing cap"),
                         "custom timing cap")

    def test_separators_and_rkm_values_keep_their_numeric_meaning(self):
        from circuitgen.values import parse_component_quantity, parse_quantity

        self.assertEqual(parse_component_quantity("resistor", "5k1_ohm"), (5100.0, "\u03a9"))
        self.assertEqual(parse_component_quantity("resistor", "1k5_ohm"), (1500.0, "\u03a9"))
        self.assertEqual(parse_quantity("-470_ohm"), (-470.0, "\u03a9"))
        self.assertEqual(format_component_value("resistor", "470-ohm"), "470 \u03a9")

    def test_descriptive_labels_are_normalized_only_when_recognized(self):
        self.assertEqual(format_component_value("led", "Red"), "red")
        self.assertEqual(format_component_value("ne555", "ne555"), "NE555")
        self.assertEqual(format_component_value("sensor_module", "ZX-42A"), "ZX-42A")

    def test_normalization_does_not_mutate_input(self):
        raw = {"components": [{"id": "R1", "type": "resistor", "value": "10000 ohms"}],
               "nets": [{"name": "N", "pins": ["R1.a"]}]}
        normalized = normalize_netlist_values(raw)
        self.assertEqual(raw["components"][0]["value"], "10000 ohms")
        self.assertEqual(normalized["components"][0]["value"], "10 kΩ")
        self.assertIsNot(raw["components"], normalized["components"])

    def test_netlist_value_normalization_is_idempotent(self):
        raw = {"components": [{"id": "R1", "type": "resistor", "value": "470R"}],
               "nets": []}
        normalized = normalize_netlist_values(raw)
        normalized_again = normalize_netlist_values(normalized)
        self.assertEqual(normalized_again, normalized)
        self.assertEqual(normalized["components"][0]["value"], "470 Ω")

    def test_library_render_and_validation_use_normalized_model_values(self):
        raw = {"components": [
            {"id": "V1", "type": "battery", "value": "9V"},
            {"id": "R1", "type": "resistor", "value": "330ohms"},
            {"id": "D1", "type": "led", "value": "Red"},
        ], "nets": [
            {"name": "P", "pins": ["V1.p", "R1.a"]},
            {"name": "M", "pins": ["R1.b", "D1.a"]},
            {"name": "N", "pins": ["D1.b", "V1.n"]},
        ]}
        check = validate(raw)
        self.assertTrue(check.valid)
        self.assertEqual(check.model.components["R1"].value, "330 Ω")
        result = from_netlist(raw, output=None)
        self.assertIn("330 Ω", result.svg)
        self.assertEqual(result.netlist["components"][0]["value"], "9 V")
        self.assertIsNotNone(result.electrical_report)
        self.assertEqual(raw["components"][0]["value"], "9V")

    def test_manual_netlist_with_separated_rkm_value_uses_shared_formatter(self):
        raw = {"components": [
            {"id": "V1", "type": "battery", "value": "9V"},
            {"id": "R1", "type": "resistor", "value": "5k1_ohm"},
            {"id": "D1", "type": "led", "value": "Red"},
        ], "nets": [
            {"name": "P", "pins": ["V1.p", "R1.a"]},
            {"name": "M", "pins": ["R1.b", "D1.a"]},
            {"name": "N", "pins": ["D1.b", "V1.n"]},
        ]}
        result = from_netlist(raw, output=None)

        self.assertIn("5.1 k\u03a9", result.svg)
        self.assertEqual(raw["components"][1]["value"], "5k1_ohm")


class TestPreferredValuesAndElectricalChecks(unittest.TestCase):
    def test_next_preferred_values_round_up_for_minimum_current_limiter(self):
        self.assertEqual(next_preferred_value(101, "E12"), 120)
        self.assertEqual(next_preferred_value(101, "E24"), 110)
        self.assertAlmostEqual(next_preferred_value(0.1, "E6"), 0.1)
        self.assertGreaterEqual(next_preferred_value(153, "E96"), 153)

    def test_preferred_value_selection_rejects_invalid_requests(self):
        for minimum, series in ((0, "E12"), (-1, "E12"), (True, "E12"), (10, "E48")):
            with self.subTest(minimum=minimum, series=series), self.assertRaises(ValueError):
                next_preferred_value(minimum, series)

    def test_nearest_preferred_value_selects_e12_capacitor_value(self):
        self.assertEqual(nearest_preferred_value(23.4e-9), 22e-9)
        self.assertEqual(nearest_preferred_value(1.2e3), 1.2e3)

    def test_parallel_source_check_understands_scaled_and_formatted_values(self):
        raw = {"components": [
            {"id": "V1", "type": "dc_source", "value": "9000mV"},
            {"id": "V2", "type": "battery", "value": "10 V"},
        ], "nets": [
            {"name": "P", "pins": ["V1.p", "V2.p"]},
            {"name": "N", "pins": ["V1.n", "V2.n"]},
        ]}
        report = check_electrical_rules(raw)
        self.assertIn("CONFLICTING_VOLTAGE_SOURCES", {issue.code for issue in report.errors})


if __name__ == "__main__":
    unittest.main()
