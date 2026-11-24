"""First-run setup screen S3 — Model Selection and Discovery (§3.4, §8)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Header, Input, Static

from circuitgen.ai import PROVIDER_DISPLAY_NAMES
from circuitgen.tui.screens.setup_complete import SetupCompleteScreen
from circuitgen.tui.services.config import ConfigService
from circuitgen.tui.services.models import ModelService, ProviderError
from circuitgen.tui.widgets.selectable_menu import MenuItem, SelectableMenu


class SetupModelBrowseScreen(Screen[None]):
    """Browse and pick from discovered provider models."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(self, provider_id: str, models: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self.provider_id = provider_id
        self.models = models

    def compose(self) -> ComposeResult:
        provider_name = PROVIDER_DISPLAY_NAMES.get(self.provider_id, self.provider_id.title())
        menu_items = [
            MenuItem(mid, mid, f"{provider_name} model")
            for mid in self.models
        ]

        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Setup / Models", classes="breadcrumb-left")
                    yield Static("Browse Models", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")

                yield Static(f"Available {provider_name} Models", classes="setup-title")
                yield Static("Select a model to use as your default. (None are guaranteed free-tier)", classes="setup-tagline")

                yield SelectableMenu(menu_items, initial_index=0, max_visible=10, id="browse-models-menu")

                yield Static("─" * 62, classes="rule")

                yield Static(
                    "↑↓ / PgUp/PgDn Navigate  ·  Enter Select  ·  Esc Back  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        chosen_model_id = event.item.key
        config = ConfigService.load()
        config.model_mode = "manual"
        config.explicit_model = chosen_model_id
        ConfigService.save(config)
        self.app.push_screen(SetupCompleteScreen(provider_id=self.provider_id))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


class SetupModelManualScreen(Screen[None]):
    """Manual model ID entry screen."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(self, provider_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.provider_id = provider_id

    def compose(self) -> ComposeResult:
        provider_name = PROVIDER_DISPLAY_NAMES.get(self.provider_id, self.provider_id.title())

        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Setup / Models", classes="breadcrumb-left")
                    yield Static("Manual Entry", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")

                yield Static(f"Enter {provider_name} Model ID", classes="setup-title")
                yield Static("Specify a provider model ID (e.g. gpt-4o, claude-3-5-sonnet-20241022):", classes="setup-tagline")

                yield Input(placeholder="Enter custom model ID", id="manual-model-input")
                yield Static("", id="manual-model-status", classes="status-message")

                yield SelectableMenu(
                    [
                        MenuItem("save", "Save model ID", "Apply and proceed to setup complete"),
                        MenuItem("cancel", "Cancel", "Return to model options"),
                    ],
                    initial_index=0,
                    id="manual-model-menu",
                )

                yield Static("─" * 62, classes="rule")

                yield Static(
                    "Tab Toggle field  ·  Enter Select  ·  Esc Back  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_mount(self) -> None:
        try:
            self.query_one("#manual-model-input", Input).focus()
        except Exception:
            pass

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        if event.item.key == "cancel":
            self.action_back()
            return

        inp = self.query_one("#manual-model-input", Input)
        model_id = inp.value.strip()
        is_valid, msg = ModelService.validate_model_id(model_id)
        if not is_valid:
            try:
                self.query_one("#manual-model-status", Static).update(f"! {msg}")
            except Exception:
                pass
            inp.focus()
            return

        config = ConfigService.load()
        config.model_mode = "manual"
        config.explicit_model = model_id
        ConfigService.save(config)
        self.app.push_screen(SetupCompleteScreen(provider_id=self.provider_id))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


class SetupModelScreen(Screen[None]):
    """First-run setup model selection screen (Step 4 of 4)."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(self, provider_id: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.provider_id = provider_id or "gemini"

    def compose(self) -> ComposeResult:
        provider_name = PROVIDER_DISPLAY_NAMES.get(self.provider_id, self.provider_id.title())
        rec_model = ModelService.get_recommended_model(self.provider_id)

        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Setup", classes="breadcrumb-left")
                    yield Static("Step 4 of 4", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")

                yield Static("Choose your default model", classes="setup-title")
                yield Static(f"Provider: {provider_name}", classes="setup-tagline")

                yield Static("", id="model-status-message", classes="status-message")

                yield SelectableMenu(
                    [
                        MenuItem("auto", "Automatic (recommended)", f"Favors tested, lower-cost models ({rec_model})"),
                        MenuItem("browse", "Browse provider models", "Query available models via discovery"),
                        MenuItem("manual", "Enter model ID manually", "Specify a custom model identifier"),
                    ],
                    initial_index=0,
                    id="model-options-menu",
                )

                yield Static(
                    "Automatic favors compatible, lower-cost options but does\n"
                    "not guarantee free-tier availability.",
                    classes="privacy-note",
                )

                yield Static("─" * 62, classes="rule")

                yield Static(
                    "↑↓ Navigate  ·  Enter Continue  ·  Esc Back  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def set_status(self, message: str) -> None:
        try:
            self.query_one("#model-status-message", Static).update(message)
        except Exception:
            pass

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        choice = event.item.key

        if choice == "auto":
            config = ConfigService.load()
            config.model_mode = "automatic"
            config.explicit_model = None
            ConfigService.save(config)
            self.app.push_screen(SetupCompleteScreen(provider_id=self.provider_id))

        elif choice == "browse":
            self.set_status(f"Discovering models for {self.provider_id}...")
            try:
                models = ModelService.discover_models(self.provider_id)
                self.set_status("")
                self.app.push_screen(SetupModelBrowseScreen(self.provider_id, models))
            except ProviderError as exc:
                self.set_status(f"! Could not discover models: {exc}\nYou may enter a model ID manually or use Automatic.")
            except Exception as exc:
                self.set_status(f"! Discovery failed: {exc}")

        elif choice == "manual":
            self.app.push_screen(SetupModelManualScreen(self.provider_id))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
