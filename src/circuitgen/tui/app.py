"""CircuitGen Textual Application Shell and Brand Palette."""
from __future__ import annotations

from typing import Any

from textual.app import App
from textual.binding import Binding

from circuitgen import __version__
from .screens.confirm_dialog import QuitModal
from .screens.home import HomeScreen
from .screens.render import RenderModeScreen, RenderSuccessScreen, ViewNetlistScreen
from .screens.validate import ValidateDetailsScreen, ValidateModeScreen, ValidateResultScreen
from .screens.setup_key import SetupKeyScreen
from .screens.setup_model import (
    SetupModelBrowseScreen,
    SetupModelManualScreen,
    SetupModelScreen,
)
from .screens.setup_complete import SetupCompleteScreen
from .screens.setup_provider import SetupProviderScreen
from .screens.setup_step_placeholder import SetupStepPlaceholderScreen
from .screens.setup_welcome import SetupWelcomeScreen
from .services.config import ConfigService
from .clipboard import get_system_clipboard, set_system_clipboard


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

    @property
    def clipboard(self) -> str:
        """The value of the host system clipboard, falling back to local clipboard."""
        sys_clip = get_system_clipboard()
        if sys_clip:
            return sys_clip
        return self._clipboard

    def copy_to_clipboard(self, text: str) -> None:
        """Copy text to host system clipboard, app clipboard, and OSC 52 terminal clipboard."""
        set_system_clipboard(text)
        super().copy_to_clipboard(text)

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
                RenderModeScreen,
                RenderSuccessScreen,
                ViewNetlistScreen,
                ValidateModeScreen,
                ValidateResultScreen,
                ValidateDetailsScreen,
                SetupWelcomeScreen,
                SetupProviderScreen,
                SetupKeyScreen,
                SetupModelScreen,
                SetupModelBrowseScreen,
                SetupModelManualScreen,
                SetupCompleteScreen,
                SetupStepPlaceholderScreen,
            ),
        ):
            self.exit()
            return

        def handle_quit(confirmed: bool | None) -> None:
            if confirmed:
                self.exit()

        self.push_screen(QuitModal(), handle_quit)
