"""
Schema-4 scenario load, migrate, and apply.

Authored maps (default.json, config.json) share one shape. The engine never
reconstructs Housing/Office/main from Python constants.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sim import places

if TYPE_CHECKING:
    from sim.game import GameState

SCHEMA_VERSION = 4

# Legacy schema-3 core IDs used only when migrating old saves.
_LEGACY_PROTECTED_PLACES = frozenset({"Housing", "Office", "Park", "Shopping"})
_LEGACY_CORE_INTERSECTIONS = frozenset({"main", "bypass"})
_LEGACY_BASE_LANE_COUNT = 12
_LEGACY_ROUTE_HINTS = [
    ["Housing", "Park", "bypass"],
    ["Park", "Housing", "bypass"],
]


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_map_path() -> Path:
    return project_root() / "assets" / "maps" / "default.json"


def load_json_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def load_default_scenario() -> dict:
    """Load assets/maps/default.json; raise if missing or invalid."""
    data = load_json_file(default_map_path())
    if data is None:
        raise FileNotFoundError(f"Default map not found: {default_map_path()}")
    return migrate_to_schema_4(data)


def clamp_intersection_size(n: int) -> int:
    n = max(places.INTERSECTION_SIZE_MIN, min(places.INTERSECTION_SIZE_MAX, int(n)))
    return n if n % 2 == 0 else (n // 2) * 2


def clamp_color_hue(value: Any) -> int:
    """Hue in degrees, snapped to 10°, wrapped to 0–359. 360 becomes 0."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0
    n = int(v / 10.0 + (0.5 if v >= 0 else -0.5)) * 10
    return n % 360


def clamp_color_sat(value: Any) -> float:
    """Saturation 0–2 (100% = 1.0), snapped to 0.1."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 1.0
    v = max(0.0, min(2.0, v))
    return int(v * 10.0 + 0.5) / 10.0


def migrate_to_schema_4(data: dict) -> dict:
    """
    Normalize any supported save/map dict to schema 4.
    Schema 3 (place_configs + place_geometry + lane_configs + intersection_configs)
    is merged into the unified places/intersections/lanes shape.
    """
    version = int(data.get("schema_version", 3) or 3)
    if version >= 4 and "places" in data and "intersections" in data and "lanes" in data:
        return _normalize_schema_4(data)
    return _migrate_schema_3(data)


def _normalize_schema_4(data: dict) -> dict:
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "places": {},
        "intersections": {},
        "lanes": {},
        "police": [],
        "route_hints": [],
        "spawn_balance": {
            "origin_spawn_balance_coeff": 1.0,
            "out_lane_balance_coeff": 1.0,
        },
        "user_settings": {},
    }
    for key, raw in (data.get("places") or {}).items():
        if not isinstance(raw, dict):
            continue
        out["places"][str(key)] = _normalize_place(raw, str(key))
    for key, raw in (data.get("intersections") or {}).items():
        if not isinstance(raw, dict):
            continue
        out["intersections"][str(key)] = _normalize_intersection(raw)
    for key, raw in (data.get("lanes") or {}).items():
        if not isinstance(raw, dict):
            continue
        try:
            idx = int(key)
        except (TypeError, ValueError):
            continue
        out["lanes"][str(idx)] = _normalize_lane(raw)
    hints = data.get("route_hints")
    if isinstance(hints, list):
        out["route_hints"] = [
            [str(h[0]), str(h[1]), str(h[2])]
            for h in hints
            if isinstance(h, (list, tuple)) and len(h) == 3
        ]
    sb = data.get("spawn_balance")
    if isinstance(sb, dict):
        try:
            out["spawn_balance"]["origin_spawn_balance_coeff"] = max(
                0.0, float(sb.get("origin_spawn_balance_coeff", 1.0))
            )
        except (TypeError, ValueError):
            pass
        try:
            out["spawn_balance"]["out_lane_balance_coeff"] = max(
                0.0, float(sb.get("out_lane_balance_coeff", 1.0))
            )
        except (TypeError, ValueError):
            pass
    us = data.get("user_settings")
    if isinstance(us, dict):
        cleaned = dict(us)
        if "color_hue" in cleaned:
            cleaned["color_hue"] = clamp_color_hue(cleaned["color_hue"])
        if "color_sat" in cleaned:
            cleaned["color_sat"] = clamp_color_sat(cleaned["color_sat"])
        out["user_settings"] = cleaned
    return out


def _normalize_place(raw: dict, place_id: str = "") -> dict:
    w = max(places.PLACE_SIZE_MIN, min(places.PLACE_SIZE_MAX, int(raw.get("width", 5))))
    length = max(places.PLACE_SIZE_MIN, min(places.PLACE_SIZE_MAX, int(raw.get("length", 5))))
    try:
        spawn = max(0.1, float(raw.get("spawn_interval", 2.0)))
    except (TypeError, ValueError):
        spawn = 2.0
    try:
        attract = max(0.01, float(raw.get("attract_weight", 1.0)))
    except (TypeError, ValueError):
        attract = 1.0
    return {
        "center_x": int(raw.get("center_x", 0)),
        "center_y": int(raw.get("center_y", 0)),
        "width": w,
        "length": length,
        "spawn_interval": spawn,
        "attract_weight": attract,
        "protected": bool(raw.get("protected", False)),
        "building_kind": places.clamp_building_kind(raw.get("building_kind"), place_id),
        "building_seed": places.clamp_building_seed(raw.get("building_seed", 0)),
    }


def _normalize_intersection(raw: dict) -> dict:
    return {
        "center_x": int(raw.get("center_x", 36)),
        "center_y": int(raw.get("center_y", 48)),
        "size_cells": clamp_intersection_size(int(raw.get("size_cells", places.INTERSECTION_SIZE_DEFAULT))),
        "protected": bool(raw.get("protected", False)),
    }


def _normalize_lane(raw: dict) -> dict:
    start = raw.get("start_tile", [0, 0])
    end = raw.get("end_tile", [0, 0])
    try:
        sx, sy = int(start[0]), int(start[1])
        ex, ey = int(end[0]), int(end[1])
    except (TypeError, ValueError, IndexError):
        sx = sy = ex = ey = 0
    lane_type = raw.get("lane_type", places.LANE_TYPE_NORMAL)
    if lane_type not in places.LANE_TYPES:
        lane_type = places.LANE_TYPE_NORMAL
    try:
        speed = max(0.1, min(3.0, float(raw.get("speed_limit", 1.0))))
    except (TypeError, ValueError):
        speed = 1.0
    return {
        "start_tile": [sx, sy],
        "end_tile": [ex, ey],
        "speed_limit": speed,
        "lane_type": lane_type,
        "protected": bool(raw.get("protected", False)),
    }


def _migrate_schema_3(data: dict) -> dict:
    places_out: dict[str, dict] = {}
    geometry = data.get("place_geometry") or {}
    configs = data.get("place_configs") or {}
    all_place_ids = set(geometry) | set(configs)
    for key in all_place_ids:
        g = geometry.get(key) if isinstance(geometry.get(key), dict) else {}
        c = configs.get(key) if isinstance(configs.get(key), dict) else {}
        places_out[str(key)] = _normalize_place(
            {
                "center_x": g.get("center_x", 0),
                "center_y": g.get("center_y", 0),
                "width": g.get("width", 5),
                "length": g.get("length", 5),
                "spawn_interval": c.get("spawn_interval", 2.0),
                "attract_weight": c.get("attract_weight", 1.0),
                "protected": str(key) in _LEGACY_PROTECTED_PLACES,
            },
            str(key),
        )

    intersections_out: dict[str, dict] = {}
    for key, raw in (data.get("intersection_configs") or {}).items():
        if not isinstance(raw, dict):
            continue
        intersections_out[str(key)] = _normalize_intersection(
            {
                "center_x": raw.get("center_x", 36),
                "center_y": raw.get("center_y", 48),
                "size_cells": raw.get("size_cells", places.INTERSECTION_SIZE_DEFAULT),
                "protected": str(key) in _LEGACY_CORE_INTERSECTIONS,
            }
        )

    lanes_out: dict[str, dict] = {}
    for key, raw in (data.get("lane_configs") or {}).items():
        if not isinstance(raw, dict):
            continue
        try:
            idx = int(key)
        except (TypeError, ValueError):
            continue
        start = raw.get("start_tile", [0, 0])
        end = raw.get("end_tile", [0, 0])
        # Drop legacy use_template_endpoints sentinel — keep explicit tiles if present.
        if bool(raw.get("use_template_endpoints", False)):
            # Prefer explicit tiles when they exist; otherwise leave zeros (invalid).
            pass
        lanes_out[str(idx)] = _normalize_lane(
            {
                "start_tile": start,
                "end_tile": end,
                "speed_limit": raw.get("speed_limit", 1.0),
                "lane_type": raw.get("lane_type", places.LANE_TYPE_NORMAL),
                "protected": idx < _LEGACY_BASE_LANE_COUNT,
            }
        )

    hints = data.get("route_hints")
    if not isinstance(hints, list) or not hints:
        tmpl = data.get("template") if isinstance(data.get("template"), dict) else {}
        pairs = tmpl.get("route_pairs_via_secondary") if isinstance(tmpl, dict) else None
        secondary = (tmpl.get("secondary_intersection_id") if isinstance(tmpl, dict) else None) or "bypass"
        if isinstance(pairs, list) and pairs:
            hints = [
                [str(p[0]), str(p[1]), str(secondary)]
                for p in pairs
                if isinstance(p, (list, tuple)) and len(p) == 2
            ]
        else:
            hints = copy.deepcopy(_LEGACY_ROUTE_HINTS)

    sb = data.get("spawn_balance") if isinstance(data.get("spawn_balance"), dict) else {}
    us = data.get("user_settings") if isinstance(data.get("user_settings"), dict) else {}

    return _normalize_schema_4(
        {
            "schema_version": SCHEMA_VERSION,
            "places": places_out,
            "intersections": intersections_out,
            "lanes": lanes_out,
            "police": [],
            "route_hints": hints,
            "spawn_balance": sb,
            "user_settings": us,
        }
    )


def scenario_to_game_dicts(scenario: dict) -> tuple[
    dict[str, places.Place],
    dict[str, places.IntersectionConfig],
    dict[int, places.LaneConfig],
    list[dict],
    list[tuple[str, str, str]],
    float,
    float,
]:
    """Convert a schema-4 scenario into runtime config objects."""
    places_by_id: dict[str, places.Place] = {}
    for key, raw in scenario.get("places", {}).items():
        places_by_id[key] = places.Place(
            center_x=int(raw["center_x"]),
            center_y=int(raw["center_y"]),
            width=int(raw["width"]),
            length=int(raw["length"]),
            spawn_interval=float(raw.get("spawn_interval", 2.0)),
            attract_weight=float(raw.get("attract_weight", 1.0)),
            protected=bool(raw.get("protected", False)),
            building_kind=places.clamp_building_kind(raw.get("building_kind"), key),
            building_seed=places.clamp_building_seed(raw.get("building_seed", 0)),
        )

    intersections_by_id: dict[str, places.IntersectionConfig] = {}
    for key, raw in scenario.get("intersections", {}).items():
        intersections_by_id[key] = places.IntersectionConfig(
            size_cells=clamp_intersection_size(int(raw.get("size_cells", 4))),
            center_x=int(raw["center_x"]),
            center_y=int(raw["center_y"]),
            protected=bool(raw.get("protected", False)),
        )

    lanes_by_id: dict[int, places.LaneConfig] = {}
    for key, raw in scenario.get("lanes", {}).items():
        idx = int(key)
        st = raw["start_tile"]
        et = raw["end_tile"]
        lanes_by_id[idx] = places.LaneConfig(
            speed_limit=float(raw.get("speed_limit", 1.0)),
            lane_type=str(raw.get("lane_type", places.LANE_TYPE_NORMAL)),
            start_tile=(int(st[0]), int(st[1])),
            end_tile=(int(et[0]), int(et[1])),
            protected=bool(raw.get("protected", False)),
        )

    police: list[dict] = []
    hints = [
        (str(h[0]), str(h[1]), str(h[2]))
        for h in scenario.get("route_hints", [])
        if isinstance(h, (list, tuple)) and len(h) == 3
    ]
    sb = scenario.get("spawn_balance") or {}
    origin_bal = float(sb.get("origin_spawn_balance_coeff", 1.0))
    out_bal = float(sb.get("out_lane_balance_coeff", 1.0))
    return (
        places_by_id,
        intersections_by_id,
        lanes_by_id,
        police,
        hints,
        origin_bal,
        out_bal,
    )


def apply_scenario_to_game(game: "GameState", scenario: dict) -> None:
    """Replace game map config from a schema-4 scenario (does not clear cars)."""
    (
        places_by_id,
        intersections_by_id,
        lanes_by_id,
        _police,
        hints,
        origin_bal,
        out_bal,
    ) = scenario_to_game_dicts(scenario)
    game.places = places_by_id
    game.intersections = intersections_by_id
    game.lanes = lanes_by_id
    game.route_hints = hints
    game.origin_spawn_balance_coeff = origin_bal
    game.out_lane_balance_coeff = out_bal
    game.police_list = []
    game.spawn_places = tuple(places_by_id.keys())


def game_to_scenario(game: "GameState", window=None) -> dict:
    """Serialize current game map config to schema 4."""
    places_out: dict[str, dict] = {}
    for key, p in game.places.items():
        places_out[key] = {
            "center_x": p.center_x,
            "center_y": p.center_y,
            "width": p.width,
            "length": p.length,
            "spawn_interval": p.spawn_interval,
            "attract_weight": p.attract_weight,
            "protected": bool(getattr(p, "protected", False)),
            "building_kind": places.clamp_building_kind(getattr(p, "building_kind", None), key),
            "building_seed": places.clamp_building_seed(getattr(p, "building_seed", 0)),
        }
    intersections_out: dict[str, dict] = {}
    for key, cfg in game.intersections.items():
        intersections_out[key] = {
            "center_x": cfg.center_x,
            "center_y": cfg.center_y,
            "size_cells": cfg.size_cells,
            "protected": bool(getattr(cfg, "protected", False)),
        }
    lanes_out: dict[str, dict] = {}
    for idx, cfg in game.lanes.items():
        lanes_out[str(idx)] = {
            "start_tile": [int(cfg.start_tile[0]), int(cfg.start_tile[1])],
            "end_tile": [int(cfg.end_tile[0]), int(cfg.end_tile[1])],
            "speed_limit": cfg.speed_limit,
            "lane_type": cfg.lane_type,
            "protected": bool(getattr(cfg, "protected", False)),
        }
    hints = [[a, b, c] for (a, b, c) in getattr(game, "route_hints", [])]
    user_settings = {}
    if window is not None:
        user_settings = {
            "edge_pan_enabled": getattr(window, "_edge_pan_enabled", True),
            "grass_close_enabled": getattr(window, "_grass_close_enabled", True),
            "color_hue": clamp_color_hue(getattr(window, "_color_hue", 0)),
            "color_sat": clamp_color_sat(getattr(window, "_color_sat", 1.0)),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "places": places_out,
        "intersections": intersections_out,
        "lanes": lanes_out,
        "police": [],
        "route_hints": hints,
        "spawn_balance": {
            "origin_spawn_balance_coeff": float(getattr(game, "origin_spawn_balance_coeff", 1.0)),
            "out_lane_balance_coeff": float(getattr(game, "out_lane_balance_coeff", 1.0)),
        },
        "user_settings": user_settings,
    }
