"""Unit tests for EnhancedInput desktop editing keybindings and system clipboard integration."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from textual.app import App, ComposeResult

from circuitgen.tui.app import CircuitGenApp
from circuitgen.tui.clipboard import (
    _get_darwin_clipboard,
    _get_linux_clipboard,
    _get_windows_clipboard,
    _set_darwin_clipboard,
    _set_linux_clipboard,
    _set_windows_clipboard,
    get_system_clipboard,
    set_system_clipboard,
)
from circuitgen.tui.widgets.enhanced_input import EnhancedInput


class KeybindingTestApp(App[None]):
    """Test harness for EnhancedInput."""

    def compose(self) -> ComposeResult:
        yield EnhancedInput(value="hello world foo", id="test-input")
        yield EnhancedInput(value="sk-proj-12345", password=True, id="password-input")


def test_enhanced_input_ctrl_a_select_all():
    """Test that Ctrl+A selects all text in the input."""
    async def _run():
        app = KeybindingTestApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#test-input", EnhancedInput)
            inp.focus()
            inp.cursor_position = 0
            assert inp.selected_text == ""

            await pilot.press("ctrl+a")
            assert inp.selected_text == "hello world foo"

    asyncio.run(_run())


def test_enhanced_input_typing_replaces_selection():
    """Test that typing a character replaces active selection."""
    async def _run():
        app = KeybindingTestApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#test-input", EnhancedInput)
            inp.focus()
            await pilot.press("ctrl+a")
            await pilot.press("x")
            assert inp.value == "x"

    asyncio.run(_run())


def test_enhanced_input_ctrl_c_with_and_without_selection():
    """Test that Ctrl+C copies selection if active, or full value if no selection."""
    async def _run():
        app = KeybindingTestApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#test-input", EnhancedInput)
            inp.focus()

            # 1. No selection: copies full value
            inp.cursor_position = 2
            assert inp.selected_text == ""
            await pilot.press("ctrl+c")
            assert app.clipboard == "hello world foo"

            # 2. With selection: copies selected slice
            inp.selection = (0, 5)  # "hello"
            await pilot.press("ctrl+c")
            assert app.clipboard == "hello"

    asyncio.run(_run())


def test_enhanced_input_ctrl_x_with_and_without_selection():
    """Test that Ctrl+X cuts selection if active, or cuts full field if no selection."""
    async def _run():
        app = KeybindingTestApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#test-input", EnhancedInput)
            inp.focus()

            # 1. With selection: cuts selection
            inp.selection = (0, 6)  # "hello "
            await pilot.press("ctrl+x")
            assert inp.value == "world foo"
            assert app.clipboard == "hello "

            # 2. Without selection: cuts entire field
            inp.cursor_position = 3
            assert inp.selected_text == ""
            await pilot.press("ctrl+x")
            assert inp.value == ""
            assert app.clipboard == "world foo"

    asyncio.run(_run())


def test_enhanced_input_ctrl_v_paste_and_replace():
    """Test that Ctrl+V pastes at cursor or replaces selection."""
    async def _run():
        app = KeybindingTestApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#test-input", EnhancedInput)
            inp.focus()

            # Set clipboard
            app.copy_to_clipboard("123")

            # 1. Paste at cursor (no selection)
            inp.cursor_position = 5
            inp.selection = (5, 5)
            await pilot.press("ctrl+v")
            assert inp.value == "hello123 world foo"

            # 2. Paste over selection
            inp.selection = (5, 8)  # "123"
            app.copy_to_clipboard("456")
            await pilot.press("ctrl+v")
            assert inp.value == "hello456 world foo"

    asyncio.run(_run())


def test_enhanced_input_ctrl_backspace_word_deletion():
    """Test that Ctrl+Backspace deletes backward one word at a time."""
    async def _run():
        app = KeybindingTestApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#test-input", EnhancedInput)
            inp.focus()
            inp.value = "one two three"
            inp.cursor_position = 13  # end

            await pilot.press("ctrl+backspace")
            assert inp.value == "one two "

            await pilot.press("ctrl+backspace")
            assert inp.value == "one "

            await pilot.press("ctrl+backspace")
            assert inp.value == ""

    asyncio.run(_run())


def test_enhanced_input_ctrl_backspace_password_field():
    """Test that Ctrl+Backspace in password inputs deletes word by word rather than whole input."""
    async def _run():
        app = KeybindingTestApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#password-input", EnhancedInput)
            inp.focus()
            await pilot.pause()
            inp.value = "sk-proj-abc-123"
            inp.cursor_position = len(inp.value)
            inp.selection = (len(inp.value), len(inp.value))

            await pilot.press("ctrl+backspace")
            assert inp.value == "sk-proj-abc-"

            await pilot.press("ctrl+backspace")
            assert inp.value == "sk-proj-"

    asyncio.run(_run())


def test_enhanced_input_ctrl_backspace_deletes_selection():
    """Test that Ctrl+Backspace deletes selection if one exists."""
    async def _run():
        app = KeybindingTestApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#test-input", EnhancedInput)
            inp.focus()
            inp.selection = (0, 5)  # "hello"
            await pilot.press("ctrl+backspace")
            assert inp.value == " world foo"

    asyncio.run(_run())


def test_enhanced_input_delete_key():
    """Test Delete key deletes character to the right or active selection."""
    async def _run():
        app = KeybindingTestApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#test-input", EnhancedInput)
            inp.focus()

            # Delete single character right
            inp.cursor_position = 0
            inp.selection = (0, 0)
            await pilot.press("delete")
            assert inp.value == "ello world foo"

            # Delete active selection
            inp.selection = (0, 4)  # "ello"
            await pilot.press("delete")
            assert inp.value == " world foo"

    asyncio.run(_run())


def test_enhanced_input_backspace_key():
    """Test Backspace key deletes character to the left or active selection."""
    async def _run():
        app = KeybindingTestApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#test-input", EnhancedInput)
            inp.focus()

            # Delete active selection with backspace
            inp.selection = (0, 5)  # "hello"
            await pilot.press("backspace")
            assert inp.value == " world foo"

    asyncio.run(_run())


def test_enhanced_input_ctrl_delete():
    """Test Ctrl+Delete deletes word to the right or active selection."""
    async def _run():
        app = KeybindingTestApp()
        async with app.run_test() as pilot:
            inp = app.query_one("#test-input", EnhancedInput)
            inp.focus()

            # Ctrl+Delete forward
            inp.cursor_position = 0
            inp.selection = (0, 0)
            await pilot.press("ctrl+delete")
            assert inp.value == "world foo"

    asyncio.run(_run())


def test_clipboard_cross_platform():
    """Test get_system_clipboard and set_system_clipboard fallback and platform dispatch."""
    set_system_clipboard("circuitgen-clip-test")
    assert get_system_clipboard() == "circuitgen-clip-test"

    # Test Darwin mocked
    with patch("sys.platform", "darwin"):
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(stdout="mac-text")
            assert _get_darwin_clipboard() == "mac-text"
            assert _set_darwin_clipboard("test-mac") is True

    # Test Linux mocked
    with patch("sys.platform", "linux"):
        with patch("shutil.which", return_value="/usr/bin/wl-paste"):
            with patch("subprocess.run") as mock_sub:
                mock_sub.return_value = MagicMock(stdout="linux-text")
                assert _get_linux_clipboard() == "linux-text"

    # Test Exception resilience
    with patch("subprocess.run", side_effect=Exception("Failed")):
        assert _get_darwin_clipboard() is None
        assert _set_darwin_clipboard("fail") is False
        assert _get_linux_clipboard() is None
        assert _set_linux_clipboard("fail") is False


def test_circuitgen_app_clipboard_integration():
    """Test CircuitGenApp clipboard property and copy_to_clipboard integration."""
    app = CircuitGenApp()
    app.copy_to_clipboard("test-app-clipboard")
    assert app.clipboard == "test-app-clipboard"
