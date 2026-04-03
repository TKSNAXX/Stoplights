"""
Intersection paths: one path per (in_lane, out_lane) pair.
Straight-through = line segment; turns = quarter-circular arc tangent to inbound lane at start.
"""
from __future__ import annotations

import math

from sim.places import STRAIGHT_TRANSITIONS
from sim import world

# Sample step for path length integral and tangent epsilon
_PATH_LENGTH_SAMPLES = 32
_TANGENT_EPS = 1e-4


def _inbound_tangent(lane_index: int) -> tuple[float, float]:
    """Unit tangent at the end of the lane (direction into the intersection)."""
    lane = world.get_lane_cells(lane_index)
    if not lane or len(lane) < 2:
        return (0.0, 0.0)
    dx = float(lane[-1][0] - lane[-2][0])
    dy = float(lane[-1][1] - lane[-2][1])
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _outbound_tangent(lane_index: int) -> tuple[float, float]:
    """Unit tangent at the start of the lane (direction out of the intersection)."""
    lane = world.get_lane_cells(lane_index)
    if not lane or len(lane) < 2:
        return (0.0, 0.0)
    dx = float(lane[1][0] - lane[0][0])
    dy = float(lane[1][1] - lane[0][1])
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _turn_arc_center_and_radius(
    start: tuple[float, float],
    end: tuple[float, float],
    tin: tuple[float, float],
    tout: tuple[float, float],
) -> tuple[tuple[float, float], float] | None:
    """
    Compute arc center and radius for a 90-degree turn.
    Center satisfies (C-S) perp Tin and (C-E) perp Tout.
    Returns (center, radius) or None if degenerate.
    """
    sx, sy = start
    ex, ey = end
    dix, diy = tin
    dox, doy = tout
    det = dix * doy - diy * dox
    if abs(det) < 1e-9:
        return None
    rhs = ex * dox + ey * doy - sx * dox - sy * doy
    t = rhs / det
    cx = sx - t * diy
    cy = sy + t * dix
    r = math.hypot(cx - sx, cy - sy)
    if r < 1e-6:
        return None
    return ((cx, cy), r)


def _arc_reaches_end(
    end: tuple[float, float],
    center: tuple[float, float],
    r: float,
    tol: float = 1e-3,
) -> bool:
    """True when end lies on the same circle radius as start."""
    return abs(math.hypot(end[0] - center[0], end[1] - center[1]) - r) <= tol


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


def _turn_cubic_position(
    start: tuple[float, float],
    end: tuple[float, float],
    tin: tuple[float, float],
    tout: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    """
    Cubic Bezier fallback for turns.
    Guarantees exact endpoints while preserving inbound/outbound tangents.
    """
    sx, sy = start
    ex, ey = end
    chord = math.hypot(ex - sx, ey - sy)
    handle = max(0.5, 0.5 * chord)
    p1 = (sx + tin[0] * handle, sy + tin[1] * handle)
    p2 = (ex - tout[0] * handle, ey - tout[1] * handle)
    u = 1.0 - t
    gx = u * u * u * sx + 3.0 * u * u * t * p1[0] + 3.0 * u * t * t * p2[0] + t * t * t * ex
    gy = u * u * u * sy + 3.0 * u * u * t * p1[1] + 3.0 * u * t * t * p2[1] + t * t * t * ey
    return (gx, gy)


def is_straight_path(in_lane_index: int, out_lane_index: int) -> bool:
    """True if this (in, out) pair is straight-through at the intersection."""
    return (in_lane_index, out_lane_index) in STRAIGHT_TRANSITIONS


def path_position(in_lane_index: int, out_lane_index: int, t: float) -> tuple[float, float]:
    """
    Position (gx, gy) along the intersection path at parameter t in [0, 1].
    Straight: line from last cell of in_lane to first cell of out_lane.
    Turn: circular arc when valid; cubic-tangent fallback for wide/invalid arc fits.
    """
    t = max(0.0, min(1.0, t))
    in_lane = world.get_lane_cells(in_lane_index)
    if not in_lane:
        return (0.0, 0.0)
    out_lane = world.get_lane_cells(out_lane_index)
    if not out_lane:
        return (0.0, 0.0)
    start = (float(in_lane[-1][0]), float(in_lane[-1][1]))
    end = (float(out_lane[0][0]), float(out_lane[0][1]))
    if is_straight_path(in_lane_index, out_lane_index):
        return (start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1]))
    tin = _inbound_tangent(in_lane_index)
    tout = _outbound_tangent(out_lane_index)
    arc_result = _turn_arc_center_and_radius(start, end, tin, tout)
    if arc_result is not None:
        center, radius = arc_result
        if _arc_reaches_end(end, center, radius):
            return _turn_arc_position(start, end, center, radius, t)
    # Fallback guarantees no snap at lane handoff and keeps turn tangents.
    return _turn_cubic_position(start, end, tin, tout, t)


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
    lane = world.get_lane_cells(lane_index)
    if not lane:
        return (0.0, 0.0)
    if from_pos < 0 or from_pos >= len(lane) or to_pos < 0 or to_pos >= len(lane):
        return (float(lane[0][0]), float(lane[0][1]))
    start = lane[from_pos]
    end = lane[to_pos]
    return (start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1]))


def lane_segment_tangent(lane_index: int, from_pos: int, to_pos: int) -> tuple[float, float]:
    """Unit tangent of a lane segment between two lane cell indices."""
    lane = world.get_lane_cells(lane_index)
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
