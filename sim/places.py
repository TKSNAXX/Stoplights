"""
Place definitions and spawn points.
Four places: Office (N), Park (E), Housing (S), Shopping (W). Each 6×6 at road end.
"""
from __future__ import annotations

from sim.world import ALL_LANES, GRID_W, GRID_H, ROAD_LENGTH

CX = (GRID_W - 1) // 2
CY = (GRID_H - 1) // 2

# Place names and cardinal direction
NORTH = "Office"
EAST = "Park"
SOUTH = "Housing"
WEST = "Shopping"

PLACES = (NORTH, EAST, SOUTH, WEST)

# Lane indices from world.build_lanes(): N_in, N_out, S_in, S_out, E_in, E_out, W_in, W_out (2 each).
# "In" = toward intersection = lanes that leave the place. So spawn on these.
LANES_BY_PLACE: dict[str, list[int]] = {
    NORTH: [0, 1],   # N in
    EAST: [8, 9],    # E in
    SOUTH: [4, 5],   # S in
    WEST: [12, 13],  # W in
}

# Out lanes (intersection -> place): same order N, S, E, W.
OUT_LANES_BY_PLACE: dict[str, list[int]] = {
    NORTH: [2, 3],   # N out
    EAST: [10, 11],  # E out
    SOUTH: [6, 7],   # S out
    WEST: [14, 15],  # W out
}

# Which place (destination) each in-lane road serves. In-lane index -> origin place.
IN_LANE_ORIGIN: dict[int, str] = {
    0: NORTH, 1: NORTH, 4: SOUTH, 5: SOUTH, 8: EAST, 9: EAST, 12: WEST, 13: WEST,
}

# In-lane base index per place (so sub-lane = lane_index - base is 0 or 1).
IN_LANE_BASE: dict[str, int] = {NORTH: 0, SOUTH: 4, EAST: 8, WEST: 12}
OUT_LANE_BASE: dict[str, int] = {NORTH: 2, SOUTH: 6, EAST: 10, WEST: 14}


def place_bounds(place: str) -> list[tuple[int, int]]:
    """Return list of (gx, gy) grid cells for the 6×6 place. Outer end of road."""
    if place == NORTH:
        return [(x, y) for x in range(CX - 2, CX + 4) for y in range(CY + 2 + ROAD_LENGTH, CY + 2 + ROAD_LENGTH + 6)]
    if place == SOUTH:
        return [(x, y) for x in range(CX - 2, CX + 4) for y in range(CY - ROAD_LENGTH - 6, CY - ROAD_LENGTH)]
    if place == EAST:
        return [(x, y) for x in range(CX + 2 + ROAD_LENGTH, CX + 2 + ROAD_LENGTH + 6) for y in range(CY - 2, CY + 4)]
    if place == WEST:
        return [(x, y) for x in range(CX - ROAD_LENGTH - 6, CX - ROAD_LENGTH) for y in range(CY - 2, CY + 4)]
    return []


def spawn_lanes_for_place(place: str) -> list[int]:
    """Lane indices where a car spawning at this place should start (position 0)."""
    return list(LANES_BY_PLACE.get(place, []))
