from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from .ai import generate_netlist, list_providers
from .engine import CircuitError, CircuitModel, make_svg_from_netlist, validate_model
from .export import OUTPUT_FORMATS, SchematicStyle, encode_schematic, normalize_format
from .routing import make_routed_svg
from .symbols import BUILTIN_SYMBOLS


# RESULTS

@dataclasses.dataclass
class CircuitResult:
    svg: str
    netlist: dict[str, Any]
    model: CircuitModel | None = None
    output_path: str | None = None
    output_format: str = "svg"

    def encode(self, output_format: str | None = None) -> str | bytes:
        return encode_schematic(self.svg, output_format or self.output_format)

    def save(self, path: str | Path, *, output_format: str | None = None) -> str:
        dest = Path(path)
        suffix = dest.suffix.lower().lstrip(".")
        data = self.encode(output_format or (suffix if suffix in OUTPUT_FORMATS else self.output_format))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            dest.write_text(data, encoding="utf-8")
        else:
            dest.write_bytes(data)
        self.output_path = str(dest)
        return self.output_path


@dataclasses.dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: list[str] = dataclasses.field(default_factory=list)
    model: CircuitModel | None = None


# DISCOVERY

def list_symbols() -> list[str]:
    return sorted(BUILTIN_SYMBOLS.keys())


# VALIDATION

def validate(data: dict[str, Any]) -> ValidationResult:
    try:
        model = validate_model(data)
        return ValidationResult(valid=True, errors=[], model=model)
    except (CircuitError, ValueError, TypeError, KeyError) as exc:
        return ValidationResult(valid=False, errors=[str(exc)], model=None)


# RENDERING

def render(
    model: CircuitModel | dict[str, Any],
    *,
    optimize: bool = False,
    color: str = "#000000",
    style: SchematicStyle | None = None,
    output_format: str = "svg",
) -> str | bytes:
    if isinstance(model, CircuitModel):
        svg = make_routed_svg(model, optimize=optimize, color=color)
    elif isinstance(model, dict):
        svg = make_svg_from_netlist(model, optimize=optimize, color=color)
    else:
        raise TypeError(f"Expected CircuitModel or netlist dict, got {type(model).__name__}")
    return encode_schematic(style.apply(svg) if style else svg, output_format)


# WORKFLOWS

def from_netlist(
    data: dict[str, Any],
    *,
    output: str | Path | None = None,
    optimize: bool = False,
    color: str = "#000000",
    style: SchematicStyle | None = None,
    output_format: str | None = None,
) -> CircuitResult:
    suffix = Path(output).suffix.lower().lstrip(".") if output is not None else ""
    output_format = normalize_format(output_format if output_format is not None else (
        suffix if suffix in OUTPUT_FORMATS else "svg"
    ))
    model = validate_model(data)
    svg = make_svg_from_netlist(data, optimize=optimize, color=color)
    result = CircuitResult(
        svg=style.apply(svg) if style else svg, netlist=data, model=model, output_format=output_format
    )
    if output is not None:
        result.save(output, output_format=output_format)
    return result


def generate(
    description: str,
    *,
    provider: str = "gemini",
    model: str | None = None,
    output: str | Path | None = None,
    optimize: bool = False,
    color: str = "#000000",
    correction: str = "",
    style: SchematicStyle | None = None,
    output_format: str | None = None,
    timeout: float = 120,
    retry_transient: bool = False,
    allow_model_fallback: bool = False,
    clarify: bool = False,
) -> CircuitResult:
    request_options = {}
    if timeout != 120:
        request_options["timeout"] = timeout
    if retry_transient:
        request_options["retry_transient"] = True
    if allow_model_fallback:
        request_options["allow_model_fallback"] = True
    if clarify:
        request_options["clarify"] = True
    netlist = generate_netlist(
        description,
        provider=provider,
        model=model,
        correction=correction,
        **request_options,
    )
    return from_netlist(
        netlist,
        output=output,
        optimize=optimize,
        color=color,
        style=style,
        output_format=output_format,
    )
