"""
World grid, intersection, and lane geometry.
Pure data: no cars, no Arcade.
"""
from __future__ import annotations

# Grid: 34×34. Intersection 2×2 at center; roads ~10 cells each, 2 lanes per direction.
GRID_W = 34
GRID_H = 34
ROAD_LENGTH = 10
INTERSECTION_SIZE = 2

# Intersection cell indices (center of grid)
_CX = (GRID_W - 1) // 2  # 16
_CY = (GRID_H - 1) // 2  # 16
INTERSECTION_CELLS = [
    (_CX, _CY), (_CX + 1, _CY), (_CX, _CY + 1), (_CX + 1, _CY + 1),
]


def _north_road_cells() -> list[tuple[int, int]]:
    """Cells of the north road (2 columns, 10 rows). Toward intersection = decreasing y."""
    return [(x, y) for x in (_CX, _CX + 1) for y in range(_CY + 2, _CY + 2 + ROAD_LENGTH)]


def _south_road_cells() -> list[tuple[int, int]]:
    """Cells of the south road."""
    return [(x, y) for x in (_CX, _CX + 1) for y in range(_CY - ROAD_LENGTH, _CY)]


def _east_road_cells() -> list[tuple[int, int]]:
    """Cells of the east road. Toward intersection = decreasing x."""
    return [(x, y) for y in (_CY, _CY + 1) for x in range(_CX + 2, _CX + 2 + ROAD_LENGTH)]


def _west_road_cells() -> list[tuple[int, int]]:
    """Cells of the west road. Toward intersection = increasing x."""
    return [(x, y) for y in (_CY, _CY + 1) for x in range(_CX - ROAD_LENGTH, _CX)]


def _lane_positions_north_south(
    road_cells: list[tuple[int, int]], place_at_high_y: bool, toward_intersection: bool
) -> list[list[tuple[int, int]]]:
    """
    N/S roads: two lanes (by x). place_at_high_y: True=N (place at y=27), False=S (place at y=6).
    toward_intersection True => order place -> intersection; False => intersection -> place.
    """
    by_lane: dict[int, list[tuple[int, int]]] = {}
    for c in road_cells:
        key = c[0]
        if key not in by_lane:
            by_lane[key] = []
        by_lane[key].append(c)
    for k in by_lane:
        by_lane[k].sort(key=lambda p: (p[1], p[0]))
    lanes = list(by_lane.values())
    if place_at_high_y:  # North: in = (27->18) reverse, out = (18->27) keep
        if toward_intersection:
            for L in lanes:
                L.reverse()
    else:  # South: in = (6->15) keep, out = (15->6) reverse
        if not toward_intersection:
            for L in lanes:
                L.reverse()
    return lanes


def _lane_positions_east_west(
    road_cells: list[tuple[int, int]], place_at_low_x: bool, toward_intersection: bool
) -> list[list[tuple[int, int]]]:
    """E/W roads: two lanes (by y). place_at_low_x: True=W (place at x=6), False=E (place at x=27)."""
    by_lane: dict[int, list[tuple[int, int]]] = {}
    for c in road_cells:
        key = c[1]
        if key not in by_lane:
            by_lane[key] = []
        by_lane[key].append(c)
    for k in by_lane:
        by_lane[k].sort(key=lambda p: (p[0], p[1]))
    lanes = list(by_lane.values())
    if place_at_low_x:  # West: in = (6->15) keep, out = (15->6) reverse
        if not toward_intersection:
            for L in lanes:
                L.reverse()
    else:  # East: in = (27->18) reverse, out = (18->27) keep
        if toward_intersection:
            for L in lanes:
                L.reverse()
    return lanes


def build_lanes() -> list[list[tuple[int, int]]]:
    """
    All lane segments: each lane is a directed list of grid positions (place end -> intersection or intersection -> place).
    Order: N_in, N_out, S_in, S_out, E_in, E_out, W_in, W_out; each direction has 2 lanes.
    """
    lanes: list[list[tuple[int, int]]] = []

    north_cells = _north_road_cells()
    lanes.extend(_lane_positions_north_south(north_cells, place_at_high_y=True, toward_intersection=True))
    lanes.extend(_lane_positions_north_south(north_cells, place_at_high_y=True, toward_intersection=False))

    south_cells = _south_road_cells()
    lanes.extend(_lane_positions_north_south(south_cells, place_at_high_y=False, toward_intersection=True))
    lanes.extend(_lane_positions_north_south(south_cells, place_at_high_y=False, toward_intersection=False))

    east_cells = _east_road_cells()
    lanes.extend(_lane_positions_east_west(east_cells, place_at_low_x=False, toward_intersection=True))
    lanes.extend(_lane_positions_east_west(east_cells, place_at_low_x=False, toward_intersection=False))

    west_cells = _west_road_cells()
    lanes.extend(_lane_positions_east_west(west_cells, place_at_low_x=True, toward_intersection=True))
    lanes.extend(_lane_positions_east_west(west_cells, place_at_low_x=True, toward_intersection=False))

    return lanes


def get_intersection_cells() -> list[tuple[int, int]]:
    """Return list of (gx, gy) that are part of the 2×2 intersection."""
    return list(INTERSECTION_CELLS)


# Prebuild for use by sim
ALL_LANES = build_lanes()


if __name__ == "__main__":
    print("Lane count:", len(ALL_LANES))
    for i, lane in enumerate(ALL_LANES):
        print(f"  Lane {i}: len={len(lane)}, first={lane[0]}, last={lane[-1]}")
