"""
World grid and lane geometry.
Lane and intersection definitions are loaded from serializable map data.
"""
from __future__ import annotations

from sim.map_data import load_map_data

MAP_DATA = load_map_data()
GRID_W = int(MAP_DATA["grid"]["width"])
GRID_H = int(MAP_DATA["grid"]["height"])
ALL_LANES: list[list[tuple[int, int]]] = [
    [tuple(cell) for cell in lane] for lane in MAP_DATA["lanes"]
]
INTERSECTION_CELLS = [tuple(cell) for cell in MAP_DATA["intersection"]["cells"]]
_INTER_SLOT_CELLS = [tuple(cell) for cell in MAP_DATA["intersection"]["slots"]]
_HP_INTERSECTION = MAP_DATA.get("hp_intersection", {})
_HP_CELLS = [tuple(cell) for cell in _HP_INTERSECTION.get("cells", [])]
_HP_SLOT_CELLS = [tuple(cell) for cell in _HP_INTERSECTION.get("slots", [])]


def get_intersection_cells() -> list[tuple[int, int]]:
    """Return list of (gx, gy) that are part of any intersection."""
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for cell in INTERSECTION_CELLS + _HP_CELLS:
        if cell not in seen:
            seen.add(cell)
            out.append(cell)
    return out


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


def intersection_cell_for_transition(in_lane_index: int, out_lane_index: int) -> tuple[int, int]:
    """Return intersection cell for this (in, out) lane pair."""
    if in_lane_index == 8 and _HP_SLOT_CELLS:
        return _HP_SLOT_CELLS[0]
    if in_lane_index == 10 and len(_HP_SLOT_CELLS) > 1:
        return _HP_SLOT_CELLS[1]
    idx = in_lane_index // 2
    if idx < 0 or idx >= len(_INTER_SLOT_CELLS):
        idx = 0
    return _INTER_SLOT_CELLS[idx]


if __name__ == "__main__":
    print("Lane count:", len(ALL_LANES))
    for i, lane in enumerate(ALL_LANES):
        print(f"  Lane {i}: len={len(lane)}, first={lane[0]}, last={lane[-1]}")
    print("Intersection:", INTERSECTION_CELLS)
