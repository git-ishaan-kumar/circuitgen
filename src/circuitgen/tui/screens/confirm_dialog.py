"""Quit confirmation modal dialog (§10)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from ..widgets.selectable_menu import MenuItem, SelectableMenu


class QuitModal(ModalScreen[bool]):
    """Modal dialog prompting confirmation before exiting CircuitGen."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True, priority=True),
        Binding("ctrl+q", "confirm_quit", "Quit", show=False, priority=True),
        Binding("q", "confirm_quit", "Quit", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="quit-dialog"):
            yield Static("Quit CircuitGen?", classes="modal-title")
            yield Static("Unsaved input will be discarded.", classes="modal-warning")
            yield SelectableMenu(
                items=[
                    MenuItem("keep", "Keep working", ""),
                    MenuItem("quit", "Quit CircuitGen", ""),
                ],
                initial_index=0,
                id="quit-menu",
            )
            yield Static("↑↓ Navigate  ·  Enter Select  ·  Esc Cancel", classes="status-left")

    def on_mount(self) -> None:
        self.query_one(SelectableMenu).focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        if message.item.key == "quit":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm_quit(self) -> None:
        self.dismiss(True)
