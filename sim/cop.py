"""
Police car for gridlock response.

One cop owns a beat of junctions joined by a short lane, but he only works the
junction he is standing at: its mouths, and the cars in its box. He spawns from
a place lane.
Home end of a lane is derived from traffic_in/traffic_out (place end), not map names.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from sim.constants import INBOUND_TAIL_CELLS, POLICE_SPEED
from sim.movement import pose_for_lane_position
from sim.occupancy import occupancy_from
from sim.paths import direction_index_8_from_tangent, path_length, path_position, path_tangent
from sim.places import choose_next_lane_from_node
from sim import routes, world

DISMISS_LINGER = 5.0
# How long the one-side signal fades out to every approach flowing, before he leaves.
FADE_SECONDS = 8.0
# One cop owns a whole beat (a junction plus the neighbours a short lane joins it to).
COPS_PER_INTERSECTION = 1
# Cars one approach may send before he closes it, and the longest that green lasts.
RELEASE_CARS = 4
RELEASE_SECONDS = 8.0
# Gives up when the box cannot empty, then stays away so he does not respawn at once.
MAX_HOLD_SECONDS = 30.0
RESPAWN_COOLDOWN = 20.0
# Share of normal speed for the creep. The old cyan exemption, kept slow on purpose.
DRAIN_SPEED = 0.3
# A feed-lane car is stopped only this close to the mouth, in fractional grid cells.
HOLD_NEAR_CELLS = 0.5
_NO_EXIT = float("inf")

LIGHT_CYCLE = [(255, 255, 255), (60, 140, 220), (255, 255, 255), (220, 80, 80)]
LIGHT_PHASE_DURATION = 0.25 / 3


def _home_at_lane_start(lane_idx: int) -> bool:
    """
    Home is the place end of the lane.
    If traffic_in is a place, home is pos 0; if traffic_out is a place, home is len-1.
    """
    tin = world.lane_traffic_in(lane_idx)
    tout = world.lane_traffic_out(lane_idx)
    if tin and not world.is_intersection(tin):
        return True
    if tout and not world.is_intersection(tout):
        return False
    # Fallback: treat end toward intersection as home-at-len-1 (legacy Shopping-style).
    return False


def _intersection_center(key: str) -> tuple[float, float]:
    cells = world.get_intersection_cells_by_key(key)
    if not cells:
        return (0.0, 0.0)
    return (
        sum(c[0] for c in cells) / len(cells),
        sum(c[1] for c in cells) / len(cells),
    )


def _place_center(place_id: str) -> tuple[float, float] | None:
    rect = world.get_place_rects().get(place_id)
    if not rect:
        return None
    x = float(rect.get("x", 0))
    y = float(rect.get("y", 0))
    w = float(rect.get("w", 0))
    h = float(rect.get("h", 0))
    return (x + w / 2.0, y + h / 2.0)


def place_on_lane_for_intersection(lane_idx: int, intersection_id: str) -> str | None:
    """Place id at the other end of a lane that touches this intersection, else None."""
    tin = world.lane_traffic_in(lane_idx)
    tout = world.lane_traffic_out(lane_idx)
    if tin == intersection_id and tout and not world.is_intersection(tout):
        return tout
    if tout == intersection_id and tin and not world.is_intersection(tin):
        return tin
    return None


def _path_car_in_box(car, intersection_id: str) -> bool:
    if getattr(car, "motion_mode", "lane") != "path":
        return False
    cell = car.current_cell()
    return cell is not None and world.cell_in_intersection(cell, intersection_id)


def _inbound_tail(car, intersection_id: str) -> bool:
    """True if the car is in the last INBOUND_TAIL_CELLS of a lane approaching this node."""
    if getattr(car, "motion_mode", "lane") == "path":
        return False
    if world.lane_traffic_out(car.lane_index) != intersection_id:
        return False
    lane = car.get_lane()
    if not lane:
        return False
    return car.position_in_lane >= max(0, len(lane) - INBOUND_TAIL_CELLS)


def in_node_jam(car, intersection_id: str) -> bool:
    """Path cars in the box, inbound tails, or path cars in short-hop attached boxes."""
    if _path_car_in_box(car, intersection_id) or _inbound_tail(car, intersection_id):
        return True
    return any(
        _path_car_in_box(car, other)
        for other in world.attached_intersections(intersection_id)
    )


def iter_node_jam_cars(occupancy, intersection_id: str):
    """Unique civilian cars in this node's jam set (box, inbound tails, attached boxes)."""
    occ = occupancy_from(occupancy)
    seen: set[int] = set()
    for car in occ.cars_in_intersection(intersection_id):
        ident = id(car)
        if ident in seen:
            continue
        seen.add(ident)
        yield car
    for other in world.attached_intersections(intersection_id):
        for car in occ.cars_in_intersection(other):
            ident = id(car)
            if ident in seen:
                continue
            seen.add(ident)
            yield car
    for lane_idx in world.incoming_lanes(intersection_id):
        lane = world.get_lane_cells(lane_idx)
        if not lane:
            continue
        thresh = max(0, len(lane) - INBOUND_TAIL_CELLS)
        for car in occ.cars_on_lane(lane_idx):
            if car.position_in_lane < thresh:
                continue
            ident = id(car)
            if ident in seen:
                continue
            seen.add(ident)
            yield car


def intersection_jam_score(occupancy, intersection_id: str) -> int:
    """Occupancy for spawn: this box + red inbound tails + path cars in short-hop attached boxes."""
    occ = occupancy_from(occupancy)
    score = 0
    counted: set[int] = set()
    for car in occ.cars_in_intersection(intersection_id):
        ident = id(car)
        if ident in counted:
            continue
        counted.add(ident)
        score += 1
    for other in world.attached_intersections(intersection_id):
        for car in occ.cars_in_intersection(other):
            ident = id(car)
            if ident in counted:
                continue
            counted.add(ident)
            score += 1
    for lane_idx in world.incoming_lanes(intersection_id):
        lane = world.get_lane_cells(lane_idx)
        if not lane:
            continue
        thresh = max(0, len(lane) - INBOUND_TAIL_CELLS)
        for car in occ.cars_on_lane(lane_idx):
            ident = id(car)
            if ident in counted:
                continue
            if car.position_in_lane >= thresh and getattr(car, "visibility_state", "green") == "red":
                counted.add(ident)
                score += 1
    return score


def intersection_dismiss_score(occupancy, intersection_id: str) -> int:
    """Remaining jam: red-in-box + red inbound tails + red path cars in short-hop attached boxes."""
    occ = occupancy_from(occupancy)
    score = 0
    counted: set[int] = set()
    for car in occ.cars_in_intersection(intersection_id):
        if getattr(car, "visibility_state", "green") != "red":
            continue
        ident = id(car)
        if ident in counted:
            continue
        counted.add(ident)
        score += 1
    for other in world.attached_intersections(intersection_id):
        for car in occ.cars_in_intersection(other):
            if getattr(car, "visibility_state", "green") != "red":
                continue
            ident = id(car)
            if ident in counted:
                continue
            counted.add(ident)
            score += 1
    for lane_idx in world.incoming_lanes(intersection_id):
        lane = world.get_lane_cells(lane_idx)
        if not lane:
            continue
        thresh = max(0, len(lane) - INBOUND_TAIL_CELLS)
        for car in occ.cars_on_lane(lane_idx):
            ident = id(car)
            if ident in counted:
                continue
            if car.position_in_lane >= thresh and getattr(car, "visibility_state", "green") == "red":
                counted.add(ident)
                score += 1
    return score


def pick_deploy_lane(intersection_id: str, used_lanes: set[int] | None = None) -> int | None:
    """Nearest place-connected lane into the node; else any unused inbound."""
    used = set(used_lanes or ())
    ix, iy = _intersection_center(intersection_id)
    placed: list[tuple[float, int]] = []
    inbound_fallback: list[int] = []
    touching = list(world.incoming_lanes(intersection_id)) + list(world.outgoing_lanes(intersection_id))
    seen_lanes: set[int] = set()
    for i in touching:
        if i in used or i in seen_lanes:
            continue
        seen_lanes.add(i)
        place_id = place_on_lane_for_intersection(i, intersection_id)
        if place_id:
            pc = _place_center(place_id)
            if pc is None:
                continue
            dist = (pc[0] - ix) ** 2 + (pc[1] - iy) ** 2
            placed.append((dist, i))
        elif world.lane_traffic_out(i) == intersection_id:
            inbound_fallback.append(i)
    if placed:
        placed.sort(key=lambda t: (t[0], t[1]))
        return placed[0][1]
    if inbound_fallback:
        inbound_fallback.sort()
        return inbound_fallback[0]
    return None


def _lane_place(lane_idx: int) -> str:
    """Place at either end of a lane, or "" when both ends are junctions."""
    tin = world.lane_traffic_in(lane_idx)
    tout = world.lane_traffic_out(lane_idx)
    if tin and not world.is_intersection(tin):
        return tin
    if tout and not world.is_intersection(tout):
        return tout
    return ""


def _lane_touches(lane_idx: int, node: str) -> bool:
    return world.lane_traffic_in(lane_idx) == node or world.lane_traffic_out(lane_idx) == node


def beats() -> tuple[frozenset[str], ...]:
    """
    One entry per cluster of junctions joined by a lane shorter than the inbound tail.

    The link is the undirected form of attached_intersections, closed over the chain,
    so a street of several short hops is one beat rather than a cop on every box.
    """
    nodes = list(world.get_intersection_keys())
    neighbours: dict[str, set[str]] = {node: set() for node in nodes}
    for node in nodes:
        for other in world.attached_intersections(node):
            neighbours.setdefault(node, set()).add(other)
            neighbours.setdefault(other, set()).add(node)
    seen: set[str] = set()
    found: list[frozenset[str]] = []
    for node in nodes:
        if node in seen:
            continue
        stack = [node]
        comp: set[str] = set()
        while stack:
            current = stack.pop()
            if current in comp:
                continue
            comp.add(current)
            stack.extend(neighbours.get(current, ()) - comp)
        seen |= comp
        found.append(frozenset(comp))
    return tuple(found)


def beat_of(node: str) -> frozenset[str]:
    for beat in beats():
        if node in beat:
            return beat
    return frozenset((node,))


def beat_key(node: str) -> tuple[str, ...]:
    """Stable cooldown key for the beat containing node."""
    return tuple(sorted(beat_of(node)))


def approach_groups(node: str) -> dict[str, tuple[int, ...]]:
    """Inbound lanes of a junction, grouped by the direction they travel."""
    groups: dict[str, list[int]] = {}
    for lane in world.incoming_lanes(node):
        groups.setdefault(world.lane_direction(lane) or "?", []).append(lane)
    return {direction: tuple(lanes) for direction, lanes in groups.items()}


def _tail_threshold(lane_idx: int) -> int:
    lane = world.get_lane_cells(lane_idx)
    if not lane:
        return 0
    return max(0, len(lane) - INBOUND_TAIL_CELLS)


def _short_inbound(lane_idx: int) -> bool:
    lane = world.get_lane_cells(lane_idx)
    return bool(lane) and len(lane) < INBOUND_TAIL_CELLS


def _car_stopped(car) -> bool:
    if getattr(car, "impasse_active", False):
        return True
    if getattr(car, "speed_scale", 1.0) <= 0.0:
        return True
    return getattr(car, "visibility_state", "green") == "red"


def _approach_dir(car, node: str) -> str:
    """Direction of the approach this car is on, as seen by node."""
    lane_idx = getattr(car, "lane_index", -1)
    if world.lane_traffic_out(lane_idx) == node:
        return world.lane_direction(lane_idx)
    cell = car.current_cell()
    for other in world.attached_intersections(node):
        if cell is None or not world.cell_in_intersection(cell, other):
            continue
        for lane in world.incoming_lanes(node):
            if world.lane_traffic_in(lane) == other:
                return world.lane_direction(lane)
    return ""


def approach_queue_count(occupancy, _node: str, lanes: tuple[int, ...]) -> int:
    """Cars waiting on these lanes, in the tail only. The junction upstream is not his."""
    occ = occupancy_from(occupancy)
    seen: set[int] = set()
    count = 0
    for lane in lanes:
        thresh = _tail_threshold(lane)
        for car in occ.cars_on_lane(lane):
            if getattr(car, "motion_mode", "lane") == "path":
                continue
            if car.position_in_lane < thresh:
                continue
            ident = id(car)
            if ident in seen:
                continue
            seen.add(ident)
            count += 1
    return count


def approach_is_stopped(occupancy, node: str, lanes: tuple[int, ...]) -> bool:
    """True when this approach has a stopped car in its tail, or in the source box of a short hop."""
    occ = occupancy_from(occupancy)
    for lane in lanes:
        thresh = _tail_threshold(lane)
        for car in occ.cars_on_lane(lane):
            if getattr(car, "motion_mode", "lane") == "path":
                continue
            if car.position_in_lane >= thresh and _car_stopped(car):
                return True
        if not _short_inbound(lane):
            continue
        src = world.lane_traffic_in(lane)
        if not src or not world.is_intersection(src):
            continue
        for car in occ.cars_in_intersection(src):
            if _car_stopped(car):
                return True
    return False


def stopped_approach_count(occupancy, node: str) -> int:
    groups = approach_groups(node)
    return sum(1 for lanes in groups.values() if approach_is_stopped(occupancy, node, lanes))


def _stuck_in_jam(occupancy, node: str) -> bool:
    """An impasse, or a stopped car inside this box or a one-hop neighbour box."""
    for car in iter_node_jam_cars(occupancy, node):
        if getattr(car, "impasse_active", False):
            return True
        in_box = _path_car_in_box(car, node) or any(
            _path_car_in_box(car, other) for other in world.attached_intersections(node)
        )
        if in_box and _car_stopped(car):
            return True
    return False


def junction_deadlocked(occupancy, node: str) -> bool:
    """Two or more approaches stopped, and someone in the jam actually stuck."""
    if stopped_approach_count(occupancy, node) < 2:
        return False
    return _stuck_in_jam(occupancy, node)


def iter_box_cars(occupancy, node: str):
    """Path cars in this junction only. The neighbour box is another cop's problem."""
    occ = occupancy_from(occupancy)
    seen: set[int] = set()
    for car in occ.cars_in_intersection(node):
        if getattr(car, "motion_mode", "lane") != "path":
            continue
        ident = id(car)
        if ident in seen:
            continue
        seen.add(ident)
        yield car


def waiting_approaches(occupancy, node: str) -> dict[str, int]:
    """Directions that still have a car queued, mapped to how many."""
    waiting: dict[str, int] = {}
    for direction, lanes in approach_groups(node).items():
        count = approach_queue_count(occupancy, node, lanes)
        if count > 0:
            waiting[direction] = count
    return waiting


def next_beat_target(occupancy, node: str) -> str | None:
    """Another deadlocked member of this beat, the one with the most stopped approaches."""
    best: str | None = None
    best_key: tuple[int, str] | None = None
    for member in beat_of(node):
        if member == node or not junction_deadlocked(occupancy, member):
            continue
        key = (stopped_approach_count(occupancy, member), member)
        if best_key is None or key > best_key:
            best_key = key
            best = member
    return best


def pick_beat_deploy_lane(beat: frozenset[str], target: str) -> int | None:
    """
    Place-connected lane anywhere in the beat, nearest place to the deadlocked member.

    A junction in the middle of a short chain often has no place of its own. Spawning
    on the connector then drives the cop away from the box he was called to.
    """
    tx, ty = _intersection_center(target)
    placed: list[tuple[float, int]] = []
    for node in beat:
        seen: set[int] = set()
        touching = list(world.incoming_lanes(node)) + list(world.outgoing_lanes(node))
        for lane in touching:
            if lane in seen:
                continue
            seen.add(lane)
            place_id = place_on_lane_for_intersection(lane, node) or _lane_place(lane)
            if not place_id or world.is_intersection(place_id):
                continue
            pc = _place_center(place_id)
            if pc is None:
                continue
            dist = (pc[0] - tx) ** 2 + (pc[1] - ty) ** 2
            placed.append((dist, lane))
    if placed:
        placed.sort()
        return placed[0][1]
    return pick_deploy_lane(target)


def advance_signal(police: PoliceCar, dt: float, occupancy) -> str:
    """
    Advance a holding cop through Clear and Green.

    Returns "" to keep holding, "walk" to another deadlocked junction in the beat
    (destination on police.walk_target), "home" when the beat is clear, or "giveup"
    when the box will not empty.
    """
    police.hold_time += dt
    node = police.target_intersection
    box = list(iter_box_cars(occupancy, node))
    waiting = waiting_approaches(occupancy, node)

    if police.hold_time >= MAX_HOLD_SECONDS and police.phase != "fade":
        _begin_fade(police, node, giveup=True)

    if police.phase == "fade":
        return _advance_fade(police, dt, node, occupancy, box)

    if police.phase == "green":
        police.phase_time += dt
        _note_entries(police, occupancy)
        sent_enough = len(police.entered_ids) >= RELEASE_CARS
        held_long_enough = police.phase_time >= RELEASE_SECONDS
        approach_empty = waiting.get(police.green_dir, 0) == 0
        if sent_enough or held_long_enough or approach_empty:
            police.phase = "clear"
            police.green_dir = ""
            police.entered_ids = set()
            police.phase_time = 0.0
            police.linger_timer = 0.0
        return ""

    if box or waiting:
        police.linger_timer = 0.0
        if not box and waiting:
            direction = max(waiting, key=lambda name: (waiting[name], name))
            police.phase = "green"
            police.green_dir = direction
            police.entered_ids = set()
            police.phase_time = 0.0
            police.initial_clear = False
        return ""

    _begin_fade(police, node, giveup=False)
    return _advance_fade(police, dt, node, occupancy, box)


def _begin_fade(police: PoliceCar, node: str, giveup: bool) -> None:
    """Start easing every approach up to full speed. One side stays explicit."""
    police.phase = "fade"
    police.fade_time = 0.0
    police.fade_ready = False
    police.fade_giveup = giveup
    police.fade_dirs = tuple(sorted(approach_groups(node)))
    police.green_dir = police.fade_dirs[0] if police.fade_dirs else ""
    police.initial_clear = False
    police.linger_timer = 0.0


def _advance_fade(police: PoliceCar, dt: float, node: str, occupancy, box: list) -> str:
    """
    Walk the explicit green through the sides while the others speed up.

    The tick that reaches the end leaves him holding at full speed. The next tick
    sends him home, so dropping the flags changes nothing.
    """
    if not police.fade_giveup and box:
        police.phase = "clear"
        police.fade_time = 0.0
        police.fade_ready = False
        police.fade_giveup = False
        police.fade_dirs = ()
        police.green_dir = ""
        police.linger_timer = 0.0
        return ""
    if police.fade_ready:
        if police.fade_giveup:
            return "giveup"
        other = next_beat_target(occupancy, node)
        if other:
            police.walk_target = other
            return "walk"
        return "home"
    police.fade_time += dt
    if police.fade_time >= FADE_SECONDS:
        police.fade_time = FADE_SECONDS
        police.fade_ready = True
    return ""


def side_release(police: PoliceCar, direction: str) -> float:
    """Speed for one approach during a fade: 1 once featured, otherwise the progress."""
    dirs = police.fade_dirs
    span = FADE_SECONDS if FADE_SECONDS > 0 else 1.0
    progress = max(0.0, min(1.0, police.fade_time / span))
    if not dirs or progress >= 1.0:
        return 1.0
    featured = min(len(dirs) - 1, int(progress * len(dirs)))
    try:
        index = dirs.index(direction)
    except ValueError:
        return progress
    if index <= featured:
        return 1.0
    return progress


def _note_entries(police: PoliceCar, occupancy) -> None:
    """Remember cars that have taken the open approach, including after they leave the box."""
    if police.phase != "green" or not police.green_dir:
        return
    node = police.target_intersection
    for car in occupancy_from(occupancy).iter_path_cars():
        lane_idx = getattr(car, "lane_index", -1)
        if world.lane_traffic_out(lane_idx) != node:
            continue
        if world.lane_direction(lane_idx) != police.green_dir:
            continue
        police.entered_ids.add(id(car))


def _pose_xy(car) -> tuple[float, float] | None:
    gx = getattr(car, "pose_gx", None)
    gy = getattr(car, "pose_gy", None)
    if gx is not None and gy is not None:
        return (float(gx), float(gy))
    cell = car.current_cell()
    if cell is None:
        return None
    return (float(cell[0]), float(cell[1]))


def _exit_cell(car, node: str) -> tuple[float, float] | None:
    """Where this car is headed: the out-lane mouth in the box, or the lane's last cell."""
    if getattr(car, "motion_mode", "lane") == "path":
        out = getattr(car, "pending_out_lane_index", None)
        if out is None and getattr(car, "route", ()):
            planned = routes.out_lane_after(car.route, int(getattr(car, "route_index", 0)))
            if planned is not None:
                out = planned[0]
        if out is None:
            return None
        cells = world.get_lane_cells(int(out))
        if not cells:
            return None
        return (float(cells[0][0]), float(cells[0][1]))
    if world.lane_traffic_out(getattr(car, "lane_index", -1)) == node:
        lane = world.get_lane_cells(car.lane_index)
        if lane:
            return (float(lane[-1][0]), float(lane[-1][1]))
    return None


def drain_cap(node: str) -> int:
    """Cars that may creep at once: the intersection's size, used directly."""
    return max(1, world.intersection_size(node))


def cells_to_exit(car, node: str) -> float:
    """Fractional grid cells from the car's pose to the point it is driving toward."""
    start = _pose_xy(car)
    end = _exit_cell(car, node)
    if start is None or end is None:
        return _NO_EXIT
    return math.hypot(end[0] - start[0], end[1] - start[1])


def _fill_drain(police: PoliceCar, box_cars: list, node: str) -> None:
    """Keep a few cars creeping until they leave, then hand the slot to the nearest exit."""
    present = {id(car) for car in box_cars}
    police.drain_ids = {ident for ident in police.drain_ids if ident in present}
    cap = drain_cap(node)
    if len(police.drain_ids) >= cap:
        return
    waiting = [car for car in box_cars if id(car) not in police.drain_ids]
    waiting.sort(key=lambda car: (cells_to_exit(car, node), id(car)))
    for car in waiting:
        if len(police.drain_ids) >= cap:
            break
        police.drain_ids.add(id(car))


def _set_release(car, speed: float) -> None:
    """0 stops, a fraction trickles, 1 is the full-speed wave."""
    car.police_release = max(0.0, min(1.0, speed))
    if car.police_release >= 1.0:
        car.police_held = False
        car.police_clear = "wave"
    elif car.police_release <= 0.0:
        car.police_held = True
        car.police_clear = ""
    else:
        car.police_held = False
        car.police_clear = ""


def _mark_fade(police: PoliceCar, occupancy, node: str) -> None:
    """Featured sides flow. Sides not yet reached move at the fade's progress."""
    occ = occupancy_from(occupancy)
    for direction, lanes in approach_groups(node).items():
        _apply_side_speed(occ, node, lanes, side_release(police, direction))
    for car in iter_box_cars(occ, node):
        _set_release(car, side_release(police, _approach_dir(car, node)))


def _apply_side_speed(occ, node: str, lanes: tuple[int, ...], speed: float) -> None:
    for lane in lanes:
        thresh = _tail_threshold(lane)
        for car in occ.cars_on_lane(lane):
            if getattr(car, "motion_mode", "lane") == "path":
                continue
            if car.position_in_lane < thresh:
                continue
            if speed >= 1.0 or cells_to_exit(car, node) <= HOLD_NEAR_CELLS:
                _set_release(car, speed)


def mark_holding(police: PoliceCar, occupancy) -> None:
    """Hold every approach but the open one. On arrival, a few cars creep out at a time."""
    if police.state != "holding":
        return
    node = police.target_intersection
    if police.phase == "fade":
        _mark_fade(police, occupancy, node)
        return
    green = police.green_dir if police.phase == "green" else ""
    box_cars = list(iter_box_cars(occupancy, node))
    if police.initial_clear:
        _fill_drain(police, box_cars, node)
    for car in box_cars:
        if police.initial_clear:
            if id(car) in police.drain_ids:
                car.police_held = False
                car.police_clear = "drain"
            else:
                car.police_clear = ""
                car.police_held = True
            continue
        in_this = _path_car_in_box(car, node)
        if in_this or (green and _approach_dir(car, node) == green):
            car.police_held = False
            car.police_clear = "wave"
        else:
            car.police_clear = ""
            car.police_held = True
    for direction, lanes in approach_groups(node).items():
        released = bool(green) and direction == green
        for lane in lanes:
            thresh = _tail_threshold(lane)
            for car in occupancy_from(occupancy).cars_on_lane(lane):
                if getattr(car, "motion_mode", "lane") == "path":
                    continue
                if car.position_in_lane < thresh:
                    continue
                if released:
                    car.police_held = False
                    if car.police_clear != "drain":
                        car.police_clear = "wave"
                elif cells_to_exit(car, node) <= HOLD_NEAR_CELLS:
                    car.police_clear = ""
                    car.police_held = True
                else:
                    car.police_clear = ""
                    car.police_held = False


def spawn_police(intersection_id: str, deploy_lane: int) -> PoliceCar:
    """New cop already deploying from the home end of deploy_lane."""
    home_place = place_on_lane_for_intersection(deploy_lane, intersection_id) or _lane_place(deploy_lane)
    car = PoliceCar(
        deploy_lane=deploy_lane,
        return_lane=deploy_lane,
        travel_lane=deploy_lane,
        target_intersection=intersection_id,
        current_node=intersection_id,
        dest_node=intersection_id,
        home_place=home_place,
        inbound_lane=deploy_lane,
        state="deploying",
        can_divert=True,
    )
    if not _lane_touches(deploy_lane, intersection_id) and home_place:
        # The place lane belongs to a neighbour. Route across the beat.
        car.routing = True
        car.current_node = home_place
        car.begin_hop(home_place, intersection_id, inbound=None)
        return car
    lane_len = car._lane_len(deploy_lane)
    home_at_0 = _home_at_lane_start(deploy_lane)
    if home_at_0:
        car.lane_pos = 0.0
        car.direction = 1
    else:
        car.lane_pos = float(max(0, lane_len - 1))
        car.direction = -1
    return car


@dataclass
class PoliceCar:
    """Police car state machine for gridlock response."""

    deploy_lane: int = 0
    return_lane: int = 0
    travel_lane: int = 0
    target_intersection: str = ""
    current_node: str = ""
    dest_node: str = ""
    home_place: str = ""
    inbound_lane: int | None = None
    state: str = "deploying"  # deploying | holding | diverting | returning | despawned
    motion: str = "lane"  # lane | path
    path_in: int = 0
    path_out: int = 0
    path_t: float = 0.0
    lane_pos: float = 0.0
    direction: int = 1
    light_phase: int = 0
    light_timer: float = 0.0
    red_zero_timer: float = 0.0
    linger_timer: float = 0.0
    depart_pending: bool = False
    can_divert: bool = True
    use_reverse: bool = False
    # Signal, while holding. Clear drains the box; green releases one direction.
    phase: str = "clear"
    green_dir: str = ""
    entered_ids: set[int] = field(default_factory=set)
    phase_time: float = 0.0
    hold_time: float = 0.0
    initial_clear: bool = True
    drain_ids: set[int] = field(default_factory=set)
    fade_dirs: tuple[str, ...] = ()
    fade_time: float = 0.0
    fade_ready: bool = False
    fade_giveup: bool = False
    routing: bool = False
    walk_target: str = ""

    def _current_lane(self) -> int:
        return self.travel_lane

    def _lane_len(self, lane_idx: int | None = None) -> int:
        idx = lane_idx if lane_idx is not None else self._current_lane()
        lane = world.get_lane_cells(idx)
        return len(lane) if lane else 0

    def at_mouth(self) -> bool:
        """True when at the intersection end of the travel lane (holding, or just arriving)."""
        if self.state == "holding":
            return True
        if self.state != "deploying" or self.motion != "lane":
            return False
        lane_len = self._lane_len(self.travel_lane)
        if lane_len < 2:
            return False
        home_at_0 = _home_at_lane_start(self.travel_lane)
        if home_at_0:
            return self.lane_pos >= lane_len - 1.0
        return self.lane_pos <= 0.5

    def get_pose(self) -> tuple[float, float, int]:
        if self.motion == "path":
            gx, gy = path_position(self.path_in, self.path_out, self.path_t)
            dx, dy = path_tangent(self.path_in, self.path_out, self.path_t)
            di = direction_index_8_from_tangent(dx, dy)
            return (gx, gy, di)
        lane_idx = self._current_lane()
        lane = world.get_lane_cells(lane_idx)
        if not lane:
            return (0.0, 0.0, 0)
        gx, gy, di = pose_for_lane_position(lane_idx, self.lane_pos, self.direction)
        if self.at_mouth() and self.target_intersection:
            cx, cy = _intersection_center(self.target_intersection)
            dx, dy = cx - gx, cy - gy
            if dx * dx + dy * dy > 1e-9:
                di = direction_index_8_from_tangent(dx, dy)
        return (gx, gy, di)

    def get_light_color(self) -> tuple[int, int, int]:
        if self.state == "returning":
            return (255, 255, 255)
        return LIGHT_CYCLE[self.light_phase % len(LIGHT_CYCLE)]

    def begin_holding(self, node: str) -> None:
        """Stand at the mouth of node and start a fresh clear of its box."""
        self.state = "holding"
        self.current_node = node
        self.target_intersection = node
        self.dest_node = node
        self.routing = False
        self.phase = "clear"
        self.green_dir = ""
        self.entered_ids = set()
        self.phase_time = 0.0
        self.hold_time = 0.0
        self.initial_clear = True
        self.drain_ids = set()
        self.fade_dirs = ()
        self.fade_time = 0.0
        self.fade_ready = False
        self.fade_giveup = False
        self.linger_timer = 0.0
        self.depart_pending = False
        self.walk_target = ""
        lane_len = self._lane_len(self.travel_lane)
        if lane_len and world.lane_traffic_in(self.travel_lane) == node:
            self.lane_pos = 0.0
            self.direction = -1
        else:
            self.lane_pos = float(max(0, lane_len - 1))
            self.direction = 1

    def begin_divert(self, dest_intersection: str) -> None:
        """Leave the current box toward dest; lights stay on. One tour only."""
        self.can_divert = False
        self.depart_pending = False
        self.use_reverse = False
        from_node = self.current_node or self.target_intersection
        self.state = "diverting"
        self.target_intersection = dest_intersection
        self.dest_node = dest_intersection
        self.routing = True
        self.begin_hop(from_node, dest_intersection, inbound=self.travel_lane)

    def begin_walk(self, dest_intersection: str) -> None:
        """Move to another junction in this beat. Does not spend the divert tour."""
        self.depart_pending = False
        self.use_reverse = False
        from_node = self.current_node or self.target_intersection
        self.state = "diverting"
        self.target_intersection = dest_intersection
        self.dest_node = dest_intersection
        self.routing = True
        self.walk_target = ""
        self.begin_hop(from_node, dest_intersection, inbound=self.travel_lane)

    def begin_return_home(self) -> None:
        """Lights off; graph-route to the original deploy place, or reverse if none."""
        was = self.state
        self.depart_pending = False
        self.state = "returning"
        if not self.home_place:
            self._begin_reverse_home()
            return
        self.dest_node = self.home_place
        self.use_reverse = False
        if self.motion == "path":
            return
        if was in ("holding", "deploying"):
            from_node = self.current_node or self.target_intersection
            self.begin_hop(from_node, self.home_place, inbound=self.travel_lane)

    def begin_hop(self, from_node: str, dest: str, inbound: int | None) -> None:
        """Pick the next out-lane toward dest; cross the box when leaving an intersection."""
        if not dest:
            self._begin_reverse_home()
            return
        out = choose_next_lane_from_node(from_node, dest, inbound)
        if out is None and inbound is not None:
            # A cop may turn around. The civilian rule forbids that lane.
            out = choose_next_lane_from_node(from_node, dest, None)
        if out is None:
            self._begin_reverse_home()
            return
        self.dest_node = dest
        sitting_on_outbound = (
            inbound is not None
            and world.is_intersection(from_node)
            and world.lane_traffic_in(inbound) == from_node
        )
        if sitting_on_outbound:
            self.motion = "lane"
            self.travel_lane = out
            self.return_lane = out
            self.lane_pos = 0.0
            self.direction = 1
            self.inbound_lane = out
            return
        if inbound is not None and world.is_intersection(from_node):
            self.motion = "path"
            self.path_in = inbound
            self.path_out = out
            self.path_t = 0.0
            return
        self.motion = "lane"
        self.travel_lane = out
        self.return_lane = out
        self.lane_pos = 0.0
        self.direction = 1
        self.inbound_lane = out

    def _begin_reverse_home(self) -> None:
        """Fallback: reverse along the current/original deploy lane to its place end."""
        self.state = "returning"
        self.use_reverse = True
        self.motion = "lane"
        self.travel_lane = self.deploy_lane
        self.return_lane = self.deploy_lane
        lane_len = self._lane_len(self.deploy_lane)
        home_at_0 = _home_at_lane_start(self.deploy_lane)
        if home_at_0:
            self.lane_pos = float(max(0, lane_len - 1))
            self.direction = -1
        else:
            self.lane_pos = 0.0
            self.direction = 1

    def _advance_path(self, dt: float) -> None:
        length = max(0.1, path_length(self.path_in, self.path_out))
        self.path_t += POLICE_SPEED * dt / length
        if self.path_t < 1.0:
            return
        self.motion = "lane"
        self.travel_lane = self.path_out
        self.return_lane = self.path_out
        self.lane_pos = 0.0
        self.direction = 1
        self.inbound_lane = self.path_out
        self.path_t = 1.0

    def _arrive_at_node(self, node: str | None) -> None:
        if not node:
            self.state = "despawned"
            return
        if self.use_reverse:
            if not world.is_intersection(node):
                self.state = "despawned"
            return
        if not world.is_intersection(node):
            if self.state == "returning" and node == (self.dest_node or self.home_place):
                self.state = "despawned"
                return
            self.current_node = node
            self.begin_hop(node, self.dest_node, inbound=None)
            return
        self.current_node = node
        if self.state in ("diverting", "deploying") and node == self.dest_node:
            self.begin_holding(node)
            return
        self.begin_hop(node, self.dest_node, inbound=self.travel_lane)

    def _advance_lane(self, dt: float) -> None:
        lane_len = self._lane_len()
        if lane_len < 2:
            self.state = "despawned"
            return
        self.lane_pos += POLICE_SPEED * dt * self.direction
        if self.direction >= 0:
            if self.lane_pos >= lane_len - 1.0:
                self.lane_pos = float(lane_len - 1)
                self._arrive_at_node(world.lane_traffic_out(self.travel_lane))
            else:
                self.lane_pos = min(float(lane_len - 1), self.lane_pos)
        else:
            if self.lane_pos <= 0.5:
                self.lane_pos = 0.0
                self._arrive_at_node(world.lane_traffic_in(self.travel_lane))
            else:
                self.lane_pos = max(0.0, self.lane_pos)

    def _advance_motion(self, dt: float) -> None:
        if self.motion == "path":
            self._advance_path(dt)
        else:
            self._advance_lane(dt)

    def tick(self, dt: float, node_score: int = 0) -> None:
        """Move and flash. Holding decisions are advance_signal; node_score is unused."""
        del node_score
        if self.motion == "lane":
            lane_len = self._lane_len()
            if lane_len < 2:
                self.state = "despawned"
                return

        if self.state != "returning":
            self.light_timer += dt
            while self.light_timer >= LIGHT_PHASE_DURATION:
                self.light_timer -= LIGHT_PHASE_DURATION
                self.light_phase = (self.light_phase + 1) % len(LIGHT_CYCLE)

        if self.state in ("despawned", "holding"):
            return

        if self.state == "deploying" and not self.routing:
            lane_len = self._lane_len(self.travel_lane)
            home_at_0 = _home_at_lane_start(self.travel_lane)
            if home_at_0:
                arrived = self.lane_pos >= lane_len - 1.0
            else:
                arrived = self.lane_pos <= 0.5
            if arrived:
                self.begin_holding(self.target_intersection)
                return
            advance = POLICE_SPEED * dt * self.direction
            self.lane_pos += advance
            self.lane_pos = max(0.0, min(float(lane_len - 1), self.lane_pos))
            return

        if self.state in ("deploying", "diverting", "returning"):
            self._advance_motion(dt)
