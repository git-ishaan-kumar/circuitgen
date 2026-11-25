"""First-run setup screen S1 — Choose AI provider (§3.2)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Header, Static

from circuitgen.ai import PROVIDER_DISPLAY_NAMES, list_providers
from circuitgen.tui.screens.setup_key import SetupKeyScreen
from circuitgen.tui.services.config import ConfigService
from circuitgen.tui.widgets.selectable_menu import MenuItem, SelectableMenu

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "gemini": "Google Gemini",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "groq": "Groq",
    "mistral": "Mistral",
    "xai": "xAI",
    "openrouter": "OpenRouter",
    "together": "Together AI",
    "fireworks": "Fireworks AI",
    "cerebras": "Cerebras",
}


class SetupProviderScreen(Screen[None]):
    """First-run setup provider selection screen (Step 2 of 4)."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("q", "quit", "Quit", show=False),
    ]

    def compose(self) -> ComposeResult:
        config = ConfigService.load()
        current_provider = config.default_provider

        # Build menu items from actual provider registry
        registered_providers = list_providers()
        menu_items: list[MenuItem] = []
        initial_index = 0

        for idx, pid in enumerate(registered_providers):
            display_name = PROVIDER_DISPLAY_NAMES.get(pid, pid.title())
            menu_items.append(MenuItem(pid, display_name, f"Use {display_name} for AI generation"))
            if pid == current_provider:
                initial_index = idx

        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Setup", classes="breadcrumb-left")
                    yield Static("Step 2 of 4", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")

                yield Static("Choose your AI provider", classes="setup-title")
                yield Static("You can change this later in Settings.", classes="setup-tagline")

                yield SelectableMenu(menu_items, initial_index=initial_index, max_visible=10, id="provider-menu")

                yield Static("─" * 62, classes="rule")

                yield Static(
                    "↑↓ / PgUp/PgDn Navigate  ·  Enter Select  ·  Esc Back  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        """Handle provider selection."""
        provider_id = event.item.key
        config = ConfigService.load()
        if not any(getattr(screen, "restart", False) for screen in self.app.screen_stack):
            if config.default_provider != provider_id:
                config.model_mode, config.explicit_model = "automatic", None
            config.default_provider = provider_id
            ConfigService.save(config)

        # Advance to Step 3 API key setup (Phase 4)
        self.app.push_screen(SetupKeyScreen(provider_id=provider_id))

    def action_back(self) -> None:
        """Go back to Setup Welcome screen."""
        self.app.pop_screen()

    def action_quit(self) -> None:
        """Exit without completing onboarding."""
        self.app.exit()
