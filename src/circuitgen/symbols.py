"""Reusable schematic symbols and pin geometry; no routing or third-party packages."""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Sequence
from unicodedata import east_asian_width
from xml.sax.saxutils import escape as xml_escape

GRID_PX = 24
PIN_NAME = re.compile(r"[A-Za-z0-9_+\-]{1,24}\Z")


def label_width(text: str, font_size: int, average: float) -> float:
    return sum(font_size if char in 'MWmw@%' or east_asian_width(char) in ('F', 'W')
               else average for char in text)


@dataclasses.dataclass(frozen=True)
class PinSpec:
    name: str
    x: float
    y: float
    number: str = ""


@dataclasses.dataclass(frozen=True)
class SymbolSpec:
    kind: str
    shape: str
    pins: tuple[PinSpec, ...]
    half_width: float = 1.5
    half_height: float = 1.5

    @property
    def pin_names(self) -> tuple[str, ...]:
        return tuple(pin.name for pin in self.pins)


def _two(kind: str, shape: str) -> SymbolSpec:
    return SymbolSpec(kind, shape, (PinSpec("a", -2, 0), PinSpec("b", 2, 0)), 1.3, 0.9)


def _source(kind: str, shape: str) -> SymbolSpec:
    return SymbolSpec(kind, shape, (PinSpec("p", 0, -2), PinSpec("n", 0, 2)), 1.2, 1.2)


def _pin_rows(names: tuple[tuple[str, str], ...], side: str) -> tuple[PinSpec, ...]:
    result = []
    count = len(names)
    for idx, (name, number) in enumerate(names):
        y = (idx - (count - 1) / 2) * 1.0
        result.append(PinSpec(name, -3.2 if side == "left" else 3.2, y, number))
    return tuple(result)


def _ic(kind: str, left: tuple[tuple[str, str], ...], right: tuple[tuple[str, str], ...],
        top: tuple[tuple[str, str], ...] = (), bottom: tuple[tuple[str, str], ...] = ()) -> SymbolSpec:
    rows = max(len(left), len(right), 2)
    height = max(2.0, rows / 2 + 0.35)
    pins = list(_pin_rows(left, "left") + _pin_rows(right, "right"))
    for i, (name, number) in enumerate(top):
        pins.append(PinSpec(name, (i - (len(top) - 1) / 2), -height - 1, number))
    for i, (name, number) in enumerate(bottom):
        pins.append(PinSpec(name, (i - (len(bottom) - 1) / 2), height + 1, number))
    return SymbolSpec(kind, "ic", tuple(pins), 2.2, height)


BUILTIN_SYMBOLS: dict[str, SymbolSpec] = {
    **{kind: _two(kind, kind) for kind in (
        "resistor", "capacitor", "inductor", "diode", "led", "switch", "lamp", "fuse"
    )},
    **{kind: _source(kind, kind) for kind in ("battery", "dc_source", "ac_source", "current_source")},
    "ground": SymbolSpec("ground", "ground", (PinSpec("gnd", 0, -2),), 0.7, 0.65),
    "npn": SymbolSpec("npn", "npn", (PinSpec("C", 1, -2), PinSpec("B", -2, 0), PinSpec("E", 1, 2))),
    "pnp": SymbolSpec("pnp", "pnp", (PinSpec("C", 1, -2), PinSpec("B", -2, 0), PinSpec("E", 1, 2))),
    "nmos": SymbolSpec("nmos", "nmos", (PinSpec("G", -2, 0), PinSpec("D", 1, -2), PinSpec("S", 1, 2))),
    "pmos": SymbolSpec("pmos", "pmos", (PinSpec("G", -2, 0), PinSpec("D", 1, -2), PinSpec("S", 1, 2))),
    "opamp": SymbolSpec("opamp", "opamp", (
        PinSpec("IN+", -2, 1), PinSpec("IN-", -2, -1), PinSpec("OUT", 3, 0),
        PinSpec("V+", 0, -2), PinSpec("V-", 0, 2)
    ), 1.5, 1.6),
    "ne555": _ic("ne555", (
        ("TRIG", "2"), ("RESET", "4"), ("CTRL", "5"), ("THRES", "6"),
    ), (("OUT", "3"), ("DISCH", "7")), (("VCC", "8"),), (("GND", "1"),)),
    "arduino_uno": _ic("arduino_uno",
        tuple((f"D{i}", "") for i in range(14)),
        tuple((f"A{i}", "") for i in range(6)) +
        (("3V3", ""), ("5V", ""), ("VIN", ""), ("GND", ""), ("RESET", ""))),
}


def get_symbol(kind: str, pins: Sequence[str] | None = None) -> SymbolSpec:
    """Get a symbol definition, generating a rectangular symbol for custom parts.

    Known part pin lists cannot be redefined: mismatched pins are unsafe.
    Unknown part pin lists describe logical names, not verified pinouts.
    """
    if not isinstance(kind, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", kind):
        raise ValueError("Invalid component type")
    if pins is None:
        if kind not in BUILTIN_SYMBOLS:
            raise ValueError(f"Unknown component type {kind!r}; provide its pins")
        return BUILTIN_SYMBOLS[kind]
    if not isinstance(pins, (tuple, list)) or not 1 <= len(pins) <= 128:
        raise ValueError("Expected 1–128 pin names")
    if any(not isinstance(pin, str) or not PIN_NAME.fullmatch(pin) for pin in pins):
        raise ValueError("Invalid pin name")
    if len(set(pins)) != len(pins):
        raise ValueError("Duplicate pin name")
    if kind == "ground" and len(pins) == 1:
        spec = BUILTIN_SYMBOLS[kind]
        pin = dataclasses.replace(spec.pins[0], name=pins[0])
        return dataclasses.replace(spec, pins=(pin,))
    if kind in BUILTIN_SYMBOLS and kind != "ground":
        spec = BUILTIN_SYMBOLS[kind]
        if set(pins) != set(spec.pin_names):
            raise ValueError(f"Pin list for {kind} must match its registered symbol")
        return spec
    left = tuple((pin, "") for pin in pins[:(len(pins) + 1) // 2])
    right = tuple((pin, "") for pin in pins[(len(pins) + 1) // 2:])
    return _ic(kind, left, right)


def _check_orientation(rotation: int, mirror: bool) -> None:
    if type(rotation) is not int or rotation not in (0, 90, 180, 270):
        raise ValueError("Rotation must be 0, 90, 180, or 270 degrees")
    if type(mirror) is not bool:
        raise ValueError("mirror must be true or false")


def transform_point(x: float, y: float, rotation: int = 0, mirror: bool = False) -> tuple[float, float]:
    """Mirror local X first, then rotate clockwise in screen coordinates."""
    _check_orientation(rotation, mirror)
    if mirror:
        x = -x
    return {
        0: (x, y),
        90: (-y, x),
        180: (-x, -y),
        270: (y, -x),
    }[rotation]


def pin_positions(symbol: SymbolSpec, x: float = 0, y: float = 0,
                  rotation: int = 0, mirror: bool = False) -> dict[str, tuple[float, float]]:
    """Return exact grid-unit endpoint positions for the future wire router."""
    _check_orientation(rotation, mirror)
    if not all(math.isfinite(v) for v in (x, y)):
        raise ValueError("Position must be finite")
    return {pin.name: tuple(a + b for a, b in zip((x, y),
            transform_point(pin.x, pin.y, rotation, mirror))) for pin in symbol.pins}


def _el(tag: str, **attrs: object) -> str:
    return '<' + tag + ''.join(f' {key.replace("_", "-")}="{xml_escape(str(value), {chr(34): "&quot;"})}"'
                             for key, value in attrs.items()) + '/>'


def _local_art(symbol: SymbolSpec, visible_pins: frozenset[str] | None = None) -> list[str]:
    """Draw shapes in pixel-space, centered on (0, 0)."""
    k, s = symbol.shape, GRID_PX
    out: list[str] = []

    def line(x1: float, y1: float, x2: float, y2: float) -> None:
        out.append(_el("line", x1=x1*s, y1=y1*s, x2=x2*s, y2=y2*s, **{"class": "symbol"}))

    if k in ("ic",):
        w, h = symbol.half_width, symbol.half_height
        out.append(_el("rect", x=-w*s, y=-h*s, width=2*w*s, height=2*h*s,
                       rx=4, **{"class": "symbol"}))
        for pin in symbol.pins:
            if visible_pins is not None and pin.name not in visible_pins:
                continue
            px, py = pin.x, pin.y
            if px < -w:
                line(px, py, -w, py)
            elif px > w:
                line(w, py, px, py)
            elif py < -h:
                line(px, py, px, -h)
            elif py > h:
                line(px, h, px, py)
    elif k == "ground":
        line(0, -2, 0, -0.4)
        line(-0.60, -0.4, 0.60, -0.4)
        line(-0.42, 0, 0.42, 0)
        line(-0.22, 0.4, 0.22, 0.4)
    elif k in ("battery", "dc_source", "ac_source", "current_source"):
        line(0, -2, 0, -1)
        line(0, 1, 0, 2)
        if k == "battery":
            line(-0.9, -0.5, 0.9, -0.5)
            line(-0.55, 0.5, 0.55, 0.5)
            line(0, -1, 0, -0.5)
            line(0, 0.5, 0, 1)
        else:
            out.append(_el("circle", cx=0, cy=0, r=s, **{"class": "symbol"}))
            if k == "ac_source":
                out.append(f'<path class="symbol" d="M {-0.68*s} 0 Q {-0.34*s} {-0.65*s} 0 0 T {0.68*s} 0"/>')
            elif k == "current_source":
                line(0, 0.5, 0, -0.5)
                out.append(f'<path class="symbol" d="M {-0.22*s} {-0.25*s} L 0 {-0.55*s} L {0.22*s} {-0.25*s}"/>')
            else:
                out.append(f'<text class="mark" x="0" y="{-0.1*s}">+</text>')
                out.append(f'<text class="mark" x="0" y="{0.65*s}">−</text>')
    elif k in ("npn", "pnp", "nmos", "pmos"):
        line(-2, 0, -0.5, 0)
        line(1, -2, 1, -0.7)
        line(1, 0.7, 1, 2)
        if k in ("npn", "pnp"):
            line(-0.5, -0.85, -0.5, 0.85)
            line(-0.5, -0.55, 1, -0.7)
            line(-0.5, 0.55, 1, 0.7)
            if k == "npn":
                out.append(f'<path class="symbol" d="M {0.45*s} {0.35*s} L {1*s} {0.7*s} L {0.4*s} {0.83*s}"/>')
            else:
                out.append(f'<path class="symbol" d="M {0*s} {0.75*s} L {-0.5*s} {0.55*s} L {-0.05*s} {0.22*s}"/>')
        else:
            line(-0.4, -0.8, -0.4, 0.8)
            line(0.15, -0.85, 0.15, 0.85)
            line(0.15, -0.6, 1, -0.6)
            line(0.15, 0.6, 1, 0.6)
            if k == "pmos":
                out.append(_el("circle", cx=-0.75*s, cy=0, r=0.28*s, **{"class": "symbol"}))
    elif k == "opamp":
        out.append(f'<path class="symbol" d="M {-1.2*s} {-1.5*s} L {-1.2*s} {1.5*s} L {1.9*s} 0 Z"/>')
        line(-2, -1, -1.2, -1)
        line(-2, 1, -1.2, 1)
        line(1.9, 0, 3, 0)
        line(0, -2, 0, -0.91)
        line(0, 2, 0, 0.91)
        out.append(f'<text class="mark" x="{-0.95*s}" y="{-0.82*s}">−</text>')
        out.append(f'<text class="mark" x="{-0.95*s}" y="{1.13*s}">+</text>')
    elif k in ("resistor", "fuse"):
        line(-2, 0, -1.1, 0)
        line(1.1, 0, 2, 0)
        out.append(_el("rect", x=-1.1*s, y=-0.36*s, width=2.2*s, height=0.72*s,
                       **{"class": "symbol"}))
    elif k == "capacitor":
        line(-2, 0, -0.22, 0)
        line(0.22, 0, 2, 0)
        line(-0.22, -0.9, -0.22, 0.9)
        line(0.22, -0.9, 0.22, 0.9)
    elif k == "inductor":
        line(-2, 0, -1.2, 0)
        line(1.2, 0, 2, 0)
        out.append(f'<path class="symbol" d="M {-1.2*s} 0 ' +
                   ' '.join(f'C {(i*0.6-1.2+0.15)*s:.1f} {-0.9*s:.1f} {(i*0.6-1.2+0.45)*s:.1f} {-0.9*s:.1f} {(i*0.6-1.2+0.6)*s:.1f} 0' for i in range(4)) + '"/>')
    elif k in ("diode", "led"):
        line(-2, 0, -0.8, 0)
        line(0.5, 0, 2, 0)
        out.append(f'<path class="symbol" d="M {-0.8*s} {-0.75*s} L {-0.8*s} {0.75*s} L {0.5*s} 0 Z"/>')
        line(0.5, -0.8, 0.5, 0.8)
        if k == "led":
            out.append(f'<path class="symbol" d="M {-0.3*s} {-1.0*s} l {0.5*s} {-0.5*s} m {-0.1*s} 0 l {0.1*s} 0 l 0 {0.1*s}"/>')
    elif k == "switch":
        line(-2, 0, -0.8, 0)
        line(0.8, 0, 2, 0)
        out.append(_el("circle", cx=-0.8*s, cy=0, r=0.14*s, **{"class": "symbol"}))
        out.append(_el("circle", cx=0.8*s, cy=0, r=0.14*s, **{"class": "symbol"}))
        line(-0.8, 0, 0.6, -0.75)
    elif k == "lamp":
        line(-2, 0, -1, 0)
        line(1, 0, 2, 0)
        out.append(_el("circle", cx=0, cy=0, r=s, **{"class": "symbol"}))
        line(-0.7, -0.7, 0.7, 0.7)
        line(-0.7, 0.7, 0.7, -0.7)
    else:
        raise ValueError(f"Unknown symbol shape {k}")
    return out


def _pin_label_layout(spec: SymbolSpec, rotation: int, mirror: bool):
    """Place upright labels outside the component, using the pin's actual side."""
    labels = []
    for pin in spec.pins:
        x, y = transform_point(pin.x, pin.y, rotation, mirror)
        if spec.shape == "ic":
            if pin.x < -spec.half_width:
                dx, dy = transform_point(-1, 0, rotation, mirror)
            elif pin.x > spec.half_width:
                dx, dy = transform_point(1, 0, rotation, mirror)
            elif pin.y < -spec.half_height:
                dx, dy = transform_point(0, -1, rotation, mirror)
            else:
                dx, dy = transform_point(0, 1, rotation, mirror)
        else:
            length = math.hypot(x, y) or 1
            dx, dy = x / length, y / length
        label = pin.name + (f" ({pin.number})" if pin.number else "")
        if abs(dx) > abs(dy):
            side = "right" if dx > 0 else "left"
            lx, ly = x * GRID_PX + (11 if dx > 0 else -11), y * GRID_PX + 3.5
            anchor = "start" if dx > 0 else "end"
        else:
            side = "bottom" if dy > 0 else "top"
            lx, ly = x * GRID_PX, y * GRID_PX + (19 if dy > 0 else -12)
            anchor = "middle"
        labels.append((label, lx, ly, anchor, side, x * GRID_PX, y * GRID_PX))
    return labels


def make_symbol_svg(kind: str, value: str = "", cid: str = "U1",
                    pins: Sequence[str] | None = None,
                    rotation: int = 0, mirror: bool = False) -> str:
    """Render one transparent preview with labels outside component geometry."""
    spec = get_symbol(kind, pins)
    _check_orientation(rotation, mirror)
    if not isinstance(value, str) or not isinstance(cid, str):
        raise ValueError("value and cid must be strings")
    if len(value) > 100 or len(cid) > 50 or any(ord(c) < 32 for c in value + cid):
        raise ValueError("Invalid label text")

    corners = [transform_point(i * spec.half_width, j * spec.half_height, rotation, mirror)
               for i in (-1, 1) for j in (-1, 1)]
    endpoints = list(pin_positions(spec, rotation=rotation, mirror=mirror).values())
    all_points = corners + endpoints
    body_left = min(x for x, y in corners) * GRID_PX
    body_right = max(x for x, y in corners) * GRID_PX
    body_top = min(y for x, y in corners) * GRID_PX
    body_bottom = max(y for x, y in corners) * GRID_PX
    pin_labels = _pin_label_layout(spec, rotation, mirror)

    # Bounding boxes are conservative estimates for the fixed Arial font.
    bounds = [[min(x for x, y in all_points) * GRID_PX,
               min(y for x, y in all_points) * GRID_PX,
               max(x for x, y in all_points) * GRID_PX,
               max(y for x, y in all_points) * GRID_PX]]
    for label, x, baseline, anchor, side, _, _ in pin_labels:
        text_width = len(label) * 6.3
        left = x if anchor == "start" else x - text_width if anchor == "end" else x - text_width / 2
        bounds.append([left, baseline - 10, left + text_width, baseline + 3])

    # Title/value sit above/below every pin label, including rotated ICs.
    label_top = min(box[1] for box in bounds)
    label_bottom = max(box[3] for box in bounds)
    name_y = min(body_top, label_top) - 23
    value_y = max(body_bottom, label_bottom) + 29
    bounds.extend([
        [-len(cid)*5.8, name_y-17, len(cid)*5.8, name_y+3],
        [-len(value)*4.4, value_y-13, len(value)*4.4, value_y+3],
    ])
    margin = 18
    left = min(box[0] for box in bounds) - margin
    top = min(box[1] for box in bounds) - margin
    right = max(box[2] for box in bounds) + margin
    bottom = max(box[3] for box in bounds) + margin
    width, height = right-left, bottom-top
    cx, cy = -left, -top
    mir = " scale(-1 1)" if mirror else ""
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.1f} {height:.1f}" width="{width:.1f}" height="{height:.1f}">',
        '<title>Component symbol preview</title>',
        '<style><![CDATA[',
        '.symbol{fill:none;stroke:#213149;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round}',
        '.label{fill:#17243c;font-family:Arial,sans-serif;font-size:17px;font-weight:700;text-anchor:middle}',
        '.value{fill:#3e506d;font-family:Arial,sans-serif;font-size:13px;text-anchor:middle}',
        '.pin{fill:#394b66;font-family:Arial,sans-serif;font-size:10px}',
        '.mark{fill:#213149;font-family:Arial,sans-serif;font-size:16px;text-anchor:middle}',
        ']]></style>',
        f'<g transform="translate({cx:.1f} {cy:.1f}) rotate({rotation}){mir}">',
        *_local_art(spec),
        '</g>',
        f'<text class="label" x="{cx:.1f}" y="{cy+name_y:.1f}">{xml_escape(cid)}</text>',
        f'<text class="value" x="{cx:.1f}" y="{cy+value_y:.1f}">{xml_escape(value)}</text>',
    ]
    for label, x, baseline, anchor, side, px, py in pin_labels:
        out.append(f'<circle cx="{cx+px:.1f}" cy="{cy+py:.1f}" r="3" fill="#64748b"/>')
        out.append(f'<text class="pin" text-anchor="{anchor}" x="{cx+x:.1f}" y="{cy+baseline:.1f}">{xml_escape(label)}</text>')
    out.append('</svg>')
    return "\n".join(out) + "\n"


# REUSABLE SVG BODY

def symbol_body_svg(symbol: SymbolSpec, x_px: float, y_px: float,
                    rotation: int = 0, mirror: bool = False,
                    visible_pins: frozenset[str] | None = None) -> str:
    """Draw the component body in a larger SVG; labels can be placed separately."""
    _check_orientation(rotation, mirror)
    if not math.isfinite(x_px) or not math.isfinite(y_px):
        raise ValueError("Symbol position must be finite")
    flip = " scale(-1 1)" if mirror else ""
    return (f'<g transform="translate({x_px:.2f} {y_px:.2f}) rotate({rotation}){flip}">'
            + "\n".join(_local_art(symbol, visible_pins)) + "</g>")


def symbol_pin_labels(symbol: SymbolSpec, rotation: int = 0,
                      mirror: bool = False) -> list[tuple[str, float, float, str, str, float, float]]:
    """Return upright outward-facing labels, relative to symbol center (pixels)."""
    _check_orientation(rotation, mirror)
    return _pin_label_layout(symbol, rotation, mirror)


def routed_pin_labels(symbol: SymbolSpec, rotation: int, mirror: bool, active_pins):
    for label, x, y, anchor, side, pin_x, pin_y in symbol_pin_labels(symbol, rotation, mirror):
        if label.split(' (', 1)[0] not in active_pins:
            continue
        if side in ('left', 'right'):
            yield label, x, y - 14, anchor
        else:
            yield label, pin_x + 10, pin_y + 3.5, 'start'
