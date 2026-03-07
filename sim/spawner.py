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
    place_configs: dict,
    out_cars: list[cars.Car],
) -> None:
    """Advance spawn timers and append spawned cars. Uses per-place spawn_interval from place_configs."""
    for place in spawn_places:
        if not spawn_enabled.get(place, True):
            continue
        config = place_configs.get(place)
        spawn_interval = config.spawn_interval if config else 2.0
        spawn_timers[place] += dt
        if spawn_timers[place] < spawn_interval:
            continue
        interval = spawn_interval + random.uniform(-SPAWN_JITTER, SPAWN_JITTER)
        interval = max(SPAWN_INTERVAL_MIN, interval)
        spawn_timers[place] -= interval
        attract_weights = {p: (place_configs[p].attract_weight if p in place_configs else 1.0) for p in place_configs if p != place}
        out_cars.append(cars.spawn_car(place, attract_weights=attract_weights))
