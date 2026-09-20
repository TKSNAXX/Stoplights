"""
Place, intersection, and lane configs plus graph routing.

Routing uses traffic_in/traffic_out and optional scenario route_hints.
No hardcoded first-map lane index tables.
"""
from __future__ import annotations

import dataclasses
import random

from sim import world
from sim.occupancy import occupancy_from

# Optional documentation aliases for the default scenario place names.
# Not used for control flow.
HOUSING = "Housing"
OFFICE = "Office"
PARK = "Park"
SHOPPING = "Shopping"
SOUTH = HOUSING
NORTH = OFFICE


BUILDING_KIND_NONE = "none"
BUILDING_KIND_RESIDENTIAL = "residential"
BUILDING_KIND_COMMERCIAL = "commercial"
BUILDING_KIND_VALUES = (
    BUILDING_KIND_NONE,
    BUILDING_KIND_RESIDENTIAL,
    BUILDING_KIND_COMMERCIAL,
)

_COMMERCIAL_DEFAULT_IDS = frozenset({"Office", "Shopping"})


def default_building_kind(place_id: str) -> str:
    """Office/Shopping default commercial; everything else residential."""
    if place_id in _COMMERCIAL_DEFAULT_IDS:
        return BUILDING_KIND_COMMERCIAL
    return BUILDING_KIND_RESIDENTIAL


def clamp_building_kind(value: str | None, place_id: str = "") -> str:
    if value in BUILDING_KIND_VALUES:
        return value
    return default_building_kind(place_id)


def clamp_building_seed(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, n)


@dataclasses.dataclass
class Place:
    """Center-based place rectangle plus spawn/attract. Bounds: [cx - w//2, cx + w//2), [cy - l//2, cy + l//2)."""
    center_x: int = 0
    center_y: int = 0
    width: int = 5
    length: int = 5
    spawn_interval: float = 2.0
    attract_weight: float = 1.0
    protected: bool = False
    building_kind: str = BUILDING_KIND_RESIDENTIAL
    building_seed: int = 0


PLACE_SIZE_MIN = 1
PLACE_SIZE_MAX = 16

LANE_TYPE_NORMAL = "normal"
LANE_TYPE_PASSING = "passing"
LANE_TYPES = (LANE_TYPE_NORMAL, LANE_TYPE_PASSING)

INTERSECTION_TYPE_NONE = "none"
INTERSECTION_TYPE_CROSS = "cross"
INTERSECTION_TYPE_X = "x"  # load alias for cross
INTERSECTION_TYPE_CORNER = "corner"
INTERSECTION_TYPE_STRAIGHT = "straight"
INTERSECTION_TYPE_TEE = "tee"
INTERSECTION_TYPE_DOUBLE = "double"  # load alias of double_cross
INTERSECTION_TYPE_MIXED = "mixed"  # load alias of mixed_cross
INTERSECTION_TYPE_BIG = "big"  # load alias of double_cross
INTERSECTION_TYPE_DOUBLE_CROSS = "double_cross"
INTERSECTION_TYPE_DOUBLE_TEE = "double_tee"
INTERSECTION_TYPE_DOUBLE_CORNER = "double_corner"
INTERSECTION_TYPE_MIXED_CROSS = "mixed_cross"
INTERSECTION_TYPE_MIXED_TEE = "mixed_tee"
INTERSECTION_TYPE_MIXED_CORNER = "mixed_corner"
INTERSECTION_TYPE_MIXED_STRAIGHT = "mixed_straight"
INTERSECTION_TYPE_ONE = "one"  # load alias of one_cross
INTERSECTION_TYPE_ONE_CROSS = "one_cross"
INTERSECTION_TYPE_ONE_TEE = "one_tee"
INTERSECTION_TYPE_ONE_CORNER = "one_corner"
INTERSECTION_TYPE_ONE_STRAIGHT = "one_straight"
INTERSECTION_TYPE_NORMAL = "normal"  # load alias of normal_cross
INTERSECTION_TYPE_NORMAL_CROSS = "normal_cross"
INTERSECTION_TYPE_NORMAL_TEE = "normal_tee"
INTERSECTION_TYPE_NORMAL_CORNER = "normal_corner"
INTERSECTION_TYPE_NORMAL_STRAIGHT = "normal_straight"
INTERSECTION_TYPES = (
    INTERSECTION_TYPE_NONE,
    INTERSECTION_TYPE_CROSS,
    INTERSECTION_TYPE_CORNER,
    INTERSECTION_TYPE_STRAIGHT,
    INTERSECTION_TYPE_TEE,
    INTERSECTION_TYPE_DOUBLE_CROSS,
    INTERSECTION_TYPE_DOUBLE_TEE,
    INTERSECTION_TYPE_DOUBLE_CORNER,
    INTERSECTION_TYPE_MIXED_CROSS,
    INTERSECTION_TYPE_MIXED_TEE,
    INTERSECTION_TYPE_MIXED_CORNER,
    INTERSECTION_TYPE_MIXED_STRAIGHT,
    INTERSECTION_TYPE_ONE_CROSS,
    INTERSECTION_TYPE_ONE_TEE,
    INTERSECTION_TYPE_ONE_CORNER,
    INTERSECTION_TYPE_ONE_STRAIGHT,
    INTERSECTION_TYPE_NORMAL_CROSS,
    INTERSECTION_TYPE_NORMAL_TEE,
    INTERSECTION_TYPE_NORMAL_CORNER,
    INTERSECTION_TYPE_NORMAL_STRAIGHT,
)

INTERSECTION_SIZE_MIN = 2
INTERSECTION_SIZE_MAX = 12
INTERSECTION_SIZE_DEFAULT = 4
INTERSECTION_SIZE_VALUES = (2, 4, 6, 8, 10, 12)


def clamp_intersection_type(raw) -> str:
    """Canonical overlay type. Legacy 'x' is cross; 'big'/'double' are double_cross."""
    if raw == INTERSECTION_TYPE_X:
        return INTERSECTION_TYPE_CROSS
    if raw in (INTERSECTION_TYPE_BIG, INTERSECTION_TYPE_DOUBLE):
        return INTERSECTION_TYPE_DOUBLE_CROSS
    if raw == INTERSECTION_TYPE_MIXED:
        return INTERSECTION_TYPE_MIXED_CROSS
    if raw == INTERSECTION_TYPE_ONE:
        return INTERSECTION_TYPE_ONE_CROSS
    if raw == INTERSECTION_TYPE_NORMAL:
        return INTERSECTION_TYPE_NORMAL_CROSS
    if raw in INTERSECTION_TYPES:
        return str(raw)
    return INTERSECTION_TYPE_CROSS


def overlay_stamp_family(itype: str) -> str:
    """cross/tee/corner/straight from a stamp name, including double_/mixed_/one_/normal_."""
    if (
        itype.startswith("double_")
        or itype.startswith("mixed_")
        or itype.startswith("one_")
        or itype.startswith("normal_")
    ):
        return itype.split("_", 1)[1]
    return itype

# Module-level route hints from the active scenario: (origin, dest, via_node).
# dest or via may be HINT_WILDCARD ("*"): dest matches any destination; via means
# any first-hop neighbour that still reaches dest (civilian planner only).
HINT_WILDCARD = "*"
_route_hints: list[tuple[str, str, str]] = []


def set_route_hints(hints: list[tuple[str, str, str]] | None) -> None:
    """Install route hints from the active scenario (empty clears)."""
    global _route_hints
    _route_hints = list(hints or [])


def get_route_hints() -> list[tuple[str, str, str]]:
    return list(_route_hints)


@dataclasses.dataclass
class IntersectionConfig:
    """Per-intersection type, center, and size."""
    intersection_type: str = INTERSECTION_TYPE_CROSS
    size_cells: int = INTERSECTION_SIZE_DEFAULT
    center_x: int = 36
    center_y: int = 48
    protected: bool = False


@dataclasses.dataclass
class LaneConfig:
    """Per-lane configuration. Direction and traffic in/out are derived at build time."""
    speed_limit: float = 1.0
    lane_type: str = LANE_TYPE_NORMAL
    start_tile: tuple[int, int] = (0, 0)
    end_tile: tuple[int, int] = (0, 0)
    protected: bool = False


def out_lane_for_place(place: str, from_intersection: str | None = None) -> int | None:
    """Out-lane that goes to place from the given intersection (or any if None)."""
    if from_intersection is not None:
        lane = choose_next_lane_from_node(from_intersection, place)
        if lane is not None:
            return lane
    for i in world.incoming_lanes(place):
        if world.is_intersection(world.lane_traffic_in(i)):
            if from_intersection is None or world.lane_traffic_in(i) == from_intersection:
                return i
    return None


def in_lane_indices() -> frozenset[int]:
    """Lanes that approach an intersection."""
    return world.in_lane_ids()


def out_lane_indices() -> frozenset[int]:
    """Lanes that leave an intersection."""
    return world.out_lane_ids()


def is_uturn_transition(in_lane_index: int, out_lane_index: int) -> bool:
    """
    True if outbound goes back toward the same node the approach came from.
    """
    src = world.lane_traffic_in(in_lane_index)
    dst = world.lane_traffic_out(out_lane_index)
    if not src or not dst or src != dst:
        return False
    return True


def is_valid_intersection_path(in_lane_index: int, out_lane_index: int) -> bool:
    """
    True when this in→out pair is a legal crossing of a shared intersection.

    U-turns stay illegal. Twin dests: keep-side on the straight, inside (tight)
    on a turn — never the far lane of the new heading, and never a 180.
    Twin-to-single: both inbounds may use that one outbound.
    """
    if is_uturn_transition(in_lane_index, out_lane_index):
        return False
    node = world.lane_traffic_out(in_lane_index)
    if not world.is_intersection(node):
        return False
    if world.lane_traffic_in(out_lane_index) != node:
        return False
    in_group = world.mouth_group(in_lane_index, node, inbound=True)
    out_group = world.mouth_group(out_lane_index, node, inbound=False)
    if len(in_group) >= 2 and len(out_group) <= 1:
        return True
    if len(out_group) >= 2:
        from sim.junction import OPPOSITE_CARDINAL
        from sim.paths import is_straight_path

        if world.lane_direction(out_lane_index) == OPPOSITE_CARDINAL.get(
            world.lane_direction(in_lane_index), ""
        ):
            return False
        if is_straight_path(in_lane_index, out_lane_index):
            if len(in_group) >= 2:
                in_left = world.left_lane_of(in_group)
                out_left = world.left_lane_of(out_group)
                return (in_lane_index == in_left) == (out_lane_index == out_left)
            return world.mouths_aligned(in_lane_index, out_lane_index)
        return out_lane_index == world.nearer_to_entry_edge(in_lane_index, out_group)
    return True


def is_turn_at_intersection(in_lane_index: int, out_lane_index: int) -> bool:
    """True if in→out is a turn (not straight-through by tangent)."""
    from sim.paths import is_straight_path

    return not is_straight_path(in_lane_index, out_lane_index)


def place_bounds(place: str) -> list[tuple[int, int]]:
    """Return list of (gx, gy) grid cells for the named place rectangle."""
    rect = world.get_place_rects().get(place)
    if not rect:
        return []
    x0 = int(rect.get("x", 0))
    y0 = int(rect.get("y", 0))
    w = int(rect.get("w", 0))
    h = int(rect.get("h", 0))
    if w <= 0 or h <= 0:
        return []
    return [(x, y) for x in range(x0, x0 + w) for y in range(y0, y0 + h)]


def _hint_via(origin: str, destination: str) -> str | None:
    """Exact (from, dest) wins; else first (from, *). First row of each class wins."""
    star_via: str | None = None
    for a, b, via in _route_hints:
        if a != origin:
            continue
        if b == destination:
            return via
        if b == HINT_WILDCARD and star_via is None:
            star_via = via
    return star_via


def spawn_lanes_for_place(place: str, destination: str | None = None) -> list[int]:
    """Lane indices where a car spawning at this place should start (position 0)."""
    outgoing = list(world.outgoing_lanes(place))
    if destination is None or not outgoing:
        return outgoing

    direct = [i for i in outgoing if world.lane_exit_node(i) == destination]
    if direct:
        return direct

    next_hops = world.best_next_hops(place, destination)
    via = _hint_via(place, destination)
    if via is not None and via in next_hops:
        hinted = [i for i in outgoing if world.lane_exit_node(i) == via]
        if hinted:
            return hinted
    if next_hops:
        routed = [i for i in outgoing if world.lane_exit_node(i) in next_hops]
        if routed:
            return routed
    return outgoing


def lane_is_full(lane_idx: int, occupancy) -> bool:
    """True if cell 0 is taken or the number of on-lane cars is at least the cell count."""
    cells = world.get_lane_cells(lane_idx)
    if not cells:
        return True
    occ = occupancy_from(occupancy)
    on_lane = occ.cars_on_lane(lane_idx)
    n = len(on_lane)
    cell0 = any(getattr(car, "position_in_lane", -1) == 0 for car in on_lane)
    return cell0 or n >= len(cells)


def choose_spawn_lane(
    place: str,
    destination: str | None = None,
    lane_usage_counts: dict[tuple[str, int], int] | None = None,
    out_lane_balance_coeff: float = 0.0,
    occupancy: list | None = None,
) -> int | None:
    candidates = spawn_lanes_for_place(place, destination)
    if occupancy is not None:
        candidates = [i for i in candidates if not lane_is_full(i, occupancy)]
    if not candidates:
        return None
    if not lane_usage_counts or out_lane_balance_coeff <= 0.0:
        return random.choice(candidates)
    max_use = max(lane_usage_counts.get((place, lane), 0) for lane in candidates)
    weights = [
        1.0 + out_lane_balance_coeff * (max_use - lane_usage_counts.get((place, lane), 0))
        for lane in candidates
    ]
    return random.choices(candidates, weights=weights, k=1)[0]


def destination_reachable_from_node(start_node: str, destination: str) -> bool:
    return world.destination_reachable(start_node, destination)


def _candidates_without_uturn(inbound_lane_index: int | None, candidates: list[int]) -> list[int]:
    if inbound_lane_index is None or not candidates:
        return candidates
    node = world.lane_traffic_out(inbound_lane_index)
    if world.is_intersection(node):
        return [c for c in candidates if is_valid_intersection_path(inbound_lane_index, c)]
    good = [c for c in candidates if not is_uturn_transition(inbound_lane_index, c)]
    return good if good else candidates


def choose_next_lane_from_node(
    from_node: str,
    destination: str,
    inbound_lane_index: int | None = None,
) -> int | None:
    outgoing = list(world.outgoing_lanes(from_node))
    if not outgoing:
        return None

    direct = [i for i in outgoing if world.lane_exit_node(i) == destination]
    direct_pick = _candidates_without_uturn(inbound_lane_index, direct)
    if direct_pick:
        return random.choice(direct_pick)

    next_hops = world.best_next_hops(from_node, destination)
    via = _hint_via(from_node, destination)
    if via is not None and via in next_hops:
        hinted = [i for i in outgoing if world.lane_exit_node(i) == via]
        hinted_pick = _candidates_without_uturn(inbound_lane_index, hinted)
        if hinted_pick:
            return random.choice(hinted_pick)
    if next_hops:
        routed = [i for i in outgoing if world.lane_exit_node(i) in next_hops]
        routed_pick = _candidates_without_uturn(inbound_lane_index, routed)
        if routed_pick:
            return random.choice(routed_pick)

    fallback = _candidates_without_uturn(inbound_lane_index, outgoing)
    return random.choice(fallback) if fallback else None
