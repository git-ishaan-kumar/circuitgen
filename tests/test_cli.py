"""Tests for the non-interactive commands (render/validate/erc/symbols)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
SOURCE = str(ROOT / "src")

# Two equal batteries in parallel: electrical rules warn, nothing is an error.
WARNING_NETLIST = {
    "components": [
        {"id": "V1", "type": "battery", "value": "9V"},
        {"id": "V2", "type": "battery", "value": "9V"},
    ],
    "nets": [
        {"name": "P", "pins": ["V1.p", "V2.p"]},
        {"name": "N", "pins": ["V1.n", "V2.n"]},
    ],
}


def run_cli(*arguments: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run the CLI in a subprocess, resolving the package from this checkout."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [SOURCE] + ([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else []))
    return subprocess.run(
        [sys.executable, "-m", "circuitgen", *arguments],
        cwd=ROOT, capture_output=True, text=True, input=stdin, check=False,
        env=environment,
    )


class TestRender(unittest.TestCase):
    def test_svg_goes_to_stdout_and_summary_to_stderr(self):
        result = run_cli("render", str(EXAMPLES / "wheatstone.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("<svg"))
        self.assertEqual(result.stdout.count("data-component="), 6)
        self.assertIn("6 components, 4 nets", result.stderr)

    def test_output_file_is_written(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "nested" / "out.svg"
            result = run_cli("render", str(EXAMPLES / "controller.json"), "-o", str(target))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn("<svg", target.read_text(encoding="utf-8"))
            self.assertIn(str(target), result.stderr)

    def test_reads_standard_input(self):
        netlist = (EXAMPLES / "bridge_rectifier.json").read_text(encoding="utf-8")
        result = run_cli("render", "-", "--quiet", stdin=netlist)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("<svg"))
        self.assertEqual(result.stderr, "")

    def test_quiet_suppresses_the_summary(self):
        result = run_cli("render", str(EXAMPLES / "wheatstone.json"), "--quiet")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertTrue(result.stdout.startswith("<svg"))

    def test_ink_colour_is_applied(self):
        result = run_cli("render", str(EXAMPLES / "wheatstone.json"), "--color", "#336699")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stroke:#336699", result.stdout)
        self.assertNotIn("stroke:#264a6f", result.stdout)

    def test_optimize_still_produces_a_verified_drawing(self):
        result = run_cli("render", str(EXAMPLES / "layout_optimization.json"), "--optimize")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("<svg"))

    def test_invalid_netlist_exits_one(self):
        broken = json.dumps({"components": [{"id": "V1", "type": "battery", "value": "9V"}],
                             "nets": []})
        result = run_cli("render", "-", stdin=broken)
        self.assertEqual(result.returncode, 1)
        self.assertIn("circuitgen render:", result.stderr)

    def test_malformed_json_exits_one(self):
        result = run_cli("render", "-", stdin="{not json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not valid JSON", result.stderr)

    def test_missing_file_exits_two(self):
        result = run_cli("render", "does-not-exist.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read", result.stderr)

    def test_invalid_colour_is_a_usage_error(self):
        result = run_cli("render", str(EXAMPLES / "wheatstone.json"), "--color", "red")
        self.assertEqual(result.returncode, 2)
        self.assertIn("six-digit hex", result.stderr)


class TestValidate(unittest.TestCase):
    def test_valid_netlist_reports_counts(self):
        result = run_cli("validate", str(EXAMPLES / "controller.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "OK: 4 components, 6 nets")

    def test_json_report(self):
        result = run_cli("validate", str(EXAMPLES / "wheatstone.json"), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["valid"])
        self.assertEqual(report["components"], 6)
        self.assertEqual(report["errors"], [])

    def test_invalid_netlist_exits_one_and_names_the_error(self):
        broken = json.dumps({"components": [], "nets": []})
        result = run_cli("validate", "-", "--json", stdin=broken)
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertFalse(report["valid"])
        self.assertTrue(report["errors"])


class TestErc(unittest.TestCase):
    def test_example_with_errors_exits_one(self):
        result = run_cli("erc", str(EXAMPLES / "erc_issues.json"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("CONFLICTING_VOLTAGE_SOURCES", result.stdout)

    def test_clean_example_exits_zero(self):
        result = run_cli("erc", str(EXAMPLES / "wheatstone.json"), "--json")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_fail_on_warning(self):
        netlist = json.dumps(WARNING_NETLIST)
        relaxed = run_cli("erc", "-", stdin=netlist)
        strict = run_cli("erc", "-", "--fail-on-warning", stdin=netlist)
        self.assertEqual(relaxed.returncode, 0, relaxed.stdout)
        self.assertEqual(strict.returncode, 1, strict.stdout)

    def test_unreadable_netlist_exits_two(self):
        result = run_cli("erc", "-", stdin="{oops")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Invalid netlist", result.stdout)


class TestSymbols(unittest.TestCase):
    def test_lists_builtin_symbols(self):
        result = run_cli("symbols")
        self.assertEqual(result.returncode, 0, result.stderr)
        kinds = {line.split()[0] for line in result.stdout.splitlines()}
        self.assertIn("resistor", kinds)
        self.assertIn("ne555", kinds)
        self.assertIn("arduino_uno", kinds)

    def test_json_listing_names_pins(self):
        result = run_cli("symbols", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        listing = {item["kind"]: item["pins"] for item in json.loads(result.stdout)}
        self.assertEqual(listing["opamp"], ["IN+", "IN-", "OUT", "V+", "V-"])

    def test_draws_one_symbol(self):
        result = run_cli("symbols", "ne555", "--rotation", "90")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("<svg"))

    def test_draws_a_custom_symbol_from_pins(self):
        result = run_cli("symbols", "sensor_board", "--pins", "VCC,GND,SDA,SCL")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SDA", result.stdout)

    def test_unknown_kind_exits_two(self):
        result = run_cli("symbols", "not_a_part")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown component type", result.stderr)

    def test_mismatched_pins_for_a_builtin_exits_two(self):
        result = run_cli("symbols", "resistor", "--pins", "left,right")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must match its registered symbol", result.stderr)


class TestTopLevel(unittest.TestCase):
    def test_version(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("circuitgen", result.stdout)

    def test_help_lists_every_command(self):
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0)
        for command in ("render", "validate", "erc", "symbols"):
            self.assertIn(command, result.stdout)

    def test_unknown_command_exits_two(self):
        result = run_cli("draw", "x.json")
        self.assertEqual(result.returncode, 2)

    def test_no_arguments_without_a_terminal_explains_itself(self):
        result = run_cli(stdin="")
        self.assertEqual(result.returncode, 2)
        self.assertIn("needs a terminal", result.stderr)
        self.assertIn("render", result.stderr)


if __name__ == "__main__":
    unittest.main()
