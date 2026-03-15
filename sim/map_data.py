"""
Serializable map data with optional JSON override.
"""
from __future__ import annotations

import json
from pathlib import Path
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
    Convert center-based place geometry to {x, y, w, h} place_rects for build_lanes.
    Bounds: [cx - w//2, cx + w//2), [cy - l//2, cy + l//2).
    """
    from sim import places
    result: dict[str, dict] = {}
    for name, g in place_geometry.items():
        w = max(places.PLACE_SIZE_MIN, min(places.PLACE_SIZE_MAX, g.width))
        l = max(places.PLACE_SIZE_MIN, min(places.PLACE_SIZE_MAX, g.length))
        half_w = w // 2
        half_l = l // 2
        x = g.center_x - half_w
        y = g.center_y - half_l
        result[name] = {"x": x, "y": y, "w": w, "h": l}
    return result


def _centered_tracks(lo: int, hi: int) -> tuple[int, int]:
    """
    Return (track_lo, track_hi) for two adjacent lane tracks centered in [lo, hi).
    For even size: tracks straddle midpoint; for odd: symmetric around midpoint.
    """
    center = (lo + hi - 1) / 2
    track_lo = int(center - 0.5)
    track_hi = int(center + 0.5)
    return (track_lo, track_hi)


def _intersection_bounds(intersection: dict) -> tuple[int, int, int, int]:
    """Return (x_lo, x_hi, y_lo, y_hi) from intersection cells or explicit bounds."""
    if "x_lo" in intersection:
        return (
            int(intersection["x_lo"]),
            int(intersection["x_hi"]),
            int(intersection["y_lo"]),
            int(intersection["y_hi"]),
        )
    cells = intersection.get("cells", [])
    if not cells:
        return (0, 0, 0, 0)
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    return (min(xs), max(xs) + 1, min(ys), max(ys) + 1)


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
    main_intersection: dict,
    hp_intersection: dict,
    extra_intersection_bounds: dict[str, tuple[int, int, int, int]] | None = None,
) -> str | None:
    """Return place name / intersection key if this cell belongs to one, else None."""
    for name, rect in place_rects.items():
        x = int(rect.get("x", 0))
        y = int(rect.get("y", 0))
        w = int(rect.get("w", 0))
        h = int(rect.get("h", 0))
        if x <= gx < x + w and y <= gy < y + h:
            return name
    if (gx, gy) in set(main_intersection.get("cells", [])):
        return "main"
    if (gx, gy) in set(hp_intersection.get("cells", [])):
        return "bypass"
    if extra_intersection_bounds:
        for key, (x_lo, x_hi, y_lo, y_hi) in extra_intersection_bounds.items():
            if key in ("main", "bypass"):
                continue
            if x_lo <= gx < x_hi and y_lo <= gy < y_hi:
                return key
    return None


def derive_traffic(
    lane_idx: int,
    start: tuple[int, int],
    end: tuple[int, int],
    place_rects: dict[str, dict],
    main_intersection: dict,
    hp_intersection: dict,
    extra_intersection_bounds: dict[str, tuple[int, int, int, int]] | None = None,
) -> tuple[str, str, str]:
    """Return (direction, traffic_in, traffic_out) derived from endpoints and adjacency."""
    direction = _direction_from_tiles(start, end)
    if not direction:
        return ("", "", "")
    dx, dy = _offset_for_direction(direction)
    sx, sy = start
    ex, ey = end
    in_cell = (sx - dx, sy - dy)
    out_cell = (ex + dx, ey + dy)
    traffic_in = object_at_cell(in_cell[0], in_cell[1], place_rects, main_intersection, hp_intersection, extra_intersection_bounds) or ""
    traffic_out = object_at_cell(out_cell[0], out_cell[1], place_rects, main_intersection, hp_intersection, extra_intersection_bounds) or ""
    return (direction, traffic_in, traffic_out)


def _build_hp_intersection(bypass_center: tuple[float, float], size: int) -> dict:
    hp_x_lo, hp_x_hi, hp_y_lo, hp_y_hi = bounds_from_center(bypass_center[0], bypass_center[1], size)
    hp_cells = [(x, y) for x in range(hp_x_lo, hp_x_hi) for y in range(hp_y_lo, hp_y_hi)]
    cx = (hp_x_lo + hp_x_hi - 1) / 2
    hp_slots = [(int(cx), hp_y_lo), (int(cx), hp_y_hi - 1)]
    return {
        "x_lo": hp_x_lo,
        "x_hi": hp_x_hi,
        "y_lo": hp_y_lo,
        "y_hi": hp_y_hi,
        "cells": hp_cells,
        "slots": hp_slots,
    }


def derive_default_start_end(
    lane_idx: int,
    place_rects: dict[str, dict],
    main_intersection: dict,
    hp_intersection: dict,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Derive the default start/end endpoints from legacy base-lane geometry."""
    x_lo, x_hi, y_lo, y_hi = _intersection_bounds(main_intersection)
    ns_x_lo, ns_x_hi = _centered_tracks(x_lo, x_hi)
    ew_y_lo, ew_y_hi = _centered_tracks(y_lo, y_hi)

    def rect(place: str) -> tuple[int, int, int, int]:
        r = place_rects.get(place, {})
        return (int(r.get("x", 0)), int(r.get("y", 0)), int(r.get("w", 0)), int(r.get("h", 0)))

    hx, hy, hw, hh = rect("Housing")
    ox, oy, ow, oh = rect("Office")
    px, py, pw, ph = rect("Park")
    sx, sy, sw, sh = rect("Shopping")
    h_north = hy + hh
    o_south = oy - 1
    p_west = px - 1
    s_east = sx + sw

    hp_x_lo, hp_x_hi, hp_y_lo, hp_y_hi = _intersection_bounds(hp_intersection)
    hp_ns_x_lo, hp_ns_x_hi = _centered_tracks(hp_x_lo, hp_x_hi)
    hp_ew_y_lo, hp_ew_y_hi = _centered_tracks(hp_y_lo, hp_y_hi)
    p_south = py - 1

    defaults: list[tuple[tuple[int, int], tuple[int, int]]] = [
        ((ns_x_hi, h_north), (ns_x_hi, y_lo - 1)),
        ((ns_x_hi, y_hi), (ns_x_hi, o_south)),
        ((ns_x_lo, o_south), (ns_x_lo, y_hi)),
        ((ns_x_lo, y_lo - 1), (ns_x_lo, h_north)),
        ((p_west, ew_y_hi), (x_hi, ew_y_hi)),
        ((x_hi, ew_y_lo), (p_west, ew_y_lo)),
        ((s_east, ew_y_lo), (x_lo - 1, ew_y_lo)),
        ((x_lo - 1, ew_y_hi), (s_east, ew_y_hi)),
        ((h_east := hx + hw, hp_ew_y_lo), (hp_x_lo - 1, hp_ew_y_lo)),
        ((hp_ns_x_hi, hp_y_hi), (hp_ns_x_hi, p_south)),
        ((hp_ns_x_lo, p_south), (hp_ns_x_lo, hp_y_hi)),
        ((hp_x_lo - 1, hp_ew_y_hi), (h_east, hp_ew_y_hi)),
    ]
    if 0 <= lane_idx < len(defaults):
        return defaults[lane_idx]
    return ((0, 0), (0, 0))


def build_lanes_from_config(
    place_rects: dict[str, dict],
    main_intersection: dict,
    bypass_center: tuple[float, float],
    bypass_size: int,
    lane_configs: dict[int, "LaneConfig"],
    extra_intersection_bounds: dict[str, tuple[int, int, int, int]] | None = None,
) -> tuple[list[list[tuple[int, int]]], dict, list[tuple[str, str, str]]]:
    """Build base lanes from explicit start/end tiles. Returns (lanes, hp_intersection, lane_meta)."""
    hp_intersection = _build_hp_intersection(bypass_center, bypass_size)
    lanes: list[list[tuple[int, int]]] = []
    lane_meta: list[tuple[str, str, str]] = []
    for lane_idx in range(12):
        cfg = lane_configs.get(lane_idx)
        if cfg is None:
            start, end = derive_default_start_end(lane_idx, place_rects, main_intersection, hp_intersection)
        else:
            start = tuple(int(v) for v in cfg.start_tile)
            end = tuple(int(v) for v in cfg.end_tile)
            if not build_lane_cells(start, end):
                start, end = derive_default_start_end(lane_idx, place_rects, main_intersection, hp_intersection)
                cfg.start_tile = start
                cfg.end_tile = end
        cells = build_lane_cells(start, end)
        if not cells:
            start, end = derive_default_start_end(lane_idx, place_rects, main_intersection, hp_intersection)
            cells = build_lane_cells(start, end)
        lanes.append(cells)
        lane_meta.append(
            derive_traffic(
                lane_idx,
                start,
                end,
                place_rects,
                main_intersection,
                hp_intersection,
                extra_intersection_bounds,
            )
        )
    return lanes, hp_intersection, lane_meta


# Main intersection center (fixed). Map scaled 2x: default layout doubled.
DEFAULT_MAIN_CENTER = (36, 48)


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
        "x_lo": x_lo, "x_hi": x_hi,
        "y_lo": y_lo, "y_hi": y_hi,
        "cells": cells,
        "slots": slots,
    }


def get_main_intersection_center() -> tuple[float, float]:
    """Return the fixed main intersection center. Comes from default map layout."""
    return (float(DEFAULT_MAIN_CENTER[0]), float(DEFAULT_MAIN_CENTER[1]))


def get_bypass_intersection_center(place_rects: dict[str, dict]) -> tuple[float, float]:
    """Return bypass junction center from Housing and Park place positions."""
    def rect(place: str) -> tuple[int, int, int, int]:
        r = place_rects.get(place, {})
        return (
            int(r.get("x", 0)), int(r.get("y", 0)),
            int(r.get("w", 0)), int(r.get("h", 0)),
        )

    hx, hy, hw, hh = rect("Housing")
    px, py, pw, ph = rect("Park")

    h_east_center_y = hy + hh // 2
    p_south_center_x = px + pw // 2
    return (float(p_south_center_x), float(h_east_center_y))


def _default_map() -> dict:
    intersection_size = 4

    main_cx, main_cy = get_main_intersection_center()
    x_lo, x_hi, y_lo, y_hi = bounds_from_center(main_cx, main_cy, intersection_size)
    intersection = intersection_dict_from_bounds(x_lo, x_hi, y_lo, y_hi)

    # Place rects: 2x scale - positions doubled, place size 5x5 unchanged
    place_rects = {
        "Housing": {"x": 34, "y": 0, "w": 5, "h": 5},
        "Office": {"x": 34, "y": 82, "w": 5, "h": 5},
        "Park": {"x": 62, "y": 44, "w": 5, "h": 5},
        "Shopping": {"x": 0, "y": 44, "w": 5, "h": 5},
    }

    bypass_center = get_bypass_intersection_center(place_rects)
    lanes, hp_intersection, _lane_meta = build_lanes_from_config(
        place_rects, intersection, bypass_center, 4, {}
    )
    grid_w, grid_h = 32, 36
    for lane in lanes:
        for cx, cy in lane:
            grid_w = max(grid_w, cx + 1)
            grid_h = max(grid_h, cy + 1)
    for cell in hp_intersection["cells"]:
        grid_w = max(grid_w, cell[0] + 1)
        grid_h = max(grid_h, cell[1] + 1)

    return {
        "grid": {"width": grid_w, "height": grid_h},
        "intersection": intersection,
        "hp_intersection": hp_intersection,
        "lanes": lanes,
        "place_rects": place_rects,
    }


def load_map_data() -> dict:
    """Load map from assets/map.json when available, else use built-in defaults."""
    default = _default_map()
    map_path = Path(__file__).resolve().parent.parent / "assets" / "map.json"
    if not map_path.exists():
        return default
    try:
        loaded = json.loads(map_path.read_text(encoding="utf-8"))
    except Exception:
        return default

    # Merge with defaults so partial files are accepted.
    merged = dict(default)
    merged.update(loaded)
    merged["grid"] = {**default["grid"], **loaded.get("grid", {})}
    merged["intersection"] = {**default["intersection"], **loaded.get("intersection", {})}
    merged["hp_intersection"] = merged.get("hp_intersection") or default.get("hp_intersection", {})
    merged["place_rects"] = {**default["place_rects"], **loaded.get("place_rects", {})}
    if "lanes" not in loaded:
        place_rects = merged["place_rects"]
        intersection = merged["intersection"]
        bypass_center = get_bypass_intersection_center(place_rects)
        lanes, hp_intersection, _lane_meta = build_lanes_from_config(
            place_rects, intersection, bypass_center, 4, {}
        )
        merged["lanes"] = lanes
        merged["hp_intersection"] = hp_intersection

        grid_w, grid_h = 32, 36
        for lane in lanes:
            for cx, cy in lane:
                grid_w = max(grid_w, cx + 1)
                grid_h = max(grid_h, cy + 1)
        for cell in hp_intersection.get("cells", []):
            grid_w = max(grid_w, cell[0] + 1)
            grid_h = max(grid_h, cell[1] + 1)
        merged["grid"] = {"width": grid_w, "height": grid_h, **loaded.get("grid", {})}
    return merged


MAP_DATA = load_map_data()
