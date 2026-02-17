"""
Car state: origin, destination, current lane, position in lane, display color.
Spawn at place start; movement and blocking in step 5.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from sim.places import PLACES, spawn_lanes_for_place
from sim.world import ALL_LANES

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


@dataclass
class Car:
    origin: str
    destination: str
    lane_index: int
    position_in_lane: int  # 0 = at start of lane (place end), len(lane)-1 = at intersection end
    color: tuple[int, int, int]  # RGB for display
    intersection_cell: tuple[int, int] | None = None  # when set, car is in intersection
    pending_out_lane_index: int | None = None  # next lane when leaving intersection
    path_entry_time: float | None = None  # when in intersection: time of path entry
    path_duration: float | None = None  # when in intersection: path_length/speed
    exited_path_in_lane: int | None = None  # set for one frame on exit for display (prev = path(1))
    exited_path_out_lane: int | None = None  # set for one frame on exit for display
    motion_mode: str = "lane"  # "lane" or "path"
    segment_start_time: float | None = None
    segment_duration: float | None = None
    segment_start_pos: int | None = None  # lane cell index for lane segments
    segment_end_pos: int | None = None  # lane cell index for lane segments
    pose_gx: float | None = None  # continuous render position (grid x)
    pose_gy: float | None = None  # continuous render position (grid y)
    pose_dir_index_8: int = 0  # direction from continuous tangent
    visibility_state: str = "green"  # green | yellow | red from visibility zone
    speed_scale: float = 1.0  # 1.0 / 0.5 / 0.0 applied to segment progression
    segment_t_offset: float = 0.0  # normalized progress saved across speed-scale changes
    segment_scale_reference: float = 1.0  # speed_scale used by current segment time origin
    impasse_partner_id: int | None = None  # id(partner) when in pair impasse remedy
    impasse_active: bool = False  # true while in white override with partner
    police_priority_active: bool = False  # cyan mode: ignore all cars, move at 0.3x
    police_hold_until_exit: bool = False  # stay cyan until exiting intersection
    base_speed_multiplier: float = 1.0  # per-car random speed (0.6–1.2), set at spawn

    def current_cell(self) -> tuple[int, int] | None:
        """Current grid position, or None if invalid."""
        if self.intersection_cell is not None:
            return self.intersection_cell
        lane = self.get_lane()
        if not lane or self.position_in_lane < 0 or self.position_in_lane >= len(lane):
            return None
        return lane[self.position_in_lane]

    def get_lane(self) -> list[tuple[int, int]]:
        return ALL_LANES[self.lane_index] if 0 <= self.lane_index < len(ALL_LANES) else []


def spawn_car(origin: str, destination: str | None = None) -> Car:
    """Create a car at the start of a lane leaving origin. destination defaults to a random other place."""
    if destination is None or destination == origin:
        others = [p for p in PLACES if p != origin]
        destination = random.choice(others) if others else origin
    lanes = spawn_lanes_for_place(origin)
    lane_index = lanes[0] if lanes else 0
    color = random.choice(_CAR_COLOR_PALETTE)
    base_speed_multiplier = random.uniform(0.6, 1.2)
    return Car(origin=origin, destination=destination, lane_index=lane_index, position_in_lane=0, color=color, base_speed_multiplier=base_speed_multiplier)
