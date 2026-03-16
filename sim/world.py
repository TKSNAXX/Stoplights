"""
World grid and lane geometry.
Lane and intersection definitions are mutable; rebuilt when intersection size changes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sim import map_data
from sim.map_data import (
    DEFAULT_MAIN_CENTER,
    get_bypass_intersection_center,
    intersection_dict_from_bounds,
    load_map_data,
    bounds_from_center,
)
MAP_DATA = load_map_data()

if TYPE_CHECKING:
    from sim.places import LaneConfig

# Minimum tiles of empty space between any object and the map edge
MAP_PADDING = 4


def _apply_map_padding(
    lanes: list[list[tuple[int, int]]],
    place_rects: dict[str, dict],
    main_intersection: dict,
    hp_intersection: dict,
) -> tuple[list[list[tuple[int, int]]], dict[str, dict], dict, dict, int, int]:
    """
    Shift all geometry so there are MAP_PADDING empty cells from any object to the edge.
    Returns (transformed lanes, place_rects, main_intersection, hp_intersection, grid_w, grid_h).
    """
    all_x: list[int] = []
    all_y: list[int] = []

    for lane in lanes:
        for cx, cy in lane:
            all_x.append(cx)
            all_y.append(cy)
    for r in place_rects.values():
        rx, ry = int(r.get("x", 0)), int(r.get("y", 0))
        rw, rh = int(r.get("w", 0)), int(r.get("h", 0))
        all_x.extend([rx, rx + rw - 1] if rw else [rx])
        all_y.extend([ry, ry + rh - 1] if rh else [ry])
    for c in main_intersection.get("cells", []):
        all_x.append(c[0])
        all_y.append(c[1])
    for c in hp_intersection.get("cells", []):
        all_x.append(c[0])
        all_y.append(c[1])

    if not all_x or not all_y:
        return lanes, place_rects, main_intersection, hp_intersection, 32, 36

    x_min, x_max = min(all_x), max(all_x)
    y_min, y_max = min(all_y), max(all_y)
    offset_x = MAP_PADDING - x_min
    offset_y = MAP_PADDING - y_min

    def shift(c: tuple[int, int]) -> tuple[int, int]:
        return (c[0] + offset_x, c[1] + offset_y)

    new_lanes = [[shift(c) for c in lane] for lane in lanes]
    new_place_rects = {
        k: {"x": int(r.get("x", 0)) + offset_x, "y": int(r.get("y", 0)) + offset_y, "w": int(r.get("w", 0)), "h": int(r.get("h", 0))}
        for k, r in place_rects.items()
    }
    new_main = {
        "x_lo": main_intersection.get("x_lo", 0) + offset_x,
        "x_hi": main_intersection.get("x_hi", 0) + offset_x,
        "y_lo": main_intersection.get("y_lo", 0) + offset_y,
        "y_hi": main_intersection.get("y_hi", 0) + offset_y,
        "cells": [shift(c) for c in main_intersection.get("cells", [])],
        "slots": [shift(c) for c in main_intersection.get("slots", [])],
    }
    new_hp = {
        "cells": [shift(c) for c in hp_intersection.get("cells", [])],
        "slots": [shift(c) for c in hp_intersection.get("slots", [])],
    }

    grid_w = x_max - x_min + 1 + 2 * MAP_PADDING
    grid_h = y_max - y_min + 1 + 2 * MAP_PADDING

    return new_lanes, new_place_rects, new_main, new_hp, grid_w, grid_h


class _WorldState:
    """Mutable world geometry. Updated by rebuild_world."""

    def __init__(self) -> None:
        self.all_lanes: list[list[tuple[int, int]]] = []
        self.lane_meta: list[tuple[str, str, str]] = []  # (direction, traffic_in, traffic_out)
        self.grid_w: int = 32
        self.grid_h: int = 36
        self._place_rects: dict[str, dict] = {}
        self._main_cells: list[tuple[int, int]] = []
        self._main_slots: list[tuple[int, int]] = []
        self._hp_cells: list[tuple[int, int]] = []
        self._hp_slots: list[tuple[int, int]] = []
        self._main_cells_set: frozenset[tuple[int, int]] = frozenset()
        self._hp_cells_set: frozenset[tuple[int, int]] = frozenset()


_state = _WorldState()


def rebuild_world(
    place_rects: dict[str, dict],
    main_center: tuple[float, float],
    main_size: int,
    bypass_center: tuple[float, float],
    bypass_size: int,
    lane_configs: dict[int, "LaneConfig"] | None = None,
    extra_intersection_bounds: dict[str, tuple[int, int, int, int]] | None = None,
) -> None:
    """
    Rebuild lanes and intersection geometry from centers and sizes.
    Places and intersections own their positions; lanes are derived.
    When lane_configs is provided, lane cells are built from config start/end tiles.
    """
    main_size = max(2, min(12, main_size))
    bypass_size = max(2, min(12, bypass_size))
    if main_size % 2 != 0:
        main_size = (main_size // 2) * 2
    if bypass_size % 2 != 0:
        bypass_size = (bypass_size // 2) * 2

    main_cx, main_cy = main_center
    bypass_cx, bypass_cy = bypass_center

    x_lo, x_hi, y_lo, y_hi = bounds_from_center(main_cx, main_cy, main_size)
    main_intersection = intersection_dict_from_bounds(x_lo, x_hi, y_lo, y_hi)

    lanes, hp_intersection, lane_meta = map_data.build_lanes_from_config(
        place_rects, main_intersection, bypass_center, bypass_size,
        lane_configs or {},
        extra_intersection_bounds=extra_intersection_bounds,
    )

    grid_w, grid_h = 32, 36
    for lane in lanes:
        for cx, cy in lane:
            grid_w = max(grid_w, cx + 1)
            grid_h = max(grid_h, cy + 1)
    for cell in hp_intersection["cells"]:
        grid_w = max(grid_w, cell[0] + 1)
        grid_h = max(grid_h, cell[1] + 1)

    lanes, place_rects, main_intersection, hp_intersection, grid_w, grid_h = _apply_map_padding(
        lanes, place_rects, main_intersection, hp_intersection
    )

    _state.all_lanes.clear()
    _state.all_lanes.extend([[tuple(c) for c in lane] for lane in lanes])
    _state.lane_meta = lane_meta
    _state._place_rects = dict(place_rects)
    _state.grid_w = grid_w
    _state.grid_h = grid_h
    _state._main_cells = [tuple(c) for c in main_intersection["cells"]]
    _state._main_slots = [tuple(c) for c in main_intersection["slots"]]
    _state._hp_cells = [tuple(c) for c in hp_intersection["cells"]]
    _state._hp_slots = [tuple(c) for c in hp_intersection["slots"]]
    _state._main_cells_set = frozenset(_state._main_cells)
    _state._hp_cells_set = frozenset(_state._hp_cells)
    _refresh_refs()


# Public API - assigned by _refresh_refs after first rebuild
ALL_LANES: list[list[tuple[int, int]]] = []
GRID_W: int = 32
GRID_H: int = 36
INTERSECTION_CELLS: list[tuple[int, int]] = []
_INTER_SLOT_CELLS: list[tuple[int, int]] = []
_HP_CELLS: list[tuple[int, int]] = []
_HP_SLOT_CELLS: list[tuple[int, int]] = []
_MAIN_CELLS_SET: frozenset[tuple[int, int]] = frozenset()
_BYPASS_CELLS_SET: frozenset[tuple[int, int]] = frozenset()


def _init_from_map_data() -> None:
    """Initialize from loaded map (used at import)."""
    place_rects = MAP_DATA.get("place_rects", {})
    inter = MAP_DATA.get("intersection", {})
    hp_inter = MAP_DATA.get("hp_intersection", {})

    main_cx, main_cy = float(DEFAULT_MAIN_CENTER[0]), float(DEFAULT_MAIN_CENTER[1])
    bypass_cx, bypass_cy = get_bypass_intersection_center(place_rects)

    x_lo = inter.get("x_lo")
    if x_lo is not None:
        main_size = inter.get("x_hi", x_lo + 4) - x_lo
    else:
        cells = inter.get("cells", [])
        main_size = 4
        if cells:
            xs = [c[0] for c in cells]
            main_size = max(xs) - min(xs) + 1

    hp_cells = hp_inter.get("cells", [])
    bypass_size = 4
    if hp_cells:
        xs = [c[0] for c in hp_cells]
        bypass_size = max(xs) - min(xs) + 1

    rebuild_world(place_rects, (main_cx, main_cy), main_size, (bypass_cx, bypass_cy), bypass_size)


def _refresh_refs() -> None:
    """Update module-level refs after rebuild (for existing importers)."""
    global ALL_LANES, GRID_W, GRID_H, INTERSECTION_CELLS
    global _INTER_SLOT_CELLS, _HP_CELLS, _HP_SLOT_CELLS, _MAIN_CELLS_SET, _BYPASS_CELLS_SET
    ALL_LANES = _state.all_lanes
    GRID_W = _state.grid_w
    GRID_H = _state.grid_h
    INTERSECTION_CELLS = _state._main_cells
    _INTER_SLOT_CELLS = _state._main_slots
    _HP_CELLS = _state._hp_cells
    _HP_SLOT_CELLS = _state._hp_slots
    _MAIN_CELLS_SET = _state._main_cells_set
    _BYPASS_CELLS_SET = _state._hp_cells_set


def get_intersection_at_cell(cell: tuple[int, int]) -> str | None:
    """Return 'main' if cell in main intersection, 'bypass' if in HP junction, else None."""
    if cell in _state._main_cells_set:
        return "main"
    if cell in _state._hp_cells_set:
        return "bypass"
    return None


def get_intersection_cells() -> list[tuple[int, int]]:
    """Return list of (gx, gy) that are part of any intersection."""
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for c in _state._main_cells + _state._hp_cells:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def get_main_intersection_cells() -> list[tuple[int, int]]:
    """Return cells belonging to the main intersection only."""
    return list(_state._main_cells)


def get_bypass_intersection_cells() -> list[tuple[int, int]]:
    """Return cells belonging to the bypass (HP) intersection only."""
    return list(_state._hp_cells)


def intersection_bounds() -> tuple[int, int, int, int]:
    """Return (x_lo, x_hi, y_lo, y_hi) from intersection cells. x_hi/y_hi are exclusive."""
    cells = get_intersection_cells()
    if not cells:
        return (0, 0, 0, 0)
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    return (min(xs), max(xs) + 1, min(ys), max(ys) + 1)


def intersection_center() -> tuple[float, float]:
    """Center of the intersection in grid coordinates."""
    cells = get_intersection_cells()
    if not cells:
        return (0.0, 0.0)
    n = len(cells)
    return (sum(cell[0] for cell in cells) / n, sum(cell[1] for cell in cells) / n)


def get_grid_w() -> int:
    return _state.grid_w


def lane_traffic_in(lane_index: int) -> str:
    """Return traffic_in (origin) for lane. Empty if out of range."""
    if 0 <= lane_index < len(_state.lane_meta):
        return _state.lane_meta[lane_index][1]
    return ""


def lane_traffic_out(lane_index: int) -> str:
    """Return traffic_out (destination) for lane. Empty if out of range."""
    if 0 <= lane_index < len(_state.lane_meta):
        return _state.lane_meta[lane_index][2]
    return ""


def lane_direction(lane_index: int) -> str:
    """Return N, S, E, or W for lane. Empty if out of range."""
    if 0 <= lane_index < len(_state.lane_meta):
        return _state.lane_meta[lane_index][0]
    return ""


def get_place_rects() -> dict[str, dict]:
    """Return current place rects (x,y,w,h) from last rebuild."""
    return dict(_state._place_rects)


def get_grid_h() -> int:
    return _state.grid_h


def intersection_cell_for_transition(in_lane_index: int, out_lane_index: int) -> tuple[int, int]:
    """Return intersection cell for this (in, out) lane pair."""
    if in_lane_index == 8 and _state._hp_slots:
        return _state._hp_slots[0]
    if in_lane_index == 10 and len(_state._hp_slots) > 1:
        return _state._hp_slots[1]
    slots = _state._main_slots
    idx = in_lane_index // 2
    if idx < 0 or idx >= len(slots):
        return slots[0] if slots else (0, 0)
    return slots[idx]


# Initialize at module load
_init_from_map_data()


if __name__ == "__main__":
    print("Lane count:", len(_state.all_lanes))
    for i, lane in enumerate(_state.all_lanes):
        print(f"  Lane {i}: len={len(lane)}, first={lane[0]}, last={lane[-1]}")
    print("Intersection:", _state._main_cells)
