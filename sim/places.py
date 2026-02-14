"""
Place definitions and spawn points.
Two places: Housing (south), Office (north). One lane between them. Housing spawns only.
"""
from __future__ import annotations

from sim.world import GRID_W, GRID_H, ROAD_LENGTH

# Place names: south = Housing (spawn), north = Office (destination)
SOUTH = "Housing"
NORTH = "Office"

PLACES = (SOUTH, NORTH)

# Only Housing has a spawn lane (the single lane, index 0).
LANES_BY_PLACE: dict[str, list[int]] = {
    SOUTH: [0],
    NORTH: [],
}


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
