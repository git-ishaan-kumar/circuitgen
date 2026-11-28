from __future__ import annotations

import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from circuitgen import (
    CircuitError,
    CircuitModel,
    CircuitResult,
    ValidationResult,
    from_netlist,
    generate,
    list_providers,
    list_symbols,
    render,
    validate,
)
from circuitgen.values import normalize_netlist_values


# FIXTURES

SAMPLE_NETLIST = {
    "components": [
        {"id": "V1", "type": "battery", "value": "9V"},
        {"id": "R1", "type": "resistor", "value": "330Ω"},
        {"id": "D1", "type": "led", "value": "red"},
    ],
    "nets": [
        {"name": "VCC", "pins": ["V1.p", "R1.a"]},
        {"name": "MID", "pins": ["R1.b", "D1.a"]},
        {"name": "GND", "pins": ["D1.b", "V1.n"]},
    ],
}

INVALID_NETLIST = {
    "components": [
        {"id": "R1", "type": "resistor", "value": "10k"},
    ],
    "nets": [
        {"name": "N1", "pins": ["R1.a", "R1.bad_pin"]},
    ],
}


# TESTS

class TestPublicAPI(unittest.TestCase):
    def test_list_symbols(self):
        symbols = list_symbols()
        self.assertIsInstance(symbols, list)
        self.assertIn("resistor", symbols)
        self.assertIn("battery", symbols)
        self.assertIn("led", symbols)
        self.assertEqual(symbols, sorted(symbols))

    def test_list_providers(self):
        providers = list_providers()
        self.assertIsInstance(providers, list)
        self.assertIn("gemini", providers)
        self.assertIn("openai", providers)
        self.assertIn("anthropic", providers)

    def test_validate_valid(self):
        res = validate(SAMPLE_NETLIST)
        self.assertIsInstance(res, ValidationResult)
        self.assertTrue(res.valid)
        self.assertEqual(res.errors, [])
        self.assertIsInstance(res.model, CircuitModel)

    def test_validate_invalid(self):
        res = validate(INVALID_NETLIST)
        self.assertIsInstance(res, ValidationResult)
        self.assertFalse(res.valid)
        self.assertGreater(len(res.errors), 0)
        self.assertIsNone(res.model)

    def test_validate_exposes_separate_electrical_findings(self):
        raw = {"components": [{"id": "V1", "type": "battery", "value": "9V"}],
               "nets": [{"name": "SHORT", "pins": ["V1.p", "V1.n"]}]}
        result = validate(raw)
        self.assertTrue(result.valid)
        self.assertIsNotNone(result.electrical_report)
        self.assertIn("SHORTED_VOLTAGE_SOURCE",
                      {issue.code for issue in result.electrical_report.errors})

    def test_from_netlist_memory(self):
        res = from_netlist(SAMPLE_NETLIST, output=None)
        self.assertIsInstance(res, CircuitResult)
        self.assertIn("<svg", res.svg)
        self.assertIn("</svg>", res.svg)
        self.assertEqual(res.netlist, normalize_netlist_values(SAMPLE_NETLIST))
        self.assertEqual(SAMPLE_NETLIST["components"][0]["value"], "9V")
        self.assertIsInstance(res.model, CircuitModel)
        self.assertIsNone(res.output_path)

    def test_from_netlist_file_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "circuit.svg"
            res = from_netlist(SAMPLE_NETLIST, output=out_file)
            self.assertTrue(out_file.exists())
            self.assertEqual(res.output_path, str(out_file))
            self.assertEqual(out_file.read_text(encoding="utf-8"), res.svg)

    def test_relative_output_path_uses_root_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = Path.cwd()
            try:
                os.chdir(tmp)
                res = from_netlist(SAMPLE_NETLIST, output="circuit.svg")
                self.assertEqual(res.output_path, str(Path(tmp) / "circuit.svg"))
                self.assertTrue((Path(tmp) / "circuit.svg").exists())
            finally:
                os.chdir(original_dir)

    def test_omitted_output_uses_root_default_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = Path.cwd()
            try:
                os.chdir(tmp)
                res = from_netlist(SAMPLE_NETLIST)
                self.assertEqual(res.output_path, str(Path(tmp) / "circuit.svg"))
                self.assertTrue((Path(tmp) / "circuit.svg").exists())
            finally:
                os.chdir(original_dir)

    def test_empty_output_path_uses_root_default_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = Path.cwd()
            try:
                os.chdir(tmp)
                res = from_netlist(SAMPLE_NETLIST, output="")
                self.assertEqual(res.output_path, str(Path(tmp) / "circuit.svg"))
                self.assertTrue((Path(tmp) / "circuit.svg").exists())
            finally:
                os.chdir(original_dir)

    def test_circuit_result_save(self):
        res = from_netlist(SAMPLE_NETLIST, output=None)
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "sub" / "saved.svg"
            returned_path = res.save(out_file)
            self.assertTrue(out_file.exists())
            self.assertEqual(returned_path, str(out_file))
            self.assertEqual(res.output_path, str(out_file))

    def test_from_netlist_invalid_raises(self):
        with self.assertRaises(CircuitError):
            from_netlist(INVALID_NETLIST)

    @patch("circuitgen.api.make_svg_from_netlist", side_effect=CircuitError("No collision-free route"))
    def test_from_netlist_render_error_keeps_input_netlist(self, _render):
        from circuitgen import NetlistRenderError

        with self.assertRaises(NetlistRenderError) as caught:
            from_netlist(SAMPLE_NETLIST, output=None)

        self.assertEqual(caught.exception.netlist, SAMPLE_NETLIST)
        self.assertIn("No collision-free route", str(caught.exception))

    def test_render_with_model(self):
        check = validate(SAMPLE_NETLIST)
        self.assertTrue(check.valid)
        svg = render(check.model)
        self.assertIn("<svg", svg)

    def test_render_with_dict(self):
        svg = render(SAMPLE_NETLIST)
        self.assertIn("<svg", svg)

    def test_render_invalid_type_raises(self):
        with self.assertRaises(TypeError):
            render("not a model or dict")

    def test_custom_ic_pins(self):
        custom = {
            "components": [
                {"id": "U1", "type": "sensor", "value": "TMP36", "pins": ["VCC", "VOUT", "GND"]},
                {"id": "V1", "type": "battery", "value": "5V"},
            ],
            "nets": [
                {"name": "PWR", "pins": ["V1.p", "U1.VCC"]},
                {"name": "GND", "pins": ["V1.n", "U1.GND"]},
            ],
        }
        res = validate(custom)
        self.assertTrue(res.valid)
        out = from_netlist(custom, output=None)
        self.assertIn("<svg", out.svg)

    @patch("circuitgen.api.generate_netlist")
    def test_generate_mocked(self, mock_ai):
        mock_ai.return_value = SAMPLE_NETLIST
        res = generate("Create an LED circuit", provider="openai", model="gpt-4o", output=None)
        mock_ai.assert_called_once_with(
            "Create an LED circuit",
            provider="openai",
            model="gpt-4o",
            correction="",
        )
        self.assertIsInstance(res, CircuitResult)
        self.assertEqual(res.netlist, normalize_netlist_values(SAMPLE_NETLIST))
        self.assertIn("<svg", res.svg)


if __name__ == "__main__":
    unittest.main()
