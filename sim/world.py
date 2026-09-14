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
        self.oncoming: dict[int, int | None] = {}
        self.sisters: dict[int, int | None] = {}
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


def _axis(direction: str) -> str:
    d = (direction or "").upper()
    if d in ("N", "S"):
        return "NS"
    if d in ("E", "W"):
        return "EW"
    return d


def _min_chebyshev(
    cells_a: tuple[tuple[int, int], ...],
    cells_b: tuple[tuple[int, int], ...],
) -> int:
    best = 10**9
    for ax, ay in cells_a:
        for bx, by in cells_b:
            d = max(abs(ax - bx), abs(ay - by))
            if d < best:
                best = d
                if best == 0:
                    return 0
    return best if best != 10**9 else 10**9


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
    sisters: dict[int, int | None] = {i: None for i in ids}
    for a_idx, a in enumerate(ids):
        tin_a = lane_traffic_in(a)
        tout_a = lane_traffic_out(a)
        dir_a = lane_direction(a)
        cells_a = _state.lanes.get(a, ())
        if not tin_a or not tout_a or not cells_a:
            continue
        axis_a = _axis(dir_a)
        for b in ids[a_idx + 1 :]:
            tin_b = lane_traffic_in(b)
            tout_b = lane_traffic_out(b)
            cells_b = _state.lanes.get(b, ())
            if not tin_b or not tout_b or not cells_b:
                continue
            if _min_chebyshev(cells_a, cells_b) != 1:
                continue
            axis_b = _axis(lane_direction(b))
            if tin_a == tout_b and tout_a == tin_b and axis_a == axis_b:
                if oncoming[a] is None and oncoming[b] is None:
                    oncoming[a] = b
                    oncoming[b] = a
            if tin_a == tin_b and tout_a == tout_b and dir_a == lane_direction(b):
                if sisters[a] is None and sisters[b] is None:
                    sisters[a] = b
                    sisters[b] = a
    _state.oncoming = oncoming
    _state.sisters = sisters

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


def sister_lane(lane_index: int) -> int | None:
    return _state.sisters.get(lane_index)


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
