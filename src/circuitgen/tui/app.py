"""CircuitGen Textual Application Shell and Brand Palette."""
from __future__ import annotations

from typing import Any

from textual.app import App
from textual.binding import Binding

from circuitgen import __version__
from .screens.confirm_dialog import QuitModal
from .screens.home import HomeScreen
from .screens.setup_provider import SetupProviderScreen
from .screens.setup_step_placeholder import SetupStepPlaceholderScreen
from .screens.setup_welcome import SetupWelcomeScreen
from .services.config import ConfigService


class CircuitGenApp(App[None]):
    """Main Textual Application for CircuitGen."""

    TITLE = "CircuitGen"
    SUB_TITLE = f"v{__version__}"
    CSS_PATH = "theme.tcss"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("ctrl+q", "request_quit", "Quit", show=True, priority=True),
        Binding("q", "request_quit", "Quit", show=False),
    ]

    def on_mount(self) -> None:
        config = ConfigService.load()
        if config.should_show_onboarding():
            self.push_screen(SetupWelcomeScreen())
        else:
            self.push_screen(HomeScreen())

    def action_request_quit(self) -> None:
        """Quit the application. If on home or setup screens, exit immediately. Otherwise confirm."""
        if isinstance(
            self.screen,
            (
                HomeScreen,
                QuitModal,
                SetupWelcomeScreen,
                SetupProviderScreen,
                SetupStepPlaceholderScreen,
            ),
        ):
            self.exit()
            return

        def handle_quit(confirmed: bool | None) -> None:
            if confirmed:
                self.exit()

        self.push_screen(QuitModal(), handle_quit)
