"""Reusable multiline JSON and prompt editor widget."""
from __future__ import annotations

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

    def __init__(
        self,
        text: str = "",
        *,
        language: str | None = "json",
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
