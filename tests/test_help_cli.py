import asyncio
import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from circuitgen.cli import main
from circuitgen import __version__, from_netlist
from circuitgen.tui.app import CircuitGenApp
from circuitgen.tui.screens.generate import GenerateScreen
from circuitgen.tui.screens.help import EXAMPLES, HelpScreen, LED_NETLIST
from circuitgen.tui.screens.home import HomeScreen
from circuitgen.tui.screens.render import RenderPasteScreen
from circuitgen.tui.screens.settings import SettingsScreen
from circuitgen.tui.services.config import AppConfig, ConfigService
from circuitgen.tui.widgets import JsonEditor, SelectableMenu


class TestDirectCommands(unittest.TestCase):
    def test_example_topologies_render(self):
        components = [
            {"id": "B1", "type": "battery", "value": "9V"},
            {"id": "R1", "type": "resistor", "value": ""},
            {"id": "R2", "type": "resistor", "value": ""},
        ]
        series = [
            {"name": "POS", "pins": ["B1.p", "R1.a"]},
            {"name": "MID", "pins": ["R1.b", "R2.a"]},
            {"name": "GND", "pins": ["R2.b", "B1.n"]},
        ]
        parallel = [
            {"name": "POS", "pins": ["B1.p", "R1.a", "R2.a"]},
            {"name": "GND", "pins": ["B1.n", "R1.b", "R2.b"]},
        ]
        for nets in (series, parallel):
            self.assertIn("<svg", from_netlist({"components": components, "nets": nets}, output=None).svg)

    def test_help_and_version_are_noninteractive(self):
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:
                main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("render", output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:
                main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(f"CircuitGen {__version__}\n", output.getvalue())

    def test_validate_stdin_exit_codes(self):
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(LED_NETLIST))), redirect_stdout(output):
            self.assertEqual(main(["validate", "--stdin", "--no-color"]), 0)
        self.assertIn("valid", output.getvalue())
        error = io.StringIO()
        with patch("sys.stdin", io.StringIO("{")), redirect_stderr(error):
            self.assertEqual(main(["validate", "--stdin"]), 1)
        self.assertIn("line 1, column 2", error.getvalue())

    def test_render_stdin_uses_library_and_atomic_writer(self):
        output = io.StringIO()
        with (patch("sys.stdin", io.StringIO(json.dumps(LED_NETLIST))),
              patch("circuitgen.tui.services.file_io.FileIOService.save_output",
                    return_value=(True, "saved")) as save,
              redirect_stdout(output)):
            self.assertEqual(main(["render", "--stdin", "-o", "phase13-test.svg"]), 0)
        self.assertTrue(save.call_args.args[0].startswith("<svg"))
        self.assertIn("Saved", output.getvalue())

    def test_existing_file_needs_force(self):
        error = io.StringIO()
        with (patch("sys.stdin", io.StringIO(json.dumps(LED_NETLIST))),
              patch("pathlib.Path.exists", return_value=True), redirect_stderr(error)):
            self.assertEqual(main(["render", "--stdin", "-o", "existing.svg"]), 1)
        self.assertIn("--force", error.getvalue())

    def test_generate_reports_actual_model(self):
        def netlist(*args, on_model=None, **kwargs):
            on_model("model-used")
            return LED_NETLIST
        output = io.StringIO()
        with (patch("circuitgen.ai.generate_netlist", side_effect=netlist),
              patch.object(ConfigService, "load", return_value=AppConfig()),
              patch("circuitgen.tui.services.file_io.FileIOService.save_output",
                    return_value=(True, "saved")), redirect_stdout(output)):
            self.assertEqual(main(["generate", EXAMPLES["led"][1], "-o", "phase13-test.svg"]), 0)
        self.assertIn("Model: model-used", output.getvalue())

    def test_config_show_omits_keys(self):
        output = io.StringIO()
        with (patch.object(ConfigService, "load", return_value=AppConfig()),
              redirect_stdout(output)):
            self.assertEqual(main(["config", "--show"]), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["default_provider"], "gemini")
        self.assertFalse(any("key" in field for field in data))


class TestHelpNavigation(unittest.TestCase):
    def test_no_color_environment_is_respected(self):
        async def run():
            with (patch.dict(os.environ, {"NO_COLOR": "1"}),
                  patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed"))):
                app = CircuitGenApp()
                async with app.run_test(size=(80, 24)):
                    self.assertTrue(app._plain_colors)
        asyncio.run(run())

    def test_all_help_topics_open_at_small_terminal_size(self):
        async def run():
            with patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed",
                                                                             terminal_colors="none")):
                app = CircuitGenApp()
                async with app.run_test(size=(80, 24)) as pilot:
                    for topic in ("start", "commands", "shortcuts", "examples", "trouble", "docs"):
                        app.push_screen(HelpScreen(topic))
                        await pilot.pause()
                        self.assertEqual(app.screen.topic, topic)
                        self.assertTrue(app.screen.query_one(SelectableMenu).items)
                        await pilot.press("escape")
                        await pilot.pause()
        asyncio.run(run())

    def test_example_copy_uses_plain_description(self):
        async def run():
            with patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed")):
                app = CircuitGenApp()
                async with app.run_test(size=(80, 24)) as pilot:
                    app.push_screen(HelpScreen("example:led"))
                    await pilot.pause()
                    with patch.object(app, "copy_to_clipboard") as copy:
                        menu = app.screen.query_one(SelectableMenu)
                        menu.selected_index = 1
                        menu.focus()
                        await pilot.press("enter")
                        await pilot.pause()
                        copy.assert_called_once_with(EXAMPLES["led"][1])
        asyncio.run(run())

    def test_ctrl_q_exits_help(self):
        async def run():
            with patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed")):
                app = CircuitGenApp()
                async with app.run_test(size=(80, 24)) as pilot:
                    app.push_screen(HelpScreen("shortcuts"))
                    await pilot.pause()
                    await pilot.press("ctrl+q")
                    await pilot.pause()
                    self.assertFalse(app.is_running)
        asyncio.run(run())

    def test_question_mark_stays_in_editor(self):
        async def run():
            with patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed")):
                app = CircuitGenApp()
                async with app.run_test(size=(80, 24)) as pilot:
                    app.push_screen(GenerateScreen())
                    await pilot.pause()
                    editor = app.screen.query_one(JsonEditor)
                    editor.focus()
                    await pilot.press("?")
                    await pilot.pause()
                    self.assertEqual(editor.text, "?")
                    self.assertIsInstance(app.screen, GenerateScreen)
        asyncio.run(run())

    def test_error_help_opens_matching_topic_and_returns(self):
        async def run():
            with patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed")):
                app = CircuitGenApp()
                async with app.run_test(size=(80, 24)) as pilot:
                    app.push_screen(GenerateScreen())
                    await pilot.pause()
                    page = app.screen
                    page.set_status("Selected model is unavailable.")
                    page.query_one(SelectableMenu).focus()
                    await pilot.press("?")
                    await pilot.pause()
                    self.assertEqual(app.screen.topic, "trouble:models")
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertIs(app.screen, page)
        asyncio.run(run())

    def test_topics_links_and_back_navigation(self):
        async def run():
            with patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed")):
                app = CircuitGenApp()
                async with app.run_test(size=(80, 24)) as pilot:
                    self.assertIsInstance(app.screen, HomeScreen)
                    menu = app.screen.query_one(SelectableMenu)
                    menu.selected_index = 4
                    menu.focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, HelpScreen)
                    self.assertEqual(len(app.screen.query_one(SelectableMenu).items), 6)
                    menu = app.screen.query_one(SelectableMenu)
                    menu.selected_index = 0
                    menu.focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertEqual(app.screen.topic, "start")
                    menu = app.screen.query_one(SelectableMenu)
                    menu.selected_index = 0
                    menu.focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, GenerateScreen)
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertEqual(app.screen.topic, "start")
                    menu = app.screen.query_one(SelectableMenu)
                    menu.selected_index = 1
                    menu.focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, SettingsScreen)
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertEqual(app.screen.topic, "start")
        asyncio.run(run())

    def test_example_prefills_generate(self):
        async def run():
            with patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed")):
                app = CircuitGenApp()
                async with app.run_test(size=(80, 24)) as pilot:
                    app.push_screen(HelpScreen("example:led"))
                    await pilot.pause()
                    menu = app.screen.query_one(SelectableMenu)
                    menu.selected_index = 0
                    menu.focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, GenerateScreen)
                    self.assertEqual(app.screen.query_one(JsonEditor).text, EXAMPLES["led"][1])
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertEqual(app.screen.topic, "example:led")
        asyncio.run(run())

    def test_json_example_opens_render_editor(self):
        async def run():
            with patch.object(ConfigService, "load", return_value=AppConfig(onboarding_status="completed")):
                app = CircuitGenApp()
                async with app.run_test(size=(80, 24)) as pilot:
                    app.push_screen(HelpScreen("example:json"))
                    await pilot.pause()
                    menu = app.screen.query_one(SelectableMenu)
                    menu.selected_index = 0
                    menu.focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, RenderPasteScreen)
                    self.assertEqual(json.loads(app.screen.query_one(JsonEditor).text), LED_NETLIST)
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertEqual(app.screen.topic, "example:json")
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
