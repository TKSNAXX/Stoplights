"""
Impasse (mutual-red) detection and white override handling.
"""
from __future__ import annotations

from sim import cars
from sim.constants import IMPASSE_DURATION, IMPASSE_SPEED_SCALE, VIS_ZONE_LENGTH_CELLS
from sim.visibility import visibility_zone_band


def apply_impasse(
    dt: float,
    cars_list: list[cars.Car],
    poses: list[tuple[float, float, int] | None],
    id_to_index: dict[int, int],
    nearby_indices,
    half_width: float,
    impasse_timers: dict[tuple[int, int], float],
    impasse_candidates: set[int],
) -> int:
    """
    Update impasse timers/flags and apply white override.

    Returns pair check count for perf stats.
    """
    pair_checks = 0
    # Clear impasse for pairs no longer mutually in-zone
    to_clear: set[tuple[int, int]] = set()
    for i, car in enumerate(cars_list):
        if not getattr(car, "impasse_active", False):
            continue
        pid = getattr(car, "impasse_partner_id", None)
        if pid is None:
            continue
        j = id_to_index.get(pid)
        if j is None or poses[i] is None or poses[j] is None:
            to_clear.add((min(id(car), pid), max(id(car), pid)))
            continue
        gx, gy, di = poses[i]
        ox, oy, _ = poses[j]
        band_ij = visibility_zone_band(gx, gy, di, ox, oy, VIS_ZONE_LENGTH_CELLS, half_width)
        gx2, gy2, di2 = poses[j]
        band_ji = visibility_zone_band(gx2, gy2, di2, poses[i][0], poses[i][1], VIS_ZONE_LENGTH_CELLS, half_width)
        if band_ij != "near" or band_ji != "near":
            to_clear.add((min(id(cars_list[i]), id(cars_list[j])), max(id(cars_list[i]), id(cars_list[j]))))
    for key in to_clear:
        impasse_timers.pop(key, None)
        for car in cars_list:
            if getattr(car, "impasse_active", False) and (
                getattr(car, "impasse_partner_id", None) == key[0] or getattr(car, "impasse_partner_id", None) == key[1]
            ):
                car.impasse_active = False
                car.impasse_partner_id = None

    # Mutual red set: pairs where both cars are red AND mutually near.
    mutual_red: set[tuple[int, int]] = set()
    seen_pairs: set[tuple[int, int]] = set()
    for i, pose in enumerate(poses):
        if i not in impasse_candidates:
            continue
        if pose is None:
            continue
        if getattr(cars_list[i], "visibility_state", "green") != "red":
            continue
        gx, gy, di = pose
        for j in nearby_indices(gx, gy):
            if j <= i:
                continue
            if (i, j) in seen_pairs:
                continue
            seen_pairs.add((i, j))
            if poses[j] is None:
                continue
            if getattr(cars_list[j], "visibility_state", "green") != "red":
                continue
            ox, oy, _ = poses[j]
            band_ij = visibility_zone_band(gx, gy, di, ox, oy, VIS_ZONE_LENGTH_CELLS, half_width)
            gx2, gy2, di2 = poses[j]
            band_ji = visibility_zone_band(gx2, gy2, di2, gx, gy, VIS_ZONE_LENGTH_CELLS, half_width)
            pair_checks += 2
            if band_ij == "near" and band_ji == "near":
                mutual_red.add((min(id(cars_list[i]), id(cars_list[j])), max(id(cars_list[i]), id(cars_list[j]))))

    # Update timers.
    for key in list(impasse_timers.keys()):
        if key not in mutual_red:
            del impasse_timers[key]
    for key in mutual_red:
        impasse_timers[key] = impasse_timers.get(key, 0.0) + dt
        if impasse_timers[key] < IMPASSE_DURATION:
            continue
        id_lo, id_hi = key
        idx_lo, idx_hi = id_to_index.get(id_lo), id_to_index.get(id_hi)
        if idx_lo is not None and idx_hi is not None:
            cars_list[idx_lo].impasse_active = True
            cars_list[idx_lo].impasse_partner_id = id_hi
            cars_list[idx_hi].impasse_active = True
            cars_list[idx_hi].impasse_partner_id = id_lo

    # Apply white override after visibility; police cyan wins.
    for car in cars_list:
        if not getattr(car, "impasse_active", False):
            continue
        if getattr(car, "police_priority_active", False) or getattr(car, "police_hold_until_exit", False):
            continue
        car.visibility_state = "white"
        car.speed_scale = IMPASSE_SPEED_SCALE
    return pair_checks
