"""
Observe skills: random spawn bundle that nudges speed_scale after Brake (the fan).

Brake remains _apply_visibility. These multipliers never un-red.
"""
from __future__ import annotations

import random
from typing import Callable, Sequence

from sim import world
from sim.constants import INBOUND_TAIL_CELLS, VIS_ZONE_LENGTH_CELLS, VIS_ZONE_WIDTH_CELLS
from sim.occupancy import Occupancy
from sim.visibility import visibility_zone_band

SKILL_BEHIND = "behind"
SKILL_AHEAD = "ahead"
SKILL_SIDE = "side"
OBSERVE_SKILLS: tuple[str, ...] = (SKILL_BEHIND, SKILL_AHEAD, SKILL_SIDE)

BEHIND_SPEED_MULT = 1.15
BEHIND_SPEED_CAP = 1.2
AHEAD_SPEED_MULT = 0.7
SIDE_SPEED_MULT = 0.85


def roll_observe_skills() -> tuple[int, tuple[str, ...]]:
    """k in 0..3 and a random subset of that many observe skills (sorted, unique)."""
    k = random.randint(0, 3)
    if k == 0:
        return (0, ())
    picked = random.sample(OBSERVE_SKILLS, k)
    return (k, tuple(sorted(picked)))


def apply_observe_skills(
    cars_list: list,
    occupancy: Occupancy,
    poses: Sequence[tuple[float, float, int] | None],
    nearby_for: Callable[[float, float], list[int]],
    half_width: float | None = None,
) -> None:
    """Multiply speed_scale for cars that own observe skills. Skip cyan, white, red."""
    hw = VIS_ZONE_WIDTH_CELLS / 2.0 if half_width is None else half_width
    occupancy.sort_lanes()
    for i, car in enumerate(cars_list):
        skills = getattr(car, "observe_skills", ())
        if not skills:
            continue
        if getattr(car, "impasse_active", False):
            continue
        if getattr(car, "police_priority_active", False) or getattr(car, "police_hold_until_exit", False):
            continue
        if getattr(car, "visibility_state", "green") == "red" or car.speed_scale <= 0.0:
            continue
        pose = poses[i] if i < len(poses) else None
        if SKILL_BEHIND in skills and pose is not None:
            if _tailgated(i, pose, cars_list, poses, nearby_for, hw):
                car.speed_scale = min(BEHIND_SPEED_CAP, car.speed_scale * BEHIND_SPEED_MULT)
        if getattr(car, "visibility_state", "green") == "red" or car.speed_scale <= 0.0:
            continue
        if SKILL_AHEAD in skills and _queue_ahead(car, occupancy):
            car.speed_scale *= AHEAD_SPEED_MULT
        if SKILL_SIDE in skills and pose is not None and _sister_passing(car, occupancy, pose):
            car.speed_scale *= SIDE_SPEED_MULT


def observed_cars(
    car,
    cars_list: list,
    occupancy: Occupancy,
    poses: Sequence[tuple[float, float, int] | None],
    nearby_for: Callable[[float, float], list[int]],
    half_width: float | None = None,
) -> list:
    """Cars this car is driving off this tick. Display-only; does not change speed."""
    hw = VIS_ZONE_WIDTH_CELLS / 2.0 if half_width is None else half_width
    occupancy.sort_lanes()
    index = next((i for i, c in enumerate(cars_list) if c is car), None)
    if index is None:
        return []
    pose = poses[index] if index < len(poses) else None
    found: dict[int, object] = {}

    def add(other) -> None:
        if other is car:
            return
        found[id(other)] = other

    if pose is not None:
        gx, gy, di = pose
        for j in nearby_for(gx, gy):
            if j == index or j < 0 or j >= len(cars_list):
                continue
            other_pose = poses[j] if j < len(poses) else None
            if other_pose is None:
                continue
            ox, oy, _ = other_pose
            if visibility_zone_band(gx, gy, di, ox, oy, VIS_ZONE_LENGTH_CELLS, hw):
                add(cars_list[j])

    skills = getattr(car, "observe_skills", ())
    if skills and _observe_skills_would_run(car):
        if SKILL_BEHIND in skills and pose is not None:
            for other in _tailgaters(index, pose, cars_list, poses, nearby_for, hw):
                add(other)
        if SKILL_AHEAD in skills:
            for other in _queue_ahead_cars(car, occupancy):
                add(other)
        if SKILL_SIDE in skills and pose is not None:
            for other in _sister_passers(car, occupancy, pose):
                add(other)
    return list(found.values())


def _observe_skills_would_run(car) -> bool:
    if getattr(car, "impasse_active", False):
        return False
    if getattr(car, "police_priority_active", False) or getattr(car, "police_hold_until_exit", False):
        return False
    if getattr(car, "visibility_state", "green") == "red" or car.speed_scale <= 0.0:
        return False
    return True


def _tailgaters(
    index: int,
    pose: tuple[float, float, int],
    cars_list: list,
    poses: Sequence[tuple[float, float, int] | None],
    nearby_for: Callable[[float, float], list[int]],
    half_width: float,
) -> list:
    gx, gy, _di = pose
    out: list = []
    for j in nearby_for(gx, gy):
        if j == index or j < 0 or j >= len(cars_list):
            continue
        other_pose = poses[j] if j < len(poses) else None
        if other_pose is None:
            continue
        ox, oy, odi = other_pose
        if visibility_zone_band(ox, oy, odi, gx, gy, VIS_ZONE_LENGTH_CELLS, half_width):
            out.append(cars_list[j])
    return out


def _tailgated(
    index: int,
    pose: tuple[float, float, int],
    cars_list: list,
    poses: Sequence[tuple[float, float, int] | None],
    nearby_for: Callable[[float, float], list[int]],
    half_width: float,
) -> bool:
    return bool(_tailgaters(index, pose, cars_list, poses, nearby_for, half_width))


def _queue_ahead_cars(car, occupancy: Occupancy) -> list:
    out: list = []
    if getattr(car, "motion_mode", "lane") == "path":
        cell = getattr(car, "intersection_cell", None) or car.current_cell()
        if cell is None:
            return out
        seen: set[int] = set()
        for key in world.intersections_at_cell(cell):
            for other in occupancy.cars_in_intersection(key):
                if other is car:
                    continue
                ident = id(other)
                if ident in seen:
                    continue
                seen.add(ident)
                out.append(other)
        return out
    lane_idx = getattr(car, "lane_index", None)
    if lane_idx is None:
        return out
    pos = getattr(car, "position_in_lane", 0)
    for other in occupancy.cars_on_lane(lane_idx):
        if other is not car and getattr(other, "position_in_lane", -1) > pos:
            out.append(other)
    node = world.lane_traffic_out(lane_idx)
    if not world.is_intersection(node):
        return out
    lane = world.get_lane_cells(lane_idx)
    if not lane:
        return out
    approaching = pos >= max(0, len(lane) - INBOUND_TAIL_CELLS)
    if not approaching:
        return out
    seen_ids = {id(c) for c in out}
    for other in occupancy.cars_in_intersection(node):
        if other is car:
            continue
        ident = id(other)
        if ident in seen_ids:
            continue
        seen_ids.add(ident)
        out.append(other)
    return out


def _queue_ahead(car, occupancy: Occupancy) -> bool:
    return bool(_queue_ahead_cars(car, occupancy))


def _sister_passers(car, occupancy: Occupancy, pose: tuple[float, float, int]) -> list:
    sister = world.sister_lane(car.lane_index)
    if sister is None:
        return []
    gx, gy, _di = pose
    pos = getattr(car, "position_in_lane", 0)
    limit = VIS_ZONE_LENGTH_CELLS
    out: list = []
    for other in occupancy.cars_on_lane(sister):
        if other is car:
            continue
        if getattr(other, "position_in_lane", 0) > pos:
            continue
        ox = getattr(other, "pose_gx", None)
        oy = getattr(other, "pose_gy", None)
        if ox is None or oy is None:
            cell = other.current_cell()
            if cell is None:
                continue
            ox, oy = float(cell[0]), float(cell[1])
        if max(abs(ox - gx), abs(oy - gy)) <= limit:
            out.append(other)
    return out


def _sister_passing(car, occupancy: Occupancy, pose: tuple[float, float, int]) -> bool:
    return bool(_sister_passers(car, occupancy, pose))
