"""
Civilian-car occupancy indexes: by lane and by intersection.

Derived from GameState.cars; not a second source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Iterator

from sim import world

if TYPE_CHECKING:
    from sim.cars import Car


@dataclass
class Occupancy:
    by_lane: dict[int, list[Car]] = field(default_factory=dict)
    by_intersection: dict[str, list[Car]] = field(default_factory=dict)

    @classmethod
    def from_cars(cls, cars_list: Iterable[Car]) -> Occupancy:
        occ = cls()
        for car in cars_list:
            occ.add(car)
        return occ

    def add(self, car: Car) -> None:
        if getattr(car, "motion_mode", "lane") == "path":
            cell = getattr(car, "intersection_cell", None) or car.current_cell()
            if cell is None:
                return
            for key in world.intersections_at_cell(cell):
                bucket = self.by_intersection.get(key)
                if bucket is None:
                    self.by_intersection[key] = [car]
                else:
                    bucket.append(car)
            return
        lane_idx = getattr(car, "lane_index", None)
        if lane_idx is None:
            return
        bucket = self.by_lane.get(lane_idx)
        if bucket is None:
            self.by_lane[lane_idx] = [car]
        else:
            bucket.append(car)

    def cars_on_lane(self, lane_idx: int) -> list[Car]:
        return self.by_lane.get(lane_idx, [])

    def cars_in_intersection(self, key: str) -> list[Car]:
        return self.by_intersection.get(key, [])

    def iter_path_cars(self) -> Iterator[Car]:
        seen: set[int] = set()
        for bucket in self.by_intersection.values():
            for car in bucket:
                ident = id(car)
                if ident in seen:
                    continue
                seen.add(ident)
                yield car


def occupancy_from(obj) -> Occupancy:
    """Accept Occupancy, a car list, or None."""
    if isinstance(obj, Occupancy):
        return obj
    if obj is None:
        return Occupancy()
    return Occupancy.from_cars(obj)
