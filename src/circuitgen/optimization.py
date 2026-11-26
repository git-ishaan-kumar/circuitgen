"""Opt-in, conservative placement optimization for fully verified routed circuits.

Never changes netlists, symbols, pin orientations, or historic motif layouts.
Candidate placements are re-routed and subjected to the router's geometry and
connectivity checks. If none improves the score, the original route is kept.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

from .placement import Placement

if TYPE_CHECKING:
    from .engine import CircuitModel
    from .routing import RoutedCircuit


@dataclasses.dataclass(frozen=True)
class LayoutQuality:
    wire_length: float
    bends: int
    footprint_area: float
    named_endpoints: int
    score: float


def assess_layout(routed: RoutedCircuit) -> LayoutQuality:
    """Evaluate an already verified route; lower score is preferable."""
    from .routing import _crossover_count

    all_points = []
    for symbol in routed.placement.symbols.values():
        all_points.extend(((symbol.x-symbol.half_width, symbol.y-symbol.half_height),
                           (symbol.x+symbol.half_width, symbol.y+symbol.half_height)))
    length = 0.0
    bends = 0
    for paths in routed.paths.values():
        for path in paths:
            all_points.extend(path)
            length += sum(abs(b[0]-a[0])+abs(b[1]-a[1])
                          for a, b in zip(path, path[1:]))
            bends += max(0, len(path)-2)
    for label in routed.labels:
        x, y = label.endpoint
        # Conservative estimate of outside-net-label space.
        all_points.extend(((x-0.38*len(label.net)-1, y-1),
                           (x+0.38*len(label.net)+1, y+1)))
    left = min(x for x, y in all_points)
    right = max(x for x, y in all_points)
    top = min(y for x, y in all_points)
    bottom = max(y for x, y in all_points)
    area = (right-left)*(bottom-top)
    count = len(routed.labels)
    score = length + 1.75*bends + 0.08*area + 30*count + 34*_crossover_count(routed)
    return LayoutQuality(round(length, 4), bends, round(area, 4), count,
                         round(score, 4))


def _move_centers(placement: Placement, axis: str, factor: float) -> Placement:
    """Shrink only the distance between symbol centers, not the symbols."""
    centers = [getattr(item, axis) for item in placement.symbols.values()]
    origin = min(centers)
    moved = {}
    for cid in sorted(placement.symbols):
        item = placement.symbols[cid]
        old = getattr(item, axis)
        new = origin + round((old-origin)*factor*2)/2
        delta = round(new-old, 6)
        if axis == 'x':
            pins = {name: (round(x+delta, 6), y)
                    for name, (x, y) in item.pin_positions.items()}
        else:
            pins = {name: (x, round(y+delta, 6))
                    for name, (x, y) in item.pin_positions.items()}
        moved[cid] = dataclasses.replace(item, **{axis: round(new, 6), 'pin_positions': pins})
    return dataclasses.replace(placement, symbols=moved)


def _separated(placement: Placement, clearance: float = 0.25) -> bool:
    items = list(placement.symbols.values())
    for i, a in enumerate(items):
        for b in items[i+1:]:
            if (abs(a.x-b.x) < a.half_width+b.half_width+clearance and
                    abs(a.y-b.y) < a.half_height+b.half_height+clearance):
                return False
    return True


def compact_candidates(placement: Placement) -> Iterator[Placement]:
    """Produce a tiny deterministic search space with no symbol-body collisions."""
    # Avoid tuning bespoke placement geometry such as a controller's pin blocks.
    if len(placement.symbols) < 2 or len(placement.symbols) > 12:
        return
    seen = {tuple((cid, item.x, item.y) for cid, item in sorted(placement.symbols.items()))}
    for axis, factor in (('x', 0.85), ('y', 0.85), ('x', 0.70), ('y', 0.70)):
        candidate = _move_centers(placement, axis, factor)
        fingerprint = tuple((cid, item.x, item.y) for cid, item in sorted(candidate.symbols.items()))
        if fingerprint not in seen and _separated(candidate):
            seen.add(fingerprint)
            yield candidate


def choose_better_layout(model: CircuitModel,
                         baseline: RoutedCircuit,
                         route_fn: Callable[[CircuitModel, Placement], RoutedCircuit],
                         *, max_trials: int = 4) -> RoutedCircuit:
    """Accept only a strictly lower-scored, fully verified reroute.

    The baseline remains authoritative if candidates fail or score worse.
    """
    from .routing import RoutingError

    if max_trials < 0 or max_trials > 12:
        raise ValueError('max_trials must be 0–12')
    # Multi-pin controller placement uses hand-tuned conventions already.
    if any(len(symbol.pins) >= 12 for symbol in model.symbols.values()):
        return baseline
    best = baseline
    best_score = assess_layout(best).score
    for index, placement in enumerate(compact_candidates(baseline.placement)):
        if index >= max_trials:
            break
        try:
            trial = route_fn(model, placement)
        except RoutingError:
            continue
        score = assess_layout(trial).score
        if score < best_score - 0.01:
            best, best_score = trial, score
    return best
