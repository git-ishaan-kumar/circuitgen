import asyncio
import json
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest
from textual.widgets import Select, Static

from circuitgen.ai import ProviderRequestError
from circuitgen.tui.app import CircuitGenApp
from circuitgen.tui.screens.confirm_dialog import CreateDirectoryModal, OverwriteModal
from circuitgen.tui.screens.generate import GenerateScreen, GenerationProgress
from circuitgen.tui.screens.render import RenderSuccessScreen, ViewNetlistScreen
from circuitgen.tui.screens.settings import ProviderSettings
from circuitgen.tui.services.config import AppConfig, ConfigService
from circuitgen.tui.services.credentials import CredentialService
from circuitgen.tui.widgets import EnhancedInput, JsonEditor, SelectableMenu


PROMPT = "A 9V battery connected to a red LED through a 330Ω resistor."


def mock_netlist(*args, on_model=None, **kwargs):
    if on_model:
        on_model("mock-actual-model")
    return {
        "components": [
            {"id": "B1", "type": "battery", "value": "9V"},
            {"id": "R1", "type": "resistor", "value": "330Ω"},
            {"id": "D1", "type": "led", "value": "red"},
        ],
        "nets": [
            {"name": "VCC", "pins": ["B1.p", "R1.a"]},
            {"name": "SIGNAL", "pins": ["R1.b", "D1.a"]},
            {"name": "GND", "pins": ["D1.b", "B1.n"]},
        ],
    }


@pytest.fixture
def config(tmp_path):
    config = AppConfig(onboarding_status="completed", default_output_dir=str(tmp_path), save_netlist=True)
    with (
        patch.object(ConfigService, "load", return_value=config),
        patch.object(CredentialService, "resolve_key", return_value=("fake-key", "environment")),
        patch("circuitgen.tui.screens.generate.ModelService.discover_models",
              return_value=["gemini-2.5-flash"]),
    ):
        yield config


async def select(app, pilot, key):
    menu = app.screen.query_one(SelectableMenu)
    menu.selected_index = next(i for i, item in enumerate(menu.items) if item.key == key)
    menu.focus()
    await pilot.press("enter")
    await pilot.pause()


async def open_generate(app, pilot):
    await select(app, pilot, "generate")
    page = app.screen
    assert isinstance(page, GenerateScreen)
    page.query_one(JsonEditor).text = PROMPT
    page.query_one("#generate-filename", EnhancedInput).value = "led"
    return page


def test_generate_saves_and_opens_netlist(config, tmp_path):
    async def run():
        app = CircuitGenApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await open_generate(app, pilot)
            await select(app, pilot, "generate")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, RenderSuccessScreen)
            assert (app.screen.components_count, app.screen.nets_count) == (3, 3)
            assert app.screen.ai_source == ("Google Gemini", "mock-actual-model")
            await select(app, pilot, "open")
            await app.workers.wait_for_complete()
            await select(app, pilot, "view_netlist")
            assert isinstance(app.screen, ViewNetlistScreen)
            assert app.screen.netlist == mock_netlist()
            await select(app, pilot, "copy")

    with (
        patch("circuitgen.tui.screens.generate.generate_netlist", side_effect=mock_netlist) as request,
        patch("circuitgen.tui.screens.render.open_file_in_system_viewer", return_value=(True, "")) as viewer,
        patch.object(CircuitGenApp, "copy_to_clipboard") as copy,
    ):
        asyncio.run(run())
    assert request.call_args.args == (PROMPT,)
    assert (tmp_path / "led.svg").read_text(encoding="utf-8").startswith("<svg")
    assert json.loads((tmp_path / "led.json").read_text(encoding="utf-8")) == mock_netlist()
    viewer.assert_called_once_with(tmp_path / "led.svg")
    assert json.loads(copy.call_args.args[0]) == mock_netlist()


def test_cancel_delayed_generation_preserves_draft(config, tmp_path):
    started, finish, returned = Event(), Event(), Event()

    def slow(*args, **kwargs):
        started.set()
        finish.wait(5)
        returned.set()
        return mock_netlist()

    async def run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            page = await open_generate(app, pilot)
            directory = tmp_path / "new-output"
            page.query_one("#generate-directory", EnhancedInput).value = str(directory)
            await select(app, pilot, "generate")
            assert isinstance(app.screen, CreateDirectoryModal)
            try:
                await select(app, pilot, "create")
                assert await asyncio.to_thread(started.wait, 2)
                assert isinstance(app.screen, GenerationProgress)
                checkpoint = app.screen.query_one(".generation-checkpoint.complete", Static)
                assert str(checkpoint.content) == "✓ Check model"
                assert checkpoint.styles.background.hex.upper() == "#4ADE80"
                assert str(app.screen.query_one(".generation-checkpoint.current", Static).content) == "2 Get netlist"
                assert "Waiting for the provider" in str(app.screen.query_one("#generation-stage", Static).content)
                await pilot.press("escape")
                assert "cancelled" in str(page.query_one("#generate-status", Static).content)
                assert not page.query_one(JsonEditor).disabled
                assert page.query_one(JsonEditor).text == PROMPT
                assert page.query_one("#generate-filename", EnhancedInput).value == "led"
            finally:
                finish.set()
            assert await asyncio.to_thread(returned.wait, 2)
            await pilot.pause()
            assert app.screen is page
            assert not directory.exists()

    with patch("circuitgen.tui.screens.generate.generate_netlist", side_effect=slow):
        asyncio.run(run())


def test_generate_changes_provider_and_retries(config, tmp_path):
    async def run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            page = await open_generate(app, pilot)
            await select(app, pilot, "provider")
            assert isinstance(app.screen, ProviderSettings)
            app.screen.query_one("#default-provider", Select).value = "openai"
            await pilot.pause()
            app.screen.query_one("#default-model", EnhancedInput).value = "mock-custom-model"
            await select(app, pilot, "save")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen is page
            assert page.config.default_provider == "openai"
            assert page.config.explicit_model == "mock-custom-model"
            assert config.default_provider == "gemini"

            await select(app, pilot, "generate")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "rejected the API key" in str(page.query_one("#generate-status", Static).content)
            assert page.query_one(JsonEditor).text == PROMPT
            assert not (tmp_path / "led.svg").exists()

            await select(app, pilot, "generate")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, RenderSuccessScreen)

    with (
        patch("circuitgen.tui.screens.settings.ModelService.discover_models", return_value=["mock-custom-model"]),
        patch("circuitgen.tui.screens.generate.generate_netlist",
              side_effect=[ProviderRequestError("Denied", status=401), mock_netlist()]) as request,
    ):
        asyncio.run(run())
    assert request.call_count == 2
    assert request.call_args.kwargs["provider"] == "openai"
    assert request.call_args.kwargs["model"] == "mock-custom-model"


def test_generate_guards_existing_output(config, tmp_path):
    target = tmp_path / "led.svg"
    target.write_text("existing", encoding="utf-8")

    async def run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            page = await open_generate(app, pilot)
            await select(app, pilot, "generate")
            assert isinstance(app.screen, OverwriteModal)
            await pilot.press("escape")
            assert app.screen is page
            assert target.read_text(encoding="utf-8") == "existing"

    with patch("circuitgen.tui.screens.generate.generate_netlist") as request:
        asyncio.run(run())
    request.assert_not_called()


def test_quit_does_not_wait_for_provider_or_save(config, tmp_path):
    started, finish, returned = Event(), Event(), Event()

    def slow(*args, **kwargs):
        started.set()
        finish.wait(5)
        returned.set()
        return mock_netlist()

    async def run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            await open_generate(app, pilot)
            await select(app, pilot, "generate")
            assert await asyncio.to_thread(started.wait, 2)
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert not app.is_running

    with patch("circuitgen.tui.screens.generate.generate_netlist", side_effect=slow):
        try:
            asyncio.run(asyncio.wait_for(run(), 3))
            assert not returned.is_set()
        finally:
            finish.set()
    assert list(tmp_path.iterdir()) == []


def test_generate_requires_key_without_discarding_draft(config):
    async def run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            page = await open_generate(app, pilot)
            await select(app, pilot, "generate")
            assert app.screen is page and page.query_one(JsonEditor).text == PROMPT
            assert "Add an API key" in str(page.query_one("#generate-status", Static).content)

    with (
        patch.object(CredentialService, "resolve_key", return_value=(None, "none")),
        patch("circuitgen.tui.screens.generate.generate_netlist") as request,
    ):
        asyncio.run(run())
    request.assert_not_called()


def test_generate_blocks_model_missing_from_key_catalog(config):
    config.model_mode = "manual"
    config.explicit_model = "not-listed"

    async def run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            page = await open_generate(app, pilot)
            await select(app, pilot, "generate")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen is page
            assert "not listed for this API key" in str(page.query_one("#generate-status", Static).content)

    with patch("circuitgen.tui.screens.generate.generate_netlist") as request:
        asyncio.run(run())
    request.assert_not_called()


def test_output_folder_blocked_by_file_is_reported_before_request(config, tmp_path):
    blocking_file = tmp_path / "existing-file"
    blocking_file.write_text("original", encoding="utf-8")

    async def run():
        app = CircuitGenApp()
        async with app.run_test() as pilot:
            page = await open_generate(app, pilot)
            page.query_one("#generate-directory", EnhancedInput).value = str(blocking_file / "output")
            await select(app, pilot, "generate")
            assert app.screen is page
            assert "blocking the output folder" in str(page.query_one("#generate-status", Static).content)

    with patch("circuitgen.tui.screens.generate.generate_netlist") as request:
        asyncio.run(run())
    request.assert_not_called()
    assert blocking_file.read_text(encoding="utf-8") == "original"
