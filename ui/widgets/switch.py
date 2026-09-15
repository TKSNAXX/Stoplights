"""Boolean toggle: dark track, white square thumb."""
from __future__ import annotations

from draw_compat import ipx, rect_filled
from ui.theme import ICON_BUTTON_BG, SLIDER_TRACK


class Switch:
    """Boolean toggle. Rect (left, bottom, width, height). value is True/False."""

    def __init__(
        self,
        left: float,
        bottom: float,
        width: float,
        height: float,
        initial_value: bool = True,
        bar_color: tuple[int, int, int] = SLIDER_TRACK,
        thumb_color: tuple[int, int, int] = ICON_BUTTON_BG,
    ):
        self.rect = (left, bottom, width, height)
        self.value = initial_value
        self.bar_color = bar_color
        self.thumb_color = thumb_color

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
        left, bottom, width, height = ipx(left), ipx(bottom), ipx(width), ipx(height)
        track_h = max(4, height // 3)
        track_b = bottom + (height - track_h) // 2
        rect_filled(left, track_b, width, track_h, self.bar_color)
        thumb = min(width, height) - 2
        if self.value:
            tx = left + width - thumb
        else:
            tx = left
        rect_filled(tx, bottom + (height - thumb) // 2, thumb, thumb, self.thumb_color)
