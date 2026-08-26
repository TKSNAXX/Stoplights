"""
Geometry helpers for places, intersections, and lanes.

No named default map. Authored scenarios live in assets/maps/ and config.json.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sim.places import LaneConfig, PlaceGeometry


def geometry_from_place_rects(place_rects: dict[str, dict]) -> dict[str, "PlaceGeometry"]:
    """Convert {x, y, w, h} place_rects to center-based PlaceGeometry."""
    from sim import places

    result: dict[str, places.PlaceGeometry] = {}
    for name, r in place_rects.items():
        x = int(r.get("x", 0))
        y = int(r.get("y", 0))
        w = int(r.get("w", 0))
        h = int(r.get("h", 0))
        if w <= 0 or h <= 0:
            continue
        cx = x + w // 2
        cy = y + h // 2
        result[name] = places.PlaceGeometry(center_x=cx, center_y=cy, width=w, length=h)
    return result


def place_rects_from_geometry(place_geometry: dict[str, "PlaceGeometry"]) -> dict[str, dict]:
    """
    Convert center-based place geometry to {x, y, w, h} place_rects.
    Bounds: [cx - w//2, cx + w//2), [cy - l//2, cy + l//2).
    """
    from sim import places

    result: dict[str, dict] = {}
    for name, g in place_geometry.items():
        w = max(places.PLACE_SIZE_MIN, min(places.PLACE_SIZE_MAX, g.width))
        length = max(places.PLACE_SIZE_MIN, min(places.PLACE_SIZE_MAX, g.length))
        half_w = w // 2
        half_l = length // 2
        x = g.center_x - half_w
        y = g.center_y - half_l
        result[name] = {"x": x, "y": y, "w": w, "h": length}
    return result


def bounds_from_center(center_x: float, center_y: float, size: int) -> tuple[int, int, int, int]:
    """Return (x_lo, x_hi, y_lo, y_hi) for an intersection of given size centered at (cx, cy)."""
    half = size // 2
    x_lo = int(center_x) - half
    y_lo = int(center_y) - half
    return (x_lo, x_lo + size, y_lo, y_lo + size)


def intersection_dict_from_bounds(x_lo: int, x_hi: int, y_lo: int, y_hi: int) -> dict:
    """Build intersection dict including cells and lane-transition slots."""
    cells = [(x, y) for x in range(x_lo, x_hi) for y in range(y_lo, y_hi)]
    cx = (x_lo + x_hi - 1) / 2
    cy = (y_lo + y_hi - 1) / 2
    slots = [
        (int(cx), y_lo),
        (int(cx) + 1, y_hi - 1),
        (x_hi - 1, int(cy)),
        (x_lo, int(cy) + 1),
    ]
    return {
        "x_lo": x_lo,
        "x_hi": x_hi,
        "y_lo": y_lo,
        "y_hi": y_hi,
        "cells": cells,
        "slots": slots,
    }


def intersection_from_center(center: tuple[float, float], size: int) -> dict:
    """Build intersection dict from center and even size."""
    size = max(2, min(12, int(size)))
    if size % 2 != 0:
        size = (size // 2) * 2
    x_lo, x_hi, y_lo, y_hi = bounds_from_center(center[0], center[1], size)
    return intersection_dict_from_bounds(x_lo, x_hi, y_lo, y_hi)


def build_lane_cells(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Return all cells from start to end inclusive when orthogonal, else empty."""
    sx, sy = start
    ex, ey = end
    if sx == ex and sy == ey:
        return [(sx, sy)]
    if sx == ex:
        step = 1 if ey >= sy else -1
        return [(sx, y) for y in range(sy, ey + step, step)]
    if sy == ey:
        step = 1 if ex >= sx else -1
        return [(x, sy) for x in range(sx, ex + step, step)]
    return []


def _direction_from_tiles(start: tuple[int, int], end: tuple[int, int]) -> str:
    sx, sy = start
    ex, ey = end
    if sx == ex:
        if ey > sy:
            return "N"
        if ey < sy:
            return "S"
    if sy == ey:
        if ex > sx:
            return "E"
        if ex < sx:
            return "W"
    return ""


def _offset_for_direction(direction: str) -> tuple[int, int]:
    if direction == "N":
        return (0, 1)
    if direction == "S":
        return (0, -1)
    if direction == "E":
        return (1, 0)
    if direction == "W":
        return (-1, 0)
    return (0, 0)


def object_at_cell(
    gx: int,
    gy: int,
    place_rects: dict[str, dict],
    intersection_bounds: dict[str, tuple[int, int, int, int]],
) -> str | None:
    """Return place or intersection id if this cell belongs to one, else None."""
    for name, rect in place_rects.items():
        x = int(rect.get("x", 0))
        y = int(rect.get("y", 0))
        w = int(rect.get("w", 0))
        h = int(rect.get("h", 0))
        if x <= gx < x + w and y <= gy < y + h:
            return name
    for key, (x_lo, x_hi, y_lo, y_hi) in intersection_bounds.items():
        if x_lo <= gx < x_hi and y_lo <= gy < y_hi:
            return key
    return None


def derive_traffic(
    start: tuple[int, int],
    end: tuple[int, int],
    place_rects: dict[str, dict],
    intersection_bounds: dict[str, tuple[int, int, int, int]],
) -> tuple[str, str, str]:
    """Return (direction, traffic_in, traffic_out) from endpoints and adjacency."""
    direction = _direction_from_tiles(start, end)
    if not direction:
        return ("", "", "")
    dx, dy = _offset_for_direction(direction)
    sx, sy = start
    ex, ey = end
    in_cell = (sx - dx, sy - dy)
    out_cell = (ex + dx, ey + dy)
    traffic_in = object_at_cell(in_cell[0], in_cell[1], place_rects, intersection_bounds) or ""
    traffic_out = object_at_cell(out_cell[0], out_cell[1], place_rects, intersection_bounds) or ""
    return (direction, traffic_in, traffic_out)


def next_lane_index(lane_configs: dict) -> int:
    """Return next available lane id: max(keys)+1, or 0 if empty."""
    if not lane_configs:
        return 0
    return max(lane_configs.keys()) + 1


def build_lanes_from_config(
    place_rects: dict[str, dict],
    intersection_bounds: dict[str, tuple[int, int, int, int]],
    lane_configs: dict[int, "LaneConfig"],
) -> tuple[dict[int, list[tuple[int, int]]], dict[int, tuple[str, str, str]]]:
    """
    Build lane cells and meta from explicit start/end tiles.
    Returns (lanes_by_id, meta_by_id) where meta is (direction, traffic_in, traffic_out).
    """
    lanes: dict[int, list[tuple[int, int]]] = {}
    lane_meta: dict[int, tuple[str, str, str]] = {}
    for lane_idx in sorted(lane_configs.keys()):
        cfg = lane_configs[lane_idx]
        start = (int(cfg.start_tile[0]), int(cfg.start_tile[1]))
        end = (int(cfg.end_tile[0]), int(cfg.end_tile[1]))
        cells = build_lane_cells(start, end)
        if not cells:
            cells = [start]
        lanes[lane_idx] = cells
        lane_meta[lane_idx] = derive_traffic(start, end, place_rects, intersection_bounds)
    return lanes, lane_meta
