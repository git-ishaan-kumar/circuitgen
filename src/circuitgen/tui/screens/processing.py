"""Compact progress overlay for offline file and schematic work."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import LoadingIndicator, Static


class ProcessingScreen(ModalScreen[None]):
    """Show a small activity indicator while an offline operation runs."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="processing-card"):
            yield Static(self.message, id="processing-message", markup=False)
            yield LoadingIndicator(id="processing-indicator")


async def show_processing(screen: Screen, message: str) -> ProcessingScreen:
    progress = ProcessingScreen(message)
    await screen.app.push_screen(progress)
    return progress


def close_processing(screen: Screen, progress: ProcessingScreen) -> None:
    if screen.app.is_running and screen.app.screen is progress:
        screen.app.pop_screen()
