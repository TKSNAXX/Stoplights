"""
World grid and lane geometry.

Uniform intersections and stable lane ids. No main/bypass/extra special cases.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sim import map_data

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
        self.lanes: dict[int, list[tuple[int, int]]] = {}
        self.lane_meta: dict[int, tuple[str, str, str]] = {}
        self.x_lo: int = 0
        self.y_lo: int = 0
        self.x_hi: int = 1
        self.y_hi: int = 1
        self.place_rects: dict[str, dict] = {}
        self.intersections: dict[str, _IntersectionState] = {}


_state = _WorldState()


def _compute_bounds(
    lanes: dict[int, list[tuple[int, int]]],
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
    All intersections share one code path.
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

    _state.lanes = {idx: [tuple(c) for c in cells] for idx, cells in lane_cells.items()}
    _state.lane_meta = dict(lane_meta)
    _state.place_rects = dict(place_rects)
    _state.x_lo, _state.y_lo, _state.x_hi, _state.y_hi = x_lo, y_lo, x_hi, y_hi
    _state.intersections = {}
    for key, d in intersection_dicts.items():
        bounds = (int(d["x_lo"]), int(d["x_hi"]), int(d["y_lo"]), int(d["y_hi"]))
        cells = [tuple(c) for c in d.get("cells", [])]
        slots = [tuple(c) for c in d.get("slots", [])]
        _state.intersections[key] = _IntersectionState(key, cells, slots, bounds)


def get_intersection_at_cell(cell: tuple[int, int]) -> str | None:
    """Return intersection id if cell belongs to one, else None."""
    for key, inter in _state.intersections.items():
        if cell in inter.cells_set:
            return key
    return None


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
    lane = _state.lanes.get(lane_index)
    return tuple(lane) if lane else ()


def get_place_rects() -> dict[str, dict]:
    return dict(_state.place_rects)


def is_intersection(key: str) -> bool:
    return key in _state.intersections


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
        # Approach may stop just outside; check traffic_out.
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
