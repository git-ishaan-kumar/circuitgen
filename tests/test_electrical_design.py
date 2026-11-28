from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from circuitgen.ai import NetlistGenerationError, SCHEMA, generate_netlist
from circuitgen.engine import make_svg_from_netlist, validate_model


def response(netlist):
    return json.dumps(netlist)


def led_netlist(resistance):
    return {
        "components": [
            {"id": "V1", "type": "battery", "value": "9V"},
            {"id": "R1", "type": "resistor", "value": resistance},
            {"id": "D1", "type": "led", "value": "red"},
        ],
        "nets": [
            {"name": "SUPPLY", "pins": ["V1.p", "R1.a"]},
            {"name": "NET_LED1_ANODE", "pins": ["R1.b", "D1.a"]},
            {"name": "GND", "pins": ["D1.b", "V1.n"]},
        ],
    }


def divider_netlist(upper, lower):
    return {
        "components": [
            {"id": "V1", "type": "battery", "value": "9V"},
            {"id": "R1", "type": "resistor", "value": upper},
            {"id": "R2", "type": "resistor", "value": lower},
        ],
        "nets": [
            {"name": "SUPPLY", "pins": ["V1.p", "R1.a"]},
            {"name": "DIVIDER_OUTPUT", "pins": ["R1.b", "R2.a"]},
            {"name": "GND", "pins": ["R2.b", "V1.n"]},
        ],
    }


def coupled_filter_netlist(upper, lower, series_filter):
    netlist = {
        "components": [
            {"id": "V1", "type": "dc_source", "value": "9 V"},
            {"id": "R1", "type": "resistor", "value": "470 Ω"},
            {"id": "D1", "type": "led", "value": "red"},
            {"id": "R2", "type": "resistor", "value": "470 Ω"},
            {"id": "D2", "type": "led", "value": "red"},
            {"id": "R3", "type": "resistor", "value": upper},
            {"id": "R4", "type": "resistor", "value": lower},
            {"id": "R5", "type": "resistor", "value": series_filter},
            {"id": "C1", "type": "capacitor", "value": "100n"},
        ],
        "nets": [
            {"name": "N_9V", "pins": ["V1.p", "R1.a", "R2.a", "R3.a"]},
            {"name": "N_GND", "pins": ["V1.n", "D1.b", "D2.b", "R4.b", "C1.b"]},
            {"name": "N_LED1", "pins": ["R1.b", "D1.a"]},
            {"name": "N_LED2", "pins": ["R2.b", "D2.a"]},
            {"name": "N_DIV", "pins": ["R3.b", "R4.a", "R5.a"]},
            {"name": "N_LPF", "pins": ["R5.b", "C1.a"]},
        ],
    }
    return netlist


class TestGeneratedNameCompatibility(unittest.TestCase):
    def test_long_valid_net_name_uses_shared_supported_rules_and_renders(self):
        raw = led_netlist("470 ohms")
        model = validate_model(raw)

        self.assertIn("NET_LED1_ANODE", model.nets)
        self.assertIn("<svg", make_svg_from_netlist(raw))

    def test_ai_schema_restricts_names_to_engine_identifier_rules(self):
        component = SCHEMA["properties"]["components"]["items"]["properties"]["id"]
        net_name = SCHEMA["properties"]["nets"]["items"]["properties"]["name"]
        self.assertEqual(component["pattern"], net_name["pattern"])
        self.assertRegex("NET_LED1_ANODE", net_name["pattern"])
        self.assertNotRegex("NET-LED1-ANODE", net_name["pattern"])


class TestElectricalTargetVerification(unittest.TestCase):
    @patch("circuitgen.ai._gemini")
    def test_ai_netlist_values_use_component_aware_rkm_formatter(self, provider):
        provider.return_value = response(led_netlist("5k1_ohm"))
        result = generate_netlist(
            "Draw a 9V battery, resistor, and red LED in series.", api_key="test-key")

        self.assertEqual(result["components"][1]["value"], "5.1 k\u03a9")

    @patch("circuitgen.ai._gemini")
    def test_provider_470R_value_is_not_misread_as_an_si_prefix(self, provider):
        provider.return_value = response(led_netlist("470R"))
        result = generate_netlist(
            "Connect a red LED to a 9V battery, targeting 15 mA through a series resistor.",
            api_key="test-key",
        )

        self.assertEqual(provider.call_count, 1)
        self.assertEqual(result["components"][1]["value"], "470 \u03a9")

    @patch("circuitgen.ai._gemini")
    def test_led_resistance_is_repaired_from_calculated_current_target(self, provider):
        provider.side_effect = [response(led_netlist("390 ohms")), response(led_netlist("470 ohms"))]
        result = generate_netlist(
            "Connect a red LED to a 9V battery, targeting 15 mA through a series resistor.",
            api_key="test-key",
        )

        self.assertEqual(result["components"][1]["value"], "470 Ω")
        self.assertEqual(provider.call_count, 2)
        correction = provider.call_args_list[1].args[0]
        self.assertIn("17.9 mA", correction)
        self.assertIn("next E12 value is 470 Ω", correction)

    @patch("circuitgen.ai._gemini")
    def test_inferred_divider_values_are_checked_against_requested_output(self, provider):
        provider.side_effect = [
            response(divider_netlist("1.5k", "3.3k")),
            response(divider_netlist("6.8k", "3.3k")),
        ]
        result = generate_netlist(
            "Create a 3V voltage divider from a 9V supply using two resistors.",
            api_key="test-key",
        )

        self.assertEqual(result["components"][1]["value"], "6.8 kΩ")
        self.assertEqual(provider.call_count, 2)
        self.assertIn("produces about 6.19 V", provider.call_args_list[1].args[0])
        self.assertIn("Rupper/Rlower is about 0.455:1", provider.call_args_list[1].args[0])
        self.assertIn("target calls for about 2:1", provider.call_args_list[1].args[0])

    @patch("circuitgen.ai._gemini")
    def test_explicit_mismatched_limiter_value_is_kept_and_reported(self, provider):
        provider.return_value = response(led_netlist("390 ohms"))
        prompt = (
            "Connect a red LED to a 9V battery through the explicitly requested "
            "390 ohm resistor, targeting 15 mA."
        )

        with self.assertRaises(NetlistGenerationError) as caught:
            generate_netlist(prompt, api_key="test-key")

        self.assertEqual(provider.call_count, 1)
        self.assertIn("explicitly requested", str(caught.exception))
        self.assertEqual(caught.exception.netlist["components"][1]["value"], "390 Ω")

    def test_correct_inferred_values_pass_checks(self):
        from circuitgen.electrical_design import check_design_targets

        led_model = validate_model(led_netlist("470 ohms"))
        divider_model = validate_model(divider_netlist("6.8k", "3.3k"))
        self.assertFalse(check_design_targets(
            "A red LED from a 9V battery targeting 15mA", led_model))
        self.assertFalse(check_design_targets(
            "Create a 3V voltage divider from a 9V supply", divider_model))

    def test_loaded_divider_and_rc_filter_targets_use_connected_network(self):
        from circuitgen.electrical_design import check_design_targets

        model = validate_model(coupled_filter_netlist("1.5k", "3k", "1.6k"))
        mismatches = check_design_targets(
            "Two parallel red LED branches targeting 15 mA per LED, a voltage divider "
            "producing approximately 3 V, and an RC low-pass filter with a cutoff "
            "frequency approximately 1 kHz.", model)

        messages = " ".join(item.message for item in mismatches)
        self.assertIn("net N_DIV", messages)
        self.assertIn("produces about 6 V", messages)
        self.assertIn("Rupper/Rlower is about 0.5:1", messages)
        self.assertIn("not the requested 3 V", messages)
        self.assertIn("about 612 Hz", messages)
        self.assertIn("equivalent resistance 2.6", messages)
        self.assertEqual(len([item for item in mismatches if "LED current" in item.message]), 0)

    def test_repaired_loaded_divider_and_rc_filter_pass_targets(self):
        from circuitgen.electrical_design import check_design_targets

        model = validate_model(coupled_filter_netlist("3.3k", "1.6k", "510"))
        mismatches = check_design_targets(
            "Two parallel red LED branches targeting 15 mA per LED, a voltage divider "
            "producing approximately 3 V, and an RC low-pass filter with a cutoff "
            "frequency approximately 1 kHz.", model)
        self.assertFalse(mismatches)

    def test_rc_check_runs_when_divider_voltage_is_already_correct(self):
        from circuitgen.electrical_design import check_design_targets

        model = validate_model(coupled_filter_netlist("3k", "1.5k", "1.6k"))
        mismatches = check_design_targets(
            "A voltage divider producing 3 V drives an RC low-pass filter with a "
            "cutoff frequency of 1 kHz.", model)

        messages = " ".join(item.message for item in mismatches)
        self.assertNotIn("Voltage-divider target check failed", messages)
        self.assertIn("612 Hz", messages)
        self.assertIn("2.6e+03", messages)

    @patch("circuitgen.ai._gemini")
    def test_generation_repairs_filter_after_correct_divider_passes(self, provider):
        first = coupled_filter_netlist("3k", "1k5", "1k6")
        first["components"][1]["value"] = "470R"
        first["components"][3]["value"] = "470R"
        corrected = coupled_filter_netlist("3k", "1k5", "510")
        corrected["components"][1]["value"] = "470R"
        corrected["components"][3]["value"] = "470R"
        provider.side_effect = [response(first), response(corrected)]
        result = generate_netlist(
            "Design a 9 V circuit with two parallel red LED branches targeting 15 mA "
            "per LED, a voltage divider producing approximately 3 V, and an RC "
            "low-pass filter with a cutoff frequency approximately 1 kHz.",
            api_key="test-key",
        )

        self.assertEqual(provider.call_count, 2)
        self.assertIn("612 Hz", provider.call_args_list[1].args[0])
        self.assertIn("equivalent resistance 2.6", provider.call_args_list[1].args[0])
        self.assertEqual(result["components"][7]["value"], "510 \u03a9")

    @patch("circuitgen.ai._gemini")
    def test_repeated_bad_corrections_get_deterministic_inferred_value_repair(self, provider):
        from circuitgen.electrical_design import check_design_targets

        failed = coupled_filter_netlist("20k", "10k", "120")
        failed["components"][1]["value"] = "390 \u03a9"
        failed["components"][3]["value"] = "390 \u03a9"
        failed["components"][7]["value"] = "120 \u03a9"
        failed["components"][8]["value"] = "1000 nF"
        provider.return_value = response(failed)
        prompt = (
            "Design a 9 V circuit with two parallel red LED branches targeting 15 mA "
            "per LED, a voltage divider producing approximately 3 V, and an RC "
            "low-pass filter with a cutoff frequency approximately 1 kHz."
        )

        result = generate_netlist(prompt, api_key="test-key")

        values = {item["id"]: item["value"] for item in result["components"]}
        self.assertEqual(provider.call_count, 3)
        self.assertEqual(values["R1"], "470 \u03a9")
        self.assertEqual(values["R2"], "470 \u03a9")
        self.assertEqual(values["C1"], "22 nF")
        self.assertFalse(check_design_targets(prompt, validate_model(result)))
        self.assertIn("requires about 159 \u03a9 total resistance", provider.call_args_list[-1].args[0])

    @patch("circuitgen.ai._gemini")
    def test_deterministic_repair_preserves_explicit_capacitor_value(self, provider):
        failed = coupled_filter_netlist("20k", "10k", "120")
        failed["components"][1]["value"] = "390 \u03a9"
        failed["components"][3]["value"] = "390 \u03a9"
        failed["components"][8]["value"] = "1 uF"
        provider.return_value = response(failed)

        with self.assertRaises(NetlistGenerationError) as caught:
            generate_netlist(
                "Design a 9 V circuit with two parallel red LED branches targeting 15 mA "
                "per LED, a voltage divider producing approximately 3 V, a 1 uF "
                "capacitor, and an RC low-pass cutoff of approximately 1 kHz.",
                api_key="test-key",
            )

        self.assertEqual(caught.exception.netlist["components"][8]["value"], "1 \u00b5F")

    def test_rkm_led_values_and_divider_thevenin_resistance_are_checked_together(self):
        from circuitgen.electrical_design import check_design_targets
        from circuitgen.values import normalize_netlist_values

        raw = coupled_filter_netlist("3k", "1k5", "1k6")
        raw["components"][1]["value"] = "470R"
        raw["components"][3]["value"] = "470R"
        model = validate_model(normalize_netlist_values(raw))
        mismatches = check_design_targets(
            "Two parallel red LED branches targeting 15 mA per LED, a voltage divider "
            "producing approximately 3 V, and an RC low-pass filter with a cutoff "
            "frequency approximately 1 kHz.", model)

        self.assertFalse([item for item in mismatches if "LED current" in item.message])
        self.assertTrue(any("612 Hz" in item.message and "2.6e+03" in item.message
                            for item in mismatches))

    @patch("circuitgen.ai._gemini")
    def test_connected_circuit_errors_trigger_a_general_repair(self, provider):
        provider.side_effect = [
            response(coupled_filter_netlist("1.5k", "3k", "1.6k")),
            response(coupled_filter_netlist("3.3k", "1.6k", "510")),
        ]
        result = generate_netlist(
            "Design a 9 V circuit with two parallel red LED branches targeting 15 mA "
            "per LED, a voltage divider producing approximately 3 V, and an RC "
            "low-pass filter with a cutoff frequency approximately 1 kHz.",
            api_key="test-key",
        )

        self.assertEqual(provider.call_count, 2)
        correction = provider.call_args_list[1].args[0]
        self.assertIn("N_DIV", correction)
        self.assertIn("612 Hz", correction)
        self.assertEqual(result["components"][5]["value"], "3.3 kΩ")
        self.assertEqual(result["components"][6]["value"], "1.6 kΩ")
        self.assertEqual(result["components"][7]["value"], "510 Ω")


if __name__ == "__main__":
    unittest.main()
