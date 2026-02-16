"""
Single tick(dt) that updates spawn and all cars.
Three places, roads with midway intersection; cars route by destination at intersection or remove on arrival.
"""
from __future__ import annotations

import math
import random

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

# Spawn: one car every N seconds per place (with jitter)
SPAWN_INTERVAL = 2.0
SPAWN_JITTER = 0.3
SPAWN_INTERVAL_MIN = 1.0

# Housing, Office, Park, and Shopping spawn.
SPAWN_PLACES = (places.SOUTH, places.NORTH, places.PARK, places.SHOPPING)

# Run car movement only every Nth tick (120/16 = 7.5 moves/sec, half of original 15).
MOVEMENT_EVERY_N_TICKS = 16

# Visibility zone (must match main.py for display): length and width in grid cells
VIS_ZONE_LENGTH_CELLS = 2.0
VIS_ZONE_WIDTH_CELLS = 1.0


def _forward_right_vectors(dir_index_8: int) -> tuple[tuple[float, float], tuple[float, float]]:
    """Forward and right unit vectors in grid space for dir_index_8 (0=N..7=NW)."""
    idx = dir_index_8 % 8
    angle = math.pi / 2 - idx * (math.pi / 4)
    fx, fy = math.cos(angle), math.sin(angle)
    rx, ry = fy, -fx
    return ((fx, fy), (rx, ry))


def _visibility_zone_band(
    observer_gx: float, observer_gy: float, dir_index_8: int,
    target_gx: float, target_gy: float, length: float, half_width: float
) -> str | None:
    """Return 'near' if target in closest half of fan, 'far' if in farthest half, None if outside."""
    (fx, fy), (rx, ry) = _forward_right_vectors(dir_index_8)
    dx = target_gx - observer_gx
    dy = target_gy - observer_gy
    forward_dist = dx * fx + dy * fy
    lateral = abs(dx * rx + dy * ry)
    if forward_dist <= 0 or forward_dist > length or lateral > half_width:
        return None
    half_len = length / 2.0
    return "near" if forward_dist <= half_len else "far"


class GameState:
    def __init__(self):
        self.cars: list[cars.Car] = []
        self.spawn_interval: float = SPAWN_INTERVAL  # mutable; set by traffic slider
        self.spawn_enabled: dict[str, bool] = {p: True for p in SPAWN_PLACES}
        self.spawn_timers: dict[str, float] = {
            p: random.uniform(0, self.spawn_interval) for p in SPAWN_PLACES
        }
        self._accumulated_time = 0.0
        self._tick_count = 0
        self.movement_every_n_ticks: int = MOVEMENT_EVERY_N_TICKS  # mutable; set by speed slider

    def _set_pose_for_current_segment(self, car: cars.Car, t: float) -> None:
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

    def _start_lane_segment(self, car: cars.Car, start_time: float, speed: float, start_pos: int) -> bool:
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

    def _start_path_segment(self, car: cars.Car, start_time: float, speed: float) -> bool:
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
        car.path_entry_time = start_time
        car.path_duration = car.segment_duration
        return True

    def _start_segment_for_current_state(self, car: cars.Car, start_time: float, speed: float) -> bool:
        lane = car.get_lane()
        if not lane:
            return False
        if car.position_in_lane + 1 < len(lane):
            return self._start_lane_segment(car, start_time, speed, car.position_in_lane)
        if car.lane_index in places.IN_LANE_INDICES:
            return self._start_path_segment(car, start_time, speed)
        return False

    def _advance_car(self, car: cars.Car, current_time: float, speed: float, to_remove: list[cars.Car]) -> None:
        # Loop so one tick can consume multiple completed segments (keeps handoffs continuous).
        for _ in range(8):
            if car.segment_start_time is None or car.segment_duration is None:
                if not self._start_segment_for_current_state(car, current_time, speed):
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
                self._set_pose_for_current_segment(car, t)
                return

            # Complete current segment.
            self._set_pose_for_current_segment(car, 1.0)

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
                    if not self._start_lane_segment(car, segment_end_time, speed, car.position_in_lane):
                        to_remove.append(car)
                        return
                    continue
                if car.lane_index in places.IN_LANE_INDICES:
                    if not self._start_path_segment(car, segment_end_time, speed):
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
            car.path_entry_time = None
            car.path_duration = None
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
                if not self._start_lane_segment(car, segment_end_time, speed, car.position_in_lane):
                    to_remove.append(car)
                    return
                continue
            to_remove.append(car)
            return

        # Safety fallback if too many segment transitions in one tick.
        self._set_pose_for_current_segment(car, 1.0)

    def tick(self, dt: float, current_time: float, base_duration: float = 0.2) -> None:
        self._accumulated_time += dt
        # Spawn: run every tick so spawn timing stays correct in real time; skip disabled places.
        for place in SPAWN_PLACES:
            if not self.spawn_enabled.get(place, True):
                continue
            self.spawn_timers[place] += dt
            if self.spawn_timers[place] >= self.spawn_interval:
                interval = self.spawn_interval + random.uniform(-SPAWN_JITTER, SPAWN_JITTER)
                interval = max(SPAWN_INTERVAL_MIN, interval)
                self.spawn_timers[place] -= interval
                self.cars.append(cars.spawn_car(place))

        self._tick_count += 1
        speed = 1.0 / max(1e-6, base_duration)  # cells per second
        half_width = VIS_ZONE_WIDTH_CELLS / 2.0
        poses: list[tuple[float, float, int] | None] = []
        for c in self.cars:
            gx = getattr(c, "pose_gx", None)
            gy = getattr(c, "pose_gy", None)
            di = getattr(c, "pose_dir_index_8", 0)
            if gx is None or gy is None:
                cell = c.current_cell()
                if cell is None:
                    poses.append(None)
                    continue
                gx, gy = float(cell[0]), float(cell[1])
            poses.append((gx, gy, di))
        for i, car in enumerate(self.cars):
            car.visibility_state = "green"
            car.speed_scale = 1.0
            p = poses[i]
            if p is None:
                continue
            gx, gy, di = p
            for j, other in enumerate(self.cars):
                if i == j:
                    continue
                op = poses[j]
                if op is None:
                    continue
                ox, oy, _ = op
                band = _visibility_zone_band(gx, gy, di, ox, oy, VIS_ZONE_LENGTH_CELLS, half_width)
                if band == "near":
                    car.visibility_state = "red"
                    car.speed_scale = 0.0
                    break
                if band == "far" and car.visibility_state != "red":
                    car.visibility_state = "yellow"
                    car.speed_scale = 0.5
        to_remove: list[cars.Car] = []
        for car in self.cars:
            if car in to_remove:
                continue
            self._advance_car(car, current_time, speed, to_remove)

        for c in to_remove:
            if c in self.cars:
                self.cars.remove(c)
