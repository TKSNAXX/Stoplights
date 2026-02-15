"""
Car state: origin, destination, current lane, position in lane.
Spawn at place start; movement and blocking in step 5.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from sim.places import PLACES, spawn_lanes_for_place
from sim.world import ALL_LANES


@dataclass
class Car:
    origin: str
    destination: str
    lane_index: int
    position_in_lane: int  # 0 = at start of lane (place end), len(lane)-1 = at intersection end

    def current_cell(self) -> tuple[int, int] | None:
        """Current grid position, or None if invalid."""
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
    return Car(origin=origin, destination=destination, lane_index=lane_index, position_in_lane=0)
