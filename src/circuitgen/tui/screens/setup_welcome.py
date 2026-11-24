"""First-run setup screen S0 — Welcome (§3.1)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Header, Static

from circuitgen.tui.screens.home import HomeScreen
from circuitgen.tui.screens.setup_provider import SetupProviderScreen
from circuitgen.tui.services.config import ConfigService
from circuitgen.tui.widgets.selectable_menu import MenuItem, SelectableMenu


class SetupWelcomeScreen(Screen[None]):
    """First-run setup welcome screen (Step 1 of 4)."""

    BINDINGS = [
        Binding("escape", "skip", "Skip", show=False),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("q", "quit", "Quit", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                # Header breadcrumb / step indicator row
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Setup", classes="breadcrumb-left")
                    yield Static("Step 1 of 4", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")

                # Title & Description
                yield Static("Welcome to CircuitGen", classes="setup-title")
                yield Static(
                    "Generate schematics with AI, or render and validate JSON\n"
                    "netlists without an API key.",
                    classes="setup-tagline",
                )

                # Action menu
                yield SelectableMenu(
                    [
                        MenuItem("setup_ai", "Set up AI generation", "Configure your AI provider"),
                        MenuItem("skip", "Skip for now", "Go directly to Home"),
                    ],
                    initial_index=0,
                    id="setup-menu",
                )

                yield Static("─" * 62, classes="rule")

                # Footer shortcut reminder
                yield Static(
                    "↑↓ Navigate  ·  Enter Continue  ·  Esc Skip  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        """Handle menu selection."""
        if event.item.key == "setup_ai":
            self.app.push_screen(SetupProviderScreen())
        elif event.item.key == "skip":
            self.action_skip()

    def action_skip(self) -> None:
        """Mark onboarding as skipped and proceed to Home screen."""
        config = ConfigService.load()
        config.mark_onboarding_skipped()
        ConfigService.save(config)
        self.app.switch_screen(HomeScreen())

    def action_quit(self) -> None:
        """Exit the application without marking onboarding as completed or skipped."""
        self.app.exit()
