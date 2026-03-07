"""
Intersection paths: one path per (in_lane, out_lane) pair.
Straight-through = line segment; turns = quarter-circular arc tangent to inbound lane at start.
"""
from __future__ import annotations

import math

from sim.places import STRAIGHT_TRANSITIONS
from sim.world import ALL_LANES, intersection_center

# Sample step for path length integral and tangent epsilon
_PATH_LENGTH_SAMPLES = 32
_TANGENT_EPS = 1e-4

# Arc center (grid) for each turn: chosen so (center - start) perpendicular to lane direction.
_TURN_ARC_CENTER: dict[tuple[int, int], tuple[float, float]] = {
    (0, 5): (20, 16),   # S→E right
    (0, 7): (17, 16),   # S→W vert left
    (2, 7): (17, 19),   # N→W right
    (2, 5): (20, 19),   # N→E vert left
    (4, 1): (20, 19),   # E→N right
    (4, 3): (20, 16),   # E→S horiz left
    (6, 3): (17, 16),   # W→S right
    (6, 1): (17, 19),   # W→N horiz left
}

# Radius: 1 for right turns, 2 for left turns.
_TURN_RADIUS: dict[tuple[int, int], float] = {
    (0, 5): 1.0, (2, 7): 1.0, (4, 1): 1.0, (6, 3): 1.0,
    (0, 7): 2.0, (2, 5): 2.0, (4, 3): 2.0, (6, 1): 2.0,
}


def _turn_arc_position(
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    r: float,
    t: float,
) -> tuple[float, float]:
    """Position on quarter-circular arc from start to end; arc starts tangent to inbound lane."""
    cx, cy = center
    start_angle = math.atan2(start[1] - cy, start[0] - cx)
    end_angle = math.atan2(end[1] - cy, end[0] - cx)
    delta = end_angle - start_angle
    if delta > math.pi:
        delta -= 2.0 * math.pi
    elif delta < -math.pi:
        delta += 2.0 * math.pi
    if abs(delta) > math.pi / 2 + 0.01:
        delta = delta - (2.0 * math.pi if delta > 0 else -2.0 * math.pi)
    angle = start_angle + t * delta
    return (cx + r * math.cos(angle), cy + r * math.sin(angle))


def is_straight_path(in_lane_index: int, out_lane_index: int) -> bool:
    """True if this (in, out) pair is straight-through at the intersection."""
    return (in_lane_index, out_lane_index) in STRAIGHT_TRANSITIONS


def path_position(in_lane_index: int, out_lane_index: int, t: float) -> tuple[float, float]:
    """
    Position (gx, gy) along the intersection path at parameter t in [0, 1].
    Straight: line from last cell of in_lane to first cell of out_lane.
    Turn: quarter-circular arc tangent to inbound lane at start; Bezier fallback for other pairs.
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
    key = (in_lane_index, out_lane_index)
    if key in _TURN_ARC_CENTER and key in _TURN_RADIUS:
        return _turn_arc_position(start, end, _TURN_ARC_CENTER[key], _TURN_RADIUS[key], t)
    control = intersection_center()
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


def path_direction_index_8(in_lane_index: int, out_lane_index: int, t: float) -> int:
    """Direction index 0..7 (N, NE, E, SE, S, SW, W, NW) for sprite from path tangent at t."""
    dx, dy = path_tangent(in_lane_index, out_lane_index, t)
    return direction_index_8_from_tangent(dx, dy)


def lane_segment_position(lane_index: int, from_pos: int, to_pos: int, t: float) -> tuple[float, float]:
    """Continuous position on a lane segment between two lane cell indices."""
    t = max(0.0, min(1.0, t))
    if lane_index < 0 or lane_index >= len(ALL_LANES):
        return (0.0, 0.0)
    lane = ALL_LANES[lane_index]
    if not lane:
        return (0.0, 0.0)
    if from_pos < 0 or from_pos >= len(lane) or to_pos < 0 or to_pos >= len(lane):
        return (float(lane[0][0]), float(lane[0][1]))
    start = lane[from_pos]
    end = lane[to_pos]
    return (start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1]))


def lane_segment_tangent(lane_index: int, from_pos: int, to_pos: int) -> tuple[float, float]:
    """Unit tangent of a lane segment between two lane cell indices."""
    if lane_index < 0 or lane_index >= len(ALL_LANES):
        return (0.0, 0.0)
    lane = ALL_LANES[lane_index]
    if not lane:
        return (0.0, 0.0)
    if from_pos < 0 or from_pos >= len(lane) or to_pos < 0 or to_pos >= len(lane):
        return (0.0, 0.0)
    dx = lane[to_pos][0] - lane[from_pos][0]
    dy = lane[to_pos][1] - lane[from_pos][1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def direction_index_8_from_tangent(dx: float, dy: float) -> int:
    """Direction index 0..7 (N, NE, E, SE, S, SW, W, NW) from tangent."""
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return 0
    angle = math.atan2(dy, dx)
    idx = round((math.pi / 2 - angle) / (math.pi / 4)) % 8
    return int(idx)
