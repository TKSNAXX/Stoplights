"""
Place definitions and spawn points.
Two places: Housing (south), Office (north). Two-way road with midway intersection; both spawn.
"""
from __future__ import annotations

from sim.world import GRID_W, GRID_H, ROAD_LENGTH

# Place names: south = Housing, north = Office
SOUTH = "Housing"
NORTH = "Office"

PLACES = (SOUTH, NORTH)

# Spawn: Housing on lane 0 (Housing→inter), Office on lane 2 (Office→inter).
LANES_BY_PLACE: dict[str, list[int]] = {
    SOUTH: [0],
    NORTH: [2],
}

# At intersection: which lane to transition to (in-lane index → out-lane index).
# Lane 0 (Housing→inter) → lane 1 (inter→Office). Lane 2 (Office→inter) → lane 3 (inter→Housing).
NEXT_LANE_AT_INTERSECTION: dict[int, int] = {0: 1, 2: 3}

# Lanes that are "in" (approach intersection); end of these = transition. Others = arrival, remove car.
IN_LANE_INDICES = {0, 2}
# Lanes that are "out" (leave intersection toward place); end = arrival.
OUT_LANE_INDICES = {1, 3}

# For display: upward = Housing→Office (lanes 0, 1), downward = Office→Housing (lanes 2, 3).
LANE_UPWARD_INDICES = {0, 1}
LANE_DOWNWARD_INDICES = {2, 3}


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
