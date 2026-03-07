"""
Place definitions and spawn points.
Four places: Housing (south), Office (north), Park (east), Shopping (west). Two-way roads with midway intersection; all spawn.
"""
from __future__ import annotations

import dataclasses

from sim.map_data import MAP_DATA
from sim.world import GRID_H

@dataclasses.dataclass
class PlaceConfig:
    """Per-place spawn and attract configuration."""
    spawn_interval: float = 2.0
    attract_weight: float = 1.0


# Place names: south = Housing, north = Office, east = Park, west = Shopping
SOUTH = "Housing"
NORTH = "Office"
PARK = "Park"
SHOPPING = "Shopping"

PLACES = (SOUTH, NORTH, PARK, SHOPPING)

# Spawn: Housing on lane 0, Office on lane 2, Park on lane 4, Shopping on lane 6.
LANES_BY_PLACE: dict[str, list[int]] = {
    SOUTH: [0],
    NORTH: [2],
    PARK: [4],
    SHOPPING: [6],
}

# At intersection: route by destination (place → out-lane index).
OUT_LANE_BY_PLACE: dict[str, int] = {NORTH: 1, SOUTH: 3, PARK: 5, SHOPPING: 7}

# Lanes that are "in" (approach intersection); end of these = transition. Others = arrival, remove car.
IN_LANE_INDICES = {0, 2, 4, 6}
# Lanes that are "out" (leave intersection toward place); end = arrival.
OUT_LANE_INDICES = {1, 3, 5, 7}

# Straight-through at intersection (in_lane, out_lane): N-S arm plus Park↔Shopping cross.
STRAIGHT_TRANSITIONS = {(0, 1), (2, 3), (4, 7), (6, 5)}

# U-turn at intersection: return to same arm (do not draw as valid path).
U_TURN_TRANSITIONS = {(0, 3), (2, 1), (4, 5), (6, 7)}


def is_valid_intersection_path(in_lane_index: int, out_lane_index: int) -> bool:
    """True if this (in, out) pair is a valid path to draw (not a U-turn)."""
    return (in_lane_index, out_lane_index) not in U_TURN_TRANSITIONS


def is_turn_at_intersection(in_lane_index: int, out_lane_index: int) -> bool:
    """True if this in→out transition at the intersection is a turn (different arm), not straight."""
    return (in_lane_index, out_lane_index) not in STRAIGHT_TRANSITIONS

# For display: upward = lighter grey, downward = darker grey. Park/Shopping: upper strip = downward, lower = upward.
LANE_UPWARD_INDICES = {0, 1, 5, 6}
LANE_DOWNWARD_INDICES = {2, 3, 4, 7}


def place_bounds(place: str) -> list[tuple[int, int]]:
    """Return list of (gx, gy) grid cells for the named place rectangle."""
    rect = MAP_DATA.get("place_rects", {}).get(place)
    if not rect:
        return []
    x0 = int(rect.get("x", 0))
    y0 = int(rect.get("y", 0))
    w = int(rect.get("w", 0))
    h = int(rect.get("h", 0))
    if place == NORTH and y0 < 0:
        y0 = GRID_H + y0
    if w <= 0 or h <= 0:
        return []
    return [(x, y) for x in range(x0, x0 + w) for y in range(y0, y0 + h)]


def spawn_lanes_for_place(place: str) -> list[int]:
    """Lane indices where a car spawning at this place should start (position 0)."""
    return list(LANES_BY_PLACE.get(place, []))
