"""Reusable keyboard-navigable menu widget with arrow navigation, wrapping, and windowed scrolling."""
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
    """A vertical list menu with arrow navigation, wrapping, and windowed scrolling for long lists."""

    BINDINGS = [
        Binding("up", "cursor_up", "Move Up", show=False),
        Binding("down", "cursor_down", "Move Down", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("home", "first_item", "First Item", show=False),
        Binding("end", "last_item", "Last Item", show=False),
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
        max_visible: int | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.items = list(items)
        self.max_visible = max_visible
        self.cursor_index = max(0, min(initial_index, len(self.items) - 1)) if self.items else 0
        self.viewport_start: int = 0
        self._ensure_cursor_visible()

    @property
    def selected_index(self) -> int:
        return self.cursor_index

    @selected_index.setter
    def selected_index(self, val: int) -> None:
        self.cursor_index = max(0, min(val, len(self.items) - 1)) if self.items else 0
        self._ensure_cursor_visible()
        self.refresh()

    @property
    def selected_item(self) -> MenuItem | None:
        if 0 <= self.cursor_index < len(self.items):
            return self.items[self.cursor_index]
        return None

    def _ensure_cursor_visible(self) -> None:
        """Keep the active cursor inside the visible window with a smooth 1-item cushion."""
        if not self.max_visible or len(self.items) <= self.max_visible:
            self.viewport_start = 0
            return

        max_start = max(0, len(self.items) - self.max_visible)

        # Scrolling down cushion: keep 1 item visible ahead if possible
        if self.cursor_index >= self.viewport_start + self.max_visible - 1:
            self.viewport_start = min(self.cursor_index - self.max_visible + 2, max_start)
        # Scrolling up cushion: keep 1 item visible behind if possible
        elif self.cursor_index <= self.viewport_start:
            self.viewport_start = max(0, self.cursor_index - 1)

        self.viewport_start = max(0, min(self.viewport_start, max_start))

    def set_items(self, items: Sequence[MenuItem], initial_index: int = 0) -> None:
        """Replace menu items, resetting cursor and scroll viewport cleanly."""
        self.items = list(items)
        self.viewport_start = 0
        self.cursor_index = max(0, min(initial_index, len(self.items) - 1)) if self.items else 0
        self._ensure_cursor_visible()
        self.refresh()

    def render(self) -> Text:
        """Render visible menu items with scroll indicators when windowed."""
        text = Text()
        total = len(self.items)
        if not total:
            return text

        self._ensure_cursor_visible()

        is_windowed = bool(self.max_visible and total > self.max_visible)
        limit = self.max_visible if is_windowed else total
        visible_items = self.items[self.viewport_start : self.viewport_start + limit]

        # Top indicator if windowed
        if is_windowed:
            if self.viewport_start > 0:
                text.append(f"    ▲ ({self.viewport_start} more above)\n", style="italic #9CA3AF")
            else:
                text.append(f"    • Top of list ({total} total)\n", style="italic #4B5563")

        # Dynamic label width based on visible items
        max_lbl = max(len(it.label) for it in visible_items) if visible_items else 12
        col_width = max(14, min(max_lbl + 2, 40))

        for idx, item in enumerate(visible_items):
            actual_idx = self.viewport_start + idx
            is_active = actual_idx == self.cursor_index
            if is_active:
                text.append("  ❯ ", style="bold #4ADE80 on #163D2B")
                text.append(f"{item.label:<{col_width}} ", style="bold #4ADE80 on #163D2B")
                text.append(f"{item.description}\n", style="#E5E7EB on #163D2B")
            else:
                text.append("    ", style="default")
                text.append(f"{item.label:<{col_width}} ", style="#E5E7EB")
                text.append(f"{item.description}\n", style="#9CA3AF")

        # Bottom indicator if windowed
        if is_windowed:
            remaining = total - (self.viewport_start + len(visible_items))
            if remaining > 0:
                text.append(f"    ▼ ({remaining} more below)\n", style="italic #9CA3AF")
            else:
                text.append(f"    • End of list ({total} total)\n", style="italic #4B5563")

        # Remove trailing newline for exact height
        if text.plain.endswith("\n"):
            text.right_crop(1)
        return text

    def action_cursor_up(self) -> None:
        if not self.items:
            return
        self.cursor_index = (self.cursor_index - 1) % len(self.items)
        self._ensure_cursor_visible()
        self.refresh()
        if self.selected_item:
            self.post_message(self.Highlighted(self.selected_item))

    def action_cursor_down(self) -> None:
        if not self.items:
            return
        self.cursor_index = (self.cursor_index + 1) % len(self.items)
        self._ensure_cursor_visible()
        self.refresh()
        if self.selected_item:
            self.post_message(self.Highlighted(self.selected_item))

    def action_page_up(self) -> None:
        if not self.items:
            return
        step = self.max_visible or 5
        self.cursor_index = max(0, self.cursor_index - step)
        self._ensure_cursor_visible()
        self.refresh()
        if self.selected_item:
            self.post_message(self.Highlighted(self.selected_item))

    def action_page_down(self) -> None:
        if not self.items:
            return
        step = self.max_visible or 5
        self.cursor_index = min(len(self.items) - 1, self.cursor_index + step)
        self._ensure_cursor_visible()
        self.refresh()
        if self.selected_item:
            self.post_message(self.Highlighted(self.selected_item))

    def action_first_item(self) -> None:
        if not self.items:
            return
        self.cursor_index = 0
        self._ensure_cursor_visible()
        self.refresh()
        if self.selected_item:
            self.post_message(self.Highlighted(self.selected_item))

    def action_last_item(self) -> None:
        if not self.items:
            return
        self.cursor_index = len(self.items) - 1
        self._ensure_cursor_visible()
        self.refresh()
        if self.selected_item:
            self.post_message(self.Highlighted(self.selected_item))

    def action_select(self) -> None:
        if self.selected_item:
            self.post_message(self.Selected(self.selected_item))

    def on_click(self, event) -> None:
        """Allow mouse clicking to highlight and select."""
        y = event.y
        is_windowed = bool(self.max_visible and len(self.items) > self.max_visible)
        offset = 1 if is_windowed else 0
        item_row = y - offset
        limit = self.max_visible if is_windowed else len(self.items)
        if 0 <= item_row < limit:
            target_index = self.viewport_start + item_row
            if 0 <= target_index < len(self.items):
                self.cursor_index = target_index
                self._ensure_cursor_visible()
                self.refresh()
                self.action_select()
