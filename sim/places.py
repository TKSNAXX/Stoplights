"""
Place definitions and spawn points.
Four places: Housing (south), Office (north), Park (east), Shopping (west). Two-way roads with midway intersection; all spawn.
"""
from __future__ import annotations

import dataclasses

from sim import world
from sim.map_data import MAP_DATA, get_template_metadata

@dataclasses.dataclass
class PlaceConfig:
    """Per-place spawn and attract configuration."""
    spawn_interval: float = 2.0
    attract_weight: float = 1.0


@dataclasses.dataclass
class PlaceGeometry:
    """Center-based place rectangle. Bounds: [cx - w//2, cx + w//2), [cy - l//2, cy + l//2)."""
    center_x: int = 0
    center_y: int = 0
    width: int = 5
    length: int = 5


PLACE_SIZE_MIN = 1
PLACE_SIZE_MAX = 16


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


# Default bypass center (corner of Housing east + Park south from default map, 2x scale)
BYPASS_DEFAULT_CENTER = (64, 2)


@dataclasses.dataclass
class IntersectionConfig:
    """Per-intersection type, center, and size. Intersections are a general map entity with movable centers."""
    intersection_type: str = INTERSECTION_TYPE_X
    size_cells: int = INTERSECTION_SIZE_DEFAULT
    center_x: int = 36
    center_y: int = 48


@dataclasses.dataclass
class LaneConfig:
    """Per-lane configuration. speed_limit not yet wired to car movement. lane_type selects sprite (normal vs passing).
    Lanes are defined by start and end tiles. Direction and traffic in/out are derived at build time."""
    speed_limit: float = 1.0
    lane_type: str = LANE_TYPE_NORMAL
    start_tile: tuple[int, int] = (0, 0)
    end_tile: tuple[int, int] = (0, 0)


# Place names: south = Housing, north = Office, east = Park, west = Shopping
SOUTH = "Housing"
NORTH = "Office"
PARK = "Park"
SHOPPING = "Shopping"

PLACES = (SOUTH, NORTH, PARK, SHOPPING)

_TEMPLATE = get_template_metadata(MAP_DATA)
_SECONDARY_INTERSECTION_ID = str(_TEMPLATE.get("secondary_intersection_id", "bypass"))
ROUTE_VIA_SECONDARY = frozenset(
    (str(pair[0]), str(pair[1]))
    for pair in _TEMPLATE.get("route_pairs_via_secondary", [])
    if isinstance(pair, (list, tuple)) and len(pair) == 2
)


def out_lane_for_place(place: str, from_intersection: str = "main") -> int | None:
    """Out-lane that goes to place from the given intersection (main, bypass, or extra)."""
    for i in range(world.lane_count()):
        if world.lane_traffic_in(i) == from_intersection and world.lane_traffic_out(i) == place:
            return i
    return None


def in_lane_indices() -> set[int]:
    """Lanes that approach an intersection (traffic_out is main, bypass, or any extra intersection)."""
    return {i for i in range(world.lane_count()) if world.is_intersection(world.lane_traffic_out(i))}


def out_lane_indices() -> set[int]:
    """Lanes that leave an intersection (traffic_in is main, bypass, or any extra intersection)."""
    return {i for i in range(world.lane_count()) if world.is_intersection(world.lane_traffic_in(i))}

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
    rect = world.get_place_rects().get(place)
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
    result: list[int] = []
    for i in range(world.lane_count()):
        if world.lane_traffic_in(i) == place:
            out = world.lane_traffic_out(i)
            if destination is None or out == destination:
                result.append(i)
            elif destination is not None and (place, destination) in ROUTE_VIA_SECONDARY and out == _SECONDARY_INTERSECTION_ID:
                result.append(i)
    return result if result else [0]
