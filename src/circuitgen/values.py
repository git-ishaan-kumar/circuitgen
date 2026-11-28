"""Conservative formatting helpers for recognized electrical component values."""

from __future__ import annotations

import math
import re
from typing import Any


_UNIT_ALIASES = {
    "ω": "Ω", "Ω": "Ω", "ohm": "Ω", "ohms": "Ω",
    "f": "F", "farad": "F", "farads": "F",
    "h": "H", "henry": "H", "henries": "H",
    "v": "V", "volt": "V", "volts": "V", "vdc": "V",
    "a": "A", "amp": "A", "amps": "A", "ampere": "A", "amperes": "A",
    "w": "W", "watt": "W", "watts": "W",
    "hz": "Hz", "hertz": "Hz",
    "s": "s", "sec": "s", "second": "s", "seconds": "s",
}
_PREFIXES = {
    "": ("", 1.0), "q": ("q", 1e-30),
    "y": ("y", 1e-24), "z": ("z", 1e-21), "a": ("a", 1e-18),
    "f": ("f", 1e-15), "p": ("p", 1e-12),
    "n": ("n", 1e-9), "u": ("µ", 1e-6), "µ": ("µ", 1e-6),
    "μ": ("µ", 1e-6), "m": ("m", 1e-3), "k": ("k", 1e3),
    "c": ("c", 1e-2), "d": ("d", 1e-1), "da": ("da", 1e1),
    "h": ("h", 1e2), "K": ("k", 1e3), "M": ("M", 1e6),
    "G": ("G", 1e9), "T": ("T", 1e12), "P": ("P", 1e15),
    "E": ("E", 1e18), "Z": ("Z", 1e21), "Y": ("Y", 1e24), "Q": ("Q", 1e30),
}
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_VALUE = re.compile(rf"^\s*({_NUMBER})\s*(.*?)\s*$")
_PREFIXED_VALUE = re.compile(rf"^\s*({_NUMBER})\s*([qyzafpnumcdhKkMGTPEZYQµμ])\s*$")
_BARE_NUMERIC_VALUE = re.compile(rf"^\s*({_NUMBER})\s*$")
_RKM_VALUE = re.compile(r"^([+-]?\d+)([RrKkMmGgTtPpNnUuFfAaµμ])([0-9]+)(-?[A-Za-zΩΩµμ]*)$")
_R_SUFFIX_VALUE = re.compile(rf"^({_NUMBER})[Rr](?:[-_]*(?:ohms?|[ΩΩ]))?$", re.I)
_UNIT_BY_KIND = {
    "resistor": frozenset(("Ω",)),
    "capacitor": frozenset(("F",)),
    "inductor": frozenset(("H",)),
    "battery": frozenset(("V",)),
    "dc_source": frozenset(("V",)),
    "ac_source": frozenset(("V", "Hz")),
    "current_source": frozenset(("A",)),
    "diode": frozenset(("V", "A")),
    "led": frozenset(("V", "A")),
    "switch": frozenset(("Ω", "V", "A")),
    "lamp": frozenset(("Ω", "V", "A", "W")),
    "fuse": frozenset(("A", "V")),
    "npn": frozenset(("V", "A", "W")),
    "pnp": frozenset(("V", "A", "W")),
    "nmos": frozenset(("V", "A", "W")),
    "pmos": frozenset(("V", "A", "W")),
    "opamp": frozenset(("V", "A", "W", "Hz")),
    "ne555": frozenset(("V", "A", "W", "Hz", "s")),
    "arduino_uno": frozenset(("V", "A", "W", "Hz", "s")),
}
_DEFAULT_UNIT_BY_KIND = {
    "resistor": "Ω", "capacitor": "F", "inductor": "H",
    "battery": "V", "dc_source": "V", "ac_source": "V",
    "current_source": "A",
}
_COLORS = frozenset(("red", "orange", "yellow", "green", "blue", "violet", "purple", "white", "amber", "clear"))
_KNOWN_PARTS = {
    "ne555": "NE555", "ne556": "NE556", "lm358": "LM358", "lm393": "LM393",
    "lm741": "LM741", "lm317": "LM317", "lm386": "LM386", "lm7805": "LM7805",
    "lm7812": "LM7812", "tl072": "TL072", "atmega328p": "ATmega328P",
    "atmega2560": "ATmega2560", "arduino uno": "Arduino Uno", "esp32": "ESP32",
    "esp8266": "ESP8266", "ssd1306": "SSD1306", "bmp280": "BMP280",
    "dht11": "DHT11", "dht22": "DHT22", "ds18b20": "DS18B20", "tmp36": "TMP36",
    "74hc595": "74HC595", "cd4017": "CD4017", "uln2003": "ULN2003",
    "pc817": "PC817", "irfz44n": "IRFZ44N", "2n2222": "2N2222",
    "2n3904": "2N3904", "bc547": "BC547", "bc557": "BC557",
}
_ENGINEERING_STEPS = (("q", 1e-30), ("y", 1e-24),
                      ("z", 1e-21), ("a", 1e-18), ("f", 1e-15),
                      ("p", 1e-12), ("n", 1e-9),
                      ("µ", 1e-6), ("m", 1e-3), ("", 1.0),
                      ("k", 1e3), ("M", 1e6), ("G", 1e9), ("T", 1e12),
                      ("P", 1e15), ("E", 1e18), ("Z", 1e21), ("Y", 1e24), ("Q", 1e30))


def parse_quantity(value: str) -> tuple[float, str] | None:
    """Read an explicit number and recognized electrical unit, if present."""
    if not isinstance(value, str):
        return None
    compact = re.sub(r"[_\s]+", "", value.strip())
    r_suffix = _R_SUFFIX_VALUE.fullmatch(compact)
    if r_suffix:
        magnitude = float(r_suffix.group(1))
        return (magnitude, "Ω") if math.isfinite(magnitude) else None
    rkm = _parse_rkm(compact)
    if rkm is not None:
        return rkm
    match = _VALUE.fullmatch(compact)
    if not match:
        return None
    number, suffix = match.groups()
    suffix = re.sub(r"^[-]+|[-]+$", "", suffix.strip())
    unit = _UNIT_ALIASES.get(suffix.casefold())
    prefix = ""
    if unit is None:
        for candidate in sorted((item for item in _PREFIXES if item), key=len, reverse=True):
            if suffix.startswith(candidate):
                unit_suffix = re.sub(r"^[-]+|[-]+$", "", suffix[len(candidate):].strip())
                unit = _UNIT_ALIASES.get(unit_suffix.casefold())
                if unit is not None:
                    prefix = candidate
                    break
    prefix_data = _PREFIXES.get(prefix)
    if unit is None or prefix_data is None:
        return None
    try:
        magnitude = float(number) * prefix_data[1]
    except (OverflowError, ValueError):
        return None
    return (magnitude, unit) if math.isfinite(magnitude) else None


def _parse_rkm(value: str, default_unit: str | None = None) -> tuple[float, str] | None:
    match = _RKM_VALUE.fullmatch(value)
    if not match:
        return None
    whole, marker, fraction, raw_unit = match.groups()
    marker_scale = {
        "R": "", "r": "", "K": "k", "k": "k", "M": "M", "m": "m",
        "G": "G", "g": "G", "T": "T", "t": "T", "P": "P", "p": "p",
        "N": "n", "n": "n", "U": "µ", "u": "µ", "µ": "µ", "μ": "µ",
        "F": "f", "f": "f", "A": "a", "a": "a",
    }[marker]
    raw_unit = raw_unit.lstrip("-")
    unit = _UNIT_ALIASES.get(raw_unit.casefold()) if raw_unit else default_unit
    if unit is None and not raw_unit and marker in ("R", "r"):
        unit = "Ω"
    if unit is None:
        return None
    return parse_quantity(f"{whole}.{fraction}{marker_scale}{unit}")


def parse_component_quantity(kind: str, value: str) -> tuple[float, str] | None:
    """Parse a quantity using the component's unit when shorthand omits it."""
    parsed = parse_quantity(value)
    if parsed:
        return parsed
    default_unit = _DEFAULT_UNIT_BY_KIND.get(kind)
    if not default_unit or not isinstance(value, str):
        return None
    compact = re.sub(r"[_\s]+", "", value.strip())
    parsed = _parse_rkm(compact, default_unit)
    if parsed:
        return parsed
    abbreviated = _PREFIXED_VALUE.fullmatch(compact)
    if abbreviated:
        return parse_quantity(f"{abbreviated.group(1)}{abbreviated.group(2)}{default_unit}")
    bare = _BARE_NUMERIC_VALUE.fullmatch(compact)
    if bare:
        return parse_quantity(f"{bare.group(1)}{default_unit}")
    return None


def _number_text(number: float) -> str:
    text = f"{number:.12g}"
    return "0" if text in ("-0", "-0.0") else text


def format_component_value(kind: str, value: str) -> str:
    """Normalize known quantities and labels without rewriting custom text."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return value
    allowed = _UNIT_BY_KIND.get(kind)
    if allowed:
        parsed = parse_component_quantity(kind, stripped)
        if parsed and parsed[1] in allowed:
            magnitude, unit = parsed
            if magnitude == 0:
                return f"0 {unit}"
            for engineering_prefix, scale in _ENGINEERING_STEPS:
                scaled = magnitude / scale
                if 1 <= abs(scaled) < 1000:
                    text = _number_text(scaled)
                    if abs(float(text)) < 1000:
                        return f"{text} {engineering_prefix}{unit}"
            engineering_prefix, scale = _ENGINEERING_STEPS[-1 if abs(magnitude) >= 1e30 else 0]
            return f"{_number_text(magnitude / scale)} {engineering_prefix}{unit}"

    folded = stripped.casefold()
    if kind in ("led", "diode") and folded in _COLORS:
        return folded
    if folded in _KNOWN_PARTS:
        return _KNOWN_PARTS[folded]
    return value


def normalize_netlist_values(data: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow netlist copy with component values consistently formatted."""
    if not isinstance(data, dict) or not isinstance(data.get("components"), list):
        return data
    result = dict(data)
    components = []
    for row in data["components"]:
        if not isinstance(row, dict):
            components.append(row)
            continue
        component = dict(row)
        if isinstance(component.get("type"), str) and isinstance(component.get("value"), str):
            component["value"] = format_component_value(component["type"], component["value"])
        components.append(component)
    result["components"] = components
    return result


_E_SERIES = {
    "E6": (1.0, 1.5, 2.2, 3.3, 4.7, 6.8),
    "E12": (1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2),
    "E24": (1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
           3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1),
}


def next_preferred_value(minimum: float, series: str = "E12") -> float:
    """Return the next preferred-number value at or above a positive minimum."""
    if (isinstance(minimum, bool) or not isinstance(minimum, (int, float))
            or not math.isfinite(minimum) or minimum <= 0):
        raise ValueError("minimum must be a finite positive number")
    selected = series.upper()
    if selected == "E96":
        base = tuple(round(10 ** (index / 96), 2) for index in range(96))
    elif selected in _E_SERIES:
        base = _E_SERIES[selected]
    else:
        raise ValueError("series must be E6, E12, E24, or E96")
    decade = 10 ** math.floor(math.log10(minimum))
    for _ in range(3):
        for value in base:
            candidate = value * decade
            if math.isfinite(candidate) and candidate >= minimum:
                return float(f"{candidate:.12g}")
        decade *= 10
    raise ValueError("minimum is outside the supported numeric range")


def nearest_preferred_value(target: float, series: str = "E12") -> float:
    """Return the preferred value closest to a positive target by ratio."""
    if (isinstance(target, bool) or not isinstance(target, (int, float))
            or not math.isfinite(target) or target <= 0):
        raise ValueError("target must be a finite positive number")
    selected = series.upper()
    if selected == "E96":
        base = tuple(round(10 ** (index / 96), 2) for index in range(96))
    elif selected in _E_SERIES:
        base = _E_SERIES[selected]
    else:
        raise ValueError("series must be E6, E12, E24, or E96")
    decade = 10 ** math.floor(math.log10(target))
    candidates = (value * decade * scale for scale in (0.1, 1.0, 10.0) for value in base)
    closest = min((value for value in candidates if math.isfinite(value) and value > 0),
                  key=lambda value: abs(math.log(value / target)))
    return float(f"{closest:.12g}")
