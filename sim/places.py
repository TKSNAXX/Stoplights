"""
Place definitions and spawn points.
Two places: Housing (south), Office (north). Two lanes between them; both spawn.
"""
from __future__ import annotations

from sim.world import GRID_W, GRID_H, ROAD_LENGTH

# Place names: south = Housing, north = Office
SOUTH = "Housing"
NORTH = "Office"

PLACES = (SOUTH, NORTH)

# Lane 0 = Housing->Office, lane 1 = Office->Housing.
LANES_BY_PLACE: dict[str, list[int]] = {
    SOUTH: [0],
    NORTH: [1],
}

# For display: which lane is drawn in which grey (upward = lighter, downward = darker).
LANE_UPWARD_INDICES = {0}
LANE_DOWNWARD_INDICES = {1}


def place_bounds(place: str) -> list[tuple[int, int]]:
    """Return list of (gx, gy) grid cells for the 6×6 place."""
    if place == SOUTH:
        return [(x, y) for x in range(GRID_W) for y in range(6)]
    if place == NORTH:
        return [(x, y) for x in range(GRID_W) for y in range(6 + ROAD_LENGTH, GRID_H)]
    return []


def spawn_lanes_for_place(place: str) -> list[int]:
    """Lane indices where a car spawning at this place should start (position 0)."""
    return list(LANES_BY_PLACE.get(place, []))
