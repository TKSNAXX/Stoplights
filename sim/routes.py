"""
Civilian trip itineraries: place / lane / intersection steps, planned at spawn.

Walks rebuild-cached best_next_hops and scenario route_hints. A place with more
than one reachable first neighbour slacks the origin hop automatically (best
neighbours two straws, others one). Named via hints still force that hop.
Police stay greedy.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from sim import places, world

KIND_PLACE = "place"
KIND_LANE = "lane"
KIND_INTERSECTION = "intersection"

MAX_ROUTE_HOPS = 32
BEST_NEIGHBOR_WEIGHT = 2.0
SLACK_NEIGHBOR_WEIGHT = 1.0


@dataclass(frozen=True, slots=True)
class RouteStep:
    kind: str
    ref: str | int


def first_lane(route: tuple[RouteStep, ...]) -> int | None:
    for step in route:
        if step.kind == KIND_LANE:
            return int(step.ref)
    return None


def first_lane_step_index(route: tuple[RouteStep, ...]) -> int:
    for i, step in enumerate(route):
        if step.kind == KIND_LANE:
            return i
    return 0


def out_lane_after(route: tuple[RouteStep, ...], lane_step_index: int) -> tuple[int, int] | None:
    """After the current lane step: intersection, then the next lane. Returns (lane, step_index)."""
    ix = lane_step_index + 1
    if ix + 1 >= len(route):
        return None
    if route[ix].kind != KIND_INTERSECTION or route[ix + 1].kind != KIND_LANE:
        return None
    return (int(route[ix + 1].ref), ix + 1)


def step_lane_after(route: tuple[RouteStep, ...], lane_step_index: int) -> tuple[int, int] | None:
    """
    After the current lane step: another lane, reached by stepping across a
    seam rather than through a node. Returns (lane, step_index).
    """
    nx = lane_step_index + 1
    if nx >= len(route) or route[nx].kind != KIND_LANE:
        return None
    return (int(route[nx].ref), nx)


def next_lane_after_place(route: tuple[RouteStep, ...], lane_step_index: int) -> tuple[int, int] | None:
    """After the current lane step: a place, then the next lane. Returns (lane, step_index)."""
    px = lane_step_index + 1
    if px + 1 >= len(route):
        return None
    if route[px].kind != KIND_PLACE or route[px + 1].kind != KIND_LANE:
        return None
    return (int(route[px + 1].ref), px + 1)


def place_after_lane(route: tuple[RouteStep, ...], lane_step_index: int) -> str | None:
    nx = lane_step_index + 1
    if nx >= len(route) or route[nx].kind != KIND_PLACE:
        return None
    return str(route[nx].ref)


def format_route_nodes(route: tuple[RouteStep, ...]) -> str:
    """Place and intersection ids only, e.g. Housing > bypass > Park."""
    parts: list[str] = []
    for step in route:
        if step.kind in (KIND_PLACE, KIND_INTERSECTION):
            parts.append(str(step.ref))
    return " > ".join(parts)


def retarget_place_steps(route: tuple[RouteStep, ...], old: str, new: str) -> tuple[RouteStep, ...]:
    if not route or old == new:
        return route
    return tuple(
        RouteStep(step.kind, new if step.kind == KIND_PLACE and step.ref == old else step.ref)
        for step in route
    )


def route_is_live(route: tuple[RouteStep, ...]) -> bool:
    if not route:
        return False
    lane_ids = set(world.lane_ids())
    places_ids = set(world.get_place_rects())
    for step in route:
        if step.kind == KIND_LANE:
            if int(step.ref) not in lane_ids or not world.get_lane_cells(int(step.ref)):
                return False
        elif step.kind == KIND_PLACE:
            if str(step.ref) not in places_ids:
                return False
        elif step.kind == KIND_INTERSECTION:
            if not world.is_intersection(str(step.ref)):
                return False
        else:
            return False
    return True


def _outgoing_neighbours(from_node: str) -> list[str]:
    seen: list[str] = []
    for i in world.outgoing_lanes(from_node):
        n = world.lane_exit_node(i)
        if n and n not in seen:
            seen.append(n)
    return seen


def _neighbour_reaches(neighbour: str, destination: str) -> bool:
    return neighbour == destination or world.destination_reachable(neighbour, destination)


def _reachable_first_hops(from_node: str, destination: str) -> list[str]:
    return [n for n in _outgoing_neighbours(from_node) if _neighbour_reaches(n, destination)]


def _hops_with_non_uturn(
    from_node: str,
    hops: frozenset[str] | set[str],
    inbound: int | None,
) -> list[str]:
    """Prefer next nodes that have an outbound that is not a U-turn. Fall back to hops."""
    if inbound is None or not hops:
        return list(hops)
    usable: list[str] = []
    for n in hops:
        outgoing = [i for i in world.outgoing_lanes(from_node) if world.lane_exit_node(i) == n]
        if any(not places.is_uturn_transition(inbound, i) for i in outgoing):
            usable.append(n)
    return usable if usable else list(hops)


def _pick_best_hop(from_node: str, destination: str, inbound: int | None = None) -> str | None:
    hops = world.best_next_hops(from_node, destination)
    if not hops:
        return None
    via = places._hint_via(from_node, destination)
    if via is not None and via != places.HINT_WILDCARD and via in hops:
        return via
    pool = _hops_with_non_uturn(from_node, hops, inbound)
    return random.choice(pool)


def _weighted_slack_hop(from_node: str, destination: str) -> str | None:
    hops = world.best_next_hops(from_node, destination)
    candidates = _reachable_first_hops(from_node, destination)
    if not candidates:
        return None
    weights = [
        BEST_NEIGHBOR_WEIGHT if n in hops else SLACK_NEIGHBOR_WEIGHT for n in candidates
    ]
    return random.choices(candidates, weights=weights, k=1)[0]


def _pick_next_node(
    from_node: str,
    destination: str,
    *,
    allow_slack: bool = False,
    inbound: int | None = None,
) -> str | None:
    via = places._hint_via(from_node, destination)
    named = via is not None and via != places.HINT_WILDCARD
    if allow_slack:
        if (
            named
            and via in _outgoing_neighbours(from_node)
            and _neighbour_reaches(via, destination)
        ):
            return via
        if not world.is_intersection(from_node):
            candidates = _reachable_first_hops(from_node, destination)
            if len(candidates) > 1:
                picked = _weighted_slack_hop(from_node, destination)
                if picked is not None:
                    return picked
    return _pick_best_hop(from_node, destination, inbound)


def _pick_lane(
    from_node: str,
    next_node: str,
    inbound_lane_index: int | None,
    *,
    origin: str | None = None,
    lane_usage_counts: dict[tuple[str, int], int] | None = None,
    out_lane_balance_coeff: float = 0.0,
) -> int | None:
    outgoing = [i for i in world.outgoing_lanes(from_node) if world.lane_exit_node(i) == next_node]
    candidates = places._candidates_without_uturn(inbound_lane_index, outgoing)
    if not candidates:
        return None
    if inbound_lane_index is None and origin and lane_usage_counts and out_lane_balance_coeff > 0.0:
        max_use = max(lane_usage_counts.get((origin, lane), 0) for lane in candidates)
        weights = [
            1.0 + out_lane_balance_coeff * (max_use - lane_usage_counts.get((origin, lane), 0))
            for lane in candidates
        ]
        return random.choices(candidates, weights=weights, k=1)[0]
    return random.choice(candidates)


def plan_route(
    origin: str,
    destination: str,
    *,
    lane_usage_counts: dict[tuple[str, int], int] | None = None,
    out_lane_balance_coeff: float = 0.0,
) -> tuple[RouteStep, ...] | None:
    """Build origin → … → destination. None if unreachable. One compute; no fullness retry."""
    if not origin or not destination or origin == destination:
        return None
    if not world.destination_reachable(origin, destination):
        return None
    steps: list[RouteStep] = [RouteStep(KIND_PLACE, origin)]
    current = origin
    inbound: int | None = None
    for _ in range(MAX_ROUTE_HOPS):
        if current == destination:
            return tuple(steps)
        nxt = _pick_next_node(
            current, destination, allow_slack=inbound is None, inbound=inbound
        )
        if nxt is None:
            return None
        lane = _pick_lane(
            current,
            nxt,
            inbound,
            origin=origin if inbound is None else None,
            lane_usage_counts=lane_usage_counts,
            out_lane_balance_coeff=out_lane_balance_coeff,
        )
        if lane is None:
            return None
        # A dangling lane reaches its node only by stepping onto a stepsister,
        # so every lane of the corridor gets its own step.
        corridor = world.corridor_after(lane)
        for leg in corridor:
            steps.append(RouteStep(KIND_LANE, leg))
        if world.is_intersection(nxt):
            steps.append(RouteStep(KIND_INTERSECTION, nxt))
        else:
            steps.append(RouteStep(KIND_PLACE, nxt))
        inbound = corridor[-1]
        current = nxt
    return None


def current_node(car) -> str:
    if getattr(car, "motion_mode", "lane") == "path":
        return world.lane_traffic_out(car.lane_index)
    return world.lane_entry_node(car.lane_index)


def lane_step_index(route: tuple[RouteStep, ...], lane_index: int, after: int = -1) -> int | None:
    for i, step in enumerate(route):
        if i <= after:
            continue
        if step.kind == KIND_LANE and int(step.ref) == lane_index:
            return i
    return None
