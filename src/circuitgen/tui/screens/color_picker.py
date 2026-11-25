"""Preset color swatches with direct hex entry."""
import re

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from ..services.config import ConfigService
from ..widgets import EnhancedInput, MenuItem, SelectableMenu
from .settings import SettingsPage


HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
# Sampled from the center of each swatch in the iPhone Markup reference.
PALETTE = (
    ("#FDFDFD", "#E9E9E9", "#D5D4D5", "#C2BFBE", "#ADACAC", "#989898", "#858484", "#6F6E6F", "#5B5A5A", "#464646", "#303030", "#000000"),
    ("#003649", "#001C56", "#10043A", "#2D073C", "#390A17", "#5B0600", "#591B00", "#573200", "#553C00", "#656000", "#4E5403", "#253D0E"),
    ("#004C64", "#012F7B", "#1C0B51", "#450E59", "#540F28", "#821000", "#7A2800", "#794900", "#785701", "#8C8503", "#6E7509", "#375619"),
    ("#006D8E", "#0041A8", "#2B0876", "#5F187A", "#78193C", "#B41900", "#AC3D00", "#A86700", "#A57A00", "#C3BB00", "#9AA40D", "#4D7826"),
    ("#008BB4", "#0055D5", "#361993", "#79209D", "#98244E", "#E12300", "#D94F00", "#D28200", "#D09C00", "#F4EB00", "#C2D016", "#659C33"),
    ("#00A0D7", "#0060FC", "#4C21B1", "#972EBD", "#B82C5C", "#FE3F14", "#FE6900", "#FEAA00", "#FBC600", "#FDFA40", "#D8EB36", "#76BA40"),
    ("#00C6FB", "#3986FC", "#5D2FEA", "#BD37F2", "#E53A79", "#FC624F", "#FD8648", "#FDB33F", "#FDCA3E", "#FEF66A", "#E4EE64", "#96D160"),
    ("#53D5FB", "#73A6FE", "#854EFC", "#D256FD", "#ED719E", "#FE8C82", "#FDA57D", "#FDC676", "#FDD877", "#FEF894", "#E9F18E", "#B0DC8A"),
    ("#93E2FB", "#A6C5FE", "#B08BFD", "#E093FC", "#F3A3C0", "#FEB4AE", "#FEC4AA", "#FDD8A8", "#FCE2A7", "#FEFAB8", "#F0F5B7", "#CDE7B5"),
    ("#CAEFFE", "#D1E1FD", "#D7C9FD", "#EDC8FB", "#F8D3DD", "#FBD9D8", "#FEE1D5", "#FDEAD4", "#FCEDD4", "#FCFADC", "#F5F9DA", "#DDEDD3"),
)
SWATCH_WIDTH = 2


class ColorGrid(Static, can_focus=True):
    BINDINGS = [
        Binding("left", "move(-1, 0)", show=False),
        Binding("right", "move(1, 0)", show=False),
        Binding("up", "move(0, -1)", show=False),
        Binding("down", "move(0, 1)", show=False),
    ]

    def __init__(self) -> None:
        super().__init__(id="color-grid")
        self.column = self.row = 0
        self.color: str | None = None

    def update_hex(self, color: str) -> None:
        self.color = color.upper()
        for row, colors in enumerate(PALETTE):
            if self.color in colors:
                self.column = colors.index(self.color)
                self.row = row
                break
        self.refresh()

    def render(self) -> Text:
        text = Text()
        for row, colors in enumerate(PALETTE):
            for column, color in enumerate(colors):
                selected = (column, row) == (self.column, self.row) and self.color == color
                ink = "black" if int(color[3:5], 16) >= 128 else "white"
                text.append("\u00d7 " if selected else "  ", style=f"bold {ink} on {color}")
            if row < len(PALETTE) - 1:
                text.append("\n")
        return text

    def _choose_cell(self, column: int, row: int) -> None:
        self.row = max(0, min(len(PALETTE) - 1, row))
        self.column = max(0, min(len(PALETTE[self.row]) - 1, column))
        self.color = PALETTE[self.row][self.column]
        self.screen.query_one("#hex-color", EnhancedInput).value = self.color
        self.refresh()

    def action_move(self, dx: int, dy: int) -> None:
        self._choose_cell(self.column + dx, self.row + dy)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 1:
            self._choose_cell(event.x // SWATCH_WIDTH, event.y)
            self.focus()


class ColorPicker(SettingsPage):
    def __init__(self, label: str, color: str | None, *, background: bool = False) -> None:
        super().__init__()
        self.title_text = f"Settings / {label}"
        self.color = {"white": "#FFFFFF", "black": "#000000"}.get(color, color) or ""
        self.background = background

    def content(self) -> ComposeResult:
        yield Static("Hex color", classes="input-field-label")
        yield EnhancedInput(value=self.color if HEX_COLOR.fullmatch(self.color) else "",
                            placeholder="#RRGGBB", id="hex-color")
        if ConfigService.load().terminal_colors != "none":
            yield Static("Preset colors", classes="input-field-label")
            yield ColorGrid()
            yield Static("Click a swatch or Tab to the grid and use arrows.", classes="keys-reminder")
        defaults = (
            [MenuItem("transparent", "Transparent", ""), MenuItem("white", "White", ""), MenuItem("black", "Black", "")]
            if self.background else [MenuItem("default", "Use default color", "")]
        )
        yield SelectableMenu([MenuItem("apply", "Apply hex color", ""), *defaults, MenuItem("cancel", "Cancel", "")])

    def on_input_changed(self, event: EnhancedInput.Changed) -> None:
        value = event.value.strip()
        if HEX_COLOR.fullmatch(value):
            for grid in self.query(ColorGrid):
                if grid.color != value.upper():
                    grid.update_hex(value)

    def on_input_submitted(self) -> None:
        self._apply()

    def _apply(self) -> None:
        value = self.query_one("#hex-color", EnhancedInput).value.strip()
        if HEX_COLOR.fullmatch(value):
            self.dismiss(value.upper())
        else:
            self.status("Enter a six-digit hex color, such as #34A853.")

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        choice = event.item.key
        if choice == "apply":
            self._apply()
        elif choice == "cancel":
            self.action_back()
        else:
            self.dismiss("" if choice == "default" else choice)

    def action_back(self) -> None:
        self.dismiss(None)
