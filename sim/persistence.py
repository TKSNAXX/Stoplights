"""
Persist place, lane, and intersection configs between sessions.
No cars or simulation state—only configuration.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from sim import places

if TYPE_CHECKING:
    from sim.game import GameState

SAVE_FILENAME = "config.json"
DEBOUNCE_SEC = 1.5

_save_timer: float = 0.0


def get_save_path() -> Path:
    """Config file in project main dir (Stoplights/)."""
    base = Path(__file__).resolve().parent.parent
    return base / SAVE_FILENAME


def _clamp_size(n: int) -> int:
    """Ensure size in 2–12, even."""
    n = max(2, min(12, int(n)))
    return n if n % 2 == 0 else (n // 2) * 2


def load_config(game: "GameState") -> None:
    """Load config from disk and apply to game. On error or missing, leave configs unchanged."""
    path = get_save_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return

    pc = data.get("place_configs", {})
    for key, cfg in pc.items():
        if key not in game.place_configs:
            continue
        if isinstance(cfg, dict):
            if "spawn_interval" in cfg and isinstance(cfg["spawn_interval"], (int, float)):
                game.place_configs[key].spawn_interval = max(0.1, float(cfg["spawn_interval"]))
            if "attract_weight" in cfg and isinstance(cfg["attract_weight"], (int, float)):
                game.place_configs[key].attract_weight = max(0.01, float(cfg["attract_weight"]))

    lc = data.get("lane_configs", {})
    for key, cfg in lc.items():
        try:
            idx = int(key)
        except (ValueError, TypeError):
            continue
        if idx not in game.lane_configs:
            continue
        if isinstance(cfg, dict):
            if "speed_limit" in cfg and isinstance(cfg["speed_limit"], (int, float)):
                v = float(cfg["speed_limit"])
                game.lane_configs[idx].speed_limit = max(0.1, min(3.0, v))
            if "lane_type" in cfg and cfg["lane_type"] in places.LANE_TYPES:
                game.lane_configs[idx].lane_type = cfg["lane_type"]

    ic = data.get("intersection_configs", {})
    for key, cfg in ic.items():
        if key not in game.intersection_configs:
            continue
        if isinstance(cfg, dict):
            if "intersection_type" in cfg and cfg["intersection_type"] in places.INTERSECTION_TYPES:
                game.intersection_configs[key].intersection_type = cfg["intersection_type"]
            if "size_cells" in cfg and isinstance(cfg["size_cells"], (int, float)):
                game.intersection_configs[key].size_cells = _clamp_size(int(cfg["size_cells"]))
            if "center_x" in cfg and isinstance(cfg["center_x"], (int, float)):
                game.intersection_configs[key].center_x = int(cfg["center_x"])
            if "center_y" in cfg and isinstance(cfg["center_y"], (int, float)):
                game.intersection_configs[key].center_y = int(cfg["center_y"])

    pg = data.get("place_geometry", {})
    for key, g in pg.items():
        if key not in places.PLACES:
            continue
        if isinstance(g, dict):
            cx = int(g.get("center_x", 0))
            cy = int(g.get("center_y", 0))
            w = max(places.PLACE_SIZE_MIN, min(places.PLACE_SIZE_MAX, int(g.get("width", 5))))
            l = max(places.PLACE_SIZE_MIN, min(places.PLACE_SIZE_MAX, int(g.get("length", 5))))
            game.place_geometry[key] = places.PlaceGeometry(center_x=cx, center_y=cy, width=w, length=l)


def save_config(game: "GameState") -> None:
    """Serialize configs to JSON and write to disk."""
    path = get_save_path()
    data = {
        "place_configs": {
            k: {"spawn_interval": v.spawn_interval, "attract_weight": v.attract_weight}
            for k, v in game.place_configs.items()
        },
        "lane_configs": {
            str(k): {"speed_limit": v.speed_limit, "lane_type": v.lane_type}
            for k, v in game.lane_configs.items()
        },
        "intersection_configs": {
            k: {
                "intersection_type": v.intersection_type,
                "size_cells": v.size_cells,
                "center_x": v.center_x,
                "center_y": v.center_y,
            }
            for k, v in game.intersection_configs.items()
        },
        "place_geometry": {
            k: {"center_x": g.center_x, "center_y": g.center_y, "width": g.width, "length": g.length}
            for k, g in game.place_geometry.items()
        },
    }
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def request_debounced_save() -> None:
    """Schedule a save after DEBOUNCE_SEC. Call from place/lane on_change."""
    global _save_timer
    _save_timer = DEBOUNCE_SEC


def tick_debounced_save(game: "GameState", dt: float) -> None:
    """Call from on_update. Countdown and save when timer expires."""
    global _save_timer
    if _save_timer <= 0:
        return
    _save_timer -= dt
    if _save_timer <= 0:
        save_config(game)
        _save_timer = 0.0
