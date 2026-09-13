"""Skeuomorphic keyboard-key chip."""
from __future__ import annotations

import arcade

from draw_compat import rect_filled, rect_outline
from ui.theme import (
    ESC_CHIP_HEIGHT,
    ESC_CHIP_LEFT,
    ESC_CHIP_MARGIN_SIDE,
    ESC_CHIP_MARGIN_TOP,
    ESC_CHIP_WIDTH,
)


class SkeuoKeyChip:
    """Skeuomorphic keyboard-key control. side is 'left' or 'right' (top of the window)."""

    def __init__(self, label: str, side: str = "left"):
        self._side = side
        self._label = arcade.Text(
            label, 0, 0, color=(30, 30, 35), font_size=12, anchor_x="center", anchor_y="center"
        )

    def set_label(self, label: str) -> None:
        self._label.value = label

    def rect(self, window_width: float, window_height: float) -> tuple[float, float, float, float]:
        bottom = window_height - ESC_CHIP_MARGIN_TOP - ESC_CHIP_HEIGHT
        if self._side == "right":
            left = window_width - ESC_CHIP_MARGIN_SIDE - ESC_CHIP_WIDTH
        else:
            left = ESC_CHIP_LEFT
        return (left, bottom, ESC_CHIP_WIDTH, ESC_CHIP_HEIGHT)

    def contains(self, x: float, y: float, window_width: float, window_height: float) -> bool:
        left, bottom, width, height = self.rect(window_width, window_height)
        return left <= x <= left + width and bottom <= y <= bottom + height

    def draw(self, window_width: float, window_height: float) -> None:
        left, bottom, width, height = self.rect(window_width, window_height)
        rect_filled(left, bottom, width, height, (70, 70, 80))
        rect_filled(left + 1, bottom + 4, width - 2, height - 5, (200, 200, 210))
        rect_outline(left, bottom, width, height, (110, 110, 125), 1)
        self._label.x = left + width / 2
        self._label.y = bottom + height / 2 + 1
        self._label.draw()
