"""Short, task-focused help inside the terminal."""
from __future__ import annotations

import json
import webbrowser

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Header, Static

from ..widgets import MenuItem, SelectableMenu


LED_NETLIST = {
    "components": [
        {"id": "B1", "type": "battery", "value": "9V"},
        {"id": "R1", "type": "resistor", "value": "330Ω"},
        {"id": "D1", "type": "led", "value": "red"},
    ],
    "nets": [
        {"name": "POS", "pins": ["B1.p", "R1.a"]},
        {"name": "LED", "pins": ["R1.b", "D1.a"]},
        {"name": "GND", "pins": ["D1.b", "B1.n"]},
    ],
}

EXAMPLES = {
    "led": ("Simple LED circuit", "A 9V battery connected to a red LED through a 330Ω resistor."),
    "series": ("Series resistors", "A 9V battery connected to two resistors in series, forming a closed loop."),
    "parallel": ("Parallel resistors", "A 9V battery connected to two resistors in parallel, forming two branches."),
    "json": ("JSON netlist", json.dumps(LED_NETLIST, indent=2, ensure_ascii=False)),
}

COMMANDS = {
    "generate": ("circuitgen generate \"A 9V battery connected to an LED through a 330Ω resistor.\" -o led.svg",
                 "Use a description and an AI provider. Set a provider and key in Settings first.\n"
                 "Options: --stdin, --provider, --model, -o/--output, --force."),
    "render": ("circuitgen render circuit.json -o circuit.svg",
               "Turn a JSON netlist into SVG, PNG, or PDF. No AI key needed.\n"
               "Options: --stdin, -o/--output, --force."),
    "validate": ("circuitgen validate circuit.json",
                 "Check a JSON netlist without making a file. No AI key needed.\nOption: --stdin."),
    "config": ("circuitgen config --show",
               "Show saved preferences without API keys. Run circuitgen config in a terminal to open Settings."),
    "help": ("circuitgen help render", "Show help for a command. Use circuitgen --help for the full list."),
}

TROUBLESHOOTING = {
    "keys": ("AI provider and API keys", "If Generate says no key is configured, open Settings → AI Providers.\n"
             "Choose a provider, then add or replace its key. Render and Validate work without one."),
    "models": ("Models, limits, and billing", "If a model is unavailable, use Browse models or clear Model ID to use the default.\n"
               "A model in the list may still be blocked for your key. For quota or billing errors, check your provider account."),
    "json": ("Invalid JSON or netlist", "Check the line and column in a JSON error.\n"
             "For netlist errors, check component IDs and pin names. Every pin reference must look like R1.a."),
    "parts": ("Unsupported parts", "For an unfamiliar part, add a pins list to its JSON component.\n"
              "Use the same pin names in the nets. These are logical pins, not a verified package pinout."),
    "files": ("Files and rendering", "Check the output folder and filename. Use --force only if you want to replace a file.\n"
              "A routing error means CircuitGen could not draw every connection clearly. Inspect the netlist."),
    "terminal": ("Installation and terminals", "Run circuitgen doctor to check the installation.\n"
                 "If the screen looks cramped, make the terminal at least 80 columns by 24 rows."),
}

TOPICS = [
    MenuItem("start", "Getting started", "Make your first circuit"),
    MenuItem("commands", "Commands", "Use CircuitGen without the TUI"),
    MenuItem("shortcuts", "Keyboard shortcuts", "Move, edit, and quit"),
    MenuItem("examples", "Examples", "Copy or use a circuit description"),
    MenuItem("trouble", "Troubleshooting", "Fix common problems"),
    MenuItem("docs", "Documentation", "README and project repository"),
]


class HelpScreen(Screen[None]):
    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self, topic: str = "") -> None:
        super().__init__()
        self.topic = topic

    def _content(self) -> tuple[str, str, list[MenuItem]]:
        topic = self.topic
        back = MenuItem("back", "Back", "")
        if not topic:
            return "Help", "Choose what you need.", TOPICS
        if topic == "start":
            return "Getting started", (
                "1. Set up an AI provider and key in Settings.\n"
                "2. Choose Generate on Home.\n"
                "3. Describe the circuit and choose a file.\n"
                "4. Generate it, then open the saved schematic.\n\n"
                "Try: A 9V battery connected to a red LED through a 330Ω resistor.\n\n"
                "Have a JSON netlist already? Use Render. It works offline."
            ), [MenuItem("generate", "Start generating", ""),
                MenuItem("settings", "Set up AI", ""), back]
        if topic == "commands":
            return "Commands", "Pick a command to see how to use it.", [
                *(MenuItem(f"command:{name}", name, detail[1].splitlines()[0])
                  for name, detail in COMMANDS.items()), back]
        if topic.startswith("command:"):
            name = topic.split(":", 1)[1]
            example, details = COMMANDS[name]
            return name, f"{details}\n\nExample:\n{example}", [
                MenuItem("copy", "Copy example", ""), back]
        if topic == "shortcuts":
            return "Keyboard shortcuts", (
                "↑ / ↓     Move through a menu\n"
                "Enter     Select an item\n"
                "Esc       Go back\n"
                "Tab       Move to the next field\n"
                "Shift+Tab Move to the previous field\n"
                "Ctrl+Q    Quit CircuitGen\n"
                "?         Open Help when you are not typing\n\n"
                "In a description or JSON editor, Enter adds a line.\n"
                "Copy and paste keys depend on your terminal. Try Ctrl+C / Ctrl+V or Ctrl+Shift+C / Ctrl+Shift+V.\n"
                "You can also right-click text to copy it, or blank space to paste into a focused field."
            ), [back]
        if topic == "examples":
            return "Examples", "Choose one to copy or use.", [
                *(MenuItem(f"example:{name}", label, "") for name, (label, _) in EXAMPLES.items()), back]
        if topic.startswith("example:"):
            name = topic.split(":", 1)[1]
            label, example = EXAMPLES[name]
            action = "Open in Render" if name == "json" else "Use in Generate"
            return label, example, [MenuItem("use", action, ""), MenuItem("copy", "Copy example", ""), back]
        if topic == "trouble":
            return "Troubleshooting", "Choose the problem you are seeing.", [
                *(MenuItem(f"trouble:{name}", label, "") for name, (label, _) in TROUBLESHOOTING.items()), back]
        if topic.startswith("trouble:"):
            label, advice = TROUBLESHOOTING[topic.split(":", 1)[1]]
            return label, advice, [back]
        return "Documentation", (
            "The README has installation steps, Python examples, and supported formats.\n"
            "The project repository is on GitHub."
        ), [MenuItem("repository", "Open project on GitHub", ""), back]

    def compose(self) -> ComposeResult:
        title, body, items = self._content()
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static(f"CircuitGen / Help{(' / ' + title) if self.topic else ''}",
                                 classes="breadcrumb-left")
                yield Static("─" * 62, classes="rule")
                yield Static(title, classes="prompt-text")
                yield Static(body, classes="help-body", markup=False)
                yield SelectableMenu(items, id="help-menu")
                yield Static("", id="help-status", classes="status-message", markup=False)
                yield Static("↑↓ Navigate  ·  Enter Select  ·  Esc Back  ·  Ctrl+Q Quit",
                             classes="keys-reminder")

    def on_mount(self) -> None:
        self.query_one(SelectableMenu).focus()

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        key = event.item.key
        if key == "back":
            self.action_back()
        elif key in {item.key for item in TOPICS} or key.startswith(("command:", "example:", "trouble:")):
            self.app.push_screen(HelpScreen(key))
        elif key == "generate":
            from .generate import GenerateScreen
            self.app.push_screen(GenerateScreen())
        elif key == "settings":
            from .settings import SettingsScreen
            self.app.push_screen(SettingsScreen())
        elif key == "copy":
            source = (COMMANDS[self.topic.split(":", 1)[1]][0] if self.topic.startswith("command:")
                      else EXAMPLES[self.topic.split(":", 1)[1]][1])
            self.app.copy_to_clipboard(source)
            self.query_one("#help-status", Static).update("Copied.")
        elif key == "use":
            name = self.topic.split(":", 1)[1]
            if name == "json":
                from .render import RenderPasteScreen
                self.app.push_screen(RenderPasteScreen(initial_json=EXAMPLES[name][1]))
            else:
                from .generate import GenerateScreen
                self.app.push_screen(GenerateScreen(description=EXAMPLES[name][1]))
        elif key == "repository":
            if not webbrowser.open("https://github.com/git-ishaan-kumar/circuitgen"):
                self.query_one("#help-status", Static).update("Could not open a browser.")

    def action_back(self) -> None:
        self.app.pop_screen()
