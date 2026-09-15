"""Iso compass tile selector."""
from __future__ import annotations

import math
from typing import Callable

import arcade

from draw_compat import ipx, rect_filled
from ui.font import ui_text
from ui.theme import (
    COMPASS_BUTTON_SIZE,
    DATUM_PAD_X,
    DATUM_WIDTH,
    FONT_DATUM,
    ICON_BUTTON_BG,
    ICON_BUTTON_DISABLED_BG,
    ICON_BUTTON_DISABLED_FG,
    ICON_BUTTON_FG,
    ICON_BUTTON_GAP,
    LABEL_COLOR,
    grade_ui_color,
)
from ui.widgets.text import draw_datum
from sim.constants import TILE_H, TILE_W

_COMPASS_ISO_DIRS: dict[str, tuple[float, float]] = {
    "W": (-TILE_W, -TILE_H),
    "E": (TILE_W, TILE_H),
    "N": (-TILE_W, TILE_H),
    "S": (TILE_W, -TILE_H),
}


class CompassSelect:
    """
    Tile selector: dark (x, y) datum plus four white iso-direction squares.
    locked_axis:
      - "x": disable E/W (x fixed)
      - "y": disable N/S (y fixed)
      - None: all enabled
    """

    def __init__(
        self,
        left: float,
        bottom: float,
        width: float,
        height: float,
        value: tuple[int, int],
        on_change: Callable[[tuple[int, int]], None] | None = None,
        locked_axis: str | None = None,
        min_val: int = -200,
        max_val: int = 200,
        datum_width: float = DATUM_WIDTH,
        button_fill=ICON_BUTTON_BG,
    ):
        self.rect = (left, bottom, width, height)
        self.value = (int(value[0]), int(value[1]))
        self.locked_axis = locked_axis
        self.datum_width = datum_width
        self.button_fill = button_fill
        self._on_change = on_change
        self._min_val = min_val
        self._max_val = max_val
        self._focused = False
        self._text_buffer = f"{self.value[0]}, {self.value[1]}"
        self._text = ui_text("", size=FONT_DATUM, color=LABEL_COLOR, anchor_x="left", anchor_y="center")

    def set_value(self, value: tuple[int, int]) -> None:
        self.value = (int(value[0]), int(value[1]))
        self._text_buffer = f"{self.value[0]}, {self.value[1]}"

    def set_focus(self, focused: bool) -> None:
        if self._focused != focused:
            self._focused = focused
            if not focused:
                self._commit_text()

    def _box_rect(self) -> tuple[float, float, float, float]:
        left, bottom, _, height = self.rect
        return (left, bottom, self.datum_width, height)

    def _commit_text(self) -> None:
        parts = self._text_buffer.replace(",", " ").split()
        try:
            vx = int(parts[0]) if len(parts) >= 1 else self.value[0]
            vy = int(parts[1]) if len(parts) >= 2 else self.value[1]
            vx = max(self._min_val, min(self._max_val, vx))
            vy = max(self._min_val, min(self._max_val, vy))
            nv = (vx, vy)
            if nv != self.value:
                self.value = nv
                if self._on_change:
                    self._on_change(self.value)
        except (ValueError, IndexError):
            pass
        self._text_buffer = f"{self.value[0]}, {self.value[1]}"

    def _button_defs(self) -> list[tuple[str, str, tuple[int, int]]]:
        return [
            ("W", "", (-1, 0)),
            ("E", "", (1, 0)),
            ("N", "", (0, 1)),
            ("S", "", (0, -1)),
        ]

    def _button_rect(self, idx: int) -> tuple[float, float, float, float]:
        left, bottom, _, height = self.rect
        size = COMPASS_BUTTON_SIZE
        btn_left = left + self.datum_width + ICON_BUTTON_GAP
        y = bottom + height - size
        return (btn_left + idx * (size + ICON_BUTTON_GAP), y, size, size)

    def _is_disabled(self, key: str) -> bool:
        if self.locked_axis == "x":
            return key in ("W", "E")
        if self.locked_axis == "y":
            return key in ("N", "S")
        return False

    def _draw_iso_arrow(self, cx: float, cy: float, key: str, color: tuple[int, int, int], size: float) -> None:
        dx, dy = _COMPASS_ISO_DIRS[key]
        length = math.hypot(dx, dy)
        if length < 0.01:
            return
        dx, dy = dx / length, dy / length
        perp_x = -dy
        perp_y = dx
        head_size = size * 0.45
        base_half = size * 0.32
        tail_len = size * 0.36
        tail_half = size * 0.09
        tip_x = cx + dx * head_size
        tip_y = cy + dy * head_size
        base_x = cx - dx * head_size * 0.3
        base_y = cy - dy * head_size * 0.3
        v1 = (base_x + perp_x * base_half, base_y + perp_y * base_half)
        v2 = (base_x - perp_x * base_half, base_y - perp_y * base_half)
        arcade.draw_triangle_filled(tip_x, tip_y, v1[0], v1[1], v2[0], v2[1], color)
        tail_tip_x = cx - dx * (head_size * 0.3 + tail_len)
        tail_tip_y = cy - dy * (head_size * 0.3 + tail_len)
        t1 = (base_x + perp_x * tail_half, base_y + perp_y * tail_half)
        t2 = (base_x - perp_x * tail_half, base_y - perp_y * tail_half)
        arcade.draw_triangle_filled(tail_tip_x, tail_tip_y, t1[0], t1[1], t2[0], t2[1], color)

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        return left <= x <= left + width and bottom <= y <= bottom + height

    def on_press(self, x: float, y: float) -> bool:
        if not self.contains(x, y):
            return False
        bx, by, bw, bh = self._box_rect()
        if bx <= x <= bx + bw and by <= y <= by + bh:
            self.set_focus(True)
            return True
        for i, (key, _label, delta) in enumerate(self._button_defs()):
            l, b, w, h = self._button_rect(i)
            if l <= x <= l + w and b <= y <= b + h:
                if self._is_disabled(key):
                    return True
                nx = self.value[0] + delta[0]
                ny = self.value[1] + delta[1]
                nx = max(self._min_val, min(self._max_val, nx))
                ny = max(self._min_val, min(self._max_val, ny))
                self.value = (nx, ny)
                self._text_buffer = f"{self.value[0]}, {self.value[1]}"
                if self._on_change:
                    self._on_change(self.value)
                return True
        return True

    def on_key_press(self, key: int) -> bool:
        if not self._focused:
            return False
        if key == arcade.key.RETURN or key == arcade.key.TAB:
            self.set_focus(False)
            return True
        if key == arcade.key.BACKSPACE:
            if self._text_buffer:
                self._text_buffer = self._text_buffer[:-1]
            return True
        if 48 <= key <= 57:
            self._text_buffer += chr(key)
            return True
        if key == arcade.key.COMMA:
            self._text_buffer += ","
            return True
        if key == arcade.key.SPACE:
            self._text_buffer += " "
            return True
        if key == arcade.key.MINUS or key == 45:
            if not self._text_buffer or self._text_buffer[-1] in ", ":
                self._text_buffer += "-"
            return True
        return False

    def on_drag(self, x: float) -> bool:
        return False

    def on_release(self) -> bool:
        return False

    def draw(self) -> None:
        bx, by, bw, bh = self._box_rect()
        draw_datum(bx, by, bw, bh)
        self._text.value = self._text_buffer if self._focused else f"({self.value[0]}, {self.value[1]})"
        self._text.x = ipx(bx) + DATUM_PAD_X
        self._text.y = ipx(by + bh / 2)
        self._text.draw()
        for i, (key, _label, _delta) in enumerate(self._button_defs()):
            l, b, w, h = self._button_rect(i)
            disabled = self._is_disabled(key)
            s = ipx(min(w, h))
            l, b = ipx(l), ipx(b)
            fill = ICON_BUTTON_DISABLED_BG if disabled else grade_ui_color(self.button_fill)
            rect_filled(l, b, s, s, fill)
            fg = ICON_BUTTON_DISABLED_FG if disabled else ICON_BUTTON_FG
            self._draw_iso_arrow(l + s / 2, b + s / 2, key, fg, float(s))
