"""Enhanced Input widget with standard desktop editing keybindings.

Provides:
- Ctrl+C: Copy selected text, or full text if no selection
- Ctrl+V: Paste from system/app clipboard (replaces selection or inserts at cursor)
- Ctrl+X: Cut selected text, or full text if no selection
- Ctrl+Backspace: Delete word to the left (including in password inputs)
- Ctrl+Delete: Delete word to the right
- Delete / Backspace: Delete character right/left, or delete selection if active
- Ctrl+A: Select all text
- Typing printable characters replaces active selection
"""
from __future__ import annotations

import re
from textual.binding import Binding
from textual.widgets import Input


class EnhancedInput(Input):
    """An Input widget with desktop-grade editing keybindings and system clipboard integration."""

    BINDINGS = [
        # Word deletion bindings (overriding Textual's default ctrl+backspace -> delete_right_word)
        Binding("ctrl+backspace", "delete_left_word", "Delete word left", show=False),
        Binding("ctrl+delete", "delete_right_word", "Delete word right", show=False),
        # Select all binding with priority to override any parent home bindings
        Binding("ctrl+a,super+a", "select_all", "Select all", show=False, priority=True),
        # Clipboard bindings with system clipboard integration
        Binding("ctrl+c,super+c", "copy", "Copy", show=False),
        Binding("ctrl+x", "cut", "Cut", show=False),
        Binding("ctrl+v,super+v", "paste", "Paste", show=False),
    ]

    def action_select_all(self) -> None:
        """Select all of the text in the Input."""
        self.select_all()

    def action_copy(self) -> None:
        """Copy the current selection, or entire field if no selection exists."""
        if self.password:
            return
        selected_text = self.selected_text
        if selected_text:
            self.app.copy_to_clipboard(selected_text)
        elif self.value:
            self.app.copy_to_clipboard(self.value)

    def action_cut(self) -> None:
        """Cut the current selection (or entire field if no selection) to clipboard."""
        if self.password:
            return
        selected_text = self.selected_text
        if selected_text:
            self.app.copy_to_clipboard(selected_text)
            self.delete_selection()
        elif self.value:
            self.app.copy_to_clipboard(self.value)
            self.value = ""

    def action_paste(self) -> None:
        """Paste from system or app clipboard, replacing selection if one exists."""
        clip = self.app.clipboard
        if clip:
            start, end = self.selection
            self.replace(clip, start, end)

    def action_delete_left_word(self) -> None:
        """Delete one word to the left of the cursor, or delete selection if active."""
        if not self.selection.is_empty:
            self.delete_selection()
            return

        # Find word boundary backwards even in password fields
        try:
            *_, hit = re.finditer(self._WORD_START, self.value[: self.cursor_position])
        except ValueError:
            target = 0
        else:
            target = hit.start()

        self.delete(target, self.cursor_position)

    def action_delete_right_word(self) -> None:
        """Delete one word to the right of the cursor, or delete selection if active."""
        if not self.selection.is_empty:
            self.delete_selection()
            return

        after = self.value[self.cursor_position :]
        hit = re.search(self._WORD_START, after)
        if hit is None:
            self.action_delete_right_all()
        else:
            start = self.cursor_position
            end = start + hit.end() - 1
            self.delete(start, end)
