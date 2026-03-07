"""
Car movement segment logic.
"""
from __future__ import annotations

from sim import cars, places
from sim.paths import (
    direction_index_8_from_tangent,
    lane_segment_position,
    lane_segment_tangent,
    path_length,
    path_position,
    path_tangent,
)
from sim.world import ALL_LANES, intersection_cell_for_transition


def pose_for_lane_position(lane_idx: int, lane_pos: float, direction: int = 1) -> tuple[float, float, int]:
    """Shared lane pose computation for any lane-following actor."""
    lane = ALL_LANES[lane_idx] if 0 <= lane_idx < len(ALL_LANES) else []
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


def set_pose_for_current_segment(car: cars.Car, t: float) -> None:
    t = max(0.0, min(1.0, t))
    if car.motion_mode == "path" and car.pending_out_lane_index is not None:
        gx, gy = path_position(car.lane_index, car.pending_out_lane_index, t)
        dx, dy = path_tangent(car.lane_index, car.pending_out_lane_index, t)
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


def start_lane_segment(car: cars.Car, start_time: float, speed: float, start_pos: int) -> bool:
    lane = car.get_lane()
    if not lane or start_pos < 0 or start_pos >= len(lane):
        return False
    if start_pos + 1 >= len(lane):
        return False
    car.motion_mode = "lane"
    car.segment_start_time = start_time
    car.segment_duration = 1.0 / speed
    car.segment_start_pos = start_pos
    car.segment_end_pos = start_pos + 1
    car.segment_t_offset = 0.0
    car.segment_scale_reference = max(0.0, getattr(car, "speed_scale", 1.0))
    return True


def start_path_segment(car: cars.Car, start_time: float, speed: float) -> bool:
    out_lane_idx = places.OUT_LANE_BY_PLACE.get(car.destination)
    if out_lane_idx is None:
        return False
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


def start_segment_for_current_state(car: cars.Car, start_time: float, speed: float) -> bool:
    lane = car.get_lane()
    if not lane:
        return False
    if car.position_in_lane + 1 < len(lane):
        return start_lane_segment(car, start_time, speed, car.position_in_lane)
    if car.lane_index in places.IN_LANE_INDICES:
        return start_path_segment(car, start_time, speed)
    return False


def advance_car(car: cars.Car, current_time: float, speed: float, to_remove: list[cars.Car]) -> None:
    speed = speed * getattr(car, "base_speed_multiplier", 1.0)
    # Loop so one tick can consume multiple completed segments (keeps handoffs continuous).
    for _ in range(8):
        if car.segment_start_time is None or car.segment_duration is None:
            if not start_segment_for_current_state(car, current_time, speed):
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

        if car.motion_mode == "lane":
            if car.segment_end_pos is not None:
                car.position_in_lane = car.segment_end_pos
            car.segment_start_time = None
            car.segment_duration = None
            car.segment_start_pos = None
            car.segment_end_pos = None
            car.segment_t_offset = 0.0
            car.segment_scale_reference = 1.0

            lane = car.get_lane()
            if not lane:
                to_remove.append(car)
                return
            if car.position_in_lane + 1 < len(lane):
                if not start_lane_segment(car, segment_end_time, speed, car.position_in_lane):
                    to_remove.append(car)
                    return
                continue
            if car.lane_index in places.IN_LANE_INDICES:
                if not start_path_segment(car, segment_end_time, speed):
                    to_remove.append(car)
                    return
                continue
            to_remove.append(car)
            return

        # Path complete -> transition to outbound lane.
        out_lane_idx = car.pending_out_lane_index
        if out_lane_idx is None:
            to_remove.append(car)
            return
        car.lane_index = out_lane_idx
        car.position_in_lane = 0
        car.intersection_cell = None
        car.pending_out_lane_index = None
        car.motion_mode = "lane"
        car.segment_start_time = None
        car.segment_duration = None
        car.segment_start_pos = None
        car.segment_end_pos = None
        car.segment_t_offset = 0.0
        car.segment_scale_reference = 1.0

        lane = car.get_lane()
        if not lane:
            to_remove.append(car)
            return
        if car.position_in_lane + 1 < len(lane):
            if not start_lane_segment(car, segment_end_time, speed, car.position_in_lane):
                to_remove.append(car)
                return
            continue
        to_remove.append(car)
        return

    # Safety fallback if too many segment transitions in one tick.
    set_pose_for_current_segment(car, 1.0)
