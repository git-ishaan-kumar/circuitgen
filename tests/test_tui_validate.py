"""Automated Pilot tests for Phase 8 Validate workflow (V0, V1a, V1b, Result, Details)."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from circuitgen.tui.app import CircuitGenApp
from circuitgen.tui.screens.home import HomeScreen
from circuitgen.tui.screens.validate import (
    NetlistCheck,
    ValidateDetailsScreen,
    ValidateFileScreen,
    ValidateModeScreen,
    ValidatePasteScreen,
    ValidateResultScreen,
)
from circuitgen.tui.services.config import AppConfig, ConfigService
from circuitgen.tui.widgets.enhanced_input import EnhancedInput
from circuitgen.tui.widgets.json_editor import JsonEditor
from circuitgen.tui.widgets.selectable_menu import SelectableMenu


SAMPLE_VALID_NETLIST = """{
  "components": [
    {"id": "B1", "type": "battery", "value": "9V"},
    {"id": "R1", "type": "resistor", "value": "330Ω"},
    {"id": "D1", "type": "led", "value": "red"}
  ],
  "nets": [
    {"name": "VCC", "pins": ["B1.p", "R1.a"]},
    {"name": "LED_POS", "pins": ["R1.b", "D1.a"]},
    {"name": "GND", "pins": ["D1.b", "B1.n"]}
  ]
}"""

SAMPLE_STRUCTURAL_INVALID = SAMPLE_VALID_NETLIST.replace('"D1.b"', '"D2.b"')

SAMPLE_ELECTRICAL_SHORT = """{
  "components": [
    {"id": "B1", "type": "battery", "value": "9V"}
  ],
  "nets": [
    {"name": "SHORT", "pins": ["B1.p", "B1.n"]}
  ]
}"""


@pytest.fixture(autouse=True)
def isolated_offline_env():
    """Ensure all tests run strictly offline with no API keys."""
    ConfigService.reset_cache()
    clean_env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    with patch.dict(os.environ, clean_env, clear=True):
        with patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed")):
            yield
    ConfigService.reset_cache()


def test_home_to_validate_mode_navigation():
    """Test navigating from HomeScreen to ValidateModeScreen and back."""
    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            assert isinstance(app.screen, HomeScreen)
            menu = app.screen.query_one(SelectableMenu)
            validate_idx = next(i for i, item in enumerate(menu.items) if item.key == "validate")
            menu.cursor_index = validate_idx
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            # Now on ValidateModeScreen
            assert isinstance(app.screen, ValidateModeScreen)

            # Esc returns to HomeScreen
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(_run())


def test_validate_file_success_offline(tmp_path: Path):
    """Test validating a valid netlist file offline with zero SVG creation."""
    netlist_file = tmp_path / "valid.json"
    netlist_file.write_text(SAMPLE_VALID_NETLIST, encoding="utf-8")

    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(ValidateFileScreen(initial_path=str(netlist_file)))
            await pilot.pause()

            menu = app.screen.query_one("#validate-file-menu", SelectableMenu)
            menu.cursor_index = 0  # validate
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, ValidateResultScreen)
            assert app.screen.check.is_valid is True
            assert app.screen.check.components_count == 3
            assert app.screen.check.nets_count == 3
            assert len(app.screen.check.errors) == 0

            # Verify no SVG files were created
            svg_files = list(tmp_path.glob("*.svg"))
            assert len(svg_files) == 0

    asyncio.run(_run())


def test_validate_paste_success_offline(tmp_path: Path):
    """Test validating pasted JSON offline with zero SVG creation."""
    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(ValidatePasteScreen())
            await pilot.pause()

            editor = app.screen.query_one("#validate-paste-editor", JsonEditor)
            editor.text = SAMPLE_VALID_NETLIST

            menu = app.screen.query_one("#validate-paste-menu", SelectableMenu)
            menu.cursor_index = 0  # validate
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, ValidateResultScreen)
            assert app.screen.check.is_valid is True
            assert app.screen.check.components_count == 3
            assert app.screen.check.nets_count == 3

    asyncio.run(_run())


def test_validate_file_missing_and_invalid_json(tmp_path: Path):
    """Test error feedback when netlist file is missing or contains invalid JSON."""
    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(ValidateFileScreen(initial_path=str(tmp_path / "missing.json")))
            await pilot.pause()

            # 1. Nonexistent file
            menu = app.screen.query_one("#validate-file-menu", SelectableMenu)
            menu.cursor_index = 0
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            status = app.screen.query_one("#validate-file-status", Static)
            assert "File not found" in str(status.content)

            # 2. Malformed JSON file
            bad_json = tmp_path / "bad.json"
            bad_json.write_text("{\n  broken json", encoding="utf-8")
            app.screen.query_one("#validate-input-file", EnhancedInput).value = str(bad_json)
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            status = app.screen.query_one("#validate-file-status", Static)
            assert "Line" in str(status.content)

    asyncio.run(_run())


def test_validate_failure_structural_and_edit_restore():
    """Test validation failure on invalid component and restoring paste in editor."""
    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(ValidatePasteScreen())
            await pilot.pause()

            editor = app.screen.query_one("#validate-paste-editor", JsonEditor)
            editor.text = SAMPLE_STRUCTURAL_INVALID

            menu = app.screen.query_one("#validate-paste-menu", SelectableMenu)
            menu.cursor_index = 0
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            # Result screen indicates failure
            assert isinstance(app.screen, ValidateResultScreen)
            assert app.screen.check.is_valid is False
            assert app.screen.check.errors == ["Unknown component: D2"]

            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ValidateDetailsScreen)
            assert str(app.screen.query_one(".warning-text", Static).content) == "Electrical checks were skipped."
            assert not app.screen.query(".diag-warning-row")
            assert not app.screen.query(".diag-pass-row")
            assert "Electrical checks were skipped." in app.screen._build_report_text()
            await pilot.press("escape")
            await pilot.pause()

            # Select Edit JSON (index 1)
            result_menu = app.screen.query_one("#validate-result-menu", SelectableMenu)
            result_menu.cursor_index = 1
            result_menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            # Returns to ValidatePasteScreen with text preserved
            assert isinstance(app.screen, ValidatePasteScreen)
            new_editor = app.screen.query_one("#validate-paste-editor", JsonEditor)
            assert new_editor.text == SAMPLE_STRUCTURAL_INVALID

    with patch("circuitgen.tui.screens.validate.check_model") as electrical_check:
        asyncio.run(_run())
        electrical_check.assert_not_called()


def test_validate_failure_electrical_short_and_details():
    """Test electrical rule diagnostics on short circuit and detailed report view."""
    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(ValidatePasteScreen())
            await pilot.pause()

            editor = app.screen.query_one("#validate-paste-editor", JsonEditor)
            editor.text = SAMPLE_ELECTRICAL_SHORT

            menu = app.screen.query_one("#validate-paste-menu", SelectableMenu)
            menu.cursor_index = 0
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, ValidateResultScreen)
            assert app.screen.check.is_valid is False
            assert any("The two terminals of voltage source B1 share net SHORT." in err for err in app.screen.check.errors)

            # View details (index 0)
            result_menu = app.screen.query_one("#validate-result-menu", SelectableMenu)
            result_menu.cursor_index = 0
            result_menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, ValidateDetailsScreen)

            # Copy report to clipboard (index 0)
            details_menu = app.screen.query_one("#validate-details-menu", SelectableMenu)
            details_menu.cursor_index = 0
            details_menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            assert "The two terminals of voltage source B1 share net SHORT." in app.clipboard

            # Back to validation summary (index 1)
            details_menu.cursor_index = 1
            details_menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, ValidateResultScreen)

    asyncio.run(_run())


def test_validate_paste_clear():
    """Test that Clear editor action empties the JsonEditor."""
    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(ValidatePasteScreen())
            await pilot.pause()

            editor = app.screen.query_one("#validate-paste-editor", JsonEditor)
            assert editor.text != ""

            menu = app.screen.query_one("#validate-paste-menu", SelectableMenu)
            menu.cursor_index = 1  # clear
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            assert editor.text == ""

    asyncio.run(_run())


def test_validate_details_color_diagnostics():
    """Test that ValidateDetailsScreen renders colored sections and status indicators."""
    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            # Test screen with both errors and warnings
            errors = ["UNDEFINED_PIN: Pin D2.a does not exist on component D2"]
            warnings = ["FLOATING_NET: Net VCC has only 1 connection"]
            screen = ValidateDetailsScreen(NetlistCheck(1, 1, errors, warnings))
            app.push_screen(screen)
            await pilot.pause()

            # Verify banner and sections
            assert len(app.screen.query(".diag-error-row")) >= 1
            assert len(app.screen.query(".diag-warning-row")) >= 1
            assert len(app.screen.query(".diag-section-header")) >= 2

    asyncio.run(_run())


def test_electrical_check_failure_is_incomplete():
    async def run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(ValidatePasteScreen(initial_text=SAMPLE_VALID_NETLIST))
            await pilot.pause()
            app.screen.query_one(SelectableMenu).focus()
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, ValidateResultScreen)
            assert not app.screen.check.is_valid
            assert "Validation incomplete" in str(
                app.screen.query_one(".validation-failed-title", Static).content
            )

            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ValidateDetailsScreen)
            report = app.screen._build_report_text()
            assert "Electrical checks could not finish." in report
            assert "Validation does not guarantee electrical safety." in report
            assert "internal error" not in report

    with patch("circuitgen.tui.screens.validate.check_model", side_effect=RuntimeError("internal error")):
        asyncio.run(run())
