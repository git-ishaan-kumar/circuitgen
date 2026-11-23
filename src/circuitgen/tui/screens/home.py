"""Home Screen for CircuitGen interactive TUI (§2.4)."""
from __future__ import annotations

import os

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from circuitgen import __version__
from ..widgets.selectable_menu import MenuItem, SelectableMenu
from .placeholder import PlaceholderScreen


MENU_ITEMS = [
    MenuItem("generate", "Generate", "Create a schematic from a description"),
    MenuItem("render", "Render", "Render a JSON netlist into an SVG"),
    MenuItem("validate", "Validate", "Check a JSON netlist for errors"),
    MenuItem("settings", "Settings", "Configure providers and preferences"),
    MenuItem("help", "Help", "Guides, examples, and shortcuts"),
]


def get_ai_status() -> tuple[str, str, bool]:
    """Return (left_status, right_status, is_configured) based on environment / configuration."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        return "AI: Gemini · Automatic", "Key: Environment", True

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        return "AI: OpenAI · Automatic", "Key: Environment", True

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        return "AI: Anthropic · Automatic", "Key: Environment", True

    return "AI: Not configured", "", False


class HomeScreen(Screen[None]):
    """CircuitGen primary Home menu screen."""

    BINDINGS = [
        Binding("ctrl+q", "quit_app", "Quit", show=True, priority=True),
        Binding("q", "quit_app", "Quit", show=False),
        Binding("question_mark", "help", "Help", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                # Wordmark & Version line
                with Horizontal(classes="brand-header-row"):
                    yield Static("CircuitGen", classes="brand-title")
                    yield Static(f"v{__version__}", classes="brand-version")

                # Tagline
                yield Static("Circuit schematics from text descriptions or netlists.", classes="tagline")

                # Rule separator (horizontal bar)
                yield Static("─" * 62, classes="rule")

                # Prompt
                yield Static("What would you like to do?", classes="prompt-text")

                # 5-item Selectable Menu
                yield SelectableMenu(MENU_ITEMS, initial_index=0, id="main-menu")

                # Rule separator
                yield Static("─" * 62, classes="rule")

                # Status row
                left_status, right_status, configured = get_ai_status()
                with Horizontal(id="home-status-row"):
                    yield Static(left_status, classes="status-left")
                    if right_status:
                        yield Static(right_status, classes="status-right status-accent")

                # Shortcut keys reminder
                yield Static(
                    "↑↓ Navigate  ·  Enter Select  ·  Ctrl+Q / q Quit",
                    classes="keys-reminder",
                )

        yield Footer()

    def on_mount(self) -> None:
        self.query_one(SelectableMenu).focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        page_titles = {
            "generate": ("Generate", "Create a schematic from a natural-language description"),
            "render": ("Render", "Render a JSON netlist into an SVG"),
            "validate": ("Validate", "Check a JSON netlist for structural/electrical errors"),
            "settings": ("Settings", "Configure providers, preferences, and API keys"),
            "help": ("Help", "Guides, examples, and shortcuts"),
        }
        name, desc = page_titles.get(key, (message.item.label, ""))
        self.app.push_screen(PlaceholderScreen(page_name=name, description=desc))

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_help(self) -> None:
        self.app.push_screen(PlaceholderScreen(page_name="Help", description="Guides, examples, and shortcuts"))
