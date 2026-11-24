"""First-run setup placeholder for remaining steps (Step 3/4)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Header, Static

from circuitgen.tui.screens.home import HomeScreen
from circuitgen.tui.services.config import ConfigService
from circuitgen.tui.widgets.selectable_menu import MenuItem, SelectableMenu


class SetupStepPlaceholderScreen(Screen[None]):
    """Placeholder screen for setup steps during development (e.g. Step 3 - API key)."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(self, step: int = 3, provider_id: str = "gemini", **kwargs) -> None:
        super().__init__(**kwargs)
        self.step = step
        self.provider_id = provider_id

    def compose(self) -> ComposeResult:
        from circuitgen.tui.screens.setup_provider import PROVIDER_DISPLAY_NAMES

        provider_name = PROVIDER_DISPLAY_NAMES.get(self.provider_id, self.provider_id)

        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Setup", classes="breadcrumb-left")
                    yield Static(f"Step {self.step} of 4", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")

                yield Static(f"Connect {provider_name}", classes="setup-title")
                yield Static(
                    "Secure API key storage and verification will be configured in Phase 4.\n"
                    "You can proceed to Home or return to adjust provider selection.",
                    classes="setup-tagline",
                )

                yield SelectableMenu(
                    [
                        MenuItem("home", "Go to home", "Complete setup and open Home screen"),
                        MenuItem("back", "Change provider", "Return to provider selection"),
                    ],
                    initial_index=0,
                    id="setup-step-menu",
                )

                yield Static("─" * 62, classes="rule")

                yield Static(
                    "↑↓ Navigate  ·  Enter Select  ·  Esc Back  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        if event.item.key == "home":
            config = ConfigService.load()
            config.mark_onboarding_completed()
            ConfigService.save(config)
            self.app.switch_screen(HomeScreen())
        elif event.item.key == "back":
            self.action_back()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
