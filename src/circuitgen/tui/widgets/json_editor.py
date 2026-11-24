"""Reusable multiline JSON and prompt editor widget."""
from __future__ import annotations

from typing import Any
from textual.widgets import TextArea

from ..services.file_io import FileIOService


class JsonEditor(TextArea):
    """Multiline editor widget customized for netlists and descriptions.

    - Tab key moves focus to the next field (tab_behavior='focus').
    - Enter key inserts a newline without submitting.
    - Preserves drafts and provides built-in JSON netlist validation.
    """

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

    def validate_netlist(self) -> tuple[dict[str, Any] | None, str | None, tuple[int, int] | None]:
        """Validate the editor contents as a valid JSON netlist.

        Returns:
            (netlist_dict, error_message, (line, col) or None)
        """
        return FileIOService.parse_json_netlist(self.text)
