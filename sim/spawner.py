"""
Spawn-related helpers for GameState.
"""
from __future__ import annotations

import random

from sim import cars

SPAWN_JITTER = 0.3
SPAWN_INTERVAL_MIN = 1.0


def update_spawns(
    dt: float,
    spawn_places: tuple[str, ...],
    spawn_enabled: dict[str, bool],
    spawn_timers: dict[str, float],
    places: dict,
    out_cars: list[cars.Car],
    origin_spawn_counts: dict[str, int] | None = None,
    lane_spawn_counts: dict[tuple[str, int], int] | None = None,
    origin_spawn_balance_coeff: float = 0.0,
    out_lane_balance_coeff: float = 0.0,
) -> None:
    """Advance spawn timers and append spawned cars using eligibility + probabilistic balancing."""
    pending: dict[str, int] = {}
    intervals: dict[str, float] = {}

    for place in spawn_places:
        if not spawn_enabled.get(place, True):
            continue
        config = places.get(place)
        spawn_interval = config.spawn_interval if config else 2.0
        intervals[place] = max(SPAWN_INTERVAL_MIN, float(spawn_interval))
        spawn_timers[place] += dt
        ready = int(spawn_timers[place] // intervals[place])
        if ready > 0:
            pending[place] = ready

    total_slots = sum(pending.values())
    for _ in range(total_slots):
        eligible = [p for p, n in pending.items() if n > 0]
        if not eligible:
            break
        if origin_spawn_counts and origin_spawn_balance_coeff > 0.0:
            max_count = max(origin_spawn_counts.get(p, 0) for p in eligible)
            weights = [
                1.0 + origin_spawn_balance_coeff * (max_count - origin_spawn_counts.get(p, 0))
                for p in eligible
            ]
            place = random.choices(eligible, weights=weights, k=1)[0]
        else:
            place = random.choice(eligible)

        interval = intervals[place] + random.uniform(-SPAWN_JITTER, SPAWN_JITTER)
        interval = max(SPAWN_INTERVAL_MIN, interval)
        spawn_timers[place] -= interval
        pending[place] -= 1

        attract_weights = {
            p: (places[p].attract_weight if p in places else 1.0)
            for p in places
            if p != place
        }
        car = cars.spawn_car(
            place,
            attract_weights=attract_weights,
            lane_usage_counts=lane_spawn_counts,
            out_lane_balance_coeff=out_lane_balance_coeff,
            occupancy=out_cars,
        )
        if car is None:
            spawn_timers[place] += interval
            continue
        out_cars.append(car)
        if origin_spawn_counts is not None:
            origin_spawn_counts[place] = origin_spawn_counts.get(place, 0) + 1
        if lane_spawn_counts is not None:
            key = (place, int(car.lane_index))
            lane_spawn_counts[key] = lane_spawn_counts.get(key, 0) + 1
