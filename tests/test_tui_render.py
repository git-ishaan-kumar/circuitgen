"""Automated Pilot tests for Phase 7 Render workflow (R0, R1a, R1b, Success, Netlist View)."""
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
from circuitgen.tui.screens.render import (
    RenderFileScreen,
    RenderModeScreen,
    RenderPasteScreen,
    RenderSuccessScreen,
    ViewNetlistScreen,
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

SAMPLE_INVALID_NETLIST = """{
  "components": [
    {"id": "X1", "type": "nonexistent_component_type"}
  ],
  "nets": []
}"""


@pytest.fixture(autouse=True)
def isolated_offline_env():
    """Ensure all tests run strictly offline with no API keys."""
    ConfigService.reset_cache()
    clean_env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    with patch.dict(os.environ, clean_env, clear=True):
        with patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed", overwrite_confirmation=True)):
            yield
    ConfigService.reset_cache()


def test_home_to_render_mode_navigation():
    """Test navigating from HomeScreen to RenderModeScreen and back."""
    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            assert isinstance(app.screen, HomeScreen)
            menu = app.screen.query_one(SelectableMenu)
            render_idx = next(i for i, item in enumerate(menu.items) if item.key == "render")
            menu.cursor_index = render_idx
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            # Now on RenderModeScreen
            assert isinstance(app.screen, RenderModeScreen)

            # Esc returns to HomeScreen
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(_run())


def test_render_file_success_offline(tmp_path: Path):
    """Test rendering from a JSON file offline to an SVG output file."""
    netlist_file = tmp_path / "circuit.json"
    netlist_file.write_text(SAMPLE_VALID_NETLIST, encoding="utf-8")
    out_dir = tmp_path / "rendered_output"
    svg_filename = "circuit_from_file.svg"
    expected_svg = out_dir / svg_filename

    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(RenderFileScreen())
            await pilot.pause()

            # Set inputs
            app.screen.query_one("#render-input-file", EnhancedInput).value = str(netlist_file)
            app.screen.query_one("#render-output-dir", EnhancedInput).value = str(out_dir)
            app.screen.query_one("#render-filename", EnhancedInput).value = svg_filename

            # Focus menu and trigger render action
            menu = app.screen.query_one("#render-file-menu", SelectableMenu)
            menu.cursor_index = 0  # render
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            # Confirm directory creation modal if prompted
            if app.screen.__class__.__name__ == "CreateDirectoryModal":
                modal_menu = app.screen.query_one(SelectableMenu)
                modal_menu.focus()
                await pilot.press("enter")
                await pilot.pause()

            # Should transition to RenderSuccessScreen
            assert isinstance(app.screen, RenderSuccessScreen)
            assert expected_svg.exists()
            content = expected_svg.read_text(encoding="utf-8")
            assert "<svg" in content
            assert "</svg>" in content

    asyncio.run(_run())


def test_render_paste_success_offline(tmp_path: Path):
    """Test rendering from pasted JSON offline to an SVG output file."""
    out_dir = tmp_path / "paste_output"
    svg_filename = "pasted_circuit.svg"
    expected_svg = out_dir / svg_filename

    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(RenderPasteScreen())
            await pilot.pause()

            # Set pasted text and paths
            editor = app.screen.query_one("#render-paste-editor", JsonEditor)
            editor.text = SAMPLE_VALID_NETLIST
            app.screen.query_one("#render-paste-output-dir", EnhancedInput).value = str(out_dir)
            app.screen.query_one("#render-paste-filename", EnhancedInput).value = svg_filename

            # Focus menu and trigger render action
            menu = app.screen.query_one("#render-paste-menu", SelectableMenu)
            menu.cursor_index = 0  # render
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            # Confirm directory creation if prompted
            if app.screen.__class__.__name__ == "CreateDirectoryModal":
                modal_menu = app.screen.query_one(SelectableMenu)
                modal_menu.focus()
                await pilot.press("enter")
                await pilot.pause()

            assert isinstance(app.screen, RenderSuccessScreen)
            assert expected_svg.exists()
            content = expected_svg.read_text(encoding="utf-8")
            assert "<svg" in content

    asyncio.run(_run())


def test_render_file_missing_and_invalid_json(tmp_path: Path):
    """Test error feedback when netlist file is missing or contains invalid JSON."""
    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(RenderFileScreen())
            await pilot.pause()

            # 1. Nonexistent file
            app.screen.query_one("#render-input-file", EnhancedInput).value = str(tmp_path / "does_not_exist.json")
            menu = app.screen.query_one("#render-file-menu", SelectableMenu)
            menu.cursor_index = 0
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            status = app.screen.query_one("#render-file-status", Static)
            assert "File not found" in str(status.content)

            # 2. Malformed JSON file
            bad_json_file = tmp_path / "bad.json"
            bad_json_file.write_text("{\n  broken json", encoding="utf-8")
            app.screen.query_one("#render-input-file", EnhancedInput).value = str(bad_json_file)
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            status = app.screen.query_one("#render-file-status", Static)
            assert "Line" in str(status.content)

    asyncio.run(_run())


def test_render_engine_validation_failure(tmp_path: Path):
    """Test honest error reporting when JSON is valid syntax but fails engine validation."""
    invalid_file = tmp_path / "invalid_components.json"
    invalid_file.write_text(SAMPLE_INVALID_NETLIST, encoding="utf-8")

    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(RenderFileScreen())
            await pilot.pause()

            app.screen.query_one("#render-input-file", EnhancedInput).value = str(invalid_file)
            menu = app.screen.query_one("#render-file-menu", SelectableMenu)
            menu.cursor_index = 0
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            status = app.screen.query_one("#render-file-status", Static)
            assert "Invalid netlist" in str(status.content)

    asyncio.run(_run())


def test_render_overwrite_guard(tmp_path: Path):
    """Test that existing output file triggers OverwriteModal, and Cancel preserves existing file."""
    existing_file = tmp_path / "existing.svg"
    existing_file.write_text("original content", encoding="utf-8")

    netlist_file = tmp_path / "netlist.json"
    netlist_file.write_text(SAMPLE_VALID_NETLIST, encoding="utf-8")

    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(RenderFileScreen())
            await pilot.pause()

            app.screen.query_one("#render-input-file", EnhancedInput).value = str(netlist_file)
            app.screen.query_one("#render-output-dir", EnhancedInput).value = str(tmp_path)
            app.screen.query_one("#render-filename", EnhancedInput).value = "existing.svg"

            menu = app.screen.query_one("#render-file-menu", SelectableMenu)
            menu.cursor_index = 0
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            # OverwriteModal should appear
            assert app.screen.__class__.__name__ == "OverwriteModal"

            # Cancel is default option (index 0)
            modal_menu = app.screen.query_one(SelectableMenu)
            modal_menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            # Returned to RenderFileScreen without overwriting
            assert isinstance(app.screen, RenderFileScreen)
            assert existing_file.read_text(encoding="utf-8") == "original content"

    asyncio.run(_run())


def test_render_success_view_netlist_and_copy(tmp_path: Path):
    """Test ViewNetlistScreen navigation and copy action from RenderSuccessScreen."""
    target_svg = tmp_path / "success.svg"
    target_svg.write_text("<svg></svg>", encoding="utf-8")
    data = {"components": [{"id": "R1", "type": "resistor", "value": "10k"}], "nets": []}

    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(
                RenderSuccessScreen(
                    svg_path=target_svg,
                    input_source="test.json",
                    components_count=1,
                    nets_count=0,
                    netlist=data,
                )
            )
            await pilot.pause()

            # Select View netlist (index 1)
            menu = app.screen.query_one("#render-success-menu", SelectableMenu)
            menu.cursor_index = 1
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, ViewNetlistScreen)

            # Copy JSON action (index 0)
            netlist_menu = app.screen.query_one("#netlist-view-menu", SelectableMenu)
            netlist_menu.cursor_index = 0
            netlist_menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            assert "resistor" in app.clipboard

            # Back to success screen (index 1)
            netlist_menu.cursor_index = 1
            netlist_menu.focus()
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, RenderSuccessScreen)

    asyncio.run(_run())


def test_render_success_open_schematic_fallback(tmp_path: Path):
    """Test Open schematic fallback error message when system viewer is unavailable."""
    target_svg = tmp_path / "view.svg"
    target_svg.write_text("<svg></svg>", encoding="utf-8")

    async def _run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(
                RenderSuccessScreen(
                    svg_path=target_svg,
                    input_source="test.json",
                    components_count=1,
                    nets_count=0,
                    netlist={"components": [], "nets": []},
                )
            )
            await pilot.pause()

            # Mock viewer failure
            with patch("circuitgen.tui.screens.render.open_file_in_system_viewer", return_value=(False, "No viewer found")):
                menu = app.screen.query_one("#render-success-menu", SelectableMenu)
                menu.cursor_index = 0  # open
                menu.focus()
                await pilot.press("enter")
                await pilot.pause()

                status = app.screen.query_one("#render-success-status", Static)
                assert "No viewer found" in str(status.content)

    asyncio.run(_run())
