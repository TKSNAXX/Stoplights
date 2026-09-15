"""
Arcade compatibility shims.
"""
from __future__ import annotations

import arcade


def ipx(v: float) -> int:
    return int(round(v))

try:
    from arcade.draw.rect import draw_lbwh_rectangle_filled as _draw_rect

    def rect_filled(left: float, bottom: float, width: float, height: float, color) -> None:
        _draw_rect(ipx(left), ipx(bottom), ipx(width), ipx(height), color)

except ImportError:

    def rect_filled(left: float, bottom: float, width: float, height: float, color) -> None:
        w, h = ipx(width), ipx(height)
        cx = ipx(left) + w / 2
        cy = ipx(bottom) + h / 2
        arcade.draw_rectangle_filled(cx, cy, w, h, color)

try:
    from arcade.draw.rect import draw_lbwh_rectangle_outline as _draw_rect_outline

    def rect_outline(left: float, bottom: float, width: float, height: float, color, border_width: float = 1.0) -> None:
        _draw_rect_outline(ipx(left), ipx(bottom), ipx(width), ipx(height), color, border_width=border_width)

except ImportError:

    def rect_outline(left: float, bottom: float, width: float, height: float, color, border_width: float = 1.0) -> None:
        w, h = ipx(width), ipx(height)
        cx = ipx(left) + w / 2
        cy = ipx(bottom) + h / 2
        arcade.draw_rectangle_outline(cx, cy, w, h, color, border_width=border_width)


def circle_filled(cx: float, cy: float, radius: float, color) -> None:
    arcade.draw_circle_filled(cx, cy, radius, color)


def round_rect_filled(
    left: float, bottom: float, width: float, height: float, color, radius: float,
) -> None:
    """Integer-snapped rounded rect: corner discs plus axis-aligned fills."""
    left, bottom = ipx(left), ipx(bottom)
    width, height = ipx(width), ipx(height)
    if width <= 0 or height <= 0:
        return
    r = min(ipx(radius), width // 2, height // 2)
    if r <= 0:
        rect_filled(left, bottom, width, height, color)
        return
    rect_filled(left + r, bottom, width - 2 * r, height, color)
    rect_filled(left, bottom + r, r, height - 2 * r, color)
    rect_filled(left + width - r, bottom + r, r, height - 2 * r, color)
    circle_filled(left + r, bottom + r, r, color)
    circle_filled(left + width - r, bottom + r, r, color)
    circle_filled(left + r, bottom + height - r, r, color)
    circle_filled(left + width - r, bottom + height - r, r, color)

