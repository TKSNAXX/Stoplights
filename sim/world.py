"""
World grid and lane geometry.

Uniform intersections and stable lane ids. No main/bypass/extra special cases.
Topology tables are filled only in rebuild_world.
"""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from sim import map_data
from sim.constants import INBOUND_TAIL_CELLS

if TYPE_CHECKING:
    from sim.places import IntersectionConfig, LaneConfig


class _IntersectionState:
    __slots__ = ("key", "cells", "slots", "bounds", "cells_set")

    def __init__(
        self,
        key: str,
        cells: list[tuple[int, int]],
        slots: list[tuple[int, int]],
        bounds: tuple[int, int, int, int],
    ) -> None:
        self.key = key
        self.cells = cells
        self.slots = slots
        self.bounds = bounds
        self.cells_set = frozenset(cells)


class _WorldState:
    """Mutable world geometry. Updated by rebuild_world."""

    def __init__(self) -> None:
        self.lanes: dict[int, tuple[tuple[int, int], ...]] = {}
        self.lane_meta: dict[int, tuple[str, str, str]] = {}
        self.x_lo: int = 0
        self.y_lo: int = 0
        self.x_hi: int = 1
        self.y_hi: int = 1
        self.place_rects: dict[str, dict] = {}
        self.intersections: dict[str, _IntersectionState] = {}
        self.outgoing: dict[str, tuple[int, ...]] = {}
        self.incoming: dict[str, tuple[int, ...]] = {}
        self.in_lane_ids: frozenset[int] = frozenset()
        self.out_lane_ids: frozenset[int] = frozenset()
        self.lane_graph: dict[str, set[str]] = {}
        self.attached: dict[str, frozenset[str]] = {}
        self.cell_to_intersections: dict[tuple[int, int], tuple[str, ...]] = {}
        self.cell_to_lane: dict[tuple[int, int], int] = {}
        self.cell_to_lane_pos: dict[tuple[int, int], tuple[int, int]] = {}
        self.oncoming: dict[int, int | None] = {}
        self.sister_links: dict[int, tuple[tuple[int, str], ...]] = {}
        self.merge_sides: dict[tuple[int, int], str] = {}
        self.best_next_hops: dict[tuple[str, str], frozenset[str]] = {}


_state = _WorldState()


def _compute_bounds(
    lanes: dict[int, list[tuple[int, int]] | tuple[tuple[int, int], ...]],
    place_rects: dict[str, dict],
    intersection_dicts: dict[str, dict],
) -> tuple[int, int, int, int]:
    """
    Axis-aligned content bounds (x_lo, y_lo, x_hi, y_hi) with hi exclusive.
    Authored coordinates are not shifted.
    """
    all_x: list[int] = []
    all_y: list[int] = []

    for lane in lanes.values():
        for cx, cy in lane:
            all_x.append(cx)
            all_y.append(cy)
    for r in place_rects.values():
        rx, ry = int(r.get("x", 0)), int(r.get("y", 0))
        rw, rh = int(r.get("w", 0)), int(r.get("h", 0))
        all_x.extend([rx, rx + rw - 1] if rw else [rx])
        all_y.extend([ry, ry + rh - 1] if rh else [ry])
    for inter in intersection_dicts.values():
        for c in inter.get("cells", []):
            all_x.append(c[0])
            all_y.append(c[1])

    if not all_x or not all_y:
        return (0, 0, 1, 1)

    return (min(all_x), min(all_y), max(all_x) + 1, max(all_y) + 1)


def rebuild_world(
    place_rects: dict[str, dict],
    intersections: dict[str, "IntersectionConfig"],
    lanes: dict[int, "LaneConfig"],
) -> None:
    """
    Rebuild lanes and intersection geometry from places, intersections, and lanes.
    All intersections share one code path. Topology tables are filled here only.
    """
    intersection_bounds: dict[str, tuple[int, int, int, int]] = {}
    intersection_dicts: dict[str, dict] = {}
    for key, cfg in intersections.items():
        size = max(2, min(12, int(cfg.size_cells)))
        if size % 2 != 0:
            size = (size // 2) * 2
        bounds = map_data.bounds_from_center(cfg.center_x, cfg.center_y, size)
        intersection_bounds[key] = bounds
        x_lo, x_hi, y_lo, y_hi = bounds
        intersection_dicts[key] = map_data.intersection_dict_from_bounds(x_lo, x_hi, y_lo, y_hi)

    lane_cells, lane_meta = map_data.build_lanes_from_config(
        place_rects, intersection_bounds, lanes or {}
    )

    x_lo, y_lo, x_hi, y_hi = _compute_bounds(lane_cells, place_rects, intersection_dicts)

    _state.lanes = {idx: tuple(tuple(c) for c in cells) for idx, cells in lane_cells.items()}
    _state.lane_meta = dict(lane_meta)
    _state.place_rects = dict(place_rects)
    _state.x_lo, _state.y_lo, _state.x_hi, _state.y_hi = x_lo, y_lo, x_hi, y_hi
    _state.intersections = {}
    for key, d in intersection_dicts.items():
        bounds = (int(d["x_lo"]), int(d["x_hi"]), int(d["y_lo"]), int(d["y_hi"]))
        cells = [tuple(c) for c in d.get("cells", [])]
        slots = [tuple(c) for c in d.get("slots", [])]
        _state.intersections[key] = _IntersectionState(key, cells, slots, bounds)

    _refresh_topology()
    from sim.paths import rebuild_path_cache

    rebuild_path_cache()


_OPPOSITE_DIR = {"N": "S", "S": "N", "E": "W", "W": "E"}


def _lane_span(cells: tuple[tuple[int, int], ...]) -> tuple[int, int, int, int]:
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    return min(xs), max(xs), min(ys), max(ys)


def _ranges_overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 <= b1 and b0 <= a1


def _adjacent_overlap(
    cells_a: tuple[tuple[int, int], ...],
    dir_a: str,
    cells_b: tuple[tuple[int, int], ...],
) -> bool:
    """Adjacent on the perpendicular axis, overlapping on the travel axis."""
    ax0, ax1, ay0, ay1 = _lane_span(cells_a)
    bx0, bx1, by0, by1 = _lane_span(cells_b)
    if dir_a in ("N", "S"):
        return (
            ax0 == ax1
            and bx0 == bx1
            and abs(ax0 - bx0) == 1
            and _ranges_overlap(ay0, ay1, by0, by1)
        )
    if dir_a in ("E", "W"):
        return (
            ay0 == ay1
            and by0 == by1
            and abs(ay0 - by0) == 1
            and _ranges_overlap(ax0, ax1, bx0, bx1)
        )
    return False


def _are_sisters(
    cells_a: tuple[tuple[int, int], ...],
    dir_a: str,
    cells_b: tuple[tuple[int, int], ...],
    dir_b: str,
) -> bool:
    """Same heading, adjacent on the perpendicular, overlapping on the travel axis."""
    if not cells_a or not cells_b or dir_a != dir_b:
        return False
    return _adjacent_overlap(cells_a, dir_a, cells_b)


def _are_oncoming(
    cells_a: tuple[tuple[int, int], ...],
    dir_a: str,
    cells_b: tuple[tuple[int, int], ...],
    dir_b: str,
) -> bool:
    """Opposite heading, same adjacency and travel-range overlap as a sister."""
    if not cells_a or not cells_b or _OPPOSITE_DIR.get(dir_a) != dir_b:
        return False
    return _adjacent_overlap(cells_a, dir_a, cells_b)


SISTER_LITTLE = "little"
SISTER_BIG = "big"
SISTER_ELDER = "elder"
SISTER_STEP = "step"

MERGE_NEITHER = "neither"
MERGE_LEFT = "left"
MERGE_RIGHT = "right"
MERGE_BOTH = "both"

# Stepsister crossings one corridor may chain before we call it a loop.
MAX_CORRIDOR_LANES = 8

_MERGE_FOR_SIDES = {
    (False, False): MERGE_NEITHER,
    (True, False): MERGE_LEFT,
    (False, True): MERGE_RIGHT,
    (True, True): MERGE_BOTH,
}


def _travel_range(cells: tuple[tuple[int, int], ...], direction: str) -> tuple[int, int]:
    """Inclusive travel-axis extent of a lane: y for N/S, x for E/W."""
    x0, x1, y0, y1 = _lane_span(cells)
    return (y0, y1) if direction in ("N", "S") else (x0, x1)


def _travel_coord(cell: tuple[int, int], direction: str) -> int:
    """This cell's coordinate along the travel axis."""
    return cell[1] if direction in ("N", "S") else cell[0]


def _inside_interior(coord: int, cells: tuple[tuple[int, int], ...], direction: str) -> bool:
    """True when coord lies in a lane's non-entrance range (both mouths excluded)."""
    lo, hi = _travel_range(cells, direction)
    return lo < coord < hi


def _is_little_of(
    cells_a: tuple[tuple[int, int], ...],
    dir_a: str,
    cells_b: tuple[tuple[int, int], ...],
    dir_b: str,
) -> bool:
    """
    True when a is the little sister of b: sisters, and both of a's mouths lie
    strictly inside b's non-entrance range (b's own mouths excluded).
    """
    if not _are_sisters(cells_a, dir_a, cells_b, dir_b):
        return False
    a_lo, a_hi = _travel_range(cells_a, dir_a)
    b_lo, b_hi = _travel_range(cells_b, dir_b)
    return b_lo < a_lo and a_hi < b_hi


def _is_elder_of(
    cells_a: tuple[tuple[int, int], ...],
    dir_a: str,
    cells_b: tuple[tuple[int, int], ...],
    dir_b: str,
) -> bool:
    """
    True when a is the elder stepsister of b: sisters that begin and end inside
    each other, so a runs out mid-b and a driver must step across to carry on.
    """
    if not _are_sisters(cells_a, dir_a, cells_b, dir_b):
        return False
    return _inside_interior(
        _travel_coord(cells_a[-1], dir_a), cells_b, dir_b
    ) and _inside_interior(_travel_coord(cells_b[0], dir_b), cells_a, dir_a)


def sister_relation_between(a: int, b: int) -> str | None:
    """
    How b relates to a: little, big, elder, step, or None when not a named pair.
    Geometry only; does not consult the cached links.
    """
    cells_a, dir_a = _state.lanes.get(a, ()), lane_direction(a)
    cells_b, dir_b = _state.lanes.get(b, ()), lane_direction(b)
    if a == b or not cells_a or not cells_b:
        return None
    if _is_little_of(cells_b, dir_b, cells_a, dir_a):
        return SISTER_LITTLE
    if _is_little_of(cells_a, dir_a, cells_b, dir_b):
        return SISTER_BIG
    if _is_elder_of(cells_b, dir_b, cells_a, dir_a):
        return SISTER_ELDER
    if _is_elder_of(cells_a, dir_a, cells_b, dir_b):
        return SISTER_STEP
    return None


def _travel_overlap(a: int, b: int) -> tuple[int, int] | None:
    """Inclusive travel-axis range shared by two lanes, in ascending order."""
    cells_a, dir_a = _state.lanes.get(a, ()), lane_direction(a)
    cells_b, dir_b = _state.lanes.get(b, ()), lane_direction(b)
    if not cells_a or not cells_b or not dir_a:
        return None
    a_lo, a_hi = _travel_range(cells_a, dir_a)
    b_lo, b_hi = _travel_range(cells_b, dir_b)
    lo, hi = max(a_lo, b_lo), min(a_hi, b_hi)
    return (lo, hi) if lo <= hi else None


def _link_order_key(lane_index: int, partner: int) -> float:
    """Sort sisters the way a driver meets them: by shared run, along travel."""
    overlap = _travel_overlap(lane_index, partner)
    if overlap is None:
        return float(partner)
    sign = 1.0 if lane_direction(lane_index) in ("N", "E") else -1.0
    return sign * (overlap[0] + overlap[1]) / 2.0


def _lateral_offsets(direction: str) -> tuple[tuple[int, int], tuple[int, int]]:
    """Driver's left and right cell steps for a travel heading."""
    from sim.junction import LEFT_OF, RIGHT_OF

    left = map_data.offset_for_direction(LEFT_OF.get(direction, ""))
    right = map_data.offset_for_direction(RIGHT_OF.get(direction, ""))
    return (left, right)


def _compute_merge_sides(
    ids: list[int],
    cell_to_lane: dict[tuple[int, int], int],
) -> dict[tuple[int, int], str]:
    """
    Per-cell merge side toward a mergeable sister, driver-relative.

    Tagged from perpendicular neighbour occupancy rather than the 1:1 sister
    pairing, so a lane flanked on both sides reports "both". Cells with no
    little/big or stepsister neighbour are absent and read as "neither".
    """
    sides: dict[tuple[int, int], str] = {}
    pair_cache: dict[tuple[int, int], bool] = {}

    def is_mergeable(a: int, b: int) -> bool:
        key = (a, b) if a < b else (b, a)
        cached = pair_cache.get(key)
        if cached is not None:
            return cached
        result = sister_relation_between(a, b) is not None
        pair_cache[key] = result
        return result

    for i in ids:
        direction = lane_direction(i)
        cells = _state.lanes.get(i, ())
        if not direction or not cells:
            continue
        (lx, ly), (rx, ry) = _lateral_offsets(direction)
        for cx, cy in cells:
            flags = []
            for dx, dy in ((lx, ly), (rx, ry)):
                other = cell_to_lane.get((cx + dx, cy + dy))
                flags.append(
                    other is not None and other != i and is_mergeable(i, other)
                )
            side = _MERGE_FOR_SIDES[(flags[0], flags[1])]
            if side != MERGE_NEITHER:
                sides[(cx, cy)] = side
    return sides


def _bfs_distance(start: str, destination: str, graph: dict[str, set[str]]) -> int | None:
    if start == destination:
        return 0
    q: deque[tuple[str, int]] = deque([(start, 0)])
    seen = {start}
    while q:
        node, dist = q.popleft()
        for nxt in graph.get(node, ()):
            if nxt == destination:
                return dist + 1
            if nxt in seen:
                continue
            seen.add(nxt)
            q.append((nxt, dist + 1))
    return None


def _compute_best_next_hops(start: str, destination: str, graph: dict[str, set[str]]) -> frozenset[str]:
    neighbors = graph.get(start, set())
    if not neighbors:
        return frozenset()
    if destination in neighbors:
        return frozenset({destination})

    best_hops: set[str] = set()
    best_dist: int | None = None
    for hop in neighbors:
        dist = _bfs_distance(hop, destination, graph)
        if dist is None:
            continue
        total = dist + 1
        if best_dist is None or total < best_dist:
            best_dist = total
            best_hops = {hop}
        elif total == best_dist:
            best_hops.add(hop)
    return frozenset(best_hops)


def _refresh_topology() -> None:
    outgoing: dict[str, list[int]] = {}
    incoming: dict[str, list[int]] = {}
    graph: dict[str, set[str]] = {}
    in_lanes: set[int] = set()
    out_lanes: set[int] = set()

    for i in sorted(_state.lanes.keys()):
        meta = _state.lane_meta.get(i)
        if not meta:
            continue
        _dir, src, dst = meta
        if src:
            outgoing.setdefault(src, []).append(i)
        if dst:
            incoming.setdefault(dst, []).append(i)
        if src and dst:
            graph.setdefault(src, set()).add(dst)
        if dst and dst in _state.intersections:
            in_lanes.add(i)
        if src and src in _state.intersections:
            out_lanes.add(i)

    _state.outgoing = {k: tuple(v) for k, v in outgoing.items()}
    _state.incoming = {k: tuple(v) for k, v in incoming.items()}
    _state.lane_graph = graph
    _state.in_lane_ids = frozenset(in_lanes)
    _state.out_lane_ids = frozenset(out_lanes)

    attached: dict[str, set[str]] = {}
    for node in _state.intersections:
        attached[node] = set()
        for i in incoming.get(node, ()):
            lane = _state.lanes.get(i, ())
            if not lane or len(lane) >= INBOUND_TAIL_CELLS:
                continue
            src = lane_traffic_in(i)
            if src and src != node and src in _state.intersections:
                attached[node].add(src)
    _state.attached = {k: frozenset(v) for k, v in attached.items()}

    cell_map: dict[tuple[int, int], list[str]] = {}
    for key, inter in _state.intersections.items():
        for c in inter.cells:
            cell_map.setdefault(c, []).append(key)
    _state.cell_to_intersections = {c: tuple(keys) for c, keys in cell_map.items()}

    ids = sorted(_state.lanes.keys())
    oncoming: dict[int, int | None] = {i: None for i in ids}
    links: dict[int, list[tuple[int, str]]] = {i: [] for i in ids}
    for a_idx, a in enumerate(ids):
        dir_a = lane_direction(a)
        cells_a = _state.lanes.get(a, ())
        if not dir_a or not cells_a:
            continue
        for b in ids[a_idx + 1 :]:
            dir_b = lane_direction(b)
            cells_b = _state.lanes.get(b, ())
            if not dir_b or not cells_b:
                continue
            if _are_sisters(cells_a, dir_a, cells_b, dir_b):
                links[a].append((b, sister_relation_between(a, b) or ""))
                links[b].append((a, sister_relation_between(b, a) or ""))
            if (
                oncoming[a] is None
                and oncoming[b] is None
                and _are_oncoming(cells_a, dir_a, cells_b, dir_b)
            ):
                oncoming[a] = b
                oncoming[b] = a
    _state.oncoming = oncoming
    _state.sister_links = {
        i: tuple(sorted(pairs, key=lambda link: _link_order_key(i, link[0])))
        for i, pairs in links.items()
    }

    cell_to_lane: dict[tuple[int, int], int] = {}
    cell_to_lane_pos: dict[tuple[int, int], tuple[int, int]] = {}
    for i in ids:
        for pos, c in enumerate(_state.lanes.get(i, ())):
            cell_to_lane[c] = i
            cell_to_lane_pos[c] = (i, pos)
    _state.cell_to_lane = cell_to_lane
    _state.cell_to_lane_pos = cell_to_lane_pos
    _state.merge_sides = _compute_merge_sides(ids, cell_to_lane)

    for i in ids:
        src = lane_traffic_in(i)
        dst = lane_exit_node(i)
        if src and dst and dst != lane_traffic_out(i):
            graph.setdefault(src, set()).add(dst)

    nodes: set[str] = set(_state.place_rects)
    nodes.update(_state.intersections)
    for src, dsts in graph.items():
        nodes.add(src)
        nodes.update(dsts)
    hops: dict[tuple[str, str], frozenset[str]] = {}
    for start in nodes:
        for dest in nodes:
            if start == dest:
                continue
            hops[(start, dest)] = _compute_best_next_hops(start, dest, graph)
    _state.best_next_hops = hops


def get_intersection_at_cell(cell: tuple[int, int]) -> str | None:
    """Return intersection id if cell belongs to one, else None."""
    keys = _state.cell_to_intersections.get(cell)
    return keys[0] if keys else None


def intersections_at_cell(cell: tuple[int, int]) -> tuple[str, ...]:
    """All intersection ids occupying this cell (overlaps allowed, rebuild order)."""
    return _state.cell_to_intersections.get(cell, ())


def cell_in_intersection(cell: tuple[int, int], key: str) -> bool:
    """True if cell is in this intersection's occupancy (overlaps allowed)."""
    inter = _state.intersections.get(key)
    return bool(inter) and cell in inter.cells_set


def get_intersection_keys() -> list[str]:
    """Return all intersection ids in sorted order."""
    return sorted(_state.intersections.keys())


def get_intersection_cells_by_key(key: str) -> list[tuple[int, int]]:
    inter = _state.intersections.get(key)
    return list(inter.cells) if inter else []


def get_intersection_cells_map() -> dict[str, list[tuple[int, int]]]:
    return {k: get_intersection_cells_by_key(k) for k in get_intersection_keys()}


def get_intersection_slots(key: str) -> list[tuple[int, int]]:
    inter = _state.intersections.get(key)
    return list(inter.slots) if inter else []


def get_bounds() -> tuple[int, int, int, int]:
    """Content bounds (x_lo, y_lo, x_hi, y_hi), hi exclusive. Authored cell space."""
    return (_state.x_lo, _state.y_lo, _state.x_hi, _state.y_hi)


def get_grid_w() -> int:
    """Span of content bounds in x (not an origin-at-zero grid width)."""
    return max(1, _state.x_hi - _state.x_lo)


def get_grid_h() -> int:
    """Span of content bounds in y (not an origin-at-zero grid height)."""
    return max(1, _state.y_hi - _state.y_lo)


def lane_ids() -> list[int]:
    """Stable lane ids present in the current world, sorted."""
    return sorted(_state.lanes.keys())


def lane_count() -> int:
    return len(_state.lanes)


def lane_traffic_in(lane_index: int) -> str:
    meta = _state.lane_meta.get(lane_index)
    return meta[1] if meta else ""


def lane_traffic_out(lane_index: int) -> str:
    meta = _state.lane_meta.get(lane_index)
    return meta[2] if meta else ""


def lane_direction(lane_index: int) -> str:
    meta = _state.lane_meta.get(lane_index)
    return meta[0] if meta else ""


def get_lane_cells(lane_index: int) -> tuple[tuple[int, int], ...]:
    return _state.lanes.get(lane_index, ())


def lane_start_end_cells(
    lane_index: int,
) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """First (traffic-in) and last (traffic-out) cells of a lane."""
    cells = get_lane_cells(lane_index)
    if not cells:
        return (None, None)
    return (cells[0], cells[-1])


def node_entrance_exit_cells(
    node: str,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Incoming-lane last cells (entrances) and outgoing-lane first cells (exits)."""
    entrances: list[tuple[int, int]] = []
    exits: list[tuple[int, int]] = []
    for i in incoming_lanes(node):
        cells = get_lane_cells(i)
        if cells:
            entrances.append(cells[-1])
    for i in outgoing_lanes(node):
        cells = get_lane_cells(i)
        if cells:
            exits.append(cells[0])
    return (entrances, exits)


def get_place_rects() -> dict[str, dict]:
    return dict(_state.place_rects)


def is_intersection(key: str) -> bool:
    return key in _state.intersections


def outgoing_lanes(node: str) -> tuple[int, ...]:
    return _state.outgoing.get(node, ())


def incoming_lanes(node: str) -> tuple[int, ...]:
    return _state.incoming.get(node, ())


def in_lane_ids() -> frozenset[int]:
    return _state.in_lane_ids


def out_lane_ids() -> frozenset[int]:
    return _state.out_lane_ids


def attached_intersections(node: str) -> frozenset[str]:
    return _state.attached.get(node, frozenset())


def oncoming_lane(lane_index: int) -> int | None:
    return _state.oncoming.get(lane_index)


def sister_links(lane_index: int) -> tuple[tuple[int, str], ...]:
    """Every sister of this lane as (partner, partner's role), in travel order."""
    return _state.sister_links.get(lane_index, ())


def sister_lanes(lane_index: int) -> tuple[int, ...]:
    return tuple(partner for partner, _kind in sister_links(lane_index))


def sister_lane(lane_index: int) -> int | None:
    """First sister a driver meets on this lane, or None."""
    links = sister_links(lane_index)
    return links[0][0] if links else None


def sister_relation(lane_index: int, partner: int) -> str | None:
    """Cached role of partner as seen from lane_index; None when not sisters."""
    for other, kind in sister_links(lane_index):
        if other == partner:
            return kind or None
    return None


def sister_overlap_cells(
    lane_index: int,
    partner: int,
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """This lane's first and last cells along the run it shares with a sister."""
    overlap = _travel_overlap(lane_index, partner)
    if overlap is None:
        return None
    direction = lane_direction(lane_index)
    shared = [
        c
        for c in get_lane_cells(lane_index)
        if overlap[0] <= _travel_coord(c, direction) <= overlap[1]
    ]
    if not shared:
        return None
    return (shared[0], shared[-1])


def stepsister_step(lane_index: int) -> tuple[int, str] | None:
    """
    The sister a car must step into to carry on past this lane, with the side.

    Only for a lane that leads nowhere on its own and ends inside a sister.
    """
    if lane_traffic_out(lane_index):
        return None
    cells = get_lane_cells(lane_index)
    if not cells:
        return None
    side = cell_merge(*cells[-1])
    candidates: list[tuple[int, str]] = []
    for partner, kind in sister_links(lane_index):
        if kind != SISTER_STEP:
            continue
        for one_side in (MERGE_LEFT, MERGE_RIGHT):
            if side not in (one_side, MERGE_BOTH):
                continue
            found = merge_target(lane_index, len(cells) - 1, one_side, 1)
            if found is not None and found[0] == partner:
                candidates.append((partner, one_side))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (0 if lane_traffic_out(c[0]) else 1, c[0]))
    return candidates[0]


def corridor_after(lane_index: int) -> tuple[int, ...]:
    """
    This lane and every stepsister a car must cross into to reach a traffic node.

    Ends at the first lane with a real traffic_out, or where the chain runs out.
    """
    chain = [lane_index]
    seen = {lane_index}
    for _ in range(MAX_CORRIDOR_LANES):
        step = stepsister_step(chain[-1])
        if step is None or step[0] in seen:
            break
        chain.append(step[0])
        seen.add(step[0])
    return tuple(chain)


def corridor_before(lane_index: int) -> tuple[int, ...]:
    """Every lane that steps into this one, earliest first, then this lane."""
    chain = [lane_index]
    seen = {lane_index}
    for _ in range(MAX_CORRIDOR_LANES):
        prev = next(
            (
                partner
                for partner, kind in sister_links(chain[0])
                if kind == SISTER_ELDER
                and partner not in seen
                and (stepsister_step(partner) or (None,))[0] == chain[0]
            ),
            None,
        )
        if prev is None:
            break
        chain.insert(0, prev)
        seen.add(prev)
    return tuple(chain)


def lane_exit_node(lane_index: int) -> str:
    """Traffic node this lane leads to, following stepsister crossings."""
    direct = lane_traffic_out(lane_index)
    if direct:
        return direct
    return lane_traffic_out(corridor_after(lane_index)[-1])


def lane_entry_node(lane_index: int) -> str:
    """Traffic node a car on this lane came from, following stepsister crossings."""
    direct = lane_traffic_in(lane_index)
    if direct:
        return direct
    return lane_traffic_in(corridor_before(lane_index)[0])


def cell_merge(gx: int, gy: int) -> str:
    """Merge side acceptable from this cell: left, right, both, or neither."""
    return _state.merge_sides.get((int(gx), int(gy)), MERGE_NEITHER)


def cell_is_passing(gx: int, gy: int) -> bool:
    return cell_merge(gx, gy) != MERGE_NEITHER


def lane_merge_cells(lane_index: int) -> dict[tuple[int, int], str]:
    """Merge sides for this lane's cells, omitting "neither"."""
    out: dict[tuple[int, int], str] = {}
    for c in get_lane_cells(lane_index):
        side = _state.merge_sides.get(c)
        if side is not None:
            out[c] = side
    return out


def lane_at_cell(gx: int, gy: int) -> int | None:
    return _state.cell_to_lane.get((int(gx), int(gy)))


def lane_pos_at_cell(gx: int, gy: int) -> tuple[int, int] | None:
    """Lane id and cell index owning this cell, or None."""
    return _state.cell_to_lane_pos.get((int(gx), int(gy)))


def merge_target(
    lane_index: int,
    pos: int,
    side: str,
    forward_cells: int,
) -> tuple[int, int] | None:
    """
    Landing lane and cell index for a lane change: forward_cells ahead, one step
    to the driver's side. None when that cell belongs to no lane (off the end) or
    to the lane already being driven.
    """
    cells = get_lane_cells(lane_index)
    if not cells or pos < 0 or pos >= len(cells) or forward_cells < 1:
        return None
    direction = lane_direction(lane_index)
    left, right = _lateral_offsets(direction)
    if side == MERGE_LEFT:
        lat = left
    elif side == MERGE_RIGHT:
        lat = right
    else:
        return None
    if lat == (0, 0):
        return None
    # Walk the heading from the current cell so a short source lane does not clip
    # the runway, then step laterally onto the neighbour lane.
    fx, fy = map_data.offset_for_direction(direction)
    sx, sy = cells[pos]
    cx = sx + fx * forward_cells + lat[0]
    cy = sy + fy * forward_cells + lat[1]
    found = _state.cell_to_lane_pos.get((cx, cy))
    if found is None or found[0] == lane_index:
        return None
    if lane_direction(found[0]) != direction:
        return None
    return found


def cell_occupancy() -> dict[tuple[int, int], int]:
    return dict(_state.cell_to_lane)


def best_next_hops(start: str, destination: str) -> frozenset[str]:
    if start == destination:
        return frozenset()
    return _state.best_next_hops.get((start, destination), frozenset())


def destination_reachable(start_node: str, destination: str) -> bool:
    if start_node == destination:
        return True
    return bool(_state.best_next_hops.get((start_node, destination)))


def intersection_cell_for_transition(in_lane_index: int, out_lane_index: int) -> tuple[int, int]:
    """
    Pick a cell inside the intersection for this approach.
    Uses the intersection that owns the inbound lane's last cell; chooses the
    nearest slot to that approach endpoint (or the endpoint itself).
    """
    in_lane = get_lane_cells(in_lane_index)
    if not in_lane:
        return (0, 0)
    approach = in_lane[-1]
    key = get_intersection_at_cell(approach)
    if key is None:
        out_node = lane_traffic_out(in_lane_index)
        if is_intersection(out_node):
            key = out_node
    if key is None:
        return approach
    slots = get_intersection_slots(key)
    if not slots:
        cells = get_intersection_cells_by_key(key)
        return cells[0] if cells else approach
    ax, ay = approach
    return min(slots, key=lambda s: (s[0] - ax) ** 2 + (s[1] - ay) ** 2)
