"""Reusable multiline JSON and prompt editor widget."""
from __future__ import annotations

import re
from typing import Any
from textual import events
from textual.binding import Binding
from textual.widgets import TextArea

from ..services.file_io import FileIOService


class JsonEditor(TextArea):
    """Multiline editor widget customized for netlists and descriptions.

    - Tab key moves focus to the next field (tab_behavior='focus').
    - Enter key inserts a newline without submitting.
    - Ctrl+A selects all text in the editor.
    - Preserves drafts and provides built-in JSON netlist validation.
    """

    BINDINGS = [
        Binding("ctrl+a,super+a", "select_all", "Select all", show=False, priority=True),
        Binding("ctrl+c,super+c", "copy", "Copy", show=False),
        Binding("ctrl+x,super+x", "cut", "Cut", show=False),
        Binding("ctrl+v,super+v", "paste", "Paste", show=False),
    ]

    _LIST_ITEM = re.compile(r"^([ \t]*)(?:(\d+)([.)])|([-*+•]))([ \t]+)(.*\S.*)$")
    _EMPTY_LIST_ITEM = re.compile(r"^[ \t]*(?:\d+[.)]|[-*+•])[ \t]*$")

    def __init__(
        self,
        text: str = "",
        *,
        language: str | None = "json",
        auto_lists: bool = False,
        theme: str = "css",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(
            text=text,
            language=language,
            theme=theme,
            tab_behavior="focus",
            id=id,
            classes=classes,
        )
        self.auto_lists = auto_lists

    def _empty_list_item(self) -> tuple[int, str] | None:
        if not self.auto_lists or not self.selection.is_empty:
            return None
        row, column = self.cursor_location
        line = self.document.get_line(row)
        if column == len(line) and self._EMPTY_LIST_ITEM.fullmatch(line):
            return row, line
        return None

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter" and not self.read_only:
            empty_item = self._empty_list_item()
            if empty_item is not None:
                row, line = empty_item
                self._replace_via_keyboard("", (row, 0), (row, len(line)))
                event.stop()
                event.prevent_default()
                return
            if self.auto_lists and self.selection.is_empty:
                row, column = self.cursor_location
                line = self.document.get_line(row)
                if column == len(line):
                    match = self._LIST_ITEM.fullmatch(line)
                    if match:
                        indent, number, punctuation, bullet, spacing, _ = match.groups()
                        marker = f"{int(number) + 1}{punctuation}" if number else bullet
                        self._replace_via_keyboard(
                            f"\n{indent}{marker}{spacing}", self.cursor_location, self.cursor_location
                        )
                        event.stop()
                        event.prevent_default()
                        return
        await super()._on_key(event)

    def action_delete_left(self) -> None:
        empty_item = self._empty_list_item()
        if empty_item is not None and not self.read_only:
            row, line = empty_item
            self._replace_via_keyboard("", (row, 0), (row, len(line)))
            return
        super().action_delete_left()

    def action_select_all(self) -> None:
        """Select all text in the editor."""
        self.select_all()

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 3:
            await super()._on_mouse_down(event)
            return
        event.stop()
        if self.disabled:
            return
        if event.get_content_offset(self) is not None:
            row, column = self.get_target_document_location(event)
            line = self.document.get_line(row)
            if column < len(line):
                self.app.copy_to_clipboard(self.selected_text or line)
                return
        self.action_paste()

    def validate_netlist(self) -> tuple[dict[str, Any] | None, str | None, tuple[int, int] | None]:
        """Validate the editor contents as a valid JSON netlist.

        Returns:
            (netlist_dict, error_message, (line, col) or None)
        """
        return FileIOService.parse_json_netlist(self.text)
