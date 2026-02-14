"""
Single tick(dt) that updates spawn and all cars.
Sim state: list of cars, spawn timers per place. No rendering.
"""
from __future__ import annotations

from sim import cars, places
from sim.world import ALL_LANES

# Spawn: one car every N seconds per place
SPAWN_INTERVAL = 2.0

# Lane indices that are "in" (toward intersection); rest are "out" (toward place).
IN_LANE_INDICES = {0, 1, 4, 5, 8, 9, 12, 13}


class GameState:
    def __init__(self):
        self.cars: list[cars.Car] = []
        self.spawn_timers: dict[str, float] = {p: 0.0 for p in places.PLACES}
        self._accumulated_time = 0.0

    def tick(self, dt: float) -> None:
        self._accumulated_time += dt
        # Spawn: each place may spawn one car every SPAWN_INTERVAL
        for place in places.PLACES:
            self.spawn_timers[place] += dt
            if self.spawn_timers[place] >= SPAWN_INTERVAL:
                self.spawn_timers[place] -= SPAWN_INTERVAL
                self.cars.append(cars.spawn_car(place))

        # Occupied cells at start of movement (we'll update as we move cars)
        occupied = {c.current_cell() for c in self.cars if c.current_cell() is not None}

        # Process cars front-first (by lane, then by position descending) so lead car frees the cell
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
                # At end of lane
                if car.lane_index in IN_LANE_INDICES:
                    # Transition to out-lane toward destination
                    origin = places.IN_LANE_ORIGIN.get(car.lane_index)
                    base_in = places.IN_LANE_BASE.get(origin, 0)
                    base_out = places.OUT_LANE_BASE.get(car.destination)
                    if base_out is not None:
                        sub = car.lane_index - base_in
                        out_lane_index = base_out + sub
                        out_lane = ALL_LANES[out_lane_index]
                        if out_lane:
                            next_cell = out_lane[0]
                            next_lane_index = out_lane_index
                            next_position = 0
                else:
                    # At end of out-lane: arrived at place
                    place_lanes = places.OUT_LANES_BY_PLACE.get(car.destination, [])
                    if car.lane_index in place_lanes:
                        to_remove.append(car)
                    # else no next
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
