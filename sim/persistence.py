"""
Persist scenario between sessions (schema 4).
No cars or simulation state—only configuration.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from sim import places, scenario

if TYPE_CHECKING:
    from sim.game import GameState

SAVE_FILENAME = "config.json"
DEBOUNCE_SEC = 1.5
SCHEMA_VERSION = scenario.SCHEMA_VERSION

_save_timer: float = 0.0


def get_save_path() -> Path:
    return Path(__file__).resolve().parent.parent / SAVE_FILENAME


def load_config(game: "GameState", window=None) -> None:
    """Load config from disk, migrate to schema 4, apply to game, rewrite if migrated."""
    path = get_save_path()
    raw = scenario.load_json_file(path)
    if raw is None:
        return

    version = int(raw.get("schema_version", 3) or 3)
    data = scenario.migrate_to_schema_4(raw)

    us = data.get("user_settings", {})
    if window is not None and isinstance(us, dict):
        if "edge_pan_enabled" in us and isinstance(us["edge_pan_enabled"], bool):
            window._edge_pan_enabled = us["edge_pan_enabled"]

    scenario.apply_scenario_to_game(game, data)
    places.set_route_hints(game.route_hints)

    # Rewrite migrated saves so disk matches the lingua franca.
    if version < SCHEMA_VERSION:
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass


def save_config(game: "GameState", window=None) -> None:
    path = get_save_path()
    data = scenario.game_to_scenario(game, window=window)
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def request_debounced_save() -> None:
    global _save_timer
    _save_timer = DEBOUNCE_SEC


def tick_debounced_save(game: "GameState", dt: float, window=None) -> None:
    global _save_timer
    if _save_timer <= 0:
        return
    _save_timer -= dt
    if _save_timer <= 0:
        save_config(game, window=window)
        _save_timer = 0.0
