"""
Per-car situation snapshot: current feature, next maneuver, lane/sister counts.

Filled each tick after movement. Display-only; does not change driving.
"""
from __future__ import annotations

from sim import places, routes, world
from sim.junction import (
    LEFT_OF,
    OPPOSITE_CARDINAL,
    RIGHT_OF,
    overlay_type_for_sides,
    tee_layout_for_sides,
)
from sim.occupancy import Occupancy

UNKNOWN = "—"


def turn_side(in_dir: str, out_dir: str) -> str | None:
    """straight / left / right from inbound heading to outbound heading, or None."""
    if not in_dir or not out_dir:
        return None
    if out_dir == OPPOSITE_CARDINAL.get(in_dir):
        return "straight"
    if LEFT_OF.get(in_dir) == out_dir:
        return "left"
    if RIGHT_OF.get(in_dir) == out_dir:
        return "right"
    return None


def classify_step(lane_index: int, target_lane: int) -> str:
    """Label for the next lane of a corridor: a crossing, or a road carried on."""
    if world.lane_daughter(lane_index) == target_lane:
        return f"continue lane {target_lane}"
    step = world.stepsister_step(lane_index)
    if step is not None and step[0] == target_lane:
        return f"step {step[1]}"
    return f"step lane {target_lane}"


def classify_place(place_id: str, destination: str) -> str:
    if place_id == destination:
        return "place destination"
    return "place passthru"


def active_sides(intersection_key: str) -> frozenset[str]:
    """Connected faces from incoming approach and outgoing exit cardinals."""
    sides: set[str] = set()
    for i in world.incoming_lanes(intersection_key):
        d = world.lane_direction(i)
        face = OPPOSITE_CARDINAL.get(d)
        if face:
            sides.add(face)
    for i in world.outgoing_lanes(intersection_key):
        d = world.lane_direction(i)
        if d in OPPOSITE_CARDINAL:
            sides.add(d)
    return frozenset(sides)


def classify_intersection_maneuver(
    overlay: str,
    sides: frozenset[str],
    in_dir: str,
    out_dir: str,
) -> str:
    """Maneuver label from overlay kind and inbound/outbound headings."""
    side = turn_side(in_dir, out_dir)
    if overlay == places.INTERSECTION_TYPE_CORNER:
        if side in ("left", "right"):
            return f"corner {side}"
        return UNKNOWN
    if overlay == places.INTERSECTION_TYPE_CROSS:
        if side == "straight":
            return "cross straight"
        if side in ("left", "right"):
            return f"cross {side}"
        return UNKNOWN
    if overlay == places.INTERSECTION_TYPE_TEE:
        return _tee_label(sides, in_dir, out_dir, side)
    if overlay == places.INTERSECTION_TYPE_STRAIGHT:
        return "straight"
    return UNKNOWN


def classify_maneuver(in_lane: int, out_lane: int) -> str:
    node = world.lane_traffic_out(in_lane)
    if not world.is_intersection(node):
        return UNKNOWN
    sides = active_sides(node)
    overlay = overlay_type_for_sides(sides)
    return classify_intersection_maneuver(
        overlay,
        sides,
        world.lane_direction(in_lane),
        world.lane_direction(out_lane),
    )


def refresh_situations(cars_list: list, occupancy: Occupancy) -> None:
    occupancy.sort_lanes()
    for car in cars_list:
        _fill_car(car, occupancy)


def _tee_label(
    sides: frozenset[str],
    in_dir: str,
    out_dir: str,
    side: str | None,
) -> str:
    _axis, stem = tee_layout_for_sides(sides)
    approach = OPPOSITE_CARDINAL.get(in_dir, "")
    if approach == stem:
        if side in ("left", "right"):
            return f"tee straight {side}"
        return UNKNOWN
    if out_dir == stem:
        if side in ("left", "right"):
            return f"tee branch {side}"
        return UNKNOWN
    return "tee straight"


def _planned_out_lane(car) -> int | None:
    pending = getattr(car, "pending_out_lane_index", None)
    if pending is not None:
        return int(pending)
    route = getattr(car, "route", ()) or ()
    idx = int(getattr(car, "route_index", 0))
    pair = routes.out_lane_after(route, idx)
    if pair is not None:
        return pair[0]
    return None


def _on_feature(car) -> str:
    if getattr(car, "motion_mode", "lane") == "path":
        cell = getattr(car, "intersection_cell", None) or car.current_cell()
        keys = world.intersections_at_cell(cell) if cell is not None else ()
        if keys:
            return f"intersection {keys[0]}"
        node = world.lane_traffic_out(car.lane_index)
        if node:
            return f"intersection {node}"
        return UNKNOWN
    tin = world.lane_traffic_in(car.lane_index)
    tout = world.lane_traffic_out(car.lane_index)
    return f"lane {car.lane_index} {tin}->{tout}"


def _next_feature(car) -> str:
    route = getattr(car, "route", ()) or ()
    idx = int(getattr(car, "route_index", 0))
    if getattr(car, "motion_mode", "lane") == "path":
        out = _planned_out_lane(car)
        if out is None:
            return UNKNOWN
        return classify_maneuver(car.lane_index, out)

    if route:
        place = routes.place_after_lane(route, idx)
        if place is not None:
            return classify_place(place, getattr(car, "destination", ""))
        step = routes.step_lane_after(route, idx)
        if step is not None:
            return classify_step(car.lane_index, step[0])
        pair = routes.out_lane_after(route, idx)
        if pair is not None:
            return classify_maneuver(car.lane_index, pair[0])

    pending = getattr(car, "pending_out_lane_index", None)
    if pending is not None:
        return classify_maneuver(car.lane_index, int(pending))

    node = world.lane_traffic_out(car.lane_index)
    if not node:
        return UNKNOWN
    if not world.is_intersection(node):
        return classify_place(node, getattr(car, "destination", ""))
    return UNKNOWN


def _merge_state(car) -> str:
    side = getattr(car, "merge_side", "")
    if getattr(car, "motion_mode", "lane") != "merge" or not side:
        return UNKNOWN
    reason = getattr(car, "merge_reason", "")
    return f"{side} ({reason})" if reason else side


def _ahead_behind(car, others: list) -> tuple[int, int]:
    pos = int(getattr(car, "position_in_lane", 0))
    ahead = 0
    behind = 0
    for other in others:
        if other is car:
            continue
        op = int(getattr(other, "position_in_lane", 0))
        if op > pos:
            ahead += 1
        elif op < pos:
            behind += 1
    return ahead, behind


def _fill_car(car, occupancy: Occupancy) -> None:
    car.on_feature = _on_feature(car)
    car.next_feature = _next_feature(car)
    car.merge_state = _merge_state(car)
    if getattr(car, "motion_mode", "lane") != "lane":
        car.cars_ahead = None
        car.cars_behind = None
        car.next_feature_cars = None
        car.sister_ahead = None
        car.sister_behind = None
        return

    ahead, behind = _ahead_behind(car, occupancy.cars_on_lane(car.lane_index))
    car.cars_ahead = ahead
    car.cars_behind = behind
    if ahead == 0:
        node = world.lane_traffic_out(car.lane_index)
        if world.is_intersection(node):
            car.next_feature_cars = len(occupancy.cars_in_intersection(node))
        else:
            car.next_feature_cars = 0
    else:
        car.next_feature_cars = None

    sister = world.sister_lane(car.lane_index)
    if sister is None:
        car.sister_ahead = None
        car.sister_behind = None
        return
    s_ahead, s_behind = _ahead_behind(car, occupancy.cars_on_lane(sister))
    car.sister_ahead = s_ahead
    car.sister_behind = s_behind
