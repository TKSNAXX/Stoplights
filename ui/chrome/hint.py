"""Brief label flashed beside a toolbar button."""
from __future__ import annotations

from ui.font import ui_text
from ui.theme import LABEL_COLOR, SELECT_HINT_DURATION, SELECT_HINT_FADE


class FlashHint:
    """Short-lived label; fades during the last third of its life."""

    def __init__(self, duration: float = SELECT_HINT_DURATION) -> None:
        self._duration = duration
        self._age = 0.0
        self._live = False
        self._text = ui_text(
            "",
            0,
            0,
            size=12,
            color=LABEL_COLOR,
            anchor_x="left",
            anchor_y="center",
        )

    def show(self, label: str) -> None:
        self._text.value = label
        self._age = 0.0
        self._live = True

    def update(self, dt: float) -> None:
        if not self._live:
            return
        self._age += dt
        if self._age >= self._duration:
            self._live = False

    def draw(self, x: float, y: float) -> None:
        if not self._live:
            return
        remaining = self._duration - self._age
        fade_for = self._duration * SELECT_HINT_FADE
        alpha = 255
        if remaining < fade_for:
            alpha = max(0, int(255 * remaining / max(fade_for, 1e-6)))
        r, g, b = LABEL_COLOR[:3]
        self._text.color = (r, g, b, alpha)
        self._text.x = x
        self._text.y = y
        self._text.draw()
