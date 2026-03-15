"""
Game state orchestration.
"""
from __future__ import annotations

import math
import random
import time

from sim import cars, cop, places
from sim.constants import POLICE_PRIORITY_SCALE, VIS_ZONE_LENGTH_CELLS, VIS_ZONE_WIDTH_CELLS
from sim.map_data import (
    MAP_DATA,
    bounds_from_center,
    geometry_from_place_rects,
    place_rects_from_geometry,
)
from sim import world
from sim.impasse import apply_impasse
from sim.movement import advance_car
from sim.spawner import update_spawns
from sim.visibility import build_poses, nearby_indices, rebuild_spatial_buckets_inplace, visibility_zone_band

# Spawn: one car every N seconds per place (with jitter)
SPAWN_INTERVAL = 2.0

_LANE_ORIGIN_DEST: list[tuple[str, str]] = [
    (places.SOUTH, "main"),
    ("main", places.NORTH),
    (places.NORTH, "main"),
    ("main", places.SOUTH),
    (places.PARK, "main"),
    ("main", places.PARK),
    (places.SHOPPING, "main"),
    ("main", places.SHOPPING),
    (places.SOUTH, "bypass"),
    ("bypass", places.PARK),
    (places.PARK, "bypass"),
    ("bypass", places.SOUTH),
]

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
        for i, (orig, dest) in enumerate(_LANE_ORIGIN_DEST):
            self.lane_configs[i].origin = orig
            self.lane_configs[i].destination = dest
        self.intersection_configs: dict[str, places.IntersectionConfig] = {
            "main": places.IntersectionConfig(intersection_type=places.INTERSECTION_TYPE_X),
            "bypass": places.IntersectionConfig(
                intersection_type=places.INTERSECTION_TYPE_CORNER,
                center_x=places.BYPASS_DEFAULT_CENTER[0],
                center_y=places.BYPASS_DEFAULT_CENTER[1],
            ),
        }
        self.place_geometry: dict[str, places.PlaceGeometry] = {}
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

    def ensure_default_state(self) -> None:
        """
        Ensure a valid default game state. Call when config may be weird or corrupted.
        Restores core places and intersections if missing; prunes stale refs.
        """
        default_place_rects = MAP_DATA.get("place_rects", {})
        default_geometry = geometry_from_place_rects(default_place_rects)
        # Ensure core places exist in place_geometry
        for p in SPAWN_PLACES:
            if p not in self.place_geometry:
                self.place_geometry[p] = default_geometry.get(p, places.PlaceGeometry(center_x=36, center_y=48, width=5, length=5))
        # Ensure core place_configs exist
        for p in SPAWN_PLACES:
            if p not in self.place_configs:
                self.place_configs[p] = places.PlaceConfig()
        # Ensure main and bypass intersections exist
        if "main" not in self.intersection_configs:
            self.intersection_configs["main"] = places.IntersectionConfig(intersection_type=places.INTERSECTION_TYPE_X)
        if "bypass" not in self.intersection_configs:
            self.intersection_configs["bypass"] = places.IntersectionConfig(
                intersection_type=places.INTERSECTION_TYPE_CORNER,
                center_x=places.BYPASS_DEFAULT_CENTER[0],
                center_y=places.BYPASS_DEFAULT_CENTER[1],
            )
        # Prune place_configs and spawn_timers for deleted places
        for key in list(self.place_configs):
            if key not in self.place_geometry and key not in SPAWN_PLACES:
                del self.place_configs[key]
        for key in list(self.spawn_timers):
            if key not in self.place_configs:
                del self.spawn_timers[key]
        for p in SPAWN_PLACES:
            if p not in self.spawn_timers:
                self.spawn_timers[p] = random.uniform(0, self.spawn_interval)

    def reset_to_defaults(self) -> None:
        """
        Reset to the default map state. Clears cars, extra places, extra intersections.
        Use when things get weird or for a clean slate.
        """
        self.cars.clear()
        default_rects = MAP_DATA.get("place_rects", {})
        self.place_geometry = geometry_from_place_rects(default_rects)
        self.place_configs = {p: places.PlaceConfig() for p in SPAWN_PLACES}
        self.intersection_configs = {
            "main": places.IntersectionConfig(intersection_type=places.INTERSECTION_TYPE_X),
            "bypass": places.IntersectionConfig(
                intersection_type=places.INTERSECTION_TYPE_CORNER,
                center_x=places.BYPASS_DEFAULT_CENTER[0],
                center_y=places.BYPASS_DEFAULT_CENTER[1],
            ),
        }
        self.spawn_timers = {p: 0.0 for p in SPAWN_PLACES}
        self._impasse_timers.clear()
        # Reset lane_configs to core 0-11 only
        self.lane_configs = {i: places.LaneConfig() for i in range(12)}
        for i, (orig, dest) in enumerate(_LANE_ORIGIN_DEST):
            self.lane_configs[i].origin = orig
            self.lane_configs[i].destination = dest
        for i in (4, 7):
            self.lane_configs[i].lane_type = places.LANE_TYPE_PASSING
        self.rebuild_world_from_config()

    def next_lane_index(self) -> int:
        """Return next available lane index for adding a new lane."""
        if not self.lane_configs:
            return 12
        return max(self.lane_configs.keys()) + 1

    def _build_intersection_bounds(
        self,
        main_center: tuple[float, float],
        main_size: int,
        bypass_center: tuple[float, float],
        bypass_size: int,
    ) -> dict[str, tuple[int, int, int, int]]:
        """Build {key: (x_lo, x_hi, y_lo, y_hi)} for all intersections."""
        result: dict[str, tuple[int, int, int, int]] = {}
        main_cfg = self.intersection_configs.get("main")
        bypass_cfg = self.intersection_configs.get("bypass")
        m_sz = main_cfg.size_cells if main_cfg else main_size
        b_sz = bypass_cfg.size_cells if bypass_cfg else bypass_size
        result["main"] = bounds_from_center(main_center[0], main_center[1], m_sz)
        result["bypass"] = bounds_from_center(bypass_center[0], bypass_center[1], b_sz)
        for key, cfg in self.intersection_configs.items():
            if key in ("main", "bypass"):
                continue
            x_lo, x_hi, y_lo, y_hi = bounds_from_center(cfg.center_x, cfg.center_y, cfg.size_cells)
            result[key] = (x_lo, x_hi, y_lo, y_hi)
        return result

    def rebuild_world_from_config(self) -> None:
        """Rebuild world geometry from place_geometry and intersection configs. Call on Commit."""
        self.ensure_default_state()
        place_rects = place_rects_from_geometry(self.place_geometry)
        main_cfg = self.intersection_configs.get("main")
        bypass_cfg = self.intersection_configs.get("bypass")
        main_size = main_cfg.size_cells if main_cfg else places.INTERSECTION_SIZE_DEFAULT
        bypass_size = bypass_cfg.size_cells if bypass_cfg else places.INTERSECTION_SIZE_DEFAULT
        main_center = (main_cfg.center_x, main_cfg.center_y) if main_cfg else (36.0, 48.0)
        bypass_center = (bypass_cfg.center_x, bypass_cfg.center_y) if bypass_cfg else (64.0, 2.0)
        intersection_bounds = self._build_intersection_bounds(
            main_center, main_size, bypass_center, bypass_size
        )
        world.rebuild_world(
            place_rects, main_center, main_size, bypass_center, bypass_size,
            lane_configs=self.lane_configs,
            intersection_bounds=intersection_bounds,
        )

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
