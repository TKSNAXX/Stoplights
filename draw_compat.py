"""
Arcade compatibility shims.
"""
from __future__ import annotations

import arcade

try:
    from arcade.draw.rect import draw_lbwh_rectangle_filled as _draw_rect

    def rect_filled(left: float, bottom: float, width: float, height: float, color) -> None:
        _draw_rect(left, bottom, width, height, color)

except ImportError:

    def rect_filled(left: float, bottom: float, width: float, height: float, color) -> None:
        cx = left + width / 2
        cy = bottom + height / 2
        arcade.draw_rectangle_filled(cx, cy, width, height, color)

try:
    from arcade.draw.rect import draw_lbwh_rectangle_outline as _draw_rect_outline

    def rect_outline(left: float, bottom: float, width: float, height: float, color, border_width: float = 1.0) -> None:
        _draw_rect_outline(left, bottom, width, height, color, border_width=border_width)

except ImportError:

    def rect_outline(left: float, bottom: float, width: float, height: float, color, border_width: float = 1.0) -> None:
        cx = left + width / 2
        cy = bottom + height / 2
        arcade.draw_rectangle_outline(cx, cy, width, height, color, border_width=border_width)

