"""
Place definitions and spawn points.
Three places: Housing (south), Office (north), Park (east). Two-way roads with midway intersection; all spawn.
"""
from __future__ import annotations

from sim.world import GRID_W, GRID_H, ROAD_LENGTH

# Place names: south = Housing, north = Office, east = Park
SOUTH = "Housing"
NORTH = "Office"
PARK = "Park"

PLACES = (SOUTH, NORTH, PARK)

# Spawn: Housing on lane 0, Office on lane 2, Park on lane 4.
LANES_BY_PLACE: dict[str, list[int]] = {
    SOUTH: [0],
    NORTH: [2],
    PARK: [4],
}

# At intersection: route by destination (place → out-lane index).
OUT_LANE_BY_PLACE: dict[str, int] = {NORTH: 1, SOUTH: 3, PARK: 5}

# Lanes that are "in" (approach intersection); end of these = transition. Others = arrival, remove car.
IN_LANE_INDICES = {0, 2, 4}
# Lanes that are "out" (leave intersection toward place); end = arrival.
OUT_LANE_INDICES = {1, 3, 5}

# For display: upward = lighter grey, downward = darker grey (Park arm: 4 down, 5 up).
LANE_UPWARD_INDICES = {0, 1, 5}
LANE_DOWNWARD_INDICES = {2, 3, 4}


def place_bounds(place: str) -> list[tuple[int, int]]:
    """Return list of (gx, gy) grid cells for the 6×6 place."""
    if place == SOUTH:
        return [(x, y) for x in range(GRID_W) for y in range(6)]
    if place == NORTH:
        return [(x, y) for x in range(GRID_W) for y in range(6 + ROAD_LENGTH, GRID_H)]
    if place == PARK:
        return [(x, y) for x in range(8, 14) for y in range(7, 13)]
    return []


def spawn_lanes_for_place(place: str) -> list[int]:
    """Lane indices where a car spawning at this place should start (position 0)."""
    return list(LANES_BY_PLACE.get(place, []))
