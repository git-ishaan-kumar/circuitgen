"""Placeholder subpage screen for future phases."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class PlaceholderScreen(Screen[None]):
    """Generic placeholder screen indicating feature coming in a future phase."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=True, priority=True),
    ]

    def __init__(self, page_name: str, description: str = "") -> None:
        super().__init__()
        self.page_name = page_name
        self.description = description

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="placeholder-container"):
            with Vertical(id="placeholder-card"):
                yield Static(f"CircuitGen / {self.page_name}", classes="breadcrumb")
                yield Static(f"{self.page_name}", classes="prompt-text")
                if self.description:
                    yield Static(self.description, classes="tagline")
                yield Static("This screen will be implemented in a subsequent phase.", classes="modal-warning")
                yield Static("Press Esc to return Home.", classes="status-left")
        yield Footer()

    def action_back(self) -> None:
        self.app.pop_screen()
