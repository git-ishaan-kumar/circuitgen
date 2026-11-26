"""Keyboard behavior in the circuit description editor."""

import asyncio
from textual.app import App, ComposeResult

from circuitgen.tui.widgets import JsonEditor


class PromptEditorApp(App):
    def compose(self) -> ComposeResult:
        yield JsonEditor(language=None, auto_lists=True, id="prompt")
        yield JsonEditor(id="netlist")


def test_numbered_and_bulleted_lists_continue_and_can_be_cancelled():
    asyncio.run(_check_list_continuation())


async def _check_list_continuation():
    async with PromptEditorApp().run_test() as pilot:
        editor = pilot.app.query_one("#prompt", JsonEditor)
        editor.focus()
        for initial, next_item in (
            ("1. first", "2. "),
            ("  9) first", "  10) "),
            ("* first", "* "),
            ("- first", "- "),
            ("+ first", "+ "),
            ("• first", "• "),
        ):
            editor.text = initial
            editor.cursor_location = (0, len(initial))
            await pilot.press("enter")
            assert editor.text == f"{initial}\n{next_item}"
            await pilot.press("backspace")
            assert editor.text == f"{initial}\n"

            editor.text = f"{initial}\n{next_item}"
            editor.cursor_location = (1, len(next_item))
            await pilot.press("enter")
            assert editor.text == f"{initial}\n"


def test_list_continuation_stays_flexible_and_json_editor_is_unchanged():
    asyncio.run(_check_editor_modes())


async def _check_editor_modes():
    async with PromptEditorApp().run_test() as pilot:
        prompt = pilot.app.query_one("#prompt", JsonEditor)
        prompt.focus()
        prompt.text = "1. first"
        prompt.cursor_location = (0, 3)
        await pilot.press("enter")
        assert prompt.text == "1. \nfirst"

        prompt.text = "1. first"
        prompt.cursor_location = (0, len(prompt.text))
        await pilot.press("enter")
        await pilot.press("x")
        assert prompt.text == "1. first\n2. x"

        netlist = pilot.app.query_one("#netlist", JsonEditor)
        netlist.text = "1. first"
        netlist.cursor_location = (0, len(netlist.text))
        netlist.focus()
        await pilot.press("enter")
        assert netlist.text == "1. first\n"
