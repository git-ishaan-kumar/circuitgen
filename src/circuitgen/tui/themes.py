"""Palette tokens shared by Textual styles and Rich menu rows."""
from dataclasses import replace

from textual.theme import BUILTIN_THEMES, Theme


TOKENS = ("background", "surface", "selection", "accent", "text", "muted", "border", "warning", "error", "info")
PALETTES = {
    "terminal": ("ansi_black", "ansi_black", "ansi_blue", "ansi_bright_cyan",
                 "ansi_bright_white", "ansi_white", "ansi_bright_black", "ansi_bright_yellow",
                 "ansi_bright_red", "ansi_cyan"),
    "pcb-green": ("#0D1117", "#161B22", "#163D2B", "#4ADE80", "#E5E7EB", "#9CA3AF",
                  "#30363D", "#FBBF24", "#F87171", "#60A5FA"),
    "midnight-blue": ("#0B1224", "#141E35", "#1C3456", "#8CC8FF", "#E9F1FF", "#ACBBD4",
                      "#3B5275", "#FFD083", "#FF9BAA", "#8DD9E8"),
    "light": ("#F6F8FC", "#FFFFFF", "#DBEAFE", "#164B8B", "#182538", "#4B5B70",
              "#828FA2", "#805500", "#9D2531", "#205EA0"),
    "monochrome": ("#111111", "#212121", "#404040", "#FFFFFF", "#F0F0F0", "#C1C1C1",
                   "#777777", "#DBDBDB", "#FFFFFF", "#CCCCCC"),
}


def palette(name: str = "pcb-green") -> dict[str, str]:
    return dict(zip(TOKENS, PALETTES.get(name, PALETTES["pcb-green"])))


def make_theme(name: str) -> Theme:
    colors = palette(name)
    variables = {f"cg-{key}": value for key, value in colors.items()}
    if name == "terminal":
        terminal = BUILTIN_THEMES["ansi-dark"]
        return replace(terminal, name=name, variables={**terminal.variables, **variables})
    return Theme(
        name=name, primary=colors["accent"], accent=colors["accent"],
        foreground=colors["text"], background=colors["background"],
        surface=colors["surface"], panel=colors["surface"],
        warning=colors["warning"], error=colors["error"], success=colors["accent"],
        dark=name != "light", variables=variables,
    )
