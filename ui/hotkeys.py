"""Hotkey registry: key -> action + hint label + when it applies."""
from __future__ import annotations

from dataclasses import dataclass

import arcade

WHEN_ALWAYS = "always"
WHEN_TOOL = "tool"
WHEN_PLACEMENT = "placement"
WHEN_CAMERA = "camera"
WHEN_SELECT = "select"


@dataclass(frozen=True)
class Hotkey:
    key: int
    action: str
    hint: str
    when: str


HOTKEYS: tuple[Hotkey, ...] = (
    Hotkey(arcade.key.ESCAPE, "escape", "Esc", WHEN_TOOL),
    Hotkey(arcade.key.BACKSPACE, "placement_pop", "<-", WHEN_PLACEMENT),
    Hotkey(arcade.key.V, "toggle_visibility_fans", "V", WHEN_ALWAYS),
    Hotkey(arcade.key.LSHIFT, "select_toggle_mode", "Shift", WHEN_SELECT),
    Hotkey(arcade.key.RSHIFT, "select_toggle_mode", "Shift", WHEN_SELECT),
    Hotkey(arcade.key.LCTRL, "select_toggle_overlay", "Ctrl", WHEN_SELECT),
    Hotkey(arcade.key.RCTRL, "select_toggle_overlay", "Ctrl", WHEN_SELECT),
    Hotkey(arcade.key.LEFT, "cam_left", "Left", WHEN_CAMERA),
    Hotkey(arcade.key.RIGHT, "cam_right", "Right", WHEN_CAMERA),
    Hotkey(arcade.key.UP, "cam_up", "Up", WHEN_CAMERA),
    Hotkey(arcade.key.DOWN, "cam_down", "Down", WHEN_CAMERA),
)


def hotkey_for_action(action: str) -> Hotkey | None:
    for item in HOTKEYS:
        if item.action == action:
            return item
    return None


def hotkey_for_key(key: int) -> Hotkey | None:
    for item in HOTKEYS:
        if item.key == key:
            return item
    return None


def hint_for(action: str, default: str) -> str:
    item = hotkey_for_action(action)
    return item.hint if item is not None else default
