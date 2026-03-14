"""
World grid and lane geometry.
Lane and intersection definitions are mutable; rebuilt when intersection size changes.
"""
from __future__ import annotations

from sim.map_data import (
    build_housing_park_route,
    build_lanes_from_positions,
    get_bypass_intersection_center,
    get_main_intersection_center,
    intersection_dict_from_bounds,
    load_map_data,
    bounds_from_center,
)
MAP_DATA = load_map_data()


class _WorldState:
    """Mutable world geometry. Updated by rebuild_world."""

    def __init__(self) -> None:
        self.all_lanes: list[list[tuple[int, int]]] = []
        self.grid_w: int = 32
        self.grid_h: int = 36
        self._main_cells: list[tuple[int, int]] = []
        self._main_slots: list[tuple[int, int]] = []
        self._hp_cells: list[tuple[int, int]] = []
        self._hp_slots: list[tuple[int, int]] = []
        self._main_cells_set: frozenset[tuple[int, int]] = frozenset()
        self._hp_cells_set: frozenset[tuple[int, int]] = frozenset()


_state = _WorldState()


def rebuild_world(
    place_rects: dict[str, dict],
    main_size: int,
    bypass_size: int,
) -> None:
    """
    Rebuild lanes and intersection geometry from centers and sizes.
    Centers stay fixed; bounds recompute from size.
    """
    main_size = max(2, min(12, main_size))
    bypass_size = max(2, min(12, bypass_size))
    if main_size % 2 != 0:
        main_size = (main_size // 2) * 2
    if bypass_size % 2 != 0:
        bypass_size = (bypass_size // 2) * 2

    main_cx, main_cy = get_main_intersection_center()
    bypass_cx, bypass_cy = get_bypass_intersection_center(place_rects)

    x_lo, x_hi, y_lo, y_hi = bounds_from_center(main_cx, main_cy, main_size)
    main_intersection = intersection_dict_from_bounds(x_lo, x_hi, y_lo, y_hi)

    lanes, grid_w, grid_h = build_lanes_from_positions(main_intersection, place_rects)
    hp_lanes, hp_intersection = build_housing_park_route(place_rects, size=bypass_size)
    lanes = lanes + hp_lanes

    for lane in hp_lanes:
        for cx, cy in lane:
            grid_w = max(grid_w, cx + 1)
            grid_h = max(grid_h, cy + 1)
    for cell in hp_intersection["cells"]:
        grid_w = max(grid_w, cell[0] + 1)
        grid_h = max(grid_h, cell[1] + 1)

    _state.all_lanes.clear()
    _state.all_lanes.extend([[tuple(c) for c in lane] for lane in lanes])
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

    rebuild_world(place_rects, main_size, bypass_size)


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


def get_grid_h() -> int:
    return _state.grid_h


def intersection_cell_for_transition(in_lane_index: int, out_lane_index: int) -> tuple[int, int]:
    """Return intersection cell for this (in, out) lane pair."""
    if in_lane_index == 8 and _state._hp_slots:
        return _state._hp_slots[0]
    if in_lane_index == 10 and len(_state._hp_slots) > 1:
        return _state._hp_slots[1]
    idx = in_lane_index // 2
    slots = _state._main_slots
    if idx < 0 or idx >= len(slots):
        idx = 0
    return slots[idx]


# Initialize at module load
_init_from_map_data()


if __name__ == "__main__":
    print("Lane count:", len(_state.all_lanes))
    for i, lane in enumerate(_state.all_lanes):
        print(f"  Lane {i}: len={len(lane)}, first={lane[0]}, last={lane[-1]}")
    print("Intersection:", _state._main_cells)
