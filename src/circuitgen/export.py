"""Schematic appearance and export formats."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re


OUTPUT_FORMATS = ("svg", "png", "pdf")
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")


@dataclass(frozen=True)
class SchematicStyle:
    """Optional overrides for the renderer's default appearance."""

    background: str = "transparent"
    component_color: str | None = None
    wire_color: str | None = None
    text_color: str | None = None
    show_component_ids: bool = True
    show_component_values: bool = True

    def __post_init__(self) -> None:
        for name in ("background", "component_color", "wire_color", "text_color"):
            value = getattr(self, name)
            if name == "background" and value in ("transparent", "white", "black"):
                continue
            if name != "background" and value is None:
                continue
            if not isinstance(value, str) or not _HEX_COLOR.fullmatch(value):
                raise ValueError(f"{name} must be a six-digit hex color, such as #336699")

    def apply(self, svg: str) -> str:
        rules = []
        if self.component_color:
            rules.append(f".symbol,.fill{{stroke:{self.component_color}}}.fill{{fill:{self.component_color}}}")
        if self.wire_color:
            rules.append(f".wire,.ground-mark,.power-mark{{stroke:{self.wire_color}}}.junction{{fill:{self.wire_color}}}")
        if self.text_color:
            rules.append(f".name,.label,.value,.pin,.mark,svg > .netlabel{{fill:{self.text_color}}}")
        if not self.show_component_ids:
            rules.append(".name,.label{display:none}")
        if not self.show_component_values:
            # Preserve the adjacent polarity marks in the original series/parallel renderer.
            value_tag = r'<text class="value"[^>]*>'
            pattern = rf'({value_tag}\+</text>\s*{value_tag}−</text>)|{value_tag}[^<]*</text>'
            svg = re.sub(pattern, lambda match: match.group(1) or "", svg)
        if self.background != "transparent":
            offset = svg.index(">") + 1
            svg = svg[:offset] + f'<rect width="100%" height="100%" fill="{self.background}"/>' + svg[offset:]
        if rules:
            svg = svg.replace("</svg>", f'<style>{"".join(rules)}</style></svg>', 1)
        return svg


def normalize_format(output_format: str) -> str:
    value = output_format.lower()
    if value not in OUTPUT_FORMATS:
        raise ValueError("Output format must be SVG, PNG, or PDF")
    return value


def encode_schematic(svg: str, output_format: str) -> str | bytes:
    output_format = normalize_format(output_format)
    if output_format == "svg":
        return svg

    try:
        import resvg_py
    except ImportError:
        raise RuntimeError("PNG and PDF export require resvg-py. Reinstall CircuitGen with its dependencies.") from None

    image = resvg_py.svg_to_bytes(svg_string=svg, zoom=2 if output_format == "pdf" else 1)
    if output_format == "png":
        return image

    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("PDF export requires Pillow. Reinstall CircuitGen with its dependencies.") from None

    with Image.open(BytesIO(image)) as png, BytesIO() as output:
        png.save(output, format="PDF", resolution=144, creationDate=None, modDate=None)
        return output.getvalue()
