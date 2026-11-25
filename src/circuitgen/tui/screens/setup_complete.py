"""First-run setup screen S4 — Complete (§3.5)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Header, Static

from circuitgen.ai import PROVIDER_DISPLAY_NAMES
from circuitgen.tui.screens.home import HomeScreen
from circuitgen.tui.services.config import ConfigService
from circuitgen.tui.services.credentials import CredentialService
from circuitgen.tui.services.models import ModelService
from circuitgen.tui.widgets.selectable_menu import MenuItem, SelectableMenu


class SetupCompleteScreen(Screen[None]):
    """First-run setup complete screen (Step 4 of 4 summary)."""

    BINDINGS = [
        Binding("escape", "home", "Home", show=False),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(self, provider_id: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.provider_id = provider_id

    def compose(self) -> ComposeResult:
        config = ConfigService.load()
        pid = self.provider_id or config.default_provider
        provider_name = PROVIDER_DISPLAY_NAMES.get(pid, pid.title())
        reopened = any(getattr(screen, "restart", False) for screen in self.app.screen_stack)

        # Resolve credential status truthfully
        _, source = CredentialService.resolve_key(pid)
        if source == "environment":
            env_var = CredentialService.get_provider_env_var(pid)
            key_status = f"Configured (environment: {env_var})"
        elif source == "keyring":
            key_status = "Configured (secure storage)"
        else:
            key_status = "Not configured (offline mode only)"

        # Model policy description
        if config.model_mode == "manual" and config.explicit_model:
            model_desc = config.explicit_model
        else:
            rec_model = ModelService.get_recommended_model(pid)
            model_desc = f"Automatic ({rec_model})"

        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                # Header row
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Setup", classes="breadcrumb-left")
                    yield Static("Complete", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")

                # Title
                yield Static("✓ Setup complete", classes="setup-title")
                yield Static("Your CircuitGen environment is configured and ready.", classes="setup-tagline")

                # Summary Info Card
                with Vertical(classes="summary-card"):
                    with Horizontal(classes="summary-row"):
                        yield Static("Provider", classes="summary-label")
                        yield Static(provider_name, classes="summary-value")
                    with Horizontal(classes="summary-row"):
                        yield Static("API key", classes="summary-label")
                        yield Static(key_status, classes="summary-value")
                    with Horizontal(classes="summary-row"):
                        yield Static("Model", classes="summary-label")
                        yield Static(model_desc, classes="summary-value")
                    with Horizontal(classes="summary-row"):
                        yield Static("Output", classes="summary-label")
                        yield Static(config.default_output_dir, classes="summary-value")

                yield Static("─" * 62, classes="rule")

                # Action Menu
                yield SelectableMenu(
                    [MenuItem("home", "Back to Settings", "")] if reopened else [
                        MenuItem("home", "Go to home", "Open CircuitGen main menu"),
                        MenuItem("generate", "Start generating", "Create a circuit schematic with AI"),
                        MenuItem("settings", "Open settings", "Review preferences and connections"),
                    ],
                    initial_index=0,
                    id="setup-complete-menu",
                )

                yield Static("─" * 62, classes="rule")

                yield Static(
                    f"↑↓ Navigate  ·  Enter Select  ·  Esc {'Settings' if reopened else 'Home'}  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        """Handle completion menu action."""
        config = ConfigService.load()
        config.mark_onboarding_completed()
        ConfigService.save(config)

        if self.app.return_from_reopened_setup():
            return
        if event.item.key == "home":
            self.app.switch_screen(HomeScreen())
        elif event.item.key == "generate":
            from .generate import GenerateScreen
            self.app.switch_screen(HomeScreen())
            self.app.push_screen(GenerateScreen())
        elif event.item.key == "settings":
            from .settings import SettingsScreen
            self.app.switch_screen(HomeScreen())
            self.app.push_screen(SettingsScreen())

    def action_home(self) -> None:
        """Escape goes directly to Home, marking onboarding complete."""
        config = ConfigService.load()
        config.mark_onboarding_completed()
        ConfigService.save(config)
        if not self.app.return_from_reopened_setup():
            self.app.switch_screen(HomeScreen())

    def action_quit(self) -> None:
        """Exit app, preserving completion."""
        config = ConfigService.load()
        config.mark_onboarding_completed()
        ConfigService.save(config)
        self.app.exit()
