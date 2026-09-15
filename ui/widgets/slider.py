"""Horizontal step slider: thin dark track, compact vertical thumb."""
from __future__ import annotations

from draw_compat import ipx, rect_filled
from ui.theme import SLIDER_THUMB, SLIDER_THUMB_H, SLIDER_THUMB_W, SLIDER_TRACK, SLIDER_TRACK_H


class Slider:
    """Horizontal step slider. Rect (left, bottom, width, height). value is 0..num_steps-1."""

    def __init__(
        self,
        left: float,
        bottom: float,
        width: float,
        height: float,
        num_steps: int,
        initial_step: int = 0,
        bar_color: tuple[int, int, int] = SLIDER_TRACK,
        thumb_color: tuple[int, int, int] = SLIDER_THUMB,
    ):
        self.rect = (left, bottom, width, height)
        self.num_steps = max(1, num_steps)
        self.value = max(0, min(initial_step, self.num_steps - 1))
        self.bar_color = bar_color
        self.thumb_color = thumb_color
        self._dragging = False

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        return left <= x <= left + width and bottom <= y <= bottom + height

    def step_from_x(self, x: float) -> int:
        left, _, width, _ = self.rect
        t = (x - left) / width if width > 0 else 0
        t = max(0.0, min(1.0, t))
        return int(t * (self.num_steps - 1) + 0.5) if self.num_steps > 1 else 0

    def set_step(self, step: int) -> None:
        self.value = max(0, min(self.num_steps - 1, step))

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        left, bottom, width, height = ipx(left), ipx(bottom), ipx(width), ipx(height)
        bar_h = SLIDER_TRACK_H
        bar_bottom = bottom + (height - bar_h) // 2
        rect_filled(left, bar_bottom, width, bar_h, self.bar_color)
        thumb_w = SLIDER_THUMB_W
        thumb_h = min(SLIDER_THUMB_H, height)
        t = self.value / (self.num_steps - 1) if self.num_steps > 1 else 0
        thumb_left = left + t * max(0, width - thumb_w)
        if self.num_steps <= 1:
            thumb_left = left + (width - thumb_w) / 2
        thumb_bottom = bottom + (height - thumb_h) // 2
        rect_filled(thumb_left, thumb_bottom, thumb_w, thumb_h, self.thumb_color)

    def on_press(self, x: float, y: float) -> bool:
        if not self.contains(x, y):
            return False
        self._dragging = True
        self.set_step(self.step_from_x(x))
        return True

    def on_drag(self, x: float) -> bool:
        if not self._dragging:
            return False
        self.set_step(self.step_from_x(x))
        return True

    def on_release(self) -> bool:
        if not self._dragging:
            return False
        self._dragging = False
        return True
