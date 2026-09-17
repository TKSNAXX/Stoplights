"""
Car movement segment logic.
"""
from __future__ import annotations

from sim import cars, passing, places, routes, world
from sim.paths import (
    direction_index_8_from_tangent,
    lane_heading,
    lane_segment_position,
    lane_segment_tangent,
    merge_length,
    merge_position,
    merge_tangent,
    path_length,
    path_position,
    path_tangent,
    screen_lean_degrees,
)
from sim.places import lane_is_full
from sim.world import intersection_cell_for_transition

# Lean held for the whole lane change. The jog's true screen angle runs to 44
# degrees at its steepest, which looks airborne rather than steered.
MERGE_LEAN_DEG = 16.0


def pose_for_lane_position(lane_idx: int, lane_pos: float, direction: int = 1) -> tuple[float, float, int]:
    """Shared lane pose computation for any lane-following actor."""
    lane = world.get_lane_cells(lane_idx)
    if not lane:
        return (0.0, 0.0, 0)
    lane_len = len(lane)
    pos = max(0.0, min(float(lane_len - 1), lane_pos))
    lo = int(pos)
    hi = min(lo + 1, lane_len - 1)
    t = pos - lo
    gx, gy = lane_segment_position(lane_idx, lo, hi, t)
    dx, dy = lane_segment_tangent(lane_idx, lo, hi)
    if direction < 0:
        dx, dy = -dx, -dy
    return (gx, gy, direction_index_8_from_tangent(dx, dy))


def _merge_lean(car: cars.Car, facing: tuple[float, float]) -> float:
    """
    The one lean a lane change gets, snapped on at the seam and off at the far side.

    Sampled at the middle of the curve, where the jog is steepest: its ends run
    parallel to the lane and would read as no lean at all. Held flat from there
    rather than tweened, so the sprite flips once, as it does on a corner.
    """
    tangent = merge_tangent(
        car.merge_source_lane, car.merge_source_pos, car.lane_index, car.position_in_lane, 0.5
    )
    lean = screen_lean_degrees(tangent, facing)
    if lean == 0.0:
        return 0.0
    return MERGE_LEAN_DEG if lean > 0.0 else -MERGE_LEAN_DEG


def set_pose_for_current_segment(car: cars.Car, t: float) -> None:
    t = max(0.0, min(1.0, t))
    lean = 0.0
    if car.motion_mode == "path" and car.pending_out_lane_index is not None:
        gx, gy = path_position(car.lane_index, car.pending_out_lane_index, t)
        dx, dy = path_tangent(car.lane_index, car.pending_out_lane_index, t)
    elif car.motion_mode == "merge" and car.merge_source_lane is not None and car.merge_source_pos is not None:
        gx, gy = merge_position(
            car.merge_source_lane, car.merge_source_pos, car.lane_index, car.position_in_lane, t
        )
        # Keep the road's own sprite and lean it instead. Rounding the curve to
        # the nearest of the eight facings would pick the octant next door, which
        # this projection draws bolt upright and reads as a 90-degree turn.
        dx, dy = lane_heading(car.lane_index)
        lean = _merge_lean(car, (dx, dy))
    else:
        if car.segment_start_pos is None or car.segment_end_pos is None:
            cell = car.current_cell()
            if cell is None:
                return
            gx, gy = float(cell[0]), float(cell[1])
            dx, dy = (0.0, 1.0)
        else:
            gx, gy = lane_segment_position(car.lane_index, car.segment_start_pos, car.segment_end_pos, t)
            dx, dy = lane_segment_tangent(car.lane_index, car.segment_start_pos, car.segment_end_pos)
    car.pose_gx = gx
    car.pose_gy = gy
    car.pose_dir_index_8 = direction_index_8_from_tangent(dx, dy)
    car.pose_lean_deg = lean


def start_lane_segment(car: cars.Car, start_time: float, speed: float, start_pos: int) -> bool:
    lane = car.get_lane()
    if not lane or start_pos < 0 or start_pos >= len(lane):
        return False
    if start_pos + 1 >= len(lane):
        return False
    _clear_merge(car)
    car.segment_start_time = start_time
    car.segment_duration = 1.0 / speed
    car.segment_start_pos = start_pos
    car.segment_end_pos = start_pos + 1
    car.segment_t_offset = 0.0
    car.segment_scale_reference = max(0.0, getattr(car, "speed_scale", 1.0))
    return True


def start_merge_segment(
    car: cars.Car,
    start_time: float,
    speed: float,
    target_lane: int,
    target_pos: int,
    side: str,
    reason: str,
    occupancy=None,
    pace: float = passing.MERGE_SPEED_KEEP,
) -> bool:
    """
    Begin a lane change onto target_lane.

    The car commits to the landing cell straight away, so occupancy, lane_is_full,
    and the fan all treat the gap as taken; the source cell is kept only for the pose.
    """
    target_cells = world.get_lane_cells(target_lane)
    if not target_cells or target_pos < 0 or target_pos >= len(target_cells):
        return False
    source_lane = car.lane_index
    source_pos = car.position_in_lane
    length = merge_length(source_lane, source_pos, target_lane, target_pos)
    car.merge_source_lane = source_lane
    car.merge_source_pos = source_pos
    car.merge_side = side
    car.merge_reason = reason
    car.lane_index = target_lane
    car.position_in_lane = target_pos
    car.intersection_cell = None
    car.pending_out_lane_index = None
    car.motion_mode = "merge"
    car.segment_start_time = start_time
    # Pace is set on the curve's own length, so the car holds its road speed
    # rather than trading pace for the extra distance the jog costs.
    travel = speed * min(1.0, max(0.05, pace))
    car.segment_duration = length / travel if travel > 0 else 0.2
    car.segment_start_pos = None
    car.segment_end_pos = None
    car.segment_t_offset = 0.0
    car.segment_scale_reference = max(0.0, getattr(car, "speed_scale", 1.0))
    if occupancy is not None:
        occupancy.add(car)
    return True


def start_flow_segment(car: cars.Car, start_time: float, speed: float, occupancy=None) -> bool:
    """
    Roll off the end of a mother lane into her daughter as if the road never broke.

    The cells abut on one heading, so the lane-change curve is a straight cell of
    road: full pace, no lean, and no side to report, since nothing is crossed.
    """
    daughter = world.lane_daughter(car.lane_index)
    if daughter is None:
        return False
    if not start_merge_segment(
        car, start_time, speed, daughter, 0, "", passing.REASON_FLOW, occupancy, pace=1.0
    ):
        return False
    _advance_route_step(car, daughter)
    return True


def _clear_merge(car: cars.Car) -> None:
    car.motion_mode = "lane"
    car.merge_source_lane = None
    car.merge_source_pos = None
    car.merge_side = ""
    car.merge_reason = ""


def _planned_out_lane(car: cars.Car) -> tuple[int, int] | None:
    if not car.route:
        return None
    return routes.out_lane_after(car.route, car.route_index)


def start_path_segment(car: cars.Car, start_time: float, speed: float) -> bool:
    """Start path through intersection using the stored itinerary (no greedy hop)."""
    planned = _planned_out_lane(car)
    if planned is None:
        return False
    out_lane_idx, _out_step = planned
    car.intersection_cell = intersection_cell_for_transition(car.lane_index, out_lane_idx)
    car.pending_out_lane_index = out_lane_idx
    car.motion_mode = "path"
    car.segment_start_time = start_time
    length = path_length(car.lane_index, out_lane_idx)
    car.segment_duration = length / speed if speed > 0 else 0.2
    car.segment_start_pos = None
    car.segment_end_pos = None
    car.segment_t_offset = 0.0
    car.segment_scale_reference = max(0.0, getattr(car, "speed_scale", 1.0))
    return True


def start_segment_for_current_state(
    car: cars.Car,
    start_time: float,
    speed: float,
    occupancy=None,
) -> bool:
    for _ in range(8):
        lane = car.get_lane()
        if not lane:
            return False
        if car.position_in_lane + 1 < len(lane):
            return start_lane_segment(car, start_time, speed, car.position_in_lane)
        if world.lane_daughter(car.lane_index) is not None:
            return start_flow_segment(car, start_time, speed, occupancy)
        if car.lane_index in places.in_lane_indices():
            return start_path_segment(car, start_time, speed)
        if not _hop_through_place(car, occupancy):
            return False
    return False


def _clear_segment(car: cars.Car) -> None:
    car.segment_start_time = None
    car.segment_duration = None
    car.segment_start_pos = None
    car.segment_end_pos = None
    car.segment_t_offset = 0.0
    car.segment_scale_reference = 1.0


def _place_on_lane(
    car: cars.Car,
    lane_idx: int,
    route_index: int,
    occupancy,
) -> bool:
    """Place car at cell 0 of lane_idx. False if that lane is full (caller despawns)."""
    if occupancy is not None and lane_is_full(lane_idx, occupancy):
        return False
    car.lane_index = lane_idx
    car.position_in_lane = 0
    car.intersection_cell = None
    car.pending_out_lane_index = None
    _clear_merge(car)
    car.route_index = route_index
    _clear_segment(car)
    if occupancy is not None:
        occupancy.add(car)
    return True


def _advance_route_step(car: cars.Car, target_lane: int) -> None:
    """Move the itinerary onto the stepsister the car has just committed to."""
    nxt = routes.step_lane_after(car.route, car.route_index) if car.route else None
    if nxt is not None and nxt[0] == target_lane:
        car.route_index = nxt[1]


def _snap_to_sister(car: cars.Car, occupancy) -> bool:
    """
    Last resort at the end of a lane that leads nowhere: step straight onto the
    sister. The step and exit rules in sim.passing should merge well before
    this, so the abrupt sidestep is preferred only to vanishing.
    """
    cells = world.get_lane_cells(car.lane_index)
    if not cells or car.position_in_lane < 0 or car.position_in_lane >= len(cells):
        return False
    sides = world.cell_merge(*cells[car.position_in_lane])
    planned = passing.planned_step_lane(car)
    found_sides = []
    for side in (world.MERGE_LEFT, world.MERGE_RIGHT):
        if sides not in (side, world.MERGE_BOTH):
            continue
        found = world.merge_target(car.lane_index, car.position_in_lane, side, 1)
        if found is not None:
            found_sides.append(found)
    # The itinerary's own step first; any sister beats vanishing.
    found_sides.sort(key=lambda f: 0 if f[0] == planned else 1)
    for target_lane, target_pos in found_sides:
        car.lane_index, car.position_in_lane = target_lane, target_pos
        car.intersection_cell = None
        car.pending_out_lane_index = None
        _clear_merge(car)
        _clear_segment(car)
        _advance_route_step(car, target_lane)
        if occupancy is not None:
            occupancy.add(car)
        return True
    return False


def _hop_through_place(car: cars.Car, occupancy) -> bool:
    """Instant hop onto the next itinerary lane. False → despawn (arrived, missing, or packed)."""
    arrived = world.lane_traffic_out(car.lane_index)
    if not arrived:
        return _snap_to_sister(car, occupancy)
    if arrived == car.destination:
        return False
    hop = routes.next_lane_after_place(car.route, car.route_index) if car.route else None
    if hop is None:
        return False
    next_lane, new_idx = hop
    return _place_on_lane(car, next_lane, new_idx, occupancy)


def advance_car(
    car: cars.Car,
    current_time: float,
    speed: float,
    to_remove: list[cars.Car],
    occupancy=None,
) -> None:
    speed = speed * getattr(car, "base_speed_multiplier", 1.0)
    # Loop so one tick can consume multiple completed segments (keeps handoffs continuous).
    for _ in range(8):
        if car.segment_start_time is None or car.segment_duration is None:
            if not start_segment_for_current_state(car, current_time, speed, occupancy):
                to_remove.append(car)
                return
        duration = max(1e-9, car.segment_duration)
        scale = max(0.0, getattr(car, "speed_scale", 1.0))
        ref_scale = max(0.0, getattr(car, "segment_scale_reference", scale))
        if abs(scale - ref_scale) > 1e-9:
            # Rebase segment time origin at scale changes to preserve exact in-segment progress.
            if ref_scale > 0.0:
                t_now = car.segment_t_offset + (current_time - car.segment_start_time) * ref_scale / duration
            else:
                t_now = car.segment_t_offset
            car.segment_t_offset = max(0.0, min(1.0, t_now))
            car.segment_start_time = current_time
            car.segment_scale_reference = scale
            ref_scale = scale
        if scale > 0.0:
            t = car.segment_t_offset + (current_time - car.segment_start_time) * scale / duration
            segment_end_time = car.segment_start_time + max(0.0, (1.0 - car.segment_t_offset)) * duration / scale
        else:
            t = car.segment_t_offset
            segment_end_time = current_time
        if t < 1.0:
            set_pose_for_current_segment(car, t)
            return

        # Complete current segment.
        set_pose_for_current_segment(car, 1.0)

        if car.motion_mode == "merge":
            # Landing cell is already the car's position; carry on as a lane car.
            _clear_merge(car)

        if car.motion_mode == "lane":
            if car.segment_end_pos is not None:
                car.position_in_lane = car.segment_end_pos
            _clear_segment(car)

            lane = car.get_lane()
            if not lane:
                to_remove.append(car)
                return
            choice = passing.merge_choice(car, occupancy)
            if choice is not None:
                target_lane, target_pos, side, reason = choice
                if start_merge_segment(
                    car, segment_end_time, speed, target_lane, target_pos, side, reason, occupancy
                ):
                    if reason == passing.REASON_STEP:
                        _advance_route_step(car, target_lane)
                    continue
            if car.position_in_lane + 1 < len(lane):
                if not start_lane_segment(car, segment_end_time, speed, car.position_in_lane):
                    to_remove.append(car)
                    return
                continue
            if world.lane_daughter(car.lane_index) is not None:
                if not start_flow_segment(car, segment_end_time, speed, occupancy):
                    to_remove.append(car)
                    return
                continue
            if car.lane_index in places.in_lane_indices():
                if not start_path_segment(car, segment_end_time, speed):
                    to_remove.append(car)
                    return
                continue
            if not _hop_through_place(car, occupancy):
                to_remove.append(car)
                return
            continue

        # Path complete -> transition to outbound lane.
        out_lane_idx = car.pending_out_lane_index
        if out_lane_idx is None:
            to_remove.append(car)
            return
        planned = _planned_out_lane(car)
        new_idx = planned[1] if planned is not None else car.route_index
        if not _place_on_lane(car, out_lane_idx, new_idx, occupancy):
            to_remove.append(car)
            return
        continue

    # Safety fallback if too many segment transitions in one tick.
    set_pose_for_current_segment(car, 1.0)
