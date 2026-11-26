"""Deterministic, routing-independent placement of schematic symbols.

Produces a layout proposal for arbitrary validated circuit topologies. It does
not draw electrical wires. Phase 5 will route using each placed pin endpoint.
"""

from __future__ import annotations

import collections
import dataclasses
import math
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape as xml_escape

from .symbols import (GRID_PX, SymbolSpec, label_width, pin_positions, routed_pin_labels, symbol_body_svg,
                     symbol_pin_labels, transform_point)

if TYPE_CHECKING:
    from .engine import CircuitModel, Component

SOURCE_KINDS = {"battery", "dc_source", "ac_source", "current_source"}
COLUMN_GAP = 6.0
ROW_GAP = 4.5
ISLAND_GAP = 9.0


@dataclasses.dataclass(frozen=True)
class SymbolPlacement:
    cid: str
    x: float
    y: float
    rotation: int
    mirror: bool
    half_width: float
    half_height: float
    pin_positions: dict[str, tuple[float, float]]
    title_y: float
    value_y: float
    title_x: float = 0.0
    value_x: float = 0.0
    label_anchor: str = "middle"


@dataclasses.dataclass(frozen=True)
class Placement:
    symbols: dict[str, SymbolPlacement]
    layers: tuple[tuple[str, ...], ...]
    islands: tuple[tuple[str, ...], ...]


def _xml(s: str) -> str:
    return xml_escape(s, {'"': '&quot;', "'": '&apos;'})


def _component_graph(model: CircuitModel) -> dict[str, dict[str, float]]:
    """Weighted connectivity graph. High-fanout nets have less pairwise weight."""
    graph: dict[str, dict[str, float]] = {cid: {} for cid in model.components}
    for net in model.nets.values():
        members = sorted({pin.split(".", 1)[0] for pin in net})
        if len(members) < 2:
            continue
        weight = 1 / (len(members) - 1)
        for i, first in enumerate(members):
            for second in members[i + 1:]:
                graph[first][second] = graph[first].get(second, 0.0) + weight
                graph[second][first] = graph[second].get(first, 0.0) + weight
    return graph


def _islands(graph: dict[str, dict[str, float]]) -> list[tuple[str, ...]]:
    unseen = set(graph)
    groups = []
    while unseen:
        seed = min(unseen)
        queue = collections.deque([seed])
        unseen.remove(seed)
        group = []
        while queue:
            current = queue.popleft()
            group.append(current)
            for neighbor in sorted(graph[current]):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        groups.append(tuple(sorted(group)))
    groups.sort(key=lambda group: (
        not any(cid.upper().startswith("V") for cid in group), group[0]
    ))
    return groups


def _net_depths(model: CircuitModel, group: tuple[str, ...], anchor: str | None) -> dict[str, int]:
    """Net graph ignores sources as shorts; levels are topological, not voltages."""
    all_nets = sorted({net for cid in group for net in model.components[cid].pins.values()})
    connections: dict[str, set[str]] = {name: set() for name in all_nets}
    for cid in group:
        part = model.components[cid]
        if part.kind in SOURCE_KINDS:
            continue
        attached = sorted(set(part.pins.values()))
        # A star connects an arbitrary-pin part's nets without quadratic edges.
        if attached:
            for name in attached[1:]:
                connections[attached[0]].add(name)
                connections[name].add(attached[0])
    roots = []
    if anchor:
        first = model.components[anchor].pins.get("p")
        if first in connections:
            roots.append(first)
    roots += sorted(all_nets, key=lambda n: (not any(t in n.upper() for t in
        ("INPUT", "VIN", "VCC", "PWR")), n))
    depth = {}
    for root in roots:
        if root in depth:
            continue
        base = max(depth.values(), default=-2) + 2
        depth[root] = base
        queue = collections.deque([root])
        while queue:
            current = queue.popleft()
            for neighbor in sorted(connections[current]):
                if neighbor not in depth:
                    depth[neighbor] = depth[current] + 1
                    queue.append(neighbor)
    return depth


def _geometry(symbol: SymbolSpec, comp: Component, rotation: int, mirror: bool):
    """Conservative bounding box, including pin labels and id/value text."""
    corners = [transform_point(i * symbol.half_width, j * symbol.half_height,
                               rotation, mirror)
               for i in (-1, 1) for j in (-1, 1)]
    points = corners + list(pin_positions(symbol, rotation=rotation, mirror=mirror).values())
    left, top = min(x for x, _ in points), min(y for _, y in points)
    right, bottom = max(x for x, _ in points), max(y for _, y in points)

    if len(symbol.pins) > 2:
        for label, lx, baseline, anchor in routed_pin_labels(symbol, rotation, mirror, comp.pins):
            x, y = lx / GRID_PX, baseline / GRID_PX
            text_width = label_width(label, 10, 6.3) / GRID_PX
            label_left = x if anchor == "start" else (x - text_width if anchor == "end"
                                                         else x - text_width / 2)
            left = min(left, label_left)
            right = max(right, label_left + text_width)
            top = min(top, y - 10 / GRID_PX)
            bottom = max(bottom, y + 3 / GRID_PX)

    title_y = top - 23 / GRID_PX
    value_y = bottom + 29 / GRID_PX
    if symbol.shape == "ground":
        title_y = bottom + 23 / GRID_PX
        value_y = title_y + 0.85
    id_width = label_width(comp.cid, 17, 10.5) / GRID_PX
    value_width = label_width(comp.value, 13, 7.8) / GRID_PX
    left = min(left, -id_width / 2, -value_width / 2)
    right = max(right, id_width / 2, value_width / 2)
    top = min(top, title_y - 17 / GRID_PX)
    bottom = max(bottom, value_y + 4 / GRID_PX)
    return (max(abs(left), abs(right)) + 1,
            max(abs(top), abs(bottom)) + 1,
            title_y, value_y)


def _choose_orientation(comp: Component, symbol: SymbolSpec,
                        depth: dict[str, int], anchor: bool) -> tuple[int, bool]:
    if comp.kind in SOURCE_KINDS or anchor or len(symbol.pins) != 2:
        return 0, False
    first, second = symbol.pin_names
    if first not in comp.pins or second not in comp.pins:
        return 0, False
    a, b = depth[comp.pins[first]], depth[comp.pins[second]]
    if a == b:
        return 90, False
    return 0, a > b


def _layer_order(layer_ids: list[str], previous: dict[str, int],
                 graph: dict[str, dict[str, float]]) -> list[str]:
    if not previous:
        return sorted(layer_ids)
    def score(cid: str):
        linked = [(previous[other], weight) for other, weight in graph[cid].items()
                  if other in previous]
        if not linked:
            return (float("inf"), cid)
        barycenter = sum(pos * weight for pos, weight in linked) / sum(weight for _, weight in linked)
        return (barycenter, cid)
    return sorted(layer_ids, key=score)


def _one_island(model: CircuitModel, group: tuple[str, ...],
                graph: dict[str, dict[str, float]]):
    source = next((cid for cid in sorted(group) if model.components[cid].kind in SOURCE_KINDS), None)
    depths = _net_depths(model, group, source)
    stages: dict[int, list[str]] = collections.defaultdict(list)
    geometry = {}
    for cid in group:
        comp, symbol = model.components[cid], model.symbols[cid]
        if cid == source:
            stage = 0
        else:
            distances = sorted(depths[n] for n in comp.pins.values())
            stage = 1 + distances[0] + distances[-1] if distances else 1
        stages[stage].append(cid)
        rot, mirror = _choose_orientation(comp, symbol, depths, cid == source)
        hw, hh, name_y, value_y = _geometry(symbol, comp, rot, mirror)
        if comp.kind in SOURCE_KINDS or len(symbol.pins) > 2 or rot in (90, 270):
            # Include relocated label space when computing layer spacing.
            measured = _place_at(model, cid, 0.0, 0.0, rot, mirror, True)
            hw, hh = measured.half_width, measured.half_height
        geometry[cid] = (rot, mirror, hw, hh, name_y, value_y)

    levels = sorted(stages)
    ordered = []
    previous: dict[str, int] = {}
    for stage in levels:
        cids = _layer_order(stages[stage], previous, graph)
        ordered.append(cids)
        previous = {cid: idx for idx, cid in enumerate(cids)} | previous

    # Each layer is spaced according to its widest part, not a fixed cell width.
    x_by_level = {}
    right = 0.0
    for idx, (stage, cids) in enumerate(zip(levels, ordered)):
        half_width = max(geometry[cid][2] for cid in cids)
        x = half_width if idx == 0 else right + COLUMN_GAP + half_width
        x_by_level[stage] = x
        right = x + half_width

    layout = {}
    for stage, cids in zip(levels, ordered):
        heights = [geometry[cid][3] for cid in cids]
        total = sum(2 * h for h in heights) + ROW_GAP * (len(cids) - 1)
        y = -total / 2
        for cid, half_height in zip(cids, heights):
            rot, mirror, hw, hh, name_y, value_y = geometry[cid]
            y += half_height
            x = x_by_level[stage]
            pins = pin_positions(model.symbols[cid], x, y, rot, mirror)
            if model.components[cid].kind in SOURCE_KINDS or len(model.symbols[cid].pins) > 2 or rot in (90, 270):
                layout[cid] = _place_at(model, cid, x, y, rotation=rot, mirror=mirror,
                                         side_label=True)
            else:
                layout[cid] = SymbolPlacement(cid, x, y, rot, mirror, hw, hh,
                                              pins, name_y, value_y)
            y += half_height + ROW_GAP
    return layout, [tuple(items) for items in ordered]


# RECOGNIZABLE CIRCUIT MOTIFS

def _place_at(model: CircuitModel, cid: str, x: float, y: float,
              rotation: int = 0, mirror: bool = False,
              side_label: bool = False) -> SymbolPlacement:
    symbol = model.symbols[cid]
    comp = model.components[cid]
    hw, hh, title_y, value_y = _geometry(symbol, comp, rotation, mirror)
    title_x = value_x = 0.0
    anchor = 'middle'
    if side_label:
        anchor = 'start'
        if len(symbol.pins) > 2:
            # Put IC metadata outside the body and *above* side-pin exit rows.
            # Centering metadata beside the IC blocks OUT/DISCH on the NE555.
            title_x = value_x = symbol.half_width + 2.0
            title_y = -symbol.half_height - 0.15
            value_y = title_y + 0.85
        else:
            # Vertical sources need both labels beside their terminal axis.
            title_x = value_x = 2.3
            title_y, value_y = -0.34, 0.74
        width = max(label_width(cid, 17, 10.5), label_width(comp.value, 13, 7.8))
        hw = max(hw, title_x + width / GRID_PX + 1.0)
        hh = max(hh, abs(title_y) + 1.0, abs(value_y) + 1.0)
    return SymbolPlacement(cid, x, y, rotation, mirror, hw, hh,
                           pin_positions(symbol, x, y, rotation, mirror),
                           title_y, value_y, title_x, value_x, anchor)


def _bridge_motif(model: CircuitModel):
    """Recognize a four-arm resistance bridge with a fifth midpoint connection.

    Derive roles from net connectivity, never component IDs or net names.
    Return (source, upper_left, lower_left, upper_right, lower_right, cross).
    """
    if len(model.components) != 6 or len(model.nets) != 4:
        return None
    sources = [c for c in model.components.values() if c.kind in SOURCE_KINDS]
    if len(sources) != 1 or set(sources[0].pins) != {'p', 'n'}:
        return None
    src = sources[0]
    positive, negative = src.pins['p'], src.pins['n']
    if positive == negative:
        return None
    arms = [c for c in model.components.values() if c.cid != src.cid]
    if len(arms) != 5 or any(c.kind not in {'resistor', 'inductor', 'capacitor'}
                             or len(c.pins) != 2 for c in arms):
        return None
    mids = set(model.nets) - {positive, negative}
    if len(mids) != 2:
        return None
    bridges = [c for c in arms if set(c.pins.values()) == mids]
    if len(bridges) != 1:
        return None
    bridge = bridges[0]
    branches = []
    for mid in mids:
        above = [c for c in arms if c.cid != bridge.cid and
                 set(c.pins.values()) == {positive, mid}]
        below = [c for c in arms if c.cid != bridge.cid and
                 set(c.pins.values()) == {mid, negative}]
        if len(above) != 1 or len(below) != 1:
            return None
        branches.append((above[0], below[0], mid))
    if len({part.cid for top, bottom, _ in branches for part in (top, bottom)}) != 4:
        return None
    branches.sort(key=lambda b: (b[0].cid, b[1].cid))
    return src.cid, branches[0][0].cid, branches[0][1].cid, \
        branches[1][0].cid, branches[1][1].cid, bridge.cid


def _bridge_placement(model: CircuitModel) -> Placement | None:
    match = _bridge_motif(model)
    if match is None:
        return None
    source, tl, bl, tr, br, cross = match
    # A conventional bridge: two vertical voltage-divider arms with
    # a horizontal midpoint bridge, and the supply to the left.
    pos = model.components[source].pins['p']
    left_mid = next(net for net in model.components[tl].pins.values() if net != pos)
    right_mid = next(net for net in model.components[tr].pins.values() if net != pos)

    def vertical(cid: str, upper_net: str) -> int:
        # Keep the upper terminal above the lower one even when a/b is reversed.
        return 90 if model.components[cid].pins['a'] == upper_net else 270

    cross_mirror = model.components[cross].pins['a'] != left_mid
    coordinates = {
        source: (-9.0, 0.0, 0, False, False),
        tl: (13.0, -13.0, vertical(tl, pos), False, True),
        bl: (13.0, 13.0, vertical(bl, left_mid), False, True),
        tr: (44.0, -13.0, vertical(tr, pos), False, True),
        br: (44.0, 13.0, vertical(br, right_mid), False, True),
        cross: (28.5, 0.0, 0, cross_mirror, False),
    }
    layout = {cid: _place_at(model, cid, *args)
              for cid, args in coordinates.items()}
    return Placement(layout, ((source,), (tl, bl), (cross,), (tr, br)),
                     (tuple(sorted(model.components)),))


def _controller_placement(model: CircuitModel) -> Placement | None:
    """Compact grouping for a single Arduino with one sensor and LED branch."""
    controls = [c for c in model.components.values() if c.kind == 'arduino_uno']
    sensors = [c for c in model.components.values() if c.kind not in SOURCE_KINDS
               and c.kind not in {'arduino_uno', 'resistor', 'led'}]
    resistors = [c for c in model.components.values() if c.kind == 'resistor']
    leds = [c for c in model.components.values() if c.kind == 'led']
    if (len(model.components) != 4 or len(controls) != 1 or len(sensors) != 1
            or len(resistors) != 1 or len(leds) != 1):
        return None
    ctrl, sensor, resistor, led = (controls[0].cid, sensors[0].cid,
                                   resistors[0].cid, leds[0].cid)
    nets = {net: set(pins) for net, pins in model.nets.items()}
    digital_pins = [pin for pin in model.components[ctrl].pins
                    if pin.startswith('D') and pin[1:].isdigit()]
    chain = None
    for drive in digital_pins:
        for r_pin in ('a', 'b'):
            if not any({f'{ctrl}.{drive}', f'{resistor}.{r_pin}'} <= pins
                       for pins in nets.values()):
                continue
            remaining_r = 'b' if r_pin == 'a' else 'a'
            for l_pin in ('a', 'b'):
                if any({f'{resistor}.{remaining_r}', f'{led}.{l_pin}'} <= pins
                       for pins in nets.values()):
                    chain = (drive, r_pin, l_pin)
                    break
            if chain:
                break
        if chain:
            break
    if not chain:
        return None
    drive, r_pin, l_pin = chain
    placed_ctrl = _place_at(model, ctrl, 0.0, 0.0)
    # The LED circuit belongs beside the selected Arduino digital pin,
    # regardless of which D-number drives it.
    drive_y = placed_ctrl.pin_positions[drive][1]
    layout = {
        ctrl: placed_ctrl,
        sensor: _place_at(model, sensor, 18.0, -4.0, 0, True),
        resistor: _place_at(model, resistor, -15.0, drive_y, 0, r_pin == 'a'),
        led: _place_at(model, led, -26.0, drive_y, 0, l_pin == 'a'),
    }
    return Placement(layout, ((led, resistor), (ctrl,), (sensor,)),
                     (tuple(sorted(model.components)),))




def _ic_neighborhood_placement(model: CircuitModel) -> Placement | None:
    """Connectivity-led placement around one multi-pin part, not a 555 template.

    Nearby parts are grouped by their shared *signal* nets. Power and ground
    are deliberately weak attraction forces, so they don't drag every part
    into the same crowded column. Second-hop parts follow their neighbor.
    All symbol positions and electrical connections remain unchanged.
    """
    controllers = [cid for cid, symbol in model.symbols.items() if len(symbol.pins) >= 3]
    if len(controllers) != 1 or len(model.components) > 28:
        return None
    ic = controllers[0]
    ic_part = model.components[ic]
    ic_symbol = model.symbols[ic]
    power_words = {'GND', 'VCC', 'VDD', 'VSS', '3V3', '5V', 'VIN', 'VBAT', 'AGND', 'DGND'}
    def signal_weight(net: str) -> float:
        if net.upper() in power_words:
            return 0.03
        return 1.0 / max(1, len(model.nets[net]) - 1)

    center = _place_at(model, ic, 0, 0, side_label=True)
    # Find which external side each connection naturally exits the central IC.
    ic_nets = collections.defaultdict(list)
    for pin, net in ic_part.pins.items():
        x, y = center.pin_positions[pin]
        if x < -ic_symbol.half_width - 0.05:
            side = 'left'
        elif x > ic_symbol.half_width + 0.05:
            side = 'right'
        elif y < -ic_symbol.half_height - 0.05:
            side = 'top'
        elif y > ic_symbol.half_height + 0.05:
            side = 'bottom'
        else:
            side = 'left' if x < 0 else 'right'
        ic_nets[net].append((side, x, y))

    direct = {}
    connected = collections.defaultdict(list)
    for net, refs in model.nets.items():
        parts = sorted({r.split('.', 1)[0] for r in refs})
        for part in parts:
            for other in parts:
                if part != other:
                    connected[part].append((other, net))
    for cid, part in model.components.items():
        if cid == ic or part.kind in SOURCE_KINDS:
            continue
        choices = []
        for own_pin, net in part.pins.items():
            for side, x, y in ic_nets.get(net, []):
                choices.append((signal_weight(net), side, y, own_pin, net))
        if any(weight >= 0.1 for weight, *_ in choices):
            choices = [choice for choice in choices if choice[0] >= 0.1]
            # Prefer signal pins to supply rails. For symmetric contact between
            # opposite sides, the source component's own pin order breaks ties.
            choices.sort(key=lambda item: (-item[0], {'right':0, 'left':1, 'top':2, 'bottom':3}[item[1]], item[4]))
            direct[cid] = choices[0][1:]

    assignments = {}
    for cid, (side, y, pin, net) in direct.items():
        assignments[cid] = (side, 1, y, pin, net)

    # Follow the shortest signal-connected chain from the IC for other parts.
    # A component with only power connections is still placed, but farther away.
    remaining = set(model.components) - set(assignments) - {ic}
    sources = {cid for cid in remaining if model.components[cid].kind in SOURCE_KINDS}
    remaining -= sources
    for _ in range(len(remaining) + 1):
        changed = False
        for cid in sorted(list(remaining)):
            options = []
            for neighbor, net in connected[cid]:
                if neighbor in assignments:
                    side, depth, y, _, _ = assignments[neighbor]
                    options.append((depth, -signal_weight(net), neighbor, side, y, net))
            if options:
                depth, _, neighbor, side, y, net = min(options)
                own_pin = next((pin for pin, n in model.components[cid].pins.items() if n == net), '')
                assignments[cid] = (side, depth + 1, y, own_pin, net)
                remaining.remove(cid)
                changed = True
        if not changed:
            break
    # Unconnected components have no meaningful side; put them in an outer column.
    for cid in sorted(remaining):
        assignments[cid] = ('right', 3, 0.0, '', '')

    groups = collections.defaultdict(list)
    for cid, (side, depth, preferred_y, near_pin, net) in assignments.items():
        # Horizontal two-pin parts are easiest to connect and keep their text clear.
        mirror = False
        if len(model.symbols[cid].pins) == 2 and near_pin in ('a', 'b'):
            mirror = (near_pin == 'b') if side == 'right' else (near_pin == 'a') if side == 'left' else False
        part = _place_at(model, cid, 0, 0, mirror=mirror)
        groups[(side, depth)].append((preferred_y, cid, part, mirror))

    items = {ic: center}
    side_width = {'left': center.half_width, 'right': center.half_width,
                  'top': center.half_width, 'bottom': center.half_width}
    max_layer = max((depth for side, depth in groups), default=1)
    for depth in range(1, max_layer + 1):
        for side in ('left', 'right', 'top', 'bottom'):
            batch = sorted(groups.get((side, depth), []), key=lambda t: (t[0], t[1]))
            if depth > 1:
                following = []
                for old_y, cid, part, mirror in batch:
                    neighbors = [(signal_weight(net), neighbor, net)
                                 for neighbor, net in connected[cid] if neighbor in items]
                    if neighbors:
                        _, neighbor, _ = max(neighbors)
                        old_y = items[neighbor].y
                    following.append((old_y, cid, part, mirror))
                batch = sorted(following, key=lambda t: (t[0], t[1]))
            if not batch:
                continue
            sizes = [t[2] for t in batch]
            if side in ('left', 'right'):
                max_half_w = max(p.half_width for p in sizes)
                offset = side_width[side] + 5.5 + max_half_w
                x = -offset if side == 'left' else offset
                side_width[side] = offset + max_half_w
                gap = 3.2
                heights = [p.half_height for p in sizes]
                total = sum(2*h for h in heights) + (len(batch)-1)*gap
                preferred_center = max(-20.0, min(20.0, sum(t[0] for t in batch)/len(batch)))
                cursor = preferred_center - total/2
                for (_, cid, part, mirror), h in zip(batch, heights):
                    y = cursor + h
                    items[cid] = _place_at(model, cid, x, y, mirror=mirror)
                    cursor += 2*h + gap
            else:
                # Top/bottom pin groups are laid out horizontally.
                max_half_h = max(p.half_height for p in sizes)
                offset = center.half_height + 8 + depth*10 + max_half_h
                y = -offset if side == 'top' else offset
                gap = 4.0
                widths = [p.half_width for p in sizes]
                total = sum(2*w for w in widths) + (len(batch)-1)*gap
                cursor = -total/2
                for (_, cid, part, mirror), w in zip(batch, widths):
                    x = cursor + w
                    items[cid] = _place_at(model, cid, x, y, mirror=mirror)
                    cursor += 2*w + gap

    # Sources are traditionally left of the circuitry, outside passive parts.
    for index, cid in enumerate(sorted(sources)):
        x = -side_width['left'] - 5.5 - _place_at(model, cid, 0, 0, side_label=True).half_width
        y = (index - (len(sources)-1)/2)*14
        items[cid] = _place_at(model, cid, x, y, side_label=True)

    # Aesthetic candidate must be physically well separated. Otherwise allow
    # the generic layered placer to handle unusual shapes and pinouts.
    for i, a in enumerate(items.values()):
        for b in list(items.values())[i+1:]:
            if (abs(a.x-b.x) < a.half_width+b.half_width+1 and
                    abs(a.y-b.y) < a.half_height+b.half_height+1):
                return None
    return Placement(items, (tuple(sorted(items)),), (tuple(sorted(items)),))


# --- Pin-aware functional grouping for circuits with multiple ICs/modules ---
# This deliberately uses connectivity and symbol pin geometry, not IC model names.
# A large host board/chip is the anchor; smaller modules sit beside the actual
# connected pins; resistor/LED/passive chains stay together on the same side.

def _supply_net_names(model: CircuitModel) -> frozenset[str]:
    names = {'GND', 'VCC', 'VDD', 'VSS', '3V3', '5V', 'VIN', 'VBAT',
             'AGND', 'DGND', 'PWR', 'GROUND'}
    result = set()
    for name, refs in model.nets.items():
        up = name.upper()
        if (up in names or up.startswith(('GND_', 'VCC_', 'VDD_', 'VSS_'))
                or up.endswith(('_GND', '_VCC', '_RAIL'))):
            result.add(name)
            continue
        for ref in refs:
            cid, pin = ref.split('.', 1)
            if (model.components[cid].kind in SOURCE_KINDS
                    and pin in {'p', 'n'}) or pin.upper() in names:
                result.add(name)
                break
    return frozenset(result)


def _functional_multiblock_placement(model: CircuitModel) -> Placement | None:
    """Arrange host, peripherals and local signal chains by *actual pin rows*.

    This is geometry-only. It never edits net identities or physical pin
    names, and the caller must route + verify any candidate before rendering.
    When connectivity is too ambiguous or dense, fall back to general layout.
    """
    if not 4 <= len(model.components) <= 18:
        return None
    multi = [cid for cid, symbol in model.symbols.items()
             if len(symbol.pins) >= 3 and model.components[cid].kind not in SOURCE_KINDS]
    if len(multi) < 2:
        return None
    supply = _supply_net_names(model)
    # The largest-pin device is usually a board/controller, regardless of its
    # name. Favor actual signal degree as a secondary signal.
    def rank(cid):
        p = model.components[cid]
        return (len(model.symbols[cid].pins),
                sum(net not in supply for net in p.pins.values()), cid)
    root = max(multi, key=rank)
    active = model.components[root].pins
    root_nets = collections.defaultdict(list)
    for pin, net in active.items():
        if net not in supply:
            root_nets[net].append(pin)
    if not root_nets:
        return None
    # Avoid metadata on the same side as all output leads unless the symbol
    # actually has top/bottom pins to protect (e.g. a 555 timer).
    rootsym = model.symbols[root]
    tall_pin = any(abs(pin.y) > rootsym.half_height+0.05
                   for pin in rootsym.pins if pin.name in active)
    host = _place_at(model, root, 0.0, 0.0, side_label=tall_pin)
    layout = {root: host}

    def overlaps(a, b, gap=1.35):
        return (abs(a.x-b.x) < a.half_width+b.half_width+gap and
                abs(a.y-b.y) < a.half_height+b.half_height+gap)

    def clear(item, gap=1.35):
        return all(not overlaps(item, other, gap) for other in layout.values())

    # Place every smaller multi-pin module alongside the host pins it actually
    # uses; search mirrors / 180° orientations to face connected leads inward.
    # Prevent unrelated power rails from driving the placement.
    pending_modules = set(multi)-{root}
    if len(pending_modules) > 5:
        return None
    for cid in sorted(pending_modules,
                      key=lambda c: (-sum(net in root_nets for net in
                                           model.components[c].pins.values()), c)):
        links = [(hostpin, pin) for pin, net in model.components[cid].pins.items()
                 if net in root_nets for hostpin in root_nets[net]]
        if not links:
            # Can't associate an independently attached module with this host.
            return None
        xs = [host.pin_positions[p][0]-host.x for p, _ in links]
        ys = [host.pin_positions[p][1]-host.y for p, _ in links]
        side = 'right' if abs(sum(xs)) >= abs(sum(ys))*0.35 and sum(xs)>=0 else \
               'left' if abs(sum(xs)) >= abs(sum(ys))*0.35 else \
               'bottom' if sum(ys)>=0 else 'top'
        choices = []
        for rot, mirror in ((0, False), (0, True), (180, False), (180, True)):
            probe = _place_at(model, cid, 0, 0, rot, mirror, False)
            if side in ('left','right'):
                sign = 1 if side == 'right' else -1
                x = sign*(host.half_width + probe.half_width + 2.0)
                y = sum(host.pin_positions[h][1]-probe.pin_positions[q][1]
                        for h,q in links)/len(links)
            else:
                sign = 1 if side == 'bottom' else -1
                y = sign*(host.half_height + probe.half_height + 3.0)
                x = sum(host.pin_positions[h][0]-probe.pin_positions[q][0]
                        for h,q in links)/len(links)
            # Try small alternate slots when another module already occupies
            # the preferred position.
            for shift in (0, 10, -10, 20, -20):
                xx, yy = (x, y+shift) if side in ('left','right') else (x+shift, y)
                item = _place_at(model, cid, round(xx*2)/2, round(yy*2)/2,
                                 rot, mirror, False)
                if not clear(item):
                    continue
                length = sum(abs(host.pin_positions[h][0]-item.pin_positions[q][0]) +
                             abs(host.pin_positions[h][1]-item.pin_positions[q][1])
                             for h,q in links)
                # Prefer leads facing each other instead of looping around the
                # back of a module. Small penalty for mirror/rotation complexity.
                facing = sum(max(0, (item.pin_positions[q][0]-item.x)*(1 if side=='right' else -1))
                             for _,q in links) if side in ('left','right') else 0
                score = length + 3*facing + 0.25*abs(shift) + (0.5 if mirror else 0) + (0.8 if rot else 0)
                choices.append((score, cid, item))
        if not choices:
            return None
        layout[cid] = min(choices, key=lambda row: (row[0],row[2].x,row[2].y))[2]

    # For remaining two-terminal components, form signal-connected chains from
    # the anchor(s). This is not a resistor/LED template: every 2-pin part gets
    # the same treatment, and diode orientation follows its actual pin mapping.
    pending = {cid for cid in model.components if cid not in layout and
               model.components[cid].kind not in SOURCE_KINDS}
    if any(len(model.symbols[cid].pins) != 2 for cid in pending):
        return None
    for _ in range(len(pending)+1):
        progress = False
        for cid in sorted(pending):
            links = []
            for pin, net in model.components[cid].pins.items():
                if net in supply:
                    continue
                for neighbor, placed in layout.items():
                    for npin, nnet in model.components[neighbor].pins.items():
                        if nnet == net:
                            pos=placed.pin_positions[npin]
                            links.append((neighbor, pin, pos, net))
            if not links:
                continue
            # A link to an IC establishes the visual side. For a signal chain,
            # follow the already placed upstream part toward its outer side.
            links.sort(key=lambda row: (row[0] != root, row[0] not in multi, row[0]))
            neighbor, attach_pin, pos, net = links[0]
            base = layout[neighbor]
            if neighbor == root:
                side = 'left' if pos[0] < base.x else 'right'
            elif neighbor in multi:
                side = 'left' if pos[0] < base.x else 'right'
            else:
                side = 'left' if base.x < host.x else 'right'
            choices = []
            for mirror in (False, True):
                test = _place_at(model, cid, 0, 0, mirror=mirror, side_label=False)
                # Keep short local nets between component terminals.
                spacing = base.half_width + test.half_width + 2.2
                ideal_x = base.x + spacing*(1 if side == 'right' else -1)
                ideal_y = pos[1] - test.pin_positions[attach_pin][1]
                for offset in (0, -8, 8, -16, 16):
                    item = _place_at(model, cid, round(ideal_x*2)/2,
                                     round((ideal_y+offset)*2)/2, mirror=mirror)
                    if not clear(item):
                        continue
                    distance = abs(pos[0]-item.pin_positions[attach_pin][0]) + \
                               abs(pos[1]-item.pin_positions[attach_pin][1])
                    # Assign local chains to clear lanes; avoid pushing parts
                    # across their parent on a different side of the host.
                    choices.append((distance+0.5*abs(offset), item.x, item.y, item))
            if choices:
                layout[cid] = min(choices, key=lambda row: row[:3])[3]
                pending.remove(cid)
                progress = True
        if not progress:
            break
    if pending:
        return None

    # Position sources near the host on the left, but away from outgoing signal
    # branches. Their shared power connections are routed or named later.
    source_ids = [cid for cid in sorted(model.components)
                  if model.components[cid].kind in SOURCE_KINDS]
    for i, cid in enumerate(source_ids):
        probe = _place_at(model, cid, 0, 0, side_label=True)
        left = host.x-host.half_width
        x = round((left-probe.half_width-2.5)*2)/2
        for y in (-host.half_height+2.5 + 10*i, host.half_height+4 + 10*i,
                  -host.half_height-12-10*i, 0):
            item = _place_at(model, cid, x, round(y*2)/2, side_label=True)
            if clear(item):
                layout[cid] = item
                break
        else:
            return None
    if len(layout) != len(model.components):
        return None
    return Placement(layout, (tuple(sorted(layout)),), (tuple(sorted(layout)),))


def place_model(model: CircuitModel, *, _skip_functional: bool = False) -> Placement:
    """Place components deterministically; permit legacy general-layout fallback."""
    specialized = _bridge_placement(model)
    if specialized is not None:
        return specialized
    specialized = _controller_placement(model)
    if specialized is not None:
        return specialized
    if not _skip_functional:
        specialized = _functional_multiblock_placement(model)
        if specialized is not None:
            return specialized
    specialized = _ic_neighborhood_placement(model)
    if specialized is not None:
        return specialized
    graph = _component_graph(model)
    groups = _islands(graph)
    items = {}
    layers = []
    island_y = 0.0
    for group in groups:
        partial, partial_layers = _one_island(model, group, graph)
        top = min(p.y - p.half_height for p in partial.values())
        bottom = max(p.y + p.half_height for p in partial.values())
        shift = island_y - top
        for cid, p in partial.items():
            items[cid] = dataclasses.replace(
                p, y=p.y + shift,
                pin_positions={pin: (x, y + shift) for pin, (x, y) in p.pin_positions.items()})
        island_y += bottom - top + ISLAND_GAP
        layers.extend(partial_layers)

    # Reject any accidental symbol/label bounding-box overlap at placement time.
    for i, cid in enumerate(sorted(items)):
        a = items[cid]
        for oid in sorted(items)[i + 1:]:
            b = items[oid]
            if (abs(a.x - b.x) < a.half_width + b.half_width - 1e-8 and
                    abs(a.y - b.y) < a.half_height + b.half_height - 1e-8):
                raise ValueError(f"Placement collision between {cid} and {oid}")
    return Placement(items, tuple(layers), tuple(groups))



# --- General connectivity-aware schematic organization ---
# These candidates never edit the circuit graph or alter the pins within a
# symbol. A candidate is only useful if the router subsequently verifies it.

def _translated(item: SymbolPlacement, x: float, y: float) -> SymbolPlacement:
    x, y = round(x * 2) / 2, round(y * 2) / 2
    dx, dy = x - item.x, y - item.y
    return dataclasses.replace(
        item, x=x, y=y,
        pin_positions={name: (round(px + dx, 6), round(py + dy, 6))
                       for name, (px, py) in item.pin_positions.items()})


def _has_space(candidate: SymbolPlacement, items: dict[str, SymbolPlacement],
               *, gap: float = 1.0) -> bool:
    for other in items.values():
        if other.cid == candidate.cid:
            continue
        if (abs(candidate.x - other.x) < candidate.half_width + other.half_width + gap
                and abs(candidate.y - other.y) < candidate.half_height + other.half_height + gap):
            return False
    return True


def _weighted_neighbors(model: CircuitModel) -> dict[str, dict[str, float]]:
    # Ground/supply rails are global connectivity, not a reason to put all
    # components next to each other. Actual signal nets have stronger pull.
    supplies = {'GND', 'VCC', 'VDD', 'VSS', '3V3', '5V', 'VIN',
                'VBAT', 'AGND', 'DGND', 'PWR'}
    graph = {cid: {} for cid in model.components}
    for name, refs in model.nets.items():
        cids = sorted({ref.split('.', 1)[0] for ref in refs})
        if len(cids) < 2:
            continue
        weight = (0.035 if name.upper() in supplies else 1.0) / (len(cids)-1)
        for i, a in enumerate(cids):
            for b in cids[i+1:]:
                graph[a][b] = graph[a].get(b, 0) + weight
                graph[b][a] = graph[b].get(a, 0) + weight
    return graph


def _relax_connections(model: CircuitModel, placement: Placement,
                       passes: int = 2) -> Placement:
    """Shorten local signal connections without changing pin orientation.

    Weighted-coordinate relaxation is deliberately conservative: major ICs
    remain anchors, sources stay to the left, and every move respects full
    symbol/label bounding boxes. The renderer will re-route and reject any
    candidate that cannot be connected without crossings.
    """
    graph = _weighted_neighbors(model)
    items = dict(placement.symbols)
    anchors = {cid for cid, symbol in model.symbols.items() if len(symbol.pins) >= 3}
    # Leave disconnected islands in their current relative positions.
    for _ in range(passes):
        for cid in sorted(items, key=lambda cid: (cid in anchors,
                                                  model.components[cid].kind in SOURCE_KINDS, cid)):
            if cid in anchors or not graph[cid]:
                continue
            item = items[cid]
            # Ignore global power nets when possible.
            neighbors = [(items[k], w) for k, w in graph[cid].items() if w >= 0.15]
            if not neighbors:
                continue
            total = sum(weight for _, weight in neighbors)
            target_x = sum(part.x * weight for part, weight in neighbors) / total
            target_y = sum(part.y * weight for part, weight in neighbors) / total
            if model.components[cid].kind in SOURCE_KINDS:
                target_x = min(target_x - 9, item.x + 4)
            # Stay on the same side of a dominant IC to preserve signal flow.
            if len(anchors) == 1 and cid not in anchors:
                central = items[next(iter(anchors))]
                if item.x < central.x - central.half_width:
                    target_x = min(target_x, central.x - central.half_width - item.half_width - 4)
                elif item.x > central.x + central.half_width:
                    target_x = max(target_x, central.x + central.half_width + item.half_width + 4)
            # Try the locally cheapest step first. A half-grid quantization
            # ensures the router and SVG have stable deterministic coordinates.
            dx = max(-4.0, min(4.0, target_x-item.x))
            dy = max(-3.5, min(3.5, target_y-item.y))
            trials = ((item.x+dx, item.y+dy), (item.x+dx, item.y),
                      (item.x, item.y+dy), (item.x+dx*.5, item.y+dy*.5))
            def objective(x, y):
                return sum(weight * (abs(x-other.x) + abs(y-other.y))
                           for other, weight in neighbors)
            current_score = objective(item.x, item.y)
            options = []
            for x, y in trials:
                proposed = _translated(item, x, y)
                if _has_space(proposed, items):
                    score = objective(proposed.x, proposed.y)
                    if score < current_score - 0.05:
                        options.append((score, abs(x-item.x)+abs(y-item.y), proposed))
            if options:
                _, _, best = min(options, key=lambda row: (row[0], row[1], row[2].x, row[2].y))
                items[cid] = best
    return dataclasses.replace(placement, symbols=items)


def _scale_centers(placement: Placement, factor_x: float, factor_y: float) -> Placement | None:
    # Compact global whitespace, never resize an electrical symbol.
    xs = [p.x for p in placement.symbols.values()]
    ys = [p.y for p in placement.symbols.values()]
    cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
    items = {}
    for cid, item in sorted(placement.symbols.items()):
        next_item = _translated(item, cx + (item.x-cx)*factor_x,
                                cy + (item.y-cy)*factor_y)
        if not _has_space(next_item, items, gap=1.0):
            return None
        items[cid] = next_item
    return dataclasses.replace(placement, symbols=items)


def _compact_channels(placement: Placement) -> Placement:
    items = placement.symbols.copy()
    for axis, half_size in (('x', 'half_width'), ('y', 'half_height')):
        bands = sorted((getattr(item, axis) - getattr(item, half_size),
                        getattr(item, axis) + getattr(item, half_size), item.cid)
                       for item in items.values())
        right = bands[0][1]
        shift = 0.0
        for left, end, cid in bands:
            # Keep the same offset within each occupied band, including aligned pins.
            shift += max(0, math.floor((left - right - 2.5) * 2)) / 2
            right = max(right, end)
            if not shift:
                continue
            item = items[cid]
            dx, dy = (-shift, 0) if axis == 'x' else (0, -shift)
            items[cid] = dataclasses.replace(
                item, x=item.x + dx, y=item.y + dy,
                pin_positions={pin: (round(x + dx, 6), round(y + dy, 6))
                               for pin, (x, y) in item.pin_positions.items()},
            )
    ordered = list(items.values())
    for index, item in enumerate(ordered):
        if not _has_space(item, {other.cid: other for other in ordered[:index]}, gap=0):
            return placement
    return dataclasses.replace(placement, symbols=items)


def _compact_around_primary(model: CircuitModel, placement: Placement) -> Placement | None:
    """Pack component columns around a dominant IC, preserving pin orientations.

    A netlist with one large controller and passive/sensor satellites usually
    benefits from narrower horizontal channels and evenly packed vertical
    columns. This is only a *proposal*: routing and display verification must
    still succeed before it can be selected.
    """
    if len(placement.symbols) < 3 or len(placement.symbols) > 18:
        return None
    ranked = sorted(model.symbols, key=lambda cid: -len(model.symbols[cid].pins))
    host = ranked[0]
    if len(model.symbols[host].pins) < 4:
        return None
    if len(ranked) > 1 and len(model.symbols[ranked[1]].pins) >= len(model.symbols[host].pins):
        return None
    anchor = placement.symbols[host]
    groups = {'left': [], 'right': []}
    for cid, item in placement.symbols.items():
        if cid == host:
            continue
        if item.x + item.half_width < anchor.x - anchor.half_width:
            groups['left'].append(item)
        elif item.x - item.half_width > anchor.x + anchor.half_width:
            groups['right'].append(item)
        else:
            # Preserve less-standard top/bottom-connected devices.
            return None
    if not any(groups.values()):
        return None

    items = dict(placement.symbols)
    for side, members in groups.items():
        if not members:
            continue
        # Find columns from existing geometry without using component IDs,
        # component kinds, or special-case circuit topologies.
        columns = []
        for item in sorted(members, key=lambda p: (abs(p.x-anchor.x), p.y)):
            if columns and abs(item.x-columns[-1][0].x) < 2.7:
                columns[-1].append(item)
            else:
                columns.append([item])

        boundary = anchor.half_width
        for depth, batch in enumerate(columns):
            half_width = max(part.half_width for part in batch)
            gap = 2.2 if depth == 0 else 1.4
            center_distance = boundary + gap + half_width
            next_x = anchor.x + center_distance * (1 if side == 'right' else -1)
            boundary = center_distance + half_width

            batch = sorted(batch, key=lambda p: (p.y, p.cid))
            if len(batch) == 1:
                centers = [batch[0].y]
            else:
                # Reduce excess vertical gaps without changing component order.
                heights = [part.half_height for part in batch]
                total = sum(2*h for h in heights) + (len(batch)-1)*1.15
                mid = sum(part.y for part in batch)/len(batch)
                cursor = mid - total/2
                centers = []
                for half_height in heights:
                    centers.append(cursor + half_height)
                    cursor += 2*half_height + 1.15
            for part, next_y in zip(batch, centers):
                items[part.cid] = _translated(part, next_x, next_y)

    ordered = list(items.values())
    for i, a in enumerate(ordered):
        for b in ordered[i+1:]:
            if (abs(a.x-b.x) < a.half_width+b.half_width+0.7 and
                    abs(a.y-b.y) < a.half_height+b.half_height+0.7):
                return None
    return dataclasses.replace(placement, symbols=items)


def layout_candidates(model: CircuitModel, baseline: Placement):
    """Yield alternative deterministic layouts for any recognized netlist.

    Keep the original as the first candidate. The caller MUST re-route and
    electrically verify each candidate before it can be selected.
    """
    yield baseline
    if len(model.components) < 2:
        return
    seen = {tuple((cid, p.x, p.y) for cid, p in sorted(baseline.symbols.items()))}
    compact = _compact_channels(baseline)
    alternatives = () if len(model.components) > 18 else (
        _compact_around_primary(model, baseline),
        _relax_connections(model, baseline, 2),
        _scale_centers(baseline, .86, 1.0),
        _scale_centers(baseline, 1.0, .86),
        _scale_centers(baseline, .90, .90),
    )
    for candidate in (compact, *alternatives):
        if candidate is None:
            continue
        fingerprint = tuple((cid, p.x, p.y) for cid, p in sorted(candidate.symbols.items()))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        yield candidate


def _net_guides(model: CircuitModel, placement: Placement):
    """Spanning connections for visualization only; never treat as real wires."""
    for name in sorted(model.nets):
        pins = sorted(model.nets[name])
        positions = []
        for ref in pins:
            cid, pin = ref.split(".", 1)
            positions.append(placement.symbols[cid].pin_positions[pin])
        if len(positions) <= 1:
            continue
        covered = {0}
        while len(covered) < len(positions):
            _, a, b = min((abs(positions[i][0] - positions[j][0]) +
                            abs(positions[i][1] - positions[j][1]), i, j)
                           for i in sorted(covered) for j in range(len(positions)) if j not in covered)
            covered.add(b)
            yield name, positions[a], positions[b]


def make_placement_preview_svg(model: CircuitModel) -> str:
    """Draw symbol placements and light dashed connectivity hints (not a schematic)."""
    placement = place_model(model)
    all_p = list(placement.symbols.values())
    min_x = min(p.x - p.half_width for p in all_p) * GRID_PX - 26
    max_x = max(p.x + p.half_width for p in all_p) * GRID_PX + 26
    min_y = min(p.y - p.half_height for p in all_p) * GRID_PX - 65
    max_y = max(p.y + p.half_height for p in all_p) * GRID_PX + 32
    width, height = max_x - min_x, max_y - min_y

    def pt(p):
        return (p[0] * GRID_PX - min_x, p[1] * GRID_PX - min_y)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.1f} {height:.1f}" width="{width:.1f}" height="{height:.1f}">',
        '<title>CircuitGen placement preview — NOT a wired schematic</title>',
        '<desc>Dashed lines indicate shared nets, not verified electrical wires. Routing is not implemented here.</desc>',
        '<style><![CDATA[',
        '.symbol{fill:none;stroke:#213149;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round}',
        '.mark{fill:#213149;font-family:Arial,sans-serif;font-size:16px;text-anchor:middle}',
        '.name{fill:#17243c;font-family:Arial,sans-serif;font-size:17px;font-weight:700;text-anchor:middle}',
        '.value{fill:#3e506d;font-family:Arial,sans-serif;font-size:13px;text-anchor:middle}',
        '.pin{fill:#394b66;font-family:Arial,sans-serif;font-size:10px}',
        '.guide{stroke:#869bb4;stroke-width:1.8;stroke-dasharray:5 7;opacity:.60}',
        '.endpoint{fill:#4c6988}',
        '.hint{font-family:Arial,sans-serif;font-size:13px;fill:#6e7f93}',
        ']]></style>',
        '<text class="hint" x="18" y="27">PLACEMENT PREVIEW · dashed lines are NOT electrical wires</text>',
    ]
    for name, start, end in _net_guides(model, placement):
        x1, y1 = pt(start)
        x2, y2 = pt(end)
        out.append(f'<line class="guide" data-net="{_xml(name)}" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>')

    for cid in sorted(placement.symbols):
        item = placement.symbols[cid]
        comp = model.components[cid]
        symbol = model.symbols[cid]
        cx, cy = pt((item.x, item.y))
        out.append(f'<g data-component="{_xml(cid)}" data-type="{_xml(comp.kind)}">')
        out.append(symbol_body_svg(symbol, cx, cy, item.rotation, item.mirror))
        out.append(f'<text class="name" x="{cx+item.title_x*GRID_PX:.2f}" y="{cy + item.title_y*GRID_PX:.2f}" text-anchor="{item.label_anchor}">{_xml(cid)}</text>')
        if comp.value:
            out.append(f'<text class="value" x="{cx+item.value_x*GRID_PX:.2f}" y="{cy + item.value_y*GRID_PX:.2f}" text-anchor="{item.label_anchor}">{_xml(comp.value)}</text>')
        for pin, (x, y) in item.pin_positions.items():
            px, py = pt((x, y))
            out.append(f'<circle class="endpoint" data-pin="{_xml(pin)}" cx="{px:.2f}" cy="{py:.2f}" r="3"/>')
        if len(symbol.pins) > 2:
            for label, lx, ly, anchor, _, _, _ in symbol_pin_labels(symbol, item.rotation, item.mirror):
                out.append(f'<text class="pin" text-anchor="{anchor}" x="{cx+lx:.2f}" y="{cy+ly:.2f}">{_xml(label)}</text>')
        out.append('</g>')
    out.append('</svg>')
    return '\n'.join(out) + '\n'


# LOCAL PREVIEW COMMAND

if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Preview component placement (no electrical wire routing)")
    parser.add_argument("netlist", type=Path, help="JSON netlist file")
    parser.add_argument("output", type=Path, help="Destination SVG file")
    args = parser.parse_args()
    from .engine import validate_model

    raw = json.loads(args.netlist.read_text(encoding="utf-8"))
    result = make_placement_preview_svg(validate_model(raw))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding="utf-8")
    print(f"Saved placement preview: {args.output}")
