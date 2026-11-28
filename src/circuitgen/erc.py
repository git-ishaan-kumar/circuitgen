"""Conservative electrical rule checks for structurally valid CircuitGen netlists.

This module does not simulate circuits, verify custom pinouts, or guarantee safety.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .engine import CircuitError, CircuitModel, validate_model
from .values import parse_quantity


@dataclass(frozen=True)
class ERCIssue:
    severity: str
    code: str
    message: str
    refs: tuple[str, ...] = ()
    suggestion: str = ""


@dataclass(frozen=True)
class ERCReport:
    issues: tuple[ERCIssue, ...]

    @property
    def errors(self) -> tuple[ERCIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ERCIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def infos(self) -> tuple[ERCIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "info")

    @property
    def ok(self) -> bool:
        """True when the checker found no definite errors; warnings may remain."""
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "info": len(self.infos),
            },
            "issues": [asdict(issue) for issue in self.issues],
        }

    def format_text(self) -> str:
        lines = [f"ERC: {len(self.errors)} error(s), {len(self.warnings)} warning(s), "
                 f"{len(self.infos)} info message(s)"]
        for issue in self.issues:
            where = f" [{', '.join(issue.refs)}]" if issue.refs else ""
            lines.append(f"{issue.severity.upper()} {issue.code}{where}: {issue.message}")
            if issue.suggestion:
                lines.append(f"  Suggestion: {issue.suggestion}")
        if not self.issues:
            lines.append("No issues detected by the implemented checks.")
        return "\n".join(lines)


VOLTAGE_SOURCES = frozenset(("battery", "dc_source", "ac_source"))
TWO_TERMINAL_PARTS = frozenset((
    "resistor", "capacitor", "inductor", "diode", "led", "lamp", "fuse",
    "switch", "battery", "dc_source", "ac_source", "current_source",
))
BYPASSABLE_PARTS = frozenset((
    "resistor", "capacitor", "inductor", "diode", "led", "lamp", "fuse",
))
OUTPUT_PINS = {
    "opamp": frozenset(("OUT",)),
    "ne555": frozenset(("OUT",)),
}
REQUIRED_POWER_PINS = {
    "opamp": ("V+", "V-"),
    "ne555": ("VCC", "GND"),
    "arduino_uno": ("GND",),
}
GROUND_PINS = frozenset(("GND", "VSS", "GROUND"))
POSITIVE_PINS = frozenset(("VCC", "VDD", "V+", "5V", "3V3", "VIN"))
GROUND_NET_NAMES = frozenset(("GND", "GROUND", "VSS"))
POWER_NET_NAMES = frozenset(("VCC", "VDD"))
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _voltage(value: str) -> float | None:
    parsed = parse_quantity(value)
    return parsed[0] if parsed and parsed[1] == "V" else None


def _power_role(kind: str, pin: str) -> str | None:
    if pin.upper() in GROUND_PINS:
        return "ground"
    if pin.upper() in POSITIVE_PINS:
        return "positive"
    return None


def check_model(model: CircuitModel) -> ERCReport:
    """Check connectivity and known pin conventions without changing the model."""
    issues: list[ERCIssue] = []

    def add(severity: str, code: str, message: str, refs: tuple[str, ...] = (),
            suggestion: str = "") -> None:
        issues.append(ERCIssue(severity, code, message, tuple(sorted(refs)), suggestion))

    # Source shorts, bypassed parts, and disconnected terminals.
    for cid, component in sorted(model.components.items()):
        symbol = model.symbols[cid]
        pins = component.pins
        if component.kind in TWO_TERMINAL_PARTS:
            missing = tuple(f"{cid}.{name}" for name in symbol.pin_names if name not in pins)
            if missing:
                add("warning", "UNCONNECTED_TERMINAL",
                    f"{cid} has one or more terminals not assigned to a net.", missing,
                    "Connect the terminal or verify that the open connection is intentional.")
            if len(pins) == 2 and len(set(pins.values())) == 1:
                if component.kind in VOLTAGE_SOURCES:
                    add("error", "SHORTED_VOLTAGE_SOURCE",
                        f"The two terminals of voltage source {cid} share net {next(iter(pins.values()))}.",
                        (cid, next(iter(pins.values()))),
                        "Separate its positive and negative terminals unless you are modeling a deliberate short.")
                elif component.kind in BYPASSABLE_PARTS:
                    add("warning", "BYPASSED_COMPONENT",
                        f"Both terminals of {cid} connect to the same net; the component is bypassed.",
                        (cid, next(iter(pins.values()))),
                        "Check whether the two terminals were assigned to the intended nets.")

        required = REQUIRED_POWER_PINS.get(component.kind)
        if required is None and component.kind not in ("arduino_uno",):
            # For unknown custom ICs, these names are hints only; don't invent a pinout.
            names = set(symbol.pin_names)
            required = tuple(p for p in ("VCC", "VDD", "GND") if p in names)
        if component.kind == "opamp" and pins.get("V+") is not None and pins.get("V+") == pins.get("V-"):
            add("error", "SHORTED_DEVICE_SUPPLY",
                f"{cid}.V+ and {cid}.V- share net {pins['V+']}.",
                (f"{cid}.V+", f"{cid}.V-", pins['V+']),
                "Connect the op-amp power rails to their intended separate supply nets.")
        for pin in required or ():
            if pin not in pins or len(model.nets[pins[pin]]) < 2:
                add("warning", "UNCONNECTED_POWER_PIN",
                    f"{cid}.{pin} does not have a connection to another component.",
                    (f"{cid}.{pin}",),
                    "Check its power and ground connections against the device datasheet.")

        if component.kind not in model_builtin_kinds():
            add("info", "UNVERIFIED_CUSTOM_PINOUT",
                f"The pin names for custom component {cid} have not been checked against a datasheet.",
                (cid,), "Verify the real component's pin numbers, supply voltage, and pin functions.")

    # Per-net checks: dangling nets, shared output pins and unlikely supply mixing.
    for net_name, refs in sorted(model.nets.items()):
        if len(refs) == 1:
            add("warning", "DANGLING_NET",
                f"Net {net_name} has only one attached pin.", (net_name, refs[0]),
                "Connect another terminal or remove an unused net declaration.")

        driven = tuple(sorted(
            ref for ref in refs
            if ref.split(".")[1] in OUTPUT_PINS.get(
                model.components[ref.split(".")[0]].kind, frozenset())
        ))
        if len(driven) > 1:
            add("warning", "OUTPUT_CONFLICT",
                f"More than one potentially driven output is connected to {net_name}.",
                (net_name,) + driven,
                "Check whether the outputs are push-pull, open-drain, or intentionally shared.")

        roles = [(ref, _power_role(model.components[ref.split(".")[0]].kind,
                                   ref.split(".")[1])) for ref in refs]
        positive = tuple(ref for ref, role in roles if role == "positive")
        ground = tuple(ref for ref, role in roles if role == "ground")
        if positive and ground:
            for pos_ref in positive:
                for gnd_ref in ground:
                    if pos_ref.split(".")[0] == gnd_ref.split(".")[0]:
                        add("error", "SHORTED_DEVICE_SUPPLY",
                            f"A device's positive supply and ground pins share {net_name}.",
                            (net_name, pos_ref, gnd_ref),
                            "Connect the supply and ground pins to separate nets.")
            if not any(pos_ref.split(".")[0] == gnd_ref.split(".")[0]
                       for pos_ref in positive for gnd_ref in ground):
                add("warning", "POSSIBLE_RAIL_CONFLICT",
                    f"Positive supply pins and ground pins from different devices share {net_name}.",
                    (net_name,) + positive + ground,
                    "Verify whether this is a deliberate reference connection or an incorrect supply net.")
        elif net_name.upper() in GROUND_NET_NAMES and positive:
            add("warning", "SUPPLY_ON_GROUND_NET",
                f"Net {net_name} is named as ground but connects to a positive supply pin.",
                (net_name,) + positive)
        elif net_name.upper() in POWER_NET_NAMES and ground:
            add("warning", "GROUND_ON_POWER_NET",
                f"Net {net_name} is named as power but connects to a ground pin.",
                (net_name,) + ground)

        if any(ref.endswith(".5V") for ref in refs) and any(ref.endswith(".3V3") for ref in refs):
            add("warning", "MIXED_POWER_RAILS",
                f"5V and 3V3 pins appear on the same net {net_name}.", (net_name,),
                "Check the voltage regulator and power-rail assignments.")

    # Multiple voltage sources in parallel can conflict; series connections are fine.
    voltage_sources = [(cid, c) for cid, c in sorted(model.components.items())
                       if c.kind in VOLTAGE_SOURCES and {"p", "n"} <= c.pins.keys()]
    for i, (left_id, left) in enumerate(voltage_sources):
        for right_id, right in voltage_sources[i + 1:]:
            if {left.pins["p"], left.pins["n"]} != {right.pins["p"], right.pins["n"]}:
                continue
            same_polarity = left.pins["p"] == right.pins["p"]
            left_v, right_v = _voltage(left.value), _voltage(right.value)
            if (left.kind != "ac_source" and right.kind != "ac_source"
                    and same_polarity and left_v is not None and right_v is not None
                    and abs(left_v - right_v) > 1e-9):
                add("error", "CONFLICTING_VOLTAGE_SOURCES",
                    f"Parallel sources {left_id} ({left.value}) and {right_id} ({right.value}) "
                    "specify different DC voltages.", (left_id, right_id),
                    "Avoid directly paralleling voltage sources with different voltages.")
            else:
                add("warning", "PARALLEL_VOLTAGE_SOURCES",
                    f"Voltage sources {left_id} and {right_id} connect across the same two nets"
                    + (" with opposite polarities." if not same_polarity else "."),
                    (left_id, right_id),
                    "Check their voltages, polarities, phase, and current-sharing behavior.")

    # Disconnected blocks aren't automatically errors (e.g., isolated circuit sections).
    parents = {cid: cid for cid in model.components}

    def find(cid: str) -> str:
        while parents[cid] != cid:
            parents[cid] = parents[parents[cid]]
            cid = parents[cid]
        return cid

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parents[max(ra, rb)] = min(ra, rb)

    for refs in model.nets.values():
        members = sorted({ref.split(".", 1)[0] for ref in refs})
        for cid in members[1:]:
            union(members[0], cid)
    groups: dict[str, list[str]] = {}
    for cid in sorted(model.components):
        groups.setdefault(find(cid), []).append(cid)
    if len(groups) > 1:
        add("info", "DISCONNECTED_GROUPS",
            f"The netlist contains {len(groups)} disconnected component groups.",
            tuple("/".join(group) for group in groups.values()),
            "Verify that these blocks are meant to be electrically separate.")

    issues.sort(key=lambda issue: (SEVERITY_ORDER[issue.severity], issue.code,
                                   issue.refs, issue.message))
    return ERCReport(tuple(issues))


def model_builtin_kinds() -> frozenset[str]:
    from .symbols import BUILTIN_SYMBOLS
    return frozenset(BUILTIN_SYMBOLS)


def check_electrical_rules(raw: dict[str, Any]) -> ERCReport:
    """Validate a CircuitGen netlist and return conservative electrical diagnostics."""
    return check_model(validate_model(raw))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a CircuitGen netlist for electrical rule issues")
    parser.add_argument("netlist", type=Path)
    parser.add_argument("--json", action="store_true", help="Print a structured JSON report")
    parser.add_argument("--fail-on-warning", action="store_true",
                        help="Return a nonzero exit code when warnings are present")
    args = parser.parse_args()
    try:
        raw = json.loads(args.netlist.read_text(encoding="utf-8"))
        report = check_electrical_rules(raw)
    except (OSError, ValueError, CircuitError) as error:
        if args.json:
            print(json.dumps({"ok": False, "validation_error": str(error)}, indent=2))
        else:
            print(f"Invalid netlist: {error}")
        return 2
    print(json.dumps(report.as_dict(), indent=2) if args.json else report.format_text())
    return 1 if report.errors or (args.fail_on_warning and report.warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
