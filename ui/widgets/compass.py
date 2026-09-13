"""Iso compass tile selector."""
from __future__ import annotations

import math
from typing import Callable

import arcade

from draw_compat import rect_filled, rect_outline
from sim.constants import TILE_H, TILE_W
from ui.theme import DIALOG_BORDER, LABEL_COLOR, WIDGET_BORDER, WIDGET_FILL

_COMPASS_ISO_DIRS: dict[str, tuple[float, float]] = {
    "W": (-TILE_W, -TILE_H),
    "E": (TILE_W, TILE_H),
    "N": (-TILE_W, TILE_H),
    "S": (TILE_W, -TILE_H),
}


class CompassSelect:
    """
    Tile selector control.
    Displays (x, y) plus directional buttons in one row: W, E, N, S.
    Coordinates are keyboard-editable. Arrow icons use iso projection.
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
    ):
        self.rect = (left, bottom, width, height)
        self.value = (int(value[0]), int(value[1]))
        self.locked_axis = locked_axis
        self._on_change = on_change
        self._min_val = min_val
        self._max_val = max_val
        self._focused = False
        self._text_buffer = f"{self.value[0]}, {self.value[1]}"
        self._text = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")

    def set_value(self, value: tuple[int, int]) -> None:
        self.value = (int(value[0]), int(value[1]))
        self._text_buffer = f"{self.value[0]}, {self.value[1]}"

    def set_focus(self, focused: bool) -> None:
        if self._focused != focused:
            self._focused = focused
            if not focused:
                self._commit_text()

    def _box_rect(self) -> tuple[float, float, float, float]:
        """Text box portion: (left, bottom, width, height)."""
        left, bottom, width, height = self.rect
        text_w = min(64.0, width * 0.35)
        return (left, bottom, text_w + 6, height)

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
        left, bottom, width, height = self.rect
        text_w = min(64.0, width * 0.35)
        btn_left = left + text_w + 6
        btn_width_total = max(40.0, width - (btn_left - left))
        btn_w = max(18.0, btn_width_total / 4 - 2)
        return (btn_left + idx * (btn_w + 2), bottom, btn_w, height)

    def _is_disabled(self, key: str) -> bool:
        if self.locked_axis == "x":
            return key in ("W", "E")
        if self.locked_axis == "y":
            return key in ("N", "S")
        return False

    def _draw_iso_arrow(self, cx: float, cy: float, key: str, color: tuple[int, int, int]) -> None:
        """Draw arrow with head and tail pointing in iso direction for key."""
        dx, dy = _COMPASS_ISO_DIRS[key]
        length = math.hypot(dx, dy)
        if length < 0.01:
            return
        dx, dy = dx / length, dy / length
        perp_x = -dy
        perp_y = dx
        head_size = 7.0
        base_half = 5.0
        tail_len = 5.0
        tail_half = 1.5
        tip_x = cx + dx * head_size
        tip_y = cy + dy * head_size
        base_x = cx - dx * head_size * 0.3
        base_y = cy - dy * head_size * 0.3
        v1 = (base_x + perp_x * base_half, base_y + perp_y * base_half)
        v2 = (base_x - perp_x * base_half, base_y - perp_y * base_half)
        arcade.draw_triangle_filled(
            tip_x, tip_y,
            v1[0], v1[1],
            v2[0], v2[1],
            color,
        )
        tail_tip_x = cx - dx * (head_size * 0.3 + tail_len)
        tail_tip_y = cy - dy * (head_size * 0.3 + tail_len)
        t1 = (base_x + perp_x * tail_half, base_y + perp_y * tail_half)
        t2 = (base_x - perp_x * tail_half, base_y - perp_y * tail_half)
        arcade.draw_triangle_filled(
            tail_tip_x, tail_tip_y,
            t1[0], t1[1],
            t2[0], t2[1],
            color,
        )

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
        left, bottom, width, height = self.rect
        bx, by, bw, bh = self._box_rect()
        rect_filled(bx, by, bw, bh, WIDGET_FILL)
        rect_outline(bx, by, bw, bh, DIALOG_BORDER if self._focused else WIDGET_BORDER, 1)
        self._text.value = self._text_buffer if self._focused else f"({self.value[0]}, {self.value[1]})"
        self._text.x = left + 2
        self._text.y = bottom + height / 2
        self._text.draw()
        for i, (key, _label, _delta) in enumerate(self._button_defs()):
            l, b, w, h = self._button_rect(i)
            disabled = self._is_disabled(key)
            bg = (70, 70, 80) if not disabled else (52, 52, 58)
            border = (100, 100, 115) if not disabled else (78, 78, 88)
            fg = (220, 220, 220) if not disabled else (130, 130, 140)
            rect_filled(l, b, w, h, bg)
            rect_outline(l, b, w, h, border, 1)
            self._draw_iso_arrow(l + w / 2, b + h / 2, key, fg)
