"""Home Screen for CircuitGen interactive TUI (§2.4)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from circuitgen import __version__
from ..widgets.selectable_menu import MenuItem, SelectableMenu
from .render import RenderModeScreen
from .validate import ValidateModeScreen


MENU_ITEMS = [
    MenuItem("generate", "Generate", "Create a schematic from a description"),
    MenuItem("render", "Render", "Render a JSON netlist as a schematic"),
    MenuItem("validate", "Validate", "Check a JSON netlist for errors"),
    MenuItem("settings", "Settings", "Configure providers and preferences"),
    MenuItem("help", "Help", "Guides, examples, and shortcuts"),
]


def get_ai_status() -> tuple[str, str]:
    from circuitgen.ai import PROVIDER_DISPLAY_NAMES
    from ..services.config import ConfigService
    from ..services.credentials import CredentialService
    from ..services.models import ModelService

    config = ConfigService.load()
    _, source = CredentialService.resolve_key(config.default_provider)
    if source == "none":
        return "AI: Not configured", ""
    provider = PROVIDER_DISPLAY_NAMES[config.default_provider].replace("Google ", "")
    model = config.explicit_model if config.model_mode == "manual" else None
    model = model or ModelService.get_recommended_model(config.default_provider)
    return f"Provider: {provider}", f"Model: {model}"


class HomeScreen(Screen[None]):
    """CircuitGen primary Home menu screen."""

    BINDINGS = [
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
                left_status, right_status = get_ai_status()
                with Horizontal(id="home-status-row"):
                    yield Static(left_status, classes="status-left")
                    yield Static(right_status, classes="status-right status-accent", markup=False)

                # Shortcut keys reminder
                yield Static(
                    "↑↓ Navigate  ·  Enter Select  ·  Ctrl+Q / q Quit",
                    classes="keys-reminder",
                )

        yield Footer()

    def on_mount(self) -> None:
        self.query_one(SelectableMenu).focus()

    def on_screen_resume(self) -> None:
        left = self.query(".status-left").first(Static) if self.query(".status-left") else None
        if left is not None:
            status, model = get_ai_status()
            left.update(status)
            self.query_one(".status-right", Static).update(model)

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        if key == "generate":
            from .generate import GenerateScreen
            self.app.push_screen(GenerateScreen())
            return
        if key == "render":
            self.app.push_screen(RenderModeScreen())
            return
        if key == "validate":
            self.app.push_screen(ValidateModeScreen())
            return
        if key == "settings":
            from .settings import SettingsScreen
            self.app.push_screen(SettingsScreen())
            return
        if key == "help":
            self.action_help()

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_help(self) -> None:
        from .help import HelpScreen
        self.app.push_screen(HelpScreen())
