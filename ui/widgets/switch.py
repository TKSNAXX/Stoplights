"""Boolean toggle."""
from __future__ import annotations

import arcade

from draw_compat import rect_filled
from ui.theme import LABEL_COLOR


class Switch:
    """Boolean toggle. Rect (left, bottom, width, height). value is True/False."""

    def __init__(
        self,
        left: float,
        bottom: float,
        width: float,
        height: float,
        initial_value: bool = True,
        bar_color: tuple[int, int, int] = (100, 100, 100),
        thumb_color: tuple[int, int, int] = (180, 180, 180),
    ):
        self.rect = (left, bottom, width, height)
        self.value = initial_value
        self.bar_color = bar_color
        self.thumb_color = thumb_color
        self._text_on = arcade.Text(
            "On", 0, 0, color=LABEL_COLOR, font_size=10,
            anchor_x="center", anchor_y="center",
        )
        self._text_off = arcade.Text(
            "Off", 0, 0, color=LABEL_COLOR, font_size=10,
            anchor_x="center", anchor_y="center",
        )

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        return left <= x <= left + width and bottom <= y <= bottom + height

    def toggle(self) -> bool:
        self.value = not self.value
        return self.value

    def on_press(self, x: float, y: float) -> bool:
        if not self.contains(x, y):
            return False
        self.toggle()
        return True

    def on_drag(self, x: float) -> bool:
        return False

    def on_release(self) -> bool:
        return False

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        color = self.thumb_color if self.value else self.bar_color
        rect_filled(left, bottom, width, height, color)
        cx = left + width / 2
        cy = bottom + height / 2
        if self.value:
            self._text_on.x, self._text_on.y = cx, cy
            self._text_on.draw()
        else:
            self._text_off.x, self._text_off.y = cx, cy
            self._text_off.draw()
