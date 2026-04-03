"""
Car state: origin, destination, current lane, position in lane, display color.
Spawn at place start; movement and blocking in step 5.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from sim import places
from sim.places import choose_spawn_lane
from sim import world

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
    motion_mode: str = "lane"  # "lane" or "path"

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

    # Behavior/transient state
    visibility_state: str = "green"  # green | yellow | red from visibility zone
    speed_scale: float = 1.0  # 1.0 / 0.5 / 0.0 applied to segment progression
    impasse_partner_id: int | None = None  # id(partner) when in pair impasse remedy
    impasse_active: bool = False  # true while in white override with partner
    police_priority_active: bool = False  # cyan mode: ignore all cars, move at 0.3x
    police_hold_until_exit: bool = False  # stay cyan until exiting intersection

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


def spawn_car(
    origin: str,
    destination: str | None = None,
    attract_weights: dict[str, float] | None = None,
    lane_usage_counts: dict[tuple[str, int], int] | None = None,
    out_lane_balance_coeff: float = 0.0,
) -> Car:
    """Create a car at the start of a lane leaving origin. destination defaults to weighted random other place."""
    lane_index: int | None = None
    if destination is None or destination == origin:
        lane_index = choose_spawn_lane(
            origin,
            None,
            lane_usage_counts=lane_usage_counts,
            out_lane_balance_coeff=out_lane_balance_coeff,
        )
        others = [p for p in world.get_place_rects().keys() if p != origin]
        if not others:
            destination = origin
        else:
            reachable = others
            if lane_index is not None:
                lane_out = world.lane_traffic_out(lane_index)
                if lane_out:
                    lane_reachable = [p for p in others if places.destination_reachable_from_node(lane_out, p)]
                    if lane_reachable:
                        reachable = lane_reachable
            if attract_weights:
                weights = [attract_weights.get(p, 1.0) for p in reachable]
                destination = random.choices(reachable, weights=weights, k=1)[0]
            else:
                destination = random.choice(reachable)
    if lane_index is None:
        lane_index = choose_spawn_lane(
            origin,
            destination,
            lane_usage_counts=lane_usage_counts,
            out_lane_balance_coeff=out_lane_balance_coeff,
        )
    if lane_index is None:
        fallback = [i for i in range(world.lane_count()) if world.lane_traffic_in(i) == origin]
        lane_index = random.choice(fallback) if fallback else 0
    color = random.choice(_CAR_COLOR_PALETTE)
    base_speed_multiplier = random.uniform(0.6, 1.2)
    return Car(origin=origin, destination=destination, lane_index=lane_index, position_in_lane=0, color=color, base_speed_multiplier=base_speed_multiplier)
