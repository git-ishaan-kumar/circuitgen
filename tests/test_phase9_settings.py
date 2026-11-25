import asyncio
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.widgets import Select, Static

from circuitgen import ClarificationRequired, SchematicStyle, from_netlist, render
from circuitgen.ai import ProviderRequestError, generate_netlist
from circuitgen.tui.app import CircuitGenApp
from circuitgen.tui.screens.color_picker import ColorGrid, ColorPicker
from circuitgen.tui.screens.render import RenderFileScreen, RenderSuccessScreen
from circuitgen.tui.screens.settings import (
    ConfirmSettings, KeySettings, ModelChoices, PreferenceForm, ProviderSettings, SettingsScreen,
)
from circuitgen.tui.screens.setup_welcome import SetupWelcomeScreen
from circuitgen.tui.services.config import AppConfig, ConfigService
from circuitgen.tui.services.credentials import CredentialService
from circuitgen.tui.widgets import EnhancedInput, SelectableMenu


def example():
    return json.loads(Path("examples/wheatstone.json").read_text(encoding="utf-8"))


def test_style_overrides_preserve_default_output():
    data = example()
    assert render(data, style=SchematicStyle()) == render(data)
    style = SchematicStyle(
        background="white", component_color="#123456", wire_color="#334455",
        text_color="#440022", show_component_ids=False, show_component_values=False,
    )
    svg = from_netlist(data, style=style).svg
    assert 'height="100%" fill="white"' in svg
    assert ".symbol,.fill{stroke:#123456}" in svg
    assert ".wire{stroke:#334455}" in svg
    assert "fill:#440022" in svg
    assert ".name,.label{display:none}" in svg
    assert '<text class="value"' not in svg
    with pytest.raises(ValueError, match="background"):
        SchematicStyle(background="url(https://example.test)")


def test_binary_exports(tmp_path):
    pytest.importorskip("resvg_py")
    image = pytest.importorskip("PIL.Image")
    data = example()
    png = render(data, output_format="png", style=SchematicStyle(background="#331122"))
    with image.open(BytesIO(png)) as decoded:
        assert decoded.getpixel((0, 0))[:3] == (51, 17, 34)
        assert decoded.width > 0 and decoded.height > 0
    target = tmp_path / "schematic.pdf"
    result = from_netlist(data, output=target)
    assert result.output_format == "pdf"
    assert target.read_bytes().startswith(b"%PDF-")
    assert result.svg.startswith("<svg")


def test_generation_preferences_reach_library():
    config = AppConfig(
        default_provider="openai", model_mode="manual", explicit_model="test-model",
        request_timeout=19, retry_transient=False, fallback_policy="auto",
        essential_clarifications=True, output_format="png",
    )
    with patch("circuitgen.generate") as generate:
        config.generate("LED circuit")
    assert generate.call_args.kwargs == {
        "provider": "openai", "model": "test-model", "timeout": 19,
        "retry_transient": False, "allow_model_fallback": True,
        "clarify": True, "style": SchematicStyle(), "output_format": "png",
    }


def test_generation_retry_fallback_and_clarification():
    recovered = '{"components":[],"nets":[]}'
    with patch("circuitgen.ai._gemini", side_effect=[
        ProviderRequestError("Unavailable", status=503, transient=True), recovered,
    ]) as request:
        generate_netlist("LED circuit", api_key="test", timeout=12, retry_transient=True)
        assert request.call_count == 2
        assert request.call_args.kwargs["timeout"] == 12
    with patch("circuitgen.ai._gemini", side_effect=[
        ProviderRequestError("Unavailable", status=404), recovered,
    ]) as request:
        generate_netlist("LED circuit", api_key="test", model="missing", allow_model_fallback=True)
        assert request.call_args_list[0].args[1] == "missing"
        assert request.call_args_list[1].args[1] != "missing"
    with patch("circuitgen.ai._gemini", return_value='{"question":"Series or parallel?"}'):
        with pytest.raises(ClarificationRequired, match="Series or parallel"):
            generate_netlist("Two resistors", api_key="test", clarify=True)


@pytest.fixture
def settings_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CIRCUITGEN_CONFIG_DIR", str(tmp_path))
    ConfigService.reset_cache()
    ConfigService.save(AppConfig(onboarding_status="completed"))
    with patch("circuitgen.tui.services.credentials.CredentialService.resolve_key", return_value=(None, "none")):
        yield
    ConfigService.reset_cache()


async def select(pilot, app, key):
    menu = app.screen.query_one(SelectableMenu)
    menu.selected_index = next(i for i, item in enumerate(menu.items) if item.key == key)
    menu.focus()
    await pilot.press("enter")
    await pilot.pause()


def test_interface_save_cancel_reset_and_reopen(settings_env):
    async def run():
        app = CircuitGenApp()
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            settings = app.screen
            menu = settings.query_one(SelectableMenu)
            menu.cursor_index = 4
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, PreferenceForm)
            await select(pilot, app, "interface_theme")
            await select(pilot, app, "light")
            await select(pilot, app, "reduced_motion")
            await select(pilot, app, "save")
            assert app.screen is settings and menu.cursor_index == 4
            assert app.theme == "light" and app.animation_level == "none"

            await select(pilot, app, "Interface")
            await select(pilot, app, "interface_theme")
            await select(pilot, app, "midnight-blue")
            await pilot.press("escape")
            assert ConfigService.load().interface_theme == "light"

            await select(pilot, app, "Interface")
            await select(pilot, app, "interface_theme")
            await select(pilot, app, "terminal")
            await select(pilot, app, "save")
            assert app.theme == "terminal" and app.native_ansi_color

            await select(pilot, app, "Interface")
            await select(pilot, app, "interface_theme")
            await select(pilot, app, "none")
            await select(pilot, app, "save")
            assert ConfigService.load(force_reload=True).terminal_colors == "none"

            menu.cursor_index = 6
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, SetupWelcomeScreen)
            await pilot.press("escape")
            assert app.screen is settings and ConfigService.load().interface_theme == "terminal"
            assert ConfigService.load().terminal_colors == "none"

            menu.cursor_index = 5
            menu.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmSettings)
            await pilot.press("down", "enter")
            await pilot.pause()
            assert app.screen is settings and app.theme == "pcb-green"
            assert ConfigService.load(force_reload=True).onboarding_status == "completed"

    with patch("circuitgen.tui.services.credentials.CredentialService.delete_key") as delete:
        asyncio.run(run())
    delete.assert_not_called()


@pytest.mark.parametrize("size", [(100, 30), (80, 24)])
def test_settings_heading_and_divider_align_with_content(size):
    async def run():
        app = CircuitGenApp()
        async with app.run_test(size=size) as pilot:
            for page in (SettingsScreen(), PreferenceForm("Output")):
                app.push_screen(page)
                await pilot.pause()
                card = page.query_one("#home-card").region
                heading = page.query_one(".breadcrumb-left").region
                divider = page.query_one(".rule").region
                assert heading.x == divider.x == card.x
                assert divider.y == heading.bottom
                assert abs(card.x - (size[0] - card.width) // 2) <= 1
                app.pop_screen()

    with (
        patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed")),
        patch.object(CredentialService, "resolve_key", return_value=(None, "none")),
    ):
        asyncio.run(run())


def test_provider_discovery_updates_draft(settings_env):
    async def run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(ProviderSettings())
            await pilot.pause()
            page = app.screen
            page.query_one("#default-provider", Select).value = "openai"
            await pilot.pause()
            await select(pilot, app, "discover")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, ModelChoices)
            await select(pilot, app, "example-model")
            assert app.screen is page
            assert page.query_one("#default-model", EnhancedInput).value == "example-model"
            assert ConfigService.load().default_provider == "gemini"
            await select(pilot, app, "save")
            config = ConfigService.load(force_reload=True)
            assert (config.default_provider, config.explicit_model) == ("openai", "example-model")

    with patch("circuitgen.tui.services.models.ModelService.discover_models", return_value=["example-model"]):
        asyncio.run(run())


def test_render_applies_output_settings(settings_env, tmp_path):
    source = tmp_path / "example.json"
    source.write_text(json.dumps(example()), encoding="utf-8")
    config = AppConfig(
        onboarding_status="completed", default_output_dir=str(tmp_path),
        background="black", text_color="#ffffff", auto_open=True, save_netlist=True,
    )
    ConfigService.save(config)

    async def run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(RenderFileScreen())
            await pilot.pause()
            app.screen.query_one("#render-input-file", EnhancedInput).value = str(source)
            app.screen.query_one("#render-filename", EnhancedInput).value = "example.svg"
            app.screen.query_one(SelectableMenu).focus()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, RenderSuccessScreen)

    with patch("circuitgen.tui.screens.render.open_file_in_system_viewer", return_value=(True, "")) as viewer:
        asyncio.run(run())
    viewer.assert_called_once_with(tmp_path / "example.svg")
    assert 'height="100%" fill="black"' in (tmp_path / "example.svg").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "example.netlist.json").read_text(encoding="utf-8")) == example()
    assert json.loads(source.read_text(encoding="utf-8")) == example()


def test_environment_key_is_read_only(settings_env):
    async def run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(KeySettings("openai"))
            await pilot.pause()
            menu = app.screen.query_one(SelectableMenu)
            assert [item.key for item in menu.items] == ["back"]

    with patch.object(CredentialService, "resolve_key", return_value=("test-key", "environment")):
        asyncio.run(run())


def test_manual_model_id_must_be_listed(settings_env):
    async def run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            app.push_screen(ProviderSettings())
            await pilot.pause()
            field = app.screen.query_one("#default-model", EnhancedInput)
            field.value = "wrong-id"
            await select(pilot, app, "save")
            await app.workers.wait_for_complete()
            assert isinstance(app.screen, ProviderSettings)
            assert "did not list" in str(app.screen.query_one("#settings-status", Static).content)
            field.value = "models/example-model"
            await select(pilot, app, "save")
            await app.workers.wait_for_complete()
            assert ConfigService.load(force_reload=True).explicit_model == "example-model"

    with patch("circuitgen.tui.services.models.ModelService.discover_models", return_value=["example-model"]):
        asyncio.run(run())


def test_schematic_color_grid_and_hex_entry(settings_env):
    async def run():
        app = CircuitGenApp()
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(PreferenceForm("Schematic Preferences"))
            await pilot.pause()
            await select(pilot, app, "wire_color")
            assert isinstance(app.screen, ColorPicker)
            grid = app.screen.query_one(ColorGrid)
            field = app.screen.query_one("#hex-color", EnhancedInput)
            assert {len(row) for row in grid.render().plain.splitlines()} == {24}
            await pilot.click("#color-grid", offset=(10, 5))
            assert (grid.column, grid.row) == (5, 5)
            assert field.value == "#FE3F14"
            await pilot.press("right", "down")
            assert field.value == "#FD8648"
            field.value = "#123abc"
            await pilot.pause()
            assert grid.color == "#123ABC"
            await select(pilot, app, "apply")
            assert ConfigService.load().wire_color is None
            await select(pilot, app, "background")
            await select(pilot, app, "black")
            await select(pilot, app, "save")
            assert ConfigService.load(force_reload=True).wire_color == "#123ABC"
            assert ConfigService.load().background == "black"

    asyncio.run(run())
