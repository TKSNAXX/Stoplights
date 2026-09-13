"""Horizontal step slider."""
from __future__ import annotations

from draw_compat import rect_filled


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
        bar_color: tuple[int, int, int] = (100, 100, 100),
        thumb_color: tuple[int, int, int] = (180, 180, 180),
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
        bar_height = min(height * 0.35, 8)
        bar_center_y = bottom + height / 2
        bar_bottom = bar_center_y - bar_height / 2
        rect_filled(left, bar_bottom, width, bar_height, self.bar_color)
        thumb_w = 16
        thumb_h = height - 4
        t = self.value / (self.num_steps - 1) if self.num_steps > 1 else 0
        thumb_left = left + thumb_w / 2 + t * (width - thumb_w) - thumb_w / 2
        if self.num_steps <= 1:
            thumb_left = left + (width - thumb_w) / 2
        rect_filled(thumb_left, bottom + 2, thumb_w, thumb_h, self.thumb_color)

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
