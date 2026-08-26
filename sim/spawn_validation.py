"""
Seeded smoke validation for spawn balance behavior.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict

from sim.game import GameState
from sim.spawner import update_spawns
from sim import world


def run_seeded_spawn_validation(seed: int = 12345, steps: int = 20000, dt: float = 0.1) -> dict:
    """
    Run seeded spawn simulation and return summary metrics.

    Checks:
    - spawned car lane traffic_in always matches origin
    - origin counts are near-even (for equal intervals)
    - per-origin lane usage stays reasonably balanced
    """
    random.seed(seed)
    game = GameState()
    game.rebuild_world_from_config()

    origin_counts: Counter[str] = Counter()
    lane_counts: dict[str, Counter[int]] = defaultdict(Counter)
    mismatched_origin_lane = 0
    spawned = 0

    for _ in range(steps):
        new_cars = []
        update_spawns(
            dt,
            game.spawn_places,
            game.spawn_enabled,
            game.spawn_timers,
            game.places,
            new_cars,
            origin_spawn_counts=game.origin_spawn_counts,
            lane_spawn_counts=game.lane_spawn_counts,
            origin_spawn_balance_coeff=game.origin_spawn_balance_coeff,
            out_lane_balance_coeff=game.out_lane_balance_coeff,
        )
        for car in new_cars:
            spawned += 1
            origin_counts[car.origin] += 1
            lane_counts[car.origin][car.lane_index] += 1
            if world.lane_traffic_in(car.lane_index) != car.origin:
                mismatched_origin_lane += 1

    values = [origin_counts.get(p, 0) for p in game.spawn_places]
    spread = (max(values) - min(values)) if values else 0
    expected = (sum(values) / len(values)) if values else 0.0
    relative_spread = (spread / expected) if expected > 0 else 0.0

    lane_spreads: dict[str, int] = {}
    for p in game.spawn_places:
        c = lane_counts.get(p, Counter())
        if not c:
            lane_spreads[p] = 0
            continue
        lane_spreads[p] = max(c.values()) - min(c.values())

    return {
        "spawned_total": spawned,
        "origin_counts": dict(origin_counts),
        "origin_relative_spread": relative_spread,
        "lane_count_spread_by_origin": lane_spreads,
        "mismatched_origin_lane": mismatched_origin_lane,
    }


if __name__ == "__main__":
    result = run_seeded_spawn_validation()
    print(result)
