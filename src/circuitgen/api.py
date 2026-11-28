from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from .ai import generate_netlist, list_providers
from .erc import ERCReport, check_model
from .engine import CircuitError, CircuitModel, make_svg_from_netlist, validate_model
from .export import OUTPUT_FORMATS, SchematicStyle, encode_schematic, normalize_format
from .routing import make_routed_svg
from .symbols import BUILTIN_SYMBOLS
from .values import normalize_netlist_values


class NetlistRenderError(CircuitError):
    """A netlist was generated or supplied, but CircuitGen could not render it."""

    def __init__(self, message: str, netlist: dict[str, Any]):
        super().__init__(message)
        self.netlist = netlist


# RESULTS

@dataclasses.dataclass
class CircuitResult:
    svg: str
    netlist: dict[str, Any]
    model: CircuitModel | None = None
    output_path: str | None = None
    output_format: str = "svg"
    electrical_report: ERCReport | None = None

    def encode(self, output_format: str | None = None) -> str | bytes:
        return encode_schematic(self.svg, output_format or self.output_format)

    def save(self, path: str | Path, *, output_format: str | None = None) -> str:
        selected_format = normalize_format(output_format or self.output_format)
        path_text = str(path).strip()
        dest = (Path.cwd() / f"circuit.{selected_format}" if not path_text
                else Path(path_text).expanduser().resolve())
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
    electrical_report: ERCReport | None = None


# DISCOVERY

def list_symbols() -> list[str]:
    return sorted(BUILTIN_SYMBOLS.keys())


# VALIDATION

def validate(data: dict[str, Any]) -> ValidationResult:
    try:
        model = validate_model(data)
        return ValidationResult(valid=True, errors=[], model=model,
                                electrical_report=check_model(model))
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
        try:
            normalized = normalize_netlist_values(model)
            svg = make_svg_from_netlist(normalized, optimize=optimize, color=color)
            return encode_schematic(style.apply(svg) if style else svg, output_format)
        except Exception as exc:
            raise NetlistRenderError(str(exc), model) from exc
    else:
        raise TypeError(f"Expected CircuitModel or netlist dict, got {type(model).__name__}")
    return encode_schematic(style.apply(svg) if style else svg, output_format)


# WORKFLOWS

def from_netlist(
    data: dict[str, Any],
    *,
    output: str | Path | None = "",
    optimize: bool = False,
    color: str = "#000000",
    style: SchematicStyle | None = None,
    output_format: str | None = None,
) -> CircuitResult:
    normalized = normalize_netlist_values(data)
    suffix = Path(output).suffix.lower().lstrip(".") if output is not None else ""
    output_format = normalize_format(output_format if output_format is not None else (
        suffix if suffix in OUTPUT_FORMATS else "svg"
    ))
    try:
        model = validate_model(normalized)
        svg = make_svg_from_netlist(normalized, optimize=optimize, color=color)
    except Exception as exc:
        raise NetlistRenderError(str(exc), data) from exc
    result = CircuitResult(
        svg=style.apply(svg) if style else svg, netlist=normalized, model=model,
        output_format=output_format, electrical_report=check_model(model),
    )
    if output is not None:
        result.save(output, output_format=output_format)
    return result


def generate(
    description: str,
    *,
    provider: str = "gemini",
    model: str | None = None,
    output: str | Path | None = "",
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
