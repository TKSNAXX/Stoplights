"""
Classify intersection connection sides from lane geometry and traffic endpoints.

Grid convention (matches sim.map_data): increasing y is North (N), decreasing y is South.
Edge labels name which side of the intersection axis-aligned bounds is pierced:
  N = north edge (cells with gy == y_hi - 1), S = south (gy == y_lo),
  E = east (gx == x_hi - 1), W = west (gx == x_lo).
"""
from __future__ import annotations

from typing import Literal

from sim import world
from sim.map_data import _offset_for_direction

Cardinal = Literal["N", "S", "E", "W"]
StraightAxis = Literal["ns", "ew"]


def _bounds_from_cells(cells: list[tuple[int, int]]) -> tuple[int, int, int, int]:
    if not cells:
        return (0, 0, 0, 0)
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    return (min(xs), max(xs) + 1, min(ys), max(ys) + 1)


def _middle_two_indices(lo: int, hi: int) -> tuple[int, int]:
    """hi exclusive; return two centre indices along that axis (even span)."""
    n = hi - lo
    if n < 2:
        return (lo, lo)
    t0 = lo + (n - 2) // 2
    return (t0, t0 + 1)


def _edge_for_step_into(dgx: int, dgy: int) -> Cardinal:
    """Outside stepped by (dgx,dgy) into intersection; label pierced edge."""
    if dgx > 0:
        return "W"
    if dgx < 0:
        return "E"
    if dgy > 0:
        return "S"
    if dgy < 0:
        return "N"
    return "W"


def _edge_for_step_out(dx_lane: int, dy_lane: int) -> Cardinal:
    """Inside cell is upstream of first lane cell along -lane direction."""
    if dx_lane > 0:
        return "E"
    if dx_lane < 0:
        return "W"
    if dy_lane > 0:
        return "N"
    if dy_lane < 0:
        return "S"
    return "W"


def _crossing_on_centre_two(
    edge: Cardinal,
    gx_inside: int,
    gy_inside: int,
    x_lo: int,
    x_hi: int,
    y_lo: int,
    y_hi: int,
) -> bool:
    mx0, mx1 = _middle_two_indices(x_lo, x_hi)
    my0, my1 = _middle_two_indices(y_lo, y_hi)
    if edge in ("W", "E"):
        return gy_inside in (my0, my1)
    return gx_inside in (mx0, mx1)


def _crossings_for_lane(
    i: int,
    intersection_key: str,
    inside: frozenset[tuple[int, int]],
) -> list[tuple[Cardinal, str, int, int]]:
    """List of (edge, 'in'|'out', gx_inside, gy_inside)."""
    tin = world.lane_traffic_in(i)
    tout = world.lane_traffic_out(i)
    if intersection_key not in (tin, tout):
        return []
    lane = list(world.get_lane_cells(i))
    if not lane:
        return []
    d = world.lane_direction(i)
    dx, dy = _offset_for_direction(d)
    out: list[tuple[Cardinal, str, int, int]] = []

    for j in range(len(lane) - 1):
        c0, c1 = lane[j], lane[j + 1]
        i0, i1 = c0 in inside, c1 in inside
        if i0 == i1:
            continue
        if i1:
            edge = _edge_for_step_into(c1[0] - c0[0], c1[1] - c0[1])
            gx, gy = c1[0], c1[1]
            kind = "in" if tout == intersection_key else "out"
        else:
            edge = _edge_for_step_into(c0[0] - c1[0], c0[1] - c1[1])
            gx, gy = c0[0], c0[1]
            kind = "out" if tin == intersection_key else "in"
        out.append((edge, kind, gx, gy))
        return out

    if not out:
        if tout == intersection_key:
            L = lane[-1]
            n = (L[0] + dx, L[1] + dy)
            if n in inside:
                edge = _edge_for_step_into(dx, dy)
                out.append((edge, "in", n[0], n[1]))
        elif tin == intersection_key:
            F = lane[0]
            n = (F[0] - dx, F[1] - dy)
            if n in inside:
                edge = _edge_for_step_out(dx, dy)
                out.append((edge, "out", n[0], n[1]))

    return out


def classify_intersection_sides(
    intersection_key: str,
    cells: list[tuple[int, int]],
    require_centre_two: bool = True,
) -> tuple[frozenset[Cardinal], frozenset[Cardinal], frozenset[Cardinal]]:
    """
    Return (active_sides, sides_with_in, sides_with_out).
    """
    inside = frozenset(cells)
    if not inside:
        return frozenset(), frozenset(), frozenset()

    x_lo, x_hi, y_lo, y_hi = _bounds_from_cells(cells)
    raw: list[tuple[Cardinal, str, int, int]] = []
    for i in world.lane_ids():
        raw.extend(_crossings_for_lane(i, intersection_key, inside))

    if require_centre_two and raw:
        filtered = [
            t
            for t in raw
            if _crossing_on_centre_two(t[0], t[2], t[3], x_lo, x_hi, y_lo, y_hi)
        ]
        if filtered:
            raw = filtered
        # else keep unfiltered (no qualifying centre-two crossings)

    sides_in: set[Cardinal] = set()
    sides_out: set[Cardinal] = set()
    for edge, kind, _, _ in raw:
        if kind == "in":
            sides_in.add(edge)
        else:
            sides_out.add(edge)
    active = frozenset(sides_in | sides_out)
    return active, frozenset(sides_in), frozenset(sides_out)


# Quadrant presets for make_corner; bypass (W+N arms) uses quadrant 0.
_PAIR_TO_QUADRANT: dict[frozenset[Cardinal], int] = {
    frozenset({"W", "N"}): 0,
    frozenset({"N", "E"}): 1,
    frozenset({"E", "S"}): 2,
    frozenset({"S", "W"}): 3,
}


def corner_quadrant_for_sides(active: frozenset[Cardinal]) -> int:
    """Map two perpendicular active sides to corner quadrant 0..3; else 0."""
    if len(active) != 2:
        return 0
    a, b = tuple(active)
    if (a in "NS" and b in "NS") or (a in "EW" and b in "EW"):
        return 0
    return _PAIR_TO_QUADRANT.get(frozenset(active), 0)


def straight_axis_for_sides(active: frozenset[Cardinal]) -> StraightAxis:
    """N+S -> ns, E+W -> ew; else default ns (ambiguous; prefer straight_axis_for_intersection)."""
    if active == frozenset({"N", "S"}):
        return "ns"
    if active == frozenset({"E", "W"}):
        return "ew"
    return "ns"


_OPPOSITE_CARDINAL: dict[Cardinal, Cardinal] = {"N": "S", "S": "N", "E": "W", "W": "E"}
_ALL_CARDINALS: frozenset[Cardinal] = frozenset({"N", "S", "E", "W"})


def tee_corner_quadrants(stem: Cardinal) -> tuple[int, int]:
    """
    Two fillet quadrants on the through-band stem side.

    Matches make_tee omit_white: E/N skip the lo curb (top / left), W/S skip hi
    (bottom / right). World-east AABB corners are not the same pair — using those
    painted one branch corner and the open-face punch erased the other.
    """
    if stem == "E":
        return (2, 3)  # top (ns omit lo)
    if stem == "W":
        return (0, 1)  # bottom
    if stem == "N":
        return (0, 3)  # left (ew omit lo)
    return (1, 2)  # S: right


def tee_layout_for_sides(
    active: frozenset[Cardinal],
    through_fallback: StraightAxis = "ns",
) -> tuple[StraightAxis, Cardinal]:
    """
    Through axis and stem cardinal for a tee overlay.

    Three active sides: missing face is open (transparent); stem is opposite the
    gap; through is the remaining pair.
    Otherwise: use through_fallback; stem is a perpendicular active side, else S.
    """
    if len(active) == 3:
        missing = next(iter(_ALL_CARDINALS - active))
        stem = _OPPOSITE_CARDINAL[missing]
        axis: StraightAxis = "ew" if stem in ("N", "S") else "ns"
        return axis, stem
    axis = through_fallback if through_fallback in ("ns", "ew") else "ns"
    perp: frozenset[Cardinal] = frozenset({"E", "W"}) if axis == "ns" else frozenset({"N", "S"})
    for side in ("N", "S", "E", "W"):
        if side in active and side in perp:
            return axis, side
    return axis, "S"


def straight_axis_for_intersection(
    intersection_key: str,
    cells: list[tuple[int, int]],
    active: frozenset[Cardinal],
) -> StraightAxis:
    """
    Through axis for straight overlay. Pure N+S / E+W use that axis; otherwise prefer **lane
    travel direction** (N/S-bound lanes vs E/W-bound) among lanes incident to this intersection.
    Edge-based crossing counts can skew E/W on symmetric maps; direction counts match road run.
    Tie -> ns.
    """
    if active == frozenset({"N", "S"}):
        return "ns"
    if active == frozenset({"E", "W"}):
        return "ew"
    score_ns = 0
    score_ew = 0
    for i in world.lane_ids():
        tin = world.lane_traffic_in(i)
        tout = world.lane_traffic_out(i)
        if intersection_key not in (tin, tout):
            continue
        d = world.lane_direction(i)
        if d in ("N", "S"):
            score_ns += 1
        elif d in ("E", "W"):
            score_ew += 1
    if score_ew > score_ns:
        return "ew"
    return "ns"


def straight_cross_cap_cells(cells: list[tuple[int, int]], axis: StraightAxis) -> set[tuple[int, int]]:
    """
    Perimeter cells one step outside the block on cross arms only, centre-two positions.
    For ns through: west/east of bounds; for ew through: south/north.
    """
    x_lo, x_hi, y_lo, y_hi = _bounds_from_cells(cells)
    if x_hi <= x_lo or y_hi <= y_lo:
        return set()
    mx0, mx1 = _middle_two_indices(x_lo, x_hi)
    my0, my1 = _middle_two_indices(y_lo, y_hi)
    caps: set[tuple[int, int]] = set()
    if axis == "ns":
        for y in (my0, my1):
            caps.add((x_lo - 1, y))
            caps.add((x_hi, y))
    else:
        for x in (mx0, mx1):
            caps.add((x, y_lo - 1))
            caps.add((x, y_hi))
    return caps
