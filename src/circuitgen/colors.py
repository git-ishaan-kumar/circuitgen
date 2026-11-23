"""Consistent, configurable schematic ink color."""
import re

_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
_HEX = r"#[0-9a-fA-F]{6}"
# Only paint declarations are ink. Rewriting every hex-looking substring also
# rewrote component values and net names that happened to look like a colour.
_STYLE_INK = re.compile(r"((?:stroke|fill):\s*)(" + _HEX + r")")
_ATTRIBUTE_INK = re.compile(r'((?:stroke|fill)=")(' + _HEX + r')(")')
_WHITE = "#ffffff"


def normalize_color(color: str = "#000000") -> str:
    """Return a validated six-digit hex colour, or raise ValueError."""
    if not isinstance(color, str) or not _COLOR.fullmatch(color):
        raise ValueError("color must be a six-digit hex string, e.g. '#000000'")
    return color


def _style_ink(match: "re.Match[str]", ink: str) -> str:
    value = match.group(2)
    return match.group(1) + (value if value.lower() == _WHITE else ink)


def _attribute_ink(match: "re.Match[str]", ink: str) -> str:
    value = match.group(2)
    return match.group(1) + (value if value.lower() == _WHITE else ink) + match.group(3)


def apply_ink_color(svg: str, color: str = "#000000") -> str:
    """Recolor schematic ink while preserving white fills and label text."""
    ink = normalize_color(color)
    svg = _STYLE_INK.sub(lambda match: _style_ink(match, ink), svg)
    return _ATTRIBUTE_INK.sub(lambda match: _attribute_ink(match, ink), svg)
