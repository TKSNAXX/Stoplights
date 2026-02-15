"""
Intersection paths: one path per (in_lane, out_lane) pair.
Straight-through = line segment; turns = quadratic Bezier through intersection center.
"""
from __future__ import annotations

import math

from sim.places import STRAIGHT_TRANSITIONS
from sim.world import ALL_LANES, get_intersection_cells

# Sample step for path length integral and tangent epsilon
_PATH_LENGTH_SAMPLES = 32
_TANGENT_EPS = 1e-4


def _intersection_center() -> tuple[float, float]:
    """Center of the 2×2 intersection in grid coordinates."""
    cells = get_intersection_cells()
    if not cells:
        return (0.0, 0.0)
    n = len(cells)
    return (sum(c[0] for c in cells) / n, sum(c[1] for c in cells) / n)


def is_straight_path(in_lane_index: int, out_lane_index: int) -> bool:
    """True if this (in, out) pair is straight-through at the intersection."""
    return (in_lane_index, out_lane_index) in STRAIGHT_TRANSITIONS


def path_position(in_lane_index: int, out_lane_index: int, t: float) -> tuple[float, float]:
    """
    Position (gx, gy) along the intersection path at parameter t in [0, 1].
    Straight: line from last cell of in_lane to first cell of out_lane.
    Turn: quadratic Bezier with control at intersection center.
    """
    t = max(0.0, min(1.0, t))
    if in_lane_index < 0 or in_lane_index >= len(ALL_LANES) or not ALL_LANES[in_lane_index]:
        return (0.0, 0.0)
    if out_lane_index < 0 or out_lane_index >= len(ALL_LANES) or not ALL_LANES[out_lane_index]:
        return (0.0, 0.0)
    start = (float(ALL_LANES[in_lane_index][-1][0]), float(ALL_LANES[in_lane_index][-1][1]))
    end = (float(ALL_LANES[out_lane_index][0][0]), float(ALL_LANES[out_lane_index][0][1]))
    if is_straight_path(in_lane_index, out_lane_index):
        return (start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1]))
    control = _intersection_center()
    # Quadratic Bezier: (1-t)^2 P0 + 2(1-t)t P1 + t^2 P2
    u = 1.0 - t
    gx = u * u * start[0] + 2 * u * t * control[0] + t * t * end[0]
    gy = u * u * start[1] + 2 * u * t * control[1] + t * t * end[1]
    return (gx, gy)


def path_length(in_lane_index: int, out_lane_index: int) -> float:
    """Total length of the path in grid-space units (same scale as one cell)."""
    total = 0.0
    prev = path_position(in_lane_index, out_lane_index, 0.0)
    for i in range(1, _PATH_LENGTH_SAMPLES + 1):
        t = i / _PATH_LENGTH_SAMPLES
        p = path_position(in_lane_index, out_lane_index, t)
        total += math.hypot(p[0] - prev[0], p[1] - prev[1])
        prev = p
    return total


def path_tangent(in_lane_index: int, out_lane_index: int, t: float) -> tuple[float, float]:
    """Unit tangent (dx, dy) in grid space at parameter t. At t=1 uses t and t-eps."""
    t = max(0.0, min(1.0, t))
    if t >= 1.0 - _TANGENT_EPS:
        p1 = path_position(in_lane_index, out_lane_index, 1.0)
        p0 = path_position(in_lane_index, out_lane_index, 1.0 - _TANGENT_EPS)
    else:
        p0 = path_position(in_lane_index, out_lane_index, t)
        p1 = path_position(in_lane_index, out_lane_index, t + _TANGENT_EPS)
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def path_direction_index(in_lane_index: int, out_lane_index: int, t: float) -> int:
    """Direction index 0..3 (N,S,E,W) for sprite from path tangent at t."""
    dx, dy = path_tangent(in_lane_index, out_lane_index, t)
    if abs(dy) >= abs(dx):
        return 0 if dy > 0 else 1  # N or S
    return 2 if dx > 0 else 3  # E or W
