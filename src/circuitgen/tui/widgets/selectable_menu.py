"""Reusable keyboard-navigable menu widget with arrow navigation and wrapping."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget


@dataclass(frozen=True)
class MenuItem:
    key: str
    label: str
    description: str


class SelectableMenu(Widget, can_focus=True):
    """A vertical list menu where arrow keys move selection and wrap at boundaries."""

    BINDINGS = [
        Binding("up", "cursor_up", "Move Up", show=False),
        Binding("down", "cursor_down", "Move Down", show=False),
        Binding("enter", "select", "Select", show=False),
    ]

    class Selected(Message):
        """Posted when a menu item is activated."""

        def __init__(self, item: MenuItem) -> None:
            super().__init__()
            self.item = item

    class Highlighted(Message):
        """Posted when a menu item is highlighted."""

        def __init__(self, item: MenuItem) -> None:
            super().__init__()
            self.item = item

    def __init__(
        self,
        items: Sequence[MenuItem],
        initial_index: int = 0,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.items = list(items)
        self.cursor_index = max(0, min(initial_index, len(self.items) - 1)) if self.items else 0

    @property
    def selected_item(self) -> MenuItem | None:
        if 0 <= self.cursor_index < len(self.items):
            return self.items[self.cursor_index]
        return None

    def render(self) -> Text:
        """Render all menu items with chevron and highlight on the current cursor."""
        text = Text()
        total = len(self.items)
        for i, item in enumerate(self.items):
            is_active = i == self.cursor_index
            if is_active:
                text.append("  ❯ ", style="bold #4ADE80 on #163D2B")
                text.append(f"{item.label:<12} ", style="bold #4ADE80 on #163D2B")
                text.append(f"{item.description}\n", style="#E5E7EB on #163D2B")
            else:
                text.append("    ", style="default")
                text.append(f"{item.label:<12} ", style="#E5E7EB")
                text.append(f"{item.description}\n", style="#9CA3AF")
        # Remove trailing newline for exact height
        if text.plain.endswith("\n"):
            text.right_crop(1)
        return text

    def action_cursor_up(self) -> None:
        if not self.items:
            return
        self.cursor_index = (self.cursor_index - 1) % len(self.items)
        self.refresh()
        if self.selected_item:
            self.post_message(self.Highlighted(self.selected_item))

    def action_cursor_down(self) -> None:
        if not self.items:
            return
        self.cursor_index = (self.cursor_index + 1) % len(self.items)
        self.refresh()
        if self.selected_item:
            self.post_message(self.Highlighted(self.selected_item))

    def action_select(self) -> None:
        if self.selected_item:
            self.post_message(self.Selected(self.selected_item))

    def on_click(self, event) -> None:
        """Allow mouse clicking to highlight and select."""
        y = event.y
        if 0 <= y < len(self.items):
            self.cursor_index = y
            self.refresh()
            self.action_select()
