from __future__ import annotations

import collections
import dataclasses
import math
import re
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from .symbols import BUILTIN_SYMBOLS, SymbolSpec, get_symbol, label_width
from .values import format_component_value

# CONFIG

MAX_COMPONENTS = 24
MAX_NETS = 30
GRID_PX = 23
LEAF_WIDTH = 6
LEAF_UP = LEAF_DOWN = 3
BRANCH_X_PAD = 2
BRANCH_Y_GAP = 2
SOURCE_X_GAP = 5
SOURCE_SYMBOL_HALF_HEIGHT = 2
MARGIN = 2.2

VALID_TYPES = {
    "resistor", "capacitor", "inductor", "diode", "led",
    "switch", "lamp", "fuse", "battery", "dc_source",
}
SOURCE_TYPES = {"battery", "dc_source"}

# COMPONENTS
# GENERAL CIRCUIT MODEL

@dataclasses.dataclass(frozen=True)
class PartDefinition:
    kind: str
    terminals: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class CircuitModel:
    components: dict[str, Component]
    nets: dict[str, tuple[str, ...]]
    symbols: dict[str, SymbolSpec] = dataclasses.field(default_factory=dict)


PARTS: dict[str, PartDefinition] = {
    kind: PartDefinition(kind, symbol.pin_names)
    for kind, symbol in BUILTIN_SYMBOLS.items()
}

ID_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}\Z")
PIN_PATTERN = re.compile(r"[A-Za-z0-9_+\\-]{1,24}\Z")


def validate_model(raw: dict[str, Any]) -> CircuitModel:
    """Validate a general connectivity model without requiring a drawable layout.

    Components can use built-in definitions or an explicit pins list. Explicit
    pins describe an instance's pin names, not a verified physical pinout.
    """
    if not isinstance(raw, dict) or set(raw) != {"components", "nets"}:
        raise CircuitError("Netlist must contain exactly components and nets")
    rows, net_rows = raw["components"], raw["nets"]
    if not isinstance(rows, list) or not isinstance(net_rows, list):
        raise CircuitError("components and nets must both be arrays")
    if not 1 <= len(rows) <= 256 or not 1 <= len(net_rows) <= 512:
        raise CircuitError("Expected 1–256 components and 1–512 nets")

    definitions = {}
    symbols: dict[str, SymbolSpec] = {}
    for row in rows:
        if not isinstance(row, dict) or not {"id", "type", "value"} <= set(row) or set(row) - {"id", "type", "value", "pins"}:
            raise CircuitError("Component requires id, type, value, and optional pins")
        cid, kind, value = row["id"], row["type"], row["value"]
        if not isinstance(cid, str) or not ID_PATTERN.fullmatch(cid):
            raise CircuitError(f"Invalid component ID: {cid!r}")
        if cid in definitions:
            raise CircuitError(f"Duplicate component ID: {cid}")
        if not isinstance(kind, str) or not ID_PATTERN.fullmatch(kind):
            raise CircuitError(f"Invalid component type: {kind!r}")
        if not isinstance(value, str) or len(value) > 100 or any(ord(c) < 32 for c in value):
            raise CircuitError(f"Invalid component value: {cid}")
        pins = row.get("pins")
        if pins is None:
            if kind not in PARTS:
                raise CircuitError(f"Unknown component type {kind!r}; provide its pins explicitly")
            pins = list(PARTS[kind].terminals)
        if not isinstance(pins, list) or not 1 <= len(pins) <= 128:
            raise CircuitError(f"Invalid pin list for {cid}")
        if any(not isinstance(pin, str) or not PIN_PATTERN.fullmatch(pin) for pin in pins):
            raise CircuitError(f"Invalid pin name for {cid}")
        if len(pins) != len(set(pins)):
            raise CircuitError(f"Duplicate pin name on {cid}")
        try:
            symbols[cid] = get_symbol(kind, pins)
        except ValueError as error:
            raise CircuitError(f"Invalid symbol for {cid}: {error}") from error
        definitions[cid] = (kind, value, tuple(pins))

    nets = {}
    pin_to_net = {}
    for row in net_rows:
        if not isinstance(row, dict) or set(row) != {"name", "pins"}:
            raise CircuitError("Each net requires name and pins")
        name, refs = row["name"], row["pins"]
        if not isinstance(name, str) or not ID_PATTERN.fullmatch(name):
            raise CircuitError(f"Invalid net name: {name!r}")
        if name in nets:
            raise CircuitError(f"Duplicate net: {name}")
        if not isinstance(refs, list) or not refs:
            raise CircuitError(f"Net {name} must contain at least one pin")
        for ref in refs:
            if not isinstance(ref, str) or ref.count(".") != 1:
                raise CircuitError(f"Invalid terminal reference: {ref!r}")
            cid, pin = ref.split(".")
            if cid not in definitions:
                raise CircuitError(f"Unknown component: {cid}")
            if pin not in definitions[cid][2]:
                raise CircuitError(f"Unknown terminal: {ref}")
            if ref in pin_to_net:
                raise CircuitError(f"Pin assigned more than once: {ref}")
            pin_to_net[ref] = name
        nets[name] = tuple(refs)

    components = {}
    for cid, (kind, value, pins) in definitions.items():
        mapping = {pin: pin_to_net[f"{cid}.{pin}"]
                   for pin in pins if f"{cid}.{pin}" in pin_to_net}
        components[cid] = Component(cid, kind, format_component_value(kind, value), mapping)
    return CircuitModel(components, nets, symbols)



class CircuitError(Exception):
    """Reject invalid/unrenderable circuits rather than inventing connections."""


@dataclasses.dataclass(frozen=True)
class Component:
    cid: str
    kind: str
    value: str
    pins: dict[str, str]


@dataclasses.dataclass(frozen=True)
class Circuit:
    components: dict[str, Component]
    nets: dict[str, tuple[str, ...]]
    source: str


@dataclasses.dataclass(frozen=True)
class Network:
    kind: str  # leaf / series / parallel
    u: str
    v: str
    cid: str = ""
    kids: tuple["Network", ...] = ()


@dataclasses.dataclass(frozen=True)
class Size:
    width: int
    up: int
    down: int
    branch_offsets: tuple[int, ...] = ()


Point = tuple[int, int]


@dataclasses.dataclass
class Placed:
    cid: str
    x: int
    y: int
    orientation: str  # 'right', 'left', 'down' for source
    terminals: dict[str, Point]


@dataclasses.dataclass
class Ink:
    wires: list[tuple[str, tuple[Point, ...]]] = dataclasses.field(default_factory=list)
    placed: dict[str, Placed] = dataclasses.field(default_factory=dict)

    def wire(self, net: str, *points: Point) -> None:
        if len(points) < 2:
            raise CircuitError("Internal error: wire has fewer than two points")
        a = tuple(points)
        for p, q in zip(a, a[1:]):
            if p[0] != q[0] and p[1] != q[1]:
                raise CircuitError(f"Internal error: diagonal wire {p} to {q}")
        if any(p != q for p, q in zip(a, a[1:])):
            self.wires.append((net, a))



# VALIDATION / LAYOUT / SVG



def validate(raw: dict[str, Any]) -> Circuit:
    if not isinstance(raw, dict):
        raise CircuitError("Netlist must be a JSON object")
    if set(raw) != {"components", "nets"}:
        raise CircuitError("Netlist must contain exactly components and nets")
    rows, net_rows = raw["components"], raw["nets"]
    if not isinstance(rows, list) or not isinstance(net_rows, list):
        raise CircuitError("components and nets must both be arrays")
    if not 2 <= len(rows) <= MAX_COMPONENTS:
        raise CircuitError(f"Expected 2–{MAX_COMPONENTS} supported components")
    if not 2 <= len(net_rows) <= MAX_NETS:
        raise CircuitError(f"Expected 2–{MAX_NETS} electrical nets")

    definitions: dict[str, tuple[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "type", "value"}:
            raise CircuitError("Each component requires id, type, and value")
        cid, kind, value = row["id"], row["type"], row["value"]
        if not isinstance(cid, str) or not ID_PATTERN.fullmatch(cid):
            raise CircuitError(f"Invalid component ID: {cid!r}")
        if cid in definitions:
            raise CircuitError(f"Duplicate component ID: {cid}")
        if not isinstance(kind, str) or kind not in VALID_TYPES:
            raise CircuitError(f"Unsupported component type {kind!r} ({cid})")
        if not isinstance(value, str) or len(value) > 28 or any(ord(c) < 32 for c in value):
            raise CircuitError(f"Invalid/overlong value for {cid}")
        definitions[cid] = (kind, value)

    sources = [cid for cid, (kind, _) in definitions.items() if kind in SOURCE_TYPES]
    if len(sources) != 1:
        raise CircuitError("This version requires exactly ONE battery/DC voltage source")

    nets: dict[str, tuple[str, ...]] = {}
    pin_to_net: dict[str, str] = {}
    for row in net_rows:
        if not isinstance(row, dict) or set(row) != {"name", "pins"}:
            raise CircuitError("Each net requires name and pins")
        name, pins = row["name"], row["pins"]
        if not isinstance(name, str) or not ID_PATTERN.fullmatch(name):
            raise CircuitError(f"Invalid net name: {name!r}")
        if name in nets:
            raise CircuitError(f"Duplicate net: {name}")
        if not isinstance(pins, list) or len(pins) < 2:
            raise CircuitError(f"Net {name} is dangling (fewer than 2 pins)")
        if any(not isinstance(pin, str) for pin in pins):
            raise CircuitError(f"Net {name} contains a non-string terminal reference")
        if len(pins) != len(set(pins)):
            raise CircuitError(f"Net {name} contains a repeated terminal")
        for pin in pins:
            if not isinstance(pin, str) or pin.count(".") != 1:
                raise CircuitError(f"Invalid terminal reference: {pin!r}")
            cid, terminal = pin.split(".")
            if cid not in definitions:
                raise CircuitError(f"Ghost component referenced: {cid}")
            kind = definitions[cid][0]
            expected = ("p", "n") if kind in SOURCE_TYPES else ("a", "b")
            if terminal not in expected:
                raise CircuitError(f"Unknown terminal {pin}; expected {expected}")
            if pin in pin_to_net:
                raise CircuitError(f"Terminal {pin} assigned to multiple nets")
            pin_to_net[pin] = name
        nets[name] = tuple(pins)

    components: dict[str, Component] = {}
    for cid, (kind, value) in definitions.items():
        names = ("p", "n") if kind in SOURCE_TYPES else ("a", "b")
        for terminal in names:
            if f"{cid}.{terminal}" not in pin_to_net:
                raise CircuitError(f"Disconnected terminal: {cid}.{terminal}")
        p = {t: pin_to_net[f"{cid}.{t}"] for t in names}
        if p[names[0]] == p[names[1]]:
            raise CircuitError(f"{cid} has both pins on the same net (shorted/bypassed)")
        components[cid] = Component(cid, kind, value, p)

    adj: dict[str, set[str]] = {name: set() for name in nets}
    for c in components.values():
        u, v = list(c.pins.values())
        adj[u].add(v)
        adj[v].add(u)
    start = next(iter(adj))
    visited = {start}
    stack = [start]
    while stack:
        for nxt in adj[stack.pop()]:
            if nxt not in visited:
                stack.append(nxt)
                visited.add(nxt)
    if len(visited) != len(adj):
        raise CircuitError("Circuit contains an electrically disconnected subcircuit")
    return Circuit(components, nets, sources[0])




def reverse(net: Network) -> Network:
    if net.kind == "leaf":
        return Network("leaf", net.v, net.u, cid=net.cid)
    if net.kind == "series":
        kids = tuple(reverse(child) for child in reversed(net.kids))
    else:
        kids = tuple(reverse(child) for child in net.kids)
    return Network(net.kind, net.v, net.u, kids=kids)


def orient(net: Network, u: str, v: str) -> Network:
    if (net.u, net.v) == (u, v):
        return net
    if (net.v, net.u) == (u, v):
        return reverse(net)
    raise CircuitError(f"Internal topology problem: cannot orient {net.kind} {u}->{v}")


def expression(circuit: Circuit) -> Network:
    """Reduce two-terminal graph by merging parallel edges and degree-2 series nodes.

    All mergers preserve exact electrical net identities on terminal components.
    A bridge network cannot be reduced and is rejected, never guessed.
    """
    source = circuit.components[circuit.source]
    positive, negative = source.pins["p"], source.pins["n"]
    edges = [Network("leaf", c.pins["a"], c.pins["b"], cid=c.cid)
             for c in circuit.components.values() if c.cid != circuit.source]

    if not edges:
        raise CircuitError("No load components to render")
    for _ in range(4 * len(edges) + 10):
        buckets: dict[tuple[str, str], list[Network]] = collections.defaultdict(list)
        for e in edges:
            buckets[tuple(sorted((e.u, e.v)))].append(e)
        merged = False
        for (u, v), members in sorted(buckets.items()):
            if len(members) < 2:
                continue
            children = [orient(x, u, v) for x in members]
            children.sort(key=lambda e: (leaf_count(e), ids(e)))
            group = Network("parallel", u, v, kids=tuple(children))
            selected = set(map(id, members))
            edges = [x for x in edges if id(x) not in selected] + [group]
            merged = True
            break
        if merged:
            continue

        degree: dict[str, list[Network]] = collections.defaultdict(list)
        for e in edges:
            degree[e.u].append(e)
            degree[e.v].append(e)
        for node in sorted(degree):
            if node in (positive, negative) or len(degree[node]) != 2:
                continue
            a, b = degree[node]
            if a is b:
                continue
            x = a.v if a.u == node else a.u
            y = b.v if b.u == node else b.u
            if x == y:
                continue
            if x > y:
                x, y = y, x
                a, b = b, a
            first = orient(a, x, node)
            second = orient(b, node, y)
            kids1 = first.kids if first.kind == "series" else (first,)
            kids2 = second.kids if second.kind == "series" else (second,)
            group = Network("series", x, y, kids=kids1 + kids2)
            edges = [e for e in edges if e is not a and e is not b] + [group]
            merged = True
            break
        if not merged:
            break

    if len(edges) != 1 or {edges[0].u, edges[0].v} != {positive, negative}:
        raise CircuitError(
            "Unsupported topology: this draft can draw series/parallel "
            "two-terminal networks, but not bridge or arbitrary feedback circuits"
        )
    return orient(edges[0], positive, negative)


def leaf_count(n: Network) -> int:
    return 1 if n.kind == "leaf" else sum(leaf_count(c) for c in n.kids)


def ids(n: Network) -> str:
    return n.cid if n.kind == "leaf" else ",".join(ids(c) for c in n.kids)


def measure(n: Network, sizes: dict[int, Size], circuit: Circuit) -> Size:
    if n.kind == "leaf":
        component = circuit.components[n.cid]
        width = max(label_width(n.cid, 17, 10.5), label_width(component.value, 14, 8.4))
        width = max(LEAF_WIDTH, 2 * math.ceil((width/2 + 12) / GRID_PX))
        result = Size(width, LEAF_UP + (component.kind == 'led'), LEAF_DOWN)
    elif n.kind == "series":
        child = [measure(c, sizes, circuit) for c in n.kids]
        result = Size(sum(s.width for s in child), max(s.up for s in child), max(s.down for s in child))
    else:
        child = [measure(c, sizes, circuit) for c in n.kids]
        cursor = 0
        centers = []
        for s in child:
            center = cursor + s.up
            centers.append(center)
            cursor = center + s.down + BRANCH_Y_GAP
        full_height = cursor - BRANCH_Y_GAP
        offsets = tuple(center - full_height // 2 for center in centers)
        miny = min(0, *(y - s.up for y, s in zip(offsets, child)))
        maxy = max(0, *(y + s.down for y, s in zip(offsets, child)))
        result = Size(max(s.width for s in child) + BRANCH_X_PAD * 2,
                      -miny, maxy, offsets)
    sizes[id(n)] = result
    return result


def place(n: Network, x: int, y: int, sizes: dict[int, Size], circuit: Circuit, ink: Ink) -> None:
    s = sizes[id(n)]
    if n.kind == "leaf":
        comp = circuit.components[n.cid]
        center = x + s.width // 2
        left_terminal = (center - 2, y)
        right_terminal = (center + 2, y)
        direction = "right" if comp.pins["a"] == n.u else "left"
        terminals = {"a": left_terminal, "b": right_terminal} if direction == "right" else {
            "a": right_terminal, "b": left_terminal,
        }
        ink.placed[n.cid] = Placed(n.cid, center, y, direction, terminals)
        ink.wire(n.u, (x, y), left_terminal)
        ink.wire(n.v, right_terminal, (x + s.width, y))
        return
    if n.kind == "series":
        current = x
        for c in n.kids:
            place(c, current, y, sizes, circuit, ink)
            current += sizes[id(c)].width
        return
    content_w = s.width - 2 * BRANCH_X_PAD
    top, bottom = min(0, *s.branch_offsets), max(0, *s.branch_offsets)
    ink.wire(n.u, (x, top+y), (x, bottom+y))
    ink.wire(n.v, (x+s.width, top+y), (x+s.width, bottom+y))
    for child, offset in zip(n.kids, s.branch_offsets):
        branch_y = y + offset
        delta = (content_w - sizes[id(child)].width) // 2
        left = x + BRANCH_X_PAD + delta
        right = left + sizes[id(child)].width
        ink.wire(n.u, (x, branch_y), (left, branch_y))
        place(child, left, branch_y, sizes, circuit, ink)
        ink.wire(n.v, (right, branch_y), (x + s.width, branch_y))


def layout(circuit: Circuit) -> Ink:
    tree = expression(circuit)
    sizes: dict[int, Size] = {}
    body = measure(tree, sizes, circuit)
    ink = Ink()
    place(tree, 0, 0, sizes, circuit, ink)
    source = circuit.components[circuit.source]
    s_net, t_net = source.pins["p"], source.pins["n"]
    source_x = -SOURCE_X_GAP
    return_y = max(9, body.down + 3)
    source_y = return_y // 2
    if source_y <= SOURCE_SYMBOL_HALF_HEIGHT + 1:
        raise CircuitError("Internal error: source placement conflict")
    ink.placed[source.cid] = Placed(
        source.cid, source_x, source_y, "down",
        {"p": (source_x, source_y - SOURCE_SYMBOL_HALF_HEIGHT),
         "n": (source_x, source_y + SOURCE_SYMBOL_HALF_HEIGHT)},
    )
    ink.wire(s_net, (source_x, 0), (0, 0))
    ink.wire(s_net, (source_x, 0), (source_x, source_y - SOURCE_SYMBOL_HALF_HEIGHT))
    ink.wire(t_net, (source_x, source_y + SOURCE_SYMBOL_HALF_HEIGHT), (source_x, return_y))
    ink.wire(t_net, (source_x, return_y), (body.width, return_y))
    tail = tree
    while tail.kind == "series":
        tail = tail.kids[-1]
    rail_end = max(sizes[id(tail)].branch_offsets, default=0)
    ink.wire(t_net, (body.width, return_y), (body.width, max(0, rail_end)))
    verify_geometry(circuit, ink)
    return ink




def segment_cells(a: Point, b: Point) -> list[Point]:
    if a[0] != b[0] and a[1] != b[1]:
        raise CircuitError(f"Diagonal wire from {a} to {b}")
    dx = (b[0] > a[0]) - (b[0] < a[0])
    dy = (b[1] > a[1]) - (b[1] < a[1])
    length = abs(b[0] - a[0]) + abs(b[1] - a[1])
    return [(a[0] + dx * i, a[1] + dy * i) for i in range(length + 1)]


def verify_geometry(circuit: Circuit, ink: Ink) -> None:
    """Fail closed: validate exact pin-to-net mapping and wire-grid continuity."""
    if set(ink.placed) != set(circuit.components):
        raise CircuitError("Layout omitted or duplicated one or more components")
    cells: dict[str, set[Point]] = {n: set() for n in circuit.nets}
    for net, points in ink.wires:
        if net not in cells:
            raise CircuitError("Wire refers to a nonexistent net")
        for a, b in zip(points, points[1:]):
            cells[net].update(segment_cells(a, b))

    occupied: dict[Point, str] = {}
    for net, points in cells.items():
        for point in points:
            other = occupied.get(point)
            if other is not None and other != net:
                raise CircuitError(f"Two DIFFERENT nets overlap/cross at {point}: {other}, {net}")
            occupied[point] = net

    for cid, comp in circuit.components.items():
        p = ink.placed[cid]
        for pin, net in comp.pins.items():
            point = p.terminals[pin]
            if point not in cells[net]:
                raise CircuitError(f"Open circuit: {cid}.{pin} has no wire on net {net}")
            if occupied.get(point) != net:
                raise CircuitError(f"Incorrect-net attachment: {cid}.{pin}")
        for xy, net in occupied.items():
            if comp.kind in SOURCE_TYPES:
                collision = abs(xy[0] - p.x) <= 1 and abs(xy[1] - p.y) <= 1
            else:
                collision = abs(xy[0] - p.x) <= 1 and abs(xy[1] - p.y) <= 0
            if collision:
                raise CircuitError(f"A wire from {net} intersects body of component {cid}")

    for net, points in cells.items():
        if not points:
            raise CircuitError(f"No routing generated for net {net}")
        seed = next(iter(points))
        reached = {seed}
        stack = [seed]
        while stack:
            x, y = stack.pop()
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in points and q not in reached:
                    reached.add(q)
                    stack.append(q)
        if len(reached) != len(points):
            raise CircuitError(f"Disconnected wire geometry on net {net}")




def xml_text(value: str) -> str:
    return xml_escape(value, {'"': '&quot;', "'": '&apos;'})


def svg(circuit: Circuit, ink: Ink) -> str:
    coords = [point for _, pts in ink.wires for point in pts]
    for p in ink.placed.values():
        coords.extend(p.terminals.values())
        coords.append((p.x, p.y))
    source = circuit.components[circuit.source]
    source_label = max(label_width(source.cid, 17, 10.5), label_width(source.value, 14, 8.4))
    min_x = min(min(p[0] for p in coords) - 2,
                ink.placed[source.cid].x - math.ceil((source_label + 51) / GRID_PX))
    max_x = max(p[0] for p in coords) + 4
    min_y = min(p[1] for p in coords) - 4
    max_y = max(p[1] for p in coords) + 3
    width = (max_x - min_x) * GRID_PX
    height = (max_y - min_y) * GRID_PX

    def xy(p: Point) -> tuple[float, float]:
        return ((p[0] - min_x) * GRID_PX, (p[1] - min_y) * GRID_PX)

    def line(a: Point, b: Point, style: str = 'class="wire"') -> str:
        x1, y1 = xy(a)
        x2, y2 = xy(b)
        return f'<line {style} x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}">',
        '<title>CircuitGen schematic</title>',
        '<desc>Automatically generated and geometrically validated two-terminal electrical schematic. Review before physical use.</desc>',
        '<style><![CDATA[',
        '.wire{stroke:#27354d;stroke-width:3;stroke-linejoin:round;stroke-linecap:round}',
        '.symbol{stroke:#213149;stroke-width:3;fill:none;stroke-linecap:round;stroke-linejoin:round}',
        '.fill{fill:#213149;stroke:#213149;stroke-width:2}',
        '.label{fill:#17243c;font-family:Arial,Helvetica,sans-serif;font-size:17px;font-weight:700;text-anchor:middle}',
        '.value{fill:#3e506d;font-family:Arial,Helvetica,sans-serif;font-size:14px;text-anchor:middle}',
        '.junction{fill:#27354d}',
        ']]></style>',
    ]
    for net, pts in ink.wires:
        for a, b in zip(pts, pts[1:]):
            out.append(line(a, b))

    unit = GRID_PX
    for cid in sorted(ink.placed):
        p = ink.placed[cid]
        c = circuit.components[cid]
        x, y = xy((p.x, p.y))
        out.append(f'<g data-component="{xml_text(cid)}" data-type="{xml_text(c.kind)}">')
        if c.kind in SOURCE_TYPES:
            if c.kind == "battery":
                out.append(f'<line class="symbol" x1="{x-20}" y1="{y-15}" x2="{x+20}" y2="{y-15}"/>')
                out.append(f'<line class="symbol" x1="{x-11}" y1="{y+15}" x2="{x+11}" y2="{y+15}"/>')
                out.append(f'<line class="symbol" x1="{x}" y1="{y-2*unit}" x2="{x}" y2="{y-15}"/>')
                out.append(f'<line class="symbol" x1="{x}" y1="{y+15}" x2="{x}" y2="{y+2*unit}"/>')
            else:
                out.append(f'<circle class="symbol" cx="{x}" cy="{y}" r="25"/>')
                out.append(f'<line class="symbol" x1="{x}" y1="{y-2*unit}" x2="{x}" y2="{y-25}"/>')
                out.append(f'<line class="symbol" x1="{x}" y1="{y+25}" x2="{x}" y2="{y+2*unit}"/>')
            out.append(f'<text class="label" style="text-anchor:end" x="{x-36}" y="{y-6}">{xml_text(cid)}</text>')
            out.append(f'<text class="value" style="text-anchor:end" x="{x-36}" y="{y+15}">{xml_text(c.value)}</text>')
            if c.kind == "battery":
                out.append(f'<text class="value" x="{x+20}" y="{y-25}">+</text>')
                out.append(f'<text class="value" x="{x+20}" y="{y+33}">−</text>')
            elif c.kind == "dc_source":
                out.append(f'<text class="value" text-anchor="middle" x="{x}" y="{y-5}">+</text>')
                out.append(f'<text class="value" text-anchor="middle" x="{x}" y="{y+16}">−</text>')
        else:
            if p.orientation == "left":
                out.append(f'<g transform="translate({x:.1f} {y:.1f}) rotate(180)">')
            else:
                out.append(f'<g transform="translate({x:.1f} {y:.1f})">')
            d = 2 * unit
            sym = 1.22 * unit
            if c.kind == "resistor":
                verts = [(-sym, 0), (-0.94*unit, -10), (-0.65*unit, 10),
                         (-0.35*unit, -10), (-0.05*unit, 10),
                         (0.25*unit, -10), (0.55*unit, 10),
                         (0.85*unit, -10), (sym, 0)]
                poly = ' '.join(f'{a:.1f},{b:.1f}' for a,b in verts)
                out.append(f'<line class="symbol" x1="{-d}" y1="0" x2="{-sym}" y2="0"/>')
                out.append(f'<polyline class="symbol" points="{poly}"/>')
                out.append(f'<line class="symbol" x1="{sym}" y1="0" x2="{d}" y2="0"/>')
            elif c.kind == "capacitor":
                out.append(f'<line class="symbol" x1="{-d}" y1="0" x2="{-7}" y2="0"/>')
                out.append(f'<line class="symbol" x1="{-7}" y1="-20" x2="{-7}" y2="20"/>')
                out.append(f'<line class="symbol" x1="7" y1="-20" x2="7" y2="20"/>')
                out.append(f'<line class="symbol" x1="7" y1="0" x2="{d}" y2="0"/>')
            elif c.kind == "inductor":
                out.append(f'<line class="symbol" x1="{-d}" y1="0" x2="{-unit}" y2="0"/>')
                parts = [f'M {-unit} 0']
                for i in range(4):
                    start = -unit + (i * unit/2)
                    parts.append(f'C {start+unit/8:.2f} -22 {start+3*unit/8:.2f} -22 {start+unit/2:.2f} 0')
                out.append(f'<path class="symbol" d="{" ".join(parts)}"/>')
                out.append(f'<line class="symbol" x1="{unit}" y1="0" x2="{d}" y2="0"/>')
            elif c.kind in {"diode", "led"}:
                out.append(f'<line class="symbol" x1="{-d}" y1="0" x2="{-20}" y2="0"/>')
                out.append('<polygon class="symbol" points="-20,-19 -20,19 12,0"/>')
                out.append('<line class="symbol" x1="12" y1="-20" x2="12" y2="20"/>')
                out.append(f'<line class="symbol" x1="12" y1="0" x2="{d}" y2="0"/>')
                if c.kind == "led":
                    out.append('<path class="symbol" d="M -1 -26 l 15 -13 m -4 1 l 4 -1 l -1 5"/>')
                    out.append('<path class="symbol" d="M 11 -22 l 15 -13 m -4 1 l 4 -1 l -1 5"/>')
            elif c.kind == "switch":
                out.append(f'<line class="symbol" x1="{-d}" y1="0" x2="{-18}" y2="0"/>')
                out.append(f'<circle class="symbol" cx="{-18}" cy="0" r="4"/>')
                out.append(f'<circle class="symbol" cx="18" cy="0" r="4"/>')
                out.append(f'<line class="symbol" x1="{-18}" y1="0" x2="16" y2="-20"/>')
                out.append(f'<line class="symbol" x1="18" y1="0" x2="{d}" y2="0"/>')
            elif c.kind == "lamp":
                out.append(f'<line class="symbol" x1="{-d}" y1="0" x2="{-24}" y2="0"/>')
                out.append('<circle class="symbol" r="24"/>')
                out.append('<path class="symbol" d="M -16 -16 L16 16 M -16 16 L16 -16"/>')
                out.append(f'<line class="symbol" x1="24" y1="0" x2="{d}" y2="0"/>')
            elif c.kind == "fuse":
                out.append(f'<line class="symbol" x1="{-d}" y1="0" x2="{-22}" y2="0"/>')
                out.append('<rect class="symbol" x="-22" y="-10" width="44" height="20"/>')
                out.append(f'<line class="symbol" x1="22" y1="0" x2="{d}" y2="0"/>')
            else:
                raise CircuitError(f"Internal rendering error: {c.kind}")
            out.append('</g>')
            label_y = y - (60 if c.kind == 'led' else 32)
            out.append(f'<text class="label" x="{x:.1f}" y="{label_y:.1f}">{xml_text(cid)}</text>')
            if c.value:
                out.append(f'<text class="value" x="{x:.1f}" y="{y+43:.1f}">{xml_text(c.value)}</text>')
        out.append('</g>')

    net_pin_counts = {name: len(pins) for name, pins in circuit.nets.items()}
    attachment: dict[str, list[Point]] = collections.defaultdict(list)
    for c in circuit.components.values():
        p = ink.placed[c.cid]
        for pin, net in c.pins.items():
            attachment[net].append(p.terminals[pin])
    positions_by_net: dict[str, set[Point]] = collections.defaultdict(set)
    for net, pts in ink.wires:
        for a,b in zip(pts,pts[1:]):
            positions_by_net[net].update(segment_cells(a,b))
    for net, pts in positions_by_net.items():
        if net_pin_counts[net] < 3:
            continue
        junction_candidates = []
        for x0,y0 in pts:
            neighbors = sum(((x0+1,y0) in pts, (x0-1,y0) in pts,
                             (x0,y0+1) in pts, (x0,y0-1) in pts))
            if neighbors >= 3:
                junction_candidates.append((x0,y0))
        for pt in junction_candidates:
            x0,y0 = xy(pt)
            out.append(f'<circle class="junction" cx="{x0:.1f}" cy="{y0:.1f}" r="5"/>')

    out.append('</svg>')
    return '\n'.join(out) + '\n'



# API

def make_svg_from_netlist(raw: dict[str, Any], *, optimize: bool = False, color: str = "#000000") -> str:
    from .colors import apply_ink_color
    model = validate_model(raw)
    if (all(c.kind in VALID_TYPES for c in model.components.values()) and
            all(len(c.pins) == 2 for c in model.components.values()) and
            sum(c.kind in SOURCE_TYPES for c in model.components.values()) == 1):
        try:
            circuit = validate(raw)
            ink = layout(circuit)
            return apply_ink_color(svg(circuit, ink), color)
        except CircuitError as error:
            if "Unsupported topology" not in str(error):
                raise
    return make_routed_svg_from_netlist(raw, optimize=optimize, color=color)


def route_netlist(raw: dict[str, Any], *, optimize: bool = False):
    """Return verified orthogonal wire paths for a general circuit."""
    from .routing import route_model
    return route_model(validate_model(raw), optimize=optimize)


def make_routed_svg_from_netlist(raw: dict[str, Any], *, optimize: bool = False, color: str = "#000000") -> str:
    """Route a general circuit and render a transparent SVG."""
    from .routing import make_routed_svg
    return make_routed_svg(validate_model(raw), optimize=optimize, color=color)



# GENERAL PLACEMENT API

def place_netlist(raw: dict[str, Any]):
    """Return geometry for any structurally valid netlist; no wires are routed."""
    from .placement import place_model
    return place_model(validate_model(raw))


def make_placement_preview_svg_from_netlist(raw: dict[str, Any]) -> str:
    """Render placement and dashed connectivity guides, NOT a wired schematic."""
    from .placement import make_placement_preview_svg
    return make_placement_preview_svg(validate_model(raw))


# ELECTRICAL RULE CHECKING

def check_electrical_rules(raw: dict[str, Any]):
    """Return errors, warnings and information without changing SVG output."""
    from .erc import check_electrical_rules as check
    return check(raw)


def make_checked_svg_from_netlist(raw: dict[str, Any], *, strict: bool = False,
                                  optimize: bool = False, color: str = "#000000"):
    """Render a checked netlist, returning (svg, ERCReport).

    Definite ERC errors block rendering. Strict mode also blocks warnings.
    Ordinary make_svg_from_netlist remains backwards compatible.
    """
    report = check_electrical_rules(raw)
    if report.errors or (strict and report.warnings):
        raise CircuitError(report.format_text())
    return make_svg_from_netlist(raw, optimize=optimize, color=color), report
