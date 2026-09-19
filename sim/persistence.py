"""
Persist scenario between sessions (schema 4).
No cars or simulation state—only configuration.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from sim import places, scenario
from sim.scenario import clamp_color_hue, clamp_color_sat

if TYPE_CHECKING:
    from sim.game import GameState

SAVE_FILENAME = "config.json"
SAVES_DIRNAME = Path("assets") / "maps" / "saves"
DEBOUNCE_SEC = 1.5
SCHEMA_VERSION = scenario.SCHEMA_VERSION

_save_timer: float = 0.0


def get_save_path() -> Path:
    return Path(__file__).resolve().parent.parent / SAVE_FILENAME


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def saves_dir(directory: Path | None = None) -> Path:
    if directory is not None:
        return Path(directory)
    return project_root() / SAVES_DIRNAME


def sanitize_save_name(raw) -> str | None:
    """Alnum, hyphen, underscore. Reject empty names and path separators."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or "/" in s or "\\" in s or ".." in s:
        return None
    out: list[str] = []
    for ch in s:
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        elif ch in " \t":
            out.append("_")
        else:
            return None
    name = "".join(out).strip("._")
    return name or None


def list_saved_maps(directory: Path | None = None) -> list[str]:
    folder = saves_dir(directory)
    if not folder.is_dir():
        return []
    names = [p.stem for p in folder.glob("*.json") if p.is_file()]
    return sorted(names)


def _write_json(path: Path, data: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def _apply_user_settings(game: "GameState", data: dict, window=None) -> None:
    us = data.get("user_settings", {})
    if window is None or not isinstance(us, dict):
        return
    if "edge_pan_enabled" in us and isinstance(us["edge_pan_enabled"], bool):
        window._edge_pan_enabled = us["edge_pan_enabled"]
    if "grass_close_enabled" in us and isinstance(us["grass_close_enabled"], bool):
        window._grass_close_enabled = us["grass_close_enabled"]
    if "police_enabled" in us and isinstance(us["police_enabled"], bool):
        window._police_enabled = us["police_enabled"]
        game.police_enabled = us["police_enabled"]
    if "color_hue" in us:
        window._color_hue = clamp_color_hue(us["color_hue"])
    if "color_sat" in us:
        window._color_sat = clamp_color_sat(us["color_sat"])


def _install_scenario(game: "GameState", data: dict, window=None) -> None:
    _apply_user_settings(game, data, window=window)
    game.cars.clear()
    game.lane_spawn_counts.clear()
    game._impasse_timers.clear()
    scenario.apply_scenario_to_game(game, data)
    game.spawn_timers = {p: 0.0 for p in game.spawn_places}
    game.origin_spawn_counts = {p: 0 for p in game.spawn_places}
    game.spawn_enabled = {p: True for p in game.spawn_places}
    places.set_route_hints(game.route_hints)
    game.rebuild_world_from_config()


def load_config(game: "GameState", window=None) -> None:
    """Load config from disk, migrate to schema 4, apply to game, rewrite if migrated."""
    path = get_save_path()
    raw = scenario.load_json_file(path)
    if raw is None:
        return

    version = int(raw.get("schema_version", 3) or 3)
    data = scenario.migrate_to_schema_4(raw)
    _apply_user_settings(game, data, window=window)
    scenario.apply_scenario_to_game(game, data)
    places.set_route_hints(game.route_hints)

    # Rewrite migrated saves so disk matches the lingua franca.
    if version < SCHEMA_VERSION:
        _write_json(path, data)


def save_config(game: "GameState", window=None, path: Path | None = None) -> None:
    dest = path if path is not None else get_save_path()
    data = scenario.game_to_scenario(game, window=window)
    _write_json(dest, data)


def save_named_map(
    game: "GameState",
    name: str,
    window=None,
    directory: Path | None = None,
) -> str | None:
    """Write a named snapshot. Returns the sanitized name, or None if refused."""
    stem = sanitize_save_name(name)
    if stem is None:
        return None
    dest = saves_dir(directory) / f"{stem}.json"
    data = scenario.game_to_scenario(game, window=window)
    if not _write_json(dest, data):
        return None
    return stem


def load_named_map(
    game: "GameState",
    name: str,
    window=None,
    directory: Path | None = None,
    working_path: Path | None = None,
) -> bool:
    """Load a named snapshot into the game and copy it to the working config."""
    stem = sanitize_save_name(name)
    if stem is None:
        return False
    src = saves_dir(directory) / f"{stem}.json"
    raw = scenario.load_json_file(src)
    if raw is None:
        return False
    data = scenario.migrate_to_schema_4(raw)
    _install_scenario(game, data, window=window)
    save_config(game, window=window, path=working_path)
    return True


def new_game(game: "GameState", window=None, working_path: Path | None = None) -> None:
    """Reload the default map and write it as the working copy."""
    game.reset_to_defaults()
    save_config(game, window=window, path=working_path)


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
