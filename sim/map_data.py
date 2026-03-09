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


def _default_map() -> dict:
    # Consistent 4x4 intersection; all geometry derived from intersection_size.
    place_size = 5
    intersection_size = 4
    west_arm_width = 16
    housing_road_length = 12
    office_road_length = 9
    park_road_length = 6
    shopping_road_length = 15

    grid_w = 15 + west_arm_width
    grid_h = place_size + housing_road_length + intersection_size + office_road_length + place_size
    inter_y_lo = place_size + housing_road_length
    inter_y_hi = inter_y_lo + intersection_size
    inter_x_lo = 16
    inter_x_hi = inter_x_lo + intersection_size

    # Centered lane tracks from intersection bounds (no hard-coded directional offsets)
    ns_x_lo, ns_x_hi = _centered_tracks(inter_x_lo, inter_x_hi)
    ew_y_lo, ew_y_hi = _centered_tracks(inter_y_lo, inter_y_hi)
    northbound_x = ns_x_hi
    southbound_x = ns_x_lo
    park_inbound_y = ew_y_hi
    park_outbound_y = ew_y_lo
    shopping_inbound_y = ew_y_lo
    shopping_outbound_y = ew_y_hi

    lanes = [
        [(northbound_x, place_size + i) for i in range(housing_road_length)],
        [(northbound_x, inter_y_hi + i) for i in range(office_road_length)],
        [(southbound_x, place_size + housing_road_length + intersection_size + office_road_length - 1 - i) for i in range(office_road_length)],
        [(southbound_x, inter_y_lo - 1 - i) for i in range(housing_road_length)],
        [(4 + west_arm_width + (park_road_length - 1 - i), park_inbound_y) for i in range(park_road_length)],
        [(4 + west_arm_width + i, park_outbound_y) for i in range(park_road_length)],
        [(3 + i, shopping_inbound_y) for i in range(shopping_road_length)],
        [(3 + (shopping_road_length - 1 - i), shopping_outbound_y) for i in range(shopping_road_length)],
    ]

    intersection_cells = [(x, y) for x in range(inter_x_lo, inter_x_hi) for y in range(inter_y_lo, inter_y_hi)]
    cx = (inter_x_lo + inter_x_hi - 1) / 2
    cy = (inter_y_lo + inter_y_hi - 1) / 2
    intersection_slots = [
        (int(cx), inter_y_lo),
        (int(cx) + 1, inter_y_hi - 1),
        (inter_x_hi - 1, int(cy)),
        (inter_x_lo, int(cy) + 1),
    ]
    place_rects = {
        "Housing": {"x": 17, "y": 0, "w": 5, "h": 5},
        "Office": {"x": 17, "y": grid_h - 5, "w": 5, "h": 5},
        "Park": {"x": 26, "y": 15, "w": 5, "h": 5},
        "Shopping": {"x": 0, "y": 15, "w": 5, "h": 5},
    }
    return {
        "grid": {"width": grid_w, "height": grid_h},
        "intersection": {"cells": intersection_cells, "slots": intersection_slots},
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
    merged["place_rects"] = {**default["place_rects"], **loaded.get("place_rects", {})}
    if "lanes" not in loaded:
        merged["lanes"] = default["lanes"]
    return merged


MAP_DATA = load_map_data()
