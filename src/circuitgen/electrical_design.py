"""Conservative checks for requested values in simple electrical branches."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .values import (format_component_value, nearest_preferred_value,
                     next_preferred_value, normalize_netlist_values,
                     parse_component_quantity, parse_quantity)

_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_PREFIX = r"(?:da|[qyzafpnumcdhKkMGTPEZYQµμ])"
_UNIT = r"(?:ohms?|[ΩΩ]|vdc|volts?|v|amps?|amperes?|a|farads?|f|henries|henry|h|hertz|hz|watts?|w|seconds?|sec|s)"
_RKM_MARKER = r"[RrKkMmGgTtPpNnUuFfAaµμ]"
_QUANTITY = re.compile(
    rf"(?<![\w.])(?:{_NUMBER}(?:[_\s-]*{_PREFIX})?[_\s-]*{_UNIT}"
    rf"|[+-]?\d+[Rr]\d+(?:[_\s-]*{_UNIT})?"
    rf"|{_NUMBER}[Rr](?:[_\s-]*{_UNIT})?"
    rf"|[+-]?\d+{_RKM_MARKER}\d+[_\s-]*{_UNIT})(?![\w])", re.I)
_LED_DROP = {"red": 2.0, "orange": 2.0, "amber": 2.0, "yellow": 2.1,
             "green": 2.2, "blue": 3.0, "violet": 3.2, "purple": 3.2, "white": 3.0}


@dataclass(frozen=True)
class DesignMismatch:
    message: str
    refs: tuple[str, ...]
    explicit_conflict: bool = False
    corrections: tuple[tuple[str, str], ...] = ()


def _quantities(text: str) -> list[tuple[float, str, int, int]]:
    result = []
    for match in _QUANTITY.finditer(text):
        parsed = parse_quantity(match.group())
        if parsed:
            result.append((parsed[0], parsed[1], match.start(), match.end()))
    return result


def _component_quantity(kind: str, value: str) -> tuple[float, str] | None:
    return parse_component_quantity(kind, value)


def _explicit(kind: str, value: str, quantities) -> bool:
    parsed = _component_quantity(kind, value)
    return bool(parsed and any(unit == parsed[1] and math.isclose(amount, parsed[0], rel_tol=1e-8)
                               for amount, unit, _, _ in quantities))


def explicit_component_values(description: str, netlist: dict) -> dict[str, tuple[str, str]]:
    quantities = _quantities(description)
    return {
        component["id"]: (component["type"], component["value"])
        for component in netlist.get("components", ())
        if isinstance(component, dict) and isinstance(component.get("id"), str)
        and isinstance(component.get("type"), str) and isinstance(component.get("value"), str)
        and _explicit(component["type"], component["value"], quantities)
    }


def preserve_explicit_values(netlist: dict, values: dict[str, tuple[str, str]]) -> None:
    components = {row.get("id"): row for row in netlist.get("components", ())
                  if isinstance(row, dict)}
    for cid, (kind, value) in values.items():
        row = components.get(cid)
        if row is not None and row.get("type") == kind:
            row["value"] = value


def _target_current(description: str, quantities) -> float | None:
    lowered = description.casefold()
    if not re.search(r"\b(?:leds?|diodes?)\b", lowered):
        return None
    for amount, unit, start, end in quantities:
        if unit == "A" and re.search(
                r"\b(?:target(?:ing)?|desired|limit(?:ed|ing)?|current\s+(?:of|at|target))\b",
                lowered[max(0, start - 70):end]):
            return amount
    return None


def _target_divider_voltage(description: str, quantities) -> float | None:
    lowered = description.casefold()
    divider = re.search(r"\bvoltage\s+divider\b", lowered)
    if not divider:
        return None
    before = lowered[max(0, divider.start() - 48):divider.start()]
    after = lowered[divider.end():divider.end() + 90]
    for amount, unit, start, end in quantities:
        if unit != "V":
            continue
        bridge = lowered[divider.end():start]
        if (start >= divider.end() and len(bridge) <= 70
                and re.search(r"\b(?:output|target|producing|produce|giving|gives|at)\b", bridge)):
            return amount
        if (end <= divider.start() and divider.start() - end <= 24
                and re.search(r"(?:output|target|to|producing|of)\s*$", before)):
            return amount
        if (start >= divider.end() and start - divider.end() <= 70
                and re.match(r"\s*(?:with\s+)?(?:an?\s+)?(?:output|target(?:\s+voltage)?|to)(?:\s+of)?\b", after)):
            return amount
    # Accept the common short form "3 V voltage divider from 9 V".
    for amount, unit, _, end in quantities:
        if unit == "V" and end <= divider.start() and divider.start() - end <= 12:
            return amount
    return None


def _target_cutoff_frequency(description: str, quantities) -> float | None:
    lowered = description.casefold()
    if not re.search(r"\b(?:rc|low[ -]pass)\b", lowered):
        return None
    for amount, unit, start, end in quantities:
        if unit == "Hz" and re.search(r"\b(?:cutoff|corner|frequency)\b",
                                      lowered[max(0, start - 60):end]):
            return amount
    return None


def _sources(model):
    for cid, component in model.components.items():
        if component.kind not in ("battery", "dc_source"):
            continue
        value = _component_quantity(component.kind, component.value)
        positive, negative = component.pins.get("p"), component.pins.get("n")
        if value and value[1] == "V" and value[0] > 0 and positive and negative:
            yield cid, value[0], positive, negative


def _pin_at(model, cid: str, net: str) -> str | None:
    return next((f"{cid}.{pin}" for pin, name in model.components[cid].pins.items()
                 if name == net), None)


def _only_pair(model, net: str, left: str, right: str) -> bool:
    return set(model.nets.get(net, ())) == {left, right}


def _contains_pair(model, net: str, left: str, right: str) -> bool:
    return {left, right}.issubset(model.nets.get(net, ()))


def _resistors(model):
    for cid, component in model.components.items():
        if component.kind != "resistor":
            continue
        value = _component_quantity("resistor", component.value)
        left, right = component.pins.get("a"), component.pins.get("b")
        if value and value[1] == "Ω" and value[0] > 0 and left and right:
            yield cid, left, right, value[0]


def _reachable(adjacency: dict[str, set[str]], start: str) -> set[str]:
    reached = {start}
    pending = [start]
    while pending:
        node = pending.pop()
        for neighbor in adjacency.get(node, ()):
            if neighbor not in reached:
                reached.add(neighbor)
                pending.append(neighbor)
    return reached


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    size = len(rhs)
    rows = [matrix[row][:] + [rhs[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(rows[row][column]), default=column)
        if abs(rows[pivot][column]) < 1e-14:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        scale = rows[column][column]
        rows[column] = [cell / scale for cell in rows[column]]
        for row in range(size):
            if row == column:
                continue
            factor = rows[row][column]
            if factor:
                rows[row] = [a - factor * b for a, b in zip(rows[row], rows[column])]
    return [rows[row][-1] for row in range(size)]


def _divider_voltages(model, positive: str, negative: str, supply: float):
    edges = tuple(_resistors(model))
    adjacency: dict[str, set[str]] = {}
    for _, left, right, _ in edges:
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    reached = _reachable(adjacency, positive)
    if negative not in reached:
        return {}, adjacency, edges
    nodes = sorted(reached - {positive, negative})
    index = {node: number for number, node in enumerate(nodes)}
    matrix = [[0.0] * len(nodes) for _ in nodes]
    rhs = [0.0] * len(nodes)
    for _, left, right, resistance in edges:
        if left not in reached or right not in reached:
            continue
        conductance = 1.0 / resistance
        if left not in (positive, negative):
            i = index[left]
            matrix[i][i] += conductance
            if right in index:
                matrix[i][index[right]] -= conductance
            elif right == positive:
                rhs[i] += conductance * supply
        if right not in (positive, negative):
            i = index[right]
            matrix[i][i] += conductance
            if left in index:
                matrix[i][index[left]] -= conductance
            elif left == positive:
                rhs[i] += conductance * supply
    result = _solve(matrix, rhs)
    if result is None:
        return {}, adjacency, edges
    voltages = {positive: supply, negative: 0.0}
    voltages.update(zip(nodes, result))
    return voltages, adjacency, edges


def _source_short_resistance(model, start: str, end: str) -> float | None:
    parent: dict[str, str] = {}

    def root(node: str) -> str:
        parent.setdefault(node, node)
        if parent[node] != node:
            parent[node] = root(parent[node])
        return parent[node]

    def union(left: str, right: str) -> None:
        a, b = root(left), root(right)
        if a != b:
            parent[b] = a

    for component in model.components.values():
        if component.kind in ("battery", "dc_source", "ac_source"):
            positive, negative = component.pins.get("p"), component.pins.get("n")
            if positive and negative:
                union(positive, negative)
    start, end = root(start), root(end)
    if start == end:
        return 0.0

    edges = []
    adjacency: dict[str, set[str]] = {}
    for cid, left, right, resistance in _resistors(model):
        left, right = root(left), root(right)
        if left == right:
            continue
        edges.append((cid, left, right, resistance))
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    reached = _reachable(adjacency, start)
    if end not in reached:
        return None
    nodes = sorted(reached - {end})
    index = {node: number for number, node in enumerate(nodes)}
    matrix = [[0.0] * len(nodes) for _ in nodes]
    rhs = [0.0] * len(nodes)
    rhs[index[start]] = 1.0
    for _, left, right, resistance in edges:
        if left not in reached or right not in reached:
            continue
        conductance = 1.0 / resistance
        if left != end:
            i = index[left]
            matrix[i][i] += conductance
            if right != end:
                matrix[i][index[right]] -= conductance
        if right != end:
            i = index[right]
            matrix[i][i] += conductance
            if left != end:
                matrix[i][index[left]] -= conductance
    result = _solve(matrix, rhs)
    return result[index[start]] if result and result[index[start]] > 0 else None


def _led_checks(description: str, model, quantities) -> list[DesignMismatch]:
    target = _target_current(description, quantities)
    sources = tuple(_sources(model))
    if target is None or target <= 0 or len(sources) != 1:
        return []
    source_id, supply, positive, negative = sources[0]
    found = []
    for led_id, led in model.components.items():
        if led.kind != "led":
            continue
        color = next((name for name in _LED_DROP if name in led.value.casefold()), None)
        anode, cathode = led.pins.get("a"), led.pins.get("b")
        if color is None or not anode or not cathode:
            continue
        for resistor_id, resistor in model.components.items():
            if resistor.kind != "resistor":
                continue
            resistance = _component_quantity("resistor", resistor.value)
            a_net, b_net = resistor.pins.get("a"), resistor.pins.get("b")
            if resistance is None or resistance[1] != "Ω" or resistance[0] <= 0:
                continue

            # Check either series order and either resistor orientation.
            if a_net == positive and b_net == anode and cathode == negative:
                expected_pairs = ((positive, f"{source_id}.p", f"{resistor_id}.a"),
                                  (anode, f"{resistor_id}.b", f"{led_id}.a"),
                                  (negative, f"{led_id}.b", f"{source_id}.n"))
            elif b_net == positive and a_net == anode and cathode == negative:
                expected_pairs = ((positive, f"{source_id}.p", f"{resistor_id}.b"),
                                  (anode, f"{resistor_id}.a", f"{led_id}.a"),
                                  (negative, f"{led_id}.b", f"{source_id}.n"))
            elif anode == positive and a_net == cathode and b_net == negative:
                expected_pairs = ((positive, f"{source_id}.p", f"{led_id}.a"),
                                  (cathode, f"{led_id}.b", f"{resistor_id}.a"),
                                  (negative, f"{resistor_id}.b", f"{source_id}.n"))
            elif anode == positive and b_net == cathode and a_net == negative:
                expected_pairs = ((positive, f"{source_id}.p", f"{led_id}.a"),
                                  (cathode, f"{led_id}.b", f"{resistor_id}.b"),
                                  (negative, f"{resistor_id}.a", f"{source_id}.n"))
            else:
                continue
            if not (_contains_pair(model, *expected_pairs[0])
                    and _only_pair(model, *expected_pairs[1])
                    and _contains_pair(model, *expected_pairs[2])):
                continue

            drop = _LED_DROP[color]
            minimum = (supply - drop) / target
            if minimum <= 0:
                continue
            preferred = next_preferred_value(minimum, "E12")
            current = (supply - drop) / resistance[0]
            if resistance[0] >= minimum and 0.9 * target <= current <= 1.05 * target:
                continue
            explicit = _explicit("resistor", resistor.value, quantities)
            found.append(DesignMismatch(
                f"LED current target check failed for {led_id}: {resistor_id} at "
                f"{resistor.value} gives about {current * 1000:.1f} mA (assumed "
                f"{drop:g} V forward drop for {color}). For {target * 1000:g} mA from "
                f"{supply:g} V, use at least {minimum:.3g} Ω; the next E12 value is "
                f"{preferred:g} Ω." + (" The resistor value was explicitly requested." if explicit else ""),
                (resistor_id, led_id, source_id), explicit,
                () if explicit else ((resistor_id, f"{preferred:g} Ω"),),
            ))
    return found


def _divider_checks(description: str, model, quantities) -> list[DesignMismatch]:
    target = _target_divider_voltage(description, quantities)
    sources = tuple(_sources(model))
    if target is None or target <= 0 or len(sources) != 1:
        return []
    source_id, supply, positive, negative = sources[0]
    if target >= supply:
        return []
    voltages, adjacency, edges = _divider_voltages(model, positive, negative, supply)
    if not voltages:
        return []
    candidates = [node for node, neighbors in adjacency.items()
                  if node not in (positive, negative) and len(neighbors) >= 2
                  and positive in _reachable(adjacency, node)
                  and negative in _reachable(adjacency, node)]
    if not candidates:
        return []
    output = min(candidates, key=lambda node: abs(voltages.get(node, -math.inf) - target))
    actual = voltages.get(output)
    if actual is None or math.isclose(actual, target, rel_tol=0.05):
        return []

    uppers = [(cid, resistance) for cid, left, right, resistance in edges
              if output in (left, right)
              and (right if left == output else left) == positive]
    lowers = [(cid, resistance) for cid, left, right, resistance in edges
              if output in (left, right)
              and (right if left == output else left) == negative]
    direct_upper = uppers[0] if uppers else None
    direct_lower = lowers[0] if lowers else None
    message = (f"Voltage-divider target check failed at net {output}: the connected "
               f"resistor network produces about {actual:.3g} V from {supply:g} V, "
               f"not the requested {target:g} V.")
    if direct_upper and direct_lower:
        observed_ratio = direct_upper[1] / direct_lower[1]
        target_ratio = supply / target - 1
        message += (f" Rupper/Rlower is about {observed_ratio:.3g}:1; "
                    f"the target calls for about {target_ratio:.3g}:1.")
    return [DesignMismatch(message, (source_id,), False)]


def _rc_checks(description: str, model, quantities) -> list[DesignMismatch]:
    target = _target_cutoff_frequency(description, quantities)
    sources = tuple(_sources(model))
    if target is None or target <= 0 or len(sources) != 1:
        return []
    source_id, _, _, negative = sources[0]
    capacitors = []
    for cid, component in model.components.items():
        if component.kind != "capacitor":
            continue
        value = _component_quantity("capacitor", component.value)
        left, right = component.pins.get("a"), component.pins.get("b")
        if value and value[1] == "F" and value[0] > 0 and left and right:
            capacitors.append((cid, component, left, right, value[0]))
    found = []
    for cid, component, left, right, capacitance in capacitors:
        resistance = _source_short_resistance(model, left, right)
        if resistance is None or resistance <= 0:
            continue
        actual = 1.0 / (2.0 * math.pi * resistance * capacitance)
        if math.isclose(actual, target, rel_tol=0.1):
            continue
        required_resistance = 1.0 / (2.0 * math.pi * target * capacitance)
        guidance = (f" At {capacitance:.3g} F, the target requires about "
                    f"{required_resistance:.3g} Ω total resistance; reduce the "
                    "divider's source resistance or use a smaller capacitor.")
        found.append(DesignMismatch(
            f"RC cutoff check failed for {cid}: the connected resistor network gives "
            f"about {actual:.3g} Hz (equivalent resistance {resistance:.3g} Ω with "
            f"{capacitance:.3g} F), not the requested {target:.3g} Hz. The resistance "
            f"seen by the capacitor includes the divider network and series resistor."
            f"{guidance}",
            (cid, source_id), False,
            _rc_capacitor_correction(cid, capacitance, resistance, target)
            if not _explicit("capacitor", component.value, quantities) else (),
        ))
    return found


def _rc_capacitor_correction(cid: str, capacitance: float, resistance: float,
                             target: float) -> tuple[tuple[str, str], ...]:
    """Suggest a standard inferred capacitor value when it meets the target."""
    required = 1.0 / (2.0 * math.pi * resistance * target)
    selected = nearest_preferred_value(required, "E12")
    resulting_cutoff = 1.0 / (2.0 * math.pi * resistance * selected)
    if not math.isclose(resulting_cutoff, target, rel_tol=0.1):
        return ()
    return ((cid, format_component_value("capacitor", f"{selected:.12g} F")),)


def apply_design_corrections(netlist: dict, mismatches: tuple[DesignMismatch, ...],
                             explicit_values: dict[str, tuple[str, str]]) -> dict | None:
    """Apply only validated, deterministic corrections to inferred values."""
    if not mismatches or any(item.explicit_conflict or not item.corrections
                             for item in mismatches):
        return None
    result = normalize_netlist_values(netlist)
    explicit_ids = set(explicit_values)
    rows = {row.get("id"): row for row in result.get("components", ())
            if isinstance(row, dict)}
    corrections = {}
    for mismatch in mismatches:
        for component_id, value in mismatch.corrections:
            if component_id in explicit_ids:
                return None
            corrections[component_id] = value
    if not corrections or any(component_id not in rows for component_id in corrections):
        return None
    for component_id, value in corrections.items():
        rows[component_id]["value"] = value
    return result


def check_design_targets(description: str, model) -> tuple[DesignMismatch, ...]:
    """Check selected targets in simple resistor and capacitor networks."""
    quantities = _quantities(description)
    return tuple(_led_checks(description, model, quantities)
                 + _divider_checks(description, model, quantities)
                 + _rc_checks(description, model, quantities))
