"""
Serializable map data with optional JSON override.
"""
from __future__ import annotations

import json
from pathlib import Path


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


def build_lanes_from_positions(
    intersection: dict,
    place_rects: dict[str, dict],
) -> tuple[list[list[tuple[int, int]]], int, int]:
    """
    Derive lane cells and grid size from intersection and place positions.
    Lanes connect each place's road edge to the intersection approach edge.
    Returns (lanes, grid_w, grid_h).
    """
    x_lo, x_hi, y_lo, y_hi = _intersection_bounds(intersection)
    ns_x_lo, ns_x_hi = _centered_tracks(x_lo, x_hi)
    ew_y_lo, ew_y_hi = _centered_tracks(y_lo, y_hi)

    def rect(place: str) -> tuple[int, int, int, int]:
        r = place_rects.get(place, {})
        return (
            int(r.get("x", 0)),
            int(r.get("y", 0)),
            int(r.get("w", 0)),
            int(r.get("h", 0)),
        )

    lanes: list[list[tuple[int, int]]] = []

    # Housing (S): lane 0 in (place→inter), lane 3 out (inter→place)
    hx, hy, hw, hh = rect("Housing")
    h_north = hy + hh  # north edge of rect
    # Lane 0: (nx, h_north) to (nx, y_lo - 1), increasing y
    lane0 = [(ns_x_hi, y) for y in range(h_north, y_lo)]
    lanes.append(lane0 if lane0 else [(ns_x_hi, h_north)])
    # Lane 1: Office outbound (inter→place, northbound)
    ox, oy, ow, oh = rect("Office")
    o_south = oy - 1  # south edge (row just south of rect)
    lane1 = [(ns_x_hi, y) for y in range(y_hi, o_south + 1)]
    lanes.append(lane1 if lane1 else [(ns_x_hi, y_hi)])
    # Lane 2: Office inbound (place→inter, southbound)
    lane2 = [(ns_x_lo, y) for y in range(o_south, y_hi - 1, -1)]
    lanes.append(lane2 if lane2 else [(ns_x_lo, o_south)])
    # Lane 3: Housing outbound (inter→place, southbound)
    lane3 = [(ns_x_lo, y) for y in range(y_lo - 1, h_north - 1, -1)]
    lanes.append(lane3 if lane3 else [(ns_x_lo, y_lo - 1)])

    # Park (E): lane 4 in, lane 5 out
    px, py, pw, ph = rect("Park")
    p_west = px - 1  # west edge
    # Lane 4: (p_west, py) to (x_hi, py), decreasing x
    lane4 = [(x, ew_y_hi) for x in range(p_west, x_hi - 1, -1)]
    lanes.append(lane4 if lane4 else [(p_west, ew_y_hi)])
    # Lane 5: (x_hi, py) to (p_west, py), increasing x
    lane5 = [(x, ew_y_lo) for x in range(x_hi, p_west + 1)]
    lanes.append(lane5 if lane5 else [(x_hi, ew_y_lo)])

    # Shopping (W): lane 6 in, lane 7 out
    sx, sy, sw, sh = rect("Shopping")
    s_east = sx + sw  # east edge
    # Lane 6: (s_east, py) to (x_lo - 1, py), increasing x
    lane6 = [(x, ew_y_lo) for x in range(s_east, x_lo)]
    lanes.append(lane6 if lane6 else [(s_east, ew_y_lo)])
    # Lane 7: (x_lo - 1, py) to (s_east, py), decreasing x
    lane7 = [(x, ew_y_hi) for x in range(x_lo - 1, s_east - 1, -1)]
    lanes.append(lane7 if lane7 else [(x_lo - 1, ew_y_hi)])

    # Grid size: bounding box of all geometry
    all_x: list[int] = []
    all_y: list[int] = []
    for lane in lanes:
        for cx, cy in lane:
            all_x.append(cx)
            all_y.append(cy)
    for r in place_rects.values():
        rx, ry = int(r.get("x", 0)), int(r.get("y", 0))
        rw, rh = int(r.get("w", 0)), int(r.get("h", 0))
        all_x.extend([rx, rx + rw])
        all_y.extend([ry, ry + rh])
    all_x.extend([x_lo, x_hi - 1])
    all_y.extend([y_lo, y_hi - 1])
    grid_w = max(all_x) + 1 if all_x else 32
    grid_h = max(all_y) + 1 if all_y else 36

    return (lanes, grid_w, grid_h)


# Main intersection center (fixed). Used when rebuilding with different sizes.
DEFAULT_MAIN_CENTER = (18, 24)


def bounds_from_center(center_x: float, center_y: float, size: int) -> tuple[int, int, int, int]:
    """Return (x_lo, x_hi, y_lo, y_hi) for an intersection of given size centered at (cx, cy)."""
    half = size // 2
    x_lo = int(center_x) - half
    y_lo = int(center_y) - half
    return (x_lo, x_lo + size, y_lo, y_lo + size)


def intersection_dict_from_bounds(x_lo: int, x_hi: int, y_lo: int, y_hi: int) -> dict:
    """Build intersection dict for build_lanes_from_positions. Includes cells and slots."""
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


def build_housing_park_route(
    place_rects: dict[str, dict],
    size: int = 4,
) -> tuple[list[list[tuple[int, int]]], dict]:
    """
    Build Housing–Park direct route from place positions.
    Junction and lane tracks derived from Housing and Park rects; RHT alignment.
    size: intersection cell count (even, 2–12). Center stays fixed.
    Returns (hp_lanes, hp_intersection).
    """
    def rect(place: str) -> tuple[int, int, int, int]:
        r = place_rects.get(place, {})
        return (
            int(r.get("x", 0)), int(r.get("y", 0)),
            int(r.get("w", 0)), int(r.get("h", 0)),
        )

    hx, hy, hw, hh = rect("Housing")
    px, py, pw, ph = rect("Park")

    h_east = hx + hw
    h_east_center_y = hy + hh // 2
    p_south = py - 1
    p_south_center_x = px + pw // 2

    center_x, center_y = p_south_center_x, h_east_center_y
    hp_x_lo, hp_x_hi, hp_y_lo, hp_y_hi = bounds_from_center(center_x, center_y, size)

    hp_cells = [(x, y) for x in range(hp_x_lo, hp_x_hi) for y in range(hp_y_lo, hp_y_hi)]
    cx = (hp_x_lo + hp_x_hi - 1) / 2
    hp_slots = [(int(cx), hp_y_lo), (int(cx), hp_y_hi - 1)]
    hp_intersection = {"cells": hp_cells, "slots": hp_slots}

    hp_ns_x_lo, hp_ns_x_hi = _centered_tracks(hp_x_lo, hp_x_hi)
    hp_ew_y_lo, hp_ew_y_hi = _centered_tracks(hp_y_lo, hp_y_hi)

    # E–W arm (Housing): RHT = eastbound on right (south/lower y)
    lane8 = [(x, hp_ew_y_lo) for x in range(h_east, hp_x_lo)]
    lane11 = [(x, hp_ew_y_hi) for x in range(hp_x_lo - 1, h_east - 1, -1)]

    # N–S arm (Park): RHT = northbound on right (east/higher x)
    # Extend to p_south (row just south of Park) so road connects to Park edge
    park_approach_y = p_south
    lane9 = [(hp_ns_x_hi, y) for y in range(hp_y_hi, park_approach_y + 1)]
    lane10 = [(hp_ns_x_lo, y) for y in range(park_approach_y, hp_y_hi - 1, -1)]

    hp_lanes = [lane8, lane9, lane10, lane11]
    return (hp_lanes, hp_intersection)


def _default_map() -> dict:
    # Intersection and place positions are the source of truth; lanes are derived.
    intersection_size = 4

    main_cx, main_cy = get_main_intersection_center()
    x_lo, x_hi, y_lo, y_hi = bounds_from_center(main_cx, main_cy, intersection_size)
    intersection = intersection_dict_from_bounds(x_lo, x_hi, y_lo, y_hi)

    # Place rects: positions chosen so lane lengths are ~17 (S), ~14 (N), ~10 (E), ~11 (W)
    place_rects = {
        "Housing": {"x": 17, "y": 0, "w": 5, "h": 5},
        "Office": {"x": 17, "y": 41, "w": 5, "h": 5},
        "Park": {"x": 31, "y": 22, "w": 5, "h": 5},
        "Shopping": {"x": 0, "y": 22, "w": 5, "h": 5},
    }

    lanes, grid_w, grid_h = build_lanes_from_positions(intersection, place_rects)
    hp_lanes, hp_intersection = build_housing_park_route(place_rects)
    lanes = lanes + hp_lanes

    # Extend grid to include HP route
    for lane in hp_lanes:
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
        lanes, grid_w, grid_h = build_lanes_from_positions(merged["intersection"], merged["place_rects"])
        hp_lanes, hp_intersection = build_housing_park_route(merged["place_rects"])
        merged["lanes"] = lanes + hp_lanes
        merged["hp_intersection"] = hp_intersection
        for lane in hp_lanes:
            for cx, cy in lane:
                grid_w = max(grid_w, cx + 1)
                grid_h = max(grid_h, cy + 1)
        for cell in hp_intersection.get("cells", []):
            grid_w = max(grid_w, cell[0] + 1)
            grid_h = max(grid_h, cell[1] + 1)
        merged["grid"] = {"width": grid_w, "height": grid_h, **loaded.get("grid", {})}
    return merged


MAP_DATA = load_map_data()
