"""
Single tick(dt) that updates spawn and all cars.
Three places, roads with midway intersection; cars route by destination at intersection or remove on arrival.
"""
from __future__ import annotations

import random

from sim import cars, places
from sim.paths import path_length
from sim.world import ALL_LANES, intersection_cell_for_transition

# Spawn: one car every N seconds per place (with jitter)
SPAWN_INTERVAL = 2.0
SPAWN_JITTER = 0.3
SPAWN_INTERVAL_MIN = 1.0

# Housing, Office, Park, and Shopping spawn.
SPAWN_PLACES = (places.SOUTH, places.NORTH, places.PARK, places.SHOPPING)

# Run car movement only every Nth tick (120/16 = 7.5 moves/sec, half of original 15).
MOVEMENT_EVERY_N_TICKS = 16


class GameState:
    def __init__(self):
        self.cars: list[cars.Car] = []
        self.spawn_interval: float = SPAWN_INTERVAL  # mutable; set by traffic slider
        self.spawn_enabled: dict[str, bool] = {p: True for p in SPAWN_PLACES}
        self.spawn_timers: dict[str, float] = {
            p: random.uniform(0, self.spawn_interval) for p in SPAWN_PLACES
        }
        self._accumulated_time = 0.0
        self._tick_count = 0
        self.movement_every_n_ticks: int = MOVEMENT_EVERY_N_TICKS  # mutable; set by speed slider

    def tick(self, dt: float, current_time: float, base_duration: float = 0.2) -> None:
        self._accumulated_time += dt
        # Spawn: run every tick so spawn timing stays correct in real time; skip disabled places.
        for place in SPAWN_PLACES:
            if not self.spawn_enabled.get(place, True):
                continue
            self.spawn_timers[place] += dt
            if self.spawn_timers[place] >= self.spawn_interval:
                interval = self.spawn_interval + random.uniform(-SPAWN_JITTER, SPAWN_JITTER)
                interval = max(SPAWN_INTERVAL_MIN, interval)
                self.spawn_timers[place] -= interval
                self.cars.append(cars.spawn_car(place))

        self._tick_count += 1
        if self._tick_count % self.movement_every_n_ticks != 0:
            return

        speed = 1.0 / base_duration  # cells per second
        # Clear one-frame exited-path state from previous tick
        for c in self.cars:
            c.exited_path_in_lane = None
            c.exited_path_out_lane = None

        # Occupied cells at start of movement (includes intersection cells).
        occupied = {c.current_cell() for c in self.cars if c.current_cell() is not None}
        to_remove: list[cars.Car] = []

        # Pass 1: cars in the intersection; path_t from time, exit when path_t >= 1.
        for car in self.cars:
            if car in to_remove or car.intersection_cell is None or car.pending_out_lane_index is None:
                continue
            if car.path_entry_time is None or car.path_duration is None:
                continue
            out_lane = ALL_LANES[car.pending_out_lane_index]
            if not out_lane:
                continue
            path_t = (current_time - car.path_entry_time) / car.path_duration
            path_t = min(1.0, path_t)
            if path_t < 1.0:
                continue
            next_position = 0
            next_cell = out_lane[0]
            can_use_first = next_cell not in occupied
            can_use_second = len(out_lane) > 1 and out_lane[1] not in occupied
            if can_use_first and can_use_second:
                next_position = 1
                next_cell = out_lane[1]
            elif not can_use_first:
                continue
            cell = car.current_cell()
            if cell is not None:
                occupied.discard(cell)
            occupied.add(next_cell)
            car.exited_path_in_lane = car.lane_index
            car.exited_path_out_lane = car.pending_out_lane_index
            car.lane_index = car.pending_out_lane_index
            car.position_in_lane = next_position
            car.intersection_cell = None
            car.pending_out_lane_index = None
            car.path_entry_time = None
            car.path_duration = None

        # Pass 2: cars not in the intersection advance (in lane, or enter intersection, or arrive).
        order = sorted(
            range(len(self.cars)),
            key=lambda i: (self.cars[i].lane_index, -self.cars[i].position_in_lane),
        )
        for i in order:
            car = self.cars[i]
            if car in to_remove or car.intersection_cell is not None:
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
            enter_intersection = False

            if car.position_in_lane + 1 < len(lane):
                # Same lane: next position
                next_cell = lane[car.position_in_lane + 1]
                next_lane_index = car.lane_index
                next_position = car.position_in_lane + 1
            else:
                # At end of lane: enter intersection (inbound) or arrival (outbound)
                if car.lane_index in places.IN_LANE_INDICES:
                    next_lane_index = places.OUT_LANE_BY_PLACE.get(car.destination)
                    if next_lane_index is not None:
                        inter_cell = intersection_cell_for_transition(car.lane_index, next_lane_index)
                        if inter_cell not in occupied or inter_cell == cell:
                            enter_intersection = True
                            next_cell = inter_cell
                            next_lane_index = car.lane_index  # keep lane; store pending in car
                            next_position = car.position_in_lane
                if not enter_intersection and next_cell is None:
                    to_remove.append(car)
                    continue

            if next_cell is None or (next_cell in occupied and next_cell != cell):
                continue

            # Move
            if next_cell != cell:
                occupied.discard(cell)
                occupied.add(next_cell)
            if enter_intersection:
                out_lane_idx = places.OUT_LANE_BY_PLACE.get(car.destination)
                car.intersection_cell = next_cell
                car.pending_out_lane_index = out_lane_idx
                length = path_length(car.lane_index, out_lane_idx) if out_lane_idx is not None else 1.0
                car.path_entry_time = current_time
                car.path_duration = length / speed
            else:
                if next_lane_index is not None and next_position is not None:
                    car.lane_index = next_lane_index
                    car.position_in_lane = next_position

        for c in to_remove:
            if c in self.cars:
                self.cars.remove(c)
