"""
Classify intersection connection sides from lane geometry and traffic endpoints.

Grid convention (matches sim.map_data): increasing y is North (N), decreasing y is South.
Edge labels name which side of the intersection axis-aligned bounds is pierced:
  N = north edge (cells with gy == y_hi - 1), S = south (gy == y_lo),
  E = east (gx == x_hi - 1), W = west (gx == x_lo).
"""
from __future__ import annotations

from sim import world
from sim.junction import (
    Cardinal,
    StraightAxis,
    overlay_type_for_sides,
    tee_layout_for_sides,
)
from sim.map_data import offset_for_direction


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
    dx, dy = offset_for_direction(d)
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


# Image-space quadrant order is clockwise from the ortho bottom-left (iso W / world NW),
# not world-clockwise around the AABB. N+E and S+W are therefore 3 and 1, not 1 and 3.
_PAIR_TO_QUADRANT: dict[frozenset[Cardinal], int] = {
    frozenset({"W", "N"}): 0,
    frozenset({"S", "W"}): 1,
    frozenset({"E", "S"}): 2,
    frozenset({"N", "E"}): 3,
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
    """N/S (one or both) -> ns, E/W -> ew; else default ns."""
    if active and active <= frozenset({"N", "S"}):
        return "ns"
    if active and active <= frozenset({"E", "W"}):
        return "ew"
    return "ns"


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
    if active and active <= frozenset({"N", "S"}):
        return "ns"
    if active and active <= frozenset({"E", "W"}):
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


def _raw_mouth_crossings(
    intersection_key: str,
    cells: list[tuple[int, int]],
) -> list[tuple[int, Cardinal, str, int, int]]:
    """Unfiltered (lane, edge, kind, gx, gy) mouths; includes outer twins."""
    inside = frozenset(cells)
    if not inside:
        return []
    out: list[tuple[int, Cardinal, str, int, int]] = []
    for i in world.lane_ids():
        for edge, kind, gx, gy in _crossings_for_lane(i, intersection_key, inside):
            out.append((i, edge, kind, gx, gy))
    return out


def mouth_spans_by_edge(
    intersection_key: str,
    cells: list[tuple[int, int]],
) -> dict[str, tuple[int, int]]:
    """Per pierced edge, inclusive min/max perpendicular cell of unfiltered mouths."""
    spans: dict[str, tuple[int, int]] = {}
    for _i, edge, _kind, gx, gy in _raw_mouth_crossings(intersection_key, cells):
        perp = gy if edge in ("W", "E") else gx
        if edge not in spans:
            spans[edge] = (perp, perp)
        else:
            lo, hi = spans[edge]
            spans[edge] = (min(lo, perp), max(hi, perp))
    return spans


def mouth_spans_local(
    cells: list[tuple[int, int]],
    spans: dict[str, tuple[int, int]],
) -> dict[str, tuple[int, int]]:
    """Translate world mouth spans into AABB-local cell indices [0, n)."""
    x_lo, _x_hi, y_lo, _y_hi = _bounds_from_cells(cells)
    out: dict[str, tuple[int, int]] = {}
    for edge, (a, b) in spans.items():
        if edge in ("W", "E"):
            out[edge] = (a - y_lo, b - y_lo)
        else:
            out[edge] = (a - x_lo, b - x_lo)
    return out


def twin_faces_for_intersection(
    intersection_key: str,
    cells: list[tuple[int, int]],
) -> frozenset[str]:
    """Edges whose unfiltered mouths include a twin group."""
    faces: set[str] = set()
    for i, edge, kind, _gx, _gy in _raw_mouth_crossings(intersection_key, cells):
        group = world.mouth_group(i, intersection_key, inbound=(kind == "in"))
        if len(group) >= 2:
            faces.add(edge)
    return frozenset(faces)


_EDGE_INBOUND_DIR: dict[str, str] = {"W": "E", "E": "W", "N": "S", "S": "N"}
_EDGE_OUTBOUND_DIR: dict[str, str] = {"W": "W", "E": "E", "N": "N", "S": "S"}
_EDGE_INBOUND_LOWER_PERP = frozenset({"W", "N"})


def _perp_on_edge(edge: str, gx: int, gy: int) -> int:
    return gy if edge in ("W", "E") else gx


def _consecutive_pair(perps: list[int]) -> bool:
    return len(perps) == 2 and perps[1] == perps[0] + 1


def _span_even_centered(lo: int, hi: int, aabb_lo: int, aabb_hi_excl: int) -> bool:
    width = hi - lo + 1
    if width < 2 or width % 2:
        return False
    return (lo + hi) == (aabb_lo + aabb_hi_excl - 1)


def _face_closed_dual(
    intersection_key: str,
    edge: str,
    crossings: list[tuple[int, Cardinal, str, int, int]],
    x_lo: int,
    x_hi: int,
    y_lo: int,
    y_hi: int,
) -> bool:
    """One inbound pair and one outbound pair, centred, RHT, no extra mouths."""
    ins: dict[int, int] = {}
    outs: dict[int, int] = {}
    for i, e, kind, gx, gy in crossings:
        if e != edge:
            continue
        perp = _perp_on_edge(e, gx, gy)
        if kind == "in":
            ins[i] = perp
        else:
            outs[i] = perp
    if len(ins) != 2 or len(outs) != 2:
        return False
    in_lanes = tuple(sorted(ins))
    out_lanes = tuple(sorted(outs))
    in_group = tuple(sorted(world.mouth_group(in_lanes[0], intersection_key, inbound=True)))
    out_group = tuple(sorted(world.mouth_group(out_lanes[0], intersection_key, inbound=False)))
    if in_group != in_lanes or len(in_group) != 2:
        return False
    if out_group != out_lanes or len(out_group) != 2:
        return False
    want_in = _EDGE_INBOUND_DIR.get(edge)
    want_out = _EDGE_OUTBOUND_DIR.get(edge)
    if any(world.lane_direction(i) != want_in for i in in_lanes):
        return False
    if any(world.lane_direction(i) != want_out for i in out_lanes):
        return False
    in_perps = sorted(set(ins.values()))
    out_perps = sorted(set(outs.values()))
    if not _consecutive_pair(in_perps) or not _consecutive_pair(out_perps):
        return False
    if set(in_perps) & set(out_perps):
        return False
    lo = min(in_perps[0], out_perps[0])
    hi = max(in_perps[1], out_perps[1])
    if hi - lo != 3:
        return False
    aabb_lo, aabb_hi = (y_lo, y_hi) if edge in ("W", "E") else (x_lo, x_hi)
    if not _span_even_centered(lo, hi, aabb_lo, aabb_hi):
        return False
    inbound_lower = in_perps[0] < out_perps[0]
    if edge in _EDGE_INBOUND_LOWER_PERP:
        return inbound_lower
    return not inbound_lower


def _face_ins_outs(
    edge: str,
    crossings: list[tuple[int, Cardinal, str, int, int]],
) -> tuple[dict[int, int], dict[int, int]]:
    ins: dict[int, int] = {}
    outs: dict[int, int] = {}
    for i, e, kind, gx, gy in crossings:
        if e != edge:
            continue
        perp = _perp_on_edge(e, gx, gy)
        if kind == "in":
            ins[i] = perp
        else:
            outs[i] = perp
    return ins, outs


def _face_opposed_pair(
    intersection_key: str,
    edge: str,
    crossings: list[tuple[int, Cardinal, str, int, int]],
    x_lo: int,
    x_hi: int,
    y_lo: int,
    y_hi: int,
) -> bool:
    """One inbound and one outbound, adjacent, centred. Side-of-road is not required."""
    ins, outs = _face_ins_outs(edge, crossings)
    if len(ins) != 1 or len(outs) != 1:
        return False
    in_i, in_perp = next(iter(ins.items()))
    out_i, out_perp = next(iter(outs.items()))
    if abs(in_perp - out_perp) != 1:
        return False
    want_in = _EDGE_INBOUND_DIR.get(edge)
    want_out = _EDGE_OUTBOUND_DIR.get(edge)
    if world.lane_direction(in_i) != want_in:
        return False
    if world.lane_direction(out_i) != want_out:
        return False
    lo, hi = min(in_perp, out_perp), max(in_perp, out_perp)
    aabb_lo, aabb_hi = (y_lo, y_hi) if edge in ("W", "E") else (x_lo, x_hi)
    return _span_even_centered(lo, hi, aabb_lo, aabb_hi)


def is_normal_layout(
    intersection_key: str,
    cells: list[tuple[int, int]],
    raw_active: frozenset[str],
) -> bool:
    """
    Centred opposed pair on every active face: one in, one out, RHT.

    No twins. A lone mouth, extra lane, or off-centre pair fails (those are One).
    """
    from sim import places

    family = overlay_type_for_sides(raw_active)
    if family == places.INTERSECTION_TYPE_NONE:
        return False
    if not raw_active:
        return False
    x_lo, x_hi, y_lo, y_hi = _bounds_from_cells(cells)
    crossings = _raw_mouth_crossings(intersection_key, cells)
    return all(
        _face_opposed_pair(
            intersection_key, edge, crossings, x_lo, x_hi, y_lo, y_hi
        )
        for edge in raw_active
    )


def is_double_layout(
    intersection_key: str,
    cells: list[tuple[int, int]],
    raw_active: frozenset[str],
) -> bool:
    """
    Closed dual on every active face: two pairs in and out, even-centred, RHT.

    Twin straights are never Double. A missing, extra, or off-centre lane fails.
    """
    from sim import places

    family = overlay_type_for_sides(raw_active)
    if family in (
        places.INTERSECTION_TYPE_STRAIGHT,
        places.INTERSECTION_TYPE_NONE,
    ):
        return False
    if not raw_active:
        return False
    x_lo, x_hi, y_lo, y_hi = _bounds_from_cells(cells)
    crossings = _raw_mouth_crossings(intersection_key, cells)
    return all(
        _face_closed_dual(
            intersection_key, edge, crossings, x_lo, x_hi, y_lo, y_hi
        )
        for edge in raw_active
    )


def leftover_xy_for_pair(
    n: int,
    local_spans: dict[str, tuple[int, int]],
    e1: str,
    e2: str,
) -> tuple[int, int] | None:
    """
    AABB-local leftover_x, leftover_y for one corner. Either may be 0.
    leftover_x is the east/west shoulder; leftover_y is the north/south shoulder.
    """
    pair = frozenset({e1, e2})
    n = max(0, int(n))

    def span(edge: str) -> tuple[int, int] | None:
        return local_spans.get(edge)

    if pair == frozenset({"W", "N"}) and span("W") and span("N"):
        return span("N")[0], (n - 1) - span("W")[1]
    if pair == frozenset({"S", "W"}) and span("S") and span("W"):
        return span("S")[0], span("W")[0]
    if pair == frozenset({"E", "S"}) and span("E") and span("S"):
        return (n - 1) - span("S")[1], span("E")[0]
    if pair == frozenset({"N", "E"}) and span("N") and span("E"):
        return (n - 1) - span("N")[1], (n - 1) - span("E")[1]
    return None


def corner_leftovers_from_local(
    cells: int,
    local_spans: dict[str, tuple[int, int]],
) -> tuple[tuple[int, int, int], ...]:
    """
    (quadrant, leftover_x_cells, leftover_y_cells) from AABB-local mouth spans.

    Quadrants are _PAIR_TO_QUADRANT (image-clockwise from BL). Zero leftover
    still emits the corner so the painter can stroke a throat L (no grass bite).
    """
    n = max(0, int(cells))
    out: list[tuple[int, int, int]] = []
    seen: set[int] = set()
    edges = tuple(local_spans)
    for i, a in enumerate(edges):
        for b in edges[i + 1 :]:
            pair = frozenset({a, b})
            q = _PAIR_TO_QUADRANT.get(pair)
            if q is None or q in seen:
                continue
            xy = leftover_xy_for_pair(n, local_spans, a, b)
            if xy is None:
                continue
            lx, ly = xy
            if lx >= 0 and ly >= 0:
                seen.add(q)
                out.append((q, lx, ly))
    return tuple(out)


def mixed_corner_leftovers(
    cells: list[tuple[int, int]],
    spans: dict[str, tuple[int, int]],
    active: frozenset[str],
) -> tuple[tuple[int, int, int], ...]:
    """
    (quadrant, leftover_x_cells, leftover_y_cells) for corners with two incident faces.

    Quadrants match _PAIR_TO_QUADRANT (0 W+N, 1 S+W, 2 E+S, 3 N+E).
    leftover_x is the east/west shoulder; leftover_y is the north/south shoulder.
    """
    x_lo, x_hi, _y_lo, _y_hi = _bounds_from_cells(cells)
    n = x_hi - x_lo
    local = {
        e: s
        for e, s in mouth_spans_local(cells, spans).items()
        if e in active
    }
    return corner_leftovers_from_local(n, local)


def even_travel_cells(
    span: tuple[int, int] | None,
    cells: int,
    default: int = 4,
) -> int:
    """Even mouth width, clamped to the AABB. Doubles may assume this is centered."""
    n = max(2, min(12, int(cells)))
    if n % 2:
        n -= 1
    if span is None:
        w = default
    else:
        w = span[1] - span[0] + 1
    if w % 2:
        w -= 1
    w = max(2, min(n, w))
    if w % 2:
        w -= 1
    return max(2, w)


def double_travel_xy(
    local_spans: dict[str, tuple[int, int]],
    cells: int,
) -> tuple[int, int]:
    """Even travel along x (N/S mouths) and y (E/W mouths)."""
    ns = local_spans.get("N") or local_spans.get("S")
    ew = local_spans.get("E") or local_spans.get("W")
    return even_travel_cells(ns, cells), even_travel_cells(ew, cells)


def overlay_type_for_intersection(intersection_key: str, active: frozenset[str]) -> str:
    """
    Stamp kind: Double{Cross,Tee,Corner} only for a closed dual on every
    active face (two centred in/out pairs, RHT). Other twin nodes are Mixed.
    Twin straights stay Mixed through-band (no Double Straight).
    No twins: Normal if every face is a centred opposed pair; One if a face
    has a lone mouth (mouth-span Mixed painter).
    """
    from sim import places

    cells = list(world.get_intersection_cells_by_key(intersection_key) or [])
    if not world.intersection_has_twins(intersection_key):
        raw_active, _, _ = classify_intersection_sides(
            intersection_key, cells, require_centre_two=False
        )
        family = overlay_type_for_sides(raw_active or active)
        if family == places.INTERSECTION_TYPE_NONE:
            return family
        if is_normal_layout(intersection_key, cells, raw_active):
            return {
                places.INTERSECTION_TYPE_CROSS: places.INTERSECTION_TYPE_NORMAL_CROSS,
                places.INTERSECTION_TYPE_TEE: places.INTERSECTION_TYPE_NORMAL_TEE,
                places.INTERSECTION_TYPE_CORNER: places.INTERSECTION_TYPE_NORMAL_CORNER,
                places.INTERSECTION_TYPE_STRAIGHT: places.INTERSECTION_TYPE_NORMAL_STRAIGHT,
            }.get(family, places.INTERSECTION_TYPE_NORMAL_CROSS)
        return {
            places.INTERSECTION_TYPE_CROSS: places.INTERSECTION_TYPE_ONE_CROSS,
            places.INTERSECTION_TYPE_TEE: places.INTERSECTION_TYPE_ONE_TEE,
            places.INTERSECTION_TYPE_CORNER: places.INTERSECTION_TYPE_ONE_CORNER,
            places.INTERSECTION_TYPE_STRAIGHT: places.INTERSECTION_TYPE_ONE_STRAIGHT,
        }.get(family, places.INTERSECTION_TYPE_ONE_CROSS)
    raw_active, _, _ = classify_intersection_sides(
        intersection_key, cells, require_centre_two=False
    )
    family = overlay_type_for_sides(raw_active)
    if family == places.INTERSECTION_TYPE_STRAIGHT:
        return places.INTERSECTION_TYPE_MIXED_STRAIGHT
    if family == places.INTERSECTION_TYPE_NONE:
        return family
    if is_double_layout(intersection_key, cells, raw_active):
        return {
            places.INTERSECTION_TYPE_CROSS: places.INTERSECTION_TYPE_DOUBLE_CROSS,
            places.INTERSECTION_TYPE_TEE: places.INTERSECTION_TYPE_DOUBLE_TEE,
            places.INTERSECTION_TYPE_CORNER: places.INTERSECTION_TYPE_DOUBLE_CORNER,
        }.get(family, places.INTERSECTION_TYPE_DOUBLE_CROSS)
    return {
        places.INTERSECTION_TYPE_CROSS: places.INTERSECTION_TYPE_MIXED_CROSS,
        places.INTERSECTION_TYPE_TEE: places.INTERSECTION_TYPE_MIXED_TEE,
        places.INTERSECTION_TYPE_CORNER: places.INTERSECTION_TYPE_MIXED_CORNER,
    }.get(family, places.INTERSECTION_TYPE_MIXED_CROSS)
