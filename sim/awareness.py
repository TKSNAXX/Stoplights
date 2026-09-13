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


def _tailgated(
    index: int,
    pose: tuple[float, float, int],
    cars_list: list,
    poses: Sequence[tuple[float, float, int] | None],
    nearby_for: Callable[[float, float], list[int]],
    half_width: float,
) -> bool:
    gx, gy, _di = pose
    for j in nearby_for(gx, gy):
        if j == index or j < 0 or j >= len(cars_list):
            continue
        other_pose = poses[j] if j < len(poses) else None
        if other_pose is None:
            continue
        ox, oy, odi = other_pose
        if visibility_zone_band(ox, oy, odi, gx, gy, VIS_ZONE_LENGTH_CELLS, half_width):
            return True
    return False


def _queue_ahead(car, occupancy: Occupancy) -> bool:
    if getattr(car, "motion_mode", "lane") == "path":
        cell = getattr(car, "intersection_cell", None) or car.current_cell()
        if cell is None:
            return False
        for key in world.intersections_at_cell(cell):
            for other in occupancy.cars_in_intersection(key):
                if other is not car:
                    return True
        return False
    lane_idx = getattr(car, "lane_index", None)
    if lane_idx is None:
        return False
    pos = getattr(car, "position_in_lane", 0)
    for other in occupancy.cars_on_lane(lane_idx):
        if other is not car and getattr(other, "position_in_lane", -1) > pos:
            return True
    node = world.lane_traffic_out(lane_idx)
    if not world.is_intersection(node):
        return False
    lane = world.get_lane_cells(lane_idx)
    if not lane:
        return False
    approaching = pos >= max(0, len(lane) - INBOUND_TAIL_CELLS)
    if not approaching:
        return False
    return any(other is not car for other in occupancy.cars_in_intersection(node))


def _sister_passing(car, occupancy: Occupancy, pose: tuple[float, float, int]) -> bool:
    sister = world.sister_lane(car.lane_index)
    if sister is None:
        return False
    gx, gy, _di = pose
    pos = getattr(car, "position_in_lane", 0)
    limit = VIS_ZONE_LENGTH_CELLS
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
            return True
    return False
