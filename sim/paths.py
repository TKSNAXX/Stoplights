"""
Intersection paths: one path per (in_lane, out_lane) pair.
Straight-through = line segment; turns = quarter-circular arc tangent to inbound lane at start.
Curves are fitted once in rebuild_path_cache (called from world.rebuild_world).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from sim import world

# Sample step for path length integral and tangent epsilon
_PATH_LENGTH_SAMPLES = 32
_TANGENT_EPS = 1e-4
_STRAIGHT_DOT_MIN = 0.9


@dataclass(frozen=True, slots=True)
class _PathCurve:
    kind: str  # straight | arc | cubic
    start: tuple[float, float]
    end: tuple[float, float]
    length: float
    tin: tuple[float, float]
    tout: tuple[float, float]
    center: tuple[float, float] | None = None
    radius: float = 0.0
    start_angle: float = 0.0
    delta: float = 0.0
    p1: tuple[float, float] | None = None
    p2: tuple[float, float] | None = None


_PATH_CACHE: dict[tuple[int, int], _PathCurve] = {}


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


def _arc_angles(
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
) -> tuple[float, float]:
    """Start angle and signed delta for a quarter-circular turn arc."""
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
    return (start_angle, delta)


def _turn_arc_position(
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    r: float,
    t: float,
) -> tuple[float, float]:
    """Position on quarter-circular arc from start to end; arc starts tangent to inbound lane."""
    cx, cy = center
    start_angle, delta = _arc_angles(start, end, center)
    angle = start_angle + t * delta
    return (cx + r * math.cos(angle), cy + r * math.sin(angle))


def _cubic_handles(
    start: tuple[float, float],
    end: tuple[float, float],
    tin: tuple[float, float],
    tout: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    sx, sy = start
    ex, ey = end
    chord = math.hypot(ex - sx, ey - sy)
    handle = max(0.5, 0.5 * chord)
    p1 = (sx + tin[0] * handle, sy + tin[1] * handle)
    p2 = (ex - tout[0] * handle, ey - tout[1] * handle)
    return (p1, p2)


def _bezier_position(
    start: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    end: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    sx, sy = start
    ex, ey = end
    u = 1.0 - t
    gx = u * u * u * sx + 3.0 * u * u * t * p1[0] + 3.0 * u * t * t * p2[0] + t * t * t * ex
    gy = u * u * u * sy + 3.0 * u * u * t * p1[1] + 3.0 * u * t * t * p2[1] + t * t * t * ey
    return (gx, gy)


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
    p1, p2 = _cubic_handles(start, end, tin, tout)
    return _bezier_position(start, p1, p2, end, t)


def _tangents_are_straight(tin: tuple[float, float], tout: tuple[float, float]) -> bool:
    if tin == (0.0, 0.0) or tout == (0.0, 0.0):
        return False
    return tin[0] * tout[0] + tin[1] * tout[1] >= _STRAIGHT_DOT_MIN


def is_straight_path(in_lane_index: int, out_lane_index: int) -> bool:
    """True if inbound and outbound tangents are aligned (straight-through)."""
    cached = _PATH_CACHE.get((in_lane_index, out_lane_index))
    if cached is not None:
        return cached.kind == "straight"
    tin = _inbound_tangent(in_lane_index)
    tout = _outbound_tangent(out_lane_index)
    return _tangents_are_straight(tin, tout)


def _eval_curve(curve: _PathCurve, t: float) -> tuple[float, float]:
    t = max(0.0, min(1.0, t))
    if curve.kind == "straight":
        sx, sy = curve.start
        ex, ey = curve.end
        return (sx + t * (ex - sx), sy + t * (ey - sy))
    if curve.kind == "arc" and curve.center is not None:
        cx, cy = curve.center
        angle = curve.start_angle + t * curve.delta
        return (cx + curve.radius * math.cos(angle), cy + curve.radius * math.sin(angle))
    if curve.p1 is not None and curve.p2 is not None:
        return _bezier_position(curve.start, curve.p1, curve.p2, curve.end, t)
    sx, sy = curve.start
    ex, ey = curve.end
    return (sx + t * (ex - sx), sy + t * (ey - sy))


def _sample_length(eval_at) -> float:
    total = 0.0
    prev = eval_at(0.0)
    for i in range(1, _PATH_LENGTH_SAMPLES + 1):
        p = eval_at(i / _PATH_LENGTH_SAMPLES)
        total += math.hypot(p[0] - prev[0], p[1] - prev[1])
        prev = p
    return total


def compute_path_position(in_lane_index: int, out_lane_index: int, t: float) -> tuple[float, float]:
    """Uncached path position (for tests and cache-miss fallback)."""
    t = max(0.0, min(1.0, t))
    in_lane = world.get_lane_cells(in_lane_index)
    if not in_lane:
        return (0.0, 0.0)
    out_lane = world.get_lane_cells(out_lane_index)
    if not out_lane:
        return (0.0, 0.0)
    start = (float(in_lane[-1][0]), float(in_lane[-1][1]))
    end = (float(out_lane[0][0]), float(out_lane[0][1]))
    tin = _inbound_tangent(in_lane_index)
    tout = _outbound_tangent(out_lane_index)
    if _tangents_are_straight(tin, tout):
        return (start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1]))
    arc_result = _turn_arc_center_and_radius(start, end, tin, tout)
    if arc_result is not None:
        center, radius = arc_result
        if _arc_reaches_end(end, center, radius):
            return _turn_arc_position(start, end, center, radius, t)
    return _turn_cubic_position(start, end, tin, tout, t)


def _fit_path_curve(in_lane_index: int, out_lane_index: int) -> _PathCurve | None:
    in_lane = world.get_lane_cells(in_lane_index)
    out_lane = world.get_lane_cells(out_lane_index)
    if not in_lane or not out_lane:
        return None
    start = (float(in_lane[-1][0]), float(in_lane[-1][1]))
    end = (float(out_lane[0][0]), float(out_lane[0][1]))
    tin = _inbound_tangent(in_lane_index)
    tout = _outbound_tangent(out_lane_index)
    if _tangents_are_straight(tin, tout):
        curve = _PathCurve(kind="straight", start=start, end=end, length=0.0, tin=tin, tout=tout)
        length = _sample_length(lambda t, c=curve: _eval_curve(c, t))
        return _PathCurve(kind="straight", start=start, end=end, length=length, tin=tin, tout=tout)
    arc_result = _turn_arc_center_and_radius(start, end, tin, tout)
    if arc_result is not None:
        center, radius = arc_result
        if _arc_reaches_end(end, center, radius):
            start_angle, delta = _arc_angles(start, end, center)
            curve = _PathCurve(
                kind="arc",
                start=start,
                end=end,
                length=0.0,
                tin=tin,
                tout=tout,
                center=center,
                radius=radius,
                start_angle=start_angle,
                delta=delta,
            )
            length = _sample_length(lambda t, c=curve: _eval_curve(c, t))
            return _PathCurve(
                kind="arc",
                start=start,
                end=end,
                length=length,
                tin=tin,
                tout=tout,
                center=center,
                radius=radius,
                start_angle=start_angle,
                delta=delta,
            )
    p1, p2 = _cubic_handles(start, end, tin, tout)
    curve = _PathCurve(kind="cubic", start=start, end=end, length=0.0, tin=tin, tout=tout, p1=p1, p2=p2)
    length = _sample_length(lambda t, c=curve: _eval_curve(c, t))
    return _PathCurve(kind="cubic", start=start, end=end, length=length, tin=tin, tout=tout, p1=p1, p2=p2)


def rebuild_path_cache() -> None:
    """Fit and store curves for every in-lane/out-lane pair sharing an intersection."""
    global _PATH_CACHE
    cache: dict[tuple[int, int], _PathCurve] = {}
    for in_lane in world.in_lane_ids():
        node = world.lane_traffic_out(in_lane)
        if not world.is_intersection(node):
            continue
        for out_lane in world.outgoing_lanes(node):
            curve = _fit_path_curve(in_lane, out_lane)
            if curve is not None:
                cache[(in_lane, out_lane)] = curve
    _PATH_CACHE = cache


def path_position(in_lane_index: int, out_lane_index: int, t: float) -> tuple[float, float]:
    """
    Position (gx, gy) along the intersection path at parameter t in [0, 1].
    Straight: line from last cell of in_lane to first cell of out_lane.
    Turn: circular arc when valid; cubic-tangent fallback for wide/invalid arc fits.
    """
    cached = _PATH_CACHE.get((in_lane_index, out_lane_index))
    if cached is not None:
        return _eval_curve(cached, t)
    return compute_path_position(in_lane_index, out_lane_index, t)


def path_length(in_lane_index: int, out_lane_index: int) -> float:
    """Total length of the path in grid-space units (same scale as one cell)."""
    cached = _PATH_CACHE.get((in_lane_index, out_lane_index))
    if cached is not None:
        return cached.length
    return _sample_length(lambda t: compute_path_position(in_lane_index, out_lane_index, t))


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
