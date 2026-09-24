"""
Game state orchestration.
"""
from __future__ import annotations

import math
import random
import time

from sim import cars, cop, places, routes, scenario, world
from sim.awareness import apply_observe_skills
from sim.constants import VIS_ZONE_LENGTH_CELLS, VIS_ZONE_WIDTH_CELLS
from sim.map_data import next_lane_index, place_rects_from_places
from sim.impasse import apply_impasse
from sim.movement import advance_car
from sim.occupancy import Occupancy
from sim.passing import hold_merge_speed
from sim.situation import refresh_situations
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
        self.police_enabled: bool = True
        self._police_cooldown: dict[tuple[str, ...], float] = {}
        self._police_marked: list = []
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

    def set_police_enabled(self, enabled: bool) -> None:
        self.police_enabled = bool(enabled)
        if not self.police_enabled:
            self.police_list.clear()

    def clear_cars(self) -> None:
        self.cars.clear()

    def next_lane_index(self) -> int:
        return next_lane_index(self.lanes)

    def delete_lane(self, lane_idx: int) -> None:
        cfg = self.lanes.get(lane_idx)
        if cfg is None:
            return
        del self.lanes[lane_idx]
        self.cars = [c for c in self.cars if c.lane_index != lane_idx]
        self.rebuild_world_from_config()

    def delete_intersection(self, intersection_key: str) -> None:
        if intersection_key not in self.intersections:
            return
        del self.intersections[intersection_key]
        self.rebuild_world_from_config()

    def delete_place(self, place_key: str) -> None:
        if place_key not in self.places:
            return
        del self.places[place_key]
        self.spawn_enabled.pop(place_key, None)
        self.spawn_timers.pop(place_key, None)
        self.origin_spawn_counts.pop(place_key, None)
        self.lane_spawn_counts = {
            k: v for k, v in self.lane_spawn_counts.items() if k[0] != place_key
        }
        self.route_hints = [
            (a, b, c) for (a, b, c) in self.route_hints if a != place_key and b != place_key
        ]
        self.cars = [
            c for c in self.cars if c.origin != place_key and c.destination != place_key
        ]
        places.set_route_hints(self.route_hints)
        self.rebuild_world_from_config()

    def get_max_impasse_timer(self) -> float | None:
        if not self._impasse_timers:
            return None
        return max(self._impasse_timers.values())

    def count_red_cars(self) -> int:
        return sum(1 for car in self.cars if getattr(car, "visibility_state", "green") == "red")

    def get_perf_stats(self) -> dict[str, float | int]:
        return dict(self._perf_stats)

    def observed_cars_for(self, car) -> list:
        """Cars this civilian is driving off this tick. Display-only."""
        from sim.awareness import observed_cars

        poses = build_poses(self.cars)
        occupancy = Occupancy.from_cars(self.cars)
        if not self._spatial_buckets:
            rebuild_spatial_buckets_inplace(self._spatial_buckets, poses)
        nearby_for = lambda gx, gy: nearby_indices(
            gx, gy, self._spatial_buckets, SPATIAL_QUERY_RADIUS_CELLS
        )
        return observed_cars(car, self.cars, occupancy, poses, nearby_for)

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
        self._prune_police()
        self._refresh_car_routes()
        self._refresh_spawn_places_from_world()

    def _refresh_car_routes(self) -> None:
        occ = Occupancy.from_cars(self.cars)
        kept: list[cars.Car] = []
        for car in self.cars:
            if not car.destination:
                kept.append(car)
                continue
            if routes.route_is_live(car.route):
                kept.append(car)
                continue
            start = routes.current_node(car)
            new = routes.plan_route(start, car.destination)
            if new is None:
                continue
            idx = routes.lane_step_index(new, car.lane_index)
            if idx is None and car.pending_out_lane_index is not None:
                idx = routes.lane_step_index(new, car.pending_out_lane_index)
            if idx is None:
                continue
            occupy_step = new[idx]
            occupy_lane = occupy_step.ref if occupy_step.kind == "lane" else None
            if occupy_lane is not None and occupy_lane != car.lane_index:
                if places.lane_is_full(occupy_lane, occ):
                    continue
            car.route = new
            car.route_index = idx
            kept.append(car)
        self.cars = kept

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
            if world.outgoing_lanes(p)
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
        return lane_index in self.lanes

    def can_remove_place(self, place_key: str) -> bool:
        return place_key in self.places

    def can_remove_intersection(self, intersection_key: str) -> bool:
        return intersection_key in self.intersections

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
            car.route = routes.retarget_place_steps(car.route, old, new)
        places.set_route_hints(self.route_hints)
        self.rebuild_world_from_config()
        return new

    def _apply_police_influence(
        self,
        poses: list[tuple[float, float, int] | None],
        nearby_for,
        half_width: float,
        occupancy: Occupancy | None = None,
    ) -> int:
        """Mark held and waved cars. A cop grants nothing until he is holding."""
        del poses, nearby_for, half_width
        for car in self._police_marked:
            car.police_held = False
            car.police_clear = ""
        self._police_marked.clear()
        occ = occupancy if occupancy is not None else Occupancy.from_cars(self.cars)
        for police in self.police_list:
            if police.state == "holding":
                cop.mark_holding(police, occ, self._police_marked)
        return 0

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
            if getattr(car, "police_held", False):
                car.visibility_state = "red"
                car.speed_scale = 0.0
                continue
            if getattr(car, "police_clear", "") == "drain":
                car.visibility_state = "cyan"
                car.speed_scale = cop.DRAIN_SPEED
                continue
            wave = getattr(car, "police_clear", "") == "wave"
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
                if wave and getattr(other, "police_held", False):
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
        inbound = world.in_lane_ids()
        for i, car in enumerate(self.cars):
            lane = car.get_lane()
            if car.motion_mode == "path":
                candidates.add(i)
                continue
            if car.lane_index in inbound and lane and car.position_in_lane >= max(0, len(lane) - 2):
                candidates.add(i)
        return candidates

    def _beat_covered(self, beat: frozenset[str]) -> bool:
        for police in self.police_list:
            if police.state in ("despawned", "returning"):
                continue
            if police.target_intersection in beat:
                return True
        return False

    def _cool_police_beat(self, node: str) -> None:
        self._police_cooldown[cop.beat_key(node)] = cop.RESPAWN_COOLDOWN

    def _decay_police_cooldown(self, dt: float) -> None:
        for key in list(self._police_cooldown):
            self._police_cooldown[key] -= dt
            if self._police_cooldown[key] <= 0.0:
                del self._police_cooldown[key]

    def _pick_divert_dest(self, police: cop.PoliceCar, occupancy: Occupancy) -> str | None:
        """A deadlocked junction in another beat that has no cop and is not cooling down."""
        if not police.can_divert:
            return None
        here = cop.beat_of(police.target_intersection)
        best: str | None = None
        best_key: tuple[int, str] | None = None
        for beat in cop.beats():
            if beat == here or self._beat_covered(beat):
                continue
            if self._police_cooldown.get(cop.beat_key(next(iter(beat))), 0.0) > 0.0:
                continue
            dead = [node for node in beat if cop.junction_deadlocked(occupancy, node)]
            if not dead:
                continue
            target = max(dead, key=lambda node: (cop.stopped_approach_count(occupancy, node), node))
            key = (cop.stopped_approach_count(occupancy, target), target)
            if best_key is None or key > best_key:
                best_key = key
                best = target
        return best

    def _spawn_police(self, occupancy: Occupancy) -> None:
        for beat in cop.beats():
            if self._police_cooldown.get(cop.beat_key(next(iter(beat))), 0.0) > 0.0:
                continue
            if self._beat_covered(beat):
                continue
            dead = [node for node in beat if cop.junction_deadlocked(occupancy, node)]
            if not dead:
                continue
            target = max(dead, key=lambda node: (cop.stopped_approach_count(occupancy, node), node))
            lane = cop.pick_beat_deploy_lane(beat, target)
            if lane is None:
                continue
            self.police_list.append(cop.spawn_police(target, lane))

    def _update_police(self, dt: float, occupancy: Occupancy | None = None) -> None:
        """Spawn one cop per deadlocked beat; hold, then walk, divert, or go home."""
        if not self.police_enabled:
            self.police_list.clear()
            return
        self._decay_police_cooldown(dt)
        occ = occupancy if occupancy is not None else Occupancy.from_cars(self.cars)
        for police in self.police_list:
            if police.state == "holding":
                action = cop.advance_signal(police, dt, occ)
                if action == "walk" and police.walk_target:
                    police.begin_walk(police.walk_target)
                elif action in ("home", "giveup"):
                    dest = None if action == "giveup" else self._pick_divert_dest(police, occ)
                    self._cool_police_beat(police.target_intersection)
                    if dest:
                        police.begin_divert(dest)
                    else:
                        police.begin_return_home()
            elif police.state == "diverting" and not cop.junction_deadlocked(occ, police.target_intersection):
                police.begin_return_home()
            police.tick(dt, 0)
        self.police_list = [p for p in self.police_list if p.state != "despawned"]
        # A cop easing off a clear junction is the one who will take the next jam.
        fading_off = any(
            p.state == "holding" and p.phase == "direct" and p.can_divert
            for p in self.police_list
        )
        if not fading_off:
            self._spawn_police(occ)

    def _prune_police(self) -> None:
        """Drop cops whose node or travel lane no longer exists."""
        keys = set(world.get_intersection_keys())
        place_ids = set(world.get_place_rects().keys())
        lane_ids = set(world.lane_ids())
        kept: list[cop.PoliceCar] = []
        for p in self.police_list:
            if p.motion == "path":
                if p.path_in not in lane_ids or p.path_out not in lane_ids:
                    continue
            else:
                lane = p.travel_lane if p.travel_lane in lane_ids else p.deploy_lane
                if lane not in lane_ids:
                    continue
                if p._lane_len(lane) < 2:
                    continue
            if p.state in ("deploying", "holding", "diverting"):
                if p.target_intersection not in keys:
                    continue
            if p.state == "deploying":
                tin = world.lane_traffic_in(p.deploy_lane)
                tout = world.lane_traffic_out(p.deploy_lane)
                if p.target_intersection not in (tin, tout):
                    continue
            if p.state == "holding":
                hold_lane = p.travel_lane if p.travel_lane in lane_ids else p.deploy_lane
                tin = world.lane_traffic_in(hold_lane)
                tout = world.lane_traffic_out(hold_lane)
                if p.target_intersection not in (tin, tout):
                    continue
            if p.state == "returning" and p.home_place and p.home_place not in place_ids:
                continue
            kept.append(p)
        self.police_list = kept

    def tick(self, dt: float, current_time: float, base_duration: float = 0.2) -> None:
        tick_start = time.perf_counter()
        self._accumulated_time += dt
        self._tick_count += 1

        occupancy = Occupancy.from_cars(self.cars)
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
            occupancy=occupancy,
        )

        speed = 1.0 / max(1e-6, base_duration)
        half_width = VIS_ZONE_WIDTH_CELLS / 2.0
        poses = build_poses(self.cars)
        id_to_index = {id(car): idx for idx, car in enumerate(self.cars)}
        spatial_buckets = rebuild_spatial_buckets_inplace(self._spatial_buckets, poses)
        nearby_for = lambda gx, gy: nearby_indices(gx, gy, spatial_buckets, SPATIAL_QUERY_RADIUS_CELLS)

        self._update_police(dt, occupancy)

        visibility_start = time.perf_counter()
        visibility_checks = self._apply_police_influence(poses, nearby_for, half_width, occupancy)
        visibility_checks += self._apply_visibility(poses, nearby_for, half_width)
        apply_observe_skills(self.cars, occupancy, poses, nearby_for, half_width)

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
        # Last word on speed: a car astride a seam always finishes the change.
        hold_merge_speed(self.cars)

        to_remove: list[cars.Car] = []
        for car in self.cars:
            if car in to_remove:
                continue
            advance_car(car, current_time, speed, to_remove, occupancy)

        for car in to_remove:
            if car in self.cars:
                self.cars.remove(car)

        sit_occ = Occupancy.from_cars(self.cars)
        refresh_situations(self.cars, sit_occ)

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
