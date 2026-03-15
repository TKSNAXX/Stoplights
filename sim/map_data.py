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


def _apply_lane_offset(
    lanes: list[list[tuple[int, int]]],
    lane_configs: dict[int, "LaneConfig"] | None,
    base_index: int = 0,
) -> list[list[tuple[int, int]]]:
    """Apply offset_x, offset_y from lane_configs to each lane's cells. base_index added to lane index."""
    if not lane_configs:
        return lanes
    result: list[list[tuple[int, int]]] = []
    for i, lane in enumerate(lanes):
        cfg = lane_configs.get(base_index + i)
        dx = cfg.offset_x if cfg else 0
        dy = cfg.offset_y if cfg else 0
        if dx == 0 and dy == 0:
            result.append(lane)
        else:
            result.append([(x + dx, y + dy) for x, y in lane])
    return result


# Canonical (origin, destination) for each lane index. Used to derive direction and validate config.
LANE_ROUTES: list[tuple[str, str]] = [
    ("Housing", "main"),
    ("main", "Office"),
    ("Office", "main"),
    ("main", "Housing"),
    ("Park", "main"),
    ("main", "Park"),
    ("Shopping", "main"),
    ("main", "Shopping"),
    ("Housing", "bypass"),
    ("bypass", "Park"),
    ("Park", "bypass"),
    ("bypass", "Housing"),
]


def build_lanes_from_config(
    place_rects: dict[str, dict],
    main_intersection: dict,
    bypass_center: tuple[float, float],
    bypass_size: int,
    lane_configs: dict[int, "LaneConfig"],
) -> tuple[list[list[tuple[int, int]]], dict]:
    """
    Build all lanes from place_rects and intersection geometry. Geometry is derived from
    lane configs' origin/destination; direction and natural center come from those.
    Falls back to canonical routes for indices 0-11 when config origin/dest invalid.
    Returns (lanes, hp_intersection).
    """
    main_lanes, grid_w, grid_h = build_lanes_from_positions(
        main_intersection, place_rects, lane_configs=lane_configs
    )
    hp_lanes, hp_intersection = build_housing_park_route(
        place_rects, bypass_center, size=bypass_size, lane_configs=lane_configs
    )
    return main_lanes + hp_lanes, hp_intersection


def build_lanes_from_positions(
    intersection: dict,
    place_rects: dict[str, dict],
    lane_configs: dict[int, "LaneConfig"] | None = None,
) -> tuple[list[list[tuple[int, int]]], int, int]:
    """
    Derive lane cells and grid size from intersection and place positions.
    Lanes connect each place's road edge to the intersection approach edge.
    When lane_configs is provided, applies offset_x/offset_y to each lane.
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

    lanes = _apply_lane_offset(lanes, lane_configs, base_index=0)
    return (lanes, grid_w, grid_h)


# Main intersection center (fixed). Used when rebuilding with different sizes.
# Map scaled 2x: default layout doubled.
DEFAULT_MAIN_CENTER = (36, 48)


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
    bypass_center: tuple[float, float],
    size: int = 4,
    lane_configs: dict[int, "LaneConfig"] | None = None,
) -> tuple[list[list[tuple[int, int]]], dict]:
    """
    Build Housing–Park direct route from place positions and explicit bypass center.
    Junction at bypass_center; lane tracks connect to Housing and Park rects. RHT alignment.
    When lane_configs is provided, applies offset_x/offset_y to lanes 8-11.
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
    p_south = py - 1

    center_x, center_y = bypass_center
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
    hp_lanes = _apply_lane_offset(hp_lanes, lane_configs, base_index=8)
    return (hp_lanes, hp_intersection)


def _default_map() -> dict:
    # Intersection and place positions are the source of truth; lanes are derived.
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

    lanes, grid_w, grid_h = build_lanes_from_positions(intersection, place_rects)
    bypass_center = get_bypass_intersection_center(place_rects)
    hp_lanes, hp_intersection = build_housing_park_route(place_rects, bypass_center)
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
        bypass_center = get_bypass_intersection_center(merged["place_rects"])
        hp_lanes, hp_intersection = build_housing_park_route(merged["place_rects"], bypass_center)
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
