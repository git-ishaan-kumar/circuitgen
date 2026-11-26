"""Tests for the CircuitGen CLI entrypoint, package execution, and packaging."""
from __future__ import annotations

import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from circuitgen import __version__
from circuitgen.cli import build_parser, main
from circuitgen.tui import CircuitGenApp


class TestCLIEntrypoint(unittest.TestCase):
    def test_parser_version(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout"):
                parser.parse_args(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_version_uses_package_version_and_project_name(self):
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit):
            build_parser().parse_args(["--version"])
        self.assertEqual(output.getvalue().strip(), f"CircuitGen {__version__}")

        with patch("circuitgen.cli.get_version", return_value="9.8.7"):
            output = StringIO()
            with redirect_stdout(output), self.assertRaises(SystemExit):
                build_parser().parse_args(["--version"])
            self.assertEqual(output.getvalue().strip(), "CircuitGen 9.8.7")

    def test_parser_help(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout"):
                parser.parse_args(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_main_version(self):
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout"):
                main(["--version"])
        self.assertEqual(cm.exception.code, 0)

    @patch.object(CircuitGenApp, "run")
    def test_main_no_args_launches_tui(self, mock_run):
        exit_code = main([])
        self.assertEqual(exit_code, 0)
        mock_run.assert_called_once()

    def test_app_instantiation(self):
        app = CircuitGenApp()
        self.assertEqual(app.TITLE, "CircuitGen")
        self.assertIn(__version__, app.SUB_TITLE)

    def test_cli_subprocess_version(self):
        res = subprocess.run(
            [sys.executable, "-m", "circuitgen.cli", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn(__version__, res.stdout)

    def test_cli_subprocess_help(self):
        res = subprocess.run(
            [sys.executable, "-m", "circuitgen.cli", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("CircuitGen: A Python library and CLI for generating circuit schematics from text descriptions or netlists.", " ".join(res.stdout.split()))

    def test_package_main_subprocess_version(self):
        """Verify python -m circuitgen --version works as a reliable entrypoint."""
        res = subprocess.run(
            [sys.executable, "-m", "circuitgen", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), f"CircuitGen {__version__}")

    def test_package_main_subprocess_help(self):
        """Verify python -m circuitgen --help works as a reliable entrypoint."""
        res = subprocess.run(
            [sys.executable, "-m", "circuitgen", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("CircuitGen: A Python library and CLI for generating circuit schematics from text descriptions or netlists.", " ".join(res.stdout.split()))

    def test_both_entrypoints_produce_identical_version_output(self):
        """Ensure python -m circuitgen and python -m circuitgen.cli match identically."""
        res_main = subprocess.run(
            [sys.executable, "-m", "circuitgen", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        res_cli = subprocess.run(
            [sys.executable, "-m", "circuitgen.cli", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res_main.returncode, res_cli.returncode)
        self.assertEqual(res_main.stdout, res_cli.stdout)
        self.assertEqual(res_main.stderr, res_cli.stderr)

    def test_console_script_entrypoint_registered(self):
        """Verify the circuit console script is declared for installation."""
        project_file = Path(__file__).resolve().parents[1] / "pyproject.toml"
        scripts = project_file.read_text(encoding="utf-8").split("[project.scripts]", 1)[1]
        scripts = scripts.split("[", 1)[0]
        self.assertIn('circuit = "circuitgen.cli:main"', scripts)
