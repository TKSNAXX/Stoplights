"""
Car state: origin, destination, current lane, position in lane, display color.
Spawn at place start; movement and blocking in step 5.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from sim import places, routes, world
from sim.places import lane_is_full

# Palette of RGB tuples for random car colors (distinct, visible on dark background).
_CAR_COLOR_PALETTE: tuple[tuple[int, int, int], ...] = (
    (220, 60, 60),   # red
    (60, 140, 220),  # blue
    (80, 200, 100),  # green
    (220, 180, 60),  # amber
    (180, 100, 220), # purple
    (60, 200, 200),  # teal
    (220, 120, 180), # pink
    (200, 160, 80),  # tan
)


@dataclass(slots=True)
class Car:
    # Identity (spawn-time)
    origin: str
    destination: str
    color: tuple[int, int, int]  # RGB for display
    base_speed_multiplier: float  # per-car random speed (0.6–1.2), set at spawn

    # Position/routing state
    lane_index: int
    position_in_lane: int  # 0 = at start of lane (place end), len(lane)-1 = at intersection end
    intersection_cell: tuple[int, int] | None = None  # when set, car is in intersection
    pending_out_lane_index: int | None = None  # next lane when leaving intersection
    motion_mode: str = "lane"  # "lane", "path", or "merge"

    # Segment interpolation state
    segment_start_time: float | None = None
    segment_duration: float | None = None
    segment_start_pos: int | None = None  # lane cell index for lane segments
    segment_end_pos: int | None = None  # lane cell index for lane segments
    segment_t_offset: float = 0.0  # normalized progress saved across speed-scale changes
    segment_scale_reference: float = 1.0  # speed_scale used by current segment time origin

    # Pose (render output)
    pose_gx: float | None = None  # continuous render position (grid x)
    pose_gy: float | None = None  # continuous render position (grid y)
    pose_dir_index_8: int = 0  # direction from continuous tangent
    pose_lean_deg: float = 0.0  # sprite roll on screen, degrees clockwise (lane changes)

    # Behavior/transient state
    visibility_state: str = "green"  # green | yellow | red from visibility zone
    speed_scale: float = 1.0  # 1.0 / 0.5 / 0.0 applied to segment progression
    impasse_partner_id: int | None = None  # id(partner) when in pair impasse remedy
    impasse_active: bool = False  # true while in white override with partner
    police_held: bool = False  # cop is holding this approach: full stop
    police_clear: str = ""  # "drain" ignores everyone; "wave" ignores held cars

    # Itinerary (spawn-time); route_index is the current lane step
    route: tuple[routes.RouteStep, ...] = ()
    route_index: int = 0

    # Observe skills (spawn-time); Brake/fan is always on
    awareness: int = 0
    observe_skills: tuple[str, ...] = ()

    # Situation snapshot (filled each tick after movement; display-only)
    on_feature: str = ""
    next_feature: str = ""
    cars_ahead: int | None = None
    cars_behind: int | None = None
    next_feature_cars: int | None = None
    sister_ahead: int | None = None
    sister_behind: int | None = None
    merge_state: str = ""

    # Lane change: lane_index/position_in_lane are the target from commit onward,
    # so the source cell is kept here only to interpolate the pose.
    merge_source_lane: int | None = None
    merge_source_pos: int | None = None
    merge_side: str = ""  # left | right while merging, "" otherwise
    merge_reason: str = ""  # keep | pass | exit while merging, "" otherwise

    def current_cell(self) -> tuple[int, int] | None:
        """Current grid position, or None if invalid."""
        if self.intersection_cell is not None:
            return self.intersection_cell
        lane = self.get_lane()
        if not lane or self.position_in_lane < 0 or self.position_in_lane >= len(lane):
            return None
        return lane[self.position_in_lane]

    def get_lane(self) -> tuple[tuple[int, int], ...]:
        return world.get_lane_cells(self.lane_index)


CAR_SELECT_RADIUS_CELLS = 1.0


def car_grid_pose(car: Car) -> tuple[float, float] | None:
    """Continuous pose, or the current cell centre if pose is unset."""
    gx = getattr(car, "pose_gx", None)
    gy = getattr(car, "pose_gy", None)
    if gx is not None and gy is not None:
        return (float(gx), float(gy))
    cell = car.current_cell()
    if cell is None:
        return None
    return (float(cell[0]), float(cell[1]))


def nearest_car_in_radius(
    cars_list: list[Car],
    gx: float,
    gy: float,
    radius: float = CAR_SELECT_RADIUS_CELLS,
) -> Car | None:
    """Nearest civilian car in grid-space Euclidean distance, or None if none within radius."""
    best: Car | None = None
    best_d2 = radius * radius
    for car in cars_list:
        pose = car_grid_pose(car)
        if pose is None:
            continue
        dx = pose[0] - gx
        dy = pose[1] - gy
        d2 = dx * dx + dy * dy
        if d2 <= best_d2:
            best = car
            best_d2 = d2
    return best


def _choose_destination(
    origin: str,
    attract_weights: dict[str, float] | None,
) -> str | None:
    others = [p for p in world.get_place_rects().keys() if p != origin]
    if not others:
        return None
    reachable = [p for p in others if places.destination_reachable_from_node(origin, p)]
    if not reachable:
        return None
    if attract_weights:
        weights = [attract_weights.get(p, 1.0) for p in reachable]
        return random.choices(reachable, weights=weights, k=1)[0]
    return random.choice(reachable)


def spawn_car(
    origin: str,
    destination: str | None = None,
    attract_weights: dict[str, float] | None = None,
    lane_usage_counts: dict[tuple[str, int], int] | None = None,
    out_lane_balance_coeff: float = 0.0,
    occupancy: list | None = None,
) -> Car | None:
    """Create a car with a planned itinerary. Destination from attract among reachable places.

    Returns None when the dest is unreachable, planning fails, or the first lane is full
    (caller should not consume the spawn timer). No second plan on a full mouth.
    """
    if destination is None or destination == origin:
        destination = _choose_destination(origin, attract_weights)
        if destination is None:
            return None
    route = routes.plan_route(
        origin,
        destination,
        lane_usage_counts=lane_usage_counts,
        out_lane_balance_coeff=out_lane_balance_coeff,
    )
    if route is None:
        return None
    lane_index = routes.first_lane(route)
    if lane_index is None:
        return None
    if occupancy is not None and lane_is_full(lane_index, occupancy):
        return None
    color = random.choice(_CAR_COLOR_PALETTE)
    base_speed_multiplier = random.uniform(0.6, 1.2)
    from sim.awareness import roll_observe_skills

    awareness, observe_skills = roll_observe_skills()
    return Car(
        origin=origin,
        destination=destination,
        lane_index=lane_index,
        position_in_lane=0,
        color=color,
        base_speed_multiplier=base_speed_multiplier,
        route=route,
        route_index=routes.first_lane_step_index(route),
        awareness=awareness,
        observe_skills=observe_skills,
    )
