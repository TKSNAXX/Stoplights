"""
Serializable map data with optional JSON override.
"""
from __future__ import annotations

import json
from pathlib import Path


def _default_map() -> dict:
    # Preserve current geometry as the default built-in map.
    place_size = 5
    intersection_size = 2
    west_arm_width = 16
    housing_road_length = 12
    office_road_length = 9
    park_road_length = 6
    shopping_road_length = 15

    grid_w = 15 + west_arm_width
    grid_h = place_size + housing_road_length + intersection_size + office_road_length + place_size
    inter_y_lo = place_size + housing_road_length
    inter_y_hi = inter_y_lo + intersection_size
    northbound_x = 3 + west_arm_width
    southbound_x = 2 + west_arm_width
    park_inbound_y = inter_y_hi - 1
    park_outbound_y = inter_y_lo
    shopping_inbound_y = inter_y_lo
    shopping_outbound_y = inter_y_hi - 1

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

    intersection_cells = [(x, y) for x in range(17, 20) for y in range(16, 19)]
    intersection_slots = [(18, 16), (18, 18), (19, 17), (17, 17)]
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
