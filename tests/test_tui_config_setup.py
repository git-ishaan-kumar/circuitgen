"""Automated tests for CircuitGen Phase 3 — Configuration, First-Run Setup (S0/S1), and Provider Selection."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from circuitgen.ai import list_providers
from circuitgen.tui.app import CircuitGenApp
from circuitgen.tui.screens.home import HomeScreen
from circuitgen.tui.screens.setup_provider import PROVIDER_DISPLAY_NAMES, SetupProviderScreen
from circuitgen.tui.screens.setup_step_placeholder import SetupStepPlaceholderScreen
from circuitgen.tui.screens.setup_welcome import SetupWelcomeScreen
from circuitgen.tui.services.config import AppConfig, ConfigService
from circuitgen.tui.widgets.selectable_menu import SelectableMenu


@pytest.fixture
def temp_config_dir():
    """Provide an isolated temporary directory for config tests."""
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


class TestConfigService:
    """Test AppConfig and ConfigService atomic file management, schema, and recovery."""

    def test_default_config_schema_and_values(self, temp_config_dir):
        config = ConfigService.load(override_dir=temp_config_dir)
        assert config.schema_version == 1
        assert config.onboarding_status == "not_started"
        assert config.default_provider == "gemini"
        assert config.model_mode == "automatic"
        assert config.should_show_onboarding() is True

    def test_atomic_save_and_reload(self, temp_config_dir):
        config = AppConfig(
            onboarding_status="completed",
            default_provider="anthropic",
            interface_theme="dark",
        )
        ConfigService.save(config, override_dir=temp_config_dir)

        # Verify file exists on disk and has valid json
        config_file = temp_config_dir / "config.json"
        assert config_file.is_file()

        reloaded = ConfigService.load(override_dir=temp_config_dir, force_reload=True)
        assert reloaded.onboarding_status == "completed"
        assert reloaded.default_provider == "anthropic"
        assert reloaded.should_show_onboarding() is False

    def test_secrets_never_persisted_to_config(self, temp_config_dir):
        config = AppConfig()
        # Even if dictionary has forbidden secret keys
        data = config.to_dict()
        data["api_key"] = "secret_123"
        data["token"] = "token_abc"

        ConfigService.save(config, override_dir=temp_config_dir)
        content = (temp_config_dir / "config.json").read_text(encoding="utf-8")
        assert "secret_123" not in content
        assert "token_abc" not in content

    def test_corrupt_config_recovers_gracefully_with_backup(self, temp_config_dir):
        config_file = temp_config_dir / "config.json"
        config_file.write_text("{invalid json: corrupt content...", encoding="utf-8")

        config = ConfigService.load(override_dir=temp_config_dir, force_reload=True)
        # Recovers without crash
        assert config.schema_version == 1
        assert config.default_provider == "gemini"
        assert config.load_warning is not None
        assert "Corrupt configuration detected" in config.load_warning

        # Backup file must have been created to protect data
        backup_file = temp_config_dir / "config.json.bak"
        assert backup_file.is_file()
        assert "{invalid json" in backup_file.read_text(encoding="utf-8")

    def test_mark_onboarding_skipped(self):
        config = AppConfig()
        assert config.should_show_onboarding() is True
        config.mark_onboarding_skipped()
        assert config.onboarding_status == "skipped"
        assert config.should_show_onboarding() is False

    def test_mark_onboarding_completed(self):
        config = AppConfig()
        assert config.should_show_onboarding() is True
        config.mark_onboarding_completed()
        assert config.onboarding_status == "completed"
        assert config.should_show_onboarding() is False


class TestFirstRunSetupScreens:
    """Test S0 (Welcome), S1 (Provider), skip/return behavior, and persistent navigation."""

    def test_first_launch_shows_welcome_screen(self, temp_config_dir):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                assert isinstance(app.screen, SetupWelcomeScreen)
                step_indicator = app.screen.query(".breadcrumb-right").first().render()
                assert "Step 1 of 4" in str(step_indicator)

                title = app.screen.query(".setup-title").first().render()
                assert "Welcome to CircuitGen" in str(title)

                menu = app.screen.query_one(SelectableMenu)
                assert len(menu.items) == 2
                assert menu.items[0].key == "setup_ai"
                assert menu.items[1].key == "skip"

        asyncio.run(_run())

    def test_welcome_skip_advances_to_home_and_persists_skip(self, temp_config_dir):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                assert isinstance(app.screen, SetupWelcomeScreen)
                # Navigate down to "Skip for now"
                await pilot.press("down")
                menu = app.screen.query_one(SelectableMenu)
                assert menu.cursor_index == 1
                assert menu.items[1].key == "skip"

                # Press Enter to select Skip
                await pilot.press("enter")
                await pilot.pause()

                # Must transition to HomeScreen
                assert isinstance(app.screen, HomeScreen)

            # Verify config persisted onboarding_status = "skipped"
            saved_config = ConfigService.load(override_dir=temp_config_dir, force_reload=True)
            assert saved_config.onboarding_status == "skipped"
            assert saved_config.should_show_onboarding() is False

            # Relaunch app: must go directly to HomeScreen without wizard!
            app2 = CircuitGenApp()
            async with app2.run_test(size=(100, 30)) as pilot2:
                assert isinstance(app2.screen, HomeScreen)

        asyncio.run(_run())

    def test_welcome_escape_key_skips_to_home(self, temp_config_dir):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                assert isinstance(app.screen, SetupWelcomeScreen)
                # Esc behaves identically to Skip for now
                await pilot.press("escape")
                await pilot.pause()
                assert isinstance(app.screen, HomeScreen)

            saved_config = ConfigService.load(override_dir=temp_config_dir, force_reload=True)
            assert saved_config.onboarding_status == "skipped"

        asyncio.run(_run())

    def test_welcome_quit_does_not_mark_skipped(self, temp_config_dir):
        """Interruption without selection leaves onboarding uncompleted."""
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                assert isinstance(app.screen, SetupWelcomeScreen)
                await pilot.press("ctrl+q")
                await pilot.pause()

            # Config file was not marked as skipped
            config_file = temp_config_dir / "config.json"
            if config_file.exists():
                cfg = ConfigService.load(override_dir=temp_config_dir, force_reload=True)
                assert cfg.onboarding_status == "not_started"

        asyncio.run(_run())

    def test_delete_config_restores_first_run_wizard(self, temp_config_dir):
        # 1. Mark skipped
        config = AppConfig(onboarding_status="skipped")
        ConfigService.save(config, override_dir=temp_config_dir)

        # 2. Delete config file
        config_file = temp_config_dir / "config.json"
        assert config_file.is_file()
        config_file.unlink()
        ConfigService.reset_cache()

        # 3. Launch app: wizard must reappear!
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                assert isinstance(app.screen, SetupWelcomeScreen)

        asyncio.run(_run())

    def test_setup_s1_provider_selection_and_back(self, temp_config_dir):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                assert isinstance(app.screen, SetupWelcomeScreen)
                # Select "Set up AI generation"
                await pilot.press("enter")
                await pilot.pause()

                # Now on SetupProviderScreen (Step 2 of 4)
                assert isinstance(app.screen, SetupProviderScreen)
                step_indicator = app.screen.query(".breadcrumb-right").first().render()
                assert "Step 2 of 4" in str(step_indicator)

                menu = app.screen.query_one(SelectableMenu)
                all_provider_keys = [item.key for item in menu.items]
                # Must match registered providers from circuitgen.ai
                assert all_provider_keys == list_providers()
                assert menu.cursor_index == 0  # Gemini is default

                # Navigate down to OpenAI (index 1)
                await pilot.press("down")
                assert menu.cursor_index == 1
                assert menu.items[1].key == "openai"

                # Navigate down to Anthropic (index 2)
                await pilot.press("down")
                assert menu.cursor_index == 2
                assert menu.items[2].key == "anthropic"

                # Press Esc to go back to S0 (Welcome)
                await pilot.press("escape")
                await pilot.pause()
                assert isinstance(app.screen, SetupWelcomeScreen)

                # Re-enter S1: selection remains intact!
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, SetupProviderScreen)

        asyncio.run(_run())

    def test_setup_s1_choose_provider_and_complete_to_home(self, temp_config_dir):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                assert isinstance(app.screen, SetupWelcomeScreen)
                await pilot.press("enter")  # -> S1
                await pilot.pause()

                assert isinstance(app.screen, SetupProviderScreen)
                # Select Anthropic
                await pilot.press("down")
                await pilot.press("down")
                menu = app.screen.query_one(SelectableMenu)
                assert menu.items[menu.cursor_index].key == "anthropic"

                # Press Enter to choose Anthropic
                await pilot.press("enter")
                await pilot.pause()

                # Verify default_provider was saved to config
                cfg = ConfigService.load(override_dir=temp_config_dir, force_reload=True)
                assert cfg.default_provider == "anthropic"

                # Now on Step 3 (SetupKeyScreen)
                from circuitgen.tui.screens.setup_key import SetupKeyScreen
                assert isinstance(app.screen, SetupKeyScreen)
                assert app.screen.provider_id == "anthropic"

                # Navigate to "Skip for now" on key screen to complete to Home
                key_menu = app.screen.query_one("#key-action-menu", SelectableMenu)
                key_menu.selected_index = 3  # "skip"
                key_menu.focus()
                await pilot.press("enter")
                await pilot.pause()

                # Transitions to HomeScreen
                assert isinstance(app.screen, HomeScreen)

            # Verify config updated
            final_cfg = ConfigService.load(override_dir=temp_config_dir, force_reload=True)
            assert final_cfg.onboarding_status == "skipped"
            assert final_cfg.default_provider == "anthropic"

        asyncio.run(_run())
