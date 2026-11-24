"""Automated Textual Pilot tests for the CircuitGen Home screen, navigation, and modals."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

from textual.widgets._header import HeaderIcon

from circuitgen.tui.app import CircuitGenApp
from circuitgen.tui.screens.confirm_dialog import QuitModal
from circuitgen.tui.screens.home import HomeScreen
from circuitgen.tui.screens.placeholder import PlaceholderScreen
from circuitgen.tui.services.config import AppConfig, ConfigService
from circuitgen.tui.widgets.selectable_menu import SelectableMenu
import pytest


@pytest.fixture(autouse=True)
def bypass_onboarding_for_home_tests():
    """Ensure HomeScreen is mounted directly during home screen tests."""
    ConfigService.reset_cache()
    with patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed")):
        yield
    ConfigService.reset_cache()



def test_home_screen_renders_menu_and_offline_status():
    async def _run():
        with patch.dict(os.environ, {}, clear=True):
            app = CircuitGenApp()
            assert app.ENABLE_COMMAND_PALETTE is False
            async with app.run_test(size=(100, 30)) as pilot:
                assert isinstance(app.screen, HomeScreen)

                # Ensure HeaderIcon (the top-left oval button) is visually removed
                header_icon = app.screen.query_one(HeaderIcon)
                assert header_icon.styles.display == "none"

                menu = app.screen.query_one(SelectableMenu)
                assert menu is not None
                assert len(menu.items) == 5
                assert [item.key for item in menu.items] == [
                    "generate",
                    "render",
                    "validate",
                    "settings",
                    "help",
                ]
                # Check tagline with "text descriptions"
                tagline = app.screen.query(".tagline").first().render()
                assert "text descriptions or netlists" in str(tagline)

                # Check offline status message
                status_text = app.screen.query(".status-left").first().render()
                assert "AI: Not configured" in str(status_text)

                # Verify "render and validate work offline" is removed
                all_text = " ".join(str(w.render()) for w in app.screen.query("Static"))
                assert "work offline" not in all_text

                # Check keys reminder
                reminder = app.screen.query(".keys-reminder").first().render()
                assert "Navigate" in str(reminder)
                assert "Enter Select" in str(reminder)
                assert "Quit" in str(reminder)

    asyncio.run(_run())


def test_home_status_with_env_key():
    async def _run():
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-abc"}, clear=True):
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                assert isinstance(app.screen, HomeScreen)
                status_left = app.screen.query(".status-left").first().render()
                status_right = app.screen.query(".status-right").first().render()
                assert "AI: Gemini · Automatic" in str(status_left)
                assert "Key: Environment" in str(status_right)

    asyncio.run(_run())


def test_menu_arrow_navigation_and_wrapping():
    async def _run():
        app = CircuitGenApp()
        async with app.run_test(size=(100, 30)) as pilot:
            menu = app.screen.query_one(SelectableMenu)
            assert menu.cursor_index == 0  # "generate"

            # Down arrow moves to next item
            await pilot.press("down")
            assert menu.cursor_index == 1  # "render"

            # Move to last item
            await pilot.press("down")
            assert menu.cursor_index == 2  # "validate"
            await pilot.press("down")
            assert menu.cursor_index == 3  # "settings"
            await pilot.press("down")
            assert menu.cursor_index == 4  # "help"

            # Down arrow from last item wraps to top
            await pilot.press("down")
            assert menu.cursor_index == 0  # "generate"

            # Up arrow from top wraps to bottom
            await pilot.press("up")
            assert menu.cursor_index == 4  # "help"

            # Up arrow moves up
            await pilot.press("up")
            assert menu.cursor_index == 3  # "settings"

    asyncio.run(_run())


def test_menu_enter_activates_subpage_and_esc_returns():
    async def _run():
        app = CircuitGenApp()
        async with app.run_test(size=(100, 30)) as pilot:
            menu = app.screen.query_one(SelectableMenu)
            assert menu.cursor_index == 0  # "generate"

            # Press Enter on Generate
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, PlaceholderScreen)
            assert app.screen.page_name == "Generate"

            # Press Esc to return Home
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            assert app.screen.query_one(SelectableMenu).has_focus

    asyncio.run(_run())


def test_esc_on_home_does_nothing():
    """Ensure pressing Esc on the home screen does not trigger an unexpected exit modal."""
    async def _run():
        app = CircuitGenApp()
        async with app.run_test(size=(100, 30)) as pilot:
            assert isinstance(app.screen, HomeScreen)

            # Press Esc on Home
            await pilot.press("escape")
            await pilot.pause()

            # Still on HomeScreen; no modal opened
            assert isinstance(app.screen, HomeScreen)
            assert app.is_running

    asyncio.run(_run())


def test_ctrl_q_on_home_exits():
    """Ensure Ctrl+Q on the home screen immediately quits."""
    async def _run():
        app = CircuitGenApp()
        async with app.run_test(size=(100, 30)) as pilot:
            assert isinstance(app.screen, HomeScreen)
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert not app.is_running

    asyncio.run(_run())


def test_q_key_on_home_exits():
    """Ensure pressing 'q' on the home screen also quits."""
    async def _run():
        app = CircuitGenApp()
        async with app.run_test(size=(100, 30)) as pilot:
            assert isinstance(app.screen, HomeScreen)
            await pilot.press("q")
            await pilot.pause()
            assert not app.is_running

    asyncio.run(_run())


def test_ctrl_q_from_subpage_opens_quit_modal_and_cancel_retains_subpage():
    async def _run():
        app = CircuitGenApp()
        async with app.run_test(size=(100, 30)) as pilot:
            # Enter "render" subpage
            await pilot.press("down", "enter")
            await pilot.pause()
            assert isinstance(app.screen, PlaceholderScreen)
            assert app.screen.page_name == "Render"

            # Press Ctrl+Q from subpage opens confirmation modal
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert isinstance(app.screen, QuitModal)

            # Cancel modal with Esc returns to subpage
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, PlaceholderScreen)

            # Re-open modal and pressing ctrl+q confirms quit
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert isinstance(app.screen, QuitModal)
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert not app.is_running

    asyncio.run(_run())


def test_quit_modal_keep_working_selection():
    async def _run():
        app = CircuitGenApp()
        async with app.run_test(size=(100, 30)) as pilot:
            # Enter subpage
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, PlaceholderScreen)

            # Trigger quit dialog
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert isinstance(app.screen, QuitModal)

            quit_menu = app.screen.query_one(SelectableMenu)
            assert quit_menu.cursor_index == 0
            assert quit_menu.selected_item.key == "keep"

            # Press Enter on Keep Working -> dismiss modal, remain in subpage
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, PlaceholderScreen)
            assert app.is_running

    asyncio.run(_run())


def test_responsive_layout_down_to_80x24():
    async def _run():
        app = CircuitGenApp()
        async with app.run_test(size=(80, 24)) as pilot:
            assert isinstance(app.screen, HomeScreen)
            menu = app.screen.query_one(SelectableMenu)
            assert menu.visible
            await pilot.press("down", "down", "up")
            assert menu.cursor_index == 1

    asyncio.run(_run())
