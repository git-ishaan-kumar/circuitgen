"""Confirmation and guard modal dialogs (§6, §10)."""
from __future__ import annotations

from pathlib import Path
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
        with Vertical(id="quit-dialog", classes="modal-dialog"):
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


class OverwriteModal(ModalScreen[bool]):
    """Modal dialog prompting confirmation before overwriting an existing file."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True, priority=True),
        Binding("ctrl+q", "quit_app", "Quit", show=False, priority=True),
    ]

    def __init__(self, target_path: Path | str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.target_path = Path(target_path)

    def compose(self) -> ComposeResult:
        with Vertical(id="overwrite-dialog", classes="modal-dialog"):
            yield Static("! File Already Exists", classes="modal-title")
            yield Static(
                f"A file already exists at:\n{self.target_path}\n\nOverwriting will replace its contents.",
                classes="modal-warning",
            )
            yield SelectableMenu(
                items=[
                    MenuItem("cancel", "Cancel (Do not overwrite)", "Keep existing file unchanged"),
                    MenuItem("overwrite", "Overwrite existing file", "Replace file with new output"),
                ],
                initial_index=0,
                id="overwrite-menu",
            )
            yield Static("↑↓ Navigate  ·  Enter Select  ·  Esc Cancel", classes="status-left")

    def on_mount(self) -> None:
        self.query_one(SelectableMenu).focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        if message.item.key == "overwrite":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_quit_app(self) -> None:
        self.app.exit()


class CreateDirectoryModal(ModalScreen[bool]):
    """Modal dialog prompting confirmation before creating a missing directory."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True, priority=True),
        Binding("ctrl+q", "quit_app", "Quit", show=False, priority=True),
    ]

    def __init__(self, target_dir: Path | str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.target_dir = Path(target_dir)

    def compose(self) -> ComposeResult:
        with Vertical(id="create-dir-dialog", classes="modal-dialog"):
            yield Static("Create Output Directory?", classes="modal-title")
            yield Static(
                f"The target folder does not exist:\n{self.target_dir}\n\nCreate this directory now?",
                classes="modal-warning",
            )
            yield SelectableMenu(
                items=[
                    MenuItem("create", "Create directory", "Create folder and continue save"),
                    MenuItem("cancel", "Cancel", "Return to editing destination path"),
                ],
                initial_index=0,
                id="create-dir-menu",
            )
            yield Static("↑↓ Navigate  ·  Enter Select  ·  Esc Cancel", classes="status-left")

    def on_mount(self) -> None:
        self.query_one(SelectableMenu).focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        if message.item.key == "create":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_quit_app(self) -> None:
        self.app.exit()
