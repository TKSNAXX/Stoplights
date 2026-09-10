"""
Civilian trip itineraries: place / lane / intersection steps, planned at spawn.

Walks rebuild-cached best_next_hops and scenario route_hints. Police stay greedy.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from sim import places, world

KIND_PLACE = "place"
KIND_LANE = "lane"
KIND_INTERSECTION = "intersection"

MAX_ROUTE_HOPS = 32


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


def _pick_next_node(from_node: str, destination: str) -> str | None:
    hops = world.best_next_hops(from_node, destination)
    if not hops:
        return None
    via = places._hint_via(from_node, destination)
    if via is not None and via in hops:
        return via
    return random.choice(tuple(hops))


def _pick_lane(
    from_node: str,
    next_node: str,
    inbound_lane_index: int | None,
    *,
    origin: str | None = None,
    lane_usage_counts: dict[tuple[str, int], int] | None = None,
    out_lane_balance_coeff: float = 0.0,
) -> int | None:
    outgoing = [i for i in world.outgoing_lanes(from_node) if world.lane_traffic_out(i) == next_node]
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
        nxt = _pick_next_node(current, destination)
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
        steps.append(RouteStep(KIND_LANE, lane))
        if world.is_intersection(nxt):
            steps.append(RouteStep(KIND_INTERSECTION, nxt))
        else:
            steps.append(RouteStep(KIND_PLACE, nxt))
        inbound = lane
        current = nxt
    return None


def current_node(car) -> str:
    if getattr(car, "motion_mode", "lane") == "path":
        return world.lane_traffic_out(car.lane_index)
    return world.lane_traffic_in(car.lane_index)


def lane_step_index(route: tuple[RouteStep, ...], lane_index: int, after: int = -1) -> int | None:
    for i, step in enumerate(route):
        if i <= after:
            continue
        if step.kind == KIND_LANE and int(step.ref) == lane_index:
            return i
    return None
