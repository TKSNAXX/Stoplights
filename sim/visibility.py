"""
Visibility geometry and spatial query helpers.
"""
from __future__ import annotations

import math

from sim import cars


def forward_right_vectors(dir_index_8: int) -> tuple[tuple[float, float], tuple[float, float]]:
    """Forward and right unit vectors in grid space for dir_index_8 (0=N..7=NW)."""
    idx = dir_index_8 % 8
    angle = math.pi / 2 - idx * (math.pi / 4)
    fx, fy = math.cos(angle), math.sin(angle)
    rx, ry = fy, -fx
    return ((fx, fy), (rx, ry))


def visibility_zone_band(
    observer_gx: float,
    observer_gy: float,
    dir_index_8: int,
    target_gx: float,
    target_gy: float,
    length: float,
    half_width: float,
) -> str | None:
    """Return 'near' if target in closest half of fan, 'far' if in farthest half, None if outside."""
    (fx, fy), (rx, ry) = forward_right_vectors(dir_index_8)
    dx = target_gx - observer_gx
    dy = target_gy - observer_gy
    forward_dist = dx * fx + dy * fy
    lateral = abs(dx * rx + dy * ry)
    if forward_dist <= 0 or forward_dist > length or lateral > half_width:
        return None
    half_len = length / 2.0
    return "near" if forward_dist <= half_len else "far"


def spatial_bucket_key(gx: float, gy: float) -> tuple[int, int]:
    """Integer grid bucket key for simple spatial hashing."""
    return (int(math.floor(gx)), int(math.floor(gy)))


def build_poses(cars_list: list[cars.Car]) -> list[tuple[float, float, int] | None]:
    """Build pose list (gx, gy, dir_index_8) for fast per-tick reuse."""
    poses: list[tuple[float, float, int] | None] = []
    for car in cars_list:
        gx = getattr(car, "pose_gx", None)
        gy = getattr(car, "pose_gy", None)
        di = getattr(car, "pose_dir_index_8", 0)
        if gx is None or gy is None:
            cell = car.current_cell()
            if cell is None:
                poses.append(None)
                continue
            gx, gy = float(cell[0]), float(cell[1])
        poses.append((gx, gy, di))
    return poses


def build_spatial_buckets(
    poses: list[tuple[float, float, int] | None],
) -> dict[tuple[int, int], list[int]]:
    """Build spatial hash bucket -> list of car indices."""
    buckets: dict[tuple[int, int], list[int]] = {}
    for idx, pose in enumerate(poses):
        if pose is None:
            continue
        key = spatial_bucket_key(pose[0], pose[1])
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(idx)
    return buckets


def rebuild_spatial_buckets_inplace(
    buckets: dict[tuple[int, int], list[int]],
    poses: list[tuple[float, float, int] | None],
) -> dict[tuple[int, int], list[int]]:
    """Reuse dictionary object when rebuilding buckets each tick."""
    buckets.clear()
    for idx, pose in enumerate(poses):
        if pose is None:
            continue
        key = spatial_bucket_key(pose[0], pose[1])
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(idx)
    return buckets


def nearby_indices(
    gx: float,
    gy: float,
    buckets: dict[tuple[int, int], list[int]],
    radius_cells: int,
) -> list[int]:
    """Return candidate car indices in nearby spatial buckets."""
    bx, by = spatial_bucket_key(gx, gy)
    out: list[int] = []
    for dx in range(-radius_cells, radius_cells + 1):
        for dy in range(-radius_cells, radius_cells + 1):
            out.extend(buckets.get((bx + dx, by + dy), []))
    return out
