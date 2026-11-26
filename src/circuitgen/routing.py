"""Deterministic grid-based Manhattan routing for arbitrary circuit netlists."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import dataclasses
import heapq
import itertools
import math
from collections import defaultdict
from functools import lru_cache, partial
from pathlib import Path
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape as xml_escape

from .placement import Placement, _supply_net_names, place_model, layout_candidates
from .symbols import GRID_PX, label_width, routed_pin_labels, symbol_body_svg, transform_point

if TYPE_CHECKING:
    from .engine import CircuitModel

BODY_CLEARANCE = 0.20
WIRE_CLEARANCE = 0.14
BEND_PENALTY = 2.6
CROSSING_PENALTY = 9.0
LABEL_CLEARANCE = 0.24
ROUTING_MARGIN = 11.0
MAX_TRACK_NODES = 100000
MAX_ROUTING_STATES = 550000
Point = tuple[float, float]
Segment = tuple[Point, Point]


class RoutingError(ValueError):
    """A net could not be routed without hitting a symbol or unrelated net."""


@dataclasses.dataclass(frozen=True)
class NetLabel:
    net: str
    ref: str
    endpoint: Point
    label_at: Point
    side: str


@dataclasses.dataclass(frozen=True)
class RoutedCircuit:
    placement: Placement
    paths: dict[str, tuple[tuple[Point, ...], ...]]
    junctions: dict[str, tuple[Point, ...]]
    pin_to_net: dict[str, str]
    labels: tuple[NetLabel, ...] = ()


def _pt(p: Point) -> Point:
    return round(p[0], 6), round(p[1], 6)


def _bounds(item, symbol) -> tuple[float, float, float, float]:
    corners = [transform_point(i * symbol.half_width, j * symbol.half_height,
                               item.rotation, item.mirror)
               for i in (-1, 1) for j in (-1, 1)]
    return (item.x + min(x for x, _ in corners),
            item.y + min(y for _, y in corners),
            item.x + max(x for x, _ in corners),
            item.y + max(y for _, y in corners))


def _intersects_rect(a: Point, b: Point, rect) -> bool:
    left, top, right, bottom = rect
    e = 1e-7
    if abs(a[1]-b[1]) < e:
        return top-e <= a[1] <= bottom+e and max(a[0], b[0]) >= left-e and min(a[0], b[0]) <= right+e
    return left-e <= a[0] <= right+e and max(a[1], b[1]) >= top-e and min(a[1], b[1]) <= bottom+e


def _segment_clearance(a: Point, b: Point, c: Point, d: Point) -> float:
    aminx, amaxx = sorted((a[0], b[0])); aminy, amaxy = sorted((a[1], b[1]))
    bminx, bmaxx = sorted((c[0], d[0])); bminy, bmaxy = sorted((c[1], d[1]))
    dx = max(0, bminx-amaxx, aminx-bmaxx)
    dy = max(0, bminy-amaxy, aminy-bmaxy)
    return math.hypot(dx, dy)


def _unjoined_crossing(a: Point, b: Point, c: Point, d: Point, *, segment_margin: float = 0.60, edge_margin: float = 0.0) -> bool:
    """True only for orthogonal crossings away from existing wire endpoints.

    A temporary pathfinding edge may end exactly at the crossing; the
    completed/compressed path has to pass *through* it, not turn onto it.
    """
    eps = 1e-6
    ah=abs(a[1]-b[1])<eps and abs(a[0]-b[0])>eps
    bh=abs(c[1]-d[1])<eps and abs(c[0]-d[0])>eps
    av=abs(a[0]-b[0])<eps and abs(a[1]-b[1])>eps
    bv=abs(c[0]-d[0])<eps and abs(c[1]-d[1])>eps
    if ah and bv:
        x,y=c[0],a[1]
        return (min(a[0],b[0])+edge_margin-eps <= x <= max(a[0],b[0])-edge_margin+eps and
                min(c[1],d[1])+segment_margin+eps < y < max(c[1],d[1])-segment_margin-eps)
    if av and bh:
        x,y=a[0],c[1]
        return (min(a[1],b[1])+edge_margin-eps <= y <= max(a[1],b[1])-edge_margin+eps and
                min(c[0],d[0])+segment_margin+eps < x < max(c[0],d[0])-segment_margin-eps)
    return False


def _segments(points):
    return tuple(zip(points, points[1:]))


def _label_rect(item, x, y, width, height, anchor):
    left = x - width * {'start': 0, 'middle': .5, 'end': 1}[anchor]
    return (item.x + left/GRID_PX - LABEL_CLEARANCE,
            item.y + (y-height)/GRID_PX - LABEL_CLEARANCE,
            item.x + (left+width)/GRID_PX + LABEL_CLEARANCE,
            item.y + (y+3)/GRID_PX + LABEL_CLEARANCE)


def _compress(points: tuple[Point, ...]) -> tuple[Point, ...]:
    if len(points) <= 2:
        return points
    result = [points[0]]
    for a, b, c in zip(points, points[1:], points[2:]):
        if not ((abs(a[0]-b[0]) < 1e-6 and abs(b[0]-c[0]) < 1e-6) or
                (abs(a[1]-b[1]) < 1e-6 and abs(b[1]-c[1]) < 1e-6)):
            result.append(b)
    return tuple(result + [points[-1]])


def _junction_points(paths: tuple[tuple[Point, ...], ...], pins: set[Point]) -> tuple[Point, ...]:
    segments = [(a, b) for path in paths for a, b in _segments(path)]
    candidates = pins | {point for path in paths for point in path}
    horizontal = [(a, b) for a, b in segments if a[1] == b[1]]
    vertical = [(a, b) for a, b in segments if a[0] == b[0]]
    for a, b in horizontal:
        for c, d in vertical:
            if min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(c[1], d[1]) <= a[1] <= max(c[1], d[1]):
                candidates.add((c[0], a[1]))

    junctions = []
    for x, y in sorted(candidates):
        directions = set()
        for a, b in segments:
            if _segment_clearance(a, b, (x, y), (x, y)) < 1e-6:
                for px, py in (a, b):
                    if (px, py) != (x, y):
                        directions.add(((px > x) - (px < x), (py > y) - (py < y)))
        if len(directions) >= 3 or (len(directions) >= 2 and (x, y) in pins):
            junctions.append((x, y))
    return tuple(junctions)


class _MeshRouter:
    def __init__(self, model: CircuitModel, placement: Placement, margin: float):
        self.model = model
        self.placement = placement
        self.pins = {f'{cid}.{pin}': _pt(pos)
                     for cid, item in placement.symbols.items()
                     for pin, pos in item.pin_positions.items()}
        self.terminal_nets = {ref: name for name, refs in model.nets.items() for ref in refs}
        extents = [(p.x-p.half_width, p.y-p.half_height,
                    p.x+p.half_width, p.y+p.half_height)
                   for p in placement.symbols.values()]
        minx = min(a for a, _, _, _ in extents)-margin
        maxx = max(c for _, _, c, _ in extents)+margin
        miny = min(b for _, b, _, _ in extents)-margin
        maxy = max(d for _, _, _, d in extents)+margin
        xs = set(range(math.floor(minx), math.ceil(maxx)+1))
        ys = set(range(math.floor(miny), math.ceil(maxy)+1))
        for x, y in self.pins.values():
            xs.update((x, round(x-0.5, 6), round(x+0.5, 6)))
            ys.update((y, round(y-0.5, 6), round(y+0.5, 6)))
        self.xs, self.ys = sorted(xs), sorted(ys)
        self.width, self.height = len(self.xs), len(self.ys)
        if self.width*self.height > MAX_TRACK_NODES:
            raise RoutingError('Circuit exceeds router grid limits')
        xidx = {x: i for i, x in enumerate(self.xs)}
        yidx = {y: i for i, y in enumerate(self.ys)}
        self.pin_nodes = {ref: (xidx[p[0]], yidx[p[1]]) for ref, p in self.pins.items()}
        self.rects = []
        for cid, item in placement.symbols.items():
            symbol = model.symbols[cid]
            component = model.components[cid]
            l, t, r, b = _bounds(item, symbol)
            self.rects.append((l-BODY_CLEARANCE, t-BODY_CLEARANCE,
                               r+BODY_CLEARANCE, b+BODY_CLEARANCE))
            self.rects.append(_label_rect(item, item.title_x*GRID_PX, item.title_y*GRID_PX,
                                          max(23, label_width(cid, 17, 10.5)), 17, item.label_anchor))
            if component.value:
                self.rects.append(_label_rect(item, item.value_x*GRID_PX, item.value_y*GRID_PX,
                                              max(19, label_width(component.value, 13, 7.8)),
                                              13, item.label_anchor))
            if len(symbol.pins) > 2 and (symbol.shape != 'ic' or item.rotation not in (0, 180)):
                for label, x, y, anchor in routed_pin_labels(symbol, item.rotation, item.mirror, component.pins):
                    self.rects.append(_label_rect(item, x, y, label_width(label, 10, 6.3), 10, anchor))
        # Every pin is reserved, including deliberately unconnected pins.
        self.reserved_pins = tuple((pos, self.terminal_nets.get(ref))
                                   for ref, pos in self.pins.items())
        self.pin_leads = []
        for cid, item in placement.symbols.items():
            symbol = model.symbols[cid]
            l, t, r, b = _bounds(item, symbol)
            for pin, endpoint in item.pin_positions.items():
                endpoint = _pt(endpoint)
                x, y = endpoint
                if x < l: body_point = (l, y)
                elif x > r: body_point = (r, y)
                elif y < t: body_point = (x, t)
                elif y > b: body_point = (x, b)
                else: continue
                lead_start = tuple(a + (b-a)*.001 for a, b in zip(endpoint, body_point))
                self.pin_leads.append((endpoint, lead_start, body_point,
                                       self.terminal_nets.get(f'{cid}.{pin}')))
        self.existing: dict[str, list[Segment]] = defaultdict(list)
        self._bin_size = 2.0
        self._reserved_pin_bins = defaultdict(list)
        self._pin_lead_bins = defaultdict(list)
        self._existing_bins = defaultdict(list)
        for point, owner in self.reserved_pins:
            self._index_item(self._reserved_pin_bins,
                             (point[0], point[1], point[0], point[1]), (point, owner))
        for lead in self.pin_leads:
            endpoint, lead_start, body_point, owner = lead
            bounds = (min(endpoint[0], body_point[0]), min(endpoint[1], body_point[1]),
                      max(endpoint[0], body_point[0]), max(endpoint[1], body_point[1]))
            self._index_item(self._pin_lead_bins, bounds, lead)
        self.edge_geometry_clear = lru_cache(maxsize=200000)(self._edge_geometry_clear)

    def _index_item(self, index, bounds, item):
        left, top, right, bottom = bounds
        size = self._bin_size
        for ix in range(math.floor(left / size), math.floor(right / size) + 1):
            for iy in range(math.floor(top / size), math.floor(bottom / size) + 1):
                index[(ix, iy)].append(item)

    def _nearby_items(self, index, a, b):
        padding = WIRE_CLEARANCE
        left, right = sorted((a[0], b[0]))
        top, bottom = sorted((a[1], b[1]))
        size = self._bin_size
        found = set()
        ordered = []
        for ix in range(math.floor((left-padding)/size), math.floor((right+padding)/size) + 1):
            for iy in range(math.floor((top-padding)/size), math.floor((bottom+padding)/size) + 1):
                for item in index.get((ix, iy), ()):
                    if item not in found:
                        found.add(item)
                        ordered.append(item)
        return ordered

    def _p(self, node):
        return self.xs[node[0]], self.ys[node[1]]

    def _edge_geometry_clear(self, u, v):
        a, b = self._p(u), self._p(v)
        return not any(_intersects_rect(a, b, rect) for rect in self.rects)

    def _valid(self, u, v, net):
        if not self.edge_geometry_clear(u, v):
            return None
        a, b = self._p(u), self._p(v)
        for point, owner in self._nearby_items(self._reserved_pin_bins, a, b):
            if owner != net and _segment_clearance(a, b, point, point) <= WIRE_CLEARANCE:
                return None
        for endpoint, lead_start, body_point, owner in self._nearby_items(self._pin_lead_bins, a, b):
            start, clearance = (lead_start, 1e-7) if owner == net else (endpoint, WIRE_CLEARANCE)
            if _segment_clearance(a, b, start, body_point) <= clearance:
                return None
        crossings = 0
        for owner, c, d in self._nearby_items(self._existing_bins, a, b):
            if owner != net:
                if _segment_clearance(a, b, c, d) <= WIRE_CLEARANCE:
                    if not _unjoined_crossing(a, b, c, d, edge_margin=0.60):
                        return None
                    x, y = (c[0], a[1]) if a[1] == b[1] else (a[0], c[1])
                    bridge = (x - .4, y - .52, x + .4, y + .06)
                    if any(l <= bridge[2] and r >= bridge[0] and t <= bridge[3] and btm >= bridge[1]
                           for l, t, r, btm in self.rects):
                            return None
                    crossings += 1
        return crossings

    def _neighbors(self, node):
        x, y = node
        if x: yield (x-1, y), 0
        if x+1 < self.width: yield (x+1, y), 0
        if y: yield (x, y-1), 1
        if y+1 < self.height: yield (x, y+1), 1

    def _join_tree(self, path, tree):
        # Crossover hops can skip mesh nodes already on the same net.
        # Stop at the first contact so the rest of the hop leaves no stub.
        joined = [path[0]]
        for (x, y), (nx, ny) in _segments(path):
            dx = (nx > x) - (nx < x)
            dy = (ny > y) - (ny < y)
            while (x, y) != (nx, ny):
                x, y = x + dx, y + dy
                joined.append((x, y))
                if (x, y) in tree:
                    return tuple(joined)
        return tuple(joined)

    def _crossing_edges(self, net):
        """Provide straight edges with runway on both sides of each crossover."""
        hops = defaultdict(list)
        coordinates = (self.xs, self.ys)
        for owner, segments in self.existing.items():
            if owner == net:
                continue
            for a, b in segments:
                along = 0 if a[1] == b[1] else 1
                across = 1 - along
                moving, fixed = coordinates[across], coordinates[along]
                left = bisect_right(moving, a[across] - 0.60 + 1e-6) - 1
                right = bisect_left(moving, a[across] + 0.60 - 1e-6)
                if left < 0 or right >= len(moving):
                    continue
                low, high = sorted((a[along], b[along]))
                for index in range(bisect_right(fixed, low + 0.60 + 1e-6),
                                   bisect_left(fixed, high - 0.60 - 1e-6)):
                    u, v = ((left, index), (right, index)) if across == 0 else ((index, left), (index, right))
                    hops[u].append((v, across))
                    hops[v].append((u, across))
        return hops

    def _search(self, start, goals, net, hops, valid_edge):
        if start in goals:
            return (start,)
        goal_points = tuple(self._p(node) for node in goals)
        def heuristic(node):
            x, y = self._p(node)
            return min(abs(gx-x) + abs(gy-y) for gx, gy in goal_points)
        seq = itertools.count()
        frontier = [(heuristic(start), 0.0, next(seq), start, -1)]
        distance = {(start, -1): 0.0}
        previous = {}
        expanded = 0
        while frontier:
            _, cost, _, node, direction = heapq.heappop(frontier)
            state = (node, direction)
            if cost > distance[state]+1e-8:
                continue
            if node in goals:
                result = [node]
                while state in previous:
                    state = previous[state]
                    result.append(state[0])
                return tuple(reversed(result))
            expanded += 1
            if expanded > MAX_ROUTING_STATES:
                raise RoutingError(f'Routing search limit exceeded on net {net}')
            for nxt, d in itertools.chain(self._neighbors(node), hops.get(node, ())):
                u, v = (node, nxt) if node < nxt else (nxt, node)
                crossings = valid_edge(u, v)
                if crossings is None:
                    continue
                a, b = self._p(node), self._p(nxt)
                cost2 = (cost + abs(a[0]-b[0]) + abs(a[1]-b[1])
                         + CROSSING_PENALTY * crossings)
                if direction not in (-1, d):
                    cost2 += BEND_PENALTY
                newstate = (nxt, d)
                if cost2 < distance.get(newstate, float('inf'))-1e-8:
                    distance[newstate] = cost2
                    previous[newstate] = state
                    heapq.heappush(frontier, (cost2+heuristic(nxt), cost2,
                                              next(seq), nxt, d))
        raise RoutingError(f'No collision-free path for net {net}')

    def route(self, order):
        self.existing.clear()
        self._existing_bins.clear()
        paths_by_net = {}
        raw_by_net = {}
        for net in order:
            refs = sorted(self.model.nets[net])
            nodes = {self.pin_nodes[ref] for ref in refs}
            if len(nodes) <= 1:
                paths_by_net[net] = ()
                raw_by_net[net] = []
                continue
            root = min(nodes, key=lambda node: (
                sum(abs(self.xs[node[0]]-self.xs[other[0]]) +
                    abs(self.ys[node[1]]-self.ys[other[1]]) for other in nodes),
                node,
            ))
            tree = {root}
            remaining = nodes-tree
            raw_paths = []
            hops = self._crossing_edges(net)
            valid_edge = lru_cache(maxsize=100000)(partial(self._valid, net=net))
            while remaining:
                target = min(remaining, key=lambda node: (
                    min(abs(self.xs[node[0]]-self.xs[c[0]]) +
                        abs(self.ys[node[1]]-self.ys[c[1]]) for c in tree), node))
                path = self._join_tree(self._search(target, tree, net, hops, valid_edge), tree)
                raw_paths.append(path)
                tree.update(path)
                remaining -= tree
            raw_by_net[net] = raw_paths
            geometries = [tuple(self._p(node) for node in path) for path in raw_paths]
            paths_by_net[net] = tuple(_compress(path) for path in geometries)
            for path in geometries:
                segments = _segments(_compress(path))
                self.existing[net].extend(segments)
                for a, b in segments:
                    bounds = (min(a[0], b[0]), min(a[1], b[1]),
                              max(a[0], b[0]), max(a[1], b[1]))
                    self._index_item(self._existing_bins, bounds, (net, a, b))
        self._verify(raw_by_net, paths_by_net)
        junctions = {
            net: _junction_points(paths, {self.pins[ref] for ref in self.model.nets[net]})
            for net, paths in paths_by_net.items()
        }
        result = RoutedCircuit(self.placement, paths_by_net, junctions,
                               dict(self.terminal_nets))
        verify_display_connectivity(self.model, result)
        return result

    def _verify(self, raw_paths, paths_by_net):
        for net, refs in self.model.nets.items():
            pins = {self.pin_nodes[ref] for ref in refs}
            if len(pins) <= 1:
                continue
            links = defaultdict(set)
            for path in raw_paths[net]:
                for a, b in _segments(path):
                    links[a].add(b); links[b].add(a)
            reached = {min(pins)}
            pending = [min(pins)]
            while pending:
                for next_node in links[pending.pop()]:
                    if next_node not in reached:
                        reached.add(next_node)
                        pending.append(next_node)
            if not pins.issubset(reached):
                raise RoutingError(f'Connectivity validation failed on net {net}')
        segments = [(net, a, b) for net, paths in paths_by_net.items()
                    for path in paths for a, b in _segments(path)]
        for i, (net, a, b) in enumerate(segments):
            if any(_intersects_rect(a, b, rect) for rect in self.rects):
                raise RoutingError(f'Wire touches a component body on net {net}')
            for pos, owner in self.reserved_pins:
                if owner != net and _segment_clearance(a, b, pos, pos) <= WIRE_CLEARANCE:
                    raise RoutingError(f'Wire from {net} touches an unrelated pin')
            for endpoint, lead_start, body_point, owner in self.pin_leads:
                start, clearance = (lead_start, 1e-7) if owner == net else (endpoint, WIRE_CLEARANCE)
                if _segment_clearance(a, b, start, body_point) <= clearance:
                    raise RoutingError(f'Wire from {net} touches a pin lead before its terminal')
            for other, c, d in segments[i+1:]:
                if (net != other and _segment_clearance(a, b, c, d) <= WIRE_CLEARANCE and
                        not _unjoined_crossing(a, b, c, d, segment_margin=0.60, edge_margin=0.60)):
                    raise RoutingError(f'Wires from {net} and {other} intersect')



def verify_display_connectivity(model: CircuitModel, routed: RoutedCircuit) -> None:
    """Independent geometric audit of the paths that will actually be drawn.

    Unlike `_MeshRouter._verify`, this checks the *compressed displayed paths*
    directly. Each net must form one geometric component. Unrelated nets
    may cross with clearance for a wire jump, and may never touch terminals.

    This is a connectivity/geometry audit, not a SPICE behavior simulation.
    """
    expected = {ref: net for net, refs in model.nets.items() for ref in refs}
    if routed.pin_to_net != expected:
        raise RoutingError('Display pin-to-net mapping differs from original netlist')
    if set(routed.paths) != set(model.nets):
        raise RoutingError('Displayed set of nets differs from the original netlist')
    if set(routed.placement.symbols) != set(model.components):
        raise RoutingError('Displayed component set differs from the original netlist')

    pin_positions = {f'{cid}.{pin}': _pt(pos)
                     for cid, part in routed.placement.symbols.items()
                     for pin, pos in part.pin_positions.items()}
    if routed.labels:
        raise RoutingError('Displayed net connections must use continuous wires')

    all_segments: list[tuple[str, Point, Point]] = []
    for net, paths in routed.paths.items():
        for path in paths:
            if len(path) < 2:
                raise RoutingError(f'Invalid displayed path on {net}')
            for a, b in _segments(path):
                if not all(math.isfinite(v) for v in (*a, *b)):
                    raise RoutingError(f'Non-finite displayed wire on {net}')
                if not (abs(a[0]-b[0]) <= 1e-5 or abs(a[1]-b[1]) <= 1e-5):
                    raise RoutingError(f'Diagonal displayed wire on {net}')
                if _pt(a) != _pt(b):
                    all_segments.append((net, a, b))
    # Recheck disjoint nets independently of the router's occupancy bookkeeping.
    for i, (name, a, b) in enumerate(all_segments):
        for other, c, d in all_segments[i+1:]:
            if (name != other and _segment_clearance(a, b, c, d) <= WIRE_CLEARANCE and
                    not _unjoined_crossing(a, b, c, d, segment_margin=0.60, edge_margin=0.60)):
                raise RoutingError(f'Displayed wires from {name} and {other} touch')
        for ref, pos in pin_positions.items():
            owner = expected.get(ref)
            if owner != name and _segment_clearance(a, b, pos, pos) <= WIRE_CLEARANCE:
                raise RoutingError(f'Displayed wire {name} touches unrelated pin {ref}')

    for net, refs in model.nets.items():
        segments = [(a, b) for owner, a, b in all_segments if owner == net]
        if not segments:
            if len(refs) > 1:
                raise RoutingError(f'No displayed connections for net {net}')
            continue
        # Each displayed segment is a graph vertex. Same-net segments physically
        # intersecting (including a T-junction on a long compressed line) merge.
        parents = list(range(len(segments)))
        def find(i):
            while parents[i] != i:
                parents[i] = parents[parents[i]]
                i = parents[i]
            return i
        def union(i, j):
            parents[find(i)] = find(j)
        for i, (a, b) in enumerate(segments):
            for j in range(i+1, len(segments)):
                c, d = segments[j]
                if _segment_clearance(a, b, c, d) < 1e-5:
                    union(i, j)
        # Every terminal must touch a wire on its own net.
        groups = defaultdict(set)
        for ref in refs:
            point = pin_positions[ref]
            touching = [i for i, (a, b) in enumerate(segments)
                        if _segment_clearance(a, b, point, point) < 1e-5]
            if not touching:
                raise RoutingError(f'Pin {ref} is not connected in displayed geometry')
            roots = {find(i) for i in touching}
            if len(roots) > 1:
                raise RoutingError(f'Ambiguous unconnected paths at pin {ref}')
            groups[next(iter(roots))].add(ref)
        if len(groups) != 1 or len({find(i) for i in range(len(segments))}) != 1:
            raise RoutingError(f'Disconnected displayed wires on net {net}')



def _expanded_placement(placement: Placement, scale: float) -> Placement:
    """Expand center-to-center spacing while preserving individual symbol size.

    Merely enlarging the SVG viewBox cannot create routing channels. This
    modifies actual placements and pin endpoints without moving pins relative
    to their components or changing the circuit.
    """
    ox = (min(item.x for item in placement.symbols.values()) +
          max(item.x for item in placement.symbols.values())) / 2
    oy = (min(item.y for item in placement.symbols.values()) +
          max(item.y for item in placement.symbols.values())) / 2
    moved = {}
    for cid, item in placement.symbols.items():
        nx = round(ox + (item.x - ox)*scale, 6)
        ny = round(oy + (item.y - oy)*scale, 6)
        dx, dy = nx-item.x, ny-item.y
        moved[cid] = dataclasses.replace(
            item, x=nx, y=ny,
            pin_positions={pin: _pt((x+dx, y+dy))
                           for pin, (x, y) in item.pin_positions.items()}
        )
    return dataclasses.replace(placement, symbols=moved)


def _route_model_base(model: CircuitModel, placement: Placement | None = None) -> RoutedCircuit:
    """Try deterministic wire orders and keep the best verified route."""
    from .optimization import assess_layout

    if placement is None:
        placement = place_model(model)
    pins = {ref: _pt(placement.symbols[ref.split('.', 1)[0]].pin_positions[
                     ref.split('.', 1)[1]])
            for refs in model.nets.values() for ref in refs}

    def wire_span(net):
        locations = [pins[ref] for ref in model.nets[net]]
        if len(locations) < 2:
            return 0.0
        return (max(x for x, y in locations) - min(x for x, y in locations) +
                max(y for x, y in locations) - min(y for x, y in locations))

    # Local signal connections usually route cleanly before wide buses.
    local_first = sorted(model.nets, key=lambda n: (wire_span(n), len(model.nets[n]), n))
    wide_first = sorted(model.nets, key=lambda n: (-len(model.nets[n]), n))
    long_first = sorted(model.nets, key=lambda n: (-wire_span(n), -len(model.nets[n]), n))
    supply_nets = _supply_net_names(model)
    multi_pin_parts = {cid for cid, symbol in model.symbols.items() if len(symbol.pins) >= 3}
    interface_first = sorted(model.nets, key=lambda n: (
        n in supply_nets,
        -len({ref.split('.', 1)[0] for ref in model.nets[n]
              if ref.split('.', 1)[0] in multi_pin_parts}),
        len(model.nets[n]), wire_span(n), n,
    ))

    # Prefer verified all-wire diagrams. Among successful route orders, favor
    # fewer unjoined crossings over small savings in wire length.
    complete_wiring = []
    router = _MeshRouter(model, placement, ROUTING_MARGIN)
    orders = []
    for order in (local_first, interface_first, wide_first, long_first):
        if order not in orders:
            orders.append(order)
    errors = []
    for order in orders[:2]:
        try:
            candidate = router.route(order)
            # Routing can be electrically sound yet too cramped to draw an
            # unambiguous bridge. Reject it here so the next route order or
            # placement gets a chance before SVG generation.
            _crossover_hop_geometry(candidate, _crossover_map(candidate))
            complete_wiring.append(candidate)
            # A fully verified drawing is more useful than spending another
            # full maze search to compare small wire-length differences.
            break
        except RoutingError as error:
            errors.append('all-wire: ' + str(error))
    # Try fanout-first and span-first orders only when local and interface
    # connections could not be routed as a complete verified drawing.
    if not complete_wiring and len(orders) > 2:
        try:
            complete_wiring.append(router.route(orders[2]))
        except RoutingError as error:
            errors.append('wide-first: ' + str(error))
    if not complete_wiring and len(orders) > 3:
        try:
            complete_wiring.append(router.route(orders[3]))
        except RoutingError as error:
            errors.append('long-first: ' + str(error))
    if complete_wiring:
        return min(complete_wiring, key=lambda candidate: assess_layout(candidate).score)

    raise RoutingError('Unable to construct an electrically verified schematic. ' +
                       ' | '.join(errors[-4:]))


def route_model(model: CircuitModel, placement: Placement | None = None,
                *, optimize: bool = False) -> RoutedCircuit:
    """Choose a readable verified layout from bounded general candidates.

    Never accept a visually attractive but electrically unverified drawing.
    The source netlist stays unchanged. Routing failures are not suppressed.
    """
    if placement is not None:
        result = _route_model_base(model, placement)
        if optimize:
            from .optimization import choose_better_layout
            return choose_better_layout(model, result, _route_model_base)
        return result

    from .optimization import assess_layout
    original = place_model(model)
    best = None
    best_score = math.inf
    last_error = None

    candidates = list(layout_candidates(model, original))
    budget = 5 if optimize else 3
    for index, candidate in enumerate(candidates[:budget]):
        scales = (1.0, 1.25, 1.5, 2.5) if index == 0 else (1.0, 1.25)
        for scale in scales:
            # Expansion is for recovery, not for making a successful drawing
            # larger. Stop at the original scale if it routed successfully.
            if best is not None and scale != 1.0:
                break
            attempt = candidate if scale == 1.0 else _expanded_placement(candidate, scale)
            try:
                routed = _route_model_base(model, attempt)
            except RoutingError as error:
                last_error = error
                continue
            score = assess_layout(routed).score
            if score < best_score - 1e-5:
                best_score, best = score, routed
            break
    if best is None:
        # A new visual heuristic must never make a formerly drawable circuit
        # unrenderable. If the functional arrangement cannot route, retry the
        # original general/topological placement with the same strict checks.
        general = place_model(model, _skip_functional=True)
        if general.symbols != original.symbols:
            recovery_candidates = list(layout_candidates(model, general))[:2]
            for candidate in recovery_candidates:
                for scale in (1.0, 1.25):
                    attempt = candidate if scale == 1.0 else _expanded_placement(candidate, scale)
                    try:
                        return _route_model_base(model, attempt)
                    except RoutingError as error:
                        last_error = error
        raise RoutingError(f'No verified layout after routing and spacing retries: {last_error}')
    if optimize:
        from .optimization import choose_better_layout
        return choose_better_layout(model, best, _route_model_base)
    return best


def _crossover_count(routed: RoutedCircuit) -> int:
    return sum(len(points) for points in _crossover_map(routed).values()) // 2


def _crossover_map(routed: RoutedCircuit):
    """Locate confirmed unjoined, perpendicular crossings for SVG jump glyphs.

    The route verifier has already checked every such crossing stays away from
    wire ends and from actual component terminals. This function has no
    influence on electrical connectivity: it only renders clear crossover
    signs on top of an already-validated netlist.
    """
    segments = []
    for net, paths in routed.paths.items():
        for path_index, path in enumerate(paths):
            for segment_index, (a, b) in enumerate(_segments(path)):
                if _pt(a) != _pt(b):
                    segments.append((net, path_index, segment_index, a, b))
    crossings = defaultdict(list)
    for i, (net, pi, si, a, b) in enumerate(segments):
        for other, opi, osi, c, d in segments[i+1:]:
            if net == other:
                continue
            if not _unjoined_crossing(a, b, c, d, segment_margin=0.60,
                                       edge_margin=0.60):
                continue
            if abs(a[1]-b[1]) < 1e-6:
                pt = _pt((c[0], a[1]))
            else:
                pt = _pt((a[0], c[1]))
            crossings[(net, pi, si)].append(pt)
            crossings[(other, opi, osi)].append(pt)
    return crossings


def _crossover_hop_geometry(routed: RoutedCircuit, crossover_map):
    """Shared hop measurements for both wires at each crossover.

    A previous version centered the gap in the vertical wire on the original
    crossing rather than on the *raised bridge apex*. That left the curved
    stroke touching the other wire in the finished SVG. Compute the two from
    the same geometry so visual nonconnections cannot acquire a false join.
    """
    hops = {}
    for (net, path_i, seg_i), crossings in crossover_map.items():
        a, b = _segments(routed.paths[net][path_i])[seg_i]
        if abs(a[1] - b[1]) > 1e-6:  # Calculate once, from the horizontal wire.
            continue
        xs = sorted({pt[0] for pt in crossings})
        for j, x in enumerate(xs):
            room = min(abs(x - a[0]), abs(b[0] - x))
            if j:
                room = min(room, (x - xs[j-1]) / 2)
            if j+1 < len(xs):
                room = min(room, (xs[j+1] - x) / 2)
            radius = min(0.34, 0.78 * room)
            if radius < 0.05:
                raise RoutingError(f'Insufficient space for an unconnected wire jump on {net}')
            height = min(0.46, max(0.18, 1.35 * radius))
            hops[_pt((x, a[1]))] = (radius, height)
    return hops


def _svg_routed_path(net: str, path_index: int, path: tuple[Point, ...],
                     crossover_map, hop_geometry, locate) -> str:
    """Render smooth, continuous wire bridges with accurately aligned gaps.

    The *horizontal* wire is a continuous two-cubic hump with horizontal
    tangent at entry, apex and exit. The vertical wire has a short gap exactly
    at the hump's apex, so the SVG cannot falsely appear shorted. Gap/bridge
    dimensions are derived from the same point, independent of path order.
    """
    x0, y0 = locate(path[0])
    commands = [f'M {x0:.2f} {y0:.2f}']
    for index, (a, b) in enumerate(_segments(path)):
        crossings = crossover_map.get((net, path_index, index), ())
        if abs(a[1] - b[1]) < 1e-6:
            direction = 1 if b[0] > a[0] else -1
            xs = sorted({round(pt[0], 6) for pt in crossings}, reverse=direction < 0)
            for x in xs:
                radius, height = hop_geometry[_pt((x, a[1]))]
                y = a[1]
                before = locate((x - direction*radius, y))
                apex = locate((x, y - height))
                after = locate((x + direction*radius, y))
                c1 = locate((x - direction*.55*radius, y))
                c2 = locate((x - direction*.45*radius, y-height))
                c3 = locate((x + direction*.45*radius, y-height))
                c4 = locate((x + direction*.55*radius, y))
                commands.append(f'L {before[0]:.2f} {before[1]:.2f}')
                commands.append(f'C {c1[0]:.2f} {c1[1]:.2f} '
                                f'{c2[0]:.2f} {c2[1]:.2f} '
                                f'{apex[0]:.2f} {apex[1]:.2f}')
                commands.append(f'C {c3[0]:.2f} {c3[1]:.2f} '
                                f'{c4[0]:.2f} {c4[1]:.2f} '
                                f'{after[0]:.2f} {after[1]:.2f}')
            bx, by = locate(b)
            commands.append(f'L {bx:.2f} {by:.2f}')
        else:
            direction = 1 if b[1] > a[1] else -1
            ys = sorted({round(pt[1], 6) for pt in crossings}, reverse=direction < 0)
            for y in ys:
                radius, height = hop_geometry[_pt((a[0], y))]
                # Gap is centered on the actual curved-wire intersection,
                # not the original orthogonal crossing at (x, y).
                gap_center = y - height
                half_gap = min(0.19, max(0.13, radius*.55))
                low, high = gap_center - half_gap, gap_center + half_gap
                before_y = low if direction > 0 else high
                after_y = high if direction > 0 else low
                before = locate((a[0], before_y))
                after = locate((a[0], after_y))
                commands.append(f'L {before[0]:.2f} {before[1]:.2f}')
                commands.append(f'M {after[0]:.2f} {after[1]:.2f}')
            bx, by = locate(b)
            commands.append(f'L {bx:.2f} {by:.2f}')
    return ' '.join(commands)


def make_routed_svg(model: CircuitModel, *, optimize: bool = False, color: str = "#000000") -> str:
    """Use historical motif rendering only for exact matches; otherwise route normally."""
    from .motifs import render_motif
    from .colors import apply_ink_color
    specialized = render_motif(model)
    if specialized is not None:
        return apply_ink_color(specialized, color)
    result = route_model(model, optimize=optimize)
    placed = result.placement
    bounds = []
    for item in placed.symbols.values():
        bounds.extend(((item.x-item.half_width, item.y-item.half_height),
                       (item.x+item.half_width, item.y+item.half_height)))
    for paths in result.paths.values():
        for path in paths:
            bounds.extend(path)
    x0 = min(x for x, _ in bounds)*GRID_PX-26
    y0 = min(y for _, y in bounds)*GRID_PX-26
    x1 = max(x for x, _ in bounds)*GRID_PX+26
    y1 = max(y for _, y in bounds)*GRID_PX+26
    def loc(p):
        return p[0]*GRID_PX-x0, p[1]*GRID_PX-y0
    def xml(value):
        return xml_escape(value, {'"': '&quot;', "'": '&apos;'})
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {x1-x0:.1f} {y1-y0:.1f}" width="{x1-x0:.1f}" height="{y1-y0:.1f}">',
           '<title>CircuitGen routed schematic</title>',
           '<style><![CDATA[',
           '.symbol{fill:none;stroke:#213149;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round}',
           '.mark{fill:#213149;font-family:Arial,sans-serif;font-size:16px;text-anchor:middle}',
           '.name{fill:#17243c;font-family:Arial,sans-serif;font-size:17px;font-weight:700}',
           '.value{fill:#3e506d;font-family:Arial,sans-serif;font-size:13px}',
           '.pin{fill:#394b66;font-family:Arial,sans-serif;font-size:10px}',
           '.wire{fill:none;stroke:#264a6f;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round}',
           '.junction{fill:#264a6f}',
           ']]></style>']
    crossover_map = _crossover_map(result)
    hop_geometry = _crossover_hop_geometry(result, crossover_map)
    for net in sorted(result.paths):
        for path_index, path in enumerate(result.paths[net]):
            if len(path) < 2:
                continue
            d = _svg_routed_path(net, path_index, path, crossover_map, hop_geometry, loc)
            out.append(f'<path class="wire" data-net="{xml(net)}" d="{d}"/>')
    for net in sorted(result.junctions):
        for p in result.junctions[net]:
            x, y = loc(p)
            out.append(f'<circle class="junction" data-net="{xml(net)}" cx="{x:.2f}" cy="{y:.2f}" r="4.2"/>')
    for cid in sorted(placed.symbols):
        item = placed.symbols[cid]
        comp = model.components[cid]
        symbol = model.symbols[cid]
        cx, cy = loc((item.x, item.y))
        out.append(f'<g data-component="{xml(cid)}" data-type="{xml(comp.kind)}">')
        active_pins = frozenset(comp.pins) if symbol.shape == 'ic' else None
        out.append(symbol_body_svg(symbol, cx, cy, item.rotation, item.mirror,
                                   visible_pins=active_pins))
        out.append(f'<text class="name" text-anchor="{item.label_anchor}" x="{cx+item.title_x*GRID_PX:.2f}" y="{cy+item.title_y*GRID_PX:.2f}">{xml(cid)}</text>')
        if comp.value:
            out.append(f'<text class="value" text-anchor="{item.label_anchor}" x="{cx+item.value_x*GRID_PX:.2f}" y="{cy+item.value_y*GRID_PX:.2f}">{xml(comp.value)}</text>')
        if len(symbol.pins) > 2:
            if symbol.shape == 'ic' and item.rotation in (0, 180):
                # Names inside the IC body leave outside pin leads unobstructed.
                left, top, right, bottom = _bounds(item, symbol)
                for pin in symbol.pins:
                    if pin.name not in comp.pins:
                        continue
                    px, py = item.pin_positions[pin.name]
                    label = pin.name + (f' ({pin.number})' if pin.number else '')
                    if px < left:
                        lx, ly, anchor = cx-symbol.half_width*GRID_PX+6, (py-item.y)*GRID_PX+3, 'start'
                    elif px > right:
                        lx, ly, anchor = cx+symbol.half_width*GRID_PX-6, (py-item.y)*GRID_PX+3, 'end'
                    elif py < top:
                        lx, ly, anchor = cx+(px-item.x)*GRID_PX, -symbol.half_height*GRID_PX+13, 'middle'
                    elif py > bottom:
                        lx, ly, anchor = cx+(px-item.x)*GRID_PX, symbol.half_height*GRID_PX-7, 'middle'
                    else:
                        continue
                    out.append(f'<text class="pin" text-anchor="{anchor}" x="{lx:.2f}" y="{cy+ly:.2f}">{xml(label)}</text>')
            else:
                for label, lx, baseline, anchor in routed_pin_labels(symbol, item.rotation, item.mirror, comp.pins):
                    out.append(f'<text class="pin" text-anchor="{anchor}" x="{cx+lx:.2f}" y="{cy+baseline:.2f}">{xml(label)}</text>')
        out.append('</g>')
    out.append('</svg>')
    return apply_ink_color('\n'.join(out)+'\n', color)


if __name__ == '__main__':
    import argparse
    import json
    from .engine import validate_model
    parser = argparse.ArgumentParser(description='Render a verified routed SVG schematic')
    parser.add_argument('netlist', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--color', default='#000000', help='Ink color, e.g. #000000 or #cc0000')
    parser.add_argument('--optimize', action='store_true', help='Try verified compact placement candidates')
    args = parser.parse_args()
    data = json.loads(args.netlist.read_text(encoding='utf-8'))
    artwork = make_routed_svg(validate_model(data), optimize=args.optimize, color=args.color)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(artwork, encoding='utf-8')
    print(f'Saved routed schematic: {args.output}')
