"""
Game state orchestration.
"""
from __future__ import annotations

import math
import random
import time

from sim import cars, cop, places
from sim.constants import POLICE_PRIORITY_SCALE, VIS_ZONE_LENGTH_CELLS, VIS_ZONE_WIDTH_CELLS
from sim.map_data import next_lane_index, place_rects_from_places
from sim import scenario, world
from sim.impasse import apply_impasse
from sim.movement import advance_car
from sim.spawner import update_spawns
from sim.visibility import build_poses, nearby_indices, rebuild_spatial_buckets_inplace, visibility_zone_band

SPAWN_INTERVAL = 2.0
MOVEMENT_EVERY_N_TICKS = 16
SPATIAL_QUERY_RADIUS_CELLS = int(math.ceil(VIS_ZONE_LENGTH_CELLS))


class GameState:
    def __init__(self):
        self.cars: list[cars.Car] = []
        self.spawn_interval: float = SPAWN_INTERVAL
        self.spawn_enabled: dict[str, bool] = {}
        self.places: dict[str, places.Place] = {}
        self.lanes: dict[int, places.LaneConfig] = {}
        self.intersections: dict[str, places.IntersectionConfig] = {}
        self.route_hints: list[tuple[str, str, str]] = []
        self.spawn_places: tuple[str, ...] = ()
        self.spawn_timers: dict[str, float] = {}
        self.origin_spawn_counts: dict[str, int] = {}
        self.lane_spawn_counts: dict[tuple[str, int], int] = {}
        self.origin_spawn_balance_coeff: float = 1.0
        self.out_lane_balance_coeff: float = 1.0
        self._accumulated_time = 0.0
        self._tick_count = 0
        self.movement_every_n_ticks: int = MOVEMENT_EVERY_N_TICKS
        self._impasse_timers: dict[tuple[int, int], float] = {}
        self.police_list: list[cop.PoliceCar] = []
        self._spatial_buckets: dict[tuple[int, int], list[int]] = {}
        self._perf_stats: dict[str, float | int] = {
            "cars": 0,
            "tick_ms_ema": 0.0,
            "visibility_ms_ema": 0.0,
            "pair_ms_ema": 0.0,
            "visibility_checks": 0,
            "pair_checks": 0,
        }
        # Load default scenario as the blank slate; persistence may overwrite.
        default = scenario.load_default_scenario()
        scenario.apply_scenario_to_game(self, default)
        for p in self.spawn_places:
            self.spawn_timers[p] = random.uniform(0, self.spawn_interval)
            self.origin_spawn_counts[p] = 0
            self.spawn_enabled[p] = True
        places.set_route_hints(self.route_hints)
        self.rebuild_world_from_config()

    def next_lane_index(self) -> int:
        return next_lane_index(self.lanes)

    def delete_lane(self, lane_idx: int) -> None:
        cfg = self.lanes.get(lane_idx)
        if cfg is None or getattr(cfg, "protected", False):
            return
        del self.lanes[lane_idx]
        self.cars = [c for c in self.cars if c.lane_index != lane_idx]
        self.rebuild_world_from_config()

    def get_max_impasse_timer(self) -> float | None:
        if not self._impasse_timers:
            return None
        return max(self._impasse_timers.values())

    def count_red_cars(self) -> int:
        return sum(1 for car in self.cars if getattr(car, "visibility_state", "green") == "red")

    def get_perf_stats(self) -> dict[str, float | int]:
        return dict(self._perf_stats)

    def ensure_default_state(self) -> None:
        """Prune timers/counts for missing place ids; ensure spawn timers exist."""
        for key in list(self.spawn_timers):
            if key not in self.places:
                del self.spawn_timers[key]
        for key in list(self.origin_spawn_counts):
            if key not in self.places:
                del self.origin_spawn_counts[key]
        for p in self.places:
            if p not in self.spawn_timers:
                self.spawn_timers[p] = random.uniform(0, self.spawn_interval)
            if p not in self.origin_spawn_counts:
                self.origin_spawn_counts[p] = 0

    def reset_to_defaults(self) -> None:
        """Reload assets/maps/default.json."""
        self.cars.clear()
        self.lane_spawn_counts.clear()
        self._impasse_timers.clear()
        default = scenario.load_default_scenario()
        scenario.apply_scenario_to_game(self, default)
        self.spawn_timers = {p: 0.0 for p in self.spawn_places}
        self.origin_spawn_counts = {p: 0 for p in self.spawn_places}
        self.spawn_enabled = {p: True for p in self.spawn_places}
        places.set_route_hints(self.route_hints)
        self.rebuild_world_from_config()

    def rebuild_world_from_config(self) -> None:
        """Rebuild world geometry from current configs."""
        self.ensure_default_state()
        place_rects = place_rects_from_places(self.places)
        places.set_route_hints(self.route_hints)
        world.rebuild_world(place_rects, self.intersections, self.lanes)
        self._refresh_spawn_places_from_world()

    def _refresh_spawn_places_from_world(self) -> None:
        ordered_candidates: list[str] = []
        seen: set[str] = set()
        for p in self.spawn_places:
            if p in seen:
                continue
            ordered_candidates.append(p)
            seen.add(p)
        for p in sorted(self.places):
            if p in seen:
                continue
            ordered_candidates.append(p)
            seen.add(p)

        spawnable = tuple(
            p
            for p in ordered_candidates
            if any(world.lane_traffic_in(i) == p for i in world.lane_ids())
        )
        self.spawn_places = spawnable
        self.spawn_enabled = {p: self.spawn_enabled.get(p, True) for p in self.spawn_places}
        self.spawn_timers = {
            p: self.spawn_timers.get(p, random.uniform(0, self.spawn_interval))
            for p in self.spawn_places
        }
        self.origin_spawn_counts = {
            p: self.origin_spawn_counts.get(p, 0) for p in self.spawn_places
        }

    def can_remove_lane(self, lane_index: int) -> bool:
        cfg = self.lanes.get(lane_index)
        return cfg is not None and not getattr(cfg, "protected", False)

    def can_remove_place(self, place_key: str) -> bool:
        g = self.places.get(place_key)
        return g is not None and not getattr(g, "protected", False)

    def can_remove_intersection(self, intersection_key: str) -> bool:
        cfg = self.intersections.get(intersection_key)
        return cfg is not None and not getattr(cfg, "protected", False)

    def rename_place(self, old: str, new: str) -> str:
        """Rename a place id. Returns the name actually used (old if refused)."""
        new = (new or "").strip()
        if not old or old not in self.places or not new or new == old:
            return old
        if new in self.places or new in self.intersections:
            return old
        self.places[new] = self.places.pop(old)
        self.spawn_enabled = {(new if k == old else k): v for k, v in self.spawn_enabled.items()}
        self.spawn_timers = {(new if k == old else k): v for k, v in self.spawn_timers.items()}
        self.origin_spawn_counts = {
            (new if k == old else k): v for k, v in self.origin_spawn_counts.items()
        }
        self.lane_spawn_counts = {
            ((new if k[0] == old else k[0]), k[1]): v for k, v in self.lane_spawn_counts.items()
        }
        self.spawn_places = tuple(new if p == old else p for p in self.spawn_places)
        self.route_hints = [
            (new if a == old else a, new if b == old else b, new if c == old else c)
            for (a, b, c) in self.route_hints
        ]
        for car in self.cars:
            if car.origin == old:
                car.origin = new
            if car.destination == old:
                car.destination = new
        places.set_route_hints(self.route_hints)
        self.rebuild_world_from_config()
        return new

    def _apply_police_influence(
        self,
        poses: list[tuple[float, float, int] | None],
        nearby_for,
        half_width: float,
    ) -> int:
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
        candidates: set[int] = set()
        inbound = places.in_lane_indices()
        for i, car in enumerate(self.cars):
            lane = car.get_lane()
            if car.motion_mode == "path":
                candidates.add(i)
                continue
            if car.lane_index in inbound and lane and car.position_in_lane >= max(0, len(lane) - 2):
                candidates.add(i)
        return candidates

    def tick(self, dt: float, current_time: float, base_duration: float = 0.2) -> None:
        tick_start = time.perf_counter()
        self._accumulated_time += dt
        self._tick_count += 1

        update_spawns(
            dt,
            self.spawn_places,
            self.spawn_enabled,
            self.spawn_timers,
            self.places,
            self.cars,
            origin_spawn_counts=self.origin_spawn_counts,
            lane_spawn_counts=self.lane_spawn_counts,
            origin_spawn_balance_coeff=self.origin_spawn_balance_coeff,
            out_lane_balance_coeff=self.out_lane_balance_coeff,
        )

        speed = 1.0 / max(1e-6, base_duration)
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
