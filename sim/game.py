"""
Single tick(dt) that updates spawn and all cars.
Three places, roads with midway intersection; cars route by destination at intersection or remove on arrival.
"""
from __future__ import annotations

import random

from sim import cars, places
from sim.world import ALL_LANES

# Spawn: one car every N seconds per place (with jitter)
SPAWN_INTERVAL = 2.0
SPAWN_JITTER = 0.3
SPAWN_INTERVAL_MIN = 1.0

# Housing, Office, Park, and Shopping spawn.
SPAWN_PLACES = (places.SOUTH, places.NORTH, places.PARK, places.SHOPPING)


class GameState:
    def __init__(self):
        self.cars: list[cars.Car] = []
        self.spawn_timers: dict[str, float] = {
            p: random.uniform(0, SPAWN_INTERVAL) for p in SPAWN_PLACES
        }
        self._accumulated_time = 0.0

    def tick(self, dt: float) -> None:
        self._accumulated_time += dt
        # Spawn at Housing and Office
        for place in SPAWN_PLACES:
            self.spawn_timers[place] += dt
            if self.spawn_timers[place] >= SPAWN_INTERVAL:
                interval = SPAWN_INTERVAL + random.uniform(-SPAWN_JITTER, SPAWN_JITTER)
                interval = max(SPAWN_INTERVAL_MIN, interval)
                self.spawn_timers[place] -= interval
                self.cars.append(cars.spawn_car(place))

        # Occupied cells at start of movement
        occupied = {c.current_cell() for c in self.cars if c.current_cell() is not None}

        # Process cars front-first (by lane, then by position descending)
        order = sorted(
            range(len(self.cars)),
            key=lambda i: (self.cars[i].lane_index, -self.cars[i].position_in_lane),
        )
        to_remove: list[cars.Car] = []
        for i in order:
            car = self.cars[i]
            if car in to_remove:
                continue
            cell = car.current_cell()
            if cell is None:
                continue
            lane = car.get_lane()
            if not lane:
                continue

            next_cell: tuple[int, int] | None = None
            next_lane_index: int | None = None
            next_position: int | None = None

            if car.position_in_lane + 1 < len(lane):
                # Same lane: next position
                next_cell = lane[car.position_in_lane + 1]
                next_lane_index = car.lane_index
                next_position = car.position_in_lane + 1
            else:
                # At end of lane: transition at intersection (by destination) or arrival at place
                if car.lane_index in places.IN_LANE_INDICES:
                    next_lane_index = places.OUT_LANE_BY_PLACE.get(car.destination)
                    if next_lane_index is not None:
                        out_lane = ALL_LANES[next_lane_index]
                        if out_lane:
                            next_cell = out_lane[0]
                            next_position = 0
                if next_cell is None:
                    # Arrival (end of out-lane) or no transition
                    to_remove.append(car)
                    continue

            if next_cell is None or next_cell in occupied or next_lane_index is None or next_position is None:
                continue

            # Move
            occupied.discard(cell)
            occupied.add(next_cell)
            car.lane_index = next_lane_index
            car.position_in_lane = next_position

        for c in to_remove:
            if c in self.cars:
                self.cars.remove(c)
