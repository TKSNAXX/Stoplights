"""
Place definitions and spawn points.
Four places: Housing (south), Office (north), Park (east), Shopping (west). Two-way roads with midway intersection; all spawn.
"""
from __future__ import annotations

import dataclasses

from sim.map_data import MAP_DATA
from sim import world

@dataclasses.dataclass
class PlaceConfig:
    """Per-place spawn and attract configuration."""
    spawn_interval: float = 2.0
    attract_weight: float = 1.0


LANE_TYPE_NORMAL = "normal"
LANE_TYPE_PASSING = "passing"
LANE_TYPES = (LANE_TYPE_NORMAL, LANE_TYPE_PASSING)

INTERSECTION_TYPE_X = "x"
INTERSECTION_TYPE_CORNER = "corner"
INTERSECTION_TYPES = (INTERSECTION_TYPE_X, INTERSECTION_TYPE_CORNER)

# Intersection size: even cells only, 2–12. Default 4.
INTERSECTION_SIZE_MIN = 2
INTERSECTION_SIZE_MAX = 12
INTERSECTION_SIZE_DEFAULT = 4
INTERSECTION_SIZE_VALUES = (2, 4, 6, 8, 10, 12)


@dataclasses.dataclass
class IntersectionConfig:
    """Per-intersection type: x (cross) or corner; size in cells (even, 2–12)."""
    intersection_type: str = INTERSECTION_TYPE_X
    size_cells: int = INTERSECTION_SIZE_DEFAULT


@dataclasses.dataclass
class LaneConfig:
    """Per-lane configuration. speed_limit not yet wired to car movement. lane_type selects sprite (normal vs passing)."""
    speed_limit: float = 1.0
    lane_type: str = LANE_TYPE_NORMAL


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

# Housing-Park direct route: lanes 8-11, own junction.
ROUTE_HOUSING_PARK = frozenset({(SOUTH, PARK), (PARK, SOUTH)})
HP_IN_LANE_INDICES = {8, 10}
HP_OUT_LANE_INDICES = {9, 11}
HP_OUT_LANE_FOR_IN: dict[int, int] = {8: 9, 10: 11}

# At intersection: route by destination (place → out-lane index).
OUT_LANE_BY_PLACE: dict[str, int] = {NORTH: 1, SOUTH: 3, PARK: 5, SHOPPING: 7}

# Lanes that are "in" (approach intersection); end of these = transition. Others = arrival, remove car.
IN_LANE_INDICES = {0, 2, 4, 6, 8, 10}
# Lanes that are "out" (leave intersection toward place); end = arrival.
OUT_LANE_INDICES = {1, 3, 5, 7, 9, 11}

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
        y0 = world.get_grid_h() + y0
    if w <= 0 or h <= 0:
        return []
    return [(x, y) for x in range(x0, x0 + w) for y in range(y0, y0 + h)]


def spawn_lanes_for_place(place: str, destination: str | None = None) -> list[int]:
    """Lane indices where a car spawning at this place should start (position 0)."""
    if destination is not None and (place, destination) in ROUTE_HOUSING_PARK:
        return [8] if place == SOUTH else [10]
    return list(LANES_BY_PLACE.get(place, []))
