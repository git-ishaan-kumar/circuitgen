"""Tests for the CircuitGen CLI entrypoint, package execution, and packaging."""
from __future__ import annotations

import subprocess
import sys
import unittest
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
        with patch("sys.stdin.isatty", return_value=True):
            exit_code = main([])
        self.assertEqual(exit_code, 0)
        mock_run.assert_called_once()

    @patch.object(CircuitGenApp, "run")
    def test_main_no_args_without_a_terminal_does_not_launch_tui(self, mock_run):
        with patch("sys.stdin.isatty", return_value=False), patch("sys.stderr") as stderr:
            exit_code = main([])
        self.assertEqual(exit_code, 2)
        mock_run.assert_not_called()
        self.assertIn("needs a terminal", stderr.write.call_args[0][0])

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
        self.assertIn("CircuitGen: Circuit schematics", res.stdout)

    def test_package_main_subprocess_version(self):
        """Verify python -m circuitgen --version works as a reliable entrypoint."""
        res = subprocess.run(
            [sys.executable, "-m", "circuitgen", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn(__version__, res.stdout)

    def test_package_main_subprocess_help(self):
        """Verify python -m circuitgen --help works as a reliable entrypoint."""
        res = subprocess.run(
            [sys.executable, "-m", "circuitgen", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("CircuitGen: Circuit schematics", res.stdout)

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
        """Verify console script entrypoint circuitgen is registered in metadata."""
        if sys.version_info >= (3, 10):
            from importlib.metadata import entry_points

            eps = entry_points(group="console_scripts")
            cg_eps = [ep for ep in eps if ep.name == "circuitgen"]
            self.assertTrue(len(cg_eps) >= 1, "circuitgen console script not found in metadata")
            self.assertEqual(cg_eps[0].value, "circuitgen.cli:main")
