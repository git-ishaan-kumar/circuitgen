"""Automated tests for CircuitGen Phase 5 — Model Selection, Discovery, and Setup Completion (§3.4, §3.5, §8)."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from circuitgen.tui.app import CircuitGenApp
from circuitgen.tui.screens.home import HomeScreen
from circuitgen.tui.screens.setup_complete import SetupCompleteScreen
from circuitgen.tui.screens.setup_model import (
    SetupModelBrowseScreen,
    SetupModelManualScreen,
    SetupModelScreen,
)
from circuitgen.tui.services.config import AppConfig, ConfigService
from circuitgen.tui.services.credentials import CredentialService
from circuitgen.tui.services.models import (
    AccessDeniedError,
    AuthenticationError,
    ModelNotFoundError,
    ModelService,
    NetworkError,
    ProviderError,
    RateLimitedError,
)
from circuitgen.tui.widgets.selectable_menu import SelectableMenu
from textual.widgets import Input, Static


class InMemoryKeyring:
    priority = 5

    def __init__(self) -> None:
        self._storage: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._storage.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._storage[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        key = (service, username)
        if key in self._storage:
            del self._storage[key]


@pytest.fixture
def fake_keyring():
    ring = InMemoryKeyring()
    with patch("keyring.get_keyring", return_value=ring), \
         patch("keyring.get_password", side_effect=ring.get_password), \
         patch("keyring.set_password", side_effect=ring.set_password), \
         patch("keyring.delete_password", side_effect=ring.delete_password):
        yield ring


@pytest.fixture
def temp_config_dir():
    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        old_env = os.environ.get("CIRCUITGEN_CONFIG_DIR")
        os.environ["CIRCUITGEN_CONFIG_DIR"] = str(temp_dir)
        ConfigService.reset_cache()
        try:
            yield temp_dir
        finally:
            ConfigService.reset_cache()
            if old_env is not None:
                os.environ["CIRCUITGEN_CONFIG_DIR"] = old_env
            else:
                os.environ.pop("CIRCUITGEN_CONFIG_DIR", None)


class TestModelServiceUnit:
    """Test model discovery, validation, and error classification."""

    def test_recommended_models_policy(self):
        gemini_rec = ModelService.get_recommended_model("gemini")
        assert gemini_rec == "gemini-2.5-flash"

        openai_rec = ModelService.get_recommended_model("openai")
        assert openai_rec == "gpt-4.1-mini"

        anthropic_rec = ModelService.get_recommended_model("anthropic")
        assert anthropic_rec == "claude-sonnet-4-5"

    def test_model_id_syntactic_validation(self):
        valid, msg = ModelService.validate_model_id("gemini-2.5-flash")
        assert valid is True

        valid_custom, _ = ModelService.validate_model_id("accounts/fireworks/models/llama-v3p3-70b-instruct")
        assert valid_custom is True

        empty_valid, empty_msg = ModelService.validate_model_id("")
        assert empty_valid is False
        assert "empty" in empty_msg

        invalid_chars, inv_msg = ModelService.validate_model_id("model;rm -rf /")
        assert invalid_chars is False
        assert "invalid characters" in inv_msg

    def test_discover_models_gemini_mocked(self, fake_keyring):
        CredentialService.save_key("gemini", "dummy-key")

        mock_payload = {
            "models": [
                {"name": "models/gemini-2.5-flash"},
                {"name": "models/gemini-2.5-pro"},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = str(mock_payload).replace("'", '"').encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            models = ModelService.discover_models("gemini")
            assert "gemini-2.5-flash" in models
            assert "gemini-2.5-pro" in models
            assert len(models) == 2

    def test_discover_models_network_failure(self, fake_keyring):
        CredentialService.save_key("gemini", "dummy-key")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection reset")):
            with pytest.raises(NetworkError) as exc_info:
                ModelService.discover_models("gemini")
            assert "Network unavailable" in str(exc_info.value)

    def test_gemini_follows_pages_and_filters_generation_methods(self):
        pages = [
            {"models": [{"name": "models/embedding", "supportedGenerationMethods": ["embedContent"]}],
             "nextPageToken": "page-2"},
            {"models": [{"name": "models/chat", "supportedGenerationMethods": ["generateContent"]}]},
        ]
        responses = []
        for page in pages:
            response = MagicMock()
            response.__enter__.return_value = response
            response.read.return_value = json.dumps(page).encode()
            responses.append(response)

        with patch("urllib.request.urlopen", side_effect=responses) as open_url:
            assert ModelService.discover_models("gemini", api_key="test-key") == ["chat"]
        requests = [call.args[0] for call in open_url.call_args_list]
        assert "pageToken=page-2" in requests[1].full_url
        assert all("test-key" not in request.full_url for request in requests)
        assert all(request.get_header("X-goog-api-key") == "test-key" for request in requests)

    def test_discover_models_auth_failure(self, fake_keyring):
        CredentialService.save_key("gemini", "dummy-key")
        http_error = urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)
        with patch("urllib.request.urlopen", side_effect=http_error):
            with pytest.raises(AuthenticationError) as exc_info:
                ModelService.discover_models("gemini")
            assert "Authentication rejected" in str(exc_info.value)

    def test_discover_models_rate_limited(self, fake_keyring):
        CredentialService.save_key("gemini", "dummy-key")
        http_error = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)
        with patch("urllib.request.urlopen", side_effect=http_error):
            with pytest.raises(RateLimitedError) as exc_info:
                ModelService.discover_models("gemini")
            assert "Rate limit" in str(exc_info.value)


class TestSetupModelScreensInteraction:
    """Test S3 (Model Selection), Browse, Manual Entry, and S4 (Complete)."""

    def test_setup_s3_screen_renders_options(self, temp_config_dir):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                screen = SetupModelScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                assert isinstance(app.screen, SetupModelScreen)
                step_indicator = app.screen.query(".breadcrumb-right").first().render()
                assert "Step 4 of 4" in str(step_indicator)

                menu = app.screen.query_one("#model-options-menu", SelectableMenu)
                assert [item.key for item in menu.items] == ["auto", "browse", "manual"]

        asyncio.run(_run())

    def test_setup_s3_select_automatic_persists_policy_and_advances_to_complete(self, temp_config_dir):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                screen = SetupModelScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                menu = app.screen.query_one("#model-options-menu", SelectableMenu)
                menu.selected_index = 0  # "auto"
                menu.focus()
                await pilot.press("enter")
                await pilot.pause()

                # Advances to SetupCompleteScreen
                assert isinstance(app.screen, SetupCompleteScreen)

            # Verify persisted config
            cfg = ConfigService.load(override_dir=temp_config_dir, force_reload=True)
            assert cfg.model_mode == "automatic"
            assert cfg.explicit_model is None

        asyncio.run(_run())

    def test_setup_s3_browse_models_success(self, temp_config_dir, fake_keyring):
        CredentialService.save_key("gemini", "valid-key")

        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                screen = SetupModelScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                with patch.object(
                    ModelService,
                    "discover_models",
                    return_value=["gemini-2.5-flash", "gemini-2.5-pro"],
                ):
                    menu = app.screen.query_one("#model-options-menu", SelectableMenu)
                    menu.selected_index = 1  # "browse"
                    menu.focus()
                    await pilot.press("enter")
                    await pilot.pause()

                    # On SetupModelBrowseScreen
                    assert isinstance(app.screen, SetupModelBrowseScreen)
                    browse_menu = app.screen.query_one("#browse-models-menu", SelectableMenu)
                    assert [item.key for item in browse_menu.items] == ["gemini-2.5-flash", "gemini-2.5-pro"]

                    # Select gemini-2.5-pro (index 1)
                    browse_menu.selected_index = 1
                    browse_menu.focus()
                    await pilot.press("enter")
                    await pilot.pause()

                    # Advances to SetupCompleteScreen
                    assert isinstance(app.screen, SetupCompleteScreen)

            cfg = ConfigService.load(override_dir=temp_config_dir, force_reload=True)
            assert cfg.model_mode == "manual"
            assert cfg.explicit_model == "gemini-2.5-pro"

        asyncio.run(_run())

    def test_setup_s3_browse_discovery_failure_shows_warning(self, temp_config_dir, fake_keyring):
        CredentialService.save_key("gemini", "valid-key")

        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                screen = SetupModelScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                with patch.object(
                    ModelService,
                    "discover_models",
                    side_effect=NetworkError("Network unavailable while discovering models"),
                ):
                    menu = app.screen.query_one("#model-options-menu", SelectableMenu)
                    menu.selected_index = 1  # "browse"
                    menu.focus()
                    await pilot.press("enter")
                    await pilot.pause()

                    # Stays on SetupModelScreen, displays helpful error suggesting manual entry
                    assert isinstance(app.screen, SetupModelScreen)
                    status = app.screen.query_one("#model-status-message", Static).render()
                    assert "Could not discover models" in str(status)
                    assert "enter a model ID manually" in str(status)

        asyncio.run(_run())

    def test_setup_s3_manual_model_entry(self, temp_config_dir):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                screen = SetupModelScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                menu = app.screen.query_one("#model-options-menu", SelectableMenu)
                menu.selected_index = 2  # "manual"
                menu.focus()
                await pilot.press("enter")
                await pilot.pause()

                # On SetupModelManualScreen
                assert isinstance(app.screen, SetupModelManualScreen)

                inp = app.screen.query_one("#manual-model-input", Input)
                inp.value = "custom-gemini-experimental"

                manual_menu = app.screen.query_one("#manual-model-menu", SelectableMenu)
                manual_menu.selected_index = 0  # "save"
                manual_menu.focus()
                await pilot.press("enter")
                await pilot.pause()

                # Advances to SetupCompleteScreen
                assert isinstance(app.screen, SetupCompleteScreen)

            cfg = ConfigService.load(override_dir=temp_config_dir, force_reload=True)
            assert cfg.model_mode == "manual"
            assert cfg.explicit_model == "custom-gemini-experimental"

        asyncio.run(_run())

    def test_setup_s4_complete_screen_and_relaunch_to_home(self, temp_config_dir, fake_keyring):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                screen = SetupCompleteScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                assert isinstance(app.screen, SetupCompleteScreen)
                title = app.screen.query(".setup-title").first().render()
                assert "Setup complete" in str(title)

                # Select "Go to home"
                menu = app.screen.query_one("#setup-complete-menu", SelectableMenu)
                menu.selected_index = 0  # "home"
                menu.focus()
                await pilot.press("enter")
                await pilot.pause()

                assert isinstance(app.screen, HomeScreen)

            # Verify onboarding completed in config
            cfg = ConfigService.load(override_dir=temp_config_dir, force_reload=True)
            assert cfg.onboarding_status == "completed"

            # Relaunching app opens directly into HomeScreen
            app2 = CircuitGenApp()
            async with app2.run_test(size=(100, 30)) as pilot2:
                assert isinstance(app2.screen, HomeScreen)

        asyncio.run(_run())

    def test_selectable_menu_windowed_scrolling(self):
        from circuitgen.tui.widgets.selectable_menu import MenuItem, SelectableMenu
        items = [MenuItem(f"item-{i}", f"Item {i}", f"Description {i}") for i in range(25)]
        menu = SelectableMenu(items, initial_index=0, max_visible=10)

        # Initial render: shows top indicator and bottom indicator
        rendered = str(menu.render())
        assert "Top of list" in rendered
        assert "more below" in rendered
        assert "Item 0" in rendered
        assert "Item 9" in rendered
        assert "Item 10" not in rendered

        # Move cursor down past visible limit
        for _ in range(12):
            menu.action_cursor_down()
        assert menu.cursor_index == 12

        rendered_scrolled = str(menu.render())
        assert "more above" in rendered_scrolled
        assert "Item 12" in rendered_scrolled

        # Page down and Page up
        menu.action_page_down()
        assert menu.cursor_index == 22

        menu.action_page_up()
        assert menu.cursor_index == 12

        # Home and End
        menu.action_first_item()
        assert menu.cursor_index == 0

        menu.action_last_item()
        assert menu.cursor_index == 24
        assert "End of list" in str(menu.render())

    def test_browse_long_model_list_scrolling(self, temp_config_dir, fake_keyring):
        CredentialService.save_key("gemini", "valid-key")
        many_models = [f"model-variant-{i:02d}" for i in range(40)]

        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                screen = SetupModelScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                with patch.object(ModelService, "discover_models", return_value=many_models):
                    menu = app.screen.query_one("#model-options-menu", SelectableMenu)
                    menu.selected_index = 1  # "browse"
                    menu.focus()
                    await pilot.press("enter")
                    await pilot.pause()

                    assert isinstance(app.screen, SetupModelBrowseScreen)
                    browse_menu = app.screen.query_one("#browse-models-menu", SelectableMenu)
                    assert browse_menu.max_visible == 10
                    assert len(browse_menu.items) == 40

                    # Scroll down 15 items
                    for _ in range(15):
                        await pilot.press("down")
                    await pilot.pause()

                    assert browse_menu.cursor_index == 15
                    rendered = str(browse_menu.render())
                    assert "model-variant-15" in rendered
                    assert "more above" in rendered
                    assert "more below" in rendered

        asyncio.run(_run())
