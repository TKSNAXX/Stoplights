"""Integer-snapped dark-grey icons for white square buttons."""
from __future__ import annotations

import arcade

from draw_compat import ipx, rect_filled


def _line(x1: float, y1: float, x2: float, y2: float, color, width: float = 2) -> None:
    arcade.draw_line(ipx(x1), ipx(y1), ipx(x2), ipx(y2), color, width)


def _tri(x1, y1, x2, y2, x3, y3, color) -> None:
    arcade.draw_triangle_filled(ipx(x1), ipx(y1), ipx(x2), ipx(y2), ipx(x3), ipx(y3), color)


def draw_icon(kind: str, left: float, bottom: float, size: float, color) -> None:
    l, b, s = ipx(left), ipx(bottom), ipx(size)
    pad = max(3, s // 5)
    inner = s - pad * 2
    x0, y0 = l + pad, b + pad
    x1, y1 = x0 + inner, y0 + inner
    cx, cy = l + s / 2, b + s / 2
    if kind == "shuffle":
        _line(x0, y1 - 2, x0 + inner * 0.35, y1 - 2, color, 2)
        _line(x0 + inner * 0.35, y1 - 2, x0 + inner * 0.65, y0 + 2, color, 2)
        _line(x0 + inner * 0.65, y0 + 2, x1 - 3, y0 + 2, color, 2)
        _tri(x1, y0 + 2, x1 - 5, y0 + 6, x1 - 5, y0 - 2, color)
        _line(x0, y0 + 2, x0 + inner * 0.35, y0 + 2, color, 2)
        _line(x0 + inner * 0.35, y0 + 2, x0 + inner * 0.65, y1 - 2, color, 2)
        _line(x0 + inner * 0.65, y1 - 2, x1 - 3, y1 - 2, color, 2)
        _tri(x1, y1 - 2, x1 - 5, y1 + 2, x1 - 5, y1 - 6, color)
    elif kind == "commit":
        _line(x0 + 1, cy, cx - 1, y0 + 2, color, 2)
        _line(cx - 1, y0 + 2, x1 - 1, y1 - 1, color, 2)
    elif kind == "remove":
        rect_filled(x0 + 1, cy - 1, inner - 2, 3, color)
    elif kind == "up":
        _tri(cx, y1 - 1, x0 + 2, y0 + 3, x1 - 2, y0 + 3, color)
    elif kind == "down":
        _tri(cx, y0 + 1, x0 + 2, y1 - 3, x1 - 2, y1 - 3, color)
    elif kind == "chevron":
        _tri(cx, y0 + 3, x0 + 3, y1 - 4, x1 - 3, y1 - 4, color)
    else:
        rect_filled(cx - 1, y0 + 2, 2, inner - 4, color)
