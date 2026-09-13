"""
Intersection overlay kind and tee layout from connected cardinals.

Shared by render (paint) and sim (maneuver labels). Occupancy is unchanged.
"""
from __future__ import annotations

from typing import Literal

from sim import places

Cardinal = Literal["N", "S", "E", "W"]
StraightAxis = Literal["ns", "ew"]

OPPOSITE_CARDINAL: dict[Cardinal, Cardinal] = {"N": "S", "S": "N", "E": "W", "W": "E"}
ALL_CARDINALS: frozenset[Cardinal] = frozenset({"N", "S", "E", "W"})
LEFT_OF: dict[Cardinal, Cardinal] = {"N": "W", "W": "S", "S": "E", "E": "N"}
RIGHT_OF: dict[Cardinal, Cardinal] = {"N": "E", "E": "S", "S": "W", "W": "N"}


def overlay_type_for_sides(active: frozenset[str]) -> str:
    """Overlay kind from connected cardinals."""
    n = len(active)
    if n == 0:
        return places.INTERSECTION_TYPE_NONE
    if n == 1:
        return places.INTERSECTION_TYPE_STRAIGHT
    if n == 2:
        if active in (frozenset({"N", "S"}), frozenset({"E", "W"})):
            return places.INTERSECTION_TYPE_STRAIGHT
        return places.INTERSECTION_TYPE_CORNER
    if n == 3:
        return places.INTERSECTION_TYPE_TEE
    return places.INTERSECTION_TYPE_CROSS


def tee_layout_for_sides(
    active: frozenset[str],
    through_fallback: StraightAxis = "ns",
) -> tuple[StraightAxis, Cardinal]:
    """
    Through axis and stem cardinal for a tee overlay.

    Three active sides: missing face is open (transparent); stem is opposite the
    gap; through is the remaining pair.
    Otherwise: use through_fallback; stem is a perpendicular active side, else S.
    """
    if len(active) == 3:
        missing = next(iter(ALL_CARDINALS - active))
        stem = OPPOSITE_CARDINAL[missing]
        axis: StraightAxis = "ew" if stem in ("N", "S") else "ns"
        return axis, stem
    axis = through_fallback if through_fallback in ("ns", "ew") else "ns"
    perp: frozenset[Cardinal] = frozenset({"E", "W"}) if axis == "ns" else frozenset({"N", "S"})
    for side in ("N", "S", "E", "W"):
        if side in active and side in perp:
            return axis, side
    return axis, "S"
