"""Comprehensive automated tests for CircuitGen installation, PATH setup, diagnostics, and CLI reliability."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import circuitgen
from circuitgen import __version__
from circuitgen.cli import build_parser, get_version, launch_tui, main
from circuitgen.doctor import (
    CheckResult,
    check_circuitgen_package,
    check_config_directory,
    check_credential_store,
    check_launcher_and_path,
    check_os_and_arch,
    check_package_resources,
    check_python_environment,
    check_runtime_dependencies,
    check_terminal_capabilities,
    check_virtual_environment,
    check_working_directory,
    run_doctor,
)
from circuitgen.syspath import (
    broadcast_environment_change,
    find_installed_launcher,
    get_candidate_script_directories,
    get_effective_path_entries,
    get_persistent_windows_user_path,
    is_virtual_environment,
    is_windows,
    is_wsl,
    normalize_path,
    setup_windows_path,
    write_persistent_windows_user_path,
)


class TestInstallationAndPackaging(unittest.TestCase):
    """Test built package distributions, resource inclusion, and entrypoints."""

    def test_version_helper_and_metadata(self):
        ver = get_version()
        self.assertTrue(len(ver) > 0)
        self.assertIn(__version__, ver)

    def test_built_wheel_contains_required_resources(self):
        wheel_name = os.environ.get("CIRCUITGEN_TEST_WHEEL")
        if not wheel_name:
            self.skipTest("Set CIRCUITGEN_TEST_WHEEL to a freshly built wheel")
        wheel_path = Path(wheel_name)
        with zipfile.ZipFile(wheel_path, "r") as zf:
            namelist = zf.namelist()
            # Verify package data: theme.tcss must be inside wheel!
            self.assertTrue(
                any(n.endswith("circuitgen/tui/theme.tcss") for n in namelist),
                "circuitgen/tui/theme.tcss missing from built wheel!",
            )
            # Verify entry_points.txt exists in dist-info
            self.assertTrue(
                any(n.endswith("entry_points.txt") for n in namelist),
                "entry_points.txt missing from built wheel!",
            )
            # Verify entry_points.txt content declares circuit
            for name in namelist:
                if name.endswith("entry_points.txt"):
                    content = zf.read(name).decode("utf-8")
                    self.assertIn("circuit = circuitgen.cli:main", content)

    def test_help_and_version_outside_repository(self):
        """Commands must run successfully from any working directory outside the repo."""
        temp_dir = tempfile.gettempdir()
        res_ver = subprocess.run(
            [sys.executable, "-m", "circuitgen", "--version"],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res_ver.returncode, 0)
        self.assertIn(__version__, res_ver.stdout)

        res_help = subprocess.run(
            [sys.executable, "-m", "circuitgen", "--help"],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res_help.returncode, 0)
        self.assertIn("CircuitGen: A Python library and CLI for generating circuit schematics from text descriptions or netlists.", " ".join(res_help.stdout.split()))
        self.assertIn("setup-path", res_help.stdout)
        self.assertIn("doctor", res_help.stdout)

    def test_invalid_cli_argument_exits_with_error(self):
        res = subprocess.run(
            [sys.executable, "-m", "circuitgen", "nonexistent-subcommand"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 2)
        self.assertIn("nonexistent-subcommand", res.stderr)


class TestPathAndEnvironmentUtilities(unittest.TestCase):
    """Test PATH discovery, normalization, and environment detection."""

    def test_normalize_path(self):
        p1 = normalize_path("C:/Users/Test/../Test/Scripts")
        p2 = normalize_path("C:\\Users\\Test\\Scripts")
        if sys.platform == "win32":
            self.assertEqual(p1.lower(), p2.lower())

    def test_is_wsl_detection(self):
        # On native Windows, is_wsl must be False
        if sys.platform == "win32":
            self.assertFalse(is_wsl())

    def test_candidate_directories(self):
        candidates = get_candidate_script_directories()
        self.assertIsInstance(candidates, list)
        self.assertTrue(len(candidates) > 0)
        # All candidates must be resolved Path objects and directories
        for c in candidates:
            self.assertIsInstance(c, Path)
            self.assertTrue(c.is_dir())

    def test_get_effective_path_entries(self):
        entries = get_effective_path_entries()
        self.assertIsInstance(entries, list)
        self.assertTrue(len(entries) > 0)

    def test_find_installed_launcher_when_missing(self):
        # With empty candidates and no mock which, should return None
        with tempfile.TemporaryDirectory() as empty_dir:
            launcher = find_installed_launcher(candidate_dirs=[Path(empty_dir)])
            # If not in PATH either
            with patch("shutil.which", return_value=None):
                launcher = find_installed_launcher(candidate_dirs=[Path(empty_dir)])
                self.assertIsNone(launcher)

    def test_find_installed_launcher_found_in_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            dummy_dir = Path(td)
            exe_name = "circuit.exe" if sys.platform == "win32" else "circuit"
            dummy_exe = dummy_dir / exe_name
            dummy_exe.write_text("#!/bin/sh\n")
            found = find_installed_launcher(candidate_dirs=[dummy_dir])
            self.assertIsNotNone(found)
            self.assertEqual(found.resolve(), dummy_exe.resolve())


class TestWindowsRegistryPathSetup(unittest.TestCase):
    """Test Windows PATH setup with mocks. Never modifies real user PATH."""

    @patch("circuitgen.syspath.is_windows", return_value=False)
    @patch("circuitgen.syspath.is_wsl", return_value=False)
    def test_setup_path_on_non_windows(self, mock_wsl, mock_win):
        out = io.StringIO()
        err = io.StringIO()
        code = setup_windows_path(yes=True, stdout=out, stderr=err)
        self.assertEqual(code, 0)
        self.assertIn("Automated PATH setup is only applicable on native Windows", out.getvalue())

    @patch("circuitgen.syspath.is_wsl", return_value=True)
    def test_setup_path_on_wsl(self, mock_wsl):
        out = io.StringIO()
        err = io.StringIO()
        code = setup_windows_path(yes=True, stdout=out, stderr=err)
        self.assertEqual(code, 0)
        self.assertIn("Detected Windows Subsystem for Linux (WSL)", out.getvalue())

    @patch("circuitgen.syspath.is_windows", return_value=True)
    @patch("circuitgen.syspath.is_wsl", return_value=False)
    @patch("circuitgen.syspath.find_installed_launcher", return_value=None)
    def test_setup_path_launcher_not_found(self, mock_launcher, mock_wsl, mock_win):
        out = io.StringIO()
        err = io.StringIO()
        code = setup_windows_path(yes=True, stdout=out, stderr=err)
        self.assertEqual(code, 1)
        self.assertIn("Could not find 'circuit.exe'", err.getvalue())

    @patch("circuitgen.syspath.is_windows", return_value=True)
    @patch("circuitgen.syspath.is_wsl", return_value=False)
    def test_setup_path_already_configured_and_effective(self, mock_wsl, mock_win):
        with tempfile.TemporaryDirectory() as td:
            dummy_dir = Path(td)
            dummy_exe = dummy_dir / "circuit.exe"
            dummy_exe.touch()

            with patch("circuitgen.syspath.find_installed_launcher", return_value=dummy_exe), \
                 patch("circuitgen.syspath.get_persistent_windows_user_path", return_value=(str(dummy_dir), 2)), \
                 patch("circuitgen.syspath.get_effective_path_entries", return_value=[str(dummy_dir)]):
                out = io.StringIO()
                err = io.StringIO()
                code = setup_windows_path(yes=True, stdout=out, stderr=err)
                self.assertEqual(code, 0)
                self.assertIn("already in your persistent User PATH and active in this terminal", out.getvalue())

    @patch("circuitgen.syspath.is_windows", return_value=True)
    @patch("circuitgen.syspath.is_wsl", return_value=False)
    def test_setup_path_already_configured_needs_restart(self, mock_wsl, mock_win):
        with tempfile.TemporaryDirectory() as td:
            dummy_dir = Path(td)
            dummy_exe = dummy_dir / "circuit.exe"
            dummy_exe.touch()

            with patch("circuitgen.syspath.find_installed_launcher", return_value=dummy_exe), \
                 patch("circuitgen.syspath.get_persistent_windows_user_path", return_value=(str(dummy_dir), 2)), \
                 patch("circuitgen.syspath.get_effective_path_entries", return_value=["C:\\SomeOtherDir"]):
                out = io.StringIO()
                err = io.StringIO()
                code = setup_windows_path(yes=True, stdout=out, stderr=err)
                self.assertEqual(code, 0)
                self.assertIn("Please close and restart your terminal", out.getvalue())

    @patch("circuitgen.syspath.is_windows", return_value=True)
    @patch("circuitgen.syspath.is_wsl", return_value=False)
    def test_setup_path_check_only_flag(self, mock_wsl, mock_win):
        with tempfile.TemporaryDirectory() as td:
            dummy_dir = Path(td)
            dummy_exe = dummy_dir / "circuit.exe"
            dummy_exe.touch()

            with patch("circuitgen.syspath.find_installed_launcher", return_value=dummy_exe), \
                 patch("circuitgen.syspath.get_persistent_windows_user_path", return_value=("C:\\ExistingDir", 2)), \
                 patch("circuitgen.syspath.get_effective_path_entries", return_value=[]):
                out = io.StringIO()
                err = io.StringIO()
                code = setup_windows_path(yes=False, check_only=True, stdout=out, stderr=err)
                self.assertEqual(code, 1)
                self.assertIn("[NEEDS SETUP]", out.getvalue())

    @patch("circuitgen.syspath.is_windows", return_value=True)
    @patch("circuitgen.syspath.is_wsl", return_value=False)
    def test_setup_path_user_cancels_prompt(self, mock_wsl, mock_win):
        with tempfile.TemporaryDirectory() as td:
            dummy_dir = Path(td)
            dummy_exe = dummy_dir / "circuit.exe"
            dummy_exe.touch()

            with patch("circuitgen.syspath.find_installed_launcher", return_value=dummy_exe), \
                 patch("circuitgen.syspath.get_persistent_windows_user_path", return_value=("", 2)), \
                 patch("circuitgen.syspath.get_effective_path_entries", return_value=[]), \
                 patch("builtins.input", return_value="n"):
                out = io.StringIO()
                err = io.StringIO()
                code = setup_windows_path(yes=False, stdout=out, stderr=err)
                self.assertEqual(code, 0)
                self.assertIn("Operation cancelled by user", out.getvalue())

    @patch("circuitgen.syspath.is_windows", return_value=True)
    @patch("circuitgen.syspath.is_wsl", return_value=False)
    def test_setup_path_appends_and_broadcasts_successfully(self, mock_wsl, mock_win):
        with tempfile.TemporaryDirectory() as td:
            dummy_dir = Path(td)
            dummy_exe = dummy_dir / "circuit.exe"
            dummy_exe.touch()

            written_paths = []

            def fake_write(new_path, reg_type):
                written_paths.append((new_path, reg_type))

            with patch("circuitgen.syspath.find_installed_launcher", return_value=dummy_exe), \
                 patch("circuitgen.syspath.get_persistent_windows_user_path", return_value=("C:\\Existing", 2)), \
                 patch("circuitgen.syspath.get_effective_path_entries", return_value=[]), \
                 patch("circuitgen.syspath.write_persistent_windows_user_path", side_effect=fake_write), \
                 patch("circuitgen.syspath.broadcast_environment_change", return_value=True):
                out = io.StringIO()
                err = io.StringIO()
                code = setup_windows_path(yes=True, stdout=out, stderr=err)
                self.assertEqual(code, 0)
                self.assertIn("[SUCCESS]", out.getvalue())
                self.assertEqual(len(written_paths), 1)
                written_val, reg_type = written_paths[0]
                self.assertTrue(written_val.startswith("C:\\Existing;"))
                self.assertIn(str(dummy_dir), written_val)

    @patch("circuitgen.syspath.is_windows", return_value=True)
    @patch("circuitgen.syspath.is_wsl", return_value=False)
    def test_setup_path_registry_write_failure(self, mock_wsl, mock_win):
        with tempfile.TemporaryDirectory() as td:
            dummy_dir = Path(td)
            dummy_exe = dummy_dir / "circuit.exe"
            dummy_exe.touch()

            with patch("circuitgen.syspath.find_installed_launcher", return_value=dummy_exe), \
                 patch("circuitgen.syspath.get_persistent_windows_user_path", return_value=("", 2)), \
                 patch("circuitgen.syspath.get_effective_path_entries", return_value=[]), \
                 patch("circuitgen.syspath.write_persistent_windows_user_path", side_effect=PermissionError("Access denied")):
                out = io.StringIO()
                err = io.StringIO()
                code = setup_windows_path(yes=True, stdout=out, stderr=err)
                self.assertEqual(code, 1)
                self.assertIn("[FAIL] Failed to update Windows User PATH", err.getvalue())


class TestDoctorDiagnostics(unittest.TestCase):
    """Test read-only doctor checks, reports, and error conditions."""

    def test_check_os_and_arch(self):
        res = check_os_and_arch()
        self.assertEqual(res.status, "PASS")
        self.assertIn("Operating System", res.title)

    def test_check_python_environment(self):
        res = check_python_environment()
        self.assertEqual(res.status, "PASS")
        self.assertIn("Python Version", res.title)

    def test_check_package_and_resources(self):
        pkg_res = check_circuitgen_package()
        self.assertEqual(pkg_res.status, "PASS")

        res_res = check_package_resources()
        self.assertEqual(res_res.status, "PASS")
        self.assertIn("theme.tcss", res_res.message)

    def test_check_runtime_dependencies(self):
        deps = check_runtime_dependencies()
        self.assertEqual(len(deps), 4)
        for d in deps:
            self.assertEqual(d.status, "PASS")

    def test_check_config_directory(self):
        res = check_config_directory()
        self.assertIn(res.status, ("PASS", "WARNING"))

    def test_check_credential_store_does_not_expose_secrets(self):
        res = check_credential_store()
        self.assertIn(res.status, ("PASS", "WARNING"))
        # Must not contain API keys or secret terms
        for secret_kw in ("password", "secret_key", "token=", "sk-"):
            self.assertNotIn(secret_kw, res.message.lower())

    def test_check_terminal_capabilities(self):
        res = check_terminal_capabilities()
        self.assertIn(res.status, ("PASS", "WARNING"))

    def test_check_working_directory(self):
        res = check_working_directory()
        self.assertIn(res.status, ("PASS", "WARNING"))

    def test_run_doctor_output_and_exit_code(self):
        out = io.StringIO()
        code = run_doctor(debug=False, stdout=out)
        output = out.getvalue()
        self.assertIn("CircuitGen Doctor", output)
        self.assertIn("Operating System", output)
        self.assertIn("Doctor Summary", output)
        self.assertIn(code, (0, 1))

    def test_doctor_with_missing_dependency(self):
        with patch.dict("sys.modules", {"textual": None}):
            deps = check_runtime_dependencies()
            textual_check = next((d for d in deps if "textual" in d.title), None)
            self.assertIsNotNone(textual_check)
            self.assertEqual(textual_check.status, "FAIL")
            self.assertIn("pip install textual", textual_check.recommendation)


class TestCLIErrorHandling(unittest.TestCase):
    """Test CLI error handling and fallback behaviors."""

    def test_unsupported_python_version_prints_clean_error(self):
        with patch.object(sys, "version_info", (3, 9, 7)):
            err = io.StringIO()
            with patch("sys.stderr", err):
                code = main(["--help"])
                self.assertEqual(code, 1)
                self.assertIn("CircuitGen requires Python 3.10 or newer", err.getvalue())

    def test_keyboard_interrupt_handled_cleanly(self):
        with patch("circuitgen.cli.launch_tui", side_effect=KeyboardInterrupt):
            # main() with no args calls launch_tui
            with patch("circuitgen.cli.build_parser") as mock_parser:
                mock_args = MagicMock()
                mock_args.command = None
                mock_parser.return_value.parse_args.return_value = mock_args
                with patch("sys.stdin.isatty", return_value=True), \
                     patch("sys.stdout.isatty", return_value=True):
                    # Direct test of launch_tui KeyboardInterrupt
                    with patch("circuitgen.tui.CircuitGenApp.run", side_effect=KeyboardInterrupt):
                        code = launch_tui(debug_mode=False)
                        self.assertEqual(code, 130)

    def test_missing_dependency_handled_cleanly(self):
        with patch.dict("sys.modules", {"circuitgen.tui": None}):
            err = io.StringIO()
            with patch("sys.stderr", err):
                code = launch_tui(debug_mode=False)
                self.assertEqual(code, 1)
                self.assertIn("Missing required dependency", err.getvalue())

    def test_non_interactive_terminal_error(self):
        with patch("sys.stdin.isatty", return_value=False), \
             patch("sys.stdout.isatty", return_value=False), \
             patch.dict(os.environ, {}, clear=True):
            err = io.StringIO()
            with patch("sys.stderr", err):
                code = launch_tui(debug_mode=False)
                self.assertEqual(code, 1)
                self.assertIn("requires an interactive terminal", err.getvalue())
