"""Exclusive tool base and ghost-cell helper."""
from __future__ import annotations

import arcade

from ui.theme import TOOLBAR_LEFT
from ui.tools.host import ToolHost


class Tool:
    """Exclusive interaction mode. Default inspect; create tools replace it."""

    id: str = ""

    def __init__(self, host: ToolHost) -> None:
        self.host = host

    @property
    def active_action(self) -> str | None:
        return None

    def enter(self) -> None:
        return None

    def exit(self) -> None:
        return None

    def on_click(self, x: float, y: float) -> bool:
        return False

    def on_hover(self, x: float, y: float) -> None:
        return None

    def can_pop(self) -> bool:
        return False

    def pop(self) -> None:
        return None

    def draw_preview(self, center_x: float, center_y: float) -> None:
        return None


def readout_anchor(host: ToolHost) -> tuple[float, float]:
    _w, h = host.window_size
    return (TOOLBAR_LEFT + 56, h / 2 + 100)


def draw_ghost_cells(host: ToolHost, tex_key: str, cells, center_x: float, center_y: float) -> None:
    if not host.mouse_in_window or not cells:
        return
    tex = host.tile_set.get(tex_key)
    if tex is None:
        return
    lst = arcade.SpriteList()
    for gx, gy in cells:
        spr = arcade.Sprite(tex, scale=host.zoom_scale)
        spr.center_x, spr.center_y = host.to_screen(gx, gy, center_x, center_y)
        spr.alpha = 170
        lst.append(spr)
    lst.draw(pixelated=True)
