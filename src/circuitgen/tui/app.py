"""CircuitGen Textual Application Shell and Brand Palette."""
from __future__ import annotations

import os
from typing import Any

from rich.traceback import Traceback
from textual import events
from textual.app import App
from textual.binding import Binding
from textual.filter import NoColor
from textual.geometry import Offset
from textual.selection import Selection
from textual.widgets import Static

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
from .services.config import AppConfig, ConfigService
from .clipboard import get_system_clipboard, set_system_clipboard
from .themes import PALETTES, make_theme, palette
from .widgets import EnhancedInput, JsonEditor


class CircuitGenApp(App[None]):
    """Main Textual Application for CircuitGen."""

    TITLE = "CircuitGen"
    SUB_TITLE = f"v{__version__}"
    CSS_PATH = "theme.tcss"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True, priority=True),
        Binding("q", "request_quit", "Quit", show=False),
        Binding("question_mark", "help", "Help", show=False),
    ]

    def __init__(self, start_screen: str = "home", force_no_color: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.start_screen = start_screen
        self.force_no_color = force_no_color
        self._reduced_motion_default = self.animation_level
        self._plain_colors = False
        self._no_color_filter = NoColor()
        for name in PALETTES:
            self.register_theme(make_theme(name))

    def get_theme_variable_defaults(self) -> dict[str, str]:
        return {f"cg-{name}": value for name, value in palette().items()}

    def _fatal_error(self) -> None:
        # Worker frames can contain API keys.
        self.bell()
        self.panic(Traceback(show_locals=False, width=None))

    def apply_preferences(self, config: AppConfig) -> None:
        self.animation_level = "none" if config.reduced_motion else self._reduced_motion_default
        self._plain_colors = (self.force_no_color or config.terminal_colors == "none" or
                              (config.terminal_colors == "auto" and "NO_COLOR" in os.environ))
        self.theme = config.interface_theme if config.interface_theme in PALETTES else "pcb-green"
        self.refresh()

    def get_line_filters(self):
        filters = super().get_line_filters()
        return [*filters, self._no_color_filter] if self._plain_colors else filters

    def return_from_reopened_setup(self) -> bool:
        for index, screen in enumerate(self.screen_stack):
            if isinstance(screen, SetupWelcomeScreen) and screen.restart:
                for _ in range(len(self.screen_stack) - index):
                    self.pop_screen()
                return True
        return False

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

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 3:
            return
        widget, offset = self.screen.get_widget_and_offset_at(event.screen_x, event.screen_y)
        if isinstance(widget, (EnhancedInput, JsonEditor)):
            return
        if offset is not None:
            if isinstance(widget, Static):
                selection = self.screen.selections.get(widget) or Selection(
                    Offset(0, offset.y), Offset(0, offset.y + 1),
                )
                result = widget.get_selection(selection)
                if result and result[0].strip():
                    self.copy_to_clipboard(result[0].rstrip("\n"))
            return
        if isinstance(self.focused, (EnhancedInput, JsonEditor)) and not self.focused.disabled:
            self.focused.action_paste()

    def on_mount(self) -> None:
        config = ConfigService.load()
        self.apply_preferences(config)
        if self.start_screen == "settings":
            from .screens.settings import SettingsScreen
            self.push_screen(HomeScreen())
            self.push_screen(SettingsScreen())
            return
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

    def action_help(self) -> None:
        from .screens.help import HelpScreen

        if isinstance(self.focused, (EnhancedInput, JsonEditor)) or isinstance(self.screen, HelpScreen):
            return
        topic = ""
        statuses = self.screen.query(".status-message")
        text = " ".join(str(item.content) for item in statuses.results(Static)).lower()
        if any(word in text for word in ("model", "quota", "rate limit", "billing")):
            topic = "trouble:models"
        elif any(word in text for word in ("key", "provider", "authentication")):
            topic = "trouble:keys"
        elif any(word in text for word in ("unsupported", "unknown component")):
            topic = "trouble:parts"
        elif any(word in text for word in ("netlist", "json", "pin", "wiring")):
            topic = "trouble:json"
        elif any(word in text for word in ("file", "folder", "directory", "output", "render")):
            topic = "trouble:files"
        self.push_screen(HelpScreen(topic))
