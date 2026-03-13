"""
Game state orchestration.
"""
from __future__ import annotations

import math
import random
import time

from sim import cars, cop, places
from sim.constants import POLICE_PRIORITY_SCALE, VIS_ZONE_LENGTH_CELLS, VIS_ZONE_WIDTH_CELLS
from sim.impasse import apply_impasse
from sim.movement import advance_car
from sim.spawner import update_spawns
from sim.visibility import build_poses, nearby_indices, rebuild_spatial_buckets_inplace, visibility_zone_band

# Spawn: one car every N seconds per place (with jitter)
SPAWN_INTERVAL = 2.0

# Housing, Office, Park, and Shopping spawn.
SPAWN_PLACES = (places.SOUTH, places.NORTH, places.PARK, places.SHOPPING)

# Run car movement only every Nth tick.
MOVEMENT_EVERY_N_TICKS = 16

# Keep spatial candidate queries tight to the visibility fan footprint.
SPATIAL_QUERY_RADIUS_CELLS = int(math.ceil(VIS_ZONE_LENGTH_CELLS))


class GameState:
    def __init__(self):
        self.cars: list[cars.Car] = []
        self.spawn_interval: float = SPAWN_INTERVAL  # fallback; per-place overridden by place_configs
        self.spawn_enabled: dict[str, bool] = {p: True for p in SPAWN_PLACES}
        self.place_configs: dict[str, places.PlaceConfig] = {p: places.PlaceConfig() for p in SPAWN_PLACES}
        self.lane_configs: dict[int, places.LaneConfig] = {i: places.LaneConfig() for i in range(12)}
        for i in (4, 7):
            self.lane_configs[i].lane_type = places.LANE_TYPE_PASSING
        self.spawn_timers: dict[str, float] = {p: random.uniform(0, self.spawn_interval) for p in SPAWN_PLACES}
        self._accumulated_time = 0.0
        self._tick_count = 0
        self.movement_every_n_ticks: int = MOVEMENT_EVERY_N_TICKS  # mutable; set by speed slider
        self._impasse_timers: dict[tuple[int, int], float] = {}  # (id_lo, id_hi) -> seconds mutual near
        self.police_list = [
            cop.PoliceCar(deploy_lane=7, return_lane=7, red_trigger=10),  # Shopping
            cop.PoliceCar(deploy_lane=5, return_lane=5, red_trigger=20),  # Park
        ]
        self._spatial_buckets: dict[tuple[int, int], list[int]] = {}
        self._perf_stats: dict[str, float | int] = {
            "cars": 0,
            "tick_ms_ema": 0.0,
            "visibility_ms_ema": 0.0,
            "pair_ms_ema": 0.0,
            "visibility_checks": 0,
            "pair_checks": 0,
        }

    def get_max_impasse_timer(self) -> float | None:
        """Max timer value from _impasse_timers if any exist, else None (debug display)."""
        if not self._impasse_timers:
            return None
        return max(self._impasse_timers.values())

    def count_red_cars(self) -> int:
        """Count of cars with visibility_state == 'red'."""
        return sum(1 for car in self.cars if getattr(car, "visibility_state", "green") == "red")

    def get_perf_stats(self) -> dict[str, float | int]:
        """Snapshot of lightweight sim performance counters."""
        return dict(self._perf_stats)

    def _apply_police_influence(
        self,
        poses: list[tuple[float, float, int] | None],
        nearby_for,
        half_width: float,
    ) -> int:
        """Set police priority flags and return visibility check count contribution."""
        visibility_checks = 0
        for car in self.cars:
            car.police_priority_active = False
            if car.motion_mode != "path":
                car.police_hold_until_exit = False

        for police in self.police_list:
            if police.state not in ("deploying", "holding", "returning"):
                continue
            px, py, _ = police.get_pose()
            if police.state in ("deploying", "returning"):
                for i in nearby_for(px, py):
                    car = self.cars[i]
                    pose = poses[i]
                    if pose is None:
                        continue
                    gx, gy, di = pose
                    band = visibility_zone_band(gx, gy, di, px, py, VIS_ZONE_LENGTH_CELLS, half_width)
                    visibility_checks += 1
                    if band in ("near", "far"):
                        car.police_priority_active = True
            else:
                in_intersection: list[tuple[float, cars.Car]] = []
                for i, car in enumerate(self.cars):
                    if car.motion_mode != "path":
                        continue
                    pose = poses[i]
                    if pose is None:
                        continue
                    gx, gy, _ = pose
                    dist_sq = (gx - px) ** 2 + (gy - py) ** 2
                    in_intersection.append((dist_sq, car))
                in_intersection.sort(key=lambda item: item[0])
                for _, car in in_intersection[:3]:
                    car.police_hold_until_exit = True
        return visibility_checks

    def _apply_visibility(
        self,
        poses: list[tuple[float, float, int] | None],
        nearby_for,
        half_width: float,
    ) -> int:
        """Compute per-car visibility state/speed and return visibility check count."""
        checks = 0
        for i, car in enumerate(self.cars):
            car.visibility_state = "green"
            car.speed_scale = 1.0
            if getattr(car, "police_priority_active", False) or getattr(car, "police_hold_until_exit", False):
                car.visibility_state = "cyan"
                car.speed_scale = POLICE_PRIORITY_SCALE
                continue
            pose = poses[i]
            if pose is None:
                continue
            gx, gy, di = pose
            for j in nearby_for(gx, gy):
                other = self.cars[j]
                if i == j:
                    continue
                if getattr(car, "impasse_active", False) and getattr(car, "impasse_partner_id", None) == id(other):
                    continue
                other_pose = poses[j]
                if other_pose is None:
                    continue
                ox, oy, _ = other_pose
                band = visibility_zone_band(gx, gy, di, ox, oy, VIS_ZONE_LENGTH_CELLS, half_width)
                checks += 1
                if band == "near":
                    car.visibility_state = "red"
                    car.speed_scale = 0.0
                    break
                if band == "far" and car.visibility_state != "red":
                    car.visibility_state = "yellow"
                    car.speed_scale = 0.5
        return checks

    def _collect_impasse_candidates(self) -> set[int]:
        """Cars eligible for impasse pair checks (intersection/approach only)."""
        candidates: set[int] = set()
        for i, car in enumerate(self.cars):
            lane = car.get_lane()
            if car.motion_mode == "path":
                candidates.add(i)
                continue
            if car.lane_index in places.IN_LANE_INDICES and lane and car.position_in_lane >= max(0, len(lane) - 2):
                candidates.add(i)
        return candidates

    def tick(self, dt: float, current_time: float, base_duration: float = 0.2) -> None:
        tick_start = time.perf_counter()
        self._accumulated_time += dt
        self._tick_count += 1

        update_spawns(
            dt,
            SPAWN_PLACES,
            self.spawn_enabled,
            self.spawn_timers,
            self.place_configs,
            self.cars,
        )

        speed = 1.0 / max(1e-6, base_duration)  # cells per second
        half_width = VIS_ZONE_WIDTH_CELLS / 2.0
        poses = build_poses(self.cars)
        id_to_index = {id(car): idx for idx, car in enumerate(self.cars)}
        spatial_buckets = rebuild_spatial_buckets_inplace(self._spatial_buckets, poses)
        nearby_for = lambda gx, gy: nearby_indices(gx, gy, spatial_buckets, SPATIAL_QUERY_RADIUS_CELLS)

        visibility_start = time.perf_counter()
        visibility_checks = self._apply_police_influence(poses, nearby_for, half_width)
        visibility_checks += self._apply_visibility(poses, nearby_for, half_width)

        pair_start = time.perf_counter()
        pair_checks = apply_impasse(
            dt,
            self.cars,
            poses,
            id_to_index,
            nearby_for,
            half_width,
            self._impasse_timers,
            self._collect_impasse_candidates(),
        )

        red_count = self.count_red_cars()
        for police in self.police_list:
            police.tick(dt, red_count)

        to_remove: list[cars.Car] = []
        for car in self.cars:
            if car in to_remove:
                continue
            advance_car(car, current_time, speed, to_remove)

        for car in to_remove:
            if car in self.cars:
                self.cars.remove(car)

        tick_ms = (time.perf_counter() - tick_start) * 1000.0
        visibility_ms = (pair_start - visibility_start) * 1000.0
        pair_ms = (time.perf_counter() - pair_start) * 1000.0
        alpha = 0.1
        self._perf_stats["cars"] = len(self.cars)
        self._perf_stats["visibility_checks"] = visibility_checks
        self._perf_stats["pair_checks"] = pair_checks
        self._perf_stats["tick_ms_ema"] = (1.0 - alpha) * float(self._perf_stats["tick_ms_ema"]) + alpha * tick_ms
        self._perf_stats["visibility_ms_ema"] = (
            (1.0 - alpha) * float(self._perf_stats["visibility_ms_ema"]) + alpha * visibility_ms
        )
        self._perf_stats["pair_ms_ema"] = (1.0 - alpha) * float(self._perf_stats["pair_ms_ema"]) + alpha * pair_ms
