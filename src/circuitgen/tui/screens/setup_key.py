"""First-run setup screen S2 — API Key input and secure credential storage (§3.3)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Header, Input, Static

from circuitgen.ai import PROVIDER_DISPLAY_NAMES
from circuitgen.tui.screens.home import HomeScreen
from circuitgen.tui.screens.setup_model import SetupModelScreen
from circuitgen.tui.services.config import ConfigService
from circuitgen.tui.services.credentials import CredentialService, InsecureBackendError
from circuitgen.tui.widgets.selectable_menu import MenuItem, SelectableMenu


class SetupKeyScreen(Screen[None]):
    """First-run setup API key screen (Step 3 of 4)."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("q", "quit", "Quit", show=False),
        Binding("tab", "toggle_focus", "Toggle Focus", show=False),
    ]

    def __init__(self, provider_id: str = "gemini", **kwargs) -> None:
        super().__init__(**kwargs)
        self.provider_id = provider_id

    def compose(self) -> ComposeResult:
        provider_name = PROVIDER_DISPLAY_NAMES.get(self.provider_id, self.provider_id.title())

        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                # Header row
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Setup", classes="breadcrumb-left")
                    yield Static("Step 3 of 4", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")

                # Title & input
                yield Static(f"Connect {provider_name}", classes="setup-title")
                yield Static("API key", classes="input-field-label")
                yield Input(
                    placeholder="Paste your API key here",
                    password=True,
                    id="key-input",
                )

                # Dynamic status / verification feedback message
                yield Static("", id="key-status-message", classes="status-message")

                # Action menu
                yield SelectableMenu(
                    [
                        MenuItem("verify", "Verify and save key", "Test connection with provider and save to secure storage"),
                        MenuItem("save_unverified", "Save without verification", "Save key directly to secure storage without testing"),
                        MenuItem("how_to_get", "How do I get an API key?", f"View official key portal for {provider_name}"),
                        MenuItem("skip", "Skip for now", "Continue to Home without configuring an API key"),
                    ],
                    initial_index=0,
                    id="key-action-menu",
                )

                yield Static("The full key is never displayed or written to config files.", classes="privacy-note")

                yield Static("─" * 62, classes="rule")

                yield Static(
                    "Tab Next field  ·  Enter Select  ·  Esc Back  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_mount(self) -> None:
        """Focus the key input on initial mount."""
        try:
            self.query_one("#key-input", Input).focus()
        except Exception:
            pass

    def action_toggle_focus(self) -> None:
        """Toggle focus between key input and menu with Tab."""
        key_input = self.query_one("#key-input", Input)
        menu = self.query_one("#key-action-menu", SelectableMenu)
        if key_input.has_focus:
            menu.focus()
        else:
            key_input.focus()

    def set_status(self, message: str) -> None:
        """Display feedback status message."""
        try:
            status_widget = self.query_one("#key-status-message", Static)
            status_widget.update(message)
        except Exception:
            pass

    def clear_secret(self) -> None:
        """Dispose of the secret from input memory."""
        try:
            self.query_one("#key-input", Input).value = ""
        except Exception:
            pass

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        """Handle menu action."""
        action_key = event.item.key
        key_input = self.query_one("#key-input", Input)
        entered_key = key_input.value.strip()

        if action_key == "verify":
            if not entered_key:
                self.set_status("! Please enter an API key first.")
                key_input.focus()
                return

            if not CredentialService.is_secure_backend_available():
                env_var = CredentialService.get_provider_env_var(self.provider_id)
                self.set_status(
                    f"! Secure credential store is unavailable.\n"
                    f"  Set {env_var} environment variable or choose Save without verification."
                )
                return

            self.set_status("Verifying API key with provider...")
            res = CredentialService.verify_key(self.provider_id, entered_key)
            if res.success:
                try:
                    CredentialService.save_key(self.provider_id, entered_key)
                except Exception as exc:
                    self.set_status(f"! Failed to save key: {exc}")
                    return
                self.clear_secret()
                self.app.push_screen(SetupModelScreen(provider_id=self.provider_id))
            else:
                self.set_status(res.message)

        elif action_key == "save_unverified":
            if not entered_key:
                self.set_status("! Please enter an API key first.")
                key_input.focus()
                return

            try:
                CredentialService.save_key(self.provider_id, entered_key)
            except InsecureBackendError as exc:
                self.set_status(f"! {exc}")
                return
            except Exception as exc:
                self.set_status(f"! Could not save credential: {exc}")
                return

            self.clear_secret()
            self.app.push_screen(SetupModelScreen(provider_id=self.provider_id))

        elif action_key == "how_to_get":
            url = CredentialService.get_provider_url(self.provider_id)
            provider_name = PROVIDER_DISPLAY_NAMES.get(self.provider_id, self.provider_id.title())
            self.set_status(f"Official {provider_name} API portal:\n{url}")

        elif action_key == "skip":
            self.clear_secret()
            config = ConfigService.load()
            config.mark_onboarding_skipped()
            ConfigService.save(config)
            self.app.switch_screen(HomeScreen())

    def action_back(self) -> None:
        """Return to previous screen, clearing the secret from memory."""
        self.clear_secret()
        self.app.pop_screen()

    def action_quit(self) -> None:
        """Exit application, wiping secret from memory."""
        self.clear_secret()
        self.app.exit()
